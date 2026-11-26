'''Local shutdown coordination. Never terminates a Provider or releases its lease.'''
import asyncio
from collections import deque
import hashlib
import hmac
import logging
import math
import os
import re
from threading import Condition, Event, RLock, Thread, enumerate as enumerate_threads
import time
import uuid
import httpx

from .recovery import Recovery, RecoveryEvidenceError, canonical, owner_dead


def shutdown_limits():
    defaults = {'total': ('GEOTOOL_TEAM_SHUTDOWN_TIMEOUT', 20),
                'model': ('GEOTOOL_TEAM_MODEL_DRAIN_TIMEOUT', 10),
                'callback': ('GEOTOOL_TEAM_SHUTDOWN_CALLBACK_TIMEOUT', 1),
                'final': ('GEOTOOL_TEAM_SHUTDOWN_FINAL_TIMEOUT', 3),
                'http': ('GEOTOOL_TEAM_HTTP_DRAIN_TIMEOUT', 3)}
    result = {}
    for key, (name, default) in defaults.items():
        value = float(os.environ.get(name, default))
        if not math.isfinite(value) or not 0.05 <= value <= 120:
            raise ValueError(name + ' must be finite and between 0.05 and 120 seconds')
        result[key] = value
    return result


class ModelResources:
    '''Small signed execution receipts, including calls with no SQLite run.'''
    def __init__(self, recovery):
        self.recovery = recovery
        self.directory = recovery.directory / 'model-resources'
        self.initialized = False
        self.scan_complete = False
        self.iterator = None
        self.unresolved = {}
        self.quarantined = {}
        self.reserve_slots = None
        self.refresh = 0
        self.error_type = None
        self.lock = RLock()

    def _initialize(self):
        if not self.initialized:
            if self.recovery.identity is None or self.recovery.fd is None:
                raise RecoveryEvidenceError('Model resource ledger requires broker ownership')
            Recovery._private_directory(self.directory)
            self.initialized = True

    def _path(self, call_id):
        if not isinstance(call_id, str) or not re.fullmatch('[a-f0-9]{32}', call_id):
            raise RecoveryEvidenceError('Invalid model resource identity')
        return self.directory / (call_id + '.json')

    def write(self, record, phase):
        with self.lock:
            self._initialize()
            identity = self.recovery.identity
            data = {'format': 1, 'type': 'model_resource', 'call_id': record['id'],
                    'deployment': identity['deployment'], 'binding': identity['binding'],
                    'owner': self.recovery.owner, 'scope': record.get('scope', self.recovery.scope),
                    'uid': record['uid'], 'run_id': record['run_id'],
                    'resource_type': record['resource_type'], 'phase': phase,
                    'completion': record.get('completion', 'unknown')}
            mac = hmac.new(bytes.fromhex(identity['key']), canonical(data), hashlib.sha256).hexdigest()
            self.recovery._atomic(self.directory, self._path(record['id']).name, {'data': data, 'mac': mac})

    def _inspect(self, call_id):
        try:
            identity = self.recovery.identity
            box = Recovery._read(self._path(call_id), 8192)
            data = box['data']
            mac = hmac.new(bytes.fromhex(identity['key']), canonical(data), hashlib.sha256).hexdigest()
            if (not isinstance(box.get('mac'), str) or not hmac.compare_digest(mac, box['mac'])
                    or data.get('format') != 1 or data.get('type') != 'model_resource'
                    or data.get('call_id') != call_id or data.get('deployment') != identity['deployment']
                    or data.get('binding') != identity['binding']
                    or data.get('phase') not in ('in_flight', 'settled')):
                raise RecoveryEvidenceError('Invalid model resource receipt')
            resolved = data['phase'] == 'settled' and data.get('completion') in ('provider_returned_complete', 'not_started', 'cleanup_verified', 'trusted_function_returned')
            if (resolved or data.get('owner') == self.recovery.owner
                    or (data.get('scope') == 'broker_process' and owner_dead(data.get('owner')) is True)):
                self.unresolved.pop(call_id, None)
            elif (self.reserve_slots is not None and data.get('scope') == 'external_unknown'
                  and data['phase'] == 'settled' and data.get('resource_type') == 'task_model'
                  and data.get('completion') == 'unknown' and isinstance(data.get('run_id'), str)
                  and isinstance(data.get('uid'), str)
                  and owner_dead(data.get('owner')) is True
                  and self._terminal_task(data)
                  and (call_id in self.quarantined or self.reserve_slots())):
                self.quarantined[call_id] = {'reason_code': 'terminal_task_provider_completion_unverified',
                                             'run_id': data['run_id']}
                self.unresolved.pop(call_id, None)
            else:
                self.unresolved[call_id] = {'resource_type': data.get('resource_type'),
                    'run_id': data.get('run_id'), 'reason_code': 'previous_model_execution_unverified'}
        except Exception as exc:
            self.unresolved[call_id] = {'resource_type': 'model', 'run_id': None,
                'reason_code': 'invalid_model_evidence_' + type(exc).__name__}

    def _terminal_task(self, data):
        try:
            run = self.recovery.store.run(data['uid'], data['run_id'])
        except KeyError:
            return False
        return run['status'] in {'failed', 'interrupted', 'stopped', 'completed'} and run['finished_at'] is not None

    def scan_step(self):
        with self.lock:
            try:
                self._initialize()
                if self.scan_complete:
                    keys = list(self.unresolved)
                    for _ in range(min(4, len(keys))):
                        key = keys[self.refresh % len(keys)]
                        self.refresh += 1
                        if re.fullmatch('[a-f0-9]{32}', key):
                            self._inspect(key)
                    self.error_type = None
                    return not self.unresolved
                if self.iterator is None:
                    self.iterator = os.scandir(self.directory)
                for _ in range(4):
                    entry = next(self.iterator, None)
                    if entry is None:
                        self.iterator.close()
                        self.iterator = None
                        self.scan_complete = True
                        break
                    if re.fullmatch('[a-f0-9]{32}\\.json', entry.name):
                        self._inspect(entry.name[:-5])
                    elif not entry.name.startswith('.tmp-'):
                        self.unresolved['invalid_name'] = {'reason_code': 'invalid_model_record_name'}
                self.error_type = None
                return self.scan_complete and not self.unresolved
            except Exception as exc:
                self.error_type = type(exc).__name__
                raise

    def snapshot(self):
        with self.lock:
            return {'ready': self.scan_complete and not self.unresolved and self.error_type is None,
                    'scan_complete': self.scan_complete, 'error_type': self.error_type,
                    'unresolved': {k: dict(v) for k, v in self.unresolved.items()},
                    'quarantined_slots': len(self.quarantined)}


class ShutdownCoordinator:
    def __init__(self, recovery):
        self.recovery = recovery
        self.resources = ModelResources(recovery)
        self.condition = Condition(RLock())
        self.limits = shutdown_limits()
        self.models = {}
        self.unverified_model_ends = {}
        self.model_history = deque(maxlen=256)
        self.workers = {}
        self.worker_history = deque(maxlen=256)
        self.external_work_seen = False
        self.external_run_ids = set()
        self.process_resources = None
        self.operations = {}
        self.history = deque(maxlen=512)
        self.callbacks = {}
        self.references = 0
        self.admission_closed = False
        self.requested_at = None
        self.deadline = None
        self.shutdown_id = None
        self.phase = 'RUNNING'
        self.done = Event()
        self.thread = None
        self.errors = []
        self.unresolved = []
        self.configuration = None
        self.coordinator_stopped = False
        self.pending_recoverable = False
        self.sqlite_closed = False
        self.returned_at = None
        self._request_stamp = {}
        self.memory_workers = []
        self.memory_observation_error = None
        self.sqlite_close_deferred = None

    def configure(self, *, reconciler, memory_close, memory_thread, clear_settings, cleanup_worker,
                  coordinate, preserve_pending, sqlite_close):
        self.configuration = locals().copy()
        self.configuration.pop('self')

    def _event(self, kind, **fields):
        with self.condition:
            self.history.append({'time': time.monotonic(), 'kind': kind, **fields})
            self.condition.notify_all()

    def _phase(self, phase):
        with self.condition:
            self.phase = phase
        self._event('phase', phase=phase)

    def close_admission(self, reason='lifespan'):
        # Used by the owned Uvicorn signal hook: no callback, IO, join or lock.
        self.admission_closed = True
        # setdefault is a single operation under the pinned CPython 3.12 GIL.
        # No lock acquisition in a signal handler; concurrent callers share a stamp.
        self.requested_at = self._request_stamp.setdefault('time', time.monotonic())
        self.deadline = self.requested_at + self.limits['total']
        if self.phase == 'RUNNING':
            self.phase = 'ADMISSION_CLOSED'

    def require_admission(self):
        if self.admission_closed:
            from fastapi import HTTPException
            raise HTTPException(503, 'Service shutdown has closed task and model admission')

    def enter(self):
        with self.condition:
            if self.references == 0 and self.admission_closed:
                if not self.done.is_set() or self.unresolved or not self._local_ended():
                    raise RuntimeError('Previous shutdown has unresolved local resources')
                self.admission_closed = False
                self.requested_at = self.deadline = self.shutdown_id = None
                self.phase = 'RUNNING'
                self.done = Event()
                self.thread = None
                self.errors = []
                self.operations = {}
                self.workers = {}
                self.coordinator_stopped = False
                self.pending_recoverable = False
                self.returned_at = None
                self._request_stamp = {}
            self.references += 1
            return self.references == 1

    def leave(self):
        with self.condition:
            self.references = max(0, self.references - 1)
            return self.references == 0

    def model_registered(self, resource_type, cancel, *, uid=None, run_id=None):
        with self.condition:
            self.require_admission()
            record = {'id': uuid.uuid4().hex, 'resource_type': resource_type, 'uid': uid,
                      'run_id': run_id, 'cancel': cancel, 'created': time.monotonic(),
                      'started': None, 'ended': None, 'lease_released': False,
                      'cancellation_requested': False, 'error_type': None, 'completion': 'not_started', 'done': Event()}
            self.models[record['id']] = record
        try:
            self.resources.write(record, 'in_flight')
        except BaseException:
            self.model_finished(record, lease_released=False)
            raise
        self._event('model_registered', model_call_id=record['id'], resource_type=resource_type, run_id=run_id)
        return record

    def model_started(self, record):
        with self.condition:
            if self.admission_closed:
                from .isolation import Cancelled
                raise Cancelled('Service shutdown prevented a new Provider call')
            record['started'] = time.monotonic()
            record['completion'] = 'unknown'
        self._event('model_started', model_call_id=record['id'])

    def model_finished(self, record, *, lease_released):
        with self.condition:
            if record['done'].is_set():
                return
            record['ended'] = time.monotonic()
            record['lease_released'] = lease_released
            if record.get('cleanup_error_type'):
                record['completion'] = 'unknown'
            if self.recovery.scope != 'broker_process' and record['completion'] not in ('provider_returned_complete', 'not_started', 'trusted_function_returned'):
                self.unverified_model_ends[record['id']] = {'resource_type': record['resource_type'],
                    'model_call_id': record['id'], 'run_id': record['run_id'],
                    'reason_code': 'local_call_ended_remote_termination_unverified_B4C'}
        try:
            self.resources.write(record, 'settled')
        except Exception as exc:
            record['error_type'] = type(exc).__name__
            logging.getLogger(__name__).warning('Model resource evidence retained: call=%s error_type=%s',
                                               record['id'], type(exc).__name__)
        with self.condition:
            record['done'].set()
            self.models.pop(record['id'], None)
            self.model_history.append(self._model_view(record))
            self.condition.notify_all()
        self._event('model_finished', model_call_id=record['id'], lease_released=lease_released)

    @staticmethod
    def _model_view(record):
        return {k: record.get(k) for k in ['id', 'resource_type', 'uid', 'run_id', 'created',
                    'started', 'ended', 'lease_released', 'cancellation_requested', 'error_type', 'completion', 'cleanup_error_type']} | {
                        'actually_ended': record['ended'] is not None,
                        'bookkeeping_complete': record['done'].is_set()}

    def track_worker(self, rid, uid, cancel, thread, startup):
        with self.condition:
            for key, previous in list(self.workers.items()):
                if self._worker_ended(previous):
                    self.worker_history.append({'run_id': key, 'actually_ended': True})
                    self.workers.pop(key)
            self.workers[rid] = {'id': rid, 'uid': uid, 'cancel': cancel, 'thread': thread,
                                 'startup': startup, 'handoff_pending': True}

    def execution_authorized(self, rid):
        # A failed Thread.start/initialization is not evidence of external work.
        with self.condition:
            self.external_work_seen = self.external_work_seen or self.recovery.scope != 'broker_process'
            if self.recovery.scope != 'broker_process':
                self.external_run_ids.add(rid)
        self._event('worker_execution_authorized', run_id=rid)

    def handoff_finished(self, rid):
        with self.condition:
            if rid in self.workers:
                self.workers[rid]['handoff_pending'] = False
            self.condition.notify_all()

    def register_cleanup(self, resource_id, callback):
        '''Trusted in-process hooks only. No HTTP registration or process discovery.'''
        with self.condition:
            self.require_admission()
            if resource_id in self.callbacks:
                raise ValueError('Cleanup identity already registered')
            record = {'id': uuid.uuid4().hex, 'uid': None, 'run_id': None,
                      'resource_type': 'cleanup_callback', 'scope': 'external_unknown'}
            item = {'callback': callback, 'record': record, 'verified': False}
            self.callbacks[resource_id] = item
        self.resources.write(record, 'in_flight')

    def _cleanup_callback(self, item):
        value = item['callback']()
        if isinstance(value, dict) and value.get('cleanup_verified') is True:
            item['record']['completion'] = 'cleanup_verified'
            self.resources.write(item['record'], 'settled')
            item['verified'] = True
        return item['verified']

    def _operation(self, object_id, stage, callback):
        key = (stage, object_id)
        with self.condition:
            if key in self.operations:
                return self.operations[key]
            record = {'object_id': object_id, 'stage': stage, 'started': None, 'ended': None,
                      'error_type': None, 'timed_out': False, 'done': Event(), 'thread': None,
                      'value': None}
            self.operations[key] = record
        def invoke_callback():
            record['started'] = time.monotonic()
            try:
                record['value'] = callback()
            except BaseException as exc:
                record['error_type'] = type(exc).__name__
                self._event('callback_error', object_id=object_id, stage=stage, error_type=type(exc).__name__)
            finally:
                record['ended'] = time.monotonic()
                record['done'].set()
                with self.condition:
                    self.condition.notify_all()
        try:
            thread = Thread(target=invoke_callback, name='shutdown-' + stage, daemon=False)
            record['thread'] = thread
            thread.start()
        except BaseException as exc:
            record['error_type'] = type(exc).__name__
            record['done'].set()
            self._event('callback_dispatch_error', object_id=object_id, stage=stage,
                        error_type=type(exc).__name__)
        return record

    def _wait_operations(self, records, deadline):
        with self.condition:
            while any(not row['done'].is_set() for row in records):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.condition.wait(min(0.05, remaining))
        for row in records:
            if not row['done'].is_set():
                row['timed_out'] = True

    def _bounded(self, object_id, stage, callback, budget):
        row = self._operation(object_id, stage, callback)
        self._wait_operations([row], min(self.deadline, time.monotonic() + max(0, budget)))
        return row

    @staticmethod
    def _worker_ended(record):
        return not record['handoff_pending'] and not record['thread'].is_alive()

    def _local_ended(self):
        return (not self.models and all(self._worker_ended(row) for row in self.workers.values())
                and all(row['done'].is_set() for row in self.operations.values())
                and all(item['verified'] for item in self.callbacks.values())
                and (self.process_resources is None or self.process_resources.all_ended(self.external_run_ids))
                and self._memory_ended())

    def _memory_ended(self):
        try:
            worker = self.configuration['memory_thread']()
            if worker is not None and worker not in self.memory_workers:
                self.memory_workers.append(worker)
            return not any(worker.is_alive() for worker in self.memory_workers)
        except BaseException as exc:
            self.memory_observation_error = type(exc).__name__
            return False

    def begin(self, reason='lifespan'):
        self.close_admission(reason)
        with self.condition:
            if self.thread is not None or self.done.is_set():
                return self.shutdown_id
            self.shutdown_id = uuid.uuid4().hex
            try:
                self.thread = Thread(target=self._run, name='shutdown-orchestration', daemon=False)
                self.thread.start()
            except BaseException as exc:
                self.errors.append({'object_id': 'orchestration', 'stage': self.phase,
                                    'error_type': type(exc).__name__})
                self.unresolved = [{'resource_type': 'orchestration', 'reason_code': 'thread_start_failed'}]
                self.phase = 'UNRESOLVED_RESOURCES'
                self.done.set()
            return self.shutdown_id

    def _run(self):
        try:
            self._orchestrate()
        except BaseException as exc:
            self.errors.append({'object_id': 'orchestration', 'stage': self.phase,
                                'error_type': type(exc).__name__})
            self.unresolved.append({'resource_type': 'orchestration', 'reason_code': 'unexpected_error'})
            self._phase('UNRESOLVED_RESOURCES')
        finally:
            self.returned_at = time.monotonic()
            self.done.set()
            with self.condition:
                self.condition.notify_all()
            logging.getLogger(__name__).info('Shutdown orchestration returned: shutdown=%s phase=%s unresolved=%s',
                                            self.shutdown_id, self.phase, len(self.unresolved))

    def _orchestrate(self):
        cfg = self.configuration
        if cfg is None:
            raise RuntimeError('Shutdown dependencies not configured')
        with self.condition:
            workers, models = list(self.workers.values()), list(self.models.values())
            callbacks = list(self.callbacks.items())
        self._phase('CANCELLATION_REQUESTED')
        requests = []
        for row in workers:
            if not self._worker_ended(row):
                requests.append(self._operation(row['id'], 'cancel_task', row['cancel'].set))
        for row in models:
            def request(row=row):
                row['cancel'].set()
                row['cancellation_requested'] = True
            requests.append(self._operation(row['id'], 'cancel_model', request))
        # Submit all independent opportunities before waiting for any one callback.
        for row in workers:
            requests.append(self._operation(row['id'], 'cleanup_worker', lambda row=row: cfg['cleanup_worker'](row)))
        for key, item in callbacks:
            requests.append(self._operation(key, 'external_callback', lambda item=item: self._cleanup_callback(item)))
        if self.process_resources is not None:
            requests.append(self._operation('managed_trusted_processes', 'cleanup_processes', self.process_resources.stop_all))
        memory = self._operation('memory', 'close_memory', cfg['memory_close'])
        self._wait_operations(requests, min(self.deadline, time.monotonic() + self.limits['callback']))
        self._phase('DRAINING')
        model_deadline = min(self.deadline - self.limits['final'], time.monotonic() + self.limits['model'])
        with self.condition:
            while (any(not row['done'].is_set() for row in models)
                   or any(not self._worker_ended(row) for row in workers)
                   or not self._memory_ended()):
                remaining = model_deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.condition.wait(min(0.05, remaining))
        self._phase('FINAL_COORDINATION')
        self._bounded('pending', 'coordinate', cfg['coordinate'], self.limits['final'])
        self._phase('DEPENDENCIES_CLOSING')
        self._wait_operations([memory], min(self.deadline, time.monotonic() + self.limits['callback']))
        self._bounded('model_settings', 'clear_settings', cfg['clear_settings'], self.limits['callback'])
        rec = cfg['reconciler']
        close = self._bounded('reconciler', 'close_reconciler',
                              lambda: rec.close(timeout=max(0, self.deadline - time.monotonic())),
                              max(0, self.deadline - time.monotonic()))
        self.coordinator_stopped = bool(close['done'].is_set() and close['error_type'] is None
                                       and (rec.thread is None or not rec.thread.is_alive()))
        if self.coordinator_stopped and all(self._worker_ended(row) for row in workers):
            saved = self._bounded('pending', 'preserve_pending', cfg['preserve_pending'],
                                  max(0, self.deadline - time.monotonic()))
            self.pending_recoverable = bool(saved['done'].is_set() and saved['error_type'] is None and saved['value'])
        unresolved = []
        if not self._memory_ended():
            unresolved.append({'resource_type': 'memory_worker', 'reason_code': 'memory_database_user_not_ended',
                               'error_type': self.memory_observation_error})
        for row in workers:
            if not self._worker_ended(row):
                unresolved.append({'resource_type': 'worker', 'run_id': row['id'], 'reason_code': 'worker_not_ended'})
        for row in models:
            if not row['done'].is_set() or row['error_type']:
                unresolved.append({'resource_type': row['resource_type'], 'model_call_id': row['id'],
                    'run_id': row['run_id'], 'reason_code': ('model_resource_bookkeeping_pending' if row['ended'] is not None else 'model_not_ended') if not row['done'].is_set() else 'settled_evidence_failed'})
        for row in self.operations.values():
            if row['error_type'] or not row['done'].is_set():
                unresolved.append({'resource_type': 'callback', 'object_id': row['object_id'],
                                   'stage': row['stage'], 'reason_code': row['error_type'] or 'callback_not_ended'})
        for key, item in callbacks:
            if not item['verified']:
                unresolved.append({'resource_type': 'cleanup_callback', 'object_id': key,
                    'resource_id': item['record']['id'], 'reason_code': 'cleanup_not_verified_B4B2'})
        if not self.coordinator_stopped:
            unresolved.append({'resource_type': 'reconciler', 'reason_code': 'stop_not_confirmed'})
        if not self.pending_recoverable:
            unresolved.append({'resource_type': 'pending', 'reason_code': 'durable_preservation_not_confirmed'})
        if self.external_work_seen and not (self.process_resources is not None
                and self.process_resources.all_ended(self.external_run_ids)):
            unresolved.append({'resource_type': 'external_tools', 'reason_code': 'cleanup_not_verified_B4B2'})
        self.unresolved = unresolved
        self.unresolved.extend(dict(value) for value in self.unverified_model_ends.values())
        if self.coordinator_stopped and self.pending_recoverable and self._local_ended():
            closed = self._bounded('recovery', 'release_fence', self.recovery.close, self.limits['callback'])
            if closed['error_type'] or not closed['done'].is_set():
                self.unresolved.append({'resource_type': 'recovery_fence', 'reason_code': 'release_not_confirmed'})
        self._phase('UNRESOLVED_RESOURCES' if self.unresolved else 'CLOSED')

    async def wait(self):
        self.begin()
        # Never enqueue this wait behind potentially stuck default-executor probes.
        while not self.done.is_set() and time.monotonic() < self.deadline:
            await asyncio.sleep(min(0.02, max(0, self.deadline - time.monotonic())))
        return self.snapshot()

    def close_store(self):
        '''Only the owning CLI calls this after Uvicorn has stopped HTTP work.'''
        with self.condition:
            safe = self.done.is_set() and self.coordinator_stopped and self.pending_recoverable and self._local_ended()
            if self.sqlite_closed:
                return True
        if not safe:
            self.sqlite_close_deferred = 'Local database dependencies have not ended'
            return False
        # The installed AnyIO runtime stops a worker's queue, not its running
        # function. Do not close a shared DB beneath a still-live HTTP worker.
        if any(worker.name == 'AnyIO worker thread' and worker.is_alive() for worker in enumerate_threads()):
            self.sqlite_close_deferred = 'HTTP worker lifetime has not ended'
            return False
        self.configuration['sqlite_close']()
        self.sqlite_closed = True
        self.sqlite_close_deferred = None
        self._event('sqlite_closed')
        return True

    def snapshot(self):
        with self.condition:
            operations = [{k: row[k] for k in ['object_id', 'stage', 'started', 'ended', 'error_type', 'timed_out']}
                          | {'actually_ended': row['ended'] is not None,
                             'dispatch_finished': row['done'].is_set(), 'non_daemon_helper': True}
                          for row in self.operations.values()]
            overdue = self.deadline is not None and time.monotonic() >= self.deadline and not self.done.is_set()
            unresolved = list(self.unresolved)
            if overdue:
                unresolved.append({'resource_type': 'orchestration', 'reason_code': 'deadline_reached_work_still_tracked'})
            return {'shutdown_id': self.shutdown_id, 'phase': 'DRAIN_TIMEOUT' if overdue else self.phase,
                    'current_stage': self.phase,
                    'admission_closed': self.admission_closed, 'requested_at': self.requested_at,
                    'deadline': self.deadline, 'elapsed_seconds': max(0, (self.returned_at or time.monotonic()) - self.requested_at) if self.requested_at else 0,
                    'orchestration_returned': self.done.is_set(), 'limits': dict(self.limits),
                    'models': [self._model_view(row) for row in self.models.values()],
                    'recent_models': list(self.model_history), 'operations': operations,
                    'unverified_model_ends': list(self.unverified_model_ends.values()),
                    'workers': [{'run_id': row['id'], 'actually_ended': self._worker_ended(row),
                                 'handoff_pending': row['handoff_pending']} for row in self.workers.values()],
                    'recent_workers': list(self.worker_history),
                    'external_work_seen': self.external_work_seen,
                    'memory_workers': [{'ident': worker.ident, 'name': worker.name,
                                        'daemon': worker.daemon, 'is_alive': worker.is_alive()}
                                       for worker in self.memory_workers],
                    'errors': list(self.errors) + [{'object_id': row['object_id'], 'stage': row['stage'], 'error_type': row['error_type']} for row in self.operations.values() if row['error_type']], 'unresolved': unresolved,
                    'callback_resources': [{'object_id': key, 'resource_id': item['record']['id'], 'cleanup_verified': item['verified']} for key, item in self.callbacks.items()],
                    'coordinator_stopped': self.coordinator_stopped, 'pending_recoverable': self.pending_recoverable,
                    'sqlite_closed': self.sqlite_closed, 'process_exit_confirmed': False,
                    'sqlite_close_deferred': self.sqlite_close_deferred,
                    'external_tool_cleanup_verified': False, 'forced_provider_termination': False}


def observed_model_client(client, record):
    '''Observe complete responses, including fully read request rejections.'''
    def rejected(exc):
        # A drained synchronous request rejection is a completed transport,
        # although the task still fails. Timeouts, interrupted streams and
        # server errors remain unknown; closing a socket alone proves nothing.
        response = exc.response
        if (response.status_code in (400, 401, 403, 404, 405, 413, 415, 422, 429)
                and response.is_stream_consumed and response.is_closed):
            record['completion'] = 'provider_returned_complete'

    class View:
        def __getattr__(self, name):
            value = getattr(client, name)
            if name == 'invoke':
                def invoke(*args, **kwargs):
                    record['completion'] = 'unknown'
                    try:
                        result = value(*args, **kwargs)
                    except httpx.HTTPStatusError as exc:
                        rejected(exc)
                        raise
                    record['completion'] = 'provider_returned_complete'
                    return result
                return invoke
            if name == 'stream':
                def stream(*args, **kwargs):
                    record['completion'] = 'unknown'
                    try:
                        for item in value(*args, **kwargs):
                            yield item
                    except httpx.HTTPStatusError as exc:
                        rejected(exc)
                        raise
                    record['completion'] = 'provider_returned_complete'
                return stream
            return value
    return View()


def lifecycle_server(config, app):
    '''Use the existing Uvicorn server with an early application admission fence.'''
    import uvicorn
    class LifecycleServer(uvicorn.Server):
        def handle_exit(self, sig, frame):
            app.state.shutdown.close_admission('signal')
            super().handle_exit(sig, frame)

        async def shutdown(self, sockets=None):
            owner = app.state.shutdown
            owner.begin('uvicorn')
            remaining = max(0, owner.deadline - time.monotonic())
            configured = self.config.timeout_graceful_shutdown
            self.config.timeout_graceful_shutdown = min(owner.limits['http'], remaining,
                                                       configured if configured is not None else remaining)
            await super().shutdown(sockets=sockets)
    return LifecycleServer(config)

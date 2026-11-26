"""Trusted worker ownership; persistence and scheduling belong to Recovery/B3."""
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import sys
from threading import Lock, RLock
import time
import uuid

from .process_cgroup import CgroupRoot
from .process_identity import ProcessHandle, observe, same
from .recovery import Recovery, RecoveryEvidenceError, TERMINAL, canonical, owner_dead


def limits():
    defaults = {'term': .4, 'escalation': 1., 'empty': 1., 'persistence': 1., 'launch': 5.}
    result = {key: float(os.environ.get('GEOTOOL_PROCESS_' + key.upper() + '_TIMEOUT', value)) for key, value in defaults.items()}
    if any(not math.isfinite(v) or not .05 <= v <= 30 for v in result.values()):
        raise ValueError('Process cleanup limits must be finite and within .05 to 30 seconds')
    return result


class ProcessOwnership:
    def __init__(self, recovery, root):
        self.recovery = recovery
        self.root_path = root
        self.root = None
        self.directory = recovery.directory / 'process-resources'
        self.limits = limits()
        self.lock = RLock()
        self.live = {}
        self.known = set()
        self.errors = {}
        self.iterator = None
        self.scan_complete = False
        self.refresh = 0

    def initialize(self):
        with self.lock:
            if self.root is None:
                if self.recovery.identity is None or self.recovery.fd is None:
                    raise RecoveryEvidenceError('Process ownership requires the active broker fence')
                self.root = CgroupRoot(self.root_path)
                Recovery._private_directory(self.directory)

    def _path(self, execution):
        if not isinstance(execution, str) or not re.fullmatch('[a-f0-9]{32}', execution):
            raise RecoveryEvidenceError('Invalid execution resource identity')
        return self.directory / (execution + '.json')

    def _write(self, data):
        identity = self.recovery.identity
        payload = {**data, 'format': 1, 'type': 'trusted_process',
                   'deployment': identity['deployment'], 'binding': identity['binding']}
        mac = hmac.new(bytes.fromhex(identity['key']), canonical(payload), hashlib.sha256).hexdigest()
        self.recovery._atomic(self.directory, self._path(payload['execution_id']).name, {'data': payload, 'mac': mac})
        return payload

    def load(self, execution):
        box = Recovery._read(self._path(execution), 1024 * 1024)
        data, identity = box['data'], self.recovery.identity
        mac = hmac.new(bytes.fromhex(identity['key']), canonical(data), hashlib.sha256).hexdigest()
        if (not isinstance(box.get('mac'), str) or not hmac.compare_digest(box['mac'], mac)
                or data.get('format') != 1 or data.get('type') != 'trusted_process'
                or data.get('deployment') != identity['deployment'] or data.get('binding') != identity['binding']
                or data.get('execution_id') != execution or not re.fullmatch('[a-f0-9]{32}', data.get('run_id', ''))
                or not data.get('uid') or not data.get('cid') or not data.get('run_created')
                or data.get('coverage') not in ('trusted_worker_only', 'sandbox_tool')):
            raise RecoveryEvidenceError('Invalid process ownership evidence')
        return data

    def _run_binding(self, data, *, require_link=True):
        row = self.recovery.store.run(data['uid'], data['run_id'])
        run = self.recovery._load(data['run_id'])
        if (row['cid'] != data['cid'] or row['created'] != data['run_created']
                or run['uid'] != data['uid'] or run['cid'] != data['cid'] or run['owner'] != data['owner']
                or (require_link and not self._linked(run, data))):
            raise RecoveryEvidenceError('Process resource belongs to another run')
        return run, row

    @staticmethod
    def _linked(run, data):
        if data['coverage'] == 'trusted_worker_only':
            return run.get('process_execution') == data['execution_id']
        return (run.get('process_coverage') == 'sandbox_tools_v1'
                and run.get('process_executions', {}).get(data['execution_id']) == data['tool_invocation_id'])

    def _link(self, data):
        with self.recovery.ownership_lock:
            return self._link_locked(data)

    def _link_locked(self, data):
        run, _ = self._run_binding(data, require_link=False)
        if data['coverage'] == 'sandbox_tool':
            if (run['owner'] != self.recovery.owner or run.get('process_coverage') != 'sandbox_tools_v1'
                    or run.get('process_registration_closed') is not False):
                raise RecoveryEvidenceError('Sandbox tool registration is closed')
            executions = dict(run['process_executions'])
            if data['tool_invocation_id'] in executions.values() and executions.get(data['execution_id']) != data['tool_invocation_id']:
                raise RecoveryEvidenceError('Tool invocation cannot be replayed')
            executions[data['execution_id']] = data['tool_invocation_id']
            self.recovery.current[data['run_id']] = self.recovery._write({**run, 'process_executions': executions})
            return
        if run.get('process_execution') not in (None, data['execution_id']):
            raise RecoveryEvidenceError('Run already has another execution identity')
        if run.get('process_execution') is None:
            if run['owner'] != self.recovery.owner:
                raise RecoveryEvidenceError('Cannot invent a cold run ownership link')
            self.recovery.current[data['run_id']] = self.recovery._write({**run,
                'process_execution': data['execution_id'], 'process_coverage': 'trusted_worker_only'})

    def prepare(self, uid, cid, rid, *, local_scope_certified=False, tool_invocation_id=None):
        # Serialize one-to-many journal registration, including concurrent calls.
        # The same manager, fence, signer, launch and cleanup are reused.
        with self.recovery.ownership_lock:
            return self._prepare(uid, cid, rid, local_scope_certified=local_scope_certified,
                                 tool_invocation_id=tool_invocation_id)

    def begin_sandbox(self, uid, cid, rid):
        self.initialize()
        with self.recovery.ownership_lock:
            run = self.recovery._load(rid)
            row = self.recovery.store.run(uid, rid)
            if (run['owner'] != self.recovery.owner or run['uid'] != uid or run['cid'] != cid
                    or row['cid'] != cid or run['phase'] != 'authorized'
                    or run.get('process_execution') or run.get('process_coverage')):
                raise RecoveryEvidenceError('Sandbox run authorization mismatch')
            self.recovery.current[rid] = self.recovery._write({**run, 'process_coverage': 'sandbox_tools_v1',
                'process_executions': {}, 'process_registration_closed': False})

    def close_sandbox(self, uid, rid):
        with self.recovery.ownership_lock:
            run = self.recovery._load(rid)
            if run['owner'] != self.recovery.owner or run['uid'] != uid or run.get('process_coverage') != 'sandbox_tools_v1':
                raise RecoveryEvidenceError('Sandbox registration ownership mismatch')
            self.recovery.current[rid] = self.recovery._write({**run, 'process_registration_closed': True})

    def bind_tool_context(self, execution, core_run_id):
        if not isinstance(core_run_id, str) or not re.fullmatch('[a-f0-9]{32}', core_run_id):
            raise RecoveryEvidenceError('Invalid native Agent run identity')
        live = self._live(execution)
        with live['lock']:
            data = self.load(execution);self._run_binding(data)
            if data['coverage'] != 'sandbox_tool' or data['phase'] != 'PREPARING' or data['launch_possible']:
                raise RecoveryEvidenceError('Tool context cannot change after launch')
            self._write({**data, 'core_run_id': core_run_id})

    def _prepare(self, uid, cid, rid, *, local_scope_certified=False, tool_invocation_id=None):
        self.initialize()
        run = self.recovery._load(rid)
        row = self.recovery.store.run(uid, rid)
        if (run['owner'] != self.recovery.owner or run['uid'] != uid or run['cid'] != cid
                or row['cid'] != cid or run['phase'] != 'authorized' or run.get('process_execution')):
            raise RecoveryEvidenceError('Trusted process launch lacks authenticated authorization')
        execution = uuid.uuid4().hex
        sandbox = tool_invocation_id is not None
        if not sandbox and run.get('process_coverage'):
            raise RecoveryEvidenceError('A run cannot mix Trusted and Sandbox ownership')
        if sandbox and (not isinstance(tool_invocation_id, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', tool_invocation_id)
                or run.get('process_coverage') != 'sandbox_tools_v1' or run.get('process_registration_closed') is not False
                or tool_invocation_id in run['process_executions'].values()):
            raise RecoveryEvidenceError('Invalid or repeated ToolCall identity')
        data = {'execution_id': execution, 'run_id': rid, 'tool_invocation_id': tool_invocation_id if sandbox else 'trusted-run:' + execution,
                'uid': uid, 'cid': cid, 'run_created': row['created'], 'owner': self.recovery.owner,
                'coverage': 'sandbox_tool' if sandbox else 'trusted_worker_only', 'created_at': time.time(), 'phase': 'PREPARING',
                'local_scope_certified': local_scope_certified is True,
                'worker': None, 'cgroup': None, 'launch_possible': False, 'gate_authorized': False,
                'attempts': [], 'proof': None, 'terminal': None}
        with self.lock:
            self.known.add(execution)
            self.live[execution] = {'lock': Lock(), 'process': None, 'handle': None,
                                    'initial': data, 'record_committed': False, 'gate': None}
        live = self.live[execution]
        live['lock'].acquire()
        try:
            data = self._write(data)
            self.live[execution]['record_committed'] = True
            self._link(data)
            group = self.root.create(execution)
            live['created_cgroup'] = group
            data = self._write({**data, 'cgroup': group})
            return execution
        except BaseException as exc:
            self.errors[execution] = type(exc).__name__
            raise
        finally:
            live['lock'].release()

    def _live(self, execution):
        with self.lock:
            return self.live.setdefault(execution, {'lock': Lock(), 'process': None, 'handle': None, 'gate': None})

    def launch(self, execution, command, environment, diagnostics=None, cancel=None, *, stderr_pipe=False):
        if type(stderr_pipe) is not bool or (stderr_pipe and diagnostics is not None):
            raise ValueError("Invalid explicit process stderr transport")
        live = self._live(execution)
        child, diagnostic = None, None
        if not live['lock'].acquire(timeout=self.limits['launch']):
            raise RecoveryEvidenceError('Execution startup is already owned')
        try:
            data = self.load(execution)
            run, row = self._run_binding(data)
            if (data['phase'] != 'PREPARING' or data['launch_possible']
                    or data['owner'] != self.recovery.owner or live.get('launch_attempted')
                    or run['phase'] != 'authorized' or row['status'] not in ('running', 'stopping')):
                raise RecoveryEvidenceError('Execution startup cannot be replayed')
            live['launch_attempted'] = True
            parent, child = socket.socketpair()
            parent.settimeout(self.limits['launch'])
            live['gate'] = parent
            nonce = secrets.token_hex(32)
            data = self._write({**data, 'launch_possible': True})
            diagnostic = subprocess.PIPE if stderr_pipe else (open(diagnostics, 'ab', buffering=0) if diagnostics else subprocess.DEVNULL)
            try:
                try:
                    proc = subprocess.Popen([sys.executable, '-B', str(Path(__file__).with_name('process_bootstrap.py')),
                        str(child.fileno()), execution, nonce], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=diagnostic, env=environment, pass_fds=(child.fileno(),), close_fds=True,
                        start_new_session=True)
                except BaseException:
                    live['popen_failed'] = True
                    raise
                live['process'] = proc
                live['worker_identity'] = observe(proc.pid)
                data = self._write({**data, 'worker': live['worker_identity']})
            finally:
                child.close()
                if hasattr(diagnostic, 'close'):
                    diagnostic.close()
            handle = ProcessHandle(data['worker'])
            live['handle'] = handle
            ready = bytearray()
            while not ready.endswith(b'\n'):
                chunk = parent.recv(4096)
                if not chunk or len(ready) > 8192:
                    raise RecoveryEvidenceError('Bootstrap failed before authorization')
                ready.extend(chunk)
            if json.loads(ready) != {'ready': execution, 'nonce': nonce}:
                raise RecoveryEvidenceError('Bootstrap handshake identity mismatch')
            with self.root.open(execution, data['cgroup']) as group:
                group.attach(handle)
                group.require_member(proc.pid)
                data = self._write({**data, 'phase': 'ATTACHED', 'gate_authorized': True,
                                    'attached_at': time.time(), 'attached_observation': observe(proc.pid)})
            if cancel is not None and cancel.is_set():
                raise RecoveryEvidenceError('Cancellation denied payload authorization')
            parent.sendall((json.dumps({'go': execution, 'nonce': nonce, 'argv': command, 'env': environment}) + '\n').encode())
            parent.close(); live['gate'] = None
            self._write({**data, 'phase': 'RUNNING', 'running_at': time.time()})
            self.errors.pop(execution, None)
            return proc
        except BaseException as exc:
            self.errors[execution] = type(exc).__name__
            if live.get('gate') is not None:
                live['gate'].close(); live['gate'] = None
            raise
        finally:
            if child is not None:
                child.close()
            if hasattr(diagnostic, 'close'):
                diagnostic.close()
            live['lock'].release()

    def _recover_initial(self, execution, live):
        try:
            data = self.load(execution)
        except FileNotFoundError:
            if live.get('record_committed') is False and live.get('process') is None and live.get('initial'):
                # This instance knows Popen was never called. No cold inference or bad-MAC repair.
                data = self._write(live['initial'])
                live['record_committed'] = True
                self._link(data)
            else:
                raise
        updates = {}
        if data['owner'] == self.recovery.owner:
            if data['cgroup'] is None and live.get('created_cgroup'):
                updates['cgroup'] = live['created_cgroup']
            if data['worker'] is None and live.get('worker_identity'):
                updates['worker'] = live['worker_identity']
        return self._write({**data, **updates}) if updates else data

    def cleanup(self, execution, *, budget=None):
        self.initialize()
        live = self._live(execution)
        total = self.limits['term'] + self.limits['escalation'] + self.limits['empty'] + self.limits['persistence']
        deadline = time.monotonic() + (total if budget is None else min(total, max(0, budget)))
        if not live['lock'].acquire(timeout=max(0, deadline - time.monotonic())):
            return {'cleanup_verified': False, 'reason_code': 'cleanup_inflight'}
        try:
            data = self._recover_initial(execution, live)
            self._run_binding(data)
            if data['phase'] in ('ENDED', 'RELEASED'):
                if not self._physical_ended(data):
                    raise RecoveryEvidenceError('Invalid persisted termination proof')
                self.errors.pop(execution, None)
                return {'cleanup_verified': True, 'execution_id': execution}
            if live.get('gate') is not None:
                live['gate'].close(); live['gate'] = None
            started = time.time()
            attempts = list(data['attempts'][-31:])
            attempt = {'started_at': started, 'signals': [], 'escalated': False}
            attempts.append(attempt)
            data = self._write({**data, 'phase': 'STOPPING', 'attempts': attempts})
            proc, handle = live.get('process'), live.get('handle')
            if data['worker'] is not None:
                try:
                    current = observe(data['worker']['pid'])
                except (FileNotFoundError, ProcessLookupError):
                    current = None
                if current is not None and not same(data['worker'], current):
                    raise RecoveryEvidenceError('Original worker PID identity mismatch')
                if current is not None and current['state'] != 'Z':
                    if handle is None:
                        handle = ProcessHandle(data['worker']); live['handle'] = handle
                    handle.verify_fd()
            elif data['launch_possible'] and proc is None and not live.get('popen_failed'):
                raise RecoveryEvidenceError('Launch window has no trustworthy worker identity')
            never_started = not data['launch_possible'] or (proc is None and live.get('popen_failed') is True)
            if data['cgroup'] is None:
                if not never_started:
                    raise RecoveryEvidenceError('Execution has no dedicated containment proof')
                population = {'empty': True, 'groups': [], 'pids': [], 'reason': 'cgroup_not_created_payload_never_started'}
            else:
                with self.root.open(execution, data['cgroup']) as group:
                    snapshot = group.snapshot()
                    # A held gate makes a direct child outside the leaf safe to end with pidfd.
                    if handle is not None and not handle.exited() and not data['gate_authorized']:
                        if handle.send(signal.SIGTERM):
                            attempt['signals'].append({'pid': handle.expected['pid'], 'signal': 'SIGTERM', 'via': 'pidfd-gated-bootstrap'})
                    for pid in snapshot['pids']:
                        try:
                            actor = ProcessHandle(observe(pid))
                        except (FileNotFoundError, ProcessLookupError):
                            # An observed member can exit before pidfd_open.
                            # The unchanged final empty-cgroup/reap proof,not
                            # this exception,authorizes termination/release.
                            continue
                        try:
                            try:
                                group.require_member(pid)
                            except (FileNotFoundError, RecoveryEvidenceError):
                                if actor.exited():
                                    continue
                                raise
                            if actor.send(signal.SIGTERM):
                                attempt['signals'].append({'pid': pid, 'signal': 'SIGTERM', 'via': 'pidfd'})
                        finally:
                            actor.close()
                    grace = min(deadline, time.monotonic() + self.limits['term'])
                    while time.monotonic() < grace:
                        if group.snapshot()['empty'] and (handle is None or handle.exited()):
                            break
                        time.sleep(min(.01, max(0, grace - time.monotonic())))
                    if not group.snapshot()['empty']:
                        if time.monotonic() >= deadline:
                            raise TimeoutError('Cleanup budget exhausted before escalation')
                        group.kill(); attempt['escalated'] = True
                    if handle is not None and not handle.exited() and not data['gate_authorized']:
                        handle.send(signal.SIGKILL)
                    until = min(deadline, time.monotonic() + self.limits['escalation'] + self.limits['empty'])
                    while time.monotonic() < until:
                        if group.snapshot()['empty'] and (handle is None or handle.exited()):
                            break
                        time.sleep(min(.01, max(0, until - time.monotonic())))
                    population = group.snapshot()
                    if not population['empty'] or (handle is not None and not handle.exited()):
                        raise TimeoutError('Execution termination not independently confirmed')
            if proc is not None:
                proc.wait(timeout=max(.001, deadline - time.monotonic()))
                reaping = {'direct_child': True, 'waited': True, 'returncode': proc.returncode}
            elif data['worker'] is None and never_started:
                reaping = {'direct_child': False, 'waited': False, 'reason': 'not_started'}
            else:
                # Cold scanner is not the old process's parent. Never wait an unrelated PID.
                reaping = {'direct_child': False, 'waited': False, 'reason': 'old_parent_ended_system_reaper',
                           'old_owner_dead': owner_dead(data['owner']) is True}
                if not reaping['old_owner_dead']:
                    raise RecoveryEvidenceError('Original parent reaping responsibility is unresolved')
            if time.monotonic() >= deadline:
                raise TimeoutError('Cleanup proof persistence budget expired')
            proof = {'format': 1, 'execution_id': execution, 'run_id': data['run_id'],
                     'tool_invocation_id': data['tool_invocation_id'], 'boot_id': self.root.identity['boot_id'],
                     'worker': data['worker'], 'cgroup': data['cgroup'], 'started_at': started,
                     'completed_at': time.time(), 'term': attempt['signals'], 'escalated': attempt['escalated'],
                     'population': population, 'reaping': reaping, 'ended': True,
                     'never_started': never_started, 'callbacks_complete': True,
                     'terminal_reconciled': False}
            if data['coverage'] == 'sandbox_tool':
                proof['core_run_id'] = data.get('core_run_id')
            self._write({**data, 'phase': 'ENDED', 'attempts': attempts, 'proof': proof})
            self.errors.pop(execution, None)
            return {'cleanup_verified': True, 'execution_id': execution}
        except Exception as exc:
            self.errors[execution] = type(exc).__name__
            return {'cleanup_verified': False, 'execution_id': execution, 'reason_code': type(exc).__name__}
        finally:
            live['lock'].release()

    def _valid_proof(self, data):
        proof = data.get('proof')
        required = {'format','execution_id','run_id','tool_invocation_id','boot_id','worker','cgroup',
                    'started_at','completed_at','term','escalated','population','reaping','ended',
                    'never_started','callbacks_complete','terminal_reconciled'}
        return bool(isinstance(proof, dict) and required <= proof.keys()
            and proof.get('format') == 1 and proof.get('ended') is True
            and proof.get('execution_id') == data['execution_id'] and proof.get('run_id') == data['run_id']
            and proof.get('tool_invocation_id') == data['tool_invocation_id']
            and proof.get('worker') == data['worker'] and proof.get('cgroup') == data['cgroup']
            and proof.get('boot_id') == data['owner']['boot_id']
            and proof.get('population', {}).get('empty') is True and proof.get('callbacks_complete') is True
            and all(row.get('populated') == 0 and row.get('pids') == [] for row in proof['population'].get('groups', []))
            and (data['phase'] != 'RELEASED' or (proof.get('terminal_reconciled') is True and data.get('terminal') in TERMINAL))
            and (proof.get('reaping', {}).get('waited') is True
                 or proof.get('reaping', {}).get('old_owner_dead') is True
                 or proof.get('never_started') is True))

    def _physical_ended(self, data):
        if data['phase'] not in ('ENDED', 'RELEASED') or not self._valid_proof(data):
            return False
        if data['cgroup'] is None:
            return data['proof']['never_started']
        bound = data['cgroup']; prior_root = bound['root']
        if prior_root == self.root.identity:
            try:
                with self.root.open(data['execution_id'], bound) as group:
                    return group.snapshot()['empty']
            except FileNotFoundError:
                # Removal follows a durable RELEASED proof. Missing files while
                # a group still exists remain an observation failure.
                try:
                    Path(bound['path']).stat()
                except FileNotFoundError:
                    self.root.verify(prior_root)
                    return data['phase'] == 'RELEASED' and data['proof']['terminal_reconciled'] is True
                return False
        # A prior unit may have been collected after a fully committed release.
        # Absence is accepted only together with that complete authenticated end
        # and SQL proof. An active/unknown old record never gets this inference.
        path = Path(prior_root['path'])
        prefix = '/sys/fs/cgroup/user.slice/user-' + str(os.getuid()) + '.slice/user@' + str(os.getuid()) + '.service/'
        if (data['phase'] != 'RELEASED' or not data['proof']['terminal_reconciled']
                or not str(path).startswith(prefix) or '..' in path.parts
                or not re.fullmatch(r'oresage-p31b4b2b(?:1|2a|2b1)-[a-f0-9]{32}\.service', path.name)
                or bound['path'] != str(path / ('exec-' + data['execution_id']))):
            return False
        # A completed, authenticated cgroup proof belongs to one kernel boot.
        # A systemd unit may reuse the path after reboot, but local processes
        # from the recorded boot cannot occupy the replacement cgroup.
        prior_boot = prior_root.get('boot_id')
        current_boot = self.root.identity.get('boot_id')
        boot_id = r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}'
        if (isinstance(prior_boot, str) and isinstance(current_boot, str)
                and re.fullmatch(boot_id, prior_boot) and re.fullmatch(boot_id, current_boot)
                and prior_boot == data['owner']['boot_id'] and prior_boot != current_boot):
            return True
        try:
            path.stat()
        except FileNotFoundError:
            return True
        return False  # Incomparable still-existing delegation stays quarantined.

    def local_ended(self, run):
        try:
            if run.get('process_coverage') == 'sandbox_tools_v1':
                if not (run.get('process_registration_closed') is True or owner_dead(run['owner']) is True):
                    return False
                for key, invocation in run['process_executions'].items():
                    data = self.load(key)
                    self._run_binding(data)
                    if (data['coverage'] != 'sandbox_tool' or data['tool_invocation_id'] != invocation
                            or data.get('local_scope_certified') is not True or not self._physical_ended(data)):
                        return False
                return True
            if run.get('process_coverage') != 'trusted_worker_only':
                return False
            data = self.load(run['process_execution'])
            self._run_binding(data)
            if data.get('local_scope_certified') is not True:
                return False  # Physical local cleanup cannot certify unreviewed remote tool work.
            return self._physical_ended(data)
        except Exception:
            return False

    def reconcile(self, uid, rid):
        run = self.recovery._load(rid)
        if run.get('process_coverage') == 'sandbox_tools_v1':
            if not self.local_ended(run):
                raise RecoveryEvidenceError('Not all Sandbox ToolCalls have verified end proof')
            failures = []
            for key in run['process_executions']:
                try:
                    self._reconcile_one(uid, rid, key)
                except Exception as exc:
                    failures.append(type(exc).__name__)
            if failures:
                raise RecoveryEvidenceError('Sandbox release remains pending: ' + ','.join(failures))
            return True
        return self._reconcile_one(uid, rid, run.get('process_execution'))

    def _reconcile_one(self, uid, rid, execution):
        run = self.recovery._load(rid)
        if not execution:
            raise RecoveryEvidenceError('Managed runner has no durable execution link')
        data = self.load(execution)
        _, row = self._run_binding(data)
        if data['uid'] != uid or row['status'] not in TERMINAL or run['phase'] != 'settled' or not self.local_ended(run):
            raise RecoveryEvidenceError('Process release requires durable run terminal and complete cleanup proof')
        if data['phase'] != 'RELEASED':
            proof = {**data['proof'], 'terminal_reconciled': True, 'terminal_status': row['status']}
            data = self._write({**data, 'phase': 'RELEASED', 'proof': proof, 'terminal': row['status']})
        if data['cgroup'] is not None and data['cgroup']['root'] == self.root.identity and not data.get('cgroup_removed'):
            try:
                with self.root.open(execution, data['cgroup']) as group:
                    group.remove()
                data = self._write({**data, 'cgroup_removed': True, 'cgroup_removal_pending': False})
            except FileNotFoundError:
                if not self._physical_ended(data):
                    raise RecoveryEvidenceError('Cgroup removal observation is incomplete')
                data = self._write({**data, 'cgroup_removed': True, 'cgroup_removal_pending': False})
            except OSError as exc:
                # Physical end was proved before removal. Preserve its identity
                # and pending directory collection; never infer end from rmdir.
                data = self._write({**data, 'cgroup_removal_pending': True,
                                    'cgroup_removal_error_type': type(exc).__name__})
        self.errors.pop(execution, None)
        live = self.live.get(execution)
        if live and live.get('handle') is not None:
            live['handle'].close(); live['handle'] = None
        with self.lock:
            self.live.pop(execution, None)
        return True

    def for_run(self, uid, rid):
        run = self.recovery._load(rid)
        if run['uid'] != uid:
            raise RecoveryEvidenceError('Process resource owner mismatch')
        execution = run.get('process_execution')
        if execution:
            data = self.load(execution); self._run_binding(data)
            return execution
        with self.lock:
            return next((key for key, live in self.live.items() if live.get('initial', {}).get('run_id') == rid
                         and live['initial']['uid'] == uid), None)

    def stop_run(self, uid, rid):
        run = self.recovery._load(rid)
        if run['uid'] != uid:
            raise RecoveryEvidenceError('Process resource owner mismatch')
        if run.get('process_coverage') == 'sandbox_tools_v1':
            results = []
            for key in run['process_executions']:
                try:
                    self._run_binding(self.load(key))
                    results.append(self.cleanup(key))
                except Exception as exc:
                    results.append({'cleanup_verified': False, 'reason_code': type(exc).__name__})
            return {'cleanup_verified': all(r['cleanup_verified'] for r in results), 'executions': results}
        execution = self.for_run(uid, rid)
        return self.cleanup(execution) if execution else {'cleanup_verified': False, 'reason_code': 'unmanaged_execution'}

    def tool_execution(self, uid, rid, invocation, *, allow_preparing=False):
        run = self.recovery._load(rid)
        if run['uid'] != uid or run.get('process_coverage') != 'sandbox_tools_v1':
            raise RecoveryEvidenceError('Sandbox run owner mismatch')
        matches = [key for key, value in run['process_executions'].items() if value == invocation]
        if not matches and allow_preparing:
            with self.lock:
                matches = [key for key, live in self.live.items()
                    if live.get('initial', {}).get('uid') == uid and live['initial'].get('run_id') == rid
                    and live['initial'].get('tool_invocation_id') == invocation]
            if len(matches) == 1:
                return matches[0]  # Only the exact live owner may repair never-started preparation.
        if len(matches) != 1:
            raise RecoveryEvidenceError('Unknown or ambiguous ToolCall identity')
        data = self.load(matches[0]); self._run_binding(data)
        if data['tool_invocation_id'] != invocation:
            raise RecoveryEvidenceError('ToolCall identity mismatch')
        return matches[0]

    def stop_all(self):
        deadline = time.monotonic() + sum(self.limits[k] for k in ('term', 'escalation', 'empty', 'persistence'))
        results = []
        for key in list(self.known):
            try:
                results.append(self.cleanup(key, budget=max(0, deadline - time.monotonic())))
            except Exception as exc:
                self.errors[key] = type(exc).__name__
                results.append({'cleanup_verified': False, 'execution_id': key, 'reason_code': type(exc).__name__})
        return {'cleanup_verified': all(x['cleanup_verified'] for x in results), 'executions': len(results)}

    def all_ended(self, run_ids=()):
        try:
            return (self.scan_complete and not self.errors
                and all(self.local_ended(self.recovery._load(rid)) for rid in run_ids)
                and all(self.local_ended(self.recovery._load(self.load(key)['run_id'])) for key in self.known))
        except Exception:
            return False

    def scan_step(self):
        self.initialize()
        if not self.scan_complete:
            if self.iterator is None:
                self.iterator = os.scandir(self.directory)
            for _ in range(4):
                entry = next(self.iterator, None)
                if entry is None:
                    self.iterator.close(); self.iterator = None; self.scan_complete = True; break
                if re.fullmatch('[a-f0-9]{32}\\.json', entry.name):
                    self.known.add(entry.name[:-5])
                elif not entry.name.startswith('.tmp-'):
                    self.errors['invalid_name'] = 'RecoveryEvidenceError'
        keys = list(self.known)
        for _ in range(min(1, len(keys))):
            key = keys[self.refresh % len(keys)]; self.refresh += 1
            try:
                data = self.load(key); self._run_binding(data)
                if data['owner'] != self.recovery.owner and owner_dead(data['owner']) is True:
                    if data['phase'] not in ('ENDED', 'RELEASED'):
                        self.cleanup(key)
                        data = self.load(key)
                    run, row = self._run_binding(data)
                    if row['status'] in TERMINAL and run['phase'] == 'settled' and self.local_ended(run):
                        self.reconcile(data['uid'], data['run_id'])
                elif data['phase'] == 'ENDED':
                    run, row = self._run_binding(data)
                    if row['status'] in TERMINAL and run['phase'] == 'settled':
                        self.reconcile(data['uid'], data['run_id'])
                if data['phase'] == 'RELEASED':
                    if not self.local_ended(self.recovery._load(data['run_id'])):
                        raise RecoveryEvidenceError('Released process evidence no longer verifies')
                    self.errors.pop(key, None)
                    if data.get('cgroup_removal_pending'):
                        self.reconcile(data['uid'], data['run_id'])
            except Exception as exc:
                self.errors[key] = type(exc).__name__
        return self.snapshot()['ready']

    def snapshot(self):
        unresolved = dict(self.errors)
        for key in list(self.known):
            try:
                data = self.load(key)
                if data['phase'] == 'RELEASED':
                    if self.local_ended(self.recovery._load(data['run_id'])):
                        continue
                    unresolved[key] = 'released_resource_observation_unverified'
                ended_active_tool = (data['coverage'] == 'sandbox_tool' and data['phase'] == 'ENDED'
                    and data['owner'] == self.recovery.owner and data.get('local_scope_certified') is True
                    and self._run_binding(data)[0].get('process_registration_closed') is False
                    and self._physical_ended(data))
                if not ended_active_tool and (data['owner'] != self.recovery.owner or data['phase'] in ('STOPPING', 'ENDED', 'UNKNOWN')):
                    unresolved[key] = data['phase']
            except Exception as exc:
                unresolved[key] = type(exc).__name__
        return {'ready': self.scan_complete and not unresolved, 'scan_complete': self.scan_complete,
                'unresolved': unresolved, 'managed_executions': len(self.known)}

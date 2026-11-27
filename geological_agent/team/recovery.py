'''Private crash evidence; never executes business work or terminates processes.'''
import base64
from collections import deque
import fcntl
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
import stat
import time
from threading import RLock
import uuid
from weakref import WeakValueDictionary

from .protocol import MAX_FILE, MAX_FILES_TOTAL, relative_name

TERMINAL = {'completed', 'incomplete', 'needs_input', 'failed', 'stopped', 'budget_exhausted', 'interrupted'}
MAX_RECORD = 96 * 1024 * 1024
_PROCESS_OWNERS = WeakValueDictionary()
_PROCESS_OWNERS_LOCK = RLock()


class RecoveryEvidenceError(RuntimeError):
    pass


class BrokerOwnershipError(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def process_identity():
    fields = Path('/proc/self/stat').read_text().split(') ', 1)[1].split()
    return {'pid': os.getpid(), 'start_ticks': fields[19],
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'pid_namespace': os.readlink('/proc/self/ns/pid'), 'instance': uuid.uuid4().hex}


def owner_dead(owner):
    '''None means incomparable/unreadable, not safely dead. PID reuse is explicit.'''
    try:
        if not isinstance(owner, dict):
            return None
        if owner['boot_id'] != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
            return True  # This host boot cannot contain the previous boot's processes.
        if owner['pid_namespace'] != os.readlink('/proc/self/ns/pid'):
            return None
        path = Path('/proc') / str(int(owner['pid'])) / 'stat'
        try:
            parts = path.read_text().split(') ', 1)[1].split()
        except FileNotFoundError:
            return True
        return parts[19] != owner['start_ticks'] or parts[0] == 'Z'
    except (OSError, KeyError, ValueError, TypeError):
        return None


class Recovery:
    def __init__(self, store, scope='external_unknown'):
        self.store = store
        self.directory = store.root / '.recovery'
        self.scope = scope if scope == 'broker_process' else 'external_unknown'
        self.owner = process_identity()
        self.fd = None
        self.standby = False
        self.ownership_lock = RLock()
        self.identity = None
        self.notes = {}
        self.error_type = None
        self.scan_complete = False
        self.cursor = ''
        self.rows = deque()
        self.sql_complete = False
        self.iterator = None
        self.seen = set()
        self.queued = set()
        self.current = {}
        self.scan_attempts = 0
        self.refresh_cursor = 0
        self.process_resources = None  # Optional candidate Trusted execution evidence.

    @staticmethod
    def _sync_directory(path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _private_directory(path):
        if path.is_symlink():
            raise RecoveryEvidenceError('Recovery directory must not be a link')
        path.mkdir(mode=0o700, exist_ok=True)
        path.chmod(0o700)
        Recovery._sync_directory(path.parent)

    @staticmethod
    def _read(path, maximum=MAX_RECORD):
        # A replacement may unlink an opened inode. Yield between bounded
        # reopens so a burst of legitimate journal transitions can settle.
        deadline = time.monotonic() + 0.05
        for attempt in range(8):
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_mode & 0o077 or info.st_size > maximum):
                    raise RecoveryEvidenceError('Invalid private recovery file')
                if info.st_nlink == 0:
                    pass  # Close this stale descriptor before any retry delay.
                elif info.st_nlink != 1:
                    raise RecoveryEvidenceError('Invalid private recovery file')
                else:
                    with os.fdopen(fd, 'rb', closefd=False) as handle:
                        raw = handle.read(maximum + 1)
                    if len(raw) > maximum:
                        raise RecoveryEvidenceError('Recovery file exceeds quota')
                    return json.loads(raw)
            finally:
                os.close(fd)
            remaining = deadline - time.monotonic()
            if attempt == 7 or remaining <= 0:
                break
            time.sleep(min(0.001 * 2 ** min(attempt, 3), 0.005, remaining))
        raise RecoveryEvidenceError('Recovery file changed during bounded read')

    def _atomic(self, folder, name, value):
        raw = canonical(value)
        if len(raw) > MAX_RECORD:
            raise RecoveryEvidenceError('Recovery record exceeds quota')
        tmp = folder / ('.tmp-' + uuid.uuid4().hex)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            with os.fdopen(fd, 'wb', closefd=False) as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(fd)
            os.replace(tmp, folder / name)
            directory_fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            os.close(fd)
            # A crash can leave a temp; readers never treat it as committed evidence.
            tmp.unlink(missing_ok=True)

    def activate(self):
        with self.ownership_lock:
            try:
                self._activate()
                self.standby = False
                return True
            except BrokerOwnershipError:
                # Multiple app objects in one process may read saved account data;
                # only the existing fenced owner can recover or execute anything.
                with _PROCESS_OWNERS_LOCK:
                    owner = _PROCESS_OWNERS.get(str(self.store.root))
                    if owner is not None and owner is not self and owner.fd is not None and owner.owner['pid'] == os.getpid():
                        self.standby = True
                        return False
                raise

    def _activate(self):
        if self.fd is not None and self.identity is not None:
            return
        self._private_directory(self.directory)
        path = self.directory / 'broker.lock'
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise BrokerOwnershipError('Another broker owns this state directory') from None
        try:
            database = self.store.root / 'team.sqlite3'
            if database.is_symlink():
                raise RecoveryEvidenceError('Database identity must not be a link')
            st = database.stat()
            if st.st_nlink != 1:
                raise RecoveryEvidenceError('Database identity has multiple links')
            binding = {'root': str(self.store.root), 'device': st.st_dev, 'inode': st.st_ino}
            path = self.directory / 'identity.json'
            if path.exists() or path.is_symlink():
                identity = self._read(path, 8192)
                if identity.get('format') != 1 or identity.get('binding') != binding:
                    raise RecoveryEvidenceError('Deployment/database recovery identity mismatch')
                if not re.fullmatch('[a-f0-9]{64}', identity.get('key', '')):
                    raise RecoveryEvidenceError('Invalid recovery identity')
            else:
                identity = {'format': 1, 'binding': binding, 'deployment': uuid.uuid4().hex,
                            'key': secrets.token_hex(32)}
                self._atomic(self.directory, path.name, identity)
            self._private_directory(self.directory / 'runs')
            self.fd, self.identity = fd, identity
            with _PROCESS_OWNERS_LOCK:
                _PROCESS_OWNERS[str(self.store.root)] = self
        except BaseException:
            os.close(fd)
            raise

    def close(self):
        with self.ownership_lock:
            self._close()

    def _close(self):
        # Closing this fence is not a claim that external resources were drained.
        if self.iterator is not None:
            self.iterator.close()
            self.iterator = None
        with _PROCESS_OWNERS_LOCK:
            if _PROCESS_OWNERS.get(str(self.store.root)) is self:
                _PROCESS_OWNERS.pop(str(self.store.root), None)
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        # Retain the private key for already-owned workers finishing after lifespan exit.
        # No admission is allowed without reacquiring the fence in activate().

    def _path(self, rid):
        if not isinstance(rid, str) or not re.fullmatch('[a-f0-9]{32}', rid):
            raise RecoveryEvidenceError('Invalid recovery run identity')
        return self.directory / 'runs' / (rid + '.json')

    def _write(self, data):
        payload = {**data, 'format': 1, 'deployment': self.identity['deployment'],
                   'binding': self.identity['binding']}
        mac = hmac.new(bytes.fromhex(self.identity['key']), canonical(payload), hashlib.sha256).hexdigest()
        self._atomic(self.directory / 'runs', self._path(payload['rid']).name, {'data': payload, 'mac': mac})
        return payload

    def _load(self, rid):
        box = self._read(self._path(rid))
        data = box['data']
        mac = hmac.new(bytes.fromhex(self.identity['key']), canonical(data), hashlib.sha256).hexdigest()
        if (not isinstance(box.get('mac'), str) or not hmac.compare_digest(box['mac'], mac)
                or data.get('format') != 1 or data.get('deployment') != self.identity['deployment']
                or data.get('binding') != self.identity['binding'] or data.get('rid') != rid):
            raise RecoveryEvidenceError('Recovery evidence integrity mismatch')
        return data

    def prepare(self, uid, cid, rid):
        data = {'rid': rid, 'uid': uid, 'cid': cid, 'created': None, 'owner': self.owner,
                'scope': self.scope, 'phase': 'prepared', 'execution_authorized': False}
        if self._path(rid).exists():
            raise RecoveryEvidenceError('A recovery record already owns this run')
        self.current[rid] = self._write(data)

    def authorize(self, uid, rid):
        data = self.current.get(rid) or self._load(rid)
        row = self.store.run(uid, rid)
        if data['owner'] != self.owner or data['uid'] != uid or data['cid'] != row['cid'] or data['phase'] != 'prepared' or row['status'] not in ('running', 'stopping'):
            raise RecoveryEvidenceError('Execution authorization mismatch')
        self.current[rid] = self._write({**data, 'phase': 'authorized', 'execution_authorized': True, 'created': row['created']})

    @staticmethod
    def _pack(files):
        if files is None:
            return None
        if len(files) > 1024:
            raise RecoveryEvidenceError('Too many recovery files')
        output, total = {}, 0
        for name, raw in files.items():
            relative_name(name)
            if not isinstance(raw, bytes) or len(raw) > MAX_FILE:
                raise RecoveryEvidenceError('Invalid recovery file bytes')
            total += len(raw)
            if total > MAX_FILES_TOTAL:
                raise RecoveryEvidenceError('Recovery files exceed quota')
            output[name] = {'bytes': base64.b64encode(raw).decode('ascii'), 'sha256': hashlib.sha256(raw).hexdigest()}
        return output

    @classmethod
    def _unpack(cls, value):
        if value is None:
            return None
        if not isinstance(value, dict) or len(value) > 1024:
            raise RecoveryEvidenceError('Invalid recovery files')
        output = {}
        for name, entry in value.items():
            relative_name(name)
            raw = base64.b64decode(entry['bytes'], validate=True)
            if hashlib.sha256(raw).hexdigest() != entry['sha256']:
                raise RecoveryEvidenceError('Recovery file checksum mismatch')
            output[name] = raw
        cls._pack(output)  # Validate actual decoded sizes, not attacker-provided lengths.
        return output

    def freeze(self, record):
        if record.get('_durable'):
            return
        rid, uid = record['rid'], record['uid']
        data = record.get('_cold_source') or self.current.get(rid)
        if data is None:
            try:
                data = self._load(rid)
            except FileNotFoundError:
                pass
        if data is None:
            row = self.store.run(uid, rid)
            data = {'rid': rid, 'uid': uid, 'cid': row['cid'], 'created': row['created'],
                    'owner': self.owner, 'scope': self.scope, 'phase': 'authorized', 'execution_authorized': True}
        if data['uid'] != uid:
            raise RecoveryEvidenceError('Recovery owner mismatch')
        kind = record['kind'].removeprefix('cold_')
        if kind == 'startup':
            payload = {'kind': kind, 'reason': record['reason']}
            data = {**data, 'execution_authorized': False}
        elif kind == 'input_cancel':
            payload = {'kind': kind, 'request_id': record['request_id']}
        else:
            outcome = record['outcome']
            if outcome['status'] not in TERMINAL or not isinstance(outcome.get('answer', ''), str) or not isinstance(outcome.get('reason', ''), str):
                raise RecoveryEvidenceError('Invalid recovery outcome')
            payload = {'kind': 'terminal', 'outcome': outcome, 'files': self._pack(record['files']),
                       'base_generation': record['base_generation'], 'origins': record['origins']}
        data = self._write({**data, 'phase': 'aborted' if kind == 'startup' else 'outcome', 'payload': payload})
        self.current[rid] = data
        record['_durable'] = True
        if record.get('_cold_source') is not None:
            record['_cold_source'] = data
            record['_fingerprint'] = self._fingerprint(rid)

    def committed(self, record):
        rid = record['rid']
        data = self.current.pop(rid, None) or record.get('_cold_source')
        if data is None and self.process_resources is not None:
            data = self._load(rid)
        if data is not None:
            data = {k: v for k, v in data.items() if k != 'payload'}
            no_reservation = record['kind'].removeprefix('cold_') == 'startup' and record.get('persistent_status') is None
            self._write({**data, 'phase': 'aborted' if no_reservation else 'settled',
                         'terminal_status': record.get('persistent_status')})
        self.queued.discard(rid)
        if rid in self.notes:
            self.notes[rid]['state'] = 'quarantined' if self.notes[rid].get('resource_unverified') else 'reconciled'

    def _fingerprint(self, rid):
        st = self._path(rid).lstat()
        return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)

    def recheck(self, record):
        if self._fingerprint(record['rid']) != record['_fingerprint']:
            raise RecoveryEvidenceError('Recovery evidence changed during reconciliation')
        data = record['_cold_source']
        if owner_dead(data.get('owner')) is not True:
            raise RecoveryEvidenceError('Old broker ownership is not conclusively inactive')
        row = self.store.run(record['uid'], record['rid'])
        if row['cid'] != data['cid'] or (data.get('created') is not None and row['created'] != data['created']):
            raise RecoveryEvidenceError('Recovery run binding mismatch')

    def _note(self, rid, row, classification, reason, *, state='quarantined', resource_unverified=True):
        self.notes[rid] = {'uid': row['uid'], 'classification': classification, 'reason_code': reason,
                           'state': state, 'resource_unverified': resource_unverified}

    def _discover(self, rid, enqueue):
        if rid not in self.seen:
            self._inspect(rid, enqueue)
            self.seen.add(rid)

    def _terminal_tools_settled(self, row):
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT data FROM events WHERE rid=? ORDER BY seq", (row['id'],)).fetchall()
        pending = set()
        try:
            for (raw,) in rows:
                event = json.loads(raw)
                if event.get('kind') == 'tool_start':
                    call_id = event.get('id')
                    if not isinstance(call_id, str) or not call_id:
                        return False
                    pending.add(call_id)
                elif event.get('kind') == 'tool_result':
                    pending.discard(event.get('id'))
        except (TypeError, ValueError):
            return False
        return not pending

    def _inspect(self, rid, enqueue):
        with self.store.lock:
            row = self.store.db.execute('SELECT r.*,c.uid FROM runs r JOIN conversations c ON r.cid=c.id WHERE r.id=?', (rid,)).fetchone()
            row = dict(row) if row is not None else None
        try:
            data = self._load(rid)
        except FileNotFoundError:
            data = None
        except Exception as exc:
            if row is not None:
                self._note(rid, row, 'D', 'invalid_evidence_' + type(exc).__name__)
            else:
                self._note(rid, {'uid': None}, 'D', 'unbound_evidence')
            return
        if row is None:
            if data is not None and data['phase'] in ('prepared', 'aborted') and owner_dead(data.get('owner')) is True:
                self._note(rid, {'uid': data['uid']}, 'C', 'no_durable_reservation', state='reconciled', resource_unverified=False)
                return
            self._note(rid, {'uid': None}, 'D', 'unbound_evidence')
            return
        if data is not None and (data.get('uid') != row['uid'] or data.get('cid') != row['cid']
                or (data.get('created') is not None and data['created'] != row['created'])):
            self._note(rid, row, 'D', 'run_binding_mismatch')
            return
        if data is not None and data.get('owner') == self.owner:
            return  # A repeated lifespan scan cannot interrupt this instance's work.
        dead = owner_dead(data.get('owner')) if data else None
        local_ended = bool(data and dead is True and (data.get('scope') == 'broker_process' or data.get('execution_authorized') is False))
        if data and self.process_resources is not None and self.process_resources.local_ended(data):
            local_ended = True
        if row['status'] in TERMINAL:
            settled_without_process = bool(
                data and dead is True and data.get('phase') == 'settled'
                and data.get('terminal_status') == row['status']
                and not data.get('process_coverage')
                and self._terminal_tools_settled(row))
            self._note(rid, row, 'A', 'durable_terminal',
                       state='reconciled' if local_ended or settled_without_process
                       or data is None or data.get('execution_authorized') is False else 'quarantined',
                       resource_unverified=not (local_ended or settled_without_process
                       or data is None or data.get('execution_authorized') is False))
            return
        if data is None or dead is not True:
            self._note(rid, row, 'D', 'missing_evidence' if data is None else 'owner_live_or_incomparable')
            return
        phase = data.get('phase')
        item = {'rid': rid, 'uid': row['uid'], 'cid': row['cid'], 'startup': None,
                'execution_done': True, 'cleanup_done': True, 'persisted': False, 'attempts': 0,
                'profile': None, 'files': None, '_cold_source': data,
                '_fingerprint': self._fingerprint(rid), '_durable': True}
        if phase in ('prepared', 'aborted'):
            item.update(kind='cold_startup', target_status='failed', reason=data.get('payload', {}).get('reason', 'Broker exited before business execution was durably authorized.'))
            self._note(rid, row, 'C', 'confirmed_never_authorized', state='pending', resource_unverified=False)
        elif phase == 'outcome':
            try:
                payload = data['payload'];kind = payload['kind']
                if kind == 'input_cancel':
                    item.update(kind='cold_input_cancel', request_id=payload['request_id'], target_status='stopped')
                elif kind == 'terminal':
                    outcome = payload['outcome']
                    if outcome['status'] not in TERMINAL:
                        raise RecoveryEvidenceError('Invalid outcome status')
                    item.update(kind='cold_terminal', outcome=outcome, target_status=outcome['status'],
                                files=self._unpack(payload['files']), base_generation=payload['base_generation'], origins=payload['origins'])
                else:
                    raise RecoveryEvidenceError('Invalid outcome kind')
            except Exception as exc:
                self._note(rid, row, 'D', 'invalid_result_' + type(exc).__name__)
                return
            self._note(rid, row, 'B', 'durable_outcome', state='pending', resource_unverified=not local_ended)
        elif phase == 'authorized' and local_ended:
            item.update(kind='cold_terminal', outcome={'status': 'interrupted', 'reason': 'The confirmed process-only execution boundary ended without a durable result; no task was replayed.'}, target_status='interrupted', files=None, origins=None, base_generation=None)
            self._note(rid, row, 'D', 'process_boundary_ended_result_unknown', state='pending', resource_unverified=False)
        else:
            self._note(rid, row, 'D', 'external_execution_unverified')
            return
        self.queued.add(rid)
        enqueue(item)

    def scan_step(self, enqueue):
        self.scan_attempts += 1
        try:
            if self.scan_complete:
                # Same B3 scheduler rechecks changing owner/evidence conditions. Never
                # infer external cleanup from an absent PID; external_unknown stays held.
                pending = [rid for rid, note in self.notes.items()
                           if note['resource_unverified'] or note['state'] == 'quarantined']
                if not pending:
                    return True
                for _ in range(min(4, len(pending))):
                    rid = pending[self.refresh_cursor % len(pending)]
                    self.refresh_cursor += 1
                    if rid not in self.queued:
                        self.seen.discard(rid)
                        self._discover(rid, enqueue)
                return not any(note['resource_unverified'] or note['state'] == 'quarantined'
                               for note in self.notes.values())
            if not self.sql_complete and not self.rows:
                rows = self.store.recover(after=self.cursor, limit=64)
                self.rows.extend(row['id'] for row in rows)
                if rows:
                    self.cursor = rows[-1]['id']
                self.sql_complete = len(rows) < 64
            budget = 4
            while self.rows and budget:
                self._discover(self.rows[0], enqueue)
                self.rows.popleft()
                budget -= 1
            if self.sql_complete and not self.rows:
                if self.iterator is None:
                    self.iterator = os.scandir(self.directory / 'runs')
                for _ in range(budget):
                    entry = next(self.iterator, None)
                    if entry is None:
                        self.iterator.close(); self.iterator = None
                        self.scan_complete = True; self.error_type = None
                        return not any(note['resource_unverified'] or note['state'] == 'quarantined' for note in self.notes.values())
                    if re.fullmatch('[a-f0-9]{32}\\.json', entry.name):
                        try:
                            self._discover(entry.name[:-5], enqueue)
                        except BaseException:
                            self.rows.appendleft(entry.name[:-5])
                            raise
                    elif not entry.name.startswith('.tmp-'):
                        self._note('__invalid_record__', {'uid': None}, 'D', 'invalid_record_name')
            self.error_type = None
            return False
        except Exception as exc:
            self.error_type = type(exc).__name__
            raise

    def snapshot(self):
        quarantine = [rid for rid, value in self.notes.items() if value['resource_unverified'] or value['state'] == 'quarantined']
        return {'standby': self.standby, 'ready': not self.standby and self.scan_complete and not quarantine and self.error_type is None,
                'scan_complete': self.scan_complete, 'scan_attempts': self.scan_attempts,
                'last_error_type': self.error_type, 'quarantined': quarantine,
                'classifications': {rid: {k: v for k, v in value.items() if k != 'uid'} for rid, value in self.notes.items()}}

    def for_run(self, uid, rid):
        item = self.notes.get(rid)
        return {key: item[key] for key in ['classification', 'state', 'reason_code', 'resource_unverified']} if item and item['uid'] == uid else None

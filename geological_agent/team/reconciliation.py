'''In-process persistence retries only: never executes an Agent/model/tool.'''
from collections import deque
import logging
from threading import Condition, Thread, current_thread
import time


class Reconciler:
    def __init__(self, operation, *, base_delay=0.1, max_delay=1.0):
        self.operation = operation
        self.base_delay, self.max_delay = base_delay, max_delay
        self.condition = Condition()
        self.pending = {}
        self.history = deque(maxlen=256)
        self.thread = None
        self.references = 0
        self.stopping = True

    def start(self):
        with self.condition:
            if self.references:
                self.references += 1
                return
            if self.thread is not None and self.thread.is_alive():
                raise RuntimeError('Previous reconciliation scheduler is still stopping')
            self.stopping = False
            self.thread = Thread(target=self._loop, name='run-reconciliation', daemon=True)
            try:
                self.thread.start()
            except BaseException:
                self.stopping = True
                raise
            self.references = 1
            self.condition.notify_all()

    def close(self, timeout=2.0):
        with self.condition:
            if self.references > 1:
                self.references -= 1
                return True
            self.references = 0
            self.stopping = True
            self.condition.notify_all()
            thread = self.thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout)
        return thread is None or not thread.is_alive()

    def add(self, record):
        with self.condition:
            existing = self.pending.get(record['rid'])
            if existing is not None:
                if existing is not record:
                    raise RuntimeError('A different outcome already owns this run')
                return
            record.update(inflight=False, retry_count=0,
                          next_due=time.monotonic() + self.base_delay, error_type=None)
            self.pending[record['rid']] = record
            self.history.append({'time': time.monotonic(), 'rid': record['rid'],
                                 'kind': record['kind'], 'event': 'registered'})
            self.condition.notify_all()

    def snapshot(self, uid=None, rid=None):
        with self.condition:
            return {key: {'kind': r['kind'], 'target_status': r['target_status'],
                          'retry_count': r['retry_count'], 'attempts': r['attempts'],
                          'inflight': r['inflight'], 'persisted': r.get('persisted', False),
                          'next_due': r['next_due'], 'error_type': r.get('error_type')}
                    for key, r in self.pending.items()
                    if (uid is None or r['uid'] == uid) and (rid is None or key == rid)}

    def attempt(self, rid, *, wait=False, timeout=6.0):
        deadline = time.monotonic() + timeout
        with self.condition:
            while True:
                record = self.pending.get(rid)
                if record is None:
                    return True
                if not record['inflight']:
                    break
                remaining = deadline - time.monotonic()
                if not wait or remaining <= 0:
                    return False
                self.condition.wait(remaining)
            record['inflight'] = True
            record['retry_count'] += 1
            attempt = record['retry_count']
        error_type = None
        try:
            done = bool(self.operation(record))
        except Exception as exc:
            done = False
            error_type = type(exc).__name__
            # Bounded diagnostics: no exception text, user content, or per-retry spam.
            if attempt <= 2:
                logging.getLogger(__name__).error(
                    'Run reconciliation pending: run=%s error_type=%s', rid, error_type)
        with self.condition:
            record['inflight'] = False
            record['error_type'] = error_type
            self.history.append({'time': time.monotonic(), 'rid': rid, 'kind': record['kind'],
                                 'event': 'persisted' if done else 'retry_pending',
                                 'retry': attempt, 'error_type': error_type})
            if done:
                if self.pending.get(rid) is record:
                    self.pending.pop(rid)
            else:
                delay = min(self.max_delay, self.base_delay * (2 ** min(attempt - 1, 10)))
                record['next_due'] = time.monotonic() + delay
            self.condition.notify_all()
        if done:
            logging.getLogger(__name__).info('Run reconciliation completed: run=%s', rid)
        return done

    def _loop(self):
        while True:
            with self.condition:
                if self.stopping:
                    return
                now = time.monotonic()
                available = [(key, r) for key, r in self.pending.items() if not r['inflight']]
                due = [key for key, r in available if r['next_due'] <= now][:4]
                if not due:
                    delay = min((max(0.001, r['next_due'] - now) for _, r in available), default=1.0)
                    self.condition.wait(delay)
                    continue
            for rid in due:
                with self.condition:
                    if self.stopping:
                        return
                self.attempt(rid)

"""Local account usage receipts; accounting failures never abort a research task."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import json, logging, os, re, threading, time, uuid

_scope = ContextVar('oresage_usage_scope', default={})


@contextmanager
def account_context(uid, rid):
    token = _scope.set({'uid': uid, 'rid': rid})
    try:
        yield
    finally:
        _scope.reset(token)


def current_context():
    return dict(_scope.get())


def token_usage(value):
    """Do not add cached/reasoning breakdowns to already inclusive totals."""
    value = value if isinstance(value, dict) else {}
    def integer(*keys):
        for key in keys:
            n = value.get(key)
            if type(n) is int and n >= 0:
                return n
        return None
    prompt = integer('prompt_tokens', 'input_tokens')
    output = integer('completion_tokens', 'output_tokens')
    total = integer('total_tokens')
    if total is None and prompt is not None and output is not None:
        total = prompt + output
    return {'input_tokens': prompt, 'output_tokens': output, 'total_tokens': total}


class UsageAudit:
    def __init__(self, root, secrets=()):
        self.root = Path(root) / 'usage-audit'
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.lock = threading.RLock()
        self.secrets = tuple(x for x in secrets if x)
        self.errors = 0

    def safe(self, value, depth=0, *, text_limit=12_000):
        if depth > 12:
            return '[depth limit]'
        if isinstance(value, dict):
            return {str(k): '[REDACTED]' if re.search(
                r'(?i)(password|secret|api.?key|api.?token|authorization|cookie|csrf|^code$|^token$|^invite$|otp|credential)', str(k))
                else self.safe(v, depth + 1, text_limit=text_limit) for k, v in value.items()
                if k not in {'messages', 'reasoning_content', 'task', 'answer'}}
        if isinstance(value, (list, tuple)):
            return [self.safe(v, depth + 1, text_limit=text_limit) for v in value[:100]]
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, '[REDACTED]')
            value = re.sub(r'(?i)(Bearer\s+)[A-Za-z0-9_.~+/=-]+', r'\1[REDACTED]', value)
            value = re.sub(r'\b(?:sk-[A-Za-z0-9_-]{12,}|lsv2_[A-Za-z0-9_]+|LTAI[A-Za-z0-9]{12,})', '[REDACTED]', value)
            value = re.sub(
                r"""(?i)(\b(?:password|secret|api[_-]?(?:key|token)|access[_-]?token|refresh[_-]?token|"""
                r"""session[_-]?token|accesskeysecret|csrf|join|otp)["']?\s*[=:]\s*)"""
                r"""(?:"[^"\\]*(?:\\.[^"\\]*)*"|'[^']*'|[^\s,;"'}\]]+)""",
                r'\1[REDACTED]', value)
            return value[:text_limit]
        return value

    def record(self, uid, event, **fields):
        if not isinstance(uid, str) or not re.fullmatch(r'[a-f0-9]{32}', uid):
            return
        try:
            row = self.safe({'time': time.time(), 'event': event, **fields})
            raw = (json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n').encode()
            with self.lock:
                fd = os.open(self.root / (uid + '.jsonl'), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                try:
                    os.write(fd, raw)
                finally:
                    os.close(fd)
        except Exception as exc:
            self.errors += 1
            logging.getLogger(__name__).error('Usage receipt write failed: %s', type(exc).__name__)

    def client(self, inner, *, uid, rid=None, category='task', model='unknown'):
        audit = self
        class Client:
            def close(self):
                return inner.close()

            def _begin(self):
                call_id = uuid.uuid4().hex
                audit.record(uid, 'model_attempt', call_id=call_id, rid=rid, category=category, model=model)
                return call_id

            def _done(self, call_id, response):
                actual = (getattr(response, 'provider_metadata', {}) or {}).get('model')
                audit.record(uid, 'model_usage', call_id=call_id, rid=rid, category=category,
                             model=model, reported_model=actual, usage=token_usage(getattr(response, 'usage', {})))

            def invoke(self, request):
                call_id = self._begin()
                try:
                    response = inner.invoke(request)
                    self._done(call_id, response)
                    return response
                except BaseException as exc:
                    audit.record(uid, 'model_error', call_id=call_id, rid=rid, category=category, model=model, error_type=type(exc).__name__)
                    raise

            def stream(self, request):
                call_id = self._begin()
                try:
                    for event in inner.stream(request):
                        if getattr(event, 'response', None) is not None:
                            self._done(call_id, event.response)
                        yield event
                except BaseException as exc:
                    audit.record(uid, 'model_error', call_id=call_id, rid=rid, category=category, model=model, error_type=type(exc).__name__)
                    raise
        return Client()

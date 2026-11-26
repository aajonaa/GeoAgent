"""Managed TrustedLocalRunner IPC. Model execution remains in the broker."""
import json
import os
from pathlib import Path
import re
import selectors
import sys
import time

from ..contracts import ModelRequest
from .isolation import Cancelled
from .protocol import MAX_PACKET, decode, dumps, encode, file_packet, unpack_files

LONG_RUN_MODEL_TURNS = 512


def long_run_requested(query, mode):
    return mode == "agent" and bool(re.match(r"^\s*(?:长任务|长程执行|/long)\s*[:：]\s*\S", query))


def worker_environment():
    # Retrieval uses the authenticated context owner and private config-file paths.
    # Chat-model credentials, ownership keys and candidate controls stay in the broker.
    names = ('PATH', 'HOME', 'LANG', 'PYTHONPATH', 'OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS',
             'TIKTOKEN_CACHE_DIR', 'TMPDIR', 'GEOTOOL_HITL', 'GEOTOOL_CONTEXT_DSN_FILE',
             'GEOTOOL_KNOWLEDGE', 'GEOTOOL_KNOWLEDGE_DSN_FILE', 'GEOTOOL_QWEN_CONFIG_FILE',
             'GEOTOOL_KNOWLEDGE_TOKENIZER', 'GEOTOOL_KNOWLEDGE_TOKENIZER_SHA256',
             'GEOTOOL_KNOWLEDGE_LIMITS_FILE', 'GEOTOOL_LARGE_CORPUS',
             'GEOTOOL_SHARED_KNOWLEDGE_FILE', 'GEOTOOL_KNOWLEDGE_SHARED_ANN')
    environment = {name: os.environ[name] for name in names if name in os.environ}
    if os.environ.get('GEOTOOL_WEB_ENABLED') == '1':
        environment['GEOTOOL_WEB_ENABLED'] = '1'
        key = os.environ.get('TAVILY_API_KEY', '').strip()
        if key:
            environment['TAVILY_API_KEY'] = key
    return {**environment, 'PYTHONDONTWRITEBYTECODE': '1'}


def worker_command(runner, manager):
    bwrap = Path(os.environ['GEOTOOL_TRUSTED_PROCESS_BWRAP'])
    if not bwrap.is_absolute() or not bwrap.is_file():
        raise RuntimeError('An inspected candidate bubblewrap executable is required')
    target = runner.process_worker or [sys.executable, '-B', '-m', 'geological_agent.team.trusted_worker']
    # Same UID remains a documented trust boundary, not an adversarial sandbox.
    return [str(bwrap), '--unshare-user', '--uid', str(os.getuid()), '--gid', str(os.getgid()),
            '--unshare-ipc', '--unshare-uts', '--cap-drop', 'ALL', '--ro-bind', '/', '/',
            '--bind', str(runner.jobs_root.parent), str(runner.jobs_root.parent),
            '--tmpfs', str(manager.recovery.directory),
            '--ro-bind', '/sys/fs/cgroup', '/sys/fs/cgroup',
            '--ro-bind', str(manager.root.path), str(manager.root.path),
            '--dev', '/dev', '--tmpfs', '/tmp',
            '--chdir', str(runner.jobs_root), '--', *target]


def send(proc, packet, cancel, *, timeout=5):
    raw = memoryview(dumps(packet))
    deadline = time.monotonic() + timeout
    while raw:
        if cancel.is_set():
            raise Cancelled('Stopped before worker exchange completed')
        if time.monotonic() >= deadline:
            raise TimeoutError('Worker input exchange deadline exceeded')
        try:
            count = os.write(proc.stdin.fileno(), raw)
            raw = raw[count:]
        except BlockingIOError:
            with selectors.DefaultSelector() as ready:
                ready.register(proc.stdin, selectors.EVENT_WRITE)
                ready.select(.05)


def run_managed(runner, rid, query, files, cancel, model_call, on_trace, *, settings=None, **kwargs):
    manager = runner.process_ownership
    scope = kwargs.pop('process_scope', None)
    if not isinstance(scope, dict) or set(scope) != {'uid', 'cid'}:
        raise ValueError('Authenticated broker ownership is required for managed Trusted execution')
    uid, cid = scope['uid'], scope['cid']
    execution, proc, selector = None, None, None
    transfer_limit = (8 if kwargs.pop('long_run', False) else 2) * MAX_PACKET
    stage = 'prepare'
    try:
        execution = manager.prepare(uid, cid, rid, local_scope_certified=runner.process_scope_certified)
        if cancel.is_set():
            raise Cancelled('Stopped before execution')
        environment = {**worker_environment(), 'TMPDIR': '/tmp', 'HOME': str(runner.jobs_root)}
        stage = 'command_and_launch'
        proc = manager.launch(execution, worker_command(runner, manager), environment,
                              diagnostics=kwargs.pop('diagnostics', None), cancel=cancel)
        os.set_blocking(proc.stdin.fileno(), False)
        os.set_blocking(proc.stdout.fileno(), False)
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        stage = 'initial_packet'
        send(proc, {'rid': rid, 'jobs_root': str(runner.jobs_root), 'query': query,
                    'files': [file_packet(k, v) for k, v in files.items()], 'settings': settings or {},
                    'options': encode(kwargs)}, cancel)
        buffer, transferred = bytearray(), 0
        while True:
            stage = 'worker_packet'
            if cancel.is_set():
                raise Cancelled('Stopped. The last committed files are retained.')
            if b'\n' not in buffer:
                if not selector.select(.05):
                    continue
                raw = os.read(proc.stdout.fileno(), 65536)
                if not raw:
                    if cancel.is_set():
                        raise Cancelled('Stopped. The last committed files are retained.')
                    raise RuntimeError('Managed worker exited before a complete result')
                transferred += len(raw); buffer.extend(raw)
                if len(buffer) > MAX_PACKET or transferred > transfer_limit:
                    raise ValueError('Managed worker transport quota exceeded')
                if b'\n' not in buffer:
                    continue
            raw, _, remainder = buffer.partition(b'\n'); buffer = bytearray(remainder)
            packet = json.loads(raw)
            if not isinstance(packet, dict):
                raise ValueError('Invalid managed worker packet')
            kind = packet.get('kind')
            if kind == 'model':
                request = decode(packet['request'])
                if not isinstance(request, ModelRequest) or not isinstance(packet.get('id'), int):
                    raise ValueError('Invalid managed native model request')
                reply = {'id': packet['id']}
                try:
                    reply['response'] = encode(model_call(request, cancel))
                except Cancelled:
                    raise
                except Exception as exc:
                    reply['error'] = type(exc).__name__ + ': ' + str(exc)
                send(proc, reply, cancel)
            elif kind == 'trace':
                event, fields = packet.get('event'), decode(packet.get('fields', {}))
                if not isinstance(event, str) or not isinstance(fields, dict):
                    raise ValueError('Invalid managed trace packet')
                on_trace(event, fields)
            elif kind == 'done':
                result = packet.get('result', {})
                if result.get('status') not in {'completed', 'incomplete', 'needs_input', 'failed', 'stopped', 'budget_exhausted'} or not isinstance(result.get('answer'), str):
                    raise ValueError('Invalid managed completion result')
                result['files'] = unpack_files(packet.get('files', []))
                return result
            elif kind == 'failure':
                # Only the broker-owned cancellation flag establishes cancellation.
                if cancel.is_set():
                    raise Cancelled('Stopped. The last committed files are retained.')
                raise RuntimeError(packet.get('message', 'Managed worker failed'))
            else:
                raise ValueError('Unknown managed worker packet')
    except BaseException as exc:
        # Operational metadata only; never a request, secret or worker payload.
        manager.last_failure = {'stage': stage, 'error_type': type(exc).__name__,
                                'errno': getattr(exc, 'errno', None), 'filename': getattr(exc, 'filename', None)}
        raise
    finally:
        if selector is not None:
            selector.close()
        # Also retries a failed initial persistence only when this exact live
        # owner can prove it never attempted Popen. Cold missing records stay held.
        if execution is None:
            execution = manager.for_run(uid, rid)
        if execution is not None:
            receipt = manager.cleanup(execution)
            if not receipt['cleanup_verified']:
                raise RuntimeError('Managed process cleanup remains quarantined: ' + receipt.get('reason_code', 'unknown'))
        if proc is not None and proc.poll() is not None:
            proc.stdin.close(); proc.stdout.close()

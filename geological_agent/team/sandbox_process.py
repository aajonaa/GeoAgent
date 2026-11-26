"""Fixed local execution transport. ProcessOwnership retains every lifecycle responsibility."""
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import selectors
import sys
from threading import Event
import time
from ..contracts import ErrorInfo, ToolResult
from .protocol import MAX_PACKET, decode, encode, relative_name, unpack_files


def tool_command(runner, workspace):
    manager = runner.process_ownership
    root = manager.recovery.store.root / 'sandbox-jobs'
    workspace = Path(workspace).resolve()
    if workspace.parent != root.resolve() or not workspace.is_dir():
        raise RuntimeError('Sandbox workspace lacks trusted run binding')
    bwrap = Path(os.environ['GEOTOOL_TRUSTED_PROCESS_BWRAP'])
    if not bwrap.is_absolute() or not bwrap.is_file():
        raise RuntimeError('Inspected candidate bubblewrap is required')
    app = Path(__file__).resolve().parents[2]
    roots = list(dict.fromkeys([app, runner.runtime, *runner.readonly_paths]))
    for path in roots:
        if (not path.is_absolute() or not path.is_dir() or path in [Path('/'), Path('/data'), Path('/home'), Path('/run')]
                or manager.recovery.directory.is_relative_to(path) or path.is_relative_to(manager.recovery.directory)):
            raise RuntimeError('Unsafe sandbox runtime mount')
    command = [str(bwrap), '--unshare-user', '--uid', str(os.getuid()), '--gid', str(os.getgid()),
        '--unshare-pid', '--unshare-net', '--unshare-ipc', '--unshare-uts', '--unshare-cgroup',
        '--cap-drop', 'ALL', '--new-session', '--clearenv', '--ro-bind', '/usr', '/usr']
    for path in ['/lib', '/lib64']:
        if Path(path).exists():command += ['--ro-bind', path, path]
    for path in roots:command += ['--ro-bind', str(path), str(path)]
    python = Path(sys.executable)
    if not any(python.is_relative_to(path) for path in roots):
        raise RuntimeError('Python executable is outside inspected runtime mounts')
    command += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--bind', str(workspace), '/work',
        '--setenv', 'PATH', str(python.parent) + ':/usr/bin:/bin', '--setenv', 'HOME', '/work',
        '--setenv', 'LANG', 'C.UTF-8', '--setenv', 'PYTHONPATH', ':'.join(str(p) for p in [app, *runner.readonly_paths]),
        '--setenv', 'PYTHONDONTWRITEBYTECODE', '1', '--setenv', 'OPENBLAS_NUM_THREADS', '1',
        '--setenv', 'OMP_NUM_THREADS', '1', '--chdir', '/work', '--', str(python), '-B',
        '-m', 'geological_agent.team.sandbox_tool']
    return command


def execute_tool(runner, rid, scope, call, context):
    from .isolation import Cancelled
    manager = runner.process_ownership
    if manager is None or not isinstance(scope, dict) or set(scope) != {'uid', 'cid'}:
        raise RuntimeError('Authenticated Sandbox ownership scope is required')
    if call.name not in runner.LOCAL_TOOLS:
        return ToolResult(call.id, call.name, 'error', error=ErrorInfo('sandbox_tool_unsupported',
            'This tool is outside the verified local Sandbox scope; no host fallback was executed.'))
    entry = {'cancel': Event()}
    with runner.lock:
        if (rid, call.id) in runner.active:raise RuntimeError('ToolCall is already active')
        runner.active[(rid, call.id)] = entry
    execution, proc, selector, result = None, None, None, None
    stage = 'prepare'
    try:
        execution = manager.prepare(scope['uid'], scope['cid'], rid,
            local_scope_certified=True, tool_invocation_id=call.id)
        manager.bind_tool_context(execution, context.run_id)
        entry['execution_id'] = execution
        if context.cancel.is_set() or entry['cancel'].is_set():raise Cancelled('ToolCall cancelled before launch')
        _, command = runner.command(rid, call.id, execution_id=execution, workspace=context.workspace)
        stage = 'launch'
        proc = manager.launch(execution, command, {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}, cancel=context.cancel)
        selector = selectors.DefaultSelector()
        os.set_blocking(proc.stdout.fileno(), False);os.set_blocking(proc.stdin.fileno(), False)
        selector.register(proc.stdout, selectors.EVENT_READ)
        from .trusted_process import send
        timeout = context.settings.tool_timeout_seconds
        duration = min(context.deadline - time.monotonic(), timeout if timeout > 0 else math.inf)
        stage = 'input'
        send(proc, {'call': encode(call), 'core_run_id': context.run_id,
            'allowed_tool_names': list(context.allowed_tool_names), 'settings': asdict(context.settings),
            'duration': duration if math.isfinite(duration) else None, 'pure_cache': encode(context.pure_cache),
            'evidence_state': encode(context.evidence_state)}, context.cancel)
        deadline, raw = time.monotonic() + duration, bytearray()
        stage = 'result'
        while True:
            if context.cancel.is_set() or entry['cancel'].is_set():
                result = ToolResult(call.id, call.name, 'cancelled', error=ErrorInfo('cancelled', 'ToolCall stopped'))
                break
            if time.monotonic() >= deadline:
                result = ToolResult(call.id, call.name, 'timeout', error=ErrorInfo('tool_timeout', 'ToolCall deadline exceeded', outcome_unknown=True))
                break
            if not selector.select(.05):continue
            chunk = os.read(proc.stdout.fileno(), 65536)
            if not chunk:
                if manager.load(execution)['phase'] in ('STOPPING', 'ENDED', 'RELEASED'):
                    result = ToolResult(call.id, call.name, 'cancelled', error=ErrorInfo('cancelled', 'Owned cleanup stopped this ToolCall'))
                    break
                raise RuntimeError('Sandbox tool exited before a complete result')
            raw.extend(chunk)
            if len(raw) > min(MAX_PACKET, runner.limits.protocol_bytes):raise ValueError('Sandbox tool result exceeds IPC quota')
            if b'\n' not in raw:continue
            line, _, extra = raw.partition(b'\n')
            if extra:raise ValueError('Unexpected extra Sandbox protocol output')
            reply = json.loads(line);result = decode(reply['result'])
            if not isinstance(result, ToolResult) or result.call_id != call.id or result.name != call.name:
                raise ValueError('Sandbox result identity mismatch')
            cache = decode(reply.get('pure_cache', {}))
            if not isinstance(cache, dict):raise ValueError('Invalid tool cache')
            context.pure_cache.update(cache)
            break
    except BaseException as exc:
        manager.last_sandbox_failure = {'stage': stage, 'error_type': type(exc).__name__, 'errno': getattr(exc, 'errno', None)}
        raise
    finally:
        if selector is not None:selector.close()
        if execution is None:
            try:execution = manager.tool_execution(scope['uid'], rid, call.id, allow_preparing=True)
            except Exception:pass
        receipt = manager.cleanup(execution) if execution is not None else {'cleanup_verified': False}
        with runner.lock:runner.active.pop((rid, call.id), None)
        if proc is not None and proc.poll() is not None:
            proc.stdin.close();proc.stdout.close()
        if not receipt['cleanup_verified']:
            manager.last_sandbox_cleanup_failure = receipt
            raise RuntimeError('Sandbox ToolCall end proof remains quarantined: ' + receipt.get('reason_code', 'unknown'))
    return result


def run_agent(runner, rid, query, files, cancel, model_call, on_trace, *, settings=None,
              diagnostics=None, memory_records=(), process_scope=None, skill_id=None, read_only=False):
    from ..bootstrap import create_agent
    from ..contracts import ModelEvent
    from ..memory import SnapshotMemoryStore
    from ..settings import Settings
    from ..tools import ToolExecutor
    from .worker import snapshot
    from .isolation import Cancelled
    manager = runner.process_ownership
    if (manager is None or not runner.ownership_only or not isinstance(process_scope, dict)
            or set(process_scope) != {'uid', 'cid'}):raise RuntimeError('Candidate Sandbox ownership configuration is required')
    uid, cid = process_scope['uid'], process_scope['cid']
    manager.begin_sandbox(uid, cid, rid)
    root = manager.recovery.store.root / 'sandbox-jobs' / rid
    registration_closed, end_verified = False, False
    def seal_execution():
        nonlocal registration_closed, end_verified
        if not registration_closed:
            manager.close_sandbox(uid, rid)
            registration_closed = True
        receipt = manager.stop_run(uid, rid)
        if not receipt['cleanup_verified']:
            raise RuntimeError('Sandbox resources remain unresolved')
        end_verified = True
    try:
        root.mkdir(parents=True, mode=0o700, exist_ok=False)
        for name, data in files.items():
            target = root / relative_name(name);target.parent.mkdir(parents=True, exist_ok=True);target.write_bytes(data)
        class Model:
            def invoke(self, request):return model_call(request, cancel)
            def stream(self, request):yield ModelEvent('response', response=self.invoke(request))
        class Trace:
            def emit(self, event, **fields):on_trace(event, fields)
            def execution_context(self):
                from contextlib import nullcontext
                return nullcontext()
        agent = create_agent(Model(), settings=Settings(**(settings or {})),
            memory=SnapshotMemoryStore.from_payload(memory_records), trace_factory=lambda *args: Trace(),
            read_only=read_only)
        agent.executor = ToolExecutor(agent.tools,
            execution_adapter=lambda call, context: runner.execute_tool(rid, process_scope, call, context))
        outcome = agent.run(query, workspace=root, cancel_event=cancel, skill_id=skill_id)
        if cancel.is_set():raise Cancelled('Stopped. The last committed files are retained.')
        # File export now happens in the broker. Never traverse the workspace
        # while an unverified tool/descendant could still mutate its paths.
        seal_execution()
        return {'status': outcome.status, 'answer': outcome.answer, 'reason': outcome.reason or '',
                'turns': outcome.model_turns, 'files': unpack_files(snapshot(root))}
    finally:
        if not end_verified:seal_execution()

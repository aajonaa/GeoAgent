"""Fixed local ToolCall entry point, executed only after the ownership gate."""
import json
from pathlib import Path
import sys
from threading import Event
import time
from .protocol import MAX_PACKET, decode, dumps, encode


def main():
    output = sys.stdout.buffer
    sys.stdout = sys.stderr
    raw = sys.stdin.buffer.readline(MAX_PACKET + 1)
    if len(raw) > MAX_PACKET or not raw.endswith(b'\n'):
        raise ValueError('Invalid Sandbox tool packet')
    initial = json.loads(raw)
    from ..contracts import ToolCall
    from ..settings import Settings
    from ..tools import ToolExecutionContext, ToolExecutor, ToolRegistry, register_file_tools
    from .isolation import SandboxRunner
    call = decode(initial['call'])
    if not isinstance(call, ToolCall) or call.name in SandboxRunner.BROKER_ONLY_TOOLS:
        raise ValueError('Unsupported local Sandbox ToolCall')
    if call.name in ('read_file', 'write_file', 'execute_python'):
        registry = ToolRegistry()
        register_file_tools(registry)
    else:
        from ..bootstrap import build_registry
        registry, _, _ = build_registry()
    context = ToolExecutionContext(initial['core_run_id'], Path('/work'), tuple(initial['allowed_tool_names']),
        Settings(**initial['settings']), Event(), pure_cache=decode(initial['pure_cache']),
        evidence_state=decode(initial['evidence_state']))
    if initial['duration'] is not None:
        context.deadline = time.monotonic() + max(0, initial['duration'])
    result = ToolExecutor(registry)._execute(call, context)
    output.write(dumps({'result': encode(result), 'pure_cache': encode(context.pure_cache)}));output.flush()


if __name__ == '__main__':
    main()

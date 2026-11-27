"""Fail-closed per-ToolCall Linux runner; tool handlers never run in the broker."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
from threading import RLock


@dataclass(frozen=True)
class Limits:
    memory: str = '2G'
    cpu: str = '200%'
    tasks: int = 128
    work_bytes: int = 1024 * 1024 * 1024
    temp_bytes: int = 128 * 1024 * 1024
    diagnostic_bytes: int = 64 * 1024 * 1024
    protocol_bytes: int = 256 * 1024 * 1024


class Cancelled(Exception):
    pass


class SandboxRunner:
    isolated = True
    memory_snapshot_enabled = True
    description = 'isolated local ToolCall processes with Broker-side Brain split'
    LOCAL_TOOLS = frozenset(('skill_find', 'skill_load', 'read_file', 'write_file', 'execute_python'))
    # Brain-side tools that need authenticated network/DB/LLM/HITL access or pure
    # catalog/orchestration state. They run in the Broker so secrets and network
    # never enter the unprivileged per-ToolCall sandbox.
    BROKER_TOOLS = frozenset((
        'web_search', 'web_fetch',
        'context_search', 'context_read',
        'request_user_input',
        'skill_find', 'skill_load',
        'GeoImageAnalyze', 'GeoOpenAlexSearch',
        'update_todo', 'delegate_subagent', 'run_subagents_parallel', 'run_codeact',
    ))
    BROKER_ONLY_TOOLS = BROKER_TOOLS - LOCAL_TOOLS

    def __init__(self, runtime=None, limits=None, *, ownership_only=False, readonly_paths=None,
                 broker_tools_enabled=True, allow_extended_sandbox_tools=True):
        self.runtime = Path(runtime or sys.prefix).resolve()
        self.limits = limits or Limits()
        self.ownership_only = ownership_only is True
        self.readonly_paths = tuple(Path(p).resolve() for p in (readonly_paths or json.loads(
            os.environ.get('GEOTOOL_SANDBOX_READONLY_PATHS', '[]'))))
        dynamic = os.environ.get('GEOTOOL_DYNAMIC_PYTHON_ALLOWED', '1')
        if dynamic not in ('0', '1'):
            raise ValueError('GEOTOOL_DYNAMIC_PYTHON_ALLOWED must be 0 or 1')
        self.allow_dynamic_python = dynamic == '1'
        self.broker_tools_enabled = broker_tools_enabled is True
        self.allow_extended_sandbox_tools = allow_extended_sandbox_tools is True
        self.process_ownership = None
        self.process_scope_certified = True
        self.lock = RLock()
        self.active = {}

    def route_tool(self, tool_name):
        """Classify a tool into Brain ('broker'), Hands ('sandbox'), or 'denied'."""
        if tool_name == 'execute_python' and not self.allow_dynamic_python:
            return 'denied'
        if self.broker_tools_enabled and tool_name in self.BROKER_TOOLS:
            return 'broker'
        if tool_name in self.LOCAL_TOOLS:
            return 'sandbox'
        if self.allow_extended_sandbox_tools and tool_name not in self.BROKER_TOOLS:
            return 'sandbox'
        return 'denied'

    def command(self, rid, tool_invocation_id=None, *, execution_id=None, workspace=None):
        if sys.platform != 'linux' or not re.fullmatch(r'[a-f0-9]{32}', rid):
            raise RuntimeError('Team execution requires Linux and a server-generated job ID')
        if self.process_ownership is None or not self.ownership_only:
            raise RuntimeError('Verified candidate ownership is required; unmanaged execution is forbidden')
        if self.limits != Limits():
            raise RuntimeError('Custom resource quotas are unsupported in this ownership-only candidate')
        from .sandbox_process import tool_command
        data = self.process_ownership.load(execution_id)
        self.process_ownership._run_binding(data)
        if (data['run_id'] != rid or data['tool_invocation_id'] != tool_invocation_id
                or data['coverage'] != 'sandbox_tool' or data['phase'] != 'PREPARING'
                or Path(workspace).name != rid):
            raise RuntimeError('Sandbox command requires its exact registered ToolCall')
        return execution_id, tool_command(self, workspace)

    def stop(self, rid, tool_invocation_id=None):
        if self.process_ownership is None:
            raise RuntimeError('Unmanaged Sandbox stop is forbidden')
        run = self.process_ownership.recovery._load(rid)
        with self.lock:
            for (key, invocation), entry in self.active.items():
                if key == rid and (tool_invocation_id is None or invocation == tool_invocation_id):
                    entry['cancel'].set()
        if tool_invocation_id is None:
            return self.process_ownership.stop_run(run['uid'], rid)
        execution = self.process_ownership.tool_execution(run['uid'], rid, tool_invocation_id)
        return self.process_ownership.cleanup(execution)

    def execute_tool(self, rid, scope, call, context, *, broker_executor=None):
        if call.name == 'execute_python' and not self.allow_dynamic_python:
            from ..contracts import ToolResult, ErrorInfo
            return ToolResult(call.id, call.name, 'error', error=ErrorInfo('dynamic_python_disabled',
                'Dynamic Python is disabled by the execution policy.'))
        from .sandbox_process import execute_tool
        return execute_tool(self, rid, scope, call, context, broker_executor=broker_executor)

    def run(self, rid, query, files, cancel, model_call, on_trace, *, settings=None,
            mode='agent', diagnostics=None, memory_records=(), process_scope=None, skill_id=None, read_only=False):
        from .sandbox_process import run_agent
        if mode != 'agent':
            raise RuntimeError('Unsupported Sandbox mode; no unmanaged probe fallback')
        return run_agent(self, rid, query, files, cancel, model_call, on_trace,
            settings=settings, diagnostics=diagnostics, memory_records=memory_records,
            process_scope=process_scope, skill_id=skill_id, read_only=read_only)

"""Direct adapter for fixed isolated_cpu_bridge_v2 calls; ownership stays in the existing manager."""
from pathlib import Path
from threading import Event
import json
import os
import sys
import time

from .isolation import SandboxRunner
from ..geology import isolated_cpu_bridge_v2 as bridge


class CpuBridgeExecution:
    def __init__(self, runner, rid, scope, call, context, entry):
        self.runner, self.manager = runner, runner.process_ownership
        self.rid, self.scope, self.call, self.context, self.entry = rid, scope, call, context, entry
        self.registry = runner.cpu_profiles
        self.profile_id = runner.bridge_profiles[call.name]
        self.execution = None
        timeout = context.settings.tool_timeout_seconds
        self.deadline = min(context.deadline, time.monotonic() + timeout if timeout > 0 else float('inf'))

    def check(self):
        if self.context.cancel.is_set() or self.entry['cancel'].is_set():
            raise bridge.BridgeError('cancelled', 'The owned bridge ToolCall was stopped.')
        if time.monotonic() >= self.deadline:
            raise bridge.BridgeError('tool_timeout', 'The bridge ToolCall deadline exceeded.')

    def validate(self, name, args, output_dir, p, spec):
        self.check()
        bridge.need(name == self.call.name and p['tool'] == name, 'Bridge ToolCall identity mismatch.')
        bridge.need(spec['source_interface'].get('network_required') is False,
                    'Only fixed offline bridge calls are supported.', 'missing_dependency')
        workspace = self.context.workspace.resolve()
        private = Path(p['private_root']).resolve()
        recovery = self.manager.recovery.directory.resolve()
        jobs = (self.manager.recovery.store.root/'sandbox-jobs').resolve()
        bridge.need(not private.is_relative_to(recovery) and not recovery.is_relative_to(private)
                    and not private.is_relative_to(jobs), 'Bridge private jobs cannot overlap recovery or user workspaces.', 'invalid_path')
        for field in spec['source_interface'].get('path_fields', []):
            if field not in args:continue
            values = args[field] if isinstance(args[field], list) else [args[field]]
            for value in values:
                path = Path(value)
                if not path.is_absolute():path = Path(p['input_root']) / path
                bridge.no_links(path)
                bridge.need(path.resolve().is_relative_to(workspace), 'Bridge input belongs to another workspace.', 'invalid_path')
        if output_dir is not None:
            path = Path(output_dir).absolute();bridge.no_links(path)
            bridge.need(path.resolve().is_relative_to(workspace), 'Bridge output belongs to another workspace.', 'invalid_path')

    def command(self, command, job, p):
        # invoke() supplies a fully validated profile. Never accept a user command.
        config = bridge.strict_json(self.registry.read_bytes(), 1048576)
        bridge.need(config['profiles'].get(self.profile_id) == p and p['tool'] == self.call.name,
                    'Bridge profile changed or does not own this invocation.')
        expected = [p['python'], '-I', '-B', p['worker'], self.profile_id, str(job),
                    __import__('hashlib').sha256(self.registry.read_bytes()).hexdigest()]
        bridge.need(command == expected, 'Only the administrator-bound fixed worker command is permitted.')
        bwrap = Path(os.environ['GEOTOOL_TRUSTED_PROCESS_BWRAP'])
        bridge.need(bwrap.is_absolute() and bwrap.is_file(), 'An inspected candidate bubblewrap is required.')
        roots = list(dict.fromkeys([Path(p['source_root']), Path(p['python_prefix']), self.runner.runtime,
                                   *self.runner.readonly_paths, *[Path(v['root']) for v in p['projects'].values()]]))
        for root in roots:
            bridge.need(root.is_absolute() and root.is_dir() and root not in map(Path, ('/','/data','/home','/run'))
                        and not self.manager.recovery.directory.is_relative_to(root)
                        and not root.is_relative_to(self.manager.recovery.directory)
                        and not root.is_relative_to(self.manager.recovery.store.root/'sandbox-jobs'), 'Unsafe bridge runtime mount.')
        argv = [str(bwrap), '--unshare-user', '--uid', str(os.getuid()), '--gid', str(os.getgid()),
                '--unshare-pid', '--unshare-net', '--unshare-ipc', '--unshare-uts', '--unshare-cgroup',
                '--cap-drop', 'ALL', '--new-session', '--clearenv', '--ro-bind', '/usr', '/usr']
        for name in ['/lib','/lib64']:
            if Path(name).exists():argv += ['--ro-bind', name, name]
        for root in roots:argv += ['--ro-bind', str(root), str(root)]
        # These administrator roots need to exist for the original profile checks;
        # they expose no host files unless already in a reviewed read-only root.
        for key in ['private_root','input_root','output_root']:argv += ['--dir', p[key]]
        argv += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                 '--bind', str(job), str(job), '--ro-bind', str(job/'inputs'), str(job/'inputs'),
                 '--ro-bind', str(job/'control'), str(job/'control'), '--chdir', str(job/'inputs')]
        environment = bridge.private_environment(job)
        for key,value in environment.items():argv += ['--setenv',key,value]
        return argv + ['--', *command], environment

    def launch(self, command, job, p):
        self.check()
        if self.execution is not None:raise bridge.BridgeError('integrity_error', 'A ToolCall cannot launch twice.')
        self.execution = self.manager.prepare(self.scope['uid'], self.scope['cid'], self.rid,
            local_scope_certified=True, tool_invocation_id=self.call.id)
        self.manager.bind_tool_context(self.execution, self.context.run_id)
        self.entry['execution_id'] = self.execution
        command, environment = self.command(command, job, p)
        self.check()
        self.transport = self.manager.launch(self.execution, command, environment, cancel=self, stderr_pipe=True)
        return self.transport

    def is_set(self):
        return self.context.cancel.is_set() or self.entry['cancel'].is_set() or time.monotonic() >= self.deadline

    def finish(self):
        if self.execution is None:
            try:self.execution = self.manager.tool_execution(self.scope['uid'], self.rid, self.call.id, allow_preparing=True)
            except Exception:return
        receipt = self.manager.cleanup(self.execution)
        if receipt['cleanup_verified'] and not hasattr(self,'transport'):
            proc = self.manager.live.get(self.execution,{}).get('process')
            if proc is not None and proc.poll() is not None:
                for pipe in (proc.stdin,proc.stdout,proc.stderr):
                    if pipe is not None:pipe.close()
        if not receipt['cleanup_verified']:
            raise bridge.BridgeError('process_quarantined', 'Bridge end proof remains unresolved.',
                                     {'reason_code':receipt.get('reason_code','unknown')})


class IsolatedCpuBridgeRunner(SandboxRunner):
    """Explicit candidate configuration; the inherited five tool implementations are untouched."""
    def __init__(self, *args, cpu_profiles, tool_registry=None, **kwargs):
        super().__init__(*args, **kwargs)
        path = Path(cpu_profiles)
        if not path.is_absolute():raise ValueError('Bridge profile path must be administrator supplied and absolute')
        bridge.regular(path);config = bridge.strict_json(path.read_bytes(),1048576)
        bridge.closed(config,{'protocol','profiles'})
        bridge.need(config['protocol']==bridge.PROTOCOL and isinstance(config['profiles'],dict), 'Invalid bridge registry.')
        self.cpu_profiles = path.resolve()
        self.bridge_profiles = {}
        for profile_id,p in config['profiles'].items():
            name = p['tool']
            if name in self.LOCAL_TOOLS or name in self.bridge_profiles:raise ValueError('Ambiguous bridge ToolCall registration')
            self.bridge_profiles[name] = profile_id
        self.bridge_registry = tool_registry  # Trusted construction only, never an HTTP field.

    def execute_tool(self, rid, scope, call, context):
        if call.name not in self.bridge_profiles:return super().execute_tool(rid,scope,call,context)
        if self.process_ownership is None or not self.ownership_only or set(scope) != {'uid','cid'}:
            raise RuntimeError('Authenticated candidate bridge ownership is required')
        workspace = self.process_ownership.recovery.store.root / 'sandbox-jobs' / rid
        if context.workspace.resolve() != workspace.resolve():raise RuntimeError('Bridge workspace binding mismatch')
        from ..tools import ToolExecutor
        from legacy.ToolsAgent.ToolsFuns.source_contracts import definition
        spec = definition(call.name)
        bridge.need(spec.get('registration_metadata',{}).get('runtime',{}).get('isolation_profile_id')
                    == self.bridge_profiles[call.name], 'Canonical bridge profile binding mismatch.')
        bridge.need(spec['source_interface'].get('network_required') is False, 'Remote contracts are not local bridge calls.', 'missing_dependency')
        registry = self.bridge_registry
        if registry is None:
            from ..bootstrap import build_registry
            registry,_,_ = build_registry()
        entry = {'cancel':Event()}
        with self.lock:
            if (rid,call.id) in self.active:raise RuntimeError('Bridge ToolCall is already active')
            self.active[(rid,call.id)] = entry
        execution = CpuBridgeExecution(self,rid,scope,call,context,entry)
        try:
            with bridge.bind_execution(execution):return ToolExecutor(registry)._execute(call,context)
        finally:
            try:execution.finish()
            finally:
                with self.lock:self.active.pop((rid,call.id),None)
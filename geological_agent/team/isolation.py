"""Fail-closed Linux job runner. The host does not execute worker tool requests."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
from threading import Event, Thread
import time

from ..contracts import ModelRequest
from .protocol import MAX_PACKET, decode, dumps, encode, file_packet, unpack_files


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
    description = 'isolated Linux job'

    def __init__(self, runtime=None, limits=None):
        self.runtime = Path(runtime or sys.prefix).resolve()
        self.limits = limits or Limits()
        self.units = set()

    def command(self, rid):
        if sys.platform != 'linux' or not re.fullmatch(r'[a-f0-9]{32}', rid):
            raise RuntimeError('Team execution requires Linux and a server-generated job ID')
        if not (self.runtime / 'pyvenv.cfg').is_file():
            raise RuntimeError('Install the team release in a dedicated, non-editable virtual environment')
        required = {name: shutil.which(name) for name in ('bwrap', 'systemd-run', 'systemctl')}
        if not all(required.values()):
            raise RuntimeError('Bubblewrap and the systemd user manager are required; host execution is forbidden')
        unit = 'geotoolagent-job-' + rid
        command = [required['systemd-run'], '--user', '--quiet', '--wait', '--pipe', '--collect', '--unit', unit,
                   '-p', 'MemoryMax=' + self.limits.memory, '-p', 'MemorySwapMax=0',
                   '-p', 'TasksMax=' + str(self.limits.tasks), '-p', 'CPUQuota=' + self.limits.cpu,
                   '-p', 'KillMode=control-group', '-p', 'TimeoutStopSec=5', '-p', 'UMask=0077',
                   '-p', 'NoNewPrivileges=yes', required['bwrap'],
                   '--unshare-user', '--unshare-ipc', '--unshare-pid', '--unshare-net', '--unshare-uts',
                   '--unshare-cgroup', '--disable-userns', '--cap-drop', 'ALL', '--die-with-parent',
                   '--new-session', '--clearenv', '--ro-bind', '/usr', '/usr']
        parent = os.environ.get('GEOTOOL_TEAM_UNIT', '')
        if parent:
            if not re.fullmatch(r'[a-zA-Z0-9_.@-]+\.service', parent):
                raise RuntimeError('Invalid parent service unit')
            position = command.index(required['bwrap'])
            command[position:position] = ['-p', 'PartOf=' + parent]
        for path in ('/lib', '/lib64'):
            if Path(path).exists():
                command += ['--ro-bind', path, path]
        command += ['--dir', '/opt', '--ro-bind', str(self.runtime), '/opt/runtime',
                    '--proc', '/proc', '--dev', '/dev', '--dir', '/etc',
                    '--size', str(self.limits.work_bytes), '--tmpfs', '/work',
                    '--size', str(self.limits.temp_bytes), '--tmpfs', '/tmp',
                    '--setenv', 'PATH', '/opt/runtime/bin:/usr/bin', '--setenv', 'HOME', '/work',
                    '--setenv', 'LANG', 'C.UTF-8', '--setenv', 'PYTHONDONTWRITEBYTECODE', '1',
                    '--setenv', 'OPENBLAS_NUM_THREADS', '1', '--setenv', 'OMP_NUM_THREADS', '1',
                    '--chdir', '/work', '/opt/runtime/bin/python', '-I', '-m', 'geological_agent.team.worker']
        return unit, command

    def stop(self, rid):
        if re.fullmatch(r'[a-f0-9]{32}', rid) and sys.platform == 'linux':
            subprocess.run(['systemctl', '--user', 'stop', 'geotoolagent-job-' + rid + '.service'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12, check=False)

    def run(self, rid, query, files, cancel, model_call, on_trace, *, settings=None, mode='agent', diagnostics=None, memory_records=()):
        unit, command = self.command(rid)
        incoming, reader_done = queue.Queue(maxsize=32), Event()
        # Credentials stay in the broker and are not inherited even by systemd-run.
        environment = {key: os.environ[key] for key in ('PATH', 'HOME', 'USER', 'LOGNAME', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS') if key in os.environ}
        stderr_file = open(diagnostics, 'ab', buffering=0) if diagnostics else None
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
        self.units.add(rid)

        def put(item):
            while not reader_done.is_set():
                try:
                    incoming.put(item, timeout=0.2)
                    return
                except queue.Full:
                    continue

        def read_packets():
            try:
                transferred = 0
                while not reader_done.is_set():
                    raw = proc.stdout.readline(MAX_PACKET + 1)
                    if not raw:
                        break
                    if len(raw) > MAX_PACKET or not raw.endswith(b'\n'):
                        raise ValueError('Invalid worker packet; nothing was silently truncated')
                    transferred += len(raw)
                    if transferred > self.limits.protocol_bytes:
                        raise ValueError('Run IPC quota exceeded. Execution stopped explicitly; the last packet was not accepted.')
                    packet = json.loads(raw)
                    if not isinstance(packet, dict):
                        raise ValueError('Worker packets must be objects')
                    put(packet)
            except Exception as exc:
                put({'kind': 'failure', 'message': str(exc)})
            finally:
                put({'kind': 'eof'})

        def read_diagnostics():
            size = 0
            while not reader_done.is_set():
                raw = proc.stderr.read1(8192)
                if not raw:
                    return
                size += len(raw)
                if size > self.limits.diagnostic_bytes:
                    put({'kind': 'failure', 'message': 'Diagnostic output exceeded its 64 MiB safety quota. The run was stopped, not silently truncated.'})
                    try:
                        self.stop(rid)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                    return
                if stderr_file:
                    stderr_file.write(raw)

        def watch_cancel():
            while not reader_done.wait(0.1):
                if cancel.is_set():
                    try:
                        self.stop(rid)
                    except subprocess.TimeoutExpired:
                        pass
                    return

        Thread(target=read_packets, daemon=True).start()
        diagnostics_thread = Thread(target=read_diagnostics, daemon=True)
        diagnostics_thread.start()
        Thread(target=watch_cancel, daemon=True).start()
        try:
            from ..memory import SnapshotMemoryStore
            SnapshotMemoryStore.from_payload(memory_records)
            proc.stdin.write(dumps({'query': query, 'files': [file_packet(k, v) for k, v in files.items()], 'settings': settings or {}, 'mode': mode,
                                   'memory_records': list(memory_records)}))
            proc.stdin.flush()
            while True:
                if cancel.is_set():
                    raise Cancelled('Stopped. The last committed files are retained; in-flight task changes were not committed.')
                try:
                    packet = incoming.get(timeout=0.2)
                except queue.Empty:
                    continue
                kind = packet.get('kind')
                if kind == 'model':
                    if mode != 'agent' or not isinstance(packet.get('id'), int):
                        raise ValueError('Unexpected model request')
                    request = decode(packet['request'])
                    if not isinstance(request, ModelRequest):
                        raise ValueError('Invalid native model request')
                    reply = {'id': packet['id']}
                    try:
                        reply['response'] = encode(model_call(request, cancel))
                    except Cancelled:
                        raise
                    except Exception as exc:
                        reply['error'] = f'{type(exc).__name__}: {exc}'
                    if cancel.is_set():
                        raise Cancelled('Stopped by user')
                    proc.stdin.write(dumps(reply))
                    proc.stdin.flush()
                elif kind == 'trace':
                    event, fields = packet.get('event'), decode(packet.get('fields', {}))
                    if not isinstance(event, str) or not isinstance(fields, dict):
                        raise ValueError('Invalid trace packet')
                    on_trace(event, fields)
                elif kind == 'done':
                    result = packet.get('result', {})
                    if result.get('status') not in {'completed', 'incomplete', 'needs_input', 'failed', 'stopped', 'budget_exhausted'} or not isinstance(result.get('answer'), str):
                        raise ValueError('Invalid completion result')
                    result['files'] = unpack_files(packet.get('files', []))
                    return result
                elif kind in ('failure', 'eof'):
                    raise RuntimeError(packet.get('message') or 'Task worker exited before committing a result; inspect its private diagnostic log')
                else:
                    raise ValueError('Unknown worker message')
        finally:
            reader_done.set()
            try:
                self.stop(rid)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
            proc.stdin.close()
            proc.stdout.close()
            diagnostics_thread.join(timeout=2)
            proc.stderr.close()
            self.units.discard(rid)
            if stderr_file:
                stderr_file.close()

"""Runs INSIDE Bubblewrap. It never receives model or tracing credentials."""
from contextlib import nullcontext
import json
import os
from pathlib import Path
import stat
import sys
from threading import Lock

from ..bootstrap import create_agent
from ..contracts import ModelEvent, ModelResponse
from ..settings import Settings
from .protocol import MAX_PACKET, MAX_FILE, MAX_FILES_TOTAL, decode, dumps, encode, file_packet, relative_name, unpack_files

OUTPUT = None
OUTPUT_LOCK = Lock()


def send(packet):
    with OUTPUT_LOCK:
        OUTPUT.write(dumps(packet))
        OUTPUT.flush()


def receive():
    raw = sys.stdin.buffer.readline(MAX_PACKET + 1)
    if not raw or len(raw) > MAX_PACKET or not raw.endswith(b"\n"):
        raise ValueError("Invalid or oversized broker message")
    return json.loads(raw)


class BrokerModel:
    def __init__(self):
        self.sequence = 0

    def invoke(self, request):
        self.sequence += 1
        send({"kind": "model", "id": self.sequence, "request": encode(request)})
        reply = receive()
        if reply.get("id") != self.sequence:
            raise ValueError("Mismatched model reply")
        if reply.get("error"):
            raise RuntimeError(reply["error"])
        result = decode(reply["response"])
        if not isinstance(result, ModelResponse):
            raise ValueError("Invalid model response")
        return result

    def stream(self, request):
        # The core publishes only reviewed answers, not unreviewed draft tokens.
        yield ModelEvent("response", response=self.invoke(request))


class BrokerTrace:
    def emit(self, event, **fields):
        send({"kind": "trace", "event": event, "fields": encode(fields)})

    def execution_context(self):
        return nullcontext()


def snapshot(root):
    files, total = [], 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if name != ".agent" and not (Path(directory) / name).is_symlink()]
        for name in sorted(names):
            path = Path(directory) / name
            relative = relative_name(path.relative_to(root).as_posix())
            if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError("Output contains a non-regular file: " + relative)
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
            with os.fdopen(descriptor, "rb") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise ValueError("Output changed type during export")
                data = handle.read(MAX_FILE + 1)
            total += len(data)
            if total > MAX_FILES_TOTAL or len(files) >= 1024:
                raise ValueError("Output snapshot exceeds its explicit transfer quota")
            files.append(file_packet(relative, data))
    return files


def isolation_probe():
    """Acceptance-only mode; not exposed by the HTTP API."""
    import socket
    report = {"uid": os.getuid(), "files": sorted(p.name for p in Path('/work').iterdir()),
              "host_home_visible": Path('/data/wangjian').exists(),
              "gpu_visible": Path('/dev/nvidia0').exists(),
              "credentials_visible": any(k in os.environ for k in ('LANGSMITH_API_KEY', 'GEOTOOL_MODEL_KEY', 'WORKSPACE_MODEL_KEY')),
              "network_reachable": False, "runtime_writable": False}
    try:
        with socket.create_connection(('1.1.1.1', 443), timeout=1):
            report['network_reachable'] = True
    except OSError:
        pass
    try:
        Path('/opt/runtime/should-not-write').write_text('forbidden')
        report['runtime_writable'] = True
    except OSError:
        pass
    Path('/work/isolation-report.json').write_text(json.dumps(report), encoding='utf-8')
    return report


def main():
    global OUTPUT
    OUTPUT = os.fdopen(os.dup(1), "wb", buffering=0)
    sys.stdout = sys.stderr
    initial = receive()
    root = Path('/work')
    for name, data in unpack_files(initial.get('files', [])).items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    try:
        if initial.get('mode') == 'probe':
            result = {"status": "completed", "answer": json.dumps(isolation_probe()), "reason": "", "turns": 0}
        else:
            settings = Settings(**initial.get('settings', {}))
            from ..memory import SnapshotMemoryStore
            agent = create_agent(BrokerModel(), settings=settings, trace_factory=lambda *args: BrokerTrace(),
                                 memory=SnapshotMemoryStore.from_payload(initial.get('memory_records', [])))
            outcome = agent.run(initial['query'], workspace=root)
            result = {"status": outcome.status, "answer": outcome.answer, "reason": outcome.reason or "", "turns": outcome.model_turns}
        # Publish files and completion together; the host commits a complete snapshot.
        send({"kind": "done", "result": result, "files": snapshot(root)})
    except Exception as exc:
        send({"kind": "failure", "message": f"{type(exc).__name__}: {exc}"})
        raise SystemExit(1)


if __name__ == '__main__':
    main()

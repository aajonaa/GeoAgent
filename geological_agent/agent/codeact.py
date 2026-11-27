"""Programmatic Tool Calling (CodeAct) inside strict bubblewrap sandbox.

Allows the agent to write one Python orchestration script that invokes currently
exposed OreBOGAO tools programmatically via an injected `tools` proxy:
  - `tools.list()` -> callable tool names
  - `tools.call(name, arguments)` / `tools.<ToolName>(**kwargs)` -> validated tool data
  - `tools.batch([(name, arguments), ...])` -> parallel-safe batch execution

Security & provenance design:
- On Linux with bubblewrap configured, the Python script runs inside strict
  `--unshare-user --unshare-pid --unshare-net --cap-drop ALL --clearenv` bwrap.
- Tool RPC calls travel over an inherited anonymous `AF_UNIX` `socketpair` fd
  (zero network exposure, zero credentials inside sandbox).
- Every `tools.call(...)` executes in the parent Broker's `ToolExecutor` with full
  Draft 2020-12 schema validation, `EvidenceLedger` provenance, `pure_cache`,
  cancellation/deadline checks, recursion blocking, and a hard `max_tool_calls` cap.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import socket
import subprocess
import sys
from threading import Lock, Thread
import time
import uuid

from ..contracts import ToolCall
from ..sandbox_exec import build_bwrap_command, collect_python_runtime_roots, python_sandbox_mode, resolve_bwrap
from ..tools import Tool, ToolDefinition, ToolFailure, ToolOutput, _files, _kill, artifact, object_schema

BLOCKED_CODEACT_TOOLS = frozenset({
    "run_codeact",
    "execute_python",
    "request_user_input",
    "delegate_subagent",
    "run_subagents_parallel",
    "skill_load",
})

PARALLEL_SAFE_NAMES = frozenset({
    "read_file",
    "web_search",
    "web_fetch",
    "context_search",
    "context_read",
    "skill_find",
    "GeoOpenAlexSearch",
})

MAX_RPC_LINE_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_TOOL_CALLS = 25
HARD_MAX_TOOL_CALLS = 50
MAX_BATCH_SIZE = 16


class CodeActBridge:
    """Broker-side RPC dispatcher mediating tool calls from a sandboxed CodeAct script."""

    def __init__(
        self,
        *,
        executor,
        allowed_tools: tuple[str, ...] | list[str],
        trace=None,
        parent_run_id: str = "",
        activity=None,
        max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
    ):
        self.executor = executor
        self.allowed_tools = tuple(dict.fromkeys(allowed_tools))
        self.callable_tools = tuple(name for name in self.allowed_tools if name not in BLOCKED_CODEACT_TOOLS)
        self.trace = trace
        self.parent_run_id = parent_run_id
        self.activity = activity
        self.default_max_calls = max(1, min(int(max_tool_calls), HARD_MAX_TOOL_CALLS))

    def _is_parallel_safe(self, tool_name: str) -> bool:
        if tool_name in PARALLEL_SAFE_NAMES:
            return True
        try:
            tool = self.executor.registry.peek(tool_name)
        except Exception:
            return False
        return bool(tool.pure and not tool.input_paths)

    def make_session(self, ctx, *, max_tool_calls: int | None = None):
        limit = self.default_max_calls if max_tool_calls is None else max(1, min(int(max_tool_calls), HARD_MAX_TOOL_CALLS))
        return _CodeActSession(self, ctx, max_tool_calls=limit)


class _CodeActSession:
    def __init__(self, bridge: CodeActBridge, ctx, *, max_tool_calls: int):
        self.bridge = bridge
        self.ctx = ctx
        self.max_tool_calls = max_tool_calls
        self._lock = Lock()
        self.call_count = 0
        self.records: list[dict] = []
        self.artifacts: dict[str, object] = {}

    def _sub_context(self):
        return replace(self.ctx, allowed_tool_names=self.bridge.callable_tools, codeact_bridge=None, subagent_runner=None)

    def _reserve_calls(self, n: int) -> bool:
        with self._lock:
            if self.call_count + n > self.max_tool_calls:
                return False
            self.call_count += n
            return True

    def _validate_call(self, name, arguments) -> dict | None:
        if not isinstance(name, str) or not name:
            return {"ok": False, "code": "invalid_tool_name", "message": "Tool name must be a non-empty string", "retryable": False}
        if name in BLOCKED_CODEACT_TOOLS:
            return {
                "ok": False,
                "code": "tool_blocked_in_codeact",
                "message": f"Tool '{name}' cannot be invoked from inside run_codeact.",
                "retryable": False,
            }
        if name not in self.bridge.callable_tools:
            return {
                "ok": False,
                "code": "tool_not_exposed",
                "message": f"Tool '{name}' is not currently exposed in this run. Use skill_find/skill_load first.",
                "retryable": True,
            }
        if not isinstance(arguments, dict):
            return {"ok": False, "code": "invalid_arguments", "message": "Tool arguments must be a JSON object", "retryable": False}
        return None

    def _invoke_one(self, name: str, arguments) -> dict:
        rejected = self._validate_call(name, arguments)
        if rejected is not None:
            return rejected

        try:
            self.ctx.check()
        except ToolFailure as exc:
            return {"ok": False, "code": exc.error.code, "message": exc.error.message, "retryable": exc.error.retryable}

        call_id = "ca_" + uuid.uuid4().hex[:12]
        t0 = time.monotonic()
        result = self.bridge.executor.execute(ToolCall(call_id, name, arguments), self._sub_context())
        elapsed_ms = round((time.monotonic() - t0) * 1000, 1)

        rec = {
            "call_id": call_id,
            "name": name,
            "status": result.status,
            "cached": result.cached,
            "elapsed_ms": elapsed_ms,
        }
        if result.error is not None:
            rec["error_code"] = result.error.code
        with self._lock:
            self.records.append(rec)
            for art in result.artifacts:
                self.artifacts[art.path] = art
        if self.bridge.trace is not None:
            self.bridge.trace.emit("codeact_tool_call", run_id=self.bridge.parent_run_id, **rec)
        if self.bridge.activity is not None:
            self.bridge.activity("codeact_tool_call", name=name, status=result.status)

        if result.status == "ok":
            return {
                "ok": True,
                "call_id": call_id,
                "data": result.data,
                "artifacts": [a.path for a in result.artifacts],
                "cached": result.cached,
            }
        err = result.error
        return {
            "ok": False,
            "call_id": call_id,
            "code": err.code if err else "tool_error",
            "message": err.message if err else "Tool execution failed",
            "retryable": err.retryable if err else False,
        }

    def handle_request(self, req: dict) -> dict:
        if not isinstance(req, dict):
            return {"ok": False, "code": "invalid_rpc", "message": "RPC request must be a JSON object"}
        op = req.get("op")
        if op == "list":
            return {"ok": True, "tools": list(self.bridge.callable_tools), "remaining_calls": self.max_tool_calls - self.call_count}
        if op == "call":
            name, arguments = req.get("name"), req.get("arguments", {})
            rejected = self._validate_call(name, arguments)
            if rejected is not None:
                return rejected
            if not self._reserve_calls(1):
                return {
                    "ok": False,
                    "code": "codeact_call_limit",
                    "message": f"Exceeded run_codeact tool call limit ({self.max_tool_calls}).",
                    "retryable": False,
                }
            return self._invoke_one(name, arguments)
        if op == "batch":
            raw_calls = req.get("calls")
            if not isinstance(raw_calls, list) or not 1 <= len(raw_calls) <= MAX_BATCH_SIZE:
                return {"ok": False, "code": "invalid_batch", "message": f"Batch must contain 1 to {MAX_BATCH_SIZE} calls"}
            if not self._reserve_calls(len(raw_calls)):
                return {
                    "ok": False,
                    "code": "codeact_call_limit",
                    "message": f"Batch exceeds run_codeact tool call limit ({self.max_tool_calls}).",
                    "retryable": False,
                }
            parsed = []
            for item in raw_calls:
                if not isinstance(item, dict):
                    return {"ok": False, "code": "invalid_batch", "message": "Each batch item must be {name, arguments}"}
                parsed.append((item.get("name"), item.get("arguments", {})))
            all_parallel = (
                len(parsed) >= 2
                and self.bridge.executor.execution_adapter is None
                and all(isinstance(n, str) and n in self.bridge.callable_tools and self.bridge._is_parallel_safe(n) for n, _ in parsed)
            )
            if all_parallel:
                with ThreadPoolExecutor(max_workers=min(4, len(parsed))) as pool:
                    futs = [pool.submit(self._invoke_one, n, a) for n, a in parsed]
                    results = [f.result() for f in futs]
            else:
                results = [self._invoke_one(n, a) for n, a in parsed]
            return {"ok": True, "results": results, "parallel": all_parallel}
        return {"ok": False, "code": "unknown_op", "message": f"Unknown CodeAct RPC op: {op!r}"}


_CODEACT_RUNNER = r'''import json
import os
from pathlib import Path
import socket
import sys

program = Path(sys.argv[1])
transport = sys.argv[2]
target = sys.argv[3]
package_paths = json.loads(sys.argv[4]) if len(sys.argv) > 4 else []
if package_paths:
    sys.path.extend(package_paths)


class CodeActToolError(RuntimeError):
    def __init__(self, code, message, retryable=False):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.retryable = retryable


if transport == "fd":
    sock = socket.fromfd(int(target), socket.AF_UNIX, socket.SOCK_STREAM)
    auth_token = None
elif transport == "tcp":
    host, port = target.rsplit(":", 1)
    sock = socket.create_connection((host, int(port)), timeout=15)
    auth_token = os.environ.pop("CODEACT_RPC_TOKEN", "")
else:
    raise RuntimeError(f"Unsupported CodeAct RPC transport: {transport}")

_rpc_file = sock.makefile("rwb", buffering=0)


def _rpc(payload):
    if auth_token is not None:
        payload = {**payload, "_token": auth_token}
    raw = (json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    _rpc_file.write(raw)
    _rpc_file.flush()
    line = _rpc_file.readline(4 * 1024 * 1024 + 1)
    if not line:
        raise CodeActToolError("rpc_closed", "CodeAct broker closed RPC connection")
    return json.loads(line.decode("utf-8"))


class _ToolsProxy:
    def list(self):
        res = _rpc({"op": "list"})
        if not res.get("ok"):
            raise CodeActToolError(res.get("code", "rpc_error"), res.get("message", "list failed"))
        return list(res["tools"])

    def call(self, name, arguments=None):
        res = _rpc({"op": "call", "name": name, "arguments": {} if arguments is None else arguments})
        if not res.get("ok"):
            raise CodeActToolError(res.get("code", "tool_error"), res.get("message", "tool failed"), bool(res.get("retryable")))
        return res["data"]

    def batch(self, calls):
        normalized = []
        for item in calls:
            if isinstance(item, (tuple, list)) and len(item) == 2:
                normalized.append({"name": item[0], "arguments": item[1] or {}})
            elif isinstance(item, dict) and "name" in item:
                normalized.append({"name": item["name"], "arguments": item.get("arguments") or {}})
            else:
                raise ValueError("Each batch entry must be (tool_name, args_dict) or {'name': ..., 'arguments': ...}")
        res = _rpc({"op": "batch", "calls": normalized})
        if not res.get("ok"):
            raise CodeActToolError(res.get("code", "batch_error"), res.get("message", "batch failed"))
        return res["results"]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        def _bound(**kwargs):
            return self.call(name, kwargs)
        return _bound


tools = _ToolsProxy()
ns = {
    "__name__": "__main__",
    "__file__": str(program),
    "tools": tools,
    "CodeActToolError": CodeActToolError,
}
source = program.read_text(encoding="utf-8")
try:
    exec(compile(source, str(program), "exec"), ns, ns)
finally:
    try:
        _rpc_file.close()
    except Exception:
        pass
    try:
        sock.close()
    except Exception:
        pass
'''


def _serve_rpc_socket(conn_sock: socket.socket, session: _CodeActSession, *, expected_token: str | None = None):
    try:
        with conn_sock.makefile("rwb", buffering=0) as stream:
            while True:
                line = stream.readline(MAX_RPC_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_RPC_LINE_BYTES:
                    reply = {"ok": False, "code": "rpc_payload_too_large", "message": "RPC request too large"}
                else:
                    try:
                        req = json.loads(line.decode("utf-8"))
                    except (ValueError, UnicodeError):
                        reply = {"ok": False, "code": "invalid_json", "message": "Invalid JSON RPC line"}
                    else:
                        if expected_token is not None:
                            tok = req.pop("_token", None) if isinstance(req, dict) else None
                            if not isinstance(tok, str) or not secrets.compare_digest(tok, expected_token):
                                reply = {"ok": False, "code": "unauthorized_rpc", "message": "Invalid RPC token"}
                                stream.write((json.dumps(reply) + "\n").encode("utf-8"))
                                stream.flush()
                                break
                        reply = session.handle_request(req)
                stream.write((json.dumps(reply, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))
                stream.flush()
    except OSError:
        pass
    finally:
        try:
            conn_sock.close()
        except Exception:
            pass


def run_codeact(args, ctx):
    """Execute a CodeAct Python orchestration script with programmatic Broker-mediated tool access."""
    bridge = getattr(ctx, "codeact_bridge", None)
    if bridge is None:
        raise ToolFailure("codeact_unavailable", "CodeAct orchestration is not enabled in this execution context.")

    package_paths = []
    for value in os.environ.get("GEOTOOL_PYTHON_PACKAGES", "").split(os.pathsep):
        if not value:
            continue
        path = Path(value)
        resolved = path.resolve()
        work = ctx.workspace.resolve()
        if (not path.is_absolute() or not resolved.is_dir()
                or resolved.is_relative_to(work) or work.is_relative_to(resolved)):
            raise ToolFailure("python_environment_config", "Configured Python dependency directory is unavailable or overlaps the task workspace")
        package_paths.append(str(resolved))

    try:
        sandbox_policy = python_sandbox_mode()
    except ValueError as exc:
        raise ToolFailure("sandbox_configuration", str(exc)) from exc
    bwrap_path = resolve_bwrap() if (sys.platform == "linux" and sandbox_policy != "off") else None
    if sandbox_policy in ("required", "bwrap") and bwrap_path is None:
        raise ToolFailure(
            "sandbox_unavailable",
            "Strict sandbox (bubblewrap) is required by GEOTOOL_PYTHON_SANDBOX for run_codeact but no valid bwrap executable is available.",
        )

    max_calls = args.get("max_tool_calls")
    session = bridge.make_session(ctx, max_tool_calls=max_calls)

    before = _files(ctx)
    folder = ctx.path(".agent/codeact/" + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    code_path = folder / "program.py"
    code_path.write_text(args["code"], encoding="utf-8")
    runner_path = folder / "runner.py"
    runner_path.write_text(_CODEACT_RUNNER, encoding="utf-8")
    out_path, err_path = folder / "stdout.txt", folder / "stderr.txt"

    use_unix_pair = hasattr(socket, "AF_UNIX") and os.name != "nt"
    parent_sock = child_sock = listen_sock = None
    rpc_thread = None
    pass_fds = ()
    rpc_token = None

    if use_unix_pair:
        parent_sock, child_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        os.set_inheritable(child_sock.fileno(), True)
        pass_fds = (child_sock.fileno(),)
        transport_kind = "fd"
        transport_target = str(child_sock.fileno())
        rpc_thread = Thread(target=_serve_rpc_socket, args=(parent_sock, session), daemon=True)
        rpc_thread.start()
    else:
        listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listen_sock.bind(("127.0.0.1", 0))
        listen_sock.listen(1)
        listen_sock.settimeout(15.0)
        port = listen_sock.getsockname()[1]
        rpc_token = secrets.token_hex(32)
        transport_kind = "tcp"
        transport_target = f"127.0.0.1:{port}"

        def _accept_and_serve():
            try:
                conn, _ = listen_sock.accept()
            except OSError:
                return
            _serve_rpc_socket(conn, session, expected_token=rpc_token)

        rpc_thread = Thread(target=_accept_and_serve, daemon=True)
        rpc_thread.start()

    try:
        if bwrap_path is not None:
            work_root = ctx.workspace.resolve()
            rel_folder = folder.resolve().relative_to(work_root).as_posix()
            c_folder = PurePosixPath("/work") / rel_folder
            py_cmd = [
                sys.executable, "-I",
                str(c_folder / "runner.py"),
                str(c_folder / "program.py"),
                transport_kind,
                transport_target,
                json.dumps(package_paths),
            ]
            readonly_roots = collect_python_runtime_roots(sys.executable, extra_readonly=package_paths)
            sandbox_env = {
                "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
                "HOME": "/work",
                "TMPDIR": "/tmp",
                "LANG": "C.UTF-8",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "MPLBACKEND": "Agg",
                "MPLCONFIGDIR": str(c_folder / "matplotlib"),
                "OPENBLAS_NUM_THREADS": os.environ.get("OPENBLAS_NUM_THREADS", "1"),
                "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS", "1"),
            }
            command = build_bwrap_command(
                bwrap_path,
                work_root,
                py_cmd,
                readonly_roots=readonly_roots,
                env=sandbox_env,
            )
            env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
            sandbox_mode = "bwrap_strict"
        else:
            env = {
                k: v for k, v in os.environ.items()
                if not any(word in k.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTHORIZATION"))
            }
            env.update(
                PYTHONIOENCODING="utf-8",
                PYTHONUNBUFFERED="1",
                MPLBACKEND="Agg",
                MPLCONFIGDIR=str(folder / "matplotlib"),
            )
            if rpc_token is not None:
                env["CODEACT_RPC_TOKEN"] = rpc_token
            command = [
                sys.executable, "-I",
                str(runner_path),
                str(code_path),
                transport_kind,
                transport_target,
                json.dumps(package_paths),
            ]
            sandbox_mode = "trusted_local"

        stopped = None
        with out_path.open("wb") as out, err_path.open("wb") as err:
            options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
            if pass_fds:
                options["pass_fds"] = pass_fds
            process = subprocess.Popen(command, cwd=ctx.workspace, env=env, stdout=out, stderr=err, **options)
            if child_sock is not None:
                child_sock.close()
                child_sock = None
            try:
                while process.poll() is None:
                    ctx.check()
                    time.sleep(0.03)
            except (ToolFailure, KeyboardInterrupt) as exc:
                _kill(process)
                if isinstance(exc, KeyboardInterrupt):
                    raise
                stopped = exc
    finally:
        if child_sock is not None:
            child_sock.close()
        if listen_sock is not None:
            listen_sock.close()
        if rpc_thread is not None:
            rpc_thread.join(timeout=2.0)

    def _read_bounded(p: Path) -> str:
        with p.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(ctx.settings.max_tool_output_chars)

    after = _files(ctx)
    merged_artifacts = dict(session.artifacts)
    for name, stamp in after.items():
        if before.get(name) != stamp:
            merged_artifacts[name] = artifact(ctx.path(name), ctx)
    artifacts = tuple(merged_artifacts.values())

    data = {
        "stdout": _read_bounded(out_path),
        "stderr": _read_bounded(err_path),
        "return_code": process.returncode,
        "code_path": code_path.relative_to(ctx.workspace).as_posix(),
        "sandbox_mode": sandbox_mode,
        "tool_call_count": len(session.records),
        "tool_calls": session.records,
    }
    if stopped:
        raise ToolFailure(stopped.error.code, stopped.error.message, outcome_unknown=True, data=data, artifacts=artifacts)
    if process.returncode != 0:
        raise ToolFailure("codeact_error", "CodeAct script failed. Inspect stderr and tool_calls before retrying.", retryable=True, data=data, artifacts=artifacts)
    return ToolOutput(data, artifacts)


def register_codeact_tool(registry):
    text = {"type": "string"}
    in_schema = object_schema({
        "code": {
            **text,
            "pattern": r"^[\s\S]+$",
            "description": (
                "Python orchestration script executed in the sandbox with an injected `tools` proxy "
                "(`tools.list()`, `tools.call(name, args)`, `tools.<ToolName>(**kwargs)`, `tools.batch([(name, args), ...])`). "
                "Use for loops, parameter sweeps, multi-tool filtering/aggregation, and saving final tables/plots in one turn."
            ),
        },
        "max_tool_calls": {
            "type": "integer",
            "minimum": 1,
            "maximum": HARD_MAX_TOOL_CALLS,
            "description": "Optional per-script cap on Broker tool invocations (default 25, max 50).",
        },
    }, ["code"])
    out_schema = object_schema({
        "stdout": text,
        "stderr": text,
        "return_code": {"type": "integer"},
        "code_path": text,
        "sandbox_mode": text,
        "tool_call_count": {"type": "integer"},
        "tool_calls": {"type": "array", "items": {"type": "object"}},
    }, ["stdout", "stderr", "return_code", "code_path", "sandbox_mode", "tool_call_count", "tool_calls"])
    registry.register(Tool(
        ToolDefinition(
            "run_codeact",
            "Run a sandboxed Python script that programmatically calls exposed native tools (`tools.call`, `tools.batch`, `tools.<Name>`) via the Broker.",
            "Use when chaining multiple tool calls in loops/sweeps, filtering large intermediate outputs in code, or combining tool results with Python analysis/plotting in a single turn.",
            in_schema,
            out_schema,
        ),
        run_codeact,
    ))
    return ("run_codeact",)

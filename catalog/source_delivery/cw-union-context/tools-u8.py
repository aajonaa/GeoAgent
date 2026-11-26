from dataclasses import dataclass, field, replace
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import signal
import subprocess
import sys
from threading import Event
import time
from typing import Callable
import uuid
from jsonschema import Draft202012Validator, ValidationError
from .contracts import ArtifactRef, ErrorInfo, ToolCall, ToolResult, strict_json
from .settings import Settings


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    when_to_use: str
    input_schema: dict
    result_schema: dict


@dataclass(frozen=True)
class ToolOutput:
    data: dict
    artifacts: tuple[ArtifactRef, ...] = ()


@dataclass(frozen=True)
class Tool:
    definition: ToolDefinition
    handler: Callable
    pure: bool = False
    input_paths: tuple[str, ...] = ()
    reference_paths: tuple[str, ...] = ()


class ToolFailure(Exception):
    def __init__(self, code, message, *, retryable=False, outcome_unknown=False, data=None, artifacts=()):
        super().__init__(message)
        self.error = ErrorInfo(code, message, retryable, outcome_unknown)
        self.data = data or {}
        self.artifacts = tuple(artifacts)


@dataclass
class ToolExecutionContext:
    run_id: str
    workspace: Path
    allowed_tool_names: tuple[str, ...]
    settings: Settings
    cancel: Event
    call_id: str = ""
    deadline: float = float("inf")
    pure_cache: dict = field(default_factory=dict)
    evidence_state: dict = field(default_factory=dict)
    vision_invoke: Callable | None = None

    def check(self):
        if self.cancel.is_set():
            raise ToolFailure("cancelled", "Execution was stopped")
        if time.monotonic() >= self.deadline:
            raise ToolFailure("tool_timeout", "Tool deadline exceeded; inspect state before retrying", outcome_unknown=True)

    def path(self, relative: str) -> Path:
        candidate = Path(relative)
        if candidate.is_absolute() or not relative or "\\" in relative or ":" in relative:
            raise ToolFailure("invalid_path", "Use a workspace-relative path with forward slashes", retryable=True)
        target = (self.workspace / candidate).resolve()
        if not target.is_relative_to(self.workspace.resolve()):
            raise ToolFailure("invalid_path", "Path escapes the workspace", retryable=True)
        return target


class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, tool: Tool):
        name = tool.definition.name
        if name in self._tools:
            raise ValueError(f"Duplicate tool: {name}")
        Draft202012Validator.check_schema(tool.definition.input_schema)
        Draft202012Validator.check_schema(tool.definition.result_schema)
        self._tools[name] = tool

    def get(self, name):
        if name not in self._tools:
            raise ToolFailure("unknown_tool", f"Unknown tool: {name}; use skill_find/skill_load", retryable=True)
        return self._tools[name]

    def names(self):
        """Stable registered IDs without exposing executable handlers."""
        return tuple(self._tools)

    def definitions(self, names):
        return tuple(self.get(name).definition for name in names)


class ToolExecutor:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def execute(self, call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        from .tool_evidence import EvidenceLedger
        ledger = EvidenceLedger(context)
        try:
            tool = self.registry.get(call.name)
            args = strict_json(call.arguments) if isinstance(call.arguments, str) else call.arguments
            if not isinstance(args, dict) or call.name not in context.allowed_tool_names:
                return self._execute(call, context)
        except (ToolFailure, ValueError, TypeError):
            return self._execute(call, context)
        try:
            Draft202012Validator(tool.definition.input_schema).validate(args)
            inputs = ledger.inputs(tool, args)
        except (ToolFailure, ValidationError, OSError, ValueError, TypeError):
            inputs = []
        blocked = ledger.blocked(call, args, inputs)
        if blocked is not None:
            return blocked
        result = self._execute(call, context)
        return ledger.observe(call, args, tool, inputs, result)

    def _execute(self, call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        timeout = context.settings.tool_timeout_seconds
        configured_deadline = time.monotonic() + timeout if timeout > 0 else float("inf")
        ctx = replace(context, call_id=call.id, deadline=min(context.deadline, configured_deadline))
        try:
            ctx.check()
            tool = self.registry.get(call.name)
            if call.name not in ctx.allowed_tool_names:
                raise ToolFailure("tool_not_exposed", "Load the relevant skill before calling this tool", retryable=True)
            try:
                args = strict_json(call.arguments) if isinstance(call.arguments, str) else call.arguments
                json.dumps(args, allow_nan=False)
                Draft202012Validator(tool.definition.input_schema).validate(args)
            except (ValueError, TypeError, ValidationError) as exc:
                raise ToolFailure("invalid_arguments", str(exc)[:1800], retryable=True) from exc
            key = json.dumps([call.name, args], sort_keys=True, allow_nan=False)
            if tool.pure and key in ctx.pure_cache:
                return replace(ctx.pure_cache[key], call_id=call.id, cached=True)
            output = tool.handler(args, ctx)
            ctx.check()
            try:
                json.dumps(output.data, allow_nan=False)
                Draft202012Validator(tool.definition.result_schema).validate(output.data)
                for artifact in output.artifacts:
                    if not ctx.path(artifact.path).is_file():
                        raise ValueError(f"Artifact not found: {artifact.path}")
            except (ValueError, TypeError, ValidationError) as exc:
                raise ToolFailure("invalid_result", str(exc)[:1800]) from exc
            result = ToolResult(call.id, call.name, "ok", output.data, output.artifacts)
            if tool.pure:
                ctx.pure_cache[key] = result
            return result
        except ToolFailure as exc:
            status = {"tool_timeout": "timeout", "cancelled": "cancelled"}.get(exc.error.code, "error")
            return ToolResult(call.id, call.name, status, exc.data, exc.artifacts, exc.error)
        except Exception as exc:
            return ToolResult(call.id, call.name, "error", error=ErrorInfo("tool_error", f"{type(exc).__name__}: {exc}"[:1800], True))


def object_schema(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def artifact(path, ctx):
    return ArtifactRef(path.relative_to(ctx.workspace).as_posix(), mimetypes.guess_type(path.name)[0] or "application/octet-stream", ctx.call_id)


def read_file(args, ctx):
    path = ctx.path(args["path"])
    if path.stat().st_size > ctx.settings.max_file_bytes:
        raise ToolFailure("file_too_large", "Use execute_python to inspect this file in bounded chunks", retryable=True)
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    offset = args.get("offset", 0)
    size = min(args.get("max_chars", ctx.settings.max_tool_output_chars), ctx.settings.max_tool_output_chars)
    end = min(len(text), offset + size)
    return ToolOutput({"path": args["path"], "content": text[offset:end], "offset": offset,
                       "next_offset": end, "truncated": end < len(text), "sha256": hashlib.sha256(raw).hexdigest()})


def write_file(args, ctx):
    path = ctx.path(args["path"])
    raw = args["content"].encode("utf-8")
    if len(raw) > ctx.settings.max_file_bytes:
        raise ToolFailure("file_too_large", "Content exceeds the configured file size", retryable=True)
    if path.exists():
        previous = path.read_bytes()
        if previous != raw and args.get("expected_sha256") != hashlib.sha256(previous).hexdigest():
            raise ToolFailure("overwrite_requires_hash", "Read the current file and supply its sha256 as expected_sha256 before changing it", retryable=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_bytes(raw)
        ctx.check()
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return ToolOutput({"path": args["path"], "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}, (artifact(path, ctx),))


def _files(ctx):
    return {p.relative_to(ctx.workspace).as_posix(): (p.stat().st_mtime_ns, p.stat().st_size)
            for p in ctx.workspace.rglob("*") if p.is_file() and not p.is_symlink()
            and ".agent" not in p.relative_to(ctx.workspace).parts and p.resolve().is_relative_to(ctx.workspace)}


def _kill(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=10)


_PYTHON_RUNNER = r'''import ast
import hashlib
import json
import math
from pathlib import Path
import runpy
import sys

program, evidence, trace_path = map(Path, sys.argv[1:4])
value_limit = int(sys.argv[4])
workspace = Path.cwd().resolve()
# -I still excludes ambient PYTHONPATH and user-site packages. Only the
# administrator-configured dependency directories are passed by the broker.
if len(sys.argv) > 5:
    sys.path.extend(json.loads(sys.argv[5]))
executed, sources, code_sources, frames = {}, {}, {}, {}
sequence = 0
trace = trace_path.open("w", encoding="utf-8")

def emit(kind, **data):
    global sequence
    sequence += 1
    trace.write(json.dumps({"event": kind, "sequence": sequence, **data}, allow_nan=False) + "\n")
    return sequence

def scalar(value):
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is str and len(value) <= value_limit:
        return value
    return {"unrecorded_type": type(value).__name__}

def source_for(frame):
    code = frame.f_code
    saved = code_sources.get(id(code))
    if saved is not None:
        return saved[1]
    filename = code.co_filename
    if filename.startswith("<"):
        return None
    try:
        path = Path(filename).resolve()
        relative = path.relative_to(workspace)
        if relative.parts[0] == ".agent" and path != program.resolve():
            return None
        if code.co_name == "<module>" or filename not in sources:
            raw = path.read_bytes()
            tree = ast.parse(raw, filename)
            checks = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
            # Multiple asserts on the same physical line cannot be distinguished
            # by line tracing. Leave them unsupported rather than invent a pass.
            checks = [node for node in checks if sum(other.lineno == node.lineno for other in checks) == 1]
            source = {"path": relative.as_posix(), "sha256": hashlib.sha256(raw).hexdigest(),
                      "checks": {line: (node.lineno, node.end_lineno, ast.get_source_segment(raw.decode("utf-8"), node) or "assert")
                                 for node in checks for line in range(node.lineno, node.end_lineno + 1)}}
            sources[filename] = source
        else:
            source = sources[filename]
        # Keep code objects alive and preserve their source version across reloads.
        def bind(item):
            code_sources[id(item)] = (item, source)
            for constant in item.co_consts:
                if isinstance(constant, type(code)):
                    bind(constant)
        bind(code)
        if relative.parts[0] != ".agent":
            executed[(source["path"], source["sha256"])] = {"path": source["path"], "sha256": source["sha256"]}
        return source
    except (OSError, ValueError, IndexError, SyntaxError, UnicodeError):
        return None

def end_check(info, status):
    check = info.pop("check", None)
    if check:
        emit("assertion", path=info["source"]["path"], sha256=info["source"]["sha256"],
             line=check["line"], source=check["source"], status=status,
             function_call_ids=check["calls"])

def record(frame, event, arg):
    key = id(frame)
    if event == "call":
        source = source_for(frame)
        if source is None:
            return None
        code = frame.f_code
        names = list(code.co_varnames[:code.co_argcount + code.co_kwonlyargcount])
        next_index = len(names)
        if code.co_flags & 4:
            names.append(code.co_varnames[next_index])
            next_index += 1
        if code.co_flags & 8:
            names.append(code.co_varnames[next_index])
        kind = "module_enter" if code.co_name == "<module>" else "function_call"
        call_id = emit(kind, path=source["path"], sha256=source["sha256"],
                       function=code.co_name, line=code.co_firstlineno,
                       module_name=str(frame.f_globals.get("__name__", "")),
                       arguments={name: scalar(frame.f_locals.get(name)) for name in names})
        frames[key] = {"source": source, "call_id": call_id, "exception": False,
                       "suspending": bool(code.co_flags & (32 | 128 | 512))}
        if kind == "function_call":
            parent = frame.f_back
            while parent is not None:
                pending = frames.get(id(parent), {}).get("check")
                if pending is not None:
                    pending["calls"].append(call_id)
                parent = parent.f_back
        return record
    info = frames.get(key)
    if info is None:
        return
    if event == "line":
        info["exception"] = False
        pending = info.get("check")
        if pending and not pending["line"] <= frame.f_lineno <= pending["end"]:
            end_check(info, "completed_without_exception")
        definition = info["source"]["checks"].get(frame.f_lineno)
        if definition and "check" not in info:
            info["check"] = {"line": definition[0], "end": definition[1], "source": definition[2], "calls": []}
    elif event == "exception":
        info["exception"] = True
        end_check(info, "raised")
    elif event == "return":
        status = "raised" if info["exception"] else ("suspended_or_returned" if info["suspending"] else "returned")
        end_check(info, "completed_without_exception" if status == "returned" else "unestablished")
        emit("module_return" if frame.f_code.co_name == "<module>" else "function_return",
             path=info["source"]["path"], sha256=info["source"]["sha256"],
             call_id=info["call_id"], status=status, value=scalar(arg))
        frames.pop(key, None)
    return record

sys.argv = [str(program)]
sys.settrace(record)
try:
    runpy.run_path(str(program), run_name="__main__")
finally:
    complete = sys.gettrace() is record
    sys.settrace(None)
    trace.close()
    evidence.write_text(json.dumps({"files": list(executed.values()), "complete": complete}), encoding="utf-8")
'''


def execute_python(args, ctx):
    """Trusted local execution, NOT a security sandbox."""
    # Optional scientific dependencies are deployment-owned, never tool arguments.
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
    before = _files(ctx)
    folder = ctx.path(".agent/processes/" + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    code = folder / "program.py"
    code.write_text(args["code"], encoding="utf-8")
    runner, execution_record = folder / "runner.py", folder / "executed-files.json"
    execution_trace = folder / "execution.jsonl"
    runner.write_text(_PYTHON_RUNNER, encoding="utf-8")
    out_path, err_path = folder / "stdout.txt", folder / "stderr.txt"
    env = {k: v for k, v in os.environ.items() if not any(word in k.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTHORIZATION"))}
    env.update(PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1",
               MPLBACKEND="Agg", MPLCONFIGDIR=str(folder / "matplotlib"))
    stopped = None
    with out_path.open("wb") as out, err_path.open("wb") as err:
        options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        process = subprocess.Popen([sys.executable, "-I", str(runner), str(code), str(execution_record), str(execution_trace), str(ctx.settings.max_tool_output_chars), json.dumps(package_paths)], cwd=ctx.workspace,
                                   env=env, stdout=out, stderr=err, **options)
        try:
            while process.poll() is None:
                ctx.check()
                time.sleep(0.03)
        except (ToolFailure, KeyboardInterrupt) as exc:
            _kill(process)
            if isinstance(exc, KeyboardInterrupt):
                raise
            stopped = exc
    def text(path):
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(ctx.settings.max_tool_output_chars)
    record_data = strict_json(execution_record.read_text(encoding="utf-8")) if execution_record.is_file() else {}
    events, preview_size, truncated = [], 0, False
    digest = hashlib.sha256()
    if execution_trace.is_file():
        with execution_trace.open("rb") as handle:
            for line in handle:
                digest.update(line)
                if preview_size + len(line) <= ctx.settings.max_tool_output_chars and not truncated:
                    events.append(strict_json(line.decode("utf-8")))
                    preview_size += len(line)
                else:
                    truncated = True
    data = {"stdout": text(out_path), "stderr": text(err_path), "return_code": process.returncode,
            "stdout_path": out_path.relative_to(ctx.workspace).as_posix(),
            "stderr_path": err_path.relative_to(ctx.workspace).as_posix(),
            "code_path": code.relative_to(ctx.workspace).as_posix(),
            "executed_files": record_data.get("files", []),
            "execution_record_complete": record_data.get("complete", False),
            "execution_events": events, "execution_events_truncated": truncated,
            "execution_trace_path": execution_trace.relative_to(ctx.workspace).as_posix(),
            "execution_trace_sha256": digest.hexdigest()}
    after = _files(ctx)
    artifacts = tuple(artifact(ctx.path(name), ctx) for name, stamp in after.items() if before.get(name) != stamp)
    if stopped:
        raise ToolFailure(stopped.error.code, stopped.error.message, outcome_unknown=True, data=data, artifacts=artifacts)
    if process.returncode != 0:
        raise ToolFailure("python_error", "Python failed. Inspect stderr and change the program before retrying.", retryable=True, data=data, artifacts=artifacts)
    return ToolOutput(data, artifacts)


def register_file_tools(registry):
    text = {"type": "string"}
    definitions = [
        ("read_file", "Read a UTF-8 workspace file in bounded chunks and obtain its current hash.", "Inspect input data or read a file before editing.",
         object_schema({"path": {**text, "description": "Workspace-relative filename."}, "offset": {"type": "integer", "minimum": 0, "description": "Character offset, initially zero."},
                        "max_chars": {"type": "integer", "minimum": 1, "description": "Maximum characters to request; runtime may cap this."}}, ["path"]),
         object_schema({"path": text, "content": text, "offset": {"type": "integer"}, "next_offset": {"type": "integer"}, "truncated": {"type": "boolean"}, "sha256": text}, ["path", "content", "offset", "next_offset", "truncated", "sha256"]), read_file),
        ("write_file", "Create a UTF-8 file or safely replace a file whose current hash is known.", "Save a report, script, or edit a small file.",
         object_schema({"path": {**text, "description": "Workspace-relative output filename."}, "content": {**text, "description": "Complete new UTF-8 text."},
                        "expected_sha256": {**text, "pattern": "^[a-f0-9]{64}$", "description": "Hash from read_file; required when changing an existing file."}}, ["path", "content"]),
         object_schema({"path": text, "bytes": {"type": "integer"}, "sha256": text}, ["path", "bytes", "sha256"]), write_file),
        ("execute_python", "Run Python in this workspace and return actual stdout, stderr and generated files. Trusted local use only; not a sandbox.", "Compute, inspect tabular data, run checks, or repair code.",
         object_schema({"code": {**text, "pattern": r"^[\s\S]+$", "description": "Complete Python program. Use relative paths; avoid modifying inputs. Standard library is available; optional scientific packages are configured by the deployment. Use matplotlib's noninteractive backend for saved figures."}}, ["code"]),
         object_schema({"stdout": text, "stderr": text, "return_code": {"type": "integer"}, "stdout_path": text, "stderr_path": text, "code_path": text,
                        "executed_files": {"type": "array", "items": object_schema({"path": text, "sha256": text}, ["path", "sha256"]), "description": "Workspace source files entered in this Python process with load-time hashes. Loading alone does not prove functions or tests ran."},
                        "execution_record_complete": {"type": "boolean", "description": "The current-process trace finished with its hook active. Not proof of successful tests; child processes and other threads are not traced. Trusted local diagnostics, not tamperproof attestation."},
                        "execution_events": {"type": "array", "items": {"type": "object"}, "description": "Bounded preview of actual module loads, function arguments/returns and executed assert statements. Assertions record completion without an exception, not scientific correctness. Scalar values only; unsupported values are labelled. Same-line multiple assertions and generator/coroutine completion are not certified."},
                        "execution_events_truncated": {"type": "boolean"}, "execution_trace_path": text, "execution_trace_sha256": text},
                       ["stdout", "stderr", "return_code", "stdout_path", "stderr_path", "code_path", "executed_files", "execution_record_complete", "execution_events", "execution_events_truncated", "execution_trace_path", "execution_trace_sha256"]), execute_python),
    ]
    for name, description, when, inputs, outputs, handler in definitions:
        registry.register(Tool(ToolDefinition(name, description, when, inputs, outputs), handler))

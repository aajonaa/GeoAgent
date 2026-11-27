"""P1-2 tests: strict bubblewrap sandbox for execute_python and Brain-vs-Hands Broker split."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event
from types import SimpleNamespace

import pytest

from geological_agent.contracts import ErrorInfo, ToolCall, ToolResult
from geological_agent.sandbox_exec import (
    build_bwrap_command,
    collect_python_runtime_roots,
    resolve_bwrap,
    verify_sandbox_isolation,
)
from geological_agent.settings import Settings
from geological_agent.team.isolation import SandboxRunner
from geological_agent.team.protocol import decode, dumps, encode
from geological_agent.team.trusted_process import worker_command, worker_environment
from geological_agent.tools import ToolExecutionContext, ToolExecutor, ToolRegistry, register_file_tools


def _configured_bwrap():
    if sys.platform != "linux":
        return None
    return resolve_bwrap()


def _make_context(workspace: Path) -> ToolExecutionContext:
    return ToolExecutionContext(
        run_id="run-p1-2",
        workspace=workspace,
        allowed_tool_names=("read_file", "write_file", "execute_python"),
        settings=Settings(),
        cancel=Event(),
    )


def test_verify_sandbox_isolation_live_bwrap(tmp_path):
    bwrap = _configured_bwrap()
    if bwrap is None:
        pytest.skip("Linux bubblewrap binary not configured in environment")

    work = tmp_path / "work"
    work.mkdir()
    outside_secret = tmp_path / "host_secret.txt"
    outside_secret.write_text("top-secret-host-data", encoding="utf-8")

    probe = verify_sandbox_isolation(
        bwrap,
        work,
        probe_hidden_paths=(str(outside_secret), "/data/wangjian/oresage-incident-20261110-r2"),
        probe_ports=(50018,),
    )
    assert probe["ok"] is True, f"Sandbox self-probe failed: {probe}"
    assert probe["pid_isolated"] is True
    assert probe["cwd"] == "/work"
    assert probe["can_write_work"] is True
    assert probe["hidden_paths_blocked"] is True
    assert probe["external_net_blocked"] is True
    assert probe["loopback_ports_blocked"] is True
    assert probe["env_clean"] is True


def test_execute_python_strict_bwrap_computation_trace_and_isolation(tmp_path, monkeypatch):
    bwrap = _configured_bwrap()
    if bwrap is None:
        pytest.skip("Linux bubblewrap binary not configured in environment")

    work = tmp_path / "work"
    work.mkdir()
    outside_secret = tmp_path / "host_only_db.sqlite3"
    outside_secret.write_text("SECRET_SQLITE_BYTES", encoding="utf-8")
    (work / "helper.py").write_text("def double(x):\n    return x * 2\n", encoding="utf-8")

    monkeypatch.setenv("GEOTOOL_PYTHON_SANDBOX", "bwrap")
    monkeypatch.setenv("OPENAI_API_KEY", "labelled-test-key-must-not-leak")
    monkeypatch.setenv("TEAM_SECRET_TOKEN", "labelled-test-token-must-not-leak")

    registry = ToolRegistry()
    register_file_tools(registry)
    executor = ToolExecutor(registry)
    ctx = _make_context(work)

    code = f"""
import json, os, runpy, socket

helper = runpy.run_path("helper.py")
val = helper["double"](21)
assert val == 42

def can_connect(host, port):
    s = socket.socket()
    s.settimeout(0.4)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()

report = {{
    "val": val,
    "pid": os.getpid(),
    "cwd": os.getcwd(),
    "host_secret_visible": os.path.exists({str(outside_secret)!r}),
    "prod_dir_visible": os.path.exists("/data/wangjian/oresage-incident-20261110-r2"),
    "openai_key_present": "OPENAI_API_KEY" in os.environ,
    "team_token_present": "TEAM_SECRET_TOKEN" in os.environ,
    "external_net": can_connect("1.1.1.1", 443),
    "broker_port": can_connect("127.0.0.1", 50018),
}}
with open("sandbox_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f)
print(json.dumps(report))
"""
    res = executor.execute(ToolCall("c1", "execute_python", {"code": code}), ctx)
    assert res.status == "ok", f"execute_python failed: {res}"
    assert res.data["sandbox_mode"] == "bwrap_strict"
    assert res.data["execution_record_complete"] is True
    assert any(item["path"] == "helper.py" for item in res.data["executed_files"])
    assert any(ev.get("event") == "assertion" and ev.get("status") == "completed_without_exception"
               for ev in res.data["execution_events"])
    assert any(art.path == "sandbox_report.json" for art in res.artifacts)

    report = json.loads((work / "sandbox_report.json").read_text(encoding="utf-8"))
    assert report["val"] == 42
    assert report["pid"] <= 2
    assert report["cwd"] == "/work"
    assert report["host_secret_visible"] is False
    assert report["prod_dir_visible"] is False
    assert report["openai_key_present"] is False
    assert report["team_token_present"] is False
    assert report["external_net"] is False
    assert report["broker_port"] is False


def test_execute_python_fail_closed_when_sandbox_required(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("GEOTOOL_PYTHON_SANDBOX", "required")
    monkeypatch.delenv("GEOTOOL_SANDBOX_BWRAP", raising=False)
    monkeypatch.delenv("GEOTOOL_TRUSTED_PROCESS_BWRAP", raising=False)

    registry = ToolRegistry()
    register_file_tools(registry)
    executor = ToolExecutor(registry)
    res = executor.execute(
        ToolCall("c-req", "execute_python", {"code": "open('ran.txt', 'w').write('no')"}),
        _make_context(work),
    )
    assert res.status == "error"
    assert res.error is not None
    assert res.error.code == "sandbox_unavailable"
    assert not (work / "ran.txt").exists()


def test_execute_python_off_mode_uses_trusted_local(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("GEOTOOL_PYTHON_SANDBOX", "off")

    registry = ToolRegistry()
    register_file_tools(registry)
    executor = ToolExecutor(registry)
    res = executor.execute(
        ToolCall("c-off", "execute_python", {"code": "print('trusted-ok')"}),
        _make_context(work),
    )
    assert res.status == "ok"
    assert res.data["sandbox_mode"] == "trusted_local"
    assert "trusted-ok" in res.data["stdout"]


def test_sandbox_exec_rejects_unsafe_readonly_mounts(tmp_path, monkeypatch):
    if sys.platform != "linux":
        pytest.skip("Linux-only test")
    bwrap = tmp_path / "fake-bwrap"
    bwrap.write_text("#!/bin/sh\n", encoding="utf-8")
    bwrap.chmod(0o755)
    work = tmp_path / "work"
    work.mkdir()
    state_dir = tmp_path / "recovery_state"
    state_dir.mkdir()

    for bad_root in (Path("/"), Path("/data"), Path("/home"), work, state_dir):
        if not bad_root.exists():
            continue
        with pytest.raises(RuntimeError, match="Unsafe sandbox runtime mount"):
            build_bwrap_command(
                bwrap,
                work,
                [sys.executable, "-c", "print(1)"],
                readonly_roots=[bad_root],
                forbidden_overlap=(state_dir,),
            )


def test_trusted_worker_command_mounts_proc_and_forwards_sandbox_env(tmp_path, monkeypatch):
    if sys.platform != "linux":
        pytest.skip("Linux-only test")
    bwrap = tmp_path / "bwrap"
    bwrap.write_text("#!/bin/sh\n", encoding="utf-8")
    bwrap.chmod(0o755)
    pkg_dir = tmp_path / "sci-pkgs"
    pkg_dir.mkdir()

    monkeypatch.setenv("GEOTOOL_TRUSTED_PROCESS_BWRAP", str(bwrap))
    monkeypatch.setenv("GEOTOOL_PYTHON_SANDBOX", "required")
    monkeypatch.setenv("GEOTOOL_PYTHON_PACKAGES", str(pkg_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "secret-must-stay-in-broker")

    env = worker_environment()
    assert env["GEOTOOL_TRUSTED_PROCESS_BWRAP"] == str(bwrap)
    assert env["GEOTOOL_PYTHON_SANDBOX"] == "required"
    assert env["GEOTOOL_PYTHON_PACKAGES"] == str(pkg_dir)
    assert "OPENAI_API_KEY" not in env

    jobs_root = tmp_path / "state" / "trusted-jobs"
    jobs_root.mkdir(parents=True)
    rec_dir = tmp_path / "recovery"
    rec_dir.mkdir()
    root_dir = tmp_path / "ownership"
    root_dir.mkdir()
    runner = SimpleNamespace(jobs_root=jobs_root, process_worker=None)
    manager = SimpleNamespace(
        recovery=SimpleNamespace(directory=rec_dir),
        root=SimpleNamespace(path=root_dir),
    )
    cmd = worker_command(runner, manager)
    proc_idx = cmd.index("--proc")
    assert cmd[proc_idx + 1] == "/proc"


def test_sandbox_runner_brain_vs_hands_routing_and_broker_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_DYNAMIC_PYTHON_ALLOWED", "1")
    runner = SandboxRunner(ownership_only=True)

    # Brain (Broker) tools
    for name in ("web_search", "web_fetch", "context_search", "context_read",
                 "request_user_input", "skill_find", "skill_load",
                 "GeoImageAnalyze", "GeoOpenAlexSearch", "update_todo",
                 "delegate_subagent", "run_subagents_parallel"):
        assert runner.route_tool(name) == "broker", name

    # Hands (Sandbox) tools — both core file/code tools and professional geoscience tools
    for name in ("read_file", "write_file", "execute_python", "GeoPyrolitePlot", "GeoLithologySummary"):
        assert runner.route_tool(name) == "sandbox", name

    # Policy toggles
    monkeypatch.setenv("GEOTOOL_DYNAMIC_PYTHON_ALLOWED", "0")
    no_py = SandboxRunner(ownership_only=True)
    assert no_py.route_tool("execute_python") == "denied"
    assert no_py.route_tool("read_file") == "sandbox"

    strict_five = SandboxRunner(ownership_only=True, broker_tools_enabled=False, allow_extended_sandbox_tools=False)
    assert strict_five.route_tool("read_file") == "sandbox"
    assert strict_five.route_tool("GeoPyrolitePlot") == "denied"
    assert strict_five.route_tool("web_search") == "denied"

    # Verify execute_tool dispatches broker-routed calls to broker_executor directly
    called = []
    class FakeBrokerExecutor:
        def _execute(self, call, context):
            called.append((call.name, call.arguments))
            return ToolResult(call.id, call.name, "ok", data={"source": "broker"})

    runner.process_ownership = SimpleNamespace()
    ctx = ToolExecutionContext("r1", tmp_path, ("web_search",), Settings(), Event())
    result = runner.execute_tool(
        "a" * 32,
        {"uid": "u1", "cid": "c1"},
        ToolCall("tc-web", "web_search", {"query": "porphyry copper"}),
        ctx,
        broker_executor=FakeBrokerExecutor(),
    )
    assert result.status == "ok"
    assert result.data == {"source": "broker"}
    assert called == [("web_search", {"query": "porphyry copper"})]


def test_sandbox_tool_live_bwrap_roundtrip_and_broker_tool_rejection(tmp_path):
    bwrap = _configured_bwrap()
    if bwrap is None:
        pytest.skip("Linux bubblewrap binary not configured in environment")

    work = tmp_path / "work"
    work.mkdir()
    app_root = Path(__file__).resolve().parents[1]
    roots = collect_python_runtime_roots(sys.executable, extra_readonly=[app_root])
    sandbox_env = {
        "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
        "HOME": "/work",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "PYTHONPATH": str(app_root),
        "PYTHONDONTWRITEBYTECODE": "1",
        "GEOTOOL_PYTHON_SANDBOX": "off",
    }
    argv = build_bwrap_command(
        bwrap,
        work,
        [sys.executable, "-B", "-m", "geological_agent.team.sandbox_tool"],
        readonly_roots=roots,
        env=sandbox_env,
        unshare_cgroup=True,
    )

    def invoke_sandbox_tool(call: ToolCall, allowed: tuple[str, ...]):
        packet = dumps({
            "call": encode(call),
            "core_run_id": "run-sandbox-1",
            "allowed_tool_names": list(allowed),
            "settings": asdict(Settings()),
            "duration": 15.0,
            "pure_cache": encode({}),
            "evidence_state": encode({}),
        })
        return subprocess.run(
            argv,
            input=packet,
            capture_output=True,
            timeout=20,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        )

    # 1. Valid workspace tool runs cleanly inside strict per-ToolCall bwrap
    proc = invoke_sandbox_tool(
        ToolCall("c-write", "write_file", {"path": "hello.txt", "content": "from-sandbox"}),
        ("write_file",),
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    reply = json.loads(proc.stdout.decode("utf-8"))
    tool_res = decode(reply["result"])
    assert isinstance(tool_res, ToolResult)
    assert tool_res.status == "ok"
    assert (work / "hello.txt").read_text(encoding="utf-8") == "from-sandbox"

    # 2. Broker-only tool MUST fail closed inside sandbox_tool.py
    proc_bad = invoke_sandbox_tool(
        ToolCall("c-web", "web_search", {"query": "should be rejected"}),
        ("web_search",),
    )
    assert proc_bad.returncode != 0
    assert b"Unsupported local Sandbox ToolCall" in proc_bad.stderr

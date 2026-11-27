"""P2-2 tests: Programmatic Tool Calling (CodeAct) inside strict bubblewrap sandbox."""
import json
import sys
from threading import Event, Lock
import time

import pytest

from geological_agent.agent.codeact import CodeActBridge, register_codeact_tool
from geological_agent.bootstrap import build_registry, create_agent
from geological_agent.contracts import ModelResponse, ToolCall
from geological_agent.sandbox_exec import resolve_bwrap
from geological_agent.settings import Settings
from geological_agent.tools import Tool, ToolDefinition, ToolExecutionContext, ToolExecutor, ToolOutput, ToolRegistry, object_schema


def test_codeact_live_bwrap_geoscience_sweep_and_isolation(tmp_path, monkeypatch):
    """Real end-to-end CodeAct sweep over GeoMagnitudeToEnergy inside strict net-isolated bwrap."""
    registry, skills, base_tools = build_registry()
    assert "run_codeact" in base_tools
    earthquake_tools = skills.load("earthquake_energy").tool_names
    allowed = tuple(dict.fromkeys([*base_tools, *earthquake_tools]))

    bwrap = resolve_bwrap() if sys.platform == "linux" else None
    if bwrap is not None:
        monkeypatch.setenv("GEOTOOL_PYTHON_SANDBOX", "bwrap")
    monkeypatch.setenv("OPENAI_API_KEY", "labelled-codeact-secret-must-not-leak")

    executor = ToolExecutor(registry)
    bridge = CodeActBridge(executor=executor, allowed_tools=allowed)
    ctx = ToolExecutionContext("ca-sweep", tmp_path, allowed, Settings(), Event(), codeact_bridge=bridge)

    script = """
import json, os, socket

# 1. Verify tools.list() exposes GeoMagnitudeToEnergy but excludes blocked recursion tools
avail = tools.list()
assert "GeoMagnitudeToEnergy" in avail
assert "run_codeact" not in avail
assert "execute_python" not in avail

# 2. Sweep 4 earthquake magnitudes via shorthand + batch (including a repeat to trigger pure_cache)
r_single = tools.GeoMagnitudeToEnergy(mw=5.0)
batch_res = tools.batch([
    ("GeoMagnitudeToEnergy", {"mw": 5.0}),
    ("GeoMagnitudeToEnergy", {"mw": 6.0}),
    ("GeoMagnitudeToEnergy", {"mw": 7.0}),
])
assert all(item["ok"] for item in batch_res), batch_res
assert batch_res[0]["cached"] is True

# 3. Verify sandbox isolation (zero secret leakage, zero network in bwrap)
def net_reachable():
    s = socket.socket()
    s.settimeout(0.3)
    try:
        s.connect(("1.1.1.1", 443))
        return True
    except OSError:
        return False
    finally:
        s.close()

summary = {
    "single_m5": r_single,
    "energies": [item["data"] for item in batch_res],
    "secret_leaked": "OPENAI_API_KEY" in os.environ,
    "net_reachable": net_reachable(),
    "pid": os.getpid(),
    "cwd": os.getcwd(),
}
with open("energy_sweep.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False)
print(json.dumps({"count": len(summary["energies"]), "secret_leaked": summary["secret_leaked"]}))
"""
    res = executor.execute(ToolCall("c-ca1", "run_codeact", {"code": script}), ctx)
    assert res.status == "ok", f"{res.error} STDERR: {res.data.get('stderr')}"
    assert res.data["tool_call_count"] == 4
    assert any(a.path == "energy_sweep.json" for a in res.artifacts)
    assert any(r["cached"] is True for r in res.data["tool_calls"])

    saved = json.loads((tmp_path / "energy_sweep.json").read_text(encoding="utf-8"))
    assert len(saved["energies"]) == 3
    assert saved["secret_leaked"] is False
    if bwrap is not None:
        assert res.data["sandbox_mode"] == "bwrap_strict"
        assert saved["pid"] <= 2
        assert saved["cwd"] == "/work"
        assert saved["net_reachable"] is False


def test_codeact_blocks_recursion_unexposed_tools_and_enforces_call_cap(tmp_path):
    registry = ToolRegistry()
    register_codeact_tool(registry)
    registry.register(Tool(
        ToolDefinition("echo_num", "Echo number", "Test", object_schema({"x": {"type": "integer"}}, ["x"]),
                       object_schema({"y": {"type": "integer"}}, ["y"])),
        lambda args, ctx: ToolOutput({"y": args["x"] * 10}),
        pure=True,
    ))
    registry.register(Tool(
        ToolDefinition("secret_unexposed", "Hidden tool", "Test", object_schema({}), object_schema({"v": {"type": "string"}}, ["v"])),
        lambda args, ctx: ToolOutput({"v": "secret"}),
        pure=True,
    ))

    executor = ToolExecutor(registry)
    allowed = ("run_codeact", "echo_num")
    bridge = CodeActBridge(executor=executor, allowed_tools=allowed)
    ctx = ToolExecutionContext("ca-sec", tmp_path, allowed, Settings(), Event(), codeact_bridge=bridge)

    script = """
import json
errors = {}
for blocked in ("run_codeact", "execute_python", "request_user_input", "delegate_subagent", "skill_load"):
    try:
        tools.call(blocked, {})
    except CodeActToolError as exc:
        errors[blocked] = exc.code

try:
    tools.call("secret_unexposed", {})
except CodeActToolError as exc:
    errors["secret_unexposed"] = exc.code

# Consume max_tool_calls=2 then trigger codeact_call_limit on call #3
assert tools.echo_num(x=1)["y"] == 10
assert tools.echo_num(x=2)["y"] == 20
try:
    tools.echo_num(x=3)
except CodeActToolError as exc:
    errors["limit"] = exc.code

print(json.dumps(errors))
"""
    res = executor.execute(ToolCall("c-sec", "run_codeact", {"code": script, "max_tool_calls": 2}), ctx)
    assert res.status == "ok", f"{res.error} STDERR: {res.data.get('stderr')}"
    errors = json.loads(res.data["stdout"].strip())
    for blocked in ("run_codeact", "execute_python", "request_user_input", "delegate_subagent", "skill_load"):
        assert errors[blocked] == "tool_blocked_in_codeact"
    assert errors["secret_unexposed"] == "tool_not_exposed"
    assert errors["limit"] == "codeact_call_limit"


def test_codeact_parallel_batch_runs_concurrently_and_preserves_order(tmp_path):
    registry = ToolRegistry()
    register_codeact_tool(registry)
    lock = Lock()
    state = {"active": 0, "peak": 0}

    def slow_pure(args, ctx):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.15)
        with lock:
            state["active"] -= 1
        return ToolOutput({"idx": args["idx"], "squared": args["idx"] ** 2})

    registry.register(Tool(
        ToolDefinition("slow_sq", "Slow square", "Test", object_schema({"idx": {"type": "integer"}}, ["idx"]),
                       object_schema({"idx": {"type": "integer"}, "squared": {"type": "integer"}}, ["idx", "squared"])),
        slow_pure,
        pure=True,
    ))
    executor = ToolExecutor(registry)
    allowed = ("run_codeact", "slow_sq")
    bridge = CodeActBridge(executor=executor, allowed_tools=allowed)
    ctx = ToolExecutionContext("ca-par", tmp_path, allowed, Settings(), Event(), codeact_bridge=bridge)

    script = """
import json, time
t0 = time.monotonic()
res = tools.batch([("slow_sq", {"idx": i}) for i in (1, 2, 3, 4)])
elapsed = time.monotonic() - t0
print(json.dumps({"vals": [r["data"]["squared"] for r in res], "elapsed": elapsed}))
"""
    res = executor.execute(ToolCall("c-par", "run_codeact", {"code": script}), ctx)
    assert res.status == "ok", res
    out = json.loads(res.data["stdout"].strip())
    assert out["vals"] == [1, 4, 9, 16]
    assert state["peak"] >= 2
    assert out["elapsed"] < 0.45


def test_codeact_runtime_integration_ask_exclusion_and_fail_closed(tmp_path, monkeypatch):
    # Ask mode (read_only=True) must never expose run_codeact.
    ask = create_agent(None, read_only=True)
    assert "run_codeact" not in ask.base_tools

    # Fail-closed when GEOTOOL_PYTHON_SANDBOX=required and bwrap unavailable.
    monkeypatch.setenv("GEOTOOL_PYTHON_SANDBOX", "required")
    monkeypatch.delenv("GEOTOOL_SANDBOX_BWRAP", raising=False)
    monkeypatch.delenv("GEOTOOL_TRUSTED_PROCESS_BWRAP", raising=False)
    registry = ToolRegistry()
    register_codeact_tool(registry)
    executor = ToolExecutor(registry)
    ctx = ToolExecutionContext("ca-fc", tmp_path, ("run_codeact",), Settings(), Event(),
                               codeact_bridge=CodeActBridge(executor=executor, allowed_tools=("run_codeact",)))
    fail_res = executor.execute(ToolCall("c-fc", "run_codeact", {"code": "print(1)"}), ctx)
    assert fail_res.status == "error" and fail_res.error.code == "sandbox_unavailable"

    # Full AgentRuntime turn using run_codeact -> read_file programmatically -> stable KV prefix.
    monkeypatch.setenv("GEOTOOL_PYTHON_SANDBOX", "off")
    (tmp_path / "grades.txt").write_text("1.2,1.8,2.4", encoding="utf-8")
    seen_sys = []

    class ScriptedModel:
        def invoke(self, request):
            seen_sys.append(request.messages[0].content)
            if len(seen_sys) == 1:
                return ModelResponse(
                    "",
                    (ToolCall("ca-1", "run_codeact", {
                        "code": (
                            "raw = tools.read_file(path='grades.txt')['content']\n"
                            "nums = [float(x) for x in raw.split(',')]\n"
                            "print(f'mean={sum(nums)/len(nums):.2f}')\n"
                        )
                    }),),
                    "tool_calls",
                )
            return ModelResponse("Mean grade is 1.80.", (), "stop")

    agent = create_agent(ScriptedModel(), settings=Settings(verify_completion=False))
    outcome = agent.run("Compute mean grade from grades.txt", workspace=tmp_path)
    assert outcome.status == "completed", outcome
    assert len(set(seen_sys)) == 1  # KV-cache prefix remained byte-identical!
    tool_msgs = [json.loads(m.content) for m in outcome.state["messages"] if m.role == "tool"]
    assert tool_msgs[0]["name"] == "run_codeact"
    assert "mean=1.80" in tool_msgs[0]["data"]["stdout"]
    assert tool_msgs[0]["data"]["tool_call_count"] == 1

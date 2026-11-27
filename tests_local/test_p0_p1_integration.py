"""Unified P0+P1 cross-feature integration tests."""
import json
import sys
import time
from pathlib import Path
from threading import Event

import pytest

from geological_agent.bootstrap import create_agent
from geological_agent.contracts import ModelResponse, ToolCall
from geological_agent.mcp_client import McpServerConfig
from geological_agent.sandbox_exec import resolve_bwrap
from geological_agent.settings import Settings
from geological_agent.team.store import Store


def test_kv_prefix_stays_byte_identical_with_todo_recitation_and_skill_load(tmp_path):
    """P0-1 + P1-1 synergy: update_todo recitation and skill_load never mutate messages[0]."""
    seen_requests = []

    class ScriptedModel:
        def invoke(self, request):
            seen_requests.append(request)
            n = len(seen_requests)
            if n == 1:
                return ModelResponse(
                    "",
                    (ToolCall("c1", "update_todo", {"items": [
                        {"id": "t1", "task": "Inspect sample data", "status": "in_progress"},
                        {"id": "t2", "task": "Compute earthquake energy", "status": "pending"},
                    ]}),),
                    "tool_calls",
                    usage={"prompt_tokens": 1200, "prompt_tokens_details": {"cached_tokens": 0}},
                )
            if n == 2:
                return ModelResponse(
                    "",
                    (ToolCall("c2", "skill_load", {"skill_id": "earthquake_energy"}),),
                    "tool_calls",
                    usage={"prompt_tokens": 1500, "prompt_tokens_details": {"cached_tokens": 1100}},
                )
            if n == 3:
                return ModelResponse(
                    "",
                    (ToolCall("c3", "update_todo", {"items": [
                        {"id": "t1", "task": "Inspect sample data", "status": "done", "evidence": "read ok"},
                        {"id": "t2", "task": "Compute earthquake energy", "status": "done", "evidence": "skill loaded"},
                    ]}),),
                    "tool_calls",
                    usage={"prompt_tokens": 1900, "prompt_tokens_details": {"cached_tokens": 1450}},
                )
            return ModelResponse(
                "All tasks completed cleanly.",
                (),
                "stop",
                usage={"prompt_tokens": 2100, "prompt_tokens_details": {"cached_tokens": 1850}},
            )

    agent = create_agent(ScriptedModel(), settings=Settings(verify_completion=False))
    result = agent.run("Coordinate multi-step geoscience analysis", workspace=tmp_path)
    assert result.status == "completed", result

    # 1. System prompt messages[0] stayed 100% byte-identical across all 4 turns!
    sys_prompts = [req.messages[0].content for req in seen_requests]
    assert len(set(sys_prompts)) == 1
    metrics = result.state["metadata"]["prompt_cache_metrics"]
    assert metrics["execution_turns"] == 4
    assert metrics["system_prefix_stable_turns"] == 3
    assert metrics["cache_hit_ratio"] > 0.5

    # 2. Tail progress recitation appeared on turn 2+ without mutating messages[0]!
    assert "todo recitation" in seen_requests[1].messages[-1].content
    assert "Inspect sample data" in seen_requests[1].messages[-1].content
    assert (tmp_path / ".agent" / "todo.md").is_file()


def test_parallel_read_only_batch_with_bwrap_execute_python_and_todo_barrier(tmp_path, monkeypatch):
    """P0-2 + P1-1 + P1-2 synergy: parallel read_file batch -> todo barrier -> bwrap execute_python."""
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")
    (tmp_path / "b.txt").write_text("beta", encoding="utf-8")

    bwrap = resolve_bwrap() if sys.platform == "linux" else None
    if bwrap is not None:
        monkeypatch.setenv("GEOTOOL_PYTHON_SANDBOX", "bwrap")

    turn = {"n": 0}

    class ScriptedModel:
        def invoke(self, request):
            turn["n"] += 1
            if turn["n"] == 1:
                return ModelResponse(
                    "",
                    (
                        ToolCall("r1", "read_file", {"path": "a.txt"}),
                        ToolCall("r2", "read_file", {"path": "b.txt"}),
                        ToolCall("t1", "update_todo", {"items": [
                            {"id": "step1", "task": "Read inputs", "status": "done", "evidence": "a.txt,b.txt"},
                            {"id": "step2", "task": "Compute sum", "status": "in_progress"},
                        ]}),
                        ToolCall("p1", "execute_python", {"code": "print(len(open('a.txt').read()) + len(open('b.txt').read()))"}),
                    ),
                    "tool_calls",
                )
            return ModelResponse("Combined length is 9.", (), "stop")

    agent = create_agent(ScriptedModel(), settings=Settings(verify_completion=False))
    result = agent.run("Read both files and compute combined length", workspace=tmp_path)
    assert result.status == "completed", result

    # Parallel batch recorded for the two read_file calls
    batches = result.state["metadata"].get("parallel_tool_batches", [])
    assert len(batches) == 1
    assert batches[0]["tools"] == ["read_file", "read_file"]

    # execute_python ran in strict bwrap on Linux
    tool_msgs = [json.loads(m.content) for m in result.state["messages"] if m.role == "tool"]
    py_msg = next(m for m in tool_msgs if m["name"] == "execute_python")
    assert py_msg["status"] == "ok"
    assert py_msg["data"]["stdout"].strip() == "9"
    if bwrap is not None:
        assert py_msg["data"]["sandbox_mode"] == "bwrap_strict"


def test_ask_fast_path_with_mcp_readonly_and_hybrid_skill_search(tmp_path):
    """P0-2 + P0-3 + P1-3 synergy: fast Ask startup + read_only MCP gating + hybrid skill_find."""
    server_script = tmp_path / "mini_mcp.py"
    server_script.write_text(
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    m = json.loads(line)\n"
        "    if m.get('id') is None: continue\n"
        "    meth = m['method']\n"
        "    if meth == 'initialize': res = {'protocolVersion': '2025-03-26', 'capabilities': {'tools': {}}}\n"
        "    elif meth == 'tools/list': res = {'tools': [{'name': 'ping', 'description': 'Ping', 'inputSchema': {'type': 'object', 'properties': {}}}]}\n"
        "    else: res = {'content': [{'type': 'text', 'text': 'pong'}], 'isError': False}\n"
        "    sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': res}) + '\\n'); sys.stdout.flush()\n",
        encoding="utf-8",
    )
    ro_cfg = McpServerConfig(name="mini_ro", command=(sys.executable, "-u", str(server_script)), read_only=True)
    rw_cfg = McpServerConfig(name="mini_rw", command=(sys.executable, "-u", str(server_script)), read_only=False)

    t0 = time.perf_counter()
    ask_agent = create_agent(None, read_only=True, mcp_servers=[ro_cfg, rw_cfg])
    elapsed_ms = (time.perf_counter() - t0) * 1000
    try:
        assert "mcp__mini_ro__ping" in ask_agent.base_tools
        assert "mcp__mini_rw__ping" not in ask_agent.base_tools
        assert "execute_python" not in ask_agent.base_tools
        assert elapsed_ms < 5000  # Fast path skips 457+ catalog tools
    finally:
        ask_agent.tools.mcp_manager.close()

    # Hybrid skill search + P1-4 CAS store coexist cleanly
    agent = create_agent(None)
    hits = [s.id for s in agent.skills.registry.list("计算地震震级对应的地震能量", limit=3)]
    assert "earthquake_energy" in hits

    store = Store(tmp_path / "team_state")
    uid = store.create_user("admin", "Admin-Test-Password-2026", role="admin", initial_admin=True)
    cid = store.create_conversation(uid)["id"]
    store.snapshot(uid, cid, {"result.txt": b"integrated-p0-p1"}, action="run")
    assert store.file(uid, cid, "result.txt") == b"integrated-p0-p1"


def test_v032_theory_library_query_preserved_after_modularization():
    """Ensure v0.32 Ask-mode theory library routing survives runtime_knowledge extraction."""
    from geological_agent.agent.runtime import theory_library_query as rt_theory_query
    from geological_agent.agent.runtime_knowledge import theory_library_query as rk_theory_query

    assert rt_theory_query is rk_theory_query
    assert rt_theory_query("请上网搜索斑岩铜矿理论") is False
    assert rt_theory_query("请根据上传附件分析") is False

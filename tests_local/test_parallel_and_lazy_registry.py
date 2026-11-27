"""P0-2 regression suite: concurrent read-only/pure tool execution and lazy registry startup."""
import json
import threading
import time
from types import SimpleNamespace

import pytest
from jsonschema.exceptions import SchemaError

from geological_agent.agent.runtime import AgentRuntime
from geological_agent.bootstrap import build_registry, create_agent
from geological_agent.contracts import ModelResponse, ToolCall
from geological_agent.knowledge import NullKnowledgeRetriever
from geological_agent.memory import NullMemoryStore
from geological_agent.settings import Settings
from geological_agent.tools import Tool, ToolDefinition, ToolOutput, ToolRegistry, object_schema


def test_lazy_schema_validation_defers_work_until_access_and_still_rejects_bad_schema():
    registry = ToolRegistry()
    bad = Tool(
        ToolDefinition("bad_tool", "Bad", "Never", {"type": "not-a-valid-json-schema-type"}, object_schema({})),
        lambda args, ctx: ToolOutput({}),
    )
    registry.register(bad, validate_schema=False)
    # Existence check succeeds without triggering schema compilation.
    registry.require_registered("bad_tool")
    assert registry.peek("bad_tool") is bad
    # Accessing via get() or definitions() triggers strict Draft202012 validation.
    with pytest.raises(SchemaError):
        registry.get("bad_tool")


def test_read_only_create_agent_fast_path_skips_professional_catalog(monkeypatch):
    from geological_agent.geology import source_registry
    called = []
    monkeypatch.setattr(source_registry, "register", lambda *a, **kw: called.append(True))
    monkeypatch.setenv("GEOTOOL_WEB_ENABLED", "1")
    agent = create_agent(object(), settings=Settings(verify_completion=False), read_only=True)
    assert not called
    assert set(agent.base_tools) == {"read_file", "web_search", "web_fetch"}
    assert set(agent.tools.names()) == {"read_file", "web_search", "web_fetch"}
    assert agent.skills.registry.list() == ()


def test_build_registry_cold_and_warm_are_fast_and_preserve_all_tools_and_skills():
    t0 = time.perf_counter()
    reg1, skills1, _ = build_registry(human_input=True)
    cold_ms = (time.perf_counter() - t0) * 1000
    t1 = time.perf_counter()
    reg2, skills2, _ = build_registry(human_input=True)
    warm_ms = (time.perf_counter() - t1) * 1000
    assert len(reg1.names()) == len(reg2.names()) >= 468
    assert len(skills1.registry.list()) == len(skills2.registry.list()) == 191
    # Previously ~5,700ms per call; lazy validation + cached skill docs should stay well under 1.5s.
    assert cold_ms < 1500, f"cold build_registry too slow: {cold_ms:.1f}ms"
    assert warm_ms < 500, f"warm build_registry too slow: {warm_ms:.1f}ms"


def test_parallel_pure_tools_run_concurrently_and_preserve_declared_order(tmp_path):
    registry = ToolRegistry()
    active = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def slow_pure(args, ctx):
        with lock:
            active["now"] += 1
            active["peak"] = max(active["peak"], active["now"])
        time.sleep(0.15)
        with lock:
            active["now"] -= 1
        return ToolOutput({"index": args["index"], "squared": args["index"] ** 2})

    registry.register(Tool(
        ToolDefinition("slow_calc", "Pure calculation", "Test concurrency",
                       object_schema({"index": {"type": "integer"}}, ["index"]),
                       object_schema({"index": {"type": "integer"}, "squared": {"type": "integer"}}, ["index", "squared"])),
        slow_pure, pure=True,
    ))
    skills = SimpleNamespace(registry=SimpleNamespace(list=lambda: []))

    class Model:
        def __init__(self):
            self.turns = 0
        def invoke(self, request):
            self.turns += 1
            if self.turns == 1:
                return ModelResponse(
                    tool_calls=tuple(ToolCall(f"c{i}", "slow_calc", {"index": i}) for i in range(4)),
                    finish_reason="tool_calls",
                )
            return ModelResponse("Computed 0, 1, 4, 9.")

    agent = AgentRuntime(
        Model(), Settings(verify_completion=False, max_model_turns=4),
        registry, skills, NullMemoryStore(), NullKnowledgeRetriever(), ("slow_calc",),
    )
    t0 = time.perf_counter()
    result = agent.run("Compute four squares.", workspace=tmp_path)
    elapsed = time.perf_counter() - t0
    assert result.status == "completed", result.reason
    # All 4 ran concurrently (peak >= 2, and batch wall time well below 4 * 150ms = 600ms).
    assert active["peak"] >= 2, f"expected concurrent execution, peak={active['peak']}"
    batches = result.state["metadata"]["parallel_tool_batches"]
    assert len(batches) == 1 and batches[0]["count"] == 4
    assert batches[0]["elapsed_ms"] < 450, f"expected parallel speedup, batch={batches[0]}"
    # Tool result messages remain in exact declared call order c0, c1, c2, c3.
    tool_msgs = [json.loads(m.content) for m in result.state["messages"] if m.role == "tool"]
    assert [m["call_id"] for m in tool_msgs] == ["c0", "c1", "c2", "c3"]
    assert [m["data"]["squared"] for m in tool_msgs] == [0, 1, 4, 9]


def test_mutating_tool_acts_as_sequential_barrier_between_parallel_reads(tmp_path):
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")
    (tmp_path / "b.txt").write_text("beta", encoding="utf-8")
    events = []

    class Model:
        def __init__(self):
            self.turns = 0
        def invoke(self, request):
            self.turns += 1
            if self.turns == 1:
                return ModelResponse(tool_calls=(
                    ToolCall("r1", "read_file", {"path": "a.txt"}),
                    ToolCall("r2", "read_file", {"path": "b.txt"}),
                    ToolCall("w1", "write_file", {"path": "c.txt", "content": "gamma"}),
                    ToolCall("r3", "read_file", {"path": "c.txt"}),
                ), finish_reason="tool_calls")
            return ModelResponse("Read alpha, beta, and created/read gamma.")

    agent = create_agent(Model(), settings=Settings(verify_completion=False, max_model_turns=4),
                         trace_factory=lambda *a: SimpleNamespace(emit=lambda k, **f: events.append((k, f))))
    result = agent.run("Read a and b, write c, then read c.", workspace=tmp_path)
    assert result.status == "completed", result.reason
    tool_msgs = [json.loads(m.content) for m in result.state["messages"] if m.role == "tool"]
    assert [m["call_id"] for m in tool_msgs] == ["r1", "r2", "w1", "r3"]
    assert all(m["status"] == "ok" for m in tool_msgs)
    assert tool_msgs[3]["data"]["content"] == "gamma"
    # Only (r1, r2) ran as a parallel batch; w1 acted as barrier before r3.
    parallel_events = [f for k, f in events if k == "parallel_tool_batch"]
    assert len(parallel_events) == 1 and parallel_events[0]["tools"] == ["read_file", "read_file"]

"""P0-1 regression suite: KV-cache prefix stability, telemetry, and tool result clearing."""
from copy import deepcopy
import hashlib
import json

import pytest

from geological_agent.agent.compaction import fit_request, request_size
from geological_agent.agent.context import ContextManager
from geological_agent.agent.skill_scope import fit_skill_scope
from geological_agent.bootstrap import create_agent
from geological_agent.context_budget import input_allowance, request_budget_size
from geological_agent.contracts import Message, ModelRequest, ModelResponse, ToolCall, ToolResult
from geological_agent.llm import extract_cache_usage
from geological_agent.settings import Settings
from geological_agent.skills import Skill, SkillLoader, SkillRegistry, SkillSummary
from geological_agent.tools import ToolDefinition, object_schema


class MemoryArchive:
    def __init__(self):
        self.rows = {}

    def put(self, run_id, kind, key, payload, label=""):
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        eid = "ev_" + digest
        self.rows[eid] = deepcopy(payload)
        return {"evidence_id": eid, "sha256": digest, "source_run_id": run_id,
                "kind": kind, "total_chars": len(encoded)}


def test_extract_cache_usage_normalizes_openai_deepseek_and_anthropic():
    oa = extract_cache_usage({"prompt_tokens": 1000, "prompt_tokens_details": {"cached_tokens": 800}})
    assert oa == {"prompt_tokens": 1000, "cached_tokens": 800,
                  "cache_creation_tokens": None, "cache_hit_ratio": 0.8}

    ds = extract_cache_usage({"prompt_tokens": 2000, "prompt_cache_hit_tokens": 1500, "prompt_cache_miss_tokens": 500})
    assert ds == {"prompt_tokens": 2000, "cached_tokens": 1500,
                  "cache_creation_tokens": None, "cache_hit_ratio": 0.75}

    ds_no_total = extract_cache_usage({"prompt_cache_hit_tokens": 600, "prompt_cache_miss_tokens": 400})
    assert ds_no_total["prompt_tokens"] == 1000 and ds_no_total["cache_hit_ratio"] == 0.6

    ant = extract_cache_usage({"input_tokens": 500, "cache_read_input_tokens": 400, "cache_creation_input_tokens": 100})
    assert ant == {"prompt_tokens": 500, "cached_tokens": 400,
                   "cache_creation_tokens": 100, "cache_hit_ratio": 0.8}

    empty = extract_cache_usage({})
    assert empty == {"prompt_tokens": None, "cached_tokens": None,
                     "cache_creation_tokens": None, "cache_hit_ratio": None}


def test_system_prefix_and_history_stay_append_only_across_mid_run_skill_load(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_OPTIMIZE_ROUND_TRIPS", "1")
    requests = []

    class ScriptedModel:
        def invoke(self, request):
            requests.append(request)
            if len(requests) == 1:
                return ModelResponse(
                    tool_calls=(ToolCall("load1", "skill_load", {"skill_id": "geodesic_coordinate_analysis"}),),
                    finish_reason="tool_calls",
                    usage={"prompt_tokens": 1000, "prompt_tokens_details": {"cached_tokens": 0}},
                )
            if len(requests) == 2:
                return ModelResponse(
                    tool_calls=(ToolCall("dist1", "GeoHaversineDistance",
                                         {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 1}),),
                    finish_reason="tool_calls",
                    usage={"prompt_tokens": 1400, "prompt_tokens_details": {"cached_tokens": 950}},
                )
            return ModelResponse(
                "Distance is approximately 111.195 km.",
                usage={"prompt_tokens": 1600, "prompt_tokens_details": {"cached_tokens": 1350}},
            )

    agent = create_agent(ScriptedModel(), settings=Settings(verify_completion=False, max_model_turns=5))
    result = agent.run("Calculate distance from (0,0) to (0,1).", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert len(requests) == 3

    # System prompt (messages[0]) must stay byte-for-byte identical even after skill_load!
    assert requests[0].messages[0] == requests[1].messages[0] == requests[2].messages[0]
    # Turn 1 prefix is preserved verbatim in Turn 2; Turn 2 prefix (including inline skill disclosure)
    # is preserved verbatim in Turn 3.
    assert requests[1].messages[:len(requests[0].messages)] == requests[0].messages
    assert requests[2].messages[:len(requests[1].messages)] == requests[1].messages
    # Skill instructions were disclosed inline right after the skill_load tool result.
    assert any("Loaded skill: geodesic_coordinate_analysis" in m.content for m in requests[1].messages[1:])
    # Tool definitions are strictly append-only across skill_load.
    t0 = [t.name for t in requests[0].tools]
    t1 = [t.name for t in requests[1].tools]
    assert t1[:len(t0)] == t0 and "GeoHaversineDistance" in t1

    # Cache telemetry is recorded in metadata.
    metrics = result.state["metadata"]["prompt_cache_metrics"]
    assert metrics["execution_turns"] == 3
    assert metrics["system_prefix_stable_turns"] == 2
    assert metrics["append_only_prefix_turns"] == 2
    assert metrics["total_prompt_tokens"] == 4000
    assert metrics["total_cached_tokens"] == 2300
    assert metrics["cache_hit_ratio"] == round(2300 / 4000, 4)


def test_execution_repair_draft_appends_at_tail_preserving_history_prefix(tmp_path):
    agent = create_agent(object(), settings=Settings(verify_completion=False))
    call = ToolCall("c1", "read_file", {"path": "a.txt"})
    tool_msg = ToolResult("c1", "read_file", "ok", {"path": "a.txt", "content": "hello"}).message()
    base_state = {
        "task": "Read a.txt",
        "messages": [Message("user", "Read a.txt"), Message("assistant", "", (call,)), tool_msg],
        "selected_skill_ids": [],
        "exposed_tool_names": ["read_file"],
        "metadata": {},
    }
    before = agent.context.build(base_state)
    with_repair = deepcopy(base_state)
    with_repair["metadata"]["execution_repair_draft"] = {
        "text": "Unverified draft", "feedback": "Execute first", "turn": 2, "status": "rejected_unverified_draft",
    }
    after = agent.context.build(with_repair)
    # Entire prior conversation prefix stays identical; repair draft is appended at tail.
    assert after.messages[:len(before.messages)] == before.messages
    assert after.messages[-1].role == "user"
    assert after.messages[-1].content.startswith("Unaccepted working draft retained for correction")


def test_fit_skill_scope_keeps_append_only_order_when_all_skills_fit():
    registry = SkillRegistry()
    defs = {}
    for i in range(3):
        sid, name = f"s{i}", f"Tool{i}"
        registry.register(Skill(SkillSummary(sid, sid, "desc", "when"), (), "instr", (), (name,), ()))
        defs[name] = ToolDefinition(name, "op", "when", object_schema({}), {})
    skills = SkillLoader(registry)
    state = {
        "run_id": "a" * 32, "task": "Run tools",
        "selected_skill_ids": ["s0", "s1", "s2"],
        "exposed_tool_names": ["Tool0", "Tool1", "Tool2"],
        "pending_tool_calls": [],
        "messages": [Message("user", "Run tools")],
        "metadata": {"skill_scope_focus": ["s2"]},
        "artifacts": [],
    }
    build = lambda current: ModelRequest(
        (Message("system", "Policy"), *current["messages"]),
        tuple(defs[n] for n in current["exposed_tool_names"]),
    )
    scoped, _ = fit_skill_scope(
        state, build_request=build, base_tool_names=(), skills=skills,
        settings=Settings(context_window_tokens=None, max_context_chars=50000),
    )
    assert scoped["selected_skill_ids"] == ["s0", "s1", "s2"]
    assert scoped["exposed_tool_names"] == ["Tool0", "Tool1", "Tool2"]


def test_fitting_request_above_ninety_percent_is_not_prematurely_rewritten():
    messages = [Message("user", "Compare observed reads.")]
    for i in range(4):
        cid = f"r{i}"
        messages += [
            Message("assistant", tool_calls=(ToolCall(cid, "read_file", {"path": f"f{i}.txt"}),)),
            ToolResult(cid, "read_file", "ok", {"path": f"f{i}.txt", "content": ("same geological line " * 120)}).message(),
        ]
    state = {"run_id": "a" * 32, "task": messages[0].content, "messages": messages, "metadata": {}}
    request = ModelRequest((Message("system", "Policy."), *messages), ())
    probe_settings = Settings(context_window_tokens=32000, max_output_tokens=256)
    tokens = request_budget_size(request, probe_settings)
    # Pick a window whose input_allowance sits just above `tokens` (between 91% and 99%).
    window = int((tokens + 256 + 1024 + 40) / 0.95)
    settings = Settings(context_window_tokens=window, max_output_tokens=256)
    limit = input_allowance(settings)
    assert int(limit * 0.9) < tokens <= limit
    fitted = fit_request(request, state, settings)
    assert fitted is request
    assert "context_compactions" not in state["metadata"]
    assert not any("shared-values-v1" in m.content for m in fitted.messages)


def test_tool_result_clearing_archives_stale_reads_without_shared_values_encoding():
    messages = [Message("user", "Analyze search hits and file reads.")]
    for i in range(5):
        cid = f"s{i}"
        messages += [
            Message("assistant", tool_calls=(ToolCall(cid, "web_search", {"query": f"deposit {i}"}),)),
            ToolResult(cid, "web_search", "ok", {
                "query": f"deposit {i}",
                "results": [{"url": f"https://example.org/{i}", "snippet": f"unique porphyry mineralization body {i} " * 180}],
            }).message(),
        ]
    messages += [
        Message("assistant", tool_calls=(ToolCall("calc1", "GeoCalc", {"x": 1}),)),
        ToolResult("calc1", "GeoCalc", "ok", {"value": 42.5, "unit": "ppm"}).message(),
    ]
    state = {"run_id": "a" * 32, "task": messages[0].content, "messages": messages, "metadata": {}}
    original = deepcopy(state)
    request = ModelRequest((Message("system", "Policy."), *messages), ())
    archive = MemoryArchive()
    probe = Settings(context_window_tokens=64000, max_output_tokens=256)
    full_tokens = request_budget_size(request, probe)
    # Choose an input_allowance around 55% of full_tokens so stale web_search bodies must be cleared,
    # while keeping the newest web_search (s4) and GeoCalc (calc1) completely intact.
    target_allowance = int(full_tokens * 0.55)
    window = max(target_allowance + 256 + 1024 + 200, int((target_allowance + 256) / 0.95) + 100)
    settings = Settings(context_window_tokens=window, max_output_tokens=256)
    limit = input_allowance(settings)
    assert full_tokens > limit

    fitted = fit_request(request, state, settings, archive=archive)
    assert request_budget_size(fitted, settings) <= limit
    # Original authoritative state is untouched.
    assert state["messages"] == original["messages"]
    # Native assistant/tool block structure is preserved intact!
    ContextManager._blocks(fitted.messages)
    assert sum(m.role == "tool" for m in fitted.messages) == 6
    # Zero shared-values-v1 pointer encoding!
    assert not any("shared-values-v1" in m.content for m in fitted.messages)
    # Strategy is tool_result_clearing and archive contains original payloads.
    event = state["metadata"]["context_compactions"][-1]
    assert event["strategies"] == ["tool_result_clearing"]
    assert event["retrieval_required"] is True
    assert len(archive.rows) >= 2
    # Latest web_search (s4) and latest calculation (calc1) remain intact and un-cleared.
    by_id = {m.tool_call_id: json.loads(m.content) for m in fitted.messages if m.role == "tool"}
    assert "cleared_for_context_budget" not in by_id["s4"]["data"]
    assert by_id["calc1"]["data"] == {"value": 42.5, "unit": "ppm"}
    # Cleared older search keeps query metadata + archive evidence_id that maps to exact original payload.
    cleared_s0 = by_id["s0"]["data"]
    assert cleared_s0["cleared_for_context_budget"] is True
    assert cleared_s0["query"] == "deposit 0"
    assert archive.rows[cleared_s0["archived_data"]["evidence_id"]]["query"] == "deposit 0"

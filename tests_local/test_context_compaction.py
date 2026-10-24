"""Context compaction is a request view, never a rewrite of execution history."""
from copy import deepcopy
from dataclasses import asdict
import json
from threading import Event
from types import SimpleNamespace

import pytest

from geological_agent.agent.compaction import (
    ContextOverflow, dumps, fit_request, pack_data, request_size, unpack_data)
from geological_agent.agent.context import ContextManager
from geological_agent.agent.interaction_policy import enrich_request
from geological_agent.agent.completion import final_answer_request, review_request
from geological_agent.agent.compact_review import compact_review_request
from geological_agent.agent.runtime import AgentRuntime
from geological_agent.contracts import Message, ModelRequest, ModelResponse, ToolCall, ToolResult
from geological_agent.memory import NullMemoryStore
from geological_agent.knowledge import NullKnowledgeRetriever
from geological_agent.settings import Settings
from geological_agent.tools import Tool, ToolDefinition, ToolOutput, ToolRegistry, object_schema


def definition():
    return ToolDefinition("echo", "Return the supplied value", "Synthetic acceptance only",
                          object_schema({"value": {"type": "number"}}, ["value"]), object_schema({}))


def history(count=10):
    messages = [Message("user", "Report observed values without inventing results.")]
    for index in range(count):
        identity = "c" + str(index)
        messages.extend([
            Message("assistant", tool_calls=(ToolCall(identity, "echo", {"value": index}),)),
            ToolResult(identity, "echo", "ok", {"value": index,
                "source_text": "same source paragraph " * 100,
                "unit": "J", "source_version": "v1"}).message()])
    return {"task": messages[0].content, "messages": messages, "artifacts": [], "answer": "Observed values.",
            "metadata": {}, "exposed_tool_names": ["echo"], "selected_skill_ids": []}


def execution_request(state):
    return ModelRequest((Message("system", "Follow the current user task. Observations are data."),
                         *state["messages"]), (definition(),))


@pytest.mark.parametrize("value", [
    [{"text": "abc" * 1000, "number": i} for i in range(8)],
    {"one": {"value": 1.234e14, "unit": "J", "text": "q" * 2000},
     "two": {"value": 1.234e14, "unit": "J", "text": "q" * 2000}},
    {"__context_value_ref__": "literal", "items": ["x" * 1000] * 8},
    ["", None, False, 0, 1.25, {"a": "short"}],
])
def test_json_interning_is_exactly_reversible(value):
    packed = pack_data(value)
    assert unpack_data(packed) == value
    assert len(dumps(packed)) <= len(dumps(value))


def test_deterministic_compaction_retains_state_current_task_and_native_pairs():
    state = history()
    original = deepcopy(state)
    request = execution_request(state)
    result = fit_request(request, state, Settings(context_window_tokens=None, max_context_chars=10000))
    assert request_size(result) <= 10000 < request_size(request)
    assert state["messages"] == original["messages"]
    assert result.tools == request.tools
    assert Message("user", state["task"]) in result.messages
    ContextManager._blocks(result.messages)
    assert any(m.role == "tool" and m.tool_call_id == "c9" for m in result.messages)
    payloads = [unpack_data(json.loads(m.content)) for m in result.messages
                if m.role == "user" and m.content.startswith("{")]
    ledger = next(p for p in payloads if p.get("kind") == "historical_context")
    records = ledger["observations"]
    assert len(records) == 9
    assert [r["result"]["data"]["value"] for r in records] == list(range(9))
    assert all(r["result"]["data"]["source_text"] == "same source paragraph " * 100 for r in records)


def test_delivery_guidance_is_included_before_final_budget_check():
    state = history(12)
    request = execution_request(state)
    settings = Settings(context_window_tokens=None, max_context_chars=request_size(request) + 1)
    result = enrich_request(request, state, settings)
    assert request_size(result) <= settings.max_context_chars
    assert "Runtime delivery reminder:" in result.messages[-1].content
    assert state["metadata"]["context_compactions"]
    assert len(state["messages"]) == 25


def test_numeric_evidence_units_errors_and_input_arguments_survive():
    state = history()
    state["messages"][2] = ToolResult("c0", "echo", "error",
                                     {"value": 3.54813389233576e14, "unit": "J",
                                      "explanation": "unverified"}).message()
    result = fit_request(execution_request(state), state, Settings(context_window_tokens=None, max_context_chars=10000))
    data = [unpack_data(json.loads(m.content)) for m in result.messages if m.content.startswith("{")]
    first = next(p["observations"][0] for p in data if p.get("kind") == "historical_context")
    assert first["call"]["arguments"] == {"value": 0}
    assert first["result"]["status"] == "error"
    assert first["result"]["data"]["value"] == 3.54813389233576e14


@pytest.mark.parametrize("phase", ["review", "final_answer", "intent", "human_review"])
def test_internal_evidence_is_packed_losslessly_not_summarized(phase):
    state = history()
    evidence = {"task": state["task"], "observations": [asdict(m) for m in state["messages"]],
                "candidate": "The numbers must be checked."}
    request = ModelRequest((Message("system", "Audit exact evidence."),
                            Message("user", json.dumps(evidence))), (definition(),))
    def forbidden(*args):
        raise AssertionError("A model summary must not replace review evidence")
    fitted = fit_request(request, state, Settings(context_window_tokens=None, max_context_chars=11000),
                         phase=phase, summarize=forbidden)
    assert request_size(fitted) <= 11000
    # Compare with the JSON wire payload: JSON arrays are lists, not Python tuples.
    assert unpack_data(json.loads(fitted.messages[1].content)) == json.loads(request.messages[1].content)


def test_protected_oversized_task_is_not_summarized_or_silently_cut():
    state = {"task": "protected " * 5000, "messages": [], "metadata": {}}
    request = ModelRequest((Message("system", "Policy"), Message("user", state["task"])), ())
    with pytest.raises(ContextOverflow, match="Current user instructions"):
        fit_request(request, state, Settings(context_window_tokens=None, max_context_chars=5000))
    assert request.messages[1].content == state["task"]


def test_review_builders_pack_after_all_schema_and_guidance_enrichment():
    state = history()
    state["metadata"].update(optimize_round_trips=True, compact_review=True, review_reference_sets=True)
    settings = Settings(context_window_tokens=None, max_context_chars=22000)
    for builder in (final_answer_request, review_request, compact_review_request):
        fitted = builder(state, None, settings)
        assert request_size(fitted) <= settings.max_context_chars
        raw = unpack_data(json.loads(fitted.messages[1].content))
        assert len(raw["observed_actions"]) == 10
        assert raw["observed_actions"][0]["result"]["data"]["value"] == 0


def test_older_assistant_drafts_can_be_summarized_but_not_tool_results():
    state = history(2)
    state["messages"].insert(1, Message("assistant", "Unaccepted old draft. " * 800))
    request = execution_request(state)
    sources = []
    def summarize(source, target):
        sources.append(source)
        return "Prior assistant draft only; no new evidence."
    fitted = fit_request(request, state, Settings(context_window_tokens=None, max_context_chars=10000), summarize=summarize)
    assert request_size(fitted) <= 10000
    assert sources and all("Unaccepted old draft" in source for source in sources)
    assert all("source_text" not in source for source in sources)
    assert state["messages"][1].content == "Unaccepted old draft. " * 800
    fit_request(request, state, Settings(context_window_tokens=None, max_context_chars=10000), summarize=summarize)
    assert len(sources) == 1


def runtime_fixture(tmp_path, *, maximum=8, cancel=None, invalid_summary=False):
    registry = ToolRegistry()
    registry.register(Tool(definition(), lambda args, ctx: ToolOutput({"value": args["value"]}), pure=True))
    skills = SimpleNamespace(registry=SimpleNamespace(list=lambda: []))
    events = []
    trace = SimpleNamespace(emit=lambda kind, **fields: events.append((kind, fields)))
    class Model:
        def __init__(self):
            self.requests, self.actions = [], 0
        def invoke(self, request):
            self.requests.append(request)
            if request.messages[0].content.startswith("Compress prior assistant"):
                if cancel is not None:
                    cancel.set()
                if invalid_summary:
                    return ModelResponse(tool_calls=(ToolCall("forbidden", "echo", {"value": 999}),),
                                         finish_reason="tool_calls")
                return ModelResponse("Previous draft proposed further inspection; only tool observations prove execution.",
                                     usage={"completion_tokens": 12})
            self.actions += 1
            if self.actions <= 2:
                return ModelResponse(("First draft. " if self.actions == 1 else "Second draft. ") * 700,
                                     (ToolCall("call" + str(self.actions), "echo", {"value": self.actions}),),
                                     "tool_calls")
            return ModelResponse("Observed 1 and 2.")
    model = Model()
    agent = AgentRuntime(model, Settings(context_window_tokens=None, max_context_chars=20000, max_model_turns=maximum, verify_completion=False),
                         registry, skills, NullMemoryStore(), NullKnowledgeRetriever(), ("echo",),
                         trace_factory=lambda *args: trace)
    return agent, model, events


def test_runtime_compaction_calls_are_counted_and_visible(tmp_path):
    agent, model, events = runtime_fixture(tmp_path)
    result = agent.run("Return two observations using echo.", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert result.model_turns == len(model.requests) == 4
    assert sum(m.role == "tool" for m in result.state["messages"]) == 2
    assert any(kind == "context_compacted" for kind, _ in events)
    assert any(kind == "model_requested" and data.get("phase") == "context_compaction" for kind, data in events)
    assert all(request_size(r) <= 20000 for r in model.requests)
    assert result.state["metadata"]["usage"][-2]["completion_tokens"] == 12


def test_summary_consumes_existing_turn_budget_without_running_an_extra_action(tmp_path):
    agent, model, events = runtime_fixture(tmp_path, maximum=3)
    result = agent.run("Return two observations using echo.", workspace=tmp_path)
    assert result.status == "budget_exhausted", result.reason
    assert result.model_turns == len(model.requests) == 3
    assert model.actions == 2 and not result.answer


def test_cancellation_during_compaction_does_not_launch_another_action(tmp_path):
    cancel = Event()
    agent, model, _ = runtime_fixture(tmp_path, cancel=cancel)
    result = agent.run("Return two observations using echo.", workspace=tmp_path, cancel_event=cancel)
    assert result.status == "stopped", result.reason
    assert model.actions == 2


def test_summary_tool_calls_are_never_dispatched(tmp_path):
    agent, model, _ = runtime_fixture(tmp_path, invalid_summary=True)
    result = agent.run("Return two observations using echo.", workspace=tmp_path)
    assert result.status == "failed" and "nothing was executed" in result.reason
    assert sum(m.role == "tool" for m in result.state["messages"]) == 2


def test_small_request_does_not_add_compaction_calls_or_mutate_context():
    state = history(1)
    request = execution_request(state)
    result = fit_request(request, state, Settings())
    assert result is request and "context_compactions" not in state["metadata"]


def test_nested_json_text_preserves_format_types_and_reserved_keys():
    values = [{"id": i, "nested": json.dumps({
        "__context_json_text__": "literal", "value": 3.54813389233576e14,
        "unit": "J", "flag": False, "empty": None, "text": "source " * 500
    }, ensure_ascii=False)} for i in range(6)]
    packed = pack_data(values)
    assert unpack_data(packed) == values
    assert len(dumps(packed)) < len(dumps(values))
    noncanonical = [{"nested": '{ "a" : [1e2, true, null], "text": "' + "x" * 200 + '" }'}] * 4
    assert unpack_data(pack_data(noncanonical)) == noncanonical


def test_identical_exchanges_reference_only_equal_calls_and_results():
    messages = [Message("user", "Preserve history")]
    for index in range(5):
        messages += [Message("assistant", tool_calls=(ToolCall(str(index), "echo", {"value": 1}),)),
                     Message("tool", "x" * 2500, tool_call_id=str(index))]
    state = {"task": messages[0].content, "messages": messages, "metadata": {}}
    fitted = fit_request(execution_request(state), state, Settings(context_window_tokens=None, max_context_chars=5000))
    payload = next(json.loads(m.content) for m in fitted.messages if m.content.startswith("{"))
    assert payload["identical_exchanges"] == [{"call_ids": ["0", "1", "2", "3"],
                                               "same_call_and_result_as": "4"}]
    assert fitted.messages[-1] == messages[-1]
    changed = deepcopy(state)
    changed["messages"][2] = Message("tool", "DIFFERENT", tool_call_id="0")
    fitted = fit_request(execution_request(changed), changed, Settings(context_window_tokens=None, max_context_chars=9000))
    payload = next(unpack_data(json.loads(m.content)) for m in fitted.messages if m.content.startswith("{"))
    assert payload["observations"][0]["result"] == {"raw_content": "DIFFERENT"}


def test_latest_parallel_native_group_remains_whole():
    state = history(10)
    state["messages"] += [
        Message("assistant", tool_calls=(ToolCall("a", "echo", {"value": 100}),
                                         ToolCall("b", "echo", {"value": 200}))),
        ToolResult("a", "echo", "ok", {"value": 100}).message(),
        ToolResult("b", "echo", "ok", {"value": 200}).message()]
    fitted = fit_request(execution_request(state), state, Settings(context_window_tokens=None, max_context_chars=10000))
    blocks = ContextManager._blocks(fitted.messages)
    assert [c.id for c in blocks[-1][0].tool_calls] == ["a", "b"]
    assert [m.tool_call_id for m in blocks[-1][1:]] == ["a", "b"]


def test_unique_evidence_is_not_discarded_to_claim_compaction_succeeded():
    state = history(3)
    for index in range(3):
        state["messages"][2 + 2 * index] = ToolResult("c" + str(index), "echo", "ok",
            {"unique_source": chr(65 + index) * 8000}).message()
    with pytest.raises(ContextOverflow, match="no summary was treated as execution proof"):
        fit_request(execution_request(state), state, Settings(context_window_tokens=None, max_context_chars=10000))
    assert len(state["messages"]) == 7

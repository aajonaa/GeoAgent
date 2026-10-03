import json
from types import SimpleNamespace

import pytest

from geological_agent.agent.compact_review import indexes, parse_compact_review, schema_for
from geological_agent.agent.intent_review import parse_intent
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import Message, ModelResponse, ToolCall, ToolResult
from geological_agent.geology.validation import validate_energy_answer
from geological_agent.llm import ModelProtocolError
from geological_agent.settings import Settings
from geological_agent.tools import object_schema


def call(name, args, identity="internal"):
    return ModelResponse(tool_calls=(ToolCall(identity, name, args),), finish_reason="tool_calls")


class Model:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        result = next(self.responses)
        return result(request) if callable(result) else result


def completion(request, *, bad=False):
    keys = request.tools[0].input_schema["properties"]["requirement_checks"]["properties"]
    return call("assess_completion", {"verdict": "complete", "feedback": "", "required_outputs": ["result.txt"],
                "requires_python_execution": False, "evidence_call_ids": ["t1"],
                "requirement_checks": {key: {"ok": True, "a": ["a999" if bad else "a1"], "t": ["t1"]}
                                       for key in keys}})


def test_bare_input_pauses_before_any_domain_or_file_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_INTENT_REVIEW", "1")
    model = Model(call("assess_task_intent", {"objective_present": False, "question": "What should I calculate?"}))
    result = create_agent(model, human_input=True).run("Beijing: 39.9042,116.4074; Shanghai:31.2304,121.4737",
               workspace=tmp_path / "work", checkpoint_path=tmp_path / "checkpoints.sqlite3")
    assert result.status == "needs_input" and result.model_turns == 1
    assert result.answer == "What should I calculate?"
    assert not [m for m in result.state["messages"] if m.role == "tool"]
    assert model.requests[0].tool_choice == "required"


def test_intent_resume_uses_actual_reply_and_does_not_ask_again(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_INTENT_REVIEW", "1")
    model = Model(call("assess_task_intent", {"objective_present": False, "question": "Desired outcome?"}),
                  call("assess_task_intent", {"objective_present": True, "question": ""}), ModelResponse("Hello."))
    agent = create_agent(model, human_input=True, settings=Settings(verify_completion=False))
    kwargs = {"workspace": tmp_path / "work", "checkpoint_path": tmp_path / "checkpoint.sqlite3"}
    first = agent.run("Coordinates: 1, 2", **kwargs)
    reply = {"run_id": first.run_id, "request_id": first.state["metadata"]["pending_input"]["id"],
             "text": "Just say hello", "files": []}
    second = agent.run("Coordinates: 1, 2", resume=reply, **kwargs)
    assert second.status == "completed" and second.answer == "Hello."
    assert second.model_turns == 3
    assert "Just say hello" in model.requests[1].messages[1].content
    assert len(model.requests) == 3


def test_intent_obeys_budget_without_authorizing_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_INTENT_REVIEW", "1")
    model = Model(call("assess_task_intent", {"objective_present": True, "question": ""}))
    result = create_agent(model, settings=Settings(max_model_turns=1)).run("Calculate something", workspace=tmp_path)
    assert result.status == "budget_exhausted" and result.model_turns == 1
    assert len(model.requests) == 1 and not result.artifacts


@pytest.mark.parametrize("args", [
    {"objective_present": True, "question": "What?"},
    {"objective_present": False, "question": ""},
    {"objective_present": "false", "question": "What?"},
])
def test_intent_contract_rejects_contradictory_decisions(args):
    with pytest.raises(ModelProtocolError):
        parse_intent(call("assess_task_intent", args))


def state():
    return {"task": "Compute for 39.9042,116.4074. Report two decimals.", "answer": "Distance: 1067.31 km\nBearing: 153.07 degrees",
            "metadata": {}, "messages": [ToolResult("long-provider-id", "GeoHaversineDistance", "ok", {"km": 1067.311645}).message(),
                                          ToolResult("failed-provider-id", "Other", "error").message()]}


def request_and_args(s):
    requirements, _, _ = indexes(s)
    base = object_schema({"verdict": {"type": "string"}, "feedback": {"type": "string"},
                          "required_outputs": {"type": "array", "items": {"type": "string"}},
                          "requires_python_execution": {"type": "boolean"},
                          "evidence_call_ids": {"type": "array", "items": {"type": "string"}}},
                         ["verdict", "feedback", "required_outputs", "requires_python_execution", "evidence_call_ids"])
    req = SimpleNamespace(tools=(SimpleNamespace(name="assess_completion", input_schema=schema_for(base, requirements)),))
    args = {"verdict": "complete", "feedback": "", "required_outputs": [], "requires_python_execution": False,
            "evidence_call_ids": ["t1"], "requirement_checks": {key: {"ok": True, "a": ["a1", "a2"], "t": ["t1"]} for key in requirements}}
    return req, args


def test_short_ids_resolve_to_actual_answer_and_successful_evidence():
    s = state()
    req, args = request_and_args(s)
    parsed = parse_compact_review(call("assess_completion", args), s, req)
    assert parsed["evidence_call_ids"] == ["long-provider-id"]
    assert parsed["requirement_checks"]["r1"]["answer_quotes"] == s["answer"].splitlines()
    assert len(parsed["requirement_checks"]) == 2
    assert indexes(s)[2] == {"t1": "long-provider-id"}
    assert "39.9042" in indexes(s)[0]["r1"]


@pytest.mark.parametrize("kind", ["answer", "tool", "omitted_requirement", "extra_requirement"])
def test_compact_references_cannot_fabricate_or_omit_evidence(kind):
    s = state()
    req, args = request_and_args(s)
    if kind == "answer":
        args["requirement_checks"]["r1"]["a"] = ["a999"]
    elif kind == "tool":
        args["evidence_call_ids"] = ["failed-provider-id"]
    elif kind == "omitted_requirement":
        del args["requirement_checks"]["r2"]
    else:
        args["requirement_checks"]["invented"] = {"ok": True, "a": [], "t": []}
    with pytest.raises(ModelProtocolError):
        parse_compact_review(call("assess_completion", args), s, req)


def test_unmet_requirement_cannot_be_approved():
    s = state()
    req, args = request_and_args(s)
    args["requirement_checks"]["r2"]["ok"] = False
    result = parse_compact_review(call("assess_completion", args), s, req)
    assert result["verdict"] == "revise_answer" and "r2" in result["feedback"]


def test_human_reply_requirements_are_not_omitted():
    s = state()
    s["metadata"]["human_responses"] = [{"text": "Also report the assumptions."}]
    assert "assumptions" in indexes(s)[0]["r3"]


def test_repeated_invalid_review_revises_answer_without_rerunning_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_COMBINED_COMPLETION_REVIEW", "1")
    monkeypatch.setenv("GEOTOOL_COMPACT_REVIEW", "1")
    model = Model(call("write_file", {"path": "result.txt", "content": "42"}, "write1"),
                  ModelResponse("Created result.txt containing 42."),
                  lambda req: completion(req, bad=True), lambda req: completion(req, bad=True),
                  ModelResponse("result.txt contains 42."), completion)
    result = create_agent(model).run("Create result.txt containing 42 and report its content", workspace=tmp_path)
    assert result.status == "completed" and result.model_turns == 6
    assert len([m for m in result.state["messages"] if m.role == "tool"]) == 1
    assert model.requests[4].tool_choice == "none"
    assert len(result.state["metadata"]["review_protocol_errors"]) == 2
    assert result.state["metadata"]["completion_reviews"][0]["evidence_call_ids"] == ["write1"]
    assert (tmp_path / "result.txt").read_text() == "42"


def test_compaction_does_not_replace_numeric_validation():
    s = {"answer": "Energy: 3.548e17 J", "messages": [
        Message("assistant", tool_calls=(ToolCall("energy1", "GeoMagnitudeToEnergy", {"mw": 6.5}),)),
        ToolResult("energy1", "GeoMagnitudeToEnergy", "ok", {"energy_j": 354813389233576.06, "tnt_tons": 84802.43528527152}).message()]}
    assert validate_energy_answer(s)

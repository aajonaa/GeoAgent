"""Regression for repeated, fully valid internal intent assessments."""
from contextlib import nullcontext

import pytest

from geological_agent.agent.intent_review import parse_intent
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import ModelResponse, ToolCall
from geological_agent.llm import ModelProtocolError
from geological_agent.settings import Settings


YES = {"objective_present": True, "question": ""}
NO = {"objective_present": False, "question": "What should I calculate?"}


def response(*args, finish="stop"):
    return ModelResponse(tool_calls=tuple(ToolCall("call-" + str(i), "assess_task_intent", value)
                                          for i, value in enumerate(args)), finish_reason=finish)


@pytest.mark.parametrize("finish", ["stop", "tool_calls"])
@pytest.mark.parametrize("decision", [YES, NO])
def test_equivalent_internal_decisions_are_coalesced_after_validation(finish, decision):
    assert parse_intent(response(decision, decision, finish=finish)) == decision


def test_json_whitespace_and_key_order_do_not_create_a_conflict():
    result = response('{"objective_present":true,"question":""}', '{ "question": "", "objective_present": true }')
    assert parse_intent(result) == YES


@pytest.mark.parametrize("other", [
    NO, {"objective_present": "true", "question": ""},
    {"objective_present": True, "question": "Contradiction"},
    {"objective_present": True, "question": "", "unexpected": 1},
    '{"objective_present":true,"objective_present":false,"question":""}',
    '{"objective_present":true,', None,
])
def test_a_valid_first_call_cannot_hide_invalid_or_conflicting_followups(other):
    with pytest.raises(ModelProtocolError):
        parse_intent(response(YES, other))


@pytest.mark.parametrize("finish", ["length", "", "content_filter"])
def test_incomplete_responses_are_not_coalesced(finish):
    with pytest.raises(ModelProtocolError):
        parse_intent(response(YES, YES, finish=finish))


@pytest.mark.parametrize("other", [
    ToolCall("other", "write_file", {"path": "unauthorized.txt", "content": "bad"}),
    ToolCall("", "assess_task_intent", YES),
    ToolCall("same", "assess_task_intent", YES),
])
def test_foreign_functions_and_invalid_call_ids_are_rejected(other):
    result = ModelResponse(tool_calls=(ToolCall("same", "assess_task_intent", YES), other), finish_reason="stop")
    with pytest.raises(ModelProtocolError):
        parse_intent(result)


class Model:
    def __init__(self, *outputs):
        self.outputs = iter(outputs)
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        return next(self.outputs)


class Trace:
    def __init__(self):
        self.events = []

    def emit(self, event, **fields):
        self.events.append((event, fields))

    def execution_context(self):
        return nullcontext()


def test_runtime_preserves_raw_calls_and_records_coalescing_without_extra_model_turn(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_INTENT_REVIEW", "1")
    raw = response(YES, YES)
    model = Model(raw, ModelResponse("Hello."))
    agent = create_agent(model, settings=Settings(verify_completion=False))
    trace = Trace()
    agent.trace_factory = lambda *args: trace
    result = agent.run("Say hello", workspace=tmp_path)
    assert result.status == "completed" and result.answer == "Hello."
    assert result.model_turns == 2 and len(model.requests) == 2
    coalesced = result.state["metadata"]["intent_assessment_coalesces"]
    assert len(coalesced) == 1
    assert coalesced[0]["call_ids"] == ["call-0", "call-1"]
    assert coalesced[0]["assessment"] == YES
    original = [fields for name, fields in trace.events if name == "model_responded"][0]
    assert original["response"] is raw and len(raw.tool_calls) == 2
    assert [fields for name, fields in trace.events if name == "intent_assessment_coalesced"]
    assert not [message for message in result.state["messages"] if message.role == "tool"]


def test_conflicting_decisions_cannot_authorize_any_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_INTENT_REVIEW", "1")
    model = Model(response(YES, NO), response(YES, NO))
    result = create_agent(model).run("Calculate energy", workspace=tmp_path)
    assert result.status == "incomplete"
    assert "Conflicting intent assessments" in result.reason
    assert len(model.requests) == 2
    assert len(result.state["metadata"]["protocol_failures"]) == 2
    assert all(item["phase"] == "intent" for item in result.state["metadata"]["protocol_failures"])
    assert not result.state["metadata"].get("objective_checked")
    assert not result.artifacts
    assert not [message for message in result.state["messages"] if message.role == "tool"]


def test_equivalent_missing_objective_still_pauses_without_executing_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_INTENT_REVIEW", "1")
    model = Model(response(NO, NO))
    result = create_agent(model, human_input=True).run(
        "39.9042,116.4074", workspace=tmp_path / "work", checkpoint_path=tmp_path / "state.sqlite3")
    assert result.status == "needs_input" and result.answer == NO["question"]
    assert result.model_turns == 1 and len(model.requests) == 1
    assert result.state["metadata"]["pending_input"]["question"] == NO["question"]
    assert not [message for message in result.state["messages"] if message.role == "tool"]

"""Efficiency must preserve real actions, HITL pairing, and completion gates."""
import json
from types import SimpleNamespace

import pytest

from geological_agent.bootstrap import create_agent
from geological_agent.settings import Settings
from geological_agent.contracts import Message, ModelRequest, ModelResponse, ToolCall, ToolResult
from geological_agent.agent.completion import (
    CompletionIssue, final_answer_request, parse_review, review_request,
)
from geological_agent.llm import ModelProtocolError


class Scripted:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        return next(self.responses)


def action(*calls):
    return ModelResponse(tool_calls=tuple(calls), finish_reason="tool_calls")


def question(cid="ask"):
    return ToolCall(cid, "request_user_input", {
        "question": "Which coefficient?", "reason": "The coefficient was not provided.",
        "missing": ["coefficient"], "options": [],
    })


def calculate(cid="calc", code="from pathlib import Path\np=Path('sum.txt')\np.write_text(str(2+3))\nassert p.read_text()=='5'\nprint(p.read_text())"):
    return ToolCall(cid, "execute_python", {"code": code})


def assessment(cid, *, verdict="complete", evidence=("calc",), outputs=("sum.txt",)):
    return action(ToolCall(cid, "assess_completion", {
        "verdict": verdict, "feedback": "Observed result supports the requested work.",
        "required_outputs": list(outputs), "requires_python_execution": True,
        "evidence_call_ids": list(evidence),
    }))


@pytest.fixture(autouse=True)
def optimized(monkeypatch):
    monkeypatch.setenv("GEOTOOL_OPTIMIZE_ROUND_TRIPS", "1")


def test_ordered_action_then_question_pauses_without_rejection_and_resumes(tmp_path):
    model = Scripted([action(calculate(), question())])
    agent = create_agent(model, settings=Settings(verify_completion=False), human_input=True)
    work, checkpoint = tmp_path / "work", tmp_path / "checkpoint.sqlite3"
    paused = agent.run("Compute 2+3, then ask for a coefficient.", workspace=work, checkpoint_path=checkpoint)
    assert paused.status == "needs_input" and paused.model_turns == 1
    assert (work / "sum.txt").read_text() == "5"
    assert not paused.state["pending_tool_calls"]
    results = [json.loads(m.content) for m in paused.state["messages"] if m.role == "tool"]
    assert [(r["call_id"], r["status"]) for r in results] == [("calc", "ok"), ("ask", "ok")]
    resumed_model = Scripted([ModelResponse("The coefficient was received.")])
    resumed_agent = create_agent(resumed_model, settings=Settings(verify_completion=False), human_input=True)
    resumed = resumed_agent.run("Resume", workspace=work, checkpoint_path=checkpoint,
        resume={"run_id": paused.run_id, "request_id": paused.state["metadata"]["pending_input"]["id"], "text": "3", "files": ["sum.txt"]})
    assert resumed.status == "completed"
    assert sum(m.role == "tool" and m.tool_call_id == "calc" for m in resumed.state["messages"]) == 1


def test_question_before_actions_is_rejected_without_executing_them(tmp_path):
    model = Scripted([action(question("bad"), calculate()), action(question("good"))])
    result = create_agent(model, settings=Settings(verify_completion=False), human_input=True).run(
        "Ask before doing work", workspace=tmp_path / "work", checkpoint_path=tmp_path / "state.sqlite3")
    assert result.status == "needs_input"
    assert not (tmp_path / "work/sum.txt").exists()
    results = [json.loads(m.content) for m in result.state["messages"] if m.role == "tool"]
    assert [r["status"] for r in results] == ["error", "error", "ok"]


def test_failed_prerequisite_does_not_silently_pause_with_stale_question(tmp_path):
    model = Scripted([action(calculate(code="raise ValueError('failed prerequisite')"), question("stale")), action(question("fresh"))])
    result = create_agent(model, settings=Settings(verify_completion=False), human_input=True).run(
        "Prepare then ask", workspace=tmp_path / "work", checkpoint_path=tmp_path / "state.sqlite3")
    results = [json.loads(m.content) for m in result.state["messages"] if m.role == "tool"]
    assert result.status == "needs_input" and result.model_turns == 2
    assert results[1]["error"]["code"] == "prior_action_failed"
    assert results[2]["call_id"] == "fresh" and results[2]["status"] == "ok"


def test_review_id_error_retries_only_review_and_reuses_valid_draft(tmp_path):
    model = Scripted([
        action(calculate()), ModelResponse("The result is 5 in sum.txt."),
        assessment("review-bad", evidence=("made-up-id",)), assessment("review-good"), assessment("answer-good"),
    ])
    result = create_agent(model).run("Use Python to save and verify 2+3 in sum.txt.", workspace=tmp_path)
    assert result.status == "completed" and result.model_turns == 5
    assert [request.tools[0].name for request in model.requests[2:]] == ["assess_completion"] * 3
    assert "assessment_protocol_feedback" in json.loads(model.requests[3].messages[-1].content)
    assert not any(request.tool_choice == "none" for request in model.requests)
    assert sum(m.role == "tool" for m in result.state["messages"]) == 1
    assert result.state["metadata"]["answer_source"] == "execution_candidate"


def test_answer_audit_still_rejects_unfinished_wording_and_composes_correction(tmp_path):
    model = Scripted([
        action(calculate()), ModelResponse("Next I will inspect the output."),
        assessment("execution"), assessment("bad-answer", verdict="revise_answer"),
        ModelResponse("The result is 5 in sum.txt."), assessment("fixed-answer"),
    ])
    result = create_agent(model).run("Use Python to save and verify 2+3 in sum.txt.", workspace=tmp_path)
    assert result.status == "completed" and "result is 5" in result.answer
    assert model.requests[4].tool_choice == "none" and not model.requests[4].tools
    assert sum(m.role == "tool" for m in result.state["messages"]) == 1


def test_deterministic_completion_check_is_not_skipped_for_reused_candidate(tmp_path):
    checked = []
    def check(state):
        checked.append(state["answer"])
        return [CompletionIssue("The answer must report the observed 5, not 6.")] if "result is 6" in state["answer"] else []
    model = Scripted([
        action(calculate()), ModelResponse("The result is 6."), assessment("execution"),
        ModelResponse("The result is 5 in sum.txt."), assessment("answer"),
    ])
    result = create_agent(model, completion_checks=(check,)).run("Save and verify 2+3 in sum.txt.", workspace=tmp_path)
    assert result.status == "completed" and "result is 5" in result.answer
    assert "The result is 6." in checked
    assert model.requests[3].tool_choice == "none"


def evidence_state():
    messages = [Message("user", "Calculate using the coefficient I will supply."),
                Message("assistant", "", (ToolCall("real", "read_file", {"path": "result.txt"}),)),
                ToolResult("real", "read_file", "ok", data={"content": "15"}).message()]
    state = {"task": messages[0].content, "messages": messages, "artifacts": [], "answer": "15",
             "exposed_tool_names": ["read_file"], "metadata": {"optimize_round_trips": True,
             "human_responses": [{"request_id": "question", "text": "The coefficient is 3."}]}}
    context = SimpleNamespace(build=lambda s: ModelRequest(tuple(s["messages"]), ()))
    return state, context


def test_review_schema_constrains_ids_to_actual_successful_evidence():
    state, context = evidence_state()
    request = review_request(state, context, Settings(), phase="execution")
    assert request.tools[0].input_schema["properties"]["evidence_call_ids"]["items"]["enum"] == ["real"]
    with pytest.raises(ModelProtocolError, match="unknown or unsuccessful"):
        parse_review(assessment("bad", evidence=("invented",)), allowed_evidence_ids=["real"])


@pytest.mark.parametrize("phase", ["execution", "answer", "compose"])
def test_human_supplement_is_preserved_in_every_completion_phase(phase):
    state, context = evidence_state()
    request = (final_answer_request(state, context, Settings()) if phase == "compose" else
               review_request(state, context, Settings(), phase=phase))
    payload = json.loads(request.messages[-1].content)
    assert payload["user_supplements"] == [{"request_id": "question", "text": "The coefficient is 3."}]
    assert "not assumptions" in request.messages[0].content

"""Synthetic recovery tests: controls are not research data or execution proof."""
from copy import deepcopy
from threading import Event

import pytest

from geological_agent.agent.human_input import apply_human_reply
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import Message, ModelEvent, ModelResponse, ToolCall
from geological_agent.settings import Settings
from test_knowledge_semantics import GOOD, assessment, response, state as source_state


def control_state(phase="knowledge_semantics"):
    return {"messages": [Message("user", "Translate the detector name.")],
            "metadata": {"knowledge": source_state()["metadata"]["knowledge"],
                         "pending_input": {"id": "pending", "reason_type": "model_protocol",
                                           "recovery_origin": "runtime", "recovery_phase": phase},
                         "protocol_recovery": {"phase": phase, "candidate": GOOD,
                                               "execution_ready": True, "final_answer_composed": True,
                                               "tool_choice": "required", "failures": 2},
                         "semantic_review_progress": {"checks": {"b1": {"verdict": "supported"}},
                                                      "failure_signatures": ["prior failure"]}}}


def test_control_reply_preserves_messages_sources_progress_and_input():
    original = control_state()
    before = deepcopy(original)
    reply = {"request_id": "pending", "text": "Retry assessment", "files": ["existing.csv"]}
    update = apply_human_reply(original, reply)
    assert original == before
    assert update["messages"] == original["messages"]
    assert update["metadata"]["knowledge"] == original["metadata"]["knowledge"]
    assert "human_responses" not in update["metadata"]
    assert update["metadata"]["runtime_control_responses"] == [{**reply, "phase": "knowledge_semantics"}]
    assert update["metadata"]["semantic_review_progress"]["checks"] == original["metadata"]["semantic_review_progress"]["checks"]
    assert update["metadata"]["semantic_review_progress"]["failure_signatures"] == []
    assert update["metadata"]["resume_review_candidate"] == original["metadata"]["protocol_recovery"]


@pytest.mark.parametrize("phase", ["review:execution", "review:answer", "review:combined", "knowledge_semantics"])
def test_control_keeps_exact_review_phase(phase):
    update = apply_human_reply(control_state(phase), {"request_id": "pending", "text": "Retry"})
    assert update["metadata"]["runtime_control_resume"] == phase
    assert update["metadata"]["resume_review_candidate"]["phase"] == phase


@pytest.mark.parametrize("phase", ["intent", "execution"])
def test_protocol_recovery_preserves_phase_without_inserting_user_message(phase):
    original = control_state(phase)
    original["metadata"]["objective_checked"] = True
    update = apply_human_reply(original, {"request_id": "pending", "text": "Retry"})
    assert update["messages"] == original["messages"]
    if phase == "intent":
        assert update["metadata"]["protocol_recovery"]["failures"] == 0
        assert "objective_checked" not in update["metadata"]
    else:
        assert update["metadata"]["next_tool_choice"] == "required"
        assert update["metadata"]["native_tool_recovery_pending"] is True


@pytest.mark.parametrize("corruption", ["wrong_id", "wrong_phase", "missing_recovery", "empty_text"])
def test_invalid_control_cannot_consume_saved_state(corruption):
    original = control_state()
    reply = {"request_id": "pending", "text": "Retry"}
    if corruption == "wrong_id":
        reply["request_id"] = "stale"
    elif corruption == "wrong_phase":
        original["metadata"]["protocol_recovery"]["phase"] = "intent"
    elif corruption == "missing_recovery":
        original["metadata"].pop("protocol_recovery")
    else:
        reply["text"] = " "
    before = deepcopy(original)
    with pytest.raises(ValueError):
        apply_human_reply(original, reply)
    assert original == before


def test_retry_wording_does_not_turn_real_clarification_into_control():
    original = control_state()
    original["metadata"]["pending_input"].pop("recovery_origin")
    reply = {"request_id": "pending", "text": "Retry assessment", "files": ["supplement.csv"]}
    update = apply_human_reply(original, reply)
    assert update["metadata"]["human_responses"] == [reply]
    assert update["messages"][-1].content.startswith("Retry assessment\n")
    assert "supplement.csv" in update["messages"][-1].content
    assert "runtime_control_resume" not in update["metadata"]


def configure(monkeypatch, combined=False):
    for key in ("GEOTOOL_INTENT_REVIEW", "GEOTOOL_COMBINED_COMPLETION_REVIEW",
                "GEOTOOL_OPTIMIZE_ROUND_TRIPS", "GEOTOOL_COMPACT_REVIEW",
                "GEOTOOL_REVIEW_REFERENCE_SETS", "GEOTOOL_KNOWLEDGE", "GEOTOOL_REQUIREMENT_COVERAGE"):
        monkeypatch.delenv(key, raising=False)
    if combined:
        monkeypatch.setenv("GEOTOOL_COMBINED_COMPLETION_REVIEW", "1")


class Retriever:
    def __init__(self):
        self.queries = []

    def retrieve(self, query, limit):
        self.queries.append(query)
        return deepcopy(source_state()["metadata"]["knowledge"])


class ReviewModel:
    def __init__(self, broken=False):
        self.broken = broken
        self.requests = []

    def stream(self, request):
        yield ModelEvent("response", response=self.invoke(request))

    def invoke(self, request):
        self.requests.append(request)
        name = request.tools[0].name if request.tools else ""
        if name == "assess_knowledge_semantics":
            return ModelResponse(content="approved") if self.broken else response(assessment(request))
        if name == "assess_completion":
            return ModelResponse(tool_calls=(ToolCall("review", "assess_completion", {
                "verdict": "complete", "feedback": "", "required_outputs": [],
                "requires_python_execution": False, "evidence_call_ids": []}),), finish_reason="tool_calls")
        return ModelResponse(content=GOOD, finish_reason="stop")


def paused_review(tmp_path, monkeypatch, combined=False):
    configure(monkeypatch, combined)
    retriever = Retriever()
    model = ReviewModel(broken=True)
    workspace, checkpoint = tmp_path / "work", tmp_path / "checkpoint.sqlite3"
    runtime = create_agent(model, human_input=True, knowledge=retriever,
                           settings=Settings(knowledge_enabled=True, max_model_turns=32))
    paused = runtime.run("Translate the detector name in the supplied note.",
                         workspace=workspace, checkpoint_path=checkpoint)
    assert paused.status == "needs_input", paused.reason
    assert paused.state["metadata"]["pending_input"]["recovery_phase"] == "knowledge_semantics"
    assert len(retriever.queries) == 1
    return paused, workspace, checkpoint


def resume_review(paused, workspace, checkpoint, *, budget=32, cancel=None):
    model, retriever = ReviewModel(), Retriever()
    runtime = create_agent(model, human_input=True, knowledge=retriever,
                           settings=Settings(knowledge_enabled=True, max_model_turns=budget))
    result = runtime.run("Retry assessment", workspace=workspace, checkpoint_path=checkpoint,
        cancel_event=cancel, resume={"run_id": paused.run_id,
            "request_id": paused.state["metadata"]["pending_input"]["id"],
            "text": "Retry assessment", "files": ["existing.csv"]})
    return result, model, retriever


@pytest.mark.parametrize("combined", [False, True])
def test_durable_semantic_resume_calls_only_pending_audit(tmp_path, monkeypatch, combined):
    paused, workspace, checkpoint = paused_review(tmp_path, monkeypatch, combined)
    result, model, retriever = resume_review(paused, workspace, checkpoint)
    assert result.status == "completed", result.reason
    assert result.answer == GOOD
    assert retriever.queries == []
    assert [r.tools[0].name for r in model.requests] == ["assess_knowledge_semantics"]
    assert result.state["model_turns"] == paused.state["model_turns"] + 1
    assert result.state["metadata"]["knowledge"] == paused.state["metadata"]["knowledge"]
    assert result.state["metadata"].get("human_responses", ()) == paused.state["metadata"].get("human_responses", ())
    assert all("Retry assessment" not in m.content for r in model.requests for m in r.messages)
    assert all(m.role != "tool" for m in result.state["messages"])
    assert result.state["metadata"]["knowledge_semantic_reviews"][-1]["passed"]
    assert "runtime_control_resume" not in result.state["metadata"]
    assert "resume_review_phase" not in result.state["metadata"]


@pytest.mark.parametrize("stop", ["budget", "cancel"])
def test_recovery_still_honors_budget_and_cancellation(tmp_path, monkeypatch, stop):
    paused, workspace, checkpoint = paused_review(tmp_path, monkeypatch)
    cancel = Event()
    if stop == "cancel":
        cancel.set()
    result, model, retriever = resume_review(paused, workspace, checkpoint,
        budget=paused.state["model_turns"] if stop == "budget" else 32, cancel=cancel)
    assert result.status == ("stopped" if stop == "cancel" else "budget_exhausted")
    assert not model.requests and not retriever.queries
    assert result.state["metadata"]["knowledge"] == paused.state["metadata"]["knowledge"]


def test_real_clarification_still_refreshes_retrieval_and_keeps_tool_pair(tmp_path, monkeypatch):
    configure(monkeypatch)
    class ClarificationModel:
        def invoke(self, request):
            return ModelResponse(tool_calls=(ToolCall("question-call", "request_user_input", {
                "question": "Which detector?", "reason": "The detector was not specified.",
                "missing": ["detector"], "options": []}),), finish_reason="tool_calls")
    retriever = Retriever()
    workspace, checkpoint = tmp_path / "work", tmp_path / "checkpoint.sqlite3"
    settings = Settings(knowledge_enabled=True, verify_completion=False)
    paused = create_agent(ClarificationModel(), human_input=True, knowledge=retriever, settings=settings).run(
        "Describe the detector.", workspace=workspace, checkpoint_path=checkpoint)
    assert paused.status == "needs_input", paused.reason
    model = ReviewModel()
    result = create_agent(model, human_input=True, knowledge=retriever, settings=settings).run(
        "hydrogen sulfide", workspace=workspace, checkpoint_path=checkpoint,
        resume={"run_id": paused.run_id, "request_id": paused.state["metadata"]["pending_input"]["id"],
                "text": "hydrogen sulfide", "files": ["supplement.txt"]})
    assert result.status == "completed", result.reason
    assert len(retriever.queries) == 2
    assert retriever.queries[-1].endswith("User clarification:\nhydrogen sulfide")
    assert any(m.role == "user" and m.content.startswith("hydrogen sulfide\n") for m in model.requests[0].messages)
    assert any(m.role == "tool" and m.tool_call_id == "question-call" for m in result.state["messages"])

"""Bounded correction with synthetic model responses, never relaxed evidence."""
from copy import deepcopy
import json
from threading import Event
from types import SimpleNamespace

import pytest

from geological_agent.agent.completion import CompletionIssue, FINAL_ANSWER_SYSTEM
from geological_agent.agent.semantic_recovery import review_sources
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import ModelResponse
from geological_agent.llm import ModelProtocolError
from geological_agent.settings import Settings
from test_review_recovery import Model, call, review
from test_semantic_term_feedback import make_state, native_review, SOURCE, CID


@pytest.fixture(autouse=True)
def isolated_review_mode(monkeypatch):
    # Each test opts into any optimization whose request shape it simulates.
    for name in ("GEOTOOL_OPTIMIZE_ROUND_TRIPS", "GEOTOOL_COMBINED_COMPLETION_REVIEW",
                 "GEOTOOL_REQUIREMENT_COVERAGE", "GEOTOOL_INTENT_REVIEW",
                 "GEOTOOL_COMPACT_REVIEW", "GEOTOOL_COMPACT_DISCOVERY",
                 "GEOTOOL_REVIEW_REFERENCE_SETS"):
        monkeypatch.delenv(name, raising=False)


def invalid(message):
    def fail(request):
        raise ModelProtocolError(message)
    return fail


@pytest.mark.parametrize("phase", ["execution", "answer", "combined"])
def test_different_review_errors_have_a_stage_bound(tmp_path, monkeypatch, phase):
    monkeypatch.setenv("GEOTOOL_COMBINED_COMPLETION_REVIEW", "1" if phase == "combined" else "0")
    responses = [ModelResponse("A useful draft.")]
    if phase == "answer":
        responses += [review(), ModelResponse("Hello.")]
    responses += [invalid("Malformed review variant " + str(i)) for i in range(3)]
    model, published = Model(*responses), []
    result = create_agent(model, settings=Settings(max_model_turns=None)).run(
        "Say hello", workspace=tmp_path, on_text=published.append)
    assert result.status == "incomplete" and not result.answer and not published
    assert len(model.requests) == len(responses) == result.model_turns
    assert len(result.state["metadata"]["review_protocol_errors"]) == 3
    assert result.state["metadata"]["protocol_recovery"]["phase"] == "review:" + phase
    assert not any(m.role == "tool" for m in result.state["messages"])


def test_corrected_review_can_pass_on_last_allowed_attempt(tmp_path):
    model = Model(ModelResponse("Draft"), invalid("first"), invalid("second"),
                  review(), ModelResponse("Hello"), review())
    result = create_agent(model, settings=Settings(max_model_turns=None)).run("Say hello", workspace=tmp_path)
    assert result.status == "completed" and result.answer == "Hello"
    assert len(result.state["metadata"]["review_protocol_errors"]) == 2


def semantic_run(responder):
    current = make_state()
    original = deepcopy(current)
    requests, events = [], []
    class Reviewer:
        def invoke(self, request):
            requests.append(request)
            return responder(request, len(requests))
    result, issues = review_sources(current, settings=Settings(max_model_turns=None),
        model=Reviewer(), cancel=Event(), record=lambda *args: None,
        trace=SimpleNamespace(emit=lambda name, **fields: events.append((name, fields))),
        activity=lambda *args, **kwargs: None,
        pause=lambda state, phase, error: {**state, "status": "needs_input", "answer": "", "last_error": error})
    assert result["metadata"]["knowledge"] == original["metadata"]["knowledge"]
    assert result["messages"] == original["messages"]
    return result, issues, requests, events


def test_semantic_errors_cannot_evade_bound_by_changing_text():
    def respond(request, attempt):
        raise ModelProtocolError("Malformed semantic review variant " + str(attempt))
    result, issues, requests, events = semantic_run(respond)
    assert result["status"] == "needs_input" and not result["answer"]
    assert len(requests) == result["model_turns"] == 3
    assert not issues and not result["metadata"].get("knowledge_semantic_reviews")
    assert result["metadata"]["semantic_pending_draft"]["answer"]
    assert any(fields.get("action") == "pause_no_progress" for _, fields in events)


def test_partial_verified_blocks_reset_only_stagnant_attempts(monkeypatch):
    from geological_agent.agent import semantic_recovery as recovery
    current = make_state()
    current["answer"] = "\n\n".join(
        "Paragraph " + str(i) + ": structured knowledge [" + CID + "]." for i in range(1, 4))
    original = deepcopy(current)
    requests = []
    class Reviewer:
        def invoke(self, request):
            requests.append(request)
            attempt = len(requests)
            if attempt in (2, 3, 5, 6):
                raise ModelProtocolError("Temporary invalid record " + str(attempt))
            response = native_review()
            check = response.tool_calls[0].arguments["checks"]["b1"]
            check["source_quotes"].append({"source_id": CID, "field": "text", "quote": SOURCE})
            key = {1: "b1", 4: "b2", 7: "b3"}[attempt]
            response.tool_calls[0].arguments["checks"] = {key: check}
            return response
    result, issues = review_sources(current, settings=Settings(max_model_turns=None),
        model=Reviewer(), cancel=Event(), record=lambda *args: None,
        trace=SimpleNamespace(emit=lambda *args, **kwargs: None), activity=lambda *args, **kwargs: None,
        pause=lambda *args: pytest.fail("Verified new blocks must permit incremental progress"))
    assert len(requests) == 7 and not issues
    assert result["metadata"]["knowledge_semantic_reviews"][-1]["passed"]
    assert set(result["metadata"]["knowledge_semantic_reviews"][-1]["checks"]) == {"b1", "b2", "b3"}
    assert result["metadata"]["knowledge"] == original["metadata"]["knowledge"]
    assert result["answer"] == original["answer"]


def test_answer_repair_pauses_and_resumes_composition_without_reexecuting_tool(tmp_path):
    published = []
    def check(state):
        return [CompletionIssue("Report the actually observed number 42.")] if "wrong" in state["answer"] else []
    good = review(outputs=("value.txt",), evidence=("write-once",))
    model = Model(call("write_file", {"path": "value.txt", "content": "42"}, "write-once"),
                  ModelResponse("Work completed."), good,
                  ModelResponse("wrong first"), ModelResponse("wrong second"),
                  call("format_final_answer", {"lines": ["wrong third"]}, "format-rejected"))
    settings = Settings(max_model_turns=None)
    checkpoint = tmp_path / "checkpoint.sqlite3"
    paused = create_agent(model, settings=settings, completion_checks=(check,)).run(
        "Create value.txt containing 42 and report its number.", workspace=tmp_path,
        checkpoint_path=checkpoint, on_text=published.append)
    assert paused.status == "needs_input" and not published
    assert len(model.requests) == 6
    assert (tmp_path / "value.txt").read_text() == "42"
    assert sum(m.role == "tool" for m in paused.state["messages"]) == 1
    meta = paused.state["metadata"]
    assert meta["protocol_recovery"]["phase"] == "review:answer_revision"
    assert meta["protocol_recovery"]["candidate"] == "wrong third"
    assert len(meta["rejected_answers"]) == 3
    retry = Model(call("format_final_answer", {"lines": ["Saved value.txt containing 42."]}, "format-corrected"), good)
    resumed = create_agent(retry, settings=settings, completion_checks=(check,)).run(
        "Create value.txt containing 42 and report its number.", workspace=tmp_path,
        checkpoint_path=checkpoint,
        resume={"run_id": paused.run_id, "request_id": meta["pending_input"]["id"], "text": "Retry assessment", "files": []},
        on_text=published.append)
    assert resumed.status == "completed", resumed.reason
    assert len(retry.requests) == 2 and retry.requests[0].tool_choice == "required"
    assert [tool.name for tool in retry.requests[0].tools] == ["format_final_answer"]
    expected_system = FINAL_ANSWER_SYSTEM.replace(
        "No tools are available in this answer-writing stage.",
        "Only the internal format_final_answer function is available in this answer-writing stage.")
    assert retry.requests[0].messages[0].content.startswith(expected_system)
    payload = json.loads(retry.requests[0].messages[1].content)
    assert payload["repair_strategy"] == "native_line_array"
    assert payload["rejected_draft"]["text"] == "wrong third"
    assert [item["call"]["id"] for item in payload["observed_actions"]] == ["write-once"]
    assert sum(m.role == "tool" for m in resumed.state["messages"]) == 1
    assert published == ["Saved value.txt containing 42."]
    assert (tmp_path / "value.txt").read_text() == "42"

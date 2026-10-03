import json
from threading import Event

import pytest

from geological_agent.agent.completion import AVAILABILITY_REVIEW_GUIDANCE, EXECUTION_REVIEW_SYSTEM, FINAL_ANSWER_SYSTEM, REVIEW_SYSTEM
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import ModelEvent, ModelResponse, ToolCall
from geological_agent.llm import ModelProtocolError
from geological_agent.settings import Settings
from geological_agent.tracing import JsonlTrace


def call(name, arguments, identity="assessment"):
    return ModelResponse(tool_calls=(ToolCall(identity, name, arguments),), finish_reason="tool_calls")


def review(verdict="complete", outputs=(), evidence=()):
    return call("assess_completion", {"verdict": verdict, "feedback": "Observed work covers the task",
        "required_outputs": list(outputs), "requires_python_execution": False, "evidence_call_ids": list(evidence)})


class Model:
    def __init__(self, *responses):
        self.responses, self.requests = iter(responses), []

    def invoke(self, request):
        self.requests.append(request)
        response = next(self.responses)
        return response(request) if callable(response) else response

    def stream(self, request):
        response = self.invoke(request)
        for character in response.content:
            yield ModelEvent("text_delta", character)
        yield ModelEvent("response", response=response)


def invalid_assessments():
    complete, unfinished = review(), review("continue")
    return [
        pytest.param(ModelResponse(tool_calls=complete.tool_calls * 2, finish_reason="tool_calls"), id="duplicate"),
        pytest.param(ModelResponse(tool_calls=complete.tool_calls + unfinished.tool_calls, finish_reason="tool_calls"), id="conflicting"),
        pytest.param(ModelResponse(""), id="empty"),
        pytest.param(ModelResponse('{"verdict":"complete"}'), id="plain-json"),
        pytest.param(ModelResponse(tool_calls=complete.tool_calls, finish_reason="length"), id="truncated"),
        pytest.param(call("write_file", {"path": "forbidden.txt", "content": "INVALID_ONLY"}), id="workspace-call"),
        pytest.param(call("assess_completion", "{"), id="invalid-json"),
        pytest.param(call("assess_completion", {"verdict": "complete"}), id="missing-fields"),
        pytest.param(call("assess_completion", {**complete.tool_calls[0].arguments, "requires_python_execution": "false"}), id="wrong-type"),
    ]


@pytest.mark.parametrize("phase", ["execution", "answer"])
@pytest.mark.parametrize("invalid", invalid_assessments())
def test_review_retries_same_evidence_without_rerunning_tools(tmp_path, phase, invalid):
    draft, final = "Useful working draft: result.txt contains 42.", "Saved result.txt containing 42."
    good_review = review(outputs=("result.txt",), evidence=("w1",))
    responses = [call("write_file", {"path": "result.txt", "content": "42"}, "w1"), ModelResponse(draft)]
    if phase == "execution":
        responses += [invalid, good_review, ModelResponse(final), good_review]
        retry_index, system, key = 3, EXECUTION_REVIEW_SYSTEM, "working_draft"
    else:
        responses += [good_review, ModelResponse(final), invalid, good_review]
        retry_index, system, key = 5, REVIEW_SYSTEM, "candidate_answer"
    model, published, events = Model(*responses), [], []
    trace = JsonlTrace(tmp_path / "trace.jsonl")
    result = create_agent(model, trace_factory=lambda run_id, workspace: trace).run(
        "Create result.txt containing 42", workspace=tmp_path, on_text=published.append, on_event=events.append)
    assert result.status == "completed" and result.answer == final and result.reason is None
    assert published == [final]
    assert result.model_turns == len(model.requests) == len(result.state["metadata"]["usage"]) == 6
    assert (tmp_path / "result.txt").read_text() == "42" and not (tmp_path / "forbidden.txt").exists()
    assert len([message for message in result.state["messages"] if message.role == "tool"]) == 1
    assert any(message.content == draft for message in result.state["messages"])
    assert not any("INVALID_ONLY" in message.content for message in result.state["messages"])
    request = model.requests[retry_index]
    assert request.messages[0].content == system + AVAILABILITY_REVIEW_GUIDANCE
    assert request.tool_choice == "required" and [tool.name for tool in request.tools] == ["assess_completion"]
    payload = json.loads(request.messages[1].content)
    previous = json.loads(model.requests[retry_index - 1].messages[1].content)
    assert payload["assessment_phase"] == phase and payload["assessment_protocol_feedback"]
    assert payload[key] == (draft if phase == "execution" else final)
    assert payload["observed_actions"] == previous["observed_actions"]
    assert len(result.state["metadata"]["execution_reviews"]) == len(result.state["metadata"]["completion_reviews"]) == 1
    assert not result.state["metadata"].get("rejected_answers")
    errors = result.state["metadata"]["review_protocol_errors"]
    assert len(errors) == 1 and errors[0]["phase"] == phase
    assert any(event["kind"] == "completion_review_retry" and event["phase"] == phase for event in events)
    records = [json.loads(line) for line in trace.path.read_text().splitlines()]
    assert sum(row["event"] == "completion_review_protocol_error" for row in records) == 1


@pytest.mark.parametrize("phase", ["execution", "answer"])
def test_invalid_reviews_use_existing_budget_and_never_publish(tmp_path, phase):
    responses = [ModelResponse("Useful draft")]
    if phase == "answer":
        responses += [review(), ModelResponse("Final candidate")]
    responses += [ModelResponse(""), ModelResponse("")]
    maximum = len(responses)
    model, published = Model(*responses), []
    result = create_agent(model, settings=Settings(max_model_turns=maximum)).run(
        "Say hello", workspace=tmp_path, on_text=published.append)
    assert result.status == "budget_exhausted" and not result.answer and not published
    assert result.model_turns == len(model.requests) == len(result.state["metadata"]["usage"]) == maximum
    assert len(result.state["metadata"]["review_protocol_errors"]) == 2
    assert any(message.content == "Useful draft" for message in result.state["messages"])
    assert not result.state["metadata"].get("completion_reviews")


@pytest.mark.parametrize("phase", ["execution", "answer"])
def test_cancellation_during_invalid_review_does_not_retry_or_publish(tmp_path, phase):
    cancel = Event()
    def interrupted(request):
        cancel.set()
        return ModelResponse("")
    responses = [ModelResponse("Useful draft")]
    if phase == "answer":
        responses += [review(), ModelResponse("Final candidate")]
    responses.append(interrupted)
    model, published = Model(*responses), []
    result = create_agent(model).run("Say hello", workspace=tmp_path, cancel_event=cancel, on_text=published.append)
    assert result.status == "stopped" and not result.answer and not published
    assert result.model_turns == len(model.requests) == len(responses)


def test_invalid_review_does_not_bypass_unfinished_work(tmp_path):
    conflicting = ModelResponse(tool_calls=review().tool_calls + review("continue").tool_calls, finish_reason="tool_calls")
    model = Model(ModelResponse("Useful draft: create result.txt with 42."), conflicting,
        review("continue", outputs=("result.txt",)),
        call("write_file", {"path": "result.txt", "content": "42"}, "w1"),
        ModelResponse("Created result.txt."), review(outputs=("result.txt",), evidence=("w1",)),
        ModelResponse("Created result.txt with 42."), review(outputs=("result.txt",), evidence=("w1",)))
    result = create_agent(model).run("Create result.txt with 42", workspace=tmp_path)
    assert result.status == "completed" and result.model_turns == 8
    assert model.requests[3].tool_choice == "required" and "write_file" in [tool.name for tool in model.requests[3].tools]
    repair_messages = [message for message in model.requests[3].messages
                       if message.content.startswith("Unaccepted working draft retained for correction")]
    assert len(repair_messages) == 1 and repair_messages[0].role == "user"
    assert json.loads(repair_messages[0].content.split("\n", 1)[1])["text"] == "Useful draft: create result.txt with 42."
    assert not any(message.role == "assistant" and message.content == "Useful draft: create result.txt with 42."
                   for message in model.requests[3].messages)
    assert len([request for request in model.requests if request.messages[0].content == FINAL_ANSWER_SYSTEM]) == 1
    assert len(result.state["metadata"]["execution_reviews"]) == 2


def test_review_retry_has_no_separate_hidden_attempt_limit(tmp_path):
    model = Model(ModelResponse("Draft"), *[ModelResponse("") for _ in range(6)], review(), ModelResponse("Hello"), review())
    result = create_agent(model, settings=Settings(max_model_turns=None)).run("Say hello", workspace=tmp_path)
    assert result.status == "completed" and result.model_turns == 10
    assert len(result.state["metadata"]["review_protocol_errors"]) == 6


def test_protocol_failure_from_model_client_retries_only_review(tmp_path):
    def invalid_native_response(request):
        raise ModelProtocolError("Malformed native response")
    model = Model(ModelResponse("Draft"), invalid_native_response, review(), ModelResponse("Hello"), review())
    result = create_agent(model).run("Say hello", workspace=tmp_path)
    assert result.status == "completed" and result.model_turns == 5
    assert model.requests[1].tools == model.requests[2].tools
    assert len(result.state["metadata"]["usage"]) == 4


def test_nonprotocol_failure_does_not_become_a_format_retry(tmp_path):
    def unavailable(request):
        raise RuntimeError("Model service unavailable")
    model = Model(ModelResponse("Draft"), unavailable)
    result = create_agent(model).run("Say hello", workspace=tmp_path)
    assert result.status == "failed" and result.model_turns == len(model.requests) == 2
    assert not result.answer and not result.state["metadata"].get("review_protocol_errors")

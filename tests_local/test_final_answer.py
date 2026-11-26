import json
from threading import Event

import pytest

from geological_agent.agent.completion import AVAILABILITY_REVIEW_GUIDANCE, EXECUTION_REVIEW_SYSTEM, FINAL_ANSWER_SYSTEM
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import ModelResponse, ToolCall
from geological_agent.settings import Settings


def call(name, args, identity):
    return ModelResponse(tool_calls=(ToolCall(identity, name, args),), finish_reason="tool_calls")


def review(outputs=(), evidence=(), verdict="complete", python=False):
    return call("assess_completion", {"verdict": verdict, "feedback": "Check against observed evidence",
        "required_outputs": list(outputs), "requires_python_execution": python,
        "evidence_call_ids": list(evidence)}, "assessment")


class Model:
    def __init__(self, *responses):
        self.responses, self.requests = iter(responses), []

    def invoke(self, request):
        self.requests.append(request)
        value = next(self.responses)
        return value(request) if callable(value) else value


def test_answer_is_composed_from_real_artifacts_then_reviewed(tmp_path):
    value = '{"total":12}'
    final = "The total is 12; the saved output is result.json."
    def compose(request):
        assert request.messages[0].content == FINAL_ANSWER_SYSTEM
        assert request.tool_choice == "none" and not request.tools
        payload = json.loads(request.messages[1].content)
        assert payload["observed_artifact_contents"]["result.json"]["content"] == value
        assert payload["observed_actions"][0]["result"]["call_id"] == "w1"
        assert "candidate_answer" not in payload
        assert "provisional_conversational_response" not in payload
        assert "Next I will read" not in request.messages[1].content
        return ModelResponse(final)
    model = Model(call("write_file", {"path": "result.json", "content": value}, "w1"),
        ModelResponse("Next I will read result.json."), review(("result.json",), ("w1",)),
        compose, review(("result.json",), ("w1",)))
    result = create_agent(model).run("Save result.json with total 12 and report it", workspace=tmp_path)
    assert result.status == "completed" and result.answer == final
    assert result.state["answer"] == final
    assert result.state["messages"][-1].role == "assistant"
    assert result.state["messages"][-1].content == final
    assert result.model_turns == len(model.requests) == len(result.state["metadata"]["usage"]) == 5
    assert model.requests[2].messages[0].content == EXECUTION_REVIEW_SYSTEM + AVAILABILITY_REVIEW_GUIDANCE
    assert json.loads(model.requests[-1].messages[1].content)["candidate_answer"] == final
    assert len([m for m in result.state["messages"] if m.role == "tool"]) == 1


def test_composed_bad_quote_is_corrected_without_repeating_work(tmp_path):
    good = 'result.json\n```json\n{"total":12}\n```'
    bad = 'result.json\n```json\n{"total":12000}\n```'
    model = Model(call("write_file", {"path": "result.json", "content": '{"total":12}'}, "w1"),
        ModelResponse("Created result.json."), review(("result.json",), ("w1",)),
        ModelResponse(bad), ModelResponse(good), review(("result.json",), ("w1",)))
    result = create_agent(model).run("Create result.json with total 12", workspace=tmp_path)
    assert result.status == "completed" and result.answer == good
    assert result.model_turns == 6
    assert model.requests[4].messages[0].content == FINAL_ANSWER_SYSTEM
    assert model.requests[4].tool_choice == "none" and not model.requests[4].tools
    assert len([m for m in result.state["messages"] if m.role == "tool"]) == 1


@pytest.mark.parametrize("invalid", [ModelResponse(""), ModelResponse("partial", finish_reason="length"),
    call("write_file", {"path": "forbidden.txt", "content": "x"}, "forbidden")])
def test_invalid_composition_recovers_natively_without_side_effects(tmp_path, invalid):
    model = Model(ModelResponse("Hello"), review(), invalid, ModelResponse("Hello"), review())
    result = create_agent(model).run("Say hello", workspace=tmp_path)
    assert result.status == "completed" and result.answer == "Hello"
    assert result.model_turns == 5
    assert not (tmp_path / "forbidden.txt").exists()
    assert model.requests[3].messages[0].content == FINAL_ANSWER_SYSTEM
    assert model.requests[3].tool_choice == "none" and not model.requests[3].tools


def test_budget_counts_composition_and_refuses_unreviewed_output(tmp_path):
    model = Model(ModelResponse("Draft"), review(), ModelResponse("Final"))
    result = create_agent(model, settings=Settings(max_model_turns=3)).run("Say hello", workspace=tmp_path)
    assert result.status == "budget_exhausted" and not result.answer
    assert result.model_turns == len(model.requests) == len(result.state["metadata"]["usage"]) == 3


def test_cancel_during_composition_prevents_review_and_publication(tmp_path):
    cancel = Event()
    def compose(request):
        cancel.set()
        return ModelResponse("Final")
    model = Model(ModelResponse("Draft"), review(), compose)
    result = create_agent(model).run("Say hello", workspace=tmp_path, cancel_event=cancel)
    assert result.status == "stopped" and not result.answer and result.model_turns == 3


def test_composer_cannot_bypass_execution_evidence(tmp_path):
    model = Model(ModelResponse("I will create missing.txt."), review(("missing.txt",)),
        call("write_file", {"path": "missing.txt", "content": "42"}, "w1"),
        ModelResponse("Created missing.txt."), review(("missing.txt",), ("w1",)),
        ModelResponse("Created missing.txt with 42."), review(("missing.txt",), ("w1",)))
    result = create_agent(model).run("Create missing.txt containing 42", workspace=tmp_path)
    assert result.status == "completed" and (tmp_path / "missing.txt").read_text() == "42"
    assert model.requests[2].tool_choice == "required"
    assert result.state["metadata"]["rejected_answers"]


def test_answer_only_reviewer_correction_does_not_restart_actor(tmp_path):
    model = Model(ModelResponse("Draft"), review(), ModelResponse("Incomplete wording"),
        review(verdict="revise_answer"), ModelResponse("Correct final wording"), review())
    result = create_agent(model).run("Give a concise greeting", workspace=tmp_path)
    assert result.status == "completed" and result.model_turns == 6
    assert model.requests[4].messages[0].content == FINAL_ANSWER_SYSTEM
    assert model.requests[4].tool_choice == "none" and not model.requests[4].tools
    assert len(result.state["metadata"]["execution_reviews"]) == 1


def test_failed_execution_keeps_useful_working_draft_before_composition(tmp_path):
    draft = "Use the standard library instead: write result.json containing value 42, then report it."
    def readiness(request):
        assert request.messages[0].content == EXECUTION_REVIEW_SYSTEM + AVAILABILITY_REVIEW_GUIDANCE
        payload = json.loads(request.messages[1].content)
        assert payload["working_draft"] == draft
        assert "execute_python" in payload["available_tool_names"]
        assert "candidate_answer" not in payload
        return review(("result.json",), verdict="continue", python=True)
    def compose(request):
        payload = json.loads(request.messages[1].content)
        assert request.messages[0].content == FINAL_ANSWER_SYSTEM
        assert json.loads(payload["observed_artifact_contents"]["result.json"]["content"]) == {"value": 42}
        assert any(row["result"]["call_id"] == "p-good" and row["result"]["status"] == "ok" for row in payload["observed_actions"])
        return ModelResponse("Created result.json containing value 42.")
    model = Model(call("execute_python", {"code": "raise ModuleNotFoundError('missing_optional_package')"}, "p-bad"),
        ModelResponse(draft), readiness,
        call("execute_python", {"code": "import json\nfrom pathlib import Path\nPath('result.json').write_text(json.dumps({'value':42}))\nprint(42)"}, "p-good"),
        ModelResponse("Created result.json."), review(("result.json",), ("p-good",), python=True), compose,
        review(("result.json",), ("p-good",), python=True))
    result = create_agent(model).run("Actually run Python to create result.json with value 42", workspace=tmp_path)
    assert result.status == "completed" and result.model_turns == 8
    assert model.requests[3].tool_choice == "required"
    repair_messages = [message for message in model.requests[3].messages
                       if message.content.startswith("Unaccepted working draft retained for correction")]
    assert len(repair_messages) == 1 and repair_messages[0].role == "user"
    assert json.loads(repair_messages[0].content.split("\n", 1)[1])["text"] == draft
    assert not any(message.role == "assistant" and message.content == draft
                   for message in model.requests[3].messages)
    assert len([request for request in model.requests if request.messages[0].content == FINAL_ANSWER_SYSTEM]) == 1
    assert len(result.state["metadata"]["execution_reviews"]) == 2
    assert len([message for message in result.state["messages"] if message.role == "tool"]) == 2


def test_rejected_delivery_does_not_pollute_next_execution_request(tmp_path):
    working = "result.json exists; preserve its observed value while finishing the report."
    rejected = "REJECTED_DELIVERY: replace the correct implementation with obsolete_package code."
    model = Model(call("write_file", {"path": "result.json", "content": '{"value":42}'}, "w1"),
        ModelResponse(working), review(("result.json",), ("w1",)), ModelResponse(rejected),
        review(("result.json", "report.md"), ("w1",), verdict="continue"),
        call("write_file", {"path": "report.md", "content": "Value: 42"}, "w2"),
        ModelResponse("Both files exist."), review(("result.json", "report.md"), ("w1", "w2")),
        ModelResponse("Created result.json and report.md with value 42."), review(("result.json", "report.md"), ("w1", "w2")))
    result = create_agent(model).run("Create result.json and report.md containing value 42", workspace=tmp_path)
    assert result.status == "completed" and result.model_turns == 10
    action_request = model.requests[5]
    assert action_request.tool_choice == "required"
    assert any(message.content == working for message in action_request.messages)
    assert not any("REJECTED_DELIVERY" in message.content for message in action_request.messages)
    assert not any("REJECTED_DELIVERY" in message.content for message in result.state["messages"])
    assert result.state["metadata"]["rejected_answers"][0]["answer"] == rejected
    assert not result.state["metadata"].get("execution_repair_draft")


def test_execution_assessment_consumes_budget_before_composition(tmp_path):
    model = Model(ModelResponse("Draft"), review())
    result = create_agent(model, settings=Settings(max_model_turns=2)).run("Say hello", workspace=tmp_path)
    assert result.status == "budget_exhausted" and not result.answer
    assert result.model_turns == len(model.requests) == len(result.state["metadata"]["usage"]) == 2
    assert all(request.messages[0].content != FINAL_ANSWER_SYSTEM for request in model.requests)

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from geological_agent.bootstrap import create_agent
from geological_agent.contracts import Message, ModelEvent, ModelResponse, ToolCall, ToolResult
from geological_agent.geology.validation import validate_energy_answer
from geological_agent.settings import Settings


_spec = importlib.util.spec_from_file_location("local_agent_oracles", Path(__file__).resolve().parents[1] / "scripts/local_agent_oracles.py")
_oracles = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_oracles)


def call(name, arguments, identity="c1"):
    return ModelResponse(tool_calls=(ToolCall(identity, name, arguments),), finish_reason="tool_calls")


def review(verdict="complete", outputs=(), python=False, evidence=(), feedback="Task covered by the supplied evidence"):
    return call("assess_completion", {"verdict": verdict, "feedback": feedback,
                "required_outputs": list(outputs), "requires_python_execution": python,
                "evidence_call_ids": list(evidence)}, "assessment")


class Model:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        return next(self.responses)

    def stream(self, request):
        response = self.invoke(request)
        for character in response.content:
            yield ModelEvent("text_delta", character)
        yield ModelEvent("response", response=response)


def energy_state(answer):
    return {"answer": answer, "messages": [Message("assistant", tool_calls=(ToolCall("e1", "GeoMagnitudeToEnergy", {"mw": 6.5}),)),
            ToolResult("e1", "GeoMagnitudeToEnergy", "ok", {"energy_j": 354813389233576.06, "tnt_tons": 84802.43528527152}).message()]}


@pytest.mark.parametrize("answer", [
    "354813389233576.06 joules", "354,813,389,233,576.06 J", "3.548e14 joules",
    "3.548 x 10^14 J", "3.548 \u00d7 10^{14} J", "3.5e14 J",
    r"\(3.548 \times 10^{14}\,\mathrm{J}\)",
    "\u91ca\u653e3.548e14\u7126\u8033", "354.8 TJ",
])
def test_correct_numeric_formats_and_rounding(answer):
    assert not validate_energy_answer(energy_state(answer))
    _oracles.assert_energy_answer(answer)


@pytest.mark.parametrize("answer", [
    "3.548e17 J", "3.548 x 10^17 joules", "3.548 \u00d7 10^{17} J",
    "3.548e17 joules; the tool also returned 354,813,389,233,576.06 joules.",
    "354.8 GJ", "-3.548e14 J",
])
def test_every_contradictory_number_is_rejected(answer):
    assert validate_energy_answer(energy_state(answer))
    with pytest.raises(AssertionError):
        _oracles.assert_energy_answer(answer)


def test_oracle_requires_an_explicit_value():
    with pytest.raises(AssertionError, match="No explicit"):
        _oracles.assert_energy_answer("The energy was computed.")


def test_report_oracle_accepts_rounding_not_wrong_scale():
    _oracles.assert_rounded_number("1.16", 4.4 / 380 * 100)
    with pytest.raises(AssertionError):
        _oracles.assert_rounded_number("1160.00", 4.4 / 380 * 100)


def test_default_gate_reviews_and_only_publishes_verified_final(tmp_path):
    model = Model(ModelResponse("Hello"), review(), ModelResponse("Hello"), review())
    published, events = [], []
    result = create_agent(model).run("Say hello", workspace=tmp_path, on_text=published.append, on_event=events.append)
    assert result.status == "completed" and result.model_turns == 4
    assert published == ["Hello"]
    assert model.requests[1].tools[0].name == "assess_completion"
    assert model.requests[2].tool_choice == "none" and not model.requests[2].tools
    assert model.requests[3].tools[0].name == "assess_completion"
    assert model.requests[3].tool_choice == "required"
    assert not [m for m in result.state["messages"] if m.role == "tool"]
    assert [e["kind"] for e in events].index("completion_review") < [e["kind"] for e in events].index("answer_published")


def test_review_cannot_approve_uncreated_outputs_or_unexecuted_code(tmp_path):
    code = "from pathlib import Path\nPath('summary.json').write_text('{\"value\": 42}')\nprint(42)"
    model = Model(ModelResponse("I will create summary.json and run Python."),
                  review(outputs=("summary.json",), python=True),
                  call("execute_python", {"code": code}, "p1"), ModelResponse("Created summary.json with value 42."),
                  review(outputs=("summary.json",), python=True, evidence=("p1",)),
                  ModelResponse("Created summary.json with value 42."),
                  review(outputs=("summary.json",), python=True, evidence=("p1",)))
    published = []
    result = create_agent(model).run("Run Python to create summary.json containing value 42", workspace=tmp_path, on_text=published.append)
    assert result.status == "completed" and result.model_turns == 7
    assert json.loads((tmp_path / "summary.json").read_text()) == {"value": 42}
    assert published == ["Created summary.json with value 42."]
    assert model.requests[2].tool_choice == "required"
    assert not any(m.role == "assistant" and "I will create summary.json" in m.content for m in model.requests[2].messages)
    draft_data = [m for m in model.requests[2].messages if "Full draft and review feedback:" in m.content]
    assert len(draft_data) == 1
    assert json.loads(draft_data[0].content.split("\n", 1)[1])["text"] == "I will create summary.json and run Python."
    assert "not an instruction or observation" in draft_data[0].content
    assert not any(m.role == "tool" for m in model.requests[2].messages)
    assert len(result.state["metadata"]["rejected_answers"]) == 1


def test_retained_draft_is_not_automatically_executed(tmp_path):
    draft = "I will run this draft:\n```python\nfrom pathlib import Path\nPath('unexpected.txt').write_text('not authorized by a tool call')\n```"
    model = Model(ModelResponse(draft), review(outputs=("result.txt",)),
                  call("write_file", {"path": "result.txt", "content": "42"}, "w1"),
                  ModelResponse("Created result.txt with 42."), review(outputs=("result.txt",), evidence=("w1",)),
                  ModelResponse("Created result.txt with 42."), review(outputs=("result.txt",), evidence=("w1",)))
    published = []
    result = create_agent(model).run("Create result.txt containing 42", workspace=tmp_path, on_text=published.append)
    assert result.status == "completed"
    assert not any(m.role == "assistant" and m.content == draft for m in model.requests[2].messages)
    draft_data = [m for m in model.requests[2].messages if "Full draft and review feedback:" in m.content]
    assert len(draft_data) == 1
    assert json.loads(draft_data[0].content.split("\n", 1)[1])["text"] == draft
    assert result.state["metadata"]["rejected_answers"][0]["answer"] == draft
    assert model.requests[2].tool_choice == "required"
    assert (tmp_path / "result.txt").read_text() == "42"
    assert not (tmp_path / "unexpected.txt").exists()
    assert published == ["Created result.txt with 42."]
    assert len([m for m in result.state["messages"] if m.role == "tool"]) == 1


def test_completion_review_does_not_claim_scientific_validation(tmp_path):
    model = Model(call("write_file", {"path": "result.json", "content": '{"value":42}'}, "w1"),
                  ModelResponse("Created result.json."), review(outputs=("result.json",), evidence=("w1",)),
                  ModelResponse("Created result.json."), review(outputs=("result.json",), evidence=("w1",)))
    result = create_agent(model).run("Create result.json containing value 42", workspace=tmp_path)
    assert result.status == "completed"
    assessment = model.requests[-1]
    system = assessment.messages[0].content
    assert "NOT that the calculation or scientific result is correct" in system
    assert "do not assume such validation happened" in system
    assert "File existence and numerical checks are independently enforced by the runtime" not in system
    payload = json.loads(assessment.messages[1].content)
    assert "verified_artifact_contents" not in payload
    assert payload["observed_artifact_contents"]["result.json"]["content"] == '{"value":42}'
    assert "not certification" in payload["artifact_checks_scope"]


def test_reviewer_routes_unfinished_prose_back_to_actions(tmp_path):
    model = Model(ModelResponse("Let me calculate this in Python."),
                  review("continue", python=True, feedback="No program execution occurred"),
                  call("execute_python", {"code": "print(6 * 7)"}, "p1"),
                  ModelResponse("The result is 42."), review(python=True, evidence=("p1",)),
                  ModelResponse("The result is 42."), review(python=True, evidence=("p1",)))
    result = create_agent(model).run("Actually calculate 6*7 using Python", workspace=tmp_path)
    assert result.status == "completed" and result.answer == "The result is 42."
    assert model.requests[2].tool_choice == "required"
    assert len(result.state["metadata"]["usage"]) == 7


def test_numeric_rejection_does_not_repeat_tool_or_publish_bad_answer(tmp_path):
    bad = "3.548 x 10^17 joules; also 354813389233576.06 joules."
    good = "Estimated energy is 354813389233576.06 joules, an empirical estimate."
    model = Model(call("GeoMagnitudeToEnergy", {"mw": 6.5}, "e1"), ModelResponse("Energy calculated."),
                  review(evidence=("e1",)), ModelResponse(bad), ModelResponse(good), review(evidence=("e1",)))
    published = []
    result = create_agent(model).run("Estimate Mw 6.5 energy", workspace=tmp_path, skill_id="earthquake_energy", on_text=published.append)
    assert result.status == "completed" and result.model_turns == 6
    assert published == [good] and model.requests[4].tool_choice == "none"
    assert not any(m.content == bad for m in model.requests[4].messages)
    assert len([m for m in result.state["messages"] if m.role == "tool"]) == 1
    _oracles.assert_energy_answer(result.answer)


def test_existing_unedited_input_does_not_prove_repair(tmp_path):
    original = "def f():\n    return 300\n"
    repaired = "def f():\n    return 3\n"
    (tmp_path / "calc.py").write_text(original)
    model = Model(call("read_file", {"path": "calc.py"}, "r1"), ModelResponse("Here is the repaired code."),
                  review(outputs=("calc.py",), python=True, evidence=("r1",)),
                  call("write_file", {"path": "calc.py", "content": repaired, "expected_sha256": hashlib.sha256((tmp_path / "calc.py").read_bytes()).hexdigest()}, "w1"),
                  call("execute_python", {"code": "import runpy\nassert runpy.run_path('calc.py')['f']() == 3\nprint('verified')"}, "p1"),
                  ModelResponse("calc.py was repaired and tested."), review(outputs=("calc.py",), python=True, evidence=("w1", "p1")),
                  ModelResponse("calc.py was repaired and tested."), review(outputs=("calc.py",), python=True, evidence=("w1", "p1")))
    result = create_agent(model).run("Repair calc.py so f() returns 3 and actually run a check", workspace=tmp_path)
    assert result.status == "completed" and (tmp_path / "calc.py").read_text() == repaired
    assert model.requests[3].tool_choice == "required"


def test_invalid_generated_python_returns_to_repair(tmp_path):
    bad = "import os import sys"
    good = "print(42)\n"
    model = Model(call("write_file", {"path": "calc.py", "content": bad}, "w1"), ModelResponse("Created calc.py."),
                  call("write_file", {"path": "calc.py", "content": good, "expected_sha256": hashlib.sha256(bad.encode()).hexdigest()}, "w2"),
                  ModelResponse("Created valid calc.py."), review(outputs=("calc.py",), evidence=("w2",)),
                  ModelResponse("Created valid calc.py."), review(outputs=("calc.py",), evidence=("w2",)))
    result = create_agent(model).run("Create calc.py printing 42", workspace=tmp_path)
    assert result.status == "completed" and "SyntaxError" in result.state["metadata"]["rejected_answers"][0]["feedback"]
    assert model.requests[2].tool_choice == "required"


def test_assessment_does_not_execute_a_workspace_tool(tmp_path):
    model = Model(ModelResponse("Done"), review(), ModelResponse("Done"), call("write_file", {"path": "should-not-exist.txt", "content": "x"}))
    published = []
    result = create_agent(model, settings=Settings(max_model_turns=4)).run("Discuss a task", workspace=tmp_path, on_text=published.append)
    assert result.status == "budget_exhausted" and not published
    assert not (tmp_path / "should-not-exist.txt").exists()


def test_budget_includes_review_and_does_not_publish_unchecked_text(tmp_path):
    model = Model(ModelResponse("Hello"))
    published = []
    result = create_agent(model, settings=Settings(max_model_turns=1)).run("Say hello", workspace=tmp_path, on_text=published.append)
    assert result.status == "budget_exhausted" and not result.answer and not published


def test_clarification_is_not_successful_completion(tmp_path):
    question = "Which coordinate reference system does your data use?"
    model = Model(ModelResponse(question), review("clarify", feedback="Input CRS is missing"))
    result = create_agent(model).run("Reproject my unspecified data", workspace=tmp_path)
    assert result.status == "needs_input" and result.answer == question


def test_invalid_assessment_fails_closed(tmp_path):
    model = Model(ModelResponse("Done"), review(), ModelResponse("Done"), call("assess_completion", {"verdict": "complete"}))
    result = create_agent(model, settings=Settings(max_model_turns=4)).run("An action", workspace=tmp_path)
    assert result.status == "budget_exhausted" and not result.answer
    assert len(result.state["metadata"]["review_protocol_errors"]) == 1

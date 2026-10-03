"""One assessment must preserve actual execution, corrective routing and budgets."""
import json
from types import SimpleNamespace

import pytest

from geological_agent.agent.completion import CompletionIssue, completion_evidence, final_answer_request
from geological_agent.agent.context import ContextOverflow
from geological_agent.agent.review_policy import combined_review_request
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import Message, ModelResponse, ToolCall, ToolResult
from geological_agent.settings import Settings


class Scripted:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        return next(self.responses)


def calls(*items):
    return ModelResponse(tool_calls=items, finish_reason="tool_calls")


def audit(identity="audit", verdict="complete", evidence=("distance", "bearing"), python=False, outputs=()):
    return calls(ToolCall(identity, "assess_completion", {
        "verdict": verdict, "feedback": "Check the actual operations and observed values.",
        "required_outputs": list(outputs), "requires_python_execution": python,
        "evidence_call_ids": list(evidence),
    }))


def geodesic_calls():
    args = {"lat1": 39.9042, "lon1": 116.4074, "lat2": 31.2304, "lon2": 121.4737}
    return calls(ToolCall("distance", "GeoHaversineDistance", args), ToolCall("bearing", "GeoBearing", args))


@pytest.fixture(autouse=True)
def optimized(monkeypatch):
    monkeypatch.setenv("GEOTOOL_OPTIMIZE_ROUND_TRIPS", "1")
    monkeypatch.setenv("GEOTOOL_COMBINED_COMPLETION_REVIEW", "1")


def test_native_recovery_survives_discovery_and_restores_auto_after_real_tools(tmp_path):
    model = Scripted(ModelResponse(), calls(ToolCall("load", "skill_load", {"skill_id": "geodesic_coordinate_analysis"})),
                     geodesic_calls(), ModelResponse("1067.31 km; 153.07 degrees."), audit())
    result = create_agent(model).run("Calculate Beijing to Shanghai distance and initial bearing.", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert result.model_turns == 5
    assert [r.tool_choice for r in model.requests] == ["auto", "required", "required", "auto", "required"]
    records = [json.loads(m.content) for m in result.state["messages"] if m.role == "tool"]
    assert [(r["name"], r["status"]) for r in records] == [("skill_load", "ok"), ("GeoHaversineDistance", "ok"), ("GeoBearing", "ok")]
    assert not result.state["metadata"].get("native_tool_recovery_pending")
    assert len(result.state["metadata"]["completion_reviews"]) == 1
    assert not result.state["metadata"].get("execution_reviews")


def test_bad_audit_citation_retries_only_the_audit(tmp_path):
    model = Scripted(geodesic_calls(), ModelResponse("1067.31 km; 153.07 degrees."),
                     audit("bad", evidence=("invented",)), audit("good"))
    result = create_agent(model).run("Calculate distance and bearing.", workspace=tmp_path, skill_id="geodesic_coordinate_analysis")
    assert result.status == "completed", result.reason
    assert result.model_turns == 4
    assert sum(m.role == "tool" for m in result.state["messages"]) == 2
    assert "assessment_protocol_feedback" in json.loads(model.requests[-1].messages[-1].content)


def test_incomplete_work_routes_back_to_actual_execution(tmp_path):
    model = Scripted(ModelResponse("I will calculate it."), audit("missing", verdict="continue", evidence=(), python=True, outputs=("sum.txt",)),
        calls(ToolCall("calc", "execute_python", {"code": "from pathlib import Path\np=Path('sum.txt')\np.write_text(str(2+3))\nprint(p.read_text())"})),
        ModelResponse("5, saved to sum.txt."), audit("done", evidence=("calc",), python=True, outputs=("sum.txt",)))
    result = create_agent(model).run("Use Python to calculate 2+3 and save sum.txt.", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert (tmp_path / "sum.txt").read_text() == "5"
    assert model.requests[2].tool_choice == "required"
    assert sum(m.role == "tool" for m in result.state["messages"]) == 1


def test_bad_wording_is_revised_without_reexecuting_professional_tools(tmp_path):
    model = Scripted(geodesic_calls(), ModelResponse("Next I will read the results."),
                     audit("revise", verdict="revise_answer"), ModelResponse("1067.31 km; 153.07 degrees."), audit("done"))
    result = create_agent(model).run("Calculate distance and bearing.", workspace=tmp_path, skill_id="geodesic_coordinate_analysis")
    assert result.status == "completed", result.reason
    assert model.requests[3].tool_choice == "none" and not model.requests[3].tools
    assert sum(m.role == "tool" for m in result.state["messages"]) == 2


def test_deterministic_checks_still_reject_incorrect_answer_before_publication(tmp_path):
    seen = []
    def check(state):
        seen.append(state["answer"])
        return [CompletionIssue("The distance contradicts the actual observation.")] if "9999" in state["answer"] else []
    model = Scripted(geodesic_calls(), ModelResponse("9999 km."), ModelResponse("1067.31 km; 153.07 degrees."), audit())
    result = create_agent(model, completion_checks=(check,)).run("Calculate distance and bearing.", workspace=tmp_path, skill_id="geodesic_coordinate_analysis")
    assert result.status == "completed", result.reason
    assert "9999 km." in seen and "9999" not in result.answer
    assert model.requests[2].tool_choice == "none"
    assert sum(m.role == "tool" for m in result.state["messages"]) == 2


def evidence_state():
    messages = [Message("user", "Report the observed value."),
                Message("assistant", tool_calls=(ToolCall("actual", "read_file", {"path": "value.txt"}),)),
                ToolResult("actual", "read_file", "ok", {"content": "42"}).message()]
    state = {"task": messages[0].content, "messages": messages, "artifacts": [], "answer": "42",
             "exposed_tool_names": ["read_file"], "metadata": {"optimize_round_trips": True}}
    def forbidden_build(_):
        raise AssertionError("Assessment must not build an execution context")
    return state, SimpleNamespace(build=forbidden_build)


def test_review_and_composition_do_not_load_execution_schemas_or_drop_evidence():
    state, context = evidence_state()
    evidence = completion_evidence(state, context)
    assert evidence["observed_actions"][0]["call"]["id"] == "actual"
    assert not evidence["older_tool_records_omitted"]
    for request in (final_answer_request(state, context, Settings()), combined_review_request(state, context, Settings())):
        assert "42" in request.messages[-1].content


def test_combined_review_still_enforces_its_actual_context_budget():
    state, context = evidence_state()
    state["answer"] = "x" * 5000
    with pytest.raises(ContextOverflow):
        combined_review_request(state, context, Settings(max_context_chars=4096))


def test_combined_review_does_not_bypass_model_turn_budget(tmp_path):
    model = Scripted(geodesic_calls(), ModelResponse("1067.31 km; 153.07 degrees."))
    result = create_agent(model, settings=Settings(max_model_turns=2)).run(
        "Calculate distance and bearing.", workspace=tmp_path, skill_id="geodesic_coordinate_analysis")
    assert result.status == "budget_exhausted" and not result.answer
    assert result.model_turns == 2 and len(model.requests) == 2

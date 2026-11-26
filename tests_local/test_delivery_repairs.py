import json
from dataclasses import replace
from types import SimpleNamespace
import pytest

from geological_agent.bootstrap import create_agent
from geological_agent.contracts import Message, ModelResponse, ToolCall, ToolResult
from geological_agent.agent.delivery_contract import delivery_issues, parse_covered_review, covered_request, requirement_segments
from geological_agent.agent.interaction_policy import human_input_issue, enrich_request
from geological_agent.agent.review_policy import combined_review_request
from geological_agent.settings import Settings
from geological_agent.llm import ModelProtocolError


def state(task="Report energy in scientific notation and state assumptions.", answer="3.548e14 J. Assumptions: empirical magnitude-energy relation."):
    return {"task": task, "answer": answer, "messages": [], "metadata": {"requirement_coverage": True},
            "artifacts": [], "exposed_tool_names": [], "selected_skill_ids": []}


@pytest.mark.parametrize("answer", ["354813389233576.06 J", "3.548e14 J", "Assumptions: empirical magnitude-energy relation. 354813389233576.06 J"])
def test_delivery_rejects_omissions_even_before_a_model_can_approve(answer):
    assert delivery_issues(state(answer=answer))


@pytest.mark.parametrize("value", ["3.548e14", "3.548 x 10^14", r"3.548 \times 10^{14}"])
def test_delivery_preserves_equivalent_scientific_formats(value):
    assert not delivery_issues(state(answer=value+" J. Assumptions: empirical magnitude-energy relation."))


def test_notation_exclusion_and_unrequested_hypothetical_assumptions():
    assert not delivery_issues(state("Do not use scientific notation.", "354813389233576.06 J"))
    assert not delivery_issues(state("假设北京发生地震，请报告能量。", "能量为3.548e14 J"))


def pause(kind, evidence=(), names=()):
    return ToolCall("human", "request_user_input", {"question": "Question", "reason": "Reason", "missing": [], "options": [],
        "reason_type": kind, "supporting_call_ids": list(evidence), "approval_tool_names": list(names)})


def test_missing_input_and_objective_can_pause_without_search():
    for kind in ("missing_input", "missing_objective"):
        assert human_input_issue(pause(kind), state(), None) is None


def test_missing_resource_requires_real_discovery_and_not_a_keyword_miss():
    s = state()
    assert human_input_issue(pause("unavailable_resource"), s, None)
    c = ToolCall("find", "skill_find", {"query": "no-match"})
    s["messages"] = [Message("assistant", tool_calls=(c,)), ToolResult("find", "skill_find", "ok", {"skills": []}).message()]
    assert human_input_issue(pause("unavailable_resource", ["find"]), s, None)
    s["messages"][0] = Message("assistant", tool_calls=(replace(c, arguments={"query": ""}),))
    assert human_input_issue(pause("unavailable_resource", ["find"]), s, None) is None
    assert human_input_issue(pause("unavailable_resource", ["invented"]), s, None)


def test_pure_calculation_does_not_need_renewed_permission():
    s = state(); s["exposed_tool_names"] = ["calculate"]
    registry = SimpleNamespace(get=lambda name: SimpleNamespace(pure=True))
    assert human_input_issue(pause("approval", names=["calculate"]), s, registry)


def test_review_cannot_approve_an_explicitly_unmet_requirement():
    s = state()
    args = {"verdict": "complete", "feedback": "Done", "required_outputs": [], "requires_python_execution": False,
        "evidence_call_ids": [], "requirement_checks": {"r1": {"satisfied": False, "answer_quotes": [], "call_ids": []}}}
    response = ModelResponse(tool_calls=(ToolCall("review", "assess_completion", args),), finish_reason="tool_calls")
    assert parse_covered_review(response, s, []) ["verdict"] == "revise_answer"
    args["requirement_checks"]["r1"]["answer_quotes"] = ["invented answer evidence"]
    with pytest.raises(ModelProtocolError):
        parse_covered_review(response, s, [])


def test_native_schema_and_formatting_hints_preserve_observed_magnitude():
    agent = create_agent(object(), human_input=True)
    s = state(); s["exposed_tool_names"] = list(agent.base_tools)
    s["messages"] = [ToolResult("energy", "GeoMagnitudeToEnergy", "ok", {"energy_j": 354813389233576.06}).message()]
    request = enrich_request(agent.context.build(s), s, Settings())
    definition = next(t for t in request.tools if t.name == "request_user_input")
    assert "reason_type" in definition.input_schema["required"]
    assert "3.548133892335761e+14" in request.messages[-1].content
    review = combined_review_request(s, agent.context, Settings())
    assert "requirement_checks" in review.tools[0].input_schema["required"]


def test_answer_repair_keeps_tools_once_and_publishes_only_full_delivery(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_OPTIMIZE_ROUND_TRIPS", "1")
    monkeypatch.setenv("GEOTOOL_COMBINED_COMPLETION_REVIEW", "1")
    monkeypatch.setenv("GEOTOOL_REQUIREMENT_COVERAGE", "1")
    task = "Report energy for Mw 6.5 in scientific notation and state assumptions."
    good = "3.548e14 J. Assumptions: empirical relation log10(E/J)=1.5 Mw+4.8."
    review = {"verdict": "complete", "feedback": "Observed energy and requested presentation match", "required_outputs": [],
        "requires_python_execution": False, "evidence_call_ids": ["energy"], "requirement_checks": {
        "r1": {"satisfied": True, "answer_quotes": ["3.548e14 J", "Assumptions: empirical relation log10(E/J)=1.5 Mw+4.8."], "call_ids": ["energy"]}}}
    responses = iter([ModelResponse(tool_calls=(ToolCall("energy", "GeoMagnitudeToEnergy", {"mw": 6.5}),), finish_reason="tool_calls"),
        ModelResponse("354813389233576.06 J"), ModelResponse(good),
        ModelResponse(tool_calls=(ToolCall("audit", "assess_completion", review),), finish_reason="tool_calls")])
    requests = []
    def invoke(request):
        requests.append(request); return next(responses)
    result = create_agent(SimpleNamespace(invoke=invoke)).run(task, workspace=tmp_path, skill_id="earthquake_energy")
    assert result.status == "completed" and result.answer == good
    assert len([m for m in result.state["messages"] if m.role == "tool"]) == 1
    assert requests[2].tool_choice == "none" and not requests[2].tools


def test_requirement_ids_preserve_decimal_coordinates_and_require_all_segments():
    s = state("Beijing (39.9042,116.4074). Report distance and bearing. State assumptions.",
              "Distance: **1067.31** km.\nOther text.\nBearing: **153.07** degrees.\nAssumptions: spherical Earth.")
    segments = requirement_segments(s)
    assert segments == {"r1": "Beijing (39.9042,116.4074)", "r2": "Report distance and bearing", "r3": "State assumptions"}
    checks = {key: {"satisfied": True, "answer_quotes": [], "call_ids": []} for key in segments}
    checks["r2"]["answer_quotes"] = ["1067.31 km", "153.07 degrees"]
    args = {"verdict": "complete", "feedback": "Covered", "required_outputs": [], "requires_python_execution": False,
            "evidence_call_ids": [], "requirement_checks": checks}
    response = ModelResponse(tool_calls=(ToolCall("review", "assess_completion", args),), finish_reason="tool_calls")
    assert parse_covered_review(response, s, []) ["verdict"] == "complete"
    checks.pop("r3")
    with pytest.raises(ModelProtocolError):
        parse_covered_review(response, s, [])


def test_normalized_evidence_still_rejects_wrong_numeric_values():
    s = state("Report distance.", "Distance: **1067.31** km")
    args = {"verdict": "complete", "feedback": "Covered", "required_outputs": [], "requires_python_execution": False,
            "evidence_call_ids": [], "requirement_checks": {"r1": {"satisfied": True, "answer_quotes": ["1067310 km"], "call_ids": []}}}
    with pytest.raises(ModelProtocolError):
        parse_covered_review(ModelResponse(tool_calls=(ToolCall("review", "assess_completion", args),), finish_reason="tool_calls"), s, [])

"""Source references must not turn successful computation into another execution."""
import copy
import json

import pytest

from geological_agent.agent.compact_review import compact_review_request, parse_compact_review
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import Message, ModelResponse, ToolCall, ToolResult
from geological_agent.llm import ModelProtocolError
from geological_agent.settings import Settings


def response(name, args, identity="review"):
    return ModelResponse(tool_calls=(ToolCall(identity, name, args),), finish_reason="tool_calls")


def review_state(support="read_file", second="KelvinToCelsius"):
    calls = (ToolCall("source", support, {"path": "sources.json"}),
             ToolCall("energy", "GeoMagnitudeToEnergy", {"mw": 6}),
             ToolCall("temperature", second, {"kelvin": 298.15}))
    return {"task": "Read the source and use professional tools to estimate energy and convert temperature.",
            "answer": "Energy: 6.31e13 J\nTemperature: 25 C", "artifacts": [],
            "selected_skill_ids": [], "exposed_tool_names": [c.name for c in calls],
            "metadata": {"optimize_round_trips": True, "review_reference_sets": True,
                         "professional_tool_names": ["GeoMagnitudeToEnergy", "KelvinToCelsius"]},
            "messages": [Message("assistant", tool_calls=calls),
                         ToolResult("source", support, "ok", {"content": "Actual source"}).message(),
                         ToolResult("energy", "GeoMagnitudeToEnergy", "ok", {"energy_j": 6.31e13}).message(),
                         ToolResult("temperature", second, "ok", {"value": 25}).message()]}


def assessment(state, refs, *, verdict="complete"):
    request = compact_review_request(state, None, Settings())
    payload = {"verdict": verdict, "feedback": "", "required_outputs": [],
               "requires_python_execution": False}
    if state["metadata"]["review_reference_sets"]:
        payload.update(requirement_checks={"r1": refs}, unmet_requirement_ids=[])
    else:
        payload.update(evidence_call_ids=[r for r in refs if r.startswith("t")],
                       requirement_checks={"r1": {"ok": True,
                           "a": [r for r in refs if r.startswith("a")],
                           "t": [r for r in refs if r.startswith("t")]}})
    return parse_compact_review(response("assess_completion", payload), state, request)


@pytest.mark.parametrize("support", ["read_file", "web_fetch", "web_search"])
@pytest.mark.parametrize("reference_sets", [True, False])
def test_source_and_professional_references_are_valid_together(support, reference_sets):
    state = review_state(support)
    state["metadata"]["review_reference_sets"] = reference_sets
    original = copy.deepcopy(state)
    parsed = assessment(state, ["a1", "a2", "t1", "t2", "t3"])
    assert parsed["verdict"] == "complete"
    assert parsed["requirement_checks"]["r1"]["satisfied"]
    assert parsed["requirement_checks"]["r1"]["call_ids"] == ["source", "energy", "temperature"]
    assert state == original


@pytest.mark.parametrize("support", ["context_read", "context_search"])
@pytest.mark.parametrize("reference_sets", [True, False])
def test_context_lookup_preserves_original_execution_reference_namespace(support, reference_sets):
    state = review_state(support)
    state["metadata"]["review_reference_sets"] = reference_sets
    request = compact_review_request(state, None, Settings())
    payload = json.loads(request.messages[1].content)
    assert payload["successful_result_ids"] == ["t1", "t2"]
    assert payload["professional_result_ids"] == ["t1", "t2"]
    assert assessment(state, ["a1", "a2", "t1", "t2"])["verdict"] == "complete"
    with pytest.raises(ModelProtocolError):
        assessment(state, ["a1", "a2", "t1", "t2", "t3"])


@pytest.mark.parametrize("support", ["skill_find", "skill_load"])
@pytest.mark.parametrize("reference_sets", [True, False])
def test_discovery_is_not_promoted_to_source_or_calculation_evidence(support, reference_sets):
    state = review_state(support)
    state["metadata"]["review_reference_sets"] = reference_sets
    parsed = assessment(state, ["a1", "a2", "t1", "t2", "t3"])
    assert parsed["verdict"] == "continue"
    assert not parsed["requirement_checks"]["r1"]["satisfied"]


@pytest.mark.parametrize("refs", [[], ["a1", "a2"], ["a1", "a2", "t1"]])
def test_sources_alone_never_establish_professional_execution(refs):
    parsed = assessment(review_state(), refs)
    assert parsed["verdict"] == "continue"
    assert not parsed["requirement_checks"]["r1"]["satisfied"]


@pytest.mark.parametrize("substitute", ["execute_python", "write_file", "request_user_input"])
def test_generic_execution_cannot_replace_another_professional_operation(substitute):
    parsed = assessment(review_state(second=substitute), ["a1", "a2", "t1", "t2", "t3"])
    assert parsed["verdict"] == "continue"
    assert not parsed["requirement_checks"]["r1"]["satisfied"]


def test_explicit_tool_names_require_each_matching_professional_result():
    state = review_state()
    state["task"] = "Use GeoMagnitudeToEnergy and KelvinToCelsius, reading sources as needed."
    assert assessment(state, ["a1", "a2", "t1", "t2"])["verdict"] == "continue"
    assert assessment(state, ["a1", "a2", "t1", "t2", "t3"])["verdict"] == "complete"


def test_failed_professional_result_is_not_supporting_success():
    state = review_state()
    state["messages"][-1] = ToolResult("temperature", "KelvinToCelsius", "error", {}).message()
    state["task"] = "Use GeoMagnitudeToEnergy and KelvinToCelsius."
    parsed = assessment(state, ["a1", "a2", "t1", "t2"])
    assert parsed["verdict"] == "continue"
    assert not parsed["requirement_checks"]["r1"]["satisfied"]


def test_runtime_source_reference_does_not_repeat_successful_tools(tmp_path, monkeypatch):
    for flag in ("GEOTOOL_INTENT_REVIEW", "GEOTOOL_COMPACT_REVIEW", "GEOTOOL_REQUIREMENT_COVERAGE",
                 "GEOTOOL_COMBINED_COMPLETION_REVIEW", "GEOTOOL_OPTIMIZE_ROUND_TRIPS",
                 "GEOTOOL_COMPACT_DISCOVERY", "GEOTOOL_REVIEW_REFERENCE_SETS"):
        monkeypatch.setenv(flag, "1")
    (tmp_path / "sources.json").write_text('{"approximation":"spherical"}', encoding="utf-8")
    requests = []
    coords = {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 1}

    class Model:
        def invoke(self, request):
            requests.append(request)
            n = len(requests)
            if n == 1:
                return response("assess_task_intent", {"objective_present": True, "question": "",
                    "skill_ids": ["geodesic_coordinate_analysis"]}, "intent")
            if n == 2:
                return response("read_file", {"path": "sources.json"}, "source")
            if n == 3:
                return ModelResponse(tool_calls=(ToolCall("distance", "GeoHaversineDistance", coords),
                                                  ToolCall("bearing", "GeoBearing", coords)), finish_reason="tool_calls")
            if n == 4:
                return ModelResponse("Distance: 111.195 km\nInitial bearing: 90 degrees\nSpherical approximation.")
            assert n == 5, "Successful work was unexpectedly returned to execution"
            payload = json.loads(request.messages[1].content)
            assert payload["professional_result_ids"] == ["t2", "t3"]
            return response("assess_completion", {"verdict": "complete", "feedback": "",
                "required_outputs": [], "requires_python_execution": False,
                "requirement_checks": {key: ["a1", "a2", "a3", "t1", "t2", "t3"]
                                       for key in payload["requirement_ids"]}, "unmet_requirement_ids": []})

    result = create_agent(Model(), settings=Settings(max_model_turns=5)).run(
        "Read sources.json and use professional tools to calculate spherical distance and initial bearing from (0,0) to (0,1), stating units and the approximation.",
        workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert result.model_turns == len(requests) == 5
    assert [c.name for m in result.state["messages"] for c in m.tool_calls] == [
        "read_file", "GeoHaversineDistance", "GeoBearing"]
    observations = [json.loads(m.content) for m in result.state["messages"] if m.role == "tool"]
    assert len(observations) == 3 and all(r["status"] == "ok" for r in observations)
    assert len(result.state["metadata"]["completion_reviews"]) == 1

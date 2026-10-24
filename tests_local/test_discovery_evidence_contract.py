import json
import pytest
from geological_agent.agent.compact_review import compact_review_request, parse_compact_review
from geological_agent.agent.delivery_contract import delivery_issues, line_count_requirement
from geological_agent.agent.execution_contract import obligations, requested_execution_issues
from geological_agent.agent.intent_review import intent_request
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import Message, ModelResponse, ToolCall, ToolResult
from geological_agent.settings import Settings
from geological_agent.skills import SkillSummary

def reply(name, arguments, identity="assessment"):
    return ModelResponse(tool_calls=(ToolCall(identity, name, arguments),), finish_reason="tool_calls")

def test_catalog_describes_actual_operations_without_exposing_schemas():
    summaries = [SkillSummary("preprocess", "Preprocessing", "Spectral indices", "Preprocess")]
    mapping = {"preprocess": [{"name": "KelvinToCelsius", "purpose": "Convert kelvin to Celsius."}]}
    request = intent_request({"task": "Convert temperature", "metadata": {}}, Settings(),
                             skill_summaries=summaries, skill_tools=mapping)
    entry = json.loads(request.messages[1].content)["available_skills"][0]
    assert entry["tools"] == mapping["preprocess"]
    assert [d.name for d in request.tools] == ["assess_task_intent"]
    assert "input_schema" not in entry["tools"][0]

@pytest.mark.parametrize("task, required", [
    ("\u7528\u4e13\u4e1a\u5de5\u5177\u8ba1\u7b97\u8ddd\u79bb", True),
    ("\u4e0d\u7528\u4e13\u4e1a\u5de5\u5177", False),
    ("\u4e0d\u8981\u7528\u4e13\u4e1a\u5de5\u5177", False),
    ("\u600e\u4e48\u7528\u4e13\u4e1a\u5de5\u5177", False),
    ("Use professional tools to calculate distance.", True),
    ("Do not use professional tools.", False),
])
def test_short_use_instruction_preserves_negation_and_explanations(task, required):
    state = {"task": task, "metadata": {}, "messages": []}
    assert obligations(state, {"GeoHaversineDistance"})[0] is required
    assert bool(requested_execution_issues(state, {"GeoHaversineDistance"})) is required

@pytest.mark.parametrize("task,count", [
    ("\u53ea\u7ed9\u4e09\u884c\u7ed3\u679c", 3),
    ("\u53ea\u7ed9\u4e24\u884c\u7ed3\u679c\uff0c\u5e76\u7528\u4e00\u53e5\u8bdd\u6ce8\u660e\u8fd1\u4f3c", 3),
    ("\u53ea\u7ed9\u4e24\u884c\u7ed3\u679c\uff0c\u5e76\u8865\u4e00\u53e5\u8bf4\u660e", 3),
    ("Return exactly 3 lines.", 3),
    ("Only two lines plus a one-sentence note.", 3),
    ("Only two lines plus one sentence.", 3),
    ("Only two lines plus one-sentence note.", 3),
    ("Only 12 lines.", 12),
    ("Be concise.", None),
    ("Do not return only 3 lines.", None),
    ("Not only 3 lines.", None),
    ("\u4e0d\u8981\u53ea\u7ed9\u4e09\u884c", None),
])
def test_explicit_line_contract(task, count):
    assert line_count_requirement({"task": task}) == count

def test_line_count_checks_whole_answer_not_just_cited_results():
    task = "Return exactly three lines."
    assert not delivery_issues({"task": task, "answer": "Slope: 1.971 units/year\nSen: 2.000 units/year\nCV: 0.207 (dimensionless)"})
    issues = delivery_issues({"task": task, "answer": "Here are the results:\nSlope: 1.971\nSen: 2.000\nCV: 0.207\nThank you."})
    assert len(issues) == 1 and not issues[0].needs_action
    assert "draft has 5" in issues[0].message

def test_blank_lines_do_not_count_but_missing_result_does():
    assert not delivery_issues({"task": "Only two lines.", "answer": "A\n\nB"})
    assert delivery_issues({"task": "Only two lines.", "answer": "A"})

def evidence_state():
    return {"task": "Use professional tools to estimate energy and convert temperature.",
            "answer": "Energy: 6.31e13 J\nTemperature: 25 C",
            "artifacts": [], "selected_skill_ids": [],
            "exposed_tool_names": ["GeoMagnitudeToEnergy", "KelvinToCelsius", "execute_python"],
            "metadata": {"optimize_round_trips": True, "review_reference_sets": True,
                         "professional_tool_names": ["GeoMagnitudeToEnergy", "KelvinToCelsius"]},
            "messages": [
                Message("assistant", tool_calls=(ToolCall("energy", "GeoMagnitudeToEnergy", {"mw": 6}),
                                                  ToolCall("temperature", "execute_python", {"code": "print(25)"}))),
                ToolResult("energy", "GeoMagnitudeToEnergy", "ok", {"energy_j": 6.31e13}).message(),
                ToolResult("temperature", "execute_python", "ok", {"stdout": "25"}).message()]}

def review_payload(verdict="complete", refs=None):
    return {"verdict": verdict, "feedback": "", "required_outputs": [], "requires_python_execution": False,
            "requirement_checks": {"r1": refs if refs is not None else ["a1", "a2", "t1", "t2"]},
            "unmet_requirement_ids": []}

@pytest.mark.parametrize("refs", [[], ["a1", "a2"], ["t1", "t2"]])
def test_generic_or_absent_professional_evidence_cannot_be_approved(refs):
    state = evidence_state()
    req = compact_review_request(state, None, Settings())
    parsed = parse_compact_review(reply("assess_completion", review_payload(refs=refs)), state, req)
    assert parsed["verdict"] == "continue"
    assert not parsed["requirement_checks"]["r1"]["satisfied"]

def test_discovery_cannot_be_counted_as_professional_evidence():
    state = evidence_state()
    state["messages"][-1] = ToolResult("temperature", "skill_load", "ok", {"skill_id": "temperature"}).message()
    req = compact_review_request(state, None, Settings())
    parsed = parse_compact_review(reply("assess_completion", review_payload()), state, req)
    assert parsed["verdict"] == "continue"

def test_real_professional_results_retained_and_classified():
    state = evidence_state()
    state["messages"][0] = Message("assistant", tool_calls=(ToolCall("energy", "GeoMagnitudeToEnergy", {"mw": 6}),
                                                          ToolCall("temperature", "KelvinToCelsius", {"kelvin": 298.15})))
    state["messages"][-1] = ToolResult("temperature", "KelvinToCelsius", "ok", {"value": 25}).message()
    req = compact_review_request(state, None, Settings())
    assert json.loads(req.messages[1].content)["professional_result_ids"] == ["t1", "t2"]
    parsed = parse_compact_review(reply("assess_completion", review_payload()), state, req)
    assert parsed["verdict"] == "complete"
    assert parsed["evidence_call_ids"] == ["energy", "temperature"]

@pytest.mark.parametrize("verdict", ["clarify", "cannot_complete"])
def test_missing_resource_outcomes_are_not_forced_into_execution_loop(verdict):
    state = evidence_state()
    req = compact_review_request(state, None, Settings())
    args = review_payload(verdict=verdict, refs=[])
    args["feedback"] = "Required input or available tool is missing."
    assert parse_compact_review(reply("assess_completion", args), state, req)["verdict"] == verdict

def test_preloaded_context_and_required_choice_end_to_end(tmp_path, monkeypatch):
    for flag in ("GEOTOOL_INTENT_REVIEW", "GEOTOOL_COMPACT_REVIEW", "GEOTOOL_REQUIREMENT_COVERAGE",
                 "GEOTOOL_COMBINED_COMPLETION_REVIEW", "GEOTOOL_OPTIMIZE_ROUND_TRIPS",
                 "GEOTOOL_COMPACT_DISCOVERY", "GEOTOOL_REVIEW_REFERENCE_SETS"):
        monkeypatch.setenv(flag, "1")
    requests = []
    coords = {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 1}
    class Model:
        def invoke(self, request):
            requests.append(request)
            if len(requests) == 1:
                catalog = json.loads(request.messages[1].content)["available_skills"]
                geo = next(s for s in catalog if s["id"] == "geodesic_coordinate_analysis")
                assert any(t["name"] == "GeoBearing" and t["purpose"] for t in geo["tools"])
                return reply("assess_task_intent", {"objective_present": True, "question": "",
                                                   "skill_ids": ["geodesic_coordinate_analysis"]}, "intent")
            if len(requests) == 2:
                assert request.tool_choice == "required"
                system = request.messages[0].content
                assert "already available; no skill_load needed" in system
                line = next(line for line in system.splitlines() if "NOT YET loaded skill summaries:" in line)
                assert "geodesic_coordinate_analysis" not in line
                assert "Do not reload" in system
                assert {"GeoHaversineDistance", "GeoBearing"} <= {t.name for t in request.tools}
                return ModelResponse(tool_calls=(ToolCall("d", "GeoHaversineDistance", coords),
                                                  ToolCall("b", "GeoBearing", coords)), finish_reason="tool_calls")
            if len(requests) == 3:
                return ModelResponse("Distance: 111.195 km\nBearing: 90 degrees")
            payload = json.loads(request.messages[1].content)
            assert payload["professional_result_ids"] == ["t1", "t2"]
            return reply("assess_completion", {"verdict": "complete", "feedback": "",
                "required_outputs": [], "requires_python_execution": False,
                "requirement_checks": {key: ["a1", "a2", "t1", "t2"] for key in payload["requirement_ids"]},
                "unmet_requirement_ids": []}, "review")
    result = create_agent(Model(), settings=Settings(max_model_turns=4)).run(
        "\u7528\u4e13\u4e1a\u5de5\u5177\u8ba1\u7b97 (0,0) \u5230 (0,1) \u7684\u8ddd\u79bb\u548c\u65b9\u4f4d\u89d2\u3002Only two lines.", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert result.model_turns == 4
    assert [c.name for m in result.state["messages"] for c in m.tool_calls] == ["GeoHaversineDistance", "GeoBearing"]

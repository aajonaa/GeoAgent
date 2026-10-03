import json
from dataclasses import replace
import pytest
from geological_agent.agent.completion import final_answer_request, resolve_final_answer
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import Message, ModelRequest, ModelResponse, ToolCall, ToolResult
from geological_agent.geology.validation import validate_energy_answer
from geological_agent.llm import ModelProtocolError
from geological_agent.settings import Settings

def state():
    return {"task": "Only two lines.", "messages": [], "artifacts": [], "answer": "",
            "metadata": {"rejected_answers": [
                {"answer": "A\nB\nExtra", "feedback": "Exactly 2 nonempty answer lines in total"},
                {"answer": "A\nB\nExtra again", "feedback": "Exactly 2 nonempty answer lines in total"}]}}

def response(lines):
    return ModelResponse(tool_calls=(ToolCall("format", "format_final_answer", {"lines": lines}),),
                         finish_reason="tool_calls", usage={"completion_tokens": 12})

def test_answer_repair_sees_last_rejected_draft_and_line_diagnostics():
    s = state()
    s["metadata"]["rejected_answers"] = s["metadata"]["rejected_answers"][:1]
    request = final_answer_request(s, None, Settings())
    payload = json.loads(request.messages[1].content)
    assert payload["rejected_draft"]["text"] == "A\nB\nExtra"
    assert payload["rejected_draft"]["nonempty_lines"] == {"1": "A", "2": "B", "3": "Extra"}
    assert payload["observed_actions"] == []
    assert request.tool_choice == "none" and request.tools == ()
    assert "unit on its own result line" in request.messages[0].content

def test_repeated_line_failure_changes_to_native_formatting_without_execution():
    s = state()
    request = final_answer_request(s, None, Settings())
    assert request.tool_choice == "required"
    assert [tool.name for tool in request.tools] == ["format_final_answer"]
    assert request.tools[0].input_schema["properties"]["lines"]["minItems"] == 2
    assert request.tools[0].input_schema["properties"]["lines"]["maxItems"] == 2
    raw = response(["A", "B"])
    rendered = resolve_final_answer(raw, request)
    assert rendered.content == "A\nB"
    assert not rendered.tool_calls and rendered.finish_reason == "stop"
    assert raw.tool_calls and raw.content == ""
    assert rendered.usage == raw.usage

@pytest.mark.parametrize("lines", [["A"], ["A", "B", "C"], ["A\nC", "B"], ["  ", "B"], [1, "B"]])
def test_native_formatting_rejects_invalid_lines(lines):
    with pytest.raises(ModelProtocolError):
        resolve_final_answer(response(lines), final_answer_request(state(), None, Settings()))

def test_native_formatting_rejects_workspace_calls():
    r = replace(response(["A", "B"]), tool_calls=(ToolCall("x", "execute_python", {"code": "print(1)"}),))
    with pytest.raises(ModelProtocolError):
        resolve_final_answer(r, final_answer_request(state(), None, Settings()))

def test_non_format_response_is_never_silently_converted():
    request = ModelRequest((Message("system", "Answer only"),), (), tool_choice="none")
    raw = response(["A", "B"])
    assert resolve_final_answer(raw, request) is raw

def test_repair_does_not_bypass_numerical_validation():
    s = state()
    s["messages"] = [Message("assistant", tool_calls=(ToolCall("e", "GeoMagnitudeToEnergy", {"mw": 6}),)),
                     ToolResult("e", "GeoMagnitudeToEnergy", "ok", {"energy_j": 63095734448019.43, "tnt_tons": 15080.242458895656}).message()]
    rendered = resolve_final_answer(response(["Energy: 6.31e16 J", "Empirical estimate"]),
                                    final_answer_request(s, None, Settings()))
    assert validate_energy_answer({**s, "answer": rendered.content})

def test_runtime_repairs_presentation_without_repeating_professional_tools(tmp_path, monkeypatch):
    for flag in ("GEOTOOL_INTENT_REVIEW", "GEOTOOL_COMPACT_REVIEW", "GEOTOOL_REQUIREMENT_COVERAGE",
                 "GEOTOOL_COMBINED_COMPLETION_REVIEW", "GEOTOOL_OPTIMIZE_ROUND_TRIPS",
                 "GEOTOOL_COMPACT_DISCOVERY", "GEOTOOL_REVIEW_REFERENCE_SETS"):
        monkeypatch.setenv(flag, "1")
    requests = []
    coords = {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 1}
    class Model:
        def invoke(self, request):
            requests.append(request)
            n = len(requests)
            if n == 1:
                return ModelResponse(tool_calls=(ToolCall("intent", "assess_task_intent",
                    {"objective_present": True, "question": "", "skill_ids": ["geodesic_coordinate_analysis"]}),), finish_reason="tool_calls")
            if n == 2:
                return ModelResponse(tool_calls=(ToolCall("d", "GeoHaversineDistance", coords),
                                                  ToolCall("b", "GeoBearing", coords)), finish_reason="tool_calls")
            if n in (3, 4):
                if n == 4:
                    payload = json.loads(request.messages[1].content)
                    assert payload["rejected_draft"]["text"].endswith("Unrequested conclusion.")
                    assert request.tool_choice == "none"
                return ModelResponse("Distance: 111.195 km\nBearing: 90 degrees\nUnrequested conclusion.")
            if n == 5:
                assert request.tool_choice == "required"
                assert [t.name for t in request.tools] == ["format_final_answer"]
                return response(["Distance: 111.195 km", "Bearing: 90 degrees"])
            assert n == 6
            payload = json.loads(request.messages[1].content)
            assert set(payload["answer_line_ids"]) == {"a1", "a2"}
            assert len(payload["observed_actions"]) == 2
            return ModelResponse(tool_calls=(ToolCall("review", "assess_completion",
                {"verdict": "complete", "feedback": "", "required_outputs": [], "requires_python_execution": False,
                 "requirement_checks": {key: ["a1", "a2", "t1", "t2"] for key in payload["requirement_ids"]},
                 "unmet_requirement_ids": []}),), finish_reason="tool_calls")
    agent = create_agent(Model(), settings=Settings(max_model_turns=6))
    result = agent.run("Use professional tools to calculate distance and bearing from (0,0) to (0,1). Only two lines.",
                       workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert result.model_turns == 6
    assert result.answer == "Distance: 111.195 km\nBearing: 90 degrees"
    assert [c.name for m in result.state["messages"] for c in m.tool_calls] == ["GeoHaversineDistance", "GeoBearing"]
    assert len(result.state["metadata"]["rejected_answers"]) == 2
    assert len(result.state["metadata"]["completion_reviews"]) == 1

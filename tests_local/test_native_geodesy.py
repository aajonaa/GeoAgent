import math
from threading import Event

import pytest

from geological_agent.bootstrap import create_agent
from geological_agent.contracts import Message, ModelResponse, ToolCall
from geological_agent.tools import ToolExecutionContext
from legacy.ToolsAgent.ToolsFuns.source_contracts import definition


CASES = [
    ("GeoHaversineDistance", {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 90}, "distance_km", math.pi * 6371.0088 / 2),
    ("GeoBearing", {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 90}, "bearing_degrees", 90),
    ("GeoDecimalToDMS", {"value": 39.9042, "axis": "lat"}, "decimal_degrees", 39.9042),
    ("GeoWGS84BBoxAreaKm2", {"min_lon": 0, "min_lat": 0, "max_lon": 90, "max_lat": 90}, "area_km2", math.pi * 6371.0088 ** 2 / 2),
    ("GeoCheckCRSConsistency", {"crs_values": ["epsg:4326", "EPSG:4326"]}, "consistent", True),
    ("GeoMagnitudeToEnergy", {"mw": 6}, "energy_j", 10 ** 13.8),
]


@pytest.mark.parametrize("name,args,field,expected", CASES)
def test_native_source_contract_and_known_result(tmp_path, name, args, field, expected):
    agent = create_agent(object())
    tool = agent.tools.get(name)
    assert tool.definition.input_schema == definition(name)["input_schema"]
    assert tool.definition.result_schema == definition(name)["output_schema"]
    ctx = ToolExecutionContext("test", tmp_path, (name,), agent.settings, Event())
    result = agent.executor.execute(ToolCall("first", name, args), ctx)
    assert result.status == "ok", result.error
    assert result.data[field] == pytest.approx(expected)
    cached = agent.executor.execute(ToolCall("second", name, args), ctx)
    assert cached.cached and cached.call_id == "second" and cached.data == result.data
    hidden = agent.executor.execute(ToolCall("hidden", name, args),
                                    ToolExecutionContext("test", tmp_path, (), agent.settings, Event()))
    assert hidden.error.code == "tool_not_exposed"


@pytest.mark.parametrize("name,args", [
    ("GeoHaversineDistance", {"lat1": 91, "lon1": 0, "lat2": 0, "lon2": 90}),
    ("GeoBearing", {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 180}),
    ("GeoDecimalToDMS", {"value": 91, "axis": "lat"}),
    ("GeoWGS84BBoxAreaKm2", {"min_lon": 170, "min_lat": 0, "max_lon": -170, "max_lat": 10}),
    ("GeoCheckCRSConsistency", {"crs_values": []}),
])
def test_native_invalid_scientific_arguments_rejected(tmp_path, name, args):
    agent = create_agent(object())
    ctx = ToolExecutionContext("test", tmp_path, (name,), agent.settings, Event())
    assert agent.executor.execute(ToolCall("bad", name, args), ctx).status == "error"


def test_summary_disclosure_does_not_expose_tools_before_loading(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_OPTIMIZE_ROUND_TRIPS", "1")
    agent = create_agent(object())
    state = {"task": "Distance and bearing", "messages": [Message("user", "Distance and bearing")],
             "metadata": {"optimize_round_trips": True}, "selected_skill_ids": [],
             "exposed_tool_names": list(agent.base_tools)}
    request = agent.context.build(state)
    assert "geodesic_coordinate_analysis" in request.messages[0].content
    assert "GeoHaversineDistance" not in {t.name for t in request.tools}
    state["selected_skill_ids"] = ["geodesic_coordinate_analysis"]
    state["exposed_tool_names"] += list(agent.skills.load("geodesic_coordinate_analysis").tool_names)
    assert "GeoHaversineDistance" in {t.name for t in agent.context.build(state).tools}


def test_independent_professional_calls_share_one_turn(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_OPTIMIZE_ROUND_TRIPS", "1")
    xy = {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 90}
    result_text = "The spherical distance is 10007.56 km and the initial bearing is 90 degrees."
    review = {"verdict": "complete", "feedback": "Both requested values match the successful tool results.",
              "required_outputs": [], "requires_python_execution": False, "evidence_call_ids": ["distance", "bearing"]}
    responses = iter([
        ModelResponse(tool_calls=(ToolCall("load", "skill_load", {"skill_id": "geodesic_coordinate_analysis"}),), finish_reason="tool_calls"),
        ModelResponse(tool_calls=(ToolCall("distance", "GeoHaversineDistance", xy), ToolCall("bearing", "GeoBearing", xy)), finish_reason="tool_calls"),
        ModelResponse(result_text),
        ModelResponse(tool_calls=(ToolCall("review-work", "assess_completion", review),), finish_reason="tool_calls"),
        ModelResponse(tool_calls=(ToolCall("review-answer", "assess_completion", review),), finish_reason="tool_calls"),
    ])
    class Model:
        def invoke(self, request):
            return next(responses)
    result = create_agent(Model()).run("Calculate the distance and bearing", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert result.answer == result_text and result.model_turns == 5
    executed = [call.name for m in result.state["messages"] for call in m.tool_calls]
    assert executed == ["skill_load", "GeoHaversineDistance", "GeoBearing"]
    assert not result.artifacts

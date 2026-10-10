"""Native progressive disclosure preserves contracts, messages and validation."""
from copy import deepcopy
from dataclasses import asdict
import json
from types import SimpleNamespace

import pytest

from geological_agent.agent.compaction import ContextOverflow, request_size
from geological_agent.agent.skill_scope import fit_skill_scope
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import Message, ModelRequest, ModelResponse, ToolCall, ToolResult
from geological_agent.settings import Settings
from geological_agent.skills import Skill, SkillLoader, SkillRegistry, SkillSummary
from geological_agent.tools import ToolDefinition, object_schema


def fixture_scope(count=3):
    registry = SkillRegistry()
    definitions = {}
    for i in range(count):
        sid, name = "s" + str(i), "Tool" + str(i)
        registry.register(Skill(SkillSummary(sid, sid, "A procedure", "When needed"),
            (), "Exact instructions " + str(i) * 3000, (), (name,), ()))
        definitions[name] = ToolDefinition(name, "Native operation", "Needed",
            object_schema({"value": {"type": "number", "description": "Value in metres."}}, ["value"]), {})
    skills = SkillLoader(registry)
    state = {"run_id": "a" * 32, "task": "Keep units and originals.",
        "selected_skill_ids": ["s" + str(i) for i in range(count)],
        "exposed_tool_names": list(definitions), "pending_tool_calls": [],
        "messages": [Message("user", "Keep units and originals.")],
        "metadata": {}, "artifacts": []}
    def build(current):
        text = "Instructions\n" + "\n".join(skills.load(sid).instructions for sid in current["selected_skill_ids"])
        text += "\nDeferred: " + json.dumps(current["metadata"].get("deferred_skill_ids", []))
        return ModelRequest((Message("system", text), *current["messages"]),
                            tuple(definitions[n] for n in current["exposed_tool_names"]))
    return state, skills, definitions, build


def scope(state, skills, build, limit=8000):
    return fit_skill_scope(state, build_request=build, base_tool_names=(),
                           skills=skills, settings=Settings(context_window_tokens=None, max_context_chars=limit))


def test_overloaded_scope_defers_whole_skills_not_schema_fragments():
    state, skills, definitions, build = fixture_scope()
    original = deepcopy(state)
    result, info = scope(state, skills, build)
    assert result["selected_skill_ids"] == ["s0", "s1"]
    assert result["metadata"]["deferred_skill_ids"] == ["s2"]
    assert request_size(build(result)) <= 8000
    assert build(result).tools == (definitions["Tool0"], definitions["Tool1"])
    assert state == original and result["messages"] is state["messages"]
    assert info["execution_evidence_preserved"] and info["schemas_unchanged"]


def test_no_fixed_one_skill_or_tool_count_limit():
    state, skills, definitions, build = fixture_scope(count=5)
    result, _ = scope(state, skills, build, limit=24000)
    assert result["selected_skill_ids"] == state["selected_skill_ids"]
    assert result["exposed_tool_names"] == list(definitions)
    assert not result["metadata"]["deferred_skill_ids"]


def test_explicit_load_activates_deferred_skill_and_preserves_exact_evidence():
    state, skills, definitions, build = fixture_scope()
    first, _ = scope(state, skills, build)
    call = ToolCall("original", "Tool0", {"value": 12.25})
    observation = ToolResult("original", "Tool0", "ok",
        {"value": 12.25, "unit": "metre", "source_sha256": "b" * 64}).message()
    first["messages"] = [*first["messages"], Message("assistant", tool_calls=(call,)), observation]
    first["selected_skill_ids"].append("s2")
    first["metadata"]["skill_scope_focus"] = ["s2"]
    messages_before = deepcopy(first["messages"])
    two_skills = {**first, "selected_skill_ids": ["s2", "s0"],
                  "exposed_tool_names": ["Tool2", "Tool0"],
                  "metadata": {**first["metadata"], "deferred_skill_ids": ["s1"]}}
    # Include the complete native exchange and schemas in the fixture budget.
    # Leave room for precisely two skills at the existing 90% headroom target.
    two_size = request_size(build(two_skills))
    budget = (two_size * 10 + 8) // 9 + 2
    all_skills = {**two_skills, "selected_skill_ids": ["s2", "s0", "s1"],
                  "exposed_tool_names": ["Tool2", "Tool0", "Tool1"],
                  "metadata": {**first["metadata"], "deferred_skill_ids": []}}
    assert request_size(build(all_skills)) > budget
    result, info = scope(first, skills, build, limit=budget)
    assert result["selected_skill_ids"][0] == "s2"
    assert "Tool2" in result["exposed_tool_names"]
    assert result["metadata"]["deferred_skill_ids"] == ["s1"]
    assert result["messages"] == messages_before
    assert result["messages"][-1] is observation
    assert info["source"] == "explicit_skill_load"
    assert all(t == definitions[t.name] for t in build(result).tools)
    # Deferred schemas are not silently restored on the next turn.
    again, _ = scope(result, skills, build, limit=budget)
    assert again["selected_skill_ids"] == result["selected_skill_ids"]


def test_soft_headroom_does_not_reject_a_single_fitting_skill():
    state, skills, definitions, build = fixture_scope(count=1)
    size = request_size(build({**state, "metadata": {"deferred_skill_ids": []}}))
    result, _ = scope(state, skills, build, limit=size + 5)
    assert result["selected_skill_ids"] == ["s0"]


def test_pending_calls_cannot_lose_their_schema_or_authorization():
    state, skills, _, build = fixture_scope()
    state["pending_tool_calls"] = [ToolCall("pending", "Tool0", {"value": 1})]
    with pytest.raises(ValueError, match="pending"):
        scope(state, skills, build)


def test_oversized_user_constraints_are_not_summarized_or_dropped():
    state, skills, _, build = fixture_scope()
    state["messages"] = [Message("user", "exact-user-constraint " * 1000)]
    before = deepcopy(state)
    with pytest.raises(ContextOverflow, match="current user instructions"):
        scope(state, skills, build)
    assert state == before


def test_real_five_skill_intent_fits_then_executes_native_raster(tmp_path, monkeypatch):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from geological_agent.scientific_imaging import SCHEMAS
    for flag in ("GEOTOOL_INTENT_REVIEW", "GEOTOOL_COMPACT_DISCOVERY",
                 "GEOTOOL_OPTIMIZE_ROUND_TRIPS", "GEOTOOL_REQUIREMENT_COVERAGE"):
        monkeypatch.setenv(flag, "1")
    raster = tmp_path / "input.tif"
    with rasterio.open(raster, "w", driver="GTiff", width=2, height=2, count=2,
                       dtype="float32", crs="EPSG:32650", transform=from_origin(500000, 4000000, 10, 10)) as dst:
        dst.write(np.full((2, 2), .1, dtype="float32"), 1)
        dst.write(np.full((2, 2), .3, dtype="float32"), 2)
    requests = []
    ids = ["scientific_raster_analysis", "image_workflow", "remote_sensing_preprocessing",
           "remote_sensing_raster_statistics", "remote_sensing_data_discovery"]
    class Model:
        def invoke(self, request):
            requests.append(request)
            assert request_size(request) <= 48000
            if len(requests) == 1:
                return ModelResponse(tool_calls=(ToolCall("intent", "assess_task_intent",
                    {"objective_present": True, "question": "", "skill_ids": ids}),), finish_reason="tool_calls")
            if len(requests) == 2:
                definition = next(t for t in request.tools if t.name == "GeoRasterIndexAnalysis")
                assert definition.input_schema == SCHEMAS["GeoRasterIndexAnalysis"]
                assert "Skill disclosure deferred" in request.messages[0].content
                return ModelResponse(tool_calls=(ToolCall("ndvi", "GeoRasterIndexAnalysis",
                    {"path": "input.tif", "output_dir": "ndvi", "index": "NDVI",
                     "bands": {"red": 1, "nir": 2}, "calibration_source": "Explicit synthetic fixture; scale 1 offset 0."}),),
                    finish_reason="tool_calls")
            assert len(requests) == 3
            return ModelResponse("NDVI is 0.5 for four valid synthetic pixels; files are in ndvi/.")
    agent = create_agent(Model(), settings=Settings(verify_completion=False, max_model_turns=3))
    result = agent.run("Use the professional tool to calculate NDVI for the supplied synthetic input.tif.", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert result.model_turns == 3
    observations = [json.loads(m.content) for m in result.state["messages"] if m.role == "tool"]
    assert len(observations) == 1 and observations[0]["name"] == "GeoRasterIndexAnalysis"
    assert observations[0]["status"] == "ok"
    with rasterio.open(tmp_path / "ndvi/values.tif") as image:
        np.testing.assert_allclose(image.read(1), .5, rtol=1e-6)
    assert raster.is_file()
    assert result.state["metadata"]["intent_selected_skill_ids"] == ids
    assert result.state["metadata"]["deferred_skill_ids"]


def test_one_shot_protocol_choice_is_consumed_before_scope_planning(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_OPTIMIZE_ROUND_TRIPS", "1")
    choices = []
    args = {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 1}
    class Model:
        def invoke(self, request):
            choices.append(request.tool_choice)
            if len(choices) <= 2:
                identity = "" if len(choices) == 1 else "distance"
                return ModelResponse(tool_calls=(ToolCall(identity, "GeoHaversineDistance", args),),
                                     finish_reason="tool_calls")
            assert len(choices) == 3
            return ModelResponse("The spherical distance is approximately 111.195 km.")
    result = create_agent(Model(), settings=Settings(verify_completion=False, max_model_turns=3)).run(
        "Calculate the distance from (0,0) to (0,1).",
        workspace=tmp_path, skill_id="geodesic_coordinate_analysis")
    assert result.status == "completed", result.reason
    assert choices == ["auto", "required", "auto"]
    observations = [json.loads(m.content) for m in result.state["messages"] if m.role == "tool"]
    assert len(observations) == 1
    assert observations[0]["call_id"] == "distance" and observations[0]["status"] == "ok"

from types import SimpleNamespace
import pytest
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import ModelResponse, ToolCall
from geological_agent.settings import Settings


def call(name, arguments, identity):
    return ModelResponse(tool_calls=(ToolCall(identity, name, arguments),), finish_reason="tool_calls")


def question(kind="missing_input"):
    return {"question": "Have you installed statistics packages?", "reason": "Need packages", "missing": ["statistics packages"],
            "options": [], "reason_type": kind, "supporting_call_ids": [], "approval_tool_names": []}


@pytest.fixture(autouse=True)
def enable(monkeypatch):
    monkeypatch.setenv("GEOTOOL_REQUIREMENT_COVERAGE", "1")
    monkeypatch.setenv("GEOTOOL_OPTIMIZE_ROUND_TRIPS", "1")


def test_wrong_missing_input_classification_cannot_bypass_review(tmp_path):
    responses = iter([
        call("request_user_input", question(), "h1"),
        call("assess_human_input", {"decision": "continue", "feedback": "Load the existing geodesic_coordinate_analysis skill; package installation is not user input."}, "r1"),
        call("skill_load", {"skill_id": "geodesic_coordinate_analysis"}, "s1"),
        call("GeoHaversineDistance", {"lat1": 39.9042, "lon1": 116.4074, "lat2": 31.2304, "lon2": 121.4737}, "d1"),
        ModelResponse("1067.31 km")])
    requests = []
    def invoke(request):
        requests.append(request); return next(responses)
    result = create_agent(SimpleNamespace(invoke=invoke), settings=Settings(verify_completion=False), human_input=True).run(
        "Calculate the distance from Beijing (39.9042,116.4074) to Shanghai (31.2304,121.4737).", workspace=tmp_path/"work", checkpoint_path=tmp_path/"checkpoints.sqlite")
    assert result.status == "completed" and result.model_turns == 5
    assert result.state["metadata"]["human_input_reviews"][0]["decision"] == "continue"
    assert "pending_input" not in result.state["metadata"]
    assert requests[1].tools[0].name == "assess_human_input"
    assert not any(t.name == "assess_human_input" for t in requests[2].tools)


def test_real_missing_objective_can_pause_and_has_paired_tool_result(tmp_path):
    args = question("missing_objective")
    args.update(question="What analysis do you want?", reason="Only coordinates supplied", missing=["objective"])
    responses = iter([call("request_user_input", args, "h1"), call("assess_human_input", {"decision": "ask", "feedback": "The desired analysis is missing."}, "r1")])
    result = create_agent(SimpleNamespace(invoke=lambda request: next(responses)), human_input=True).run(
        "Beijing: 39.9042, 116.4074", workspace=tmp_path/"work", checkpoint_path=tmp_path/"checkpoint.sqlite")
    assert result.status == "needs_input" and result.model_turns == 2
    assert any(m.role == "tool" and m.tool_call_id == "h1" for m in result.state["messages"])


def test_pause_review_obeys_existing_budget(tmp_path):
    responses = iter([call("request_user_input", question(), "h1")])
    result = create_agent(SimpleNamespace(invoke=lambda request: next(responses)), settings=Settings(max_model_turns=1), human_input=True).run(
        "Calculate a trend", workspace=tmp_path/"work", checkpoint_path=tmp_path/"checkpoint.sqlite")
    assert result.status == "budget_exhausted" and result.model_turns == 1
    assert "pending_input" not in result.state["metadata"]

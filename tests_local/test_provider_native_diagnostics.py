"""Offline regressions for native dispatch versus provider-hosted diagnostics."""
from dataclasses import asdict, replace
import json

import httpx
import pytest

from geological_agent.agent.completion import completion_evidence
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import Message, ModelRequest, ModelResponse, ToolCall
from geological_agent.langsmith_tracing import LangSmithTrace
from geological_agent.llm import LocalChatClient, native_response_diagnostic
from geological_agent.settings import Settings
from geological_agent.team.model_settings import ProbeTool, probe_model
from geological_agent.team.protocol import decode, encode
from geological_agent.tracing import JsonlTrace
from test_resource_recovery import Scripted, make_agent
from test_completion import review


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch):
    for key in ("GEOTOOL_INTENT_REVIEW", "GEOTOOL_REQUIREMENT_COVERAGE",
                "GEOTOOL_COMBINED_COMPLETION_REVIEW", "GEOTOOL_OPTIMIZE_ROUND_TRIPS",
                "GEOTOOL_COMPACT_REVIEW", "GEOTOOL_COMPACT_DISCOVERY",
                "GEOTOOL_REVIEW_REFERENCE_SETS", "GEOTOOL_WEB_ENABLED"):
        monkeypatch.delenv(key, raising=False)


def hosted():
    return {"id": "response-fixture", "model": "synthetic-model",
            "citations": ["https://example.org/source"],
            "server_side_tool_usage": {"SERVER_SIDE_TOOL_WEB_SEARCH": 8}}


def test_http_preserves_provider_reports_without_creating_calls():
    body = {**hosted(), "choices": [{"message": {"role": "assistant", "content": "Provider prose"},
                                    "finish_reason": "stop"}]}
    client = LocalChatClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    try:
        response = client.invoke(ModelRequest((Message("user", "Lookup"),), (ProbeTool(),), "required"))
    finally:
        client.close()
    assert response.tool_calls == ()
    assert response.provider_metadata == hosted()
    decoded = decode(encode(response))
    assert decoded.provider_metadata == hosted()
    assert isinstance(decoded.provider_metadata["citations"], list)
    diagnostic = native_response_diagnostic(decoded)
    assert diagnostic["kind"] == "provider_hosted_tools_without_native_calls"
    assert diagnostic["provider_execution_verified"] is False


def test_stream_retains_metadata_only_frames_and_original_counts():
    frames = [
        {"choices": [{"delta": {"content": "Result"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        {**hosted(), "choices": []},
        {"server_side_tool_usage": {"SERVER_SIDE_TOOL_WEB_SEARCH": 12}, "choices": []},
    ]
    text = "".join("data: " + json.dumps(frame) + "\n\n" for frame in frames) + "data: [DONE]\n\n"
    client = LocalChatClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text=text, headers={"content-type": "text/event-stream"})))
    try:
        response = list(client.stream(ModelRequest((Message("user", "Lookup"),), (ProbeTool(),))))[-1].response
    finally:
        client.close()
    assert not response.tool_calls and response.content == "Result"
    metadata = response.provider_metadata
    assert metadata["citations"] == hosted()["citations"]
    assert [e["server_side_tool_usage"]["SERVER_SIDE_TOOL_WEB_SEARCH"] for e in metadata["stream_events"]] == [8, 12]
    assert metadata["server_side_tool_usage"]["SERVER_SIDE_TOOL_WEB_SEARCH"] == 12


@pytest.mark.parametrize("metadata", [
    {"citations": ["https://example.org"]},
    {"server_side_tool_usage": {"search": 0}},
    {"server_side_tool_usage": {"search": True}},
    {"server_side_tool_usage": {"search": "8"}},
])
def test_citations_or_invalid_counts_do_not_prove_hosted_execution(metadata):
    assert native_response_diagnostic(ModelResponse("Text", provider_metadata=metadata))["kind"] == "missing_native_tool_calls"


def test_provider_metadata_does_not_replace_or_suppress_real_native_calls():
    response = ModelResponse(tool_calls=(ToolCall("native", "read_file", {"path": "a.txt"}),),
                             provider_metadata=hosted())
    diagnostic = native_response_diagnostic(response)
    assert diagnostic["native_tool_call_count"] == 1
    assert diagnostic["kind"] != "provider_hosted_tools_without_native_calls"
    assert decode(encode(response)).tool_calls[0].name == "read_file"


def test_provider_reports_are_diagnostics_not_completion_evidence():
    state = {"task": "Lookup", "messages": [Message("assistant", "Provider claims it searched.")],
             "artifacts": [], "metadata": {"provider_metadata": hosted()}}
    evidence = completion_evidence(state, None)
    assert evidence["observed_actions"] == []


def test_hosted_response_pauses_with_accurate_reason_and_zero_dispatch(tmp_path):
    model = Scripted(ModelResponse(""), ModelResponse("Provider found a record.", provider_metadata=hosted()))
    agent = create_agent(model, settings=Settings(verify_completion=False, max_model_turns=6), human_input=True)
    result = agent.run("Look up a source.", workspace=tmp_path/"work", checkpoint_path=tmp_path/"checkpoint.sqlite3")
    assert result.status == "needs_input", result.reason
    assert model.requests[-1].tool_choice == "required"
    assert not [m for m in result.state["messages"] if m.role == "tool"]
    pending = result.state["metadata"]["pending_input"]
    assert pending["reason_type"] == "model_protocol"
    assert "provider-hosted" in pending["question"]
    assert "No additional task data" in pending["question"]
    failure = result.state["metadata"]["protocol_failures"][-1]
    assert failure["diagnostic"]["kind"] == "provider_hosted_tools_without_native_calls"
    assert failure["response"]["provider_metadata"]["citations"] == hosted()["citations"]


@pytest.mark.parametrize("has_input", [False, True])
def test_execution_and_review_share_current_availability(tmp_path, has_input):
    if has_input:
        (tmp_path/"source.csv").write_text("dep_id,country\n42,Exampleland\n")
    seen = []
    def assess(request):
        payload = json.loads(request.messages[1].content)
        seen.append(payload)
        assert ("catalog_lookup" in payload["available_tool_names"]) is has_input
        assert {"web_search", "web_fetch"} <= set(payload["available_tool_names"])
        assert ("catalog_lookup" in payload["tool_availability"]["blocked_tools"]) is not has_input
        return review()
    model = Scripted(ModelResponse("Hello"), assess, ModelResponse("Hello"), assess)
    agent, _ = make_agent(model)
    agent.settings = replace(agent.settings, verify_completion=True)
    agent.context.settings = agent.settings
    result = agent.run("Say hello.", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert len(seen) == 2


def test_old_checkpoint_draft_is_labeled_and_kept_in_full(tmp_path):
    agent = create_agent(object())
    draft = "I searched and found a deposit. Unverified number: 123."
    state = {"task": "Lookup", "messages": [Message("user", "Lookup"), Message("assistant", draft)],
             "selected_skill_ids": [], "exposed_tool_names": list(agent.base_tools),
             "metadata": {"rejected_answers": [{"answer": draft, "feedback": "No observations"}]}}
    request = agent.context.build(state, defer_compaction=True)
    assert not any(m.role == "assistant" and m.content == draft for m in request.messages)
    data = [m for m in request.messages if "Unaccepted historical assistant draft" in m.content]
    assert len(data) == 1 and json.loads(data[0].content.split("\n", 1)[1])["text"] == draft
    assert state["messages"][1].content == draft


@pytest.mark.parametrize("reply", ["OK", "wrong-receipt"])
def test_probe_rejects_generic_text_instead_of_tool_receipt(reply):
    model = Scripted(ModelResponse(tool_calls=(ToolCall("probe", "connection_probe", {"ok": True}),)),
                     ModelResponse(reply))
    with pytest.raises(ValueError, match="receipt"):
        probe_model(model)
    result = json.loads(model.requests[1].messages[-2].content)
    assert len(result["receipt"]) == 32
    assert result["receipt"] not in model.requests[1].messages[-1].content


def test_trace_exports_complete_provider_metadata_with_credentials_masked(tmp_path):
    secret = "private-fixture-key"
    metadata = {**hosted(), "citations": ["https://example.org/?api_token=" + secret]}
    local = JsonlTrace(tmp_path/"trace.jsonl", secrets=(secret,))
    trace = LangSmithTrace(local, None, project="offline", capture_content=True, run_factory=lambda **kw: None)
    trace.root = object()
    captured = []
    trace._end = lambda key, outputs, error=None: captured.append(outputs)
    trace.emit("model_responded", turn=1, response=ModelResponse("Text", provider_metadata=metadata))
    assert captured[0]["provider_metadata"]["server_side_tool_usage"] == hosted()["server_side_tool_usage"]
    assert "[REDACTED]" in captured[0]["provider_metadata"]["citations"][0]
    assert secret not in json.dumps(captured)
    record = json.loads((tmp_path/"trace.jsonl").read_text())
    assert record["response"]["provider_metadata"] == captured[0]["provider_metadata"]


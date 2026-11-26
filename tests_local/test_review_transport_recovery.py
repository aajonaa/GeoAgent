"""Synthetic transport faults; no model service or scientific tool is invoked."""
from copy import deepcopy
from dataclasses import replace
import json
from threading import Event
from types import SimpleNamespace

import httpx
import pytest

from geological_agent.agent.semantic_recovery import review_sources
from geological_agent.contracts import ModelRequest, ModelResponse
from geological_agent.llm import LocalChatClient, ModelProtocolError
from geological_agent.model_context import native_context
from geological_agent.settings import Settings
from geological_agent.tools import ToolDefinition
from geological_agent.team.protocol import encode, decode
from geological_agent.team.streaming import RunProgress, consume_model_stream
from test_required_stream_transport import make_request, native_response, sse_response
from test_knowledge_semantics import state, GOOD, assessment, semantic_request


def sse(packet, *, event="", done=True):
    text = ("event: " + event + "\n" if event else "") + "data: " + json.dumps(packet) + "\n\n"
    return httpx.Response(200, text=text + ("data: [DONE]\n\n" if done else ""),
                          headers={"content-type": "text/event-stream", "x-request-id": "fixture-request"})


@pytest.mark.parametrize("as_event", [False, True])
def test_error_frame_is_not_discarded_and_credentials_are_masked(as_event):
    error = {"code": "invalid_schema", "message": "Invalid schema; Bearer private-fixture-key",
             "api_token": "another-fixture-token"}
    packet = error if as_event else {"error": error}
    client = LocalChatClient(api_key="private-fixture-key", required_streaming=True,
        transport=httpx.MockTransport(lambda _: sse(packet, event="error" if as_event else "")))
    with pytest.raises(ModelProtocolError, match="invalid_schema") as caught:
        list(client.stream(make_request()))
    diagnostic = caught.value.diagnostic
    assert diagnostic["kind"] == "provider_error"
    assert diagnostic["provider_request_id"] == "fixture-request"
    assert "invalid_schema" in json.dumps(diagnostic)
    assert "private-fixture-key" not in str(caught.value) + json.dumps(diagnostic)
    assert "another-fixture-token" not in str(caught.value) + json.dumps(diagnostic)
    client.close()


def test_incomplete_stream_records_received_frames_without_dispatch():
    client = LocalChatClient(required_streaming=True,
        transport=httpx.MockTransport(lambda _: sse_response(include_finish=False)))
    seen = []
    with pytest.raises(ModelProtocolError, match="finish reason") as caught:
        for event in client.stream(make_request()):
            seen.append(event)
    assert all(e.kind != "response" for e in seen)
    assert caught.value.diagnostic["kind"] == "stream_incomplete"
    assert caught.value.diagnostic["done_seen"] is True
    assert caught.value.diagnostic["partial_tool_calls"] == 1
    assert len(caught.value.diagnostic["frames"]) == 3
    client.close()


def test_multiline_sse_and_metadata_frames_preserve_response():
    packet = native_response()
    choice = packet["choices"][0]
    delta = {"choices": [{"delta": choice["message"], "finish_reason": choice["finish_reason"]}]}
    delta["choices"][0]["delta"]["tool_calls"][0]["index"] = 0
    content = ": keepalive\n\n" + "".join("data: " + line + "\n" for line in json.dumps(delta, indent=2).splitlines())
    content += '\n' + 'data: {"choices":[],"usage":{"total_tokens":120}}\n\ndata: [DONE]\n\n'
    client = LocalChatClient(required_streaming=True, transport=httpx.MockTransport(
        lambda _: httpx.Response(200, text=content, headers={"content-type": "text/event-stream"})))
    result = list(client.stream(make_request()))[-1].response
    assert result.tool_calls[0].id == "call_compute" and result.usage["total_tokens"] == 120
    client.close()


@pytest.mark.parametrize("stream", [False, True])
def test_json_error_response_keeps_provider_reason(stream):
    client = LocalChatClient(required_streaming=True, transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"error": {"code": "permission_denied", "message": "Not allowed"}})))
    with pytest.raises(ModelProtocolError, match="permission_denied") as caught:
        list(client.stream(make_request())) if stream else client.invoke(make_request())
    assert caught.value.diagnostic["kind"] == "provider_error"
    client.close()


def test_http_error_remains_http_error_with_safe_body():
    client = LocalChatClient(api_key="fixture-secret", transport=httpx.MockTransport(
        lambda _: httpx.Response(401, json={"error": {"message": "Bad fixture-secret"}})))
    with pytest.raises(httpx.HTTPStatusError) as caught:
        client.invoke(make_request())
    assert caught.value.diagnostic["kind"] == "http_error"
    assert "fixture-secret" not in json.dumps(caught.value.diagnostic)
    client.close()


def test_explicit_transport_survives_ipc_without_changing_native_contract():
    original = make_request()
    original = replace(original, tools=(ToolDefinition(**vars(original.tools[0]), result_schema={}),))
    request = replace(original, transport="full_response")
    restored = decode(encode(request))
    assert restored.transport == "full_response"
    assert native_context(restored) == native_context(original)
    sent = []
    client = LocalChatClient(required_streaming=True, transport=httpx.MockTransport(
        lambda r: (sent.append(json.loads(r.content)) or httpx.Response(200, json=native_response()))))
    events = list(client.stream(restored))
    assert len(sent) == 1 and sent[0]["stream"] is False
    assert "transport" not in sent[0] and events[-1].response.finish_reason == "tool_calls"
    client.close()


def test_progress_full_response_does_not_use_stream_and_diagnostics_are_recorded():
    events = []
    progress = RunProgress(events.append)
    progress.model_phase = "review"
    class Client:
        def stream(self, request):
            raise AssertionError("A full-response request must not stream")
        def invoke(self, request):
            raise ModelProtocolError("fixture", diagnostic={"kind": "provider_error", "code": "bad_schema"})
    with pytest.raises(ModelProtocolError):
        consume_model_stream(Client(), replace(make_request(), transport="full_response"),
                             progress, progress.begin_model(), Event())
    assert events[-2]["kind"] == "stream_end"
    assert events[-2]["transport"] == "full_response"
    assert events[-2]["diagnostic"]["code"] == "bad_schema"


def run_review(*, budget=4, full_kind="valid", stream_kind="incomplete", cancel=None):
    current = state(GOOD)
    current.update(run_id="synthetic-review", model_turns=0, status="running")
    current["metadata"]["usage"] = []
    original_evidence = deepcopy(current["metadata"]["knowledge"])
    req = semantic_request(current, Settings())
    args = assessment(req)
    if full_kind == "invalid_quote":
        args["checks"]["b1"]["source_quotes"][0]["quote"] = "invented quotation"
    complete = {"choices": [{"message": {"content": "", "tool_calls": [{
        "id": "native-review", "type": "function",
        "function": {"name": "assess_knowledge_semantics", "arguments": json.dumps(args)}}]},
        "finish_reason": "tool_calls"}], "usage": {"total_tokens": 100}}
    sent, traces, events = [], [], []
    cancel = cancel or Event()
    def http(request):
        body = json.loads(request.content); sent.append(body)
        if body["stream"]:
            if stream_kind == "provider_error":
                return sse({"error": {"code": "invalid_schema", "message": "Rejected request"}})
            return httpx.Response(200, text="data: [DONE]\n\n", headers={"content-type": "text/event-stream"})
        if full_kind == "incomplete":
            return httpx.Response(200, json={"choices": [{"message": {"content": "draft"}, "finish_reason": None}]})
        return httpx.Response(200, json=complete)
    client = LocalChatClient(required_streaming=True, transport=httpx.MockTransport(http))
    progress = RunProgress(events.append)
    class Trace:
        def emit(self, event, **fields):
            traces.append((event, fields))
            progress.observe(event, fields)
    class Model:
        def invoke(self, request):
            return consume_model_stream(client, request, progress, progress.begin_model(), cancel)
    try:
        result, issues = review_sources(current, settings=Settings(max_model_turns=budget),
            model=Model(), cancel=cancel, record=lambda *args: None, trace=Trace(),
            activity=lambda *args, **kwargs: None,
            pause=lambda s, phase, error: {**s, "status": "needs_input", "last_error": error})
    finally:
        client.close()
    assert result["metadata"]["knowledge"] == original_evidence
    return result, issues, sent, traces, events


def test_semantic_fallback_uses_next_budgeted_turn_and_same_exact_sources():
    result, issues, sent, traces, events = run_review()
    assert result["model_turns"] == 2 and not issues
    assert [r["stream"] for r in sent] == [True, False]
    assert sent[0]["messages"] == sent[1]["messages"]
    assert sent[0]["tools"] == sent[1]["tools"]
    assert result["metadata"]["knowledge_semantic_reviews"][-1]["passed"]
    assert any(k == "completion_review_recovery" and v["action"] == "retry_full_response" for k, v in traces)
    assert not any(e["kind"] == "stream_delta" for e in events)


def test_semantic_fallback_cannot_bypass_turn_budget():
    result, issues, sent, _, _ = run_review(budget=1)
    assert result["status"] == "budget_exhausted"
    assert result["answer"] == "" and len(sent) == 1
    assert result["metadata"]["semantic_pending_draft"]["answer"] == GOOD


def test_provider_rejection_is_not_blindly_retried():
    result, _, sent, _, _ = run_review(stream_kind="provider_error")
    assert result["status"] == "needs_input" and len(sent) == 1
    assert "invalid_schema" in result["last_error"]
    assert not result["metadata"].get("knowledge_semantic_reviews")


def test_failed_full_response_pauses_without_switching_back_to_stream():
    result, _, sent, _, _ = run_review(full_kind="incomplete")
    assert result["status"] == "needs_input"
    assert [r["stream"] for r in sent] == [True, False]
    assert result["metadata"]["semantic_pending_draft"]["answer"] == GOOD


def test_nonstream_recovery_still_rejects_fabricated_evidence():
    result, _, sent, _, _ = run_review(full_kind="invalid_quote")
    assert result["status"] == "needs_input"
    assert not result["metadata"].get("knowledge_semantic_reviews")
    assert all(not r["stream"] for r in sent[1:])


def test_cancelled_semantic_review_makes_no_request():
    cancel = Event(); cancel.set()
    result, _, sent, _, _ = run_review(cancel=cancel)
    assert result["status"] == "stopped" and sent == []

"""Native DeepSeek continuation and credential-safe transport regressions."""
from dataclasses import asdict
import json
from types import SimpleNamespace

import httpx
import pytest

from geological_agent.agent.compaction import request_size
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import Message, ModelRequest, ToolCall
from geological_agent.llm import LocalChatClient, ModelProtocolError
from geological_agent.model_context import native_context
from geological_agent.settings import Settings
from geological_agent.team.model_settings import (
    ModelProfile, ProbeTool, model_endpoint_error, profile_client, provider_error_details, probe_model,
)
from geological_agent.team.protocol import decode, encode


@pytest.fixture(autouse=True)
def isolated_flags(monkeypatch):
    for key in ("GEOTOOL_INTENT_REVIEW", "GEOTOOL_COMBINED_COMPLETION_REVIEW",
                "GEOTOOL_REQUIREMENT_COVERAGE", "GEOTOOL_OPTIMIZE_ROUND_TRIPS",
                "GEOTOOL_COMPACT_REVIEW", "GEOTOOL_COMPACT_DISCOVERY",
                "GEOTOOL_REVIEW_REFERENCE_SETS", "GEOTOOL_WEB_ENABLED"):
        monkeypatch.delenv(key, raising=False)


def response(*, reasoning=None, calls=None, content="", finish="tool_calls"):
    return {"choices": [{"message": {"role": "assistant", "content": content,
                                    "tool_calls": calls, "reasoning_content": reasoning},
                         "finish_reason": finish}]}


def wire_call(name="connection_probe", arguments='{"ok":true}', identifier="call_1"):
    return {"id": identifier, "type": "function",
            "function": {"name": name, "arguments": arguments}}


def request(choice="auto", messages=None):
    return ModelRequest(tuple(messages or [Message("user", "Call the exposed function.")]),
                        (ProbeTool(),), choice)


@pytest.mark.parametrize("choice,mode", [("required", "disabled"), ("auto", "enabled"), ("none", "enabled")])
def test_official_deepseek_uses_legal_thinking_and_native_choice(choice, mode):
    received = []
    def handle(req):
        received.append(json.loads(req.content))
        return httpx.Response(200, json=response(
            calls=[wire_call()] if choice != "none" else None,
            finish="tool_calls" if choice != "none" else "stop", content="OK"))
    client = LocalChatClient("https://api.deepseek.com/v1", "deepseek-v4-pro",
                            transport=httpx.MockTransport(handle))
    try:
        client.invoke(request(choice))
    finally:
        client.close()
    body = received[0]
    assert len(received) == 1
    assert body["thinking"] == {"type": mode}
    assert body["tool_choice"] == choice
    assert body["tools"][0]["function"]["name"] == "connection_probe"
    assert ("temperature" in body) is (mode == "disabled")


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000/v1", "https://x-api.cfd/v1",
                               "https://api.deepseek.com.example.org/v1"])
def test_other_providers_keep_their_original_wire_parameters(url):
    client = LocalChatClient(url, "other-model", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=response(calls=[wire_call()]))))
    try:
        body = client._body(request("required"))
    finally:
        client.close()
    assert "thinking" not in body and body["temperature"] == 0
    assert body["tool_choice"] == "required"
    assert all("reasoning_content" not in m for m in body["messages"])


def test_nonstream_reasoning_and_native_call_round_trip_are_lossless():
    thought = "Inspect actual observations. " + "\u5730\u8d28" * 100
    sent = []
    def handle(req):
        sent.append(json.loads(req.content))
        return httpx.Response(200, json=response(reasoning=thought, calls=[wire_call()]))
    client = LocalChatClient("https://api.deepseek.com/v1", "deepseek-v4-pro",
                             transport=httpx.MockTransport(handle))
    try:
        reply = client.invoke(request())
        restored = decode(encode(reply))
        assert restored.reasoning_content == thought
        call = restored.tool_calls[0]
        history = [Message("user", "Call the exposed function."),
                   Message("assistant", restored.content, restored.tool_calls,
                           reasoning_content=restored.reasoning_content),
                   Message("tool", '{"ok":true}', tool_call_id=call.id)]
        client.invoke(request(messages=history))
    finally:
        client.close()
    assert sent[1]["messages"][1]["reasoning_content"] == thought
    assert sent[1]["messages"][1]["tool_calls"][0] == wire_call()
    assert sent[1]["messages"][2]["tool_call_id"] == "call_1"
    assert request_size(request(messages=history)) > request_size(request(
        messages=[history[0], Message("assistant", "", restored.tool_calls), history[2]]))


def test_stream_assembles_reasoning_without_publishing_it_as_answer_tokens():
    frames = [
        {"choices": [{"delta": {"reasoning_content": "Inspect "}, "finish_reason": None}]},
        {"choices": [{"delta": {"reasoning_content": "the data."}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "Working.", "tool_calls": None}, "finish_reason": None}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, **wire_call()}]}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ]
    sse = "".join("data: " + json.dumps(frame) + "\n\n" for frame in frames) + "data: [DONE]\n\n"
    client = LocalChatClient("https://api.deepseek.com/v1", "deepseek-v4-pro",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=sse)))
    try:
        events = list(client.stream(request()))
    finally:
        client.close()
    assert [event.kind for event in events] == ["text_delta", "response"]
    assert events[0].text == "Working."
    assert events[-1].response.reasoning_content == "Inspect the data."
    assert events[-1].response.tool_calls[0].id == "call_1"


@pytest.mark.parametrize("bad", [[], {}, 7, True])
def test_invalid_reasoning_is_rejected_before_any_dispatch(bad):
    with pytest.raises(ModelProtocolError, match="reasoning_content"):
        LocalChatClient._response({"reasoning_content": bad}, "stop")


def test_null_calls_are_a_valid_text_response_not_a_protocol_error():
    reply = LocalChatClient._response({"content": "Answer.", "tool_calls": None,
                                      "reasoning_content": None}, "stop")
    assert reply.content == "Answer." and reply.tool_calls == ()
    assert reply.reasoning_content is None


def test_old_ipc_messages_remain_readable_and_new_reasoning_is_preserved():
    old = {"_type": "Message", "fields": {"role": "assistant", "content": "Historical."}}
    assert decode(old).reasoning_content is None
    new = Message("assistant", "", (ToolCall("c", "x", "{}"),), reasoning_content="Exact thought.")
    decoded = decode(encode(new))
    assert json.loads(json.dumps(asdict(decoded))) == json.loads(json.dumps(asdict(new)))
    assert native_context(request(messages=[decoded])) == native_context(request(messages=[new]))
    with pytest.raises(ValueError, match="assistant"):
        native_context(request(messages=[Message("user", "Question", reasoning_content="Bad role")]))


def test_probe_is_nonthinking_but_still_checks_the_exact_native_receipt():
    bodies = []
    def handle(req):
        body = json.loads(req.content)
        bodies.append(body)
        if len(bodies) == 1:
            return httpx.Response(200, json=response(calls=[wire_call()]))
        receipt = json.loads(body["messages"][-2]["content"])["receipt"]
        return httpx.Response(200, json=response(content=receipt, finish="stop"))
    policy = SimpleNamespace(transport=lambda _: httpx.MockTransport(handle))
    client = profile_client(ModelProfile("custom", "https://api.deepseek.com/v1", "deepseek-v4-pro"),
                            policy, probe=True)
    try:
        result = probe_model(client)
    finally:
        client.close()
    assert result["ok"] is True and len(bodies) == 2
    assert [body["tool_choice"] for body in bodies] == ["required", "auto"]
    assert all(body["thinking"] == {"type": "disabled"} for body in bodies)
    assert bodies[1]["messages"][1]["reasoning_content"] == ""


def test_runtime_keeps_reasoning_between_actual_tool_execution_and_next_call(tmp_path):
    (tmp_path / "input.txt").write_text("Original observation.", encoding="utf-8")
    bodies = []
    thought = "I must read the supplied file before answering."
    def handle(req):
        body = json.loads(req.content)
        bodies.append(body)
        if len(bodies) == 1:
            return httpx.Response(200, json=response(reasoning=thought,
                calls=[wire_call("read_file", '{"path":"input.txt"}')]))
        assistant = next(m for m in body["messages"] if m.get("tool_calls"))
        assert assistant["reasoning_content"] == thought
        assert any(m["role"] == "tool" and m["tool_call_id"] == "call_1" for m in body["messages"])
        return httpx.Response(200, json=response(reasoning="The file has been observed.",
                                                content="Original observation.", finish="stop"))
    client = LocalChatClient("https://api.deepseek.com/v1", "deepseek-v4-pro",
                             transport=httpx.MockTransport(handle))
    try:
        agent = create_agent(client, settings=Settings(verify_completion=False, max_model_turns=3))
        result = agent.run("Read input.txt and report its text.", workspace=tmp_path)
    finally:
        client.close()
    assert result.status == "completed", result.reason
    assert result.answer == "Original observation."
    assert len(bodies) == 2
    assert next(m for m in result.state["messages"] if m.tool_calls).reasoning_content == thought


def test_upstream_errors_expose_useful_fields_but_not_credentials_or_raw_bodies():
    secret = "fixture-private-key"
    req = httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions",
                       headers={"Authorization": "Bearer " + secret})
    reply = httpx.Response(400, request=req, json={"error": {
        "message": "tool_choice=required is unsupported in thinking mode; " + secret +
                   " Bearer another-secret",
        "type": "invalid_request_error", "param": "tool_choice", "code": "invalid_parameter",
        "api_token": "hidden-secret", "request_headers": {"Authorization": secret},
    }, "request": {"messages": ["Never expose the whole request"]}})
    exc = httpx.HTTPStatusError("bad request", request=req, response=reply)
    safe = provider_error_details(exc, (secret,))
    assert safe["http_status"] == 400 and safe["param"] == "tool_choice"
    assert "thinking mode" in safe["message"] and "[REDACTED]" in safe["message"]
    published = json.dumps(safe) + model_endpoint_error(exc, (secret,))
    for value in (secret, "another-secret", "hidden-secret", "Never expose the whole request", "request_headers"):
        assert value not in published
    assert "Model endpoint request failed (400)" in published


def test_non_json_provider_errors_do_not_expose_html_or_headers():
    req = httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions")
    reply = httpx.Response(502, request=req, text="<html>private gateway diagnostics</html>")
    exc = httpx.HTTPStatusError("gateway", request=req, response=reply)
    safe = provider_error_details(exc)
    assert safe == {"error": "HTTPStatusError", "http_status": 502}
    assert "private gateway diagnostics" not in model_endpoint_error(exc)

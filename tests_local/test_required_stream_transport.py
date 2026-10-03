import json
from types import SimpleNamespace

import httpx
import pytest

from geological_agent.contracts import Message, ModelRequest
from geological_agent.llm import LocalChatClient, ModelProtocolError


CODE = "def value():\n    return 55\nprint(value())"
ARGUMENTS = json.dumps({"code": CODE})


def make_request(choice="required", with_tools=True):
    tool = SimpleNamespace(
        name="execute_python",
        description="Execute valid Python source.",
        when_to_use="A task requires actual computation.",
        input_schema={
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
            "additionalProperties": False,
        },
    )
    return ModelRequest(
        (Message("user", "Calculate the requested value using Python."),),
        (tool,) if with_tools else (),
        tool_choice=choice,
    )


def native_response(reason="tool_calls"):
    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_compute",
                    "type": "function",
                    "function": {"name": "execute_python", "arguments": ARGUMENTS},
                }],
            },
            "finish_reason": reason,
        }],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


@pytest.fixture
def http_client():
    clients = []

    def factory(responder):
        requests = []

        def handle(request):
            requests.append(json.loads(request.content))
            assert request.url.path == "/v1/chat/completions"
            return responder(request)

        client = LocalChatClient(transport=httpx.MockTransport(handle))
        clients.append(client)
        return client, requests

    yield factory
    for client in clients:
        client.close()


def test_required_stream_uses_one_complete_native_request(http_client):
    client, requests = http_client(lambda _: httpx.Response(200, json=native_response()))
    request = make_request()
    events = list(client.stream(request))

    assert len(requests) == 1
    assert requests[0]["stream"] is False
    assert requests[0]["tool_choice"] == "required"
    assert requests[0]["tools"][0]["function"]["parameters"] == request.tools[0].input_schema
    assert "response_format" not in requests[0]
    assert [event.kind for event in events] == ["response"]
    response = events[0].response
    assert response.finish_reason == "tool_calls"
    assert response.usage["total_tokens"] == 120
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "call_compute"
    assert response.tool_calls[0].name == "execute_python"
    assert response.tool_calls[0].arguments == ARGUMENTS
    assert json.loads(response.tool_calls[0].arguments)["code"] == CODE


@pytest.mark.parametrize("reason", [None, "", "missing"])
def test_required_still_rejects_missing_completion_boundary(http_client, reason):
    data = native_response(reason)
    if reason == "missing":
        del data["choices"][0]["finish_reason"]
    client, requests = http_client(lambda _: httpx.Response(200, json=data))
    with pytest.raises(ModelProtocolError):
        list(client.stream(make_request()))
    assert len(requests) == 1


def test_required_preserves_truncation_for_runtime_rejection(http_client):
    client, requests = http_client(lambda _: httpx.Response(200, json=native_response("length")))
    events = list(client.stream(make_request()))
    assert events[0].response.finish_reason == "length"
    assert len(requests) == 1


def test_required_http_error_is_not_hidden_or_retried(http_client):
    client, requests = http_client(lambda _: httpx.Response(503, json={"error": "unavailable"}))
    with pytest.raises(httpx.HTTPStatusError):
        list(client.stream(make_request()))
    assert len(requests) == 1


def test_required_timeout_is_not_hidden_or_retried(http_client):
    def timeout(request):
        raise httpx.ReadTimeout("diagnostic timeout", request=request)

    client, requests = http_client(timeout)
    with pytest.raises(httpx.ReadTimeout):
        list(client.stream(make_request()))
    assert len(requests) == 1


def test_required_without_tools_fails_before_http(http_client):
    client, requests = http_client(lambda _: httpx.Response(200, json=native_response()))
    with pytest.raises(ValueError, match="exposed tools"):
        list(client.stream(make_request(with_tools=False)))
    assert requests == []


def sse_response(include_finish=True):
    chunks = [
        {"choices": [{"delta": {"content": "Working."}, "finish_reason": None}]},
        {"choices": [{"delta": {"tool_calls": [{
            "index": 0, "id": "call_compute", "type": "function",
            "function": {"name": "execute_python", "arguments": ARGUMENTS[:12]},
        }]}, "finish_reason": None}]},
        {"choices": [{"delta": {"tool_calls": [{
            "index": 0, "function": {"arguments": ARGUMENTS[12:]},
        }]}, "finish_reason": None}]},
    ]
    if include_finish:
        chunks.append({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]})
    content = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
    return httpx.Response(200, text=content + "data: [DONE]\n\n",
                          headers={"content-type": "text/event-stream"})


def test_auto_retains_actual_streaming_and_tool_assembly(http_client):
    client, requests = http_client(lambda _: sse_response())
    events = list(client.stream(make_request("auto")))
    assert len(requests) == 1
    assert requests[0]["stream"] is True
    assert requests[0]["tool_choice"] == "auto"
    assert [event.kind for event in events] == ["text_delta", "response"]
    assert events[0].text == "Working."
    assert events[1].response.tool_calls[0].arguments == ARGUMENTS
    assert events[1].response.finish_reason == "tool_calls"


def test_auto_incomplete_stream_does_not_publish_a_call_or_retry(http_client):
    client, requests = http_client(lambda _: sse_response(include_finish=False))
    events = []
    with pytest.raises(ModelProtocolError, match="finish reason"):
        for event in client.stream(make_request("auto")):
            events.append(event)
    assert len(requests) == 1
    assert all(event.kind != "response" for event in events)

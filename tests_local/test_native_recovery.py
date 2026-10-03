import json
from dataclasses import replace

import httpx
import pytest

from geological_agent.bootstrap import create_agent as _create_agent
from geological_agent.contracts import Message, ModelRequest
from geological_agent.llm import LocalChatClient
from geological_agent.settings import Settings


def create_agent(model, **kwargs):
    # Isolate native empty-response recovery; production completion gates have
    # their own default-enabled tests in test_completion.py.
    kwargs["settings"] = replace(kwargs.get("settings") or Settings(), verify_completion=False)
    return _create_agent(model, **kwargs)


def tool(name, arguments, call_id="native1"):
    return {"content": "", "tool_calls": [{"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}]}


def model(replies, stream=False):
    bodies = []
    replies = iter(replies)
    def handle(request):
        body = json.loads(request.content)
        bodies.append(body)
        message = next(replies)
        if not body["stream"]:
            return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": "stop"}], "usage": {"completion_tokens": 1}})
        chunks = []
        for i, call in enumerate(message.get("tool_calls", [])):
            chunks.append({"choices": [{"delta": {"tool_calls": [{"index": i, **call}]}, "finish_reason": None}]})
        for char in message.get("content", ""):
            chunks.append({"choices": [{"delta": {"content": char}, "finish_reason": None}]})
        chunks.append({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"completion_tokens": 1}})
        text = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, content=text.encode(), headers={"Content-Type": "text/event-stream"})
    return LocalChatClient("http://model/v1", "test", transport=httpx.MockTransport(handle)), bodies


@pytest.mark.parametrize("stream", [False, True])
def test_empty_response_native_recovery_then_auto(tmp_path, stream):
    (tmp_path / "sample.txt").write_text("Observed value: 42", encoding="utf-8")
    client, bodies = model([{"content": ""}, tool("read_file", {"path": "sample.txt"}), {"content": "The observed value is 42."}], stream)
    text = []
    try:
        result = create_agent(client).run("Inspect sample.txt", workspace=tmp_path, on_text=text.append if stream else None)
    finally:
        client.close()
    assert result.status == "completed" and result.model_turns == 3
    assert result.answer == "The observed value is 42."
    assert [body["tool_choice"] for body in bodies] == ["auto", "required", "auto"]
    assert [body["stream"] for body in bodies] == [stream, False, stream]
    assert all("guided_json" not in body and "response_format" not in body for body in bodies)
    assert bodies[0]["tools"] == bodies[1]["tools"] == bodies[2]["tools"]
    observations = [json.loads(m.content) for m in result.state["messages"] if m.role == "tool"]
    assert len(observations) == 1 and observations[0]["status"] == "ok"
    assert "Observed value: 42" in json.dumps(observations)
    assert len(result.state["metadata"]["usage"]) == 3
    assert "next_tool_choice" not in result.state["metadata"]
    if stream:
        assert "".join(text) == result.answer


@pytest.mark.parametrize("ignored", ["", "I will read the file."])
def test_ignored_required_is_not_completion_or_endless_retry(tmp_path, ignored):
    client, bodies = model([{"content": ""}, {"content": ignored}])
    try:
        result = create_agent(client).run("Inspect local files", workspace=tmp_path)
    finally:
        client.close()
    assert result.status == "incomplete" and result.model_turns == 2
    assert "did not honor" in result.reason and not result.answer
    assert len(bodies) == 2 and not result.artifacts
    assert not [m for m in result.state["messages"] if m.role == "tool"]


def test_normal_answer_does_not_force_tools(tmp_path):
    client, bodies = model([{"content": "Hello."}])
    try:
        result = create_agent(client).run("Say hello", workspace=tmp_path)
    finally:
        client.close()
    assert result.status == "completed" and len(bodies) == 1
    assert bodies[0]["tool_choice"] == "auto"


def test_recovery_respects_model_turn_budget(tmp_path):
    client, bodies = model([{"content": ""}])
    try:
        result = create_agent(client, settings=Settings(max_model_turns=1)).run("Inspect files", workspace=tmp_path)
    finally:
        client.close()
    assert result.status == "budget_exhausted" and len(bodies) == 1
    assert result.model_turns == 1 and not result.artifacts


def test_recovery_after_an_observation_can_continue_actual_work(tmp_path):
    (tmp_path / "sample.txt").write_text("42")
    replies = [{"content": ""}, tool("read_file", {"path": "sample.txt"}, "r1"), {"content": ""},
               tool("write_file", {"path": "answer.txt", "content": "42"}, "w1"), {"content": "Created answer.txt."}]
    client, bodies = model(replies)
    try:
        result = create_agent(client).run("Read sample.txt and create answer.txt", workspace=tmp_path)
    finally:
        client.close()
    assert result.status == "completed" and (tmp_path / "answer.txt").read_text() == "42"
    assert [b["tool_choice"] for b in bodies] == ["auto", "required", "auto", "required", "auto"]


def test_plain_json_is_never_reinterpreted_as_tool_call(tmp_path):
    prose = json.dumps({"name": "write_file", "arguments": {"path": "not-created.txt", "content": "x"}})
    client, bodies = model([{"content": prose}])
    try:
        result = create_agent(client).run("Explain this JSON example", workspace=tmp_path)
    finally:
        client.close()
    assert result.answer == prose and len(bodies) == 1
    assert not (tmp_path / "not-created.txt").exists()


def test_recovery_choice_does_not_leak_into_next_run(tmp_path):
    client, bodies = model([{"content": ""}, tool("write_file", {"path": "x.txt", "content": "x"}), {"content": "Created x.txt."}, {"content": "Hello."}])
    agent = create_agent(client)
    try:
        first = agent.run("Create x.txt", workspace=tmp_path / "one")
        second = agent.run("Say hello", workspace=tmp_path / "two")
    finally:
        client.close()
    assert first.status == second.status == "completed"
    assert bodies[-1]["tool_choice"] == "auto" and second.model_turns == 1
    assert not second.artifacts


def test_required_without_tools_is_rejected_before_http():
    client, bodies = model([])
    try:
        with pytest.raises(ValueError, match="needs exposed tools"):
            client.invoke(ModelRequest((Message("user", "Hello"),), (), tool_choice="required"))
    finally:
        client.close()
    assert not bodies

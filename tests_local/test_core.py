from dataclasses import asdict, replace
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from threading import Event, Timer
import httpx
import pytest
from geological_agent.bootstrap import create_agent as _create_agent
from geological_agent.contracts import Message, ModelEvent, ModelRequest, ModelResponse, ToolCall, strict_json
from geological_agent.llm import LocalChatClient, ModelProtocolError
from geological_agent.memory import NullMemoryStore
from geological_agent.knowledge import NullKnowledgeRetriever, NullKnowledgeStore
from geological_agent.settings import Settings
from geological_agent.tools import Tool, ToolDefinition, ToolExecutionContext, ToolExecutor, ToolOutput, object_schema
from geological_agent.tracing import JsonlTrace


def create_agent(model, **kwargs):
    # These are component tests with scripted actor replies. Completion review
    # is covered separately with the production default in test_completion.py.
    kwargs["settings"] = replace(kwargs.get("settings") or Settings(), verify_completion=False)
    return _create_agent(model, **kwargs)


class Scripted:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return item(request) if callable(item) else item

    def stream(self, request):
        response = self.invoke(request)
        yield ModelEvent("text_delta", response.content)
        yield ModelEvent("response", response=response)


def call(name, arguments, id="call_1"):
    return ModelResponse(tool_calls=(ToolCall(id, name, arguments),), finish_reason="tool_calls")


def results(result):
    return [strict_json(m.content) for m in result.state["messages"] if m.role == "tool"]


def test_final_answer_no_forced_tool(tmp_path):
    model = Scripted(ModelResponse("Hello"))
    result = create_agent(model).run("Say hello", workspace=tmp_path)
    assert result.status == "completed" and result.answer == "Hello"
    assert not results(result)
    assert "GeoMagnitudeToEnergy" not in [t.name for t in model.requests[0].tools]


def test_progressive_skill_disclosure_and_native_science(tmp_path):
    model = Scripted(call("skill_find", {"query": "earthquake"}),
        call("skill_load", {"skill_id": "earthquake_energy"}, "c2"),
        call("GeoMagnitudeToEnergy", {"mw": 6.5}, "c3"), ModelResponse("Computed energy."))
    result = create_agent(model).run("Estimate Mw 6.5 energy", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert "GeoMagnitudeToEnergy" not in [t.name for t in model.requests[1].tools]
    assert "GeoMagnitudeToEnergy" in [t.name for t in model.requests[2].tools]
    assert math.isclose(results(result)[-1]["data"]["energy_j"], 10 ** 14.55, rel_tol=1e-12)
    assert result.state["selected_skill_ids"] == ["earthquake_energy"]


def test_exposure_enforced_then_repair(tmp_path):
    model = Scripted(call("GeoMagnitudeToEnergy", {"mw": 6.5}),
        call("skill_load", {"skill_id": "earthquake_energy"}, "c2"),
        call("GeoMagnitudeToEnergy", {"mw": 6.5}, "c3"), ModelResponse("Done"))
    result = create_agent(model).run("Energy", workspace=tmp_path)
    assert results(result)[0]["error"]["code"] == "tool_not_exposed"
    assert results(result)[-1]["status"] == "ok"


@pytest.mark.parametrize("bad", [{"mw": "six"}, {"mw": 6.5, "bogus": 1}, '{"mw":6.5,"mw":7}', '{"mw":NaN}', '{"mw":'])
def test_argument_errors_become_observations(tmp_path, bad):
    model = Scripted(call("GeoMagnitudeToEnergy", bad), call("GeoMagnitudeToEnergy", {"mw": 6.5}, "c2"), ModelResponse("Done"))
    result = create_agent(model).run("Energy", workspace=tmp_path, skill_id="earthquake_energy")
    assert result.status == "completed"
    assert results(result)[0]["error"]["code"] == "invalid_arguments"
    assert results(result)[1]["status"] == "ok"


def test_python_error_then_actual_repair(tmp_path):
    model = Scripted(call("execute_python", {"code": "print(1 / 0)"}),
        call("execute_python", {"code": "from pathlib import Path\nassert sum(range(1,101)) == 5050\nPath('answer.txt').write_text('5050')\nprint(5050)"}, "c2"),
        ModelResponse("The sum is 5050."))
    result = create_agent(model).run("Calculate a sum", workspace=tmp_path)
    assert result.status == "completed", result.reason
    observed = results(result)
    assert observed[0]["status"] == "error" and "ZeroDivisionError" in observed[0]["data"]["stderr"]
    assert observed[1]["data"]["stdout"].strip() == "5050"
    assert (tmp_path / "answer.txt").read_text() == "5050"
    assert [a.path for a in result.artifacts] == ["answer.txt"]


def test_fresh_run_does_not_inherit_hello_validation(tmp_path):
    model = Scripted(call("write_file", {"path": "hello.txt", "content": "old task"}), ModelResponse("Saved"),
                     call("execute_python", {"code": "print(sum(range(1,101)))"}, "new"), ModelResponse("5050"))
    agent = create_agent(model)
    first = agent.run("Write hello.txt", workspace=tmp_path)
    second = agent.run("Calculate 1 through 100; independent task", workspace=tmp_path)
    assert first.run_id != second.run_id
    assert second.model_turns == 2 and second.status == "completed"
    assert second.state["selected_skill_ids"] == [] and not second.artifacts
    assert not any("hello.txt" in m.content for m in model.requests[2].messages)
    assert (tmp_path / "hello.txt").read_text() == "old task"


def test_file_edit_requires_current_hash(tmp_path):
    (tmp_path / "note.txt").write_text("before")
    digest = hashlib.sha256(b"before").hexdigest()
    model = Scripted(call("write_file", {"path": "note.txt", "content": "after"}),
        call("read_file", {"path": "note.txt"}, "c2"),
        call("write_file", {"path": "note.txt", "content": "after", "expected_sha256": digest}, "c3"), ModelResponse("Edited"))
    result = create_agent(model).run("Edit note", workspace=tmp_path)
    assert results(result)[0]["error"]["code"] == "overwrite_requires_hash"
    assert results(result)[1]["data"]["sha256"] == digest
    assert (tmp_path / "note.txt").read_text() == "after"


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", "C:/secret.txt", "..\\outside.txt"])
def test_file_path_boundaries(tmp_path, path):
    model = Scripted(call("write_file", {"path": path, "content": "x"}), ModelResponse("Cannot write that path"))
    result = create_agent(model).run("Write", workspace=tmp_path)
    assert results(result)[0]["error"]["code"] == "invalid_path"


def test_budget_is_not_reported_as_completion(tmp_path):
    model = Scripted(call("read_file", {"path": "missing.txt"}))
    result = create_agent(model, settings=Settings(max_model_turns=1)).run("Read", workspace=tmp_path)
    assert result.status == "budget_exhausted" and not result.answer
    assert result.model_turns == 1


def test_timeout_is_observation_and_no_blind_replay(tmp_path):
    model = Scripted(call("execute_python", {"code": "import time; time.sleep(10)"}), ModelResponse("The calculation timed out."))
    result = create_agent(model, settings=Settings(tool_timeout_seconds=0.2)).run("Compute", workspace=tmp_path)
    assert result.status == "completed"
    assert len(results(result)) == 1
    assert results(result)[0]["status"] == "timeout"
    assert results(result)[0]["error"]["outcome_unknown"]


def test_cancellation_terminates_child(tmp_path):
    from threading import Thread

    stopped = Event()
    monitor_done = Event()
    child_started = tmp_path / "child.started"
    model = Scripted(call("execute_python", {"code":
        "import time\nfrom pathlib import Path\nPath('child.started').write_text('started')\ntime.sleep(15)"}))
    agent = create_agent(model)

    def cancel_started_child():
        while not monitor_done.wait(0.01):
            if child_started.exists():
                stopped.set()
                return

    monitor = Thread(target=cancel_started_child, daemon=True)
    monitor.start()
    try:
        result = agent.run("Wait", workspace=tmp_path, cancel_event=stopped)
    finally:
        monitor_done.set()
        monitor.join(timeout=2)
    assert child_started.is_file() and stopped.is_set()
    assert not monitor.is_alive()
    assert result.status == "stopped"
    assert result.state["metadata"]["elapsed_seconds"] < 8
    assert len(results(result)) == 1
    assert results(result)[0]["status"] == "cancelled"


def test_pure_cache_does_not_cache_python(tmp_path):
    model = Scripted(call("GeoMagnitudeToEnergy", {"mw": 6.5}), call("GeoMagnitudeToEnergy", {"mw": 6.5}, "c2"),
                     call("execute_python", {"code": "print('x')"}, "c3"), call("execute_python", {"code": "print('x')"}, "c4"), ModelResponse("Done"))
    result = create_agent(model).run("Compute", workspace=tmp_path, skill_id="earthquake_energy")
    assert [r["cached"] for r in results(result)] == [False, True, False, False]
    assert results(result)[2]["data"]["code_path"] != results(result)[3]["data"]["code_path"]


def test_invalid_output_schema_is_not_success(tmp_path):
    agent = create_agent(Scripted())
    definition = ToolDefinition("broken", "Broken", "Test", object_schema({}), object_schema({"value": {"type": "number"}}, ["value"]))
    agent.tools.register(Tool(definition, lambda a, c: ToolOutput({"value": "wrong"})))
    ctx = ToolExecutionContext("test", tmp_path, ("broken",), Settings(), Event())
    result = ToolExecutor(agent.tools).execute(ToolCall("x", "broken", {}), ctx)
    assert result.status == "error" and result.error.code == "invalid_result"


def test_unknown_tool_recoverable(tmp_path):
    model = Scripted(call("made_up", {}), ModelResponse("Tool not available"))
    result = create_agent(model).run("Query", workspace=tmp_path)
    assert results(result)[0]["error"]["code"] == "unknown_tool"


def test_truncated_model_call_not_executed(tmp_path):
    truncated = ModelResponse(tool_calls=(ToolCall("c1", "write_file", {"path": "bad.txt", "content": "bad"}),), finish_reason="length")
    result = create_agent(Scripted(truncated, ModelResponse("Try a smaller response"))).run("Write", workspace=tmp_path)
    assert result.status == "incomplete" and result.answer == ""
    assert not (tmp_path / "bad.txt").exists()
    assert not results(result) and not result.artifacts
    assert result.model_turns == 2
    assert len(result.state["metadata"]["protocol_failures"]) == 2


def test_duplicate_call_ids_are_rejected(tmp_path):
    repeated = ModelResponse(tool_calls=(ToolCall("same", "read_file", {"path": "x"}), ToolCall("same", "read_file", {"path": "y"})))
    result = create_agent(Scripted(repeated, ModelResponse("Corrected"))).run("Read", workspace=tmp_path)
    assert not results(result) and result.model_turns == 2


def test_context_prunes_complete_groups_not_state(tmp_path):
    agent = create_agent(Scripted(), settings=Settings(max_context_chars=9000))
    messages = [Message("user", "Current task")]
    for i in range(5):
        messages += [Message("assistant", tool_calls=(ToolCall(str(i), "read_file", {"path": "x"}),)), Message("tool", "x" * 2500, tool_call_id=str(i))]
    state = {"task": "Current task", "selected_skill_ids": [], "exposed_tool_names": ["read_file"], "messages": messages}
    request = agent.context.build(state)
    assert len(state["messages"]) == 11
    assert len(request.messages) < len(messages)
    ids = {c.id for m in request.messages for c in m.tool_calls}
    assert ids == {m.tool_call_id for m in request.messages if m.role == "tool"}
    assert "4" in ids and any(m.content == "Current task" for m in request.messages)


def test_context_overflow_does_not_fake_completion(tmp_path):
    result = create_agent(Scripted(), settings=Settings(max_context_chars=100)).run("A task", workspace=tmp_path)
    assert result.status == "failed" and "ContextOverflow" in result.reason


def test_null_boundaries_and_trace_redaction(tmp_path):
    assert NullMemoryStore().search("x", limit=3) == ()
    assert NullKnowledgeRetriever().search("x", limit=3) == ()
    assert NullKnowledgeStore().get("x") is None
    trace = JsonlTrace(tmp_path / "trace.jsonl", secrets=("credential123",))
    trace.emit("example", api_key="credential123", output="hide credential123")
    record = (tmp_path / "trace.jsonl").read_text()
    assert "credential123" not in record and "[REDACTED]" in record


def test_python_removes_secret_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_MODEL_KEY", "should-not-leak")
    result = create_agent(Scripted(call("execute_python", {"code": "import os; print(os.environ.get('GEOTOOL_MODEL_KEY', 'absent'))"}), ModelResponse("Done"))).run("Inspect", workspace=tmp_path)
    assert results(result)[0]["data"]["stdout"].strip() == "absent"


def test_stream_is_single_model_invocation(tmp_path):
    model = Scripted(ModelResponse("Hello"))
    chunks = []
    result = create_agent(model).run("Greet", workspace=tmp_path, on_text=chunks.append)
    assert result.status == "completed" and chunks == ["Hello"] and len(model.requests) == 1


def test_http_adapter_native_calls_and_tool_messages():
    received = []
    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": [{"id": "c1", "function": {"name": "read_file", "arguments": '{"path":"x"}'}}]}, "finish_reason": "tool_calls"}]})
    client = LocalChatClient(transport=httpx.MockTransport(handler))
    try:
        result = client.invoke(ModelRequest((Message("user", "Read"),), ()))
        assert result.tool_calls[0].name == "read_file"
        assert received[0]["messages"][0]["content"] == "Read"
    finally:
        client.close()


def test_http_stream_assembles_arguments_before_dispatch():
    events = [
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "read_file", "arguments": '{"path":'}}]}, "finish_reason": None}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"x"}'}}]}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ]
    content = "".join("data: " + json.dumps(event) + "\n\n" for event in events) + "data: [DONE]\n\n"
    client = LocalChatClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=content)))
    try:
        received = list(client.stream(ModelRequest((Message("user", "Read"),), ())))
        assert len(received) == 1 and received[0].kind == "response"
        assert strict_json(received[0].response.tool_calls[0].arguments) == {"path": "x"}
    finally:
        client.close()


def test_incomplete_stream_does_not_dispatch():
    client = LocalChatClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')))
    try:
        with pytest.raises(ModelProtocolError):
            list(client.stream(ModelRequest((Message("user", "Read"),), ())))
    finally:
        client.close()


def test_actual_csv_and_report_share_computation(tmp_path):
    (tmp_path / "samples.csv").write_text("id,tonnes,grade_pct\nA,100,1.2\nB,200,0.8\nC,150,\nD,-50,1.0\nE,80,2.0\n")
    code = """import csv,json
from pathlib import Path
valid=[]; rejected=[]
for row in csv.DictReader(Path('samples.csv').open()):
    try:
        t=float(row['tonnes']); g=float(row['grade_pct'])
        assert t>=0 and g>=0
        valid.append((t,g))
    except (ValueError,AssertionError): rejected.append(row['id'])
tonnes=sum(t for t,g in valid); metal=sum(t*g/100 for t,g in valid)
data={'total_tonnes':tonnes,'metal_tonnes':metal,'weighted_grade_pct':metal/tonnes*100,'rejected':rejected}
Path('summary.json').write_text(json.dumps(data))
Path('report.md').write_text(f'Theoretical metal: {metal} tonnes; ore: {tonnes} tonnes. Not recoverable metal.')
assert abs(metal-4.4)<1e-10
print(json.dumps(data))
"""
    result = create_agent(Scripted(call("execute_python", {"code": code}), ModelResponse("4.4 tonnes theoretical metal."))).run("Analyze", workspace=tmp_path)
    assert result.status == "completed", result.reason
    data = json.loads((tmp_path / "summary.json").read_text())
    assert data["total_tonnes"] == 380 and math.isclose(data["metal_tonnes"], 4.4)
    assert data["rejected"] == ["C", "D"]
    assert "4.4" in (tmp_path / "report.md").read_text()
    assert {a.path for a in result.artifacts} == {"summary.json", "report.md"}

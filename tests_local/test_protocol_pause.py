"""Native protocol correction and durable resume; no external model is called."""
import json
import os
from threading import Event
import uuid

import pytest

from geological_agent.agent.completion import CompletionIssue
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import ModelResponse, ToolCall
from geological_agent.settings import Settings
from test_hitl_cards import group, pause, reply_body, reply_url, wait_finished


@pytest.fixture(autouse=True)
def isolated_actor_settings(monkeypatch):
    for name in ("GEOTOOL_INTENT_REVIEW", "GEOTOOL_REQUIREMENT_COVERAGE",
                 "GEOTOOL_COMBINED_COMPLETION_REVIEW", "GEOTOOL_OPTIMIZE_ROUND_TRIPS",
                 "GEOTOOL_COMPACT_REVIEW", "GEOTOOL_COMPACT_DISCOVERY",
                 "GEOTOOL_REVIEW_REFERENCE_SETS"):
        monkeypatch.delenv(name, raising=False)


class Scripted:
    def __init__(self, *responses):
        self.responses, self.requests = iter(responses), []

    def invoke(self, request):
        self.requests.append(request)
        response = next(self.responses)
        return response(request) if callable(response) else response


def action(name, arguments, identity):
    return ModelResponse(tool_calls=(ToolCall(identity, name, arguments),), finish_reason="tool_calls")


def runtime(model, **kwargs):
    return create_agent(model, settings=Settings(verify_completion=False, max_model_turns=15), **kwargs)


def observations(outcome):
    return [json.loads(message.content) for message in outcome.state["messages"] if message.role == "tool"]


def needs_read(state):
    if any(message.role == "tool" and json.loads(message.content)["name"] == "read_file"
           and json.loads(message.content)["status"] == "ok" for message in state["messages"]):
        return []
    return [CompletionIssue("Inspect retained.txt through read_file before delivering the result.", True)]


def test_required_violation_is_corrected_without_replaying_successful_tools(tmp_path):
    invalid = "I already inspected the file, without returning a native call."
    model = Scripted(action("write_file", {"path": "retained.txt", "content": "42"}, "write"),
                     ModelResponse("Created the file."), ModelResponse(invalid),
                     action("read_file", {"path": "retained.txt"}, "read"), ModelResponse("The file contains 42."))
    result = runtime(model, completion_checks=(needs_read,)).run("Create and inspect retained.txt", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert [request.tool_choice for request in model.requests] == ["auto", "auto", "required", "required", "auto"]
    assert [row["name"] for row in observations(result)] == ["write_file", "read_file"]
    assert (tmp_path / "retained.txt").read_text() == "42"
    assert len(result.state["metadata"]["protocol_failures"]) == 1
    assert result.state["metadata"]["protocol_failures"][0]["response"]["content"] == invalid
    assert not any(message.role == "assistant" and message.content == invalid for message in result.state["messages"])
    assert any("Runtime protocol correction:" in message.content for message in model.requests[3].messages)
    assert "protocol_recovery" not in result.state["metadata"]


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_pause_resume_after_new_runtime_preserves_work_and_native_pairs(tmp_path, backend):
    options = {"human_input": True}
    if backend == "postgres":
        from geological_agent.context_store import ContextScope, PostgresContextStore, private_dsn
        path = os.environ.get("GEOTOOL_TEST_POSTGRES_DSN_FILE")
        if not path:
            pytest.skip("Real PostgreSQL protocol resume runs in A100 acceptance")
        options["context_store"] = PostgresContextStore(private_dsn(path), ContextScope("protocol_" + uuid.uuid4().hex, "conversation"))
    checkpoint, work = tmp_path / "checkpoint.sqlite3", tmp_path / "work"
    first = Scripted(action("write_file", {"path": "retained.txt", "content": "42"}, "write"),
                     ModelResponse(""), ModelResponse("I will inspect it."))
    result = runtime(first, **options).run("Create and inspect retained.txt", workspace=work, checkpoint_path=checkpoint)
    assert result.status == "needs_input", result.reason
    pending = result.state["metadata"]["pending_input"]
    assert pending["reason_type"] == "model_protocol" and pending["recovery_origin"] == "runtime"
    assert result.state["pending_tool_calls"] == []
    assert [row["name"] for row in observations(result)] == ["write_file"]
    # A fresh agent/model consumes the saved interrupt, not the old task prefix.
    if backend == "postgres":
        saved = options["context_store"]
        options["context_store"] = PostgresContextStore(saved._dsn, saved.scope)
    second = Scripted(action("read_file", {"path": "retained.txt"}, "read"), ModelResponse("42 remains in retained.txt."))
    resumed = runtime(second, **options).run("Continue", workspace=work, checkpoint_path=checkpoint,
        resume={"run_id": result.run_id, "request_id": pending["id"], "text": "Retry current model", "files": ["retained.txt"]})
    assert resumed.status == "completed", resumed.reason
    assert resumed.run_id == result.run_id
    assert resumed.model_turns == 5 and len(second.requests) == 2
    assert [request.tool_choice for request in second.requests] == ["required", "auto"]
    assert (work / "retained.txt").read_text() == "42"
    assert [row["name"] for row in observations(resumed)] == ["write_file", "read_file"]
    calls = [call.id for message in resumed.state["messages"] for call in message.tool_calls]
    results = [message.tool_call_id for message in resumed.state["messages"] if message.role == "tool"]
    assert calls == results == ["write", "read"]
    assert "pending_input" not in resumed.state["metadata"]
    assert len(resumed.state["metadata"]["protocol_failures"]) == 2
    if backend == "postgres":
        assert not checkpoint.exists()


def test_stale_protocol_reply_cannot_consume_saved_pause(tmp_path):
    checkpoint, work = tmp_path / "checkpoint.sqlite3", tmp_path / "work"
    first = runtime(Scripted(ModelResponse(""), ModelResponse("No call.")), human_input=True).run(
        "Inspect files", workspace=work, checkpoint_path=checkpoint)
    assert first.status == "needs_input"
    model = Scripted()
    result = runtime(model, human_input=True).run("Continue", workspace=work, checkpoint_path=checkpoint,
        resume={"run_id": first.run_id, "request_id": uuid.uuid4().hex, "text": "Continue"})
    assert result.status == "failed" and "Stale" in result.reason
    assert not model.requests
    good = runtime(Scripted(action("write_file", {"path": "result.txt", "content": "42"}, "new"),
                            ModelResponse("Created result.txt.")), human_input=True).run(
        "Continue", workspace=work, checkpoint_path=checkpoint,
        resume={"run_id": first.run_id, "request_id": first.state["metadata"]["pending_input"]["id"], "text": "Continue"})
    assert good.status == "completed", good.reason


@pytest.mark.parametrize("malformed", ["truncated", "duplicate_ids"])
def test_invalid_native_batches_never_execute_before_pause(tmp_path, malformed):
    def bad(identity):
        if malformed == "truncated":
            return ModelResponse(tool_calls=(ToolCall(identity, "write_file", {"path": "bad.txt", "content": "bad"}),),
                                 finish_reason="length")
        return ModelResponse(tool_calls=(ToolCall(identity, "write_file", {"path": "bad.txt", "content": "bad"}),
                                         ToolCall(identity, "write_file", {"path": "bad2.txt", "content": "bad"})),
                             finish_reason="tool_calls")
    result = runtime(Scripted(bad("one"), bad("two")), human_input=True).run(
        "Inspect", workspace=tmp_path / "work", checkpoint_path=tmp_path / "cp.sqlite3")
    assert result.status == "needs_input", result.reason
    assert not observations(result) and not result.artifacts
    assert not (tmp_path / "work" / "bad.txt").exists()
    assert not (tmp_path / "work" / "bad2.txt").exists()


def test_json_text_under_required_is_not_adapted_into_execution(tmp_path):
    text = json.dumps({"name": "write_file", "arguments": {"path": "bad.txt", "content": "bad"}})
    result = runtime(Scripted(ModelResponse(""), ModelResponse(text))).run("Inspect files", workspace=tmp_path)
    assert result.status == "incomplete" and not result.answer
    assert result.model_turns == 2 and not observations(result)
    assert not (tmp_path / "bad.txt").exists()
    assert result.state["metadata"]["protocol_failures"][-1]["response"]["content"] == text


def test_cancellation_during_invalid_response_does_not_open_pause(tmp_path):
    cancel = Event()
    def response(request):
        cancel.set()
        return ModelResponse("")
    result = runtime(Scripted(response), human_input=True).run("Inspect files", workspace=tmp_path / "work",
        checkpoint_path=tmp_path / "cp.sqlite3", cancel_event=cancel)
    assert result.status == "stopped"
    assert "pending_input" not in result.state["metadata"]


def test_model_change_does_not_erase_reference_data_rejection(tmp_path):
    work, checkpoint = tmp_path / "work", tmp_path / "cp.sqlite3"
    csv = "dep_id,country,commod1,latitude,longitude\n10134066,China,Nickel,38.99825,102.49969\n"
    lookup = {"dataset_path": "unverified.csv", "country": "China", "commodity": "Nickel", "limit": 1}
    first = Scripted(action("write_file", {"path": "unverified.csv", "content": csv}, "write"),
                     action("MineralResourcesSearchDeposits", lookup, "lookup"),
                     ModelResponse("This is a verified external mine."),
                     ModelResponse("I fetched the source."), ModelResponse("The source is verified."))
    agent = runtime(first, human_input=True)
    sid = next(s.id for s in agent.skills.registry.list()
               if "MineralResourcesSearchDeposits" in agent.skills.load(s.id).tool_names)
    paused = agent.run("Find an actual Chinese nickel record from its source", workspace=work,
                       checkpoint_path=checkpoint, skill_id=sid)
    assert paused.status == "needs_input", paused.reason
    assert paused.state["metadata"]["pending_input"]["reason_type"] == "model_protocol"
    second = Scripted(action("MineralResourcesSearchDeposits", lookup, "lookup_again"),
                      ModelResponse("The saved local row is a verified external mine."))
    resumed = runtime(second, human_input=True).run("Continue", workspace=work, checkpoint_path=checkpoint,
        resume={"run_id": paused.run_id, "request_id": paused.state["metadata"]["pending_input"]["id"], "text": "Changed model; continue"})
    assert resumed.status == "needs_input", resumed.reason
    assert "provenance" in resumed.reason
    assert resumed.state["metadata"]["pending_input"].get("reason_type") != "model_protocol"
    assert resumed.state["metadata"]["tool_evidence"]["files"]["unverified.csv"]["origin"] == "model_authored"
    assert (work / "unverified.csv").read_text() == csv


@pytest.mark.parametrize("reason_type,origin,allowed", [
    ("model_protocol", "runtime", True),
    ("missing_input", "runtime", False),
    ("model_protocol", "model", False),
    ("model_protocol", None, False),
])
def test_model_switch_is_allowed_only_for_runtime_protocol_pause(group, reason_type, origin, allowed):
    app, alice, bob, runner = group
    item = pause(app.state.store, reason_type=reason_type, recovery_origin=origin)
    app.state.store.event(item["rid"], {"kind": "model_config", "profile": {"model": "prior-synthetic-model"}})
    assert bob.post(reply_url(item), json=reply_body(item, "Continue")).status_code == 404
    response = alice.post(reply_url(item), json=reply_body(item, "Configuration updated; continue"))
    assert response.status_code == (200 if allowed else 409), response.text
    if allowed:
        assert wait_finished(alice, response.json()["id"])["status"] == "completed"
        assert len(runner.calls) == 1 and runner.calls[0]["id"] == item["id"]
        assert alice.post(reply_url(item), json=reply_body(item, "Continue")).status_code == 409
    else:
        assert not runner.calls
        assert app.state.store.input_request("alice", item["id"])["state"] == "pending"


"""Intent protocol recovery uses native responses, durable state and paired traces."""
import json
import os
from threading import Event
from types import SimpleNamespace
import uuid

import pytest

from geological_agent.bootstrap import create_agent
from geological_agent.contracts import ModelResponse, ToolCall
from geological_agent.langsmith_tracing import LangSmithTrace
from geological_agent.llm import ModelProtocolError
from geological_agent.settings import Settings
from geological_agent.tracing import JsonlTrace


@pytest.fixture(autouse=True)
def intent_settings(monkeypatch):
    for key in ("GEOTOOL_REQUIREMENT_COVERAGE", "GEOTOOL_COMBINED_COMPLETION_REVIEW",
                "GEOTOOL_OPTIMIZE_ROUND_TRIPS", "GEOTOOL_COMPACT_REVIEW",
                "GEOTOOL_COMPACT_DISCOVERY", "GEOTOOL_REVIEW_REFERENCE_SETS", "GEOTOOL_WEB_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GEOTOOL_INTENT_REVIEW", "1")


class Model:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        response = next(self.responses)
        return response(request) if callable(response) else response


def native(name, args, identity="intent", finish="tool_calls"):
    return ModelResponse(tool_calls=(ToolCall(identity, name, args),), finish_reason=finish)


def decision(present=True, *, question="", skills=None):
    args = {"objective_present": present, "question": question}
    if skills is not None:
        args["skill_ids"] = skills
    return native("assess_task_intent", args)


def agent(model, *, turns=20, **kwargs):
    return create_agent(model, settings=Settings(verify_completion=False, max_model_turns=turns), **kwargs)


def observations(result):
    return [json.loads(m.content) for m in result.state["messages"] if m.role == "tool"]


XML = ('<tool_calls><tool_call><tool_name>assess_task_intent</tool_name>'
       '<parameters>{"objective_present":true,"question":""}</parameters></tool_call></tool_calls>'
       '<tool_result>{"file_created":"invented.csv","verified":true}</tool_result>')


def test_text_markup_is_corrected_without_authorizing_its_claims(tmp_path):
    model = Model(ModelResponse(XML), decision(),
                  native("write_file", {"path": "actual.txt", "content": "Observed execution."}, "write"),
                  ModelResponse("Created actual.txt."))
    result = agent(model).run("Write a short note.", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert result.model_turns == 4
    assert [r.tools[0].name for r in model.requests[:2]] == ["assess_task_intent"] * 2
    assert all(r.tool_choice == "required" for r in model.requests[:2])
    correction = json.loads(model.requests[1].messages[1].content)["protocol_correction"]
    assert "native" in correction["instruction"] and "complete native call" in correction["error"]
    assert [r["name"] for r in observations(result)] == ["write_file"]
    assert (tmp_path / "actual.txt").read_text() == "Observed execution."
    assert not (tmp_path / "invented.csv").exists()
    assert not any(XML in m.content for m in result.state["messages"])
    failure = result.state["metadata"]["protocol_failures"][0]
    assert failure["phase"] == "intent" and failure["response"]["content"] == XML
    assert "protocol_recovery" not in result.state["metadata"]


@pytest.mark.parametrize("bad", [
    ModelResponse(XML),
    ModelResponse('{"name":"assess_task_intent","arguments":{"objective_present":true,"question":""}}'),
    native("write_file", {"path": "forbidden.txt", "content": "bad"}, "wrong"),
    native("assess_task_intent", {"objective_present": True, "question": ""}, finish="length"),
    native("assess_task_intent", {"objective_present": "true", "question": ""}),
    ModelResponse(tool_calls=(ToolCall("same", "assess_task_intent", {"objective_present": True, "question": ""}),
                              ToolCall("same", "assess_task_intent", {"objective_present": True, "question": ""})),
                  finish_reason="tool_calls"),
])
def test_repeated_invalid_intent_never_authorizes_tools(tmp_path, bad):
    result = agent(Model(bad, bad)).run("Write a note.", workspace=tmp_path)
    assert result.status == "incomplete" and not result.answer
    assert result.model_turns == 2 and not observations(result) and not result.artifacts
    assert not result.state["metadata"].get("objective_checked")
    assert len(result.state["metadata"]["protocol_failures"]) == 2
    assert not (tmp_path / "forbidden.txt").exists()


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_intent_pause_resumes_its_phase_with_retry_count_reset(tmp_path, backend):
    options = {"human_input": True}
    if backend == "postgres":
        from geological_agent.context_store import ContextScope, PostgresContextStore, private_dsn
        dsn = os.environ.get("GEOTOOL_TEST_POSTGRES_DSN_FILE")
        if not dsn:
            pytest.skip("Real PostgreSQL intent resume runs in A100 acceptance")
        options["context_store"] = PostgresContextStore(private_dsn(dsn),
            ContextScope("intent_" + uuid.uuid4().hex, "conversation"))
    work = tmp_path / "work"
    work.mkdir()
    (work / "retained.txt").write_text("Keep this user file.")
    checkpoint = tmp_path / "checkpoint.sqlite3" if backend == "sqlite" else None
    first = agent(Model(ModelResponse(XML), ModelResponse(XML)), **options).run(
        "Write a short note.", workspace=work, checkpoint_path=checkpoint)
    assert first.status == "needs_input", first.reason
    pending = first.state["metadata"]["pending_input"]
    assert pending["reason_type"] == "model_protocol" and pending["recovery_phase"] == "intent"
    assert pending["recovery_origin"] == "runtime"
    assert not first.state["metadata"].get("objective_checked") and not observations(first)
    if backend == "postgres":
        old = options["context_store"]
        options["context_store"] = PostgresContextStore(old._dsn, old.scope)
    second = Model(ModelResponse(XML), decision(),
                   native("write_file", {"path": "actual.txt", "content": "A note."}, "write"),
                   ModelResponse("Created actual.txt."))
    resumed = agent(second, **options).run("Continue", workspace=work, checkpoint_path=checkpoint,
        resume={"run_id": first.run_id, "request_id": pending["id"], "text": "Retry current model", "files": []})
    assert resumed.status == "completed", resumed.reason
    assert resumed.run_id == first.run_id and resumed.model_turns == 6
    assert all([t.name for t in r.tools] == ["assess_task_intent"] for r in second.requests[:2])
    assert "Retry current model" in second.requests[0].messages[1].content
    assert len(resumed.state["metadata"]["protocol_failures"]) == 3
    assert [r["name"] for r in observations(resumed)] == ["write_file"]
    assert (work / "retained.txt").read_text() == "Keep this user file."
    assert (work / "actual.txt").read_text() == "A note."
    assert "pending_input" not in resumed.state["metadata"]
    assert "protocol_recovery" not in resumed.state["metadata"]
    if backend == "postgres":
        assert not (tmp_path / "checkpoint.sqlite3").exists()


def test_corrected_intent_does_not_force_execution_for_an_explanation(tmp_path):
    model = Model(ModelResponse(XML), decision(), ModelResponse("Hello."))
    result = agent(model).run("Say hello.", workspace=tmp_path)
    assert result.status == "completed" and result.answer == "Hello."
    assert [r.tool_choice for r in model.requests] == ["required", "required", "auto"]
    assert not observations(result)


def test_missing_objective_after_correction_still_requires_human_input(tmp_path):
    model = Model(ModelResponse(XML), decision(False, question="What should I calculate?"))
    result = agent(model, human_input=True).run("39.9042,116.4074", workspace=tmp_path / "work",
                                              checkpoint_path=tmp_path / "checkpoint.sqlite3")
    assert result.status == "needs_input" and result.model_turns == 2
    assert result.answer == "What should I calculate?"
    assert result.state["metadata"]["pending_input"].get("reason_type") != "model_protocol"
    assert not result.state["metadata"].get("objective_checked") and not observations(result)


def test_recovery_cannot_bypass_cumulative_budget(tmp_path):
    model = Model(ModelResponse(XML))
    result = agent(model, turns=1).run("Write a note.", workspace=tmp_path)
    assert result.status == "budget_exhausted" and result.model_turns == 1
    assert len(model.requests) == 1 and not observations(result)
    assert not result.state["metadata"].get("objective_checked")


def test_cancellation_during_invalid_intent_does_not_pause(tmp_path):
    cancel = Event()
    def invalid(request):
        cancel.set()
        return ModelResponse(XML)
    model = Model(invalid)
    result = agent(model, human_input=True).run("Write a note.", workspace=tmp_path / "work",
        checkpoint_path=tmp_path / "checkpoint.sqlite3", cancel_event=cancel)
    assert result.status == "stopped" and result.model_turns == 1
    assert not result.state["metadata"].get("pending_input") and not observations(result)


def test_compact_skill_disclosure_occurs_only_after_valid_native_assessment(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_COMPACT_DISCOVERY", "1")
    model = Model(ModelResponse(XML), decision(skills=[]), ModelResponse("Hello."))
    result = agent(model).run("Say hello.", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert not result.state["selected_skill_ids"]
    assert not result.state["metadata"]["intent_selected_skill_ids"]
    assert not observations(result)


class FakeRun:
    def __init__(self, **fields):
        self.id = uuid.uuid4()
        self.fields, self.children, self.ends = fields, [], []

    def create_child(self, **fields):
        child = FakeRun(**fields)
        self.children.append(child)
        return child

    def post(self):
        pass

    def patch(self):
        pass

    def end(self, **fields):
        self.ends.append(fields)


def recording_trace(path):
    return LangSmithTrace(JsonlTrace(path), SimpleNamespace(flush=lambda **kwargs: None),
        project="offline-acceptance", capture_content=True, run_factory=FakeRun)


def test_returned_invalid_intent_has_one_completion_and_separate_protocol_event(tmp_path):
    path = tmp_path / "trace.jsonl"
    trace = recording_trace(path)
    model = Model(ModelResponse(XML), decision(), ModelResponse("Hello."))
    result = agent(model, trace_factory=lambda *args: trace).run("Say hello.", workspace=tmp_path / "work")
    assert result.status == "completed", result.reason
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert not [e for e in events if e["event"] in ("langsmith_unmatched_completion", "langsmith_export_failed", "model_failed")]
    assert len([e for e in events if e["event"] == "model_requested"]) == 3
    assert len([e for e in events if e["event"] == "model_responded"]) == 3
    rejected = [e for e in events if e["event"] == "model_protocol_error"]
    assert len(rejected) == 1 and rejected[0]["phase"] == "intent"
    assert any(c.fields["name"] == "model_protocol_error" for c in trace.root.children)
    assert not trace.active and all(len(c.ends) == 1 for c in trace.root.children)
    first = next(c for c in trace.root.children if c.fields["run_type"] == "llm")
    assert first.ends[0]["outputs"]["message"]["content"] == XML


@pytest.mark.parametrize("protocol", [False, True])
def test_transport_failure_is_closed_once_and_not_confused_with_response_validation(tmp_path, protocol):
    def failure(request):
        if protocol:
            raise ModelProtocolError("Malformed native response envelope")
        raise RuntimeError("Model endpoint request failed (402)")
    model = Model(failure, decision(), ModelResponse("Hello.")) if protocol else Model(failure)
    path = tmp_path / "trace.jsonl"
    trace = recording_trace(path)
    result = agent(model, trace_factory=lambda *args: trace).run("Say hello.", workspace=tmp_path / "work")
    assert result.status == ("completed" if protocol else "failed"), result.reason
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert len([e for e in events if e["event"] == "model_failed"]) == 1
    assert not [e for e in events if e["event"] in ("langsmith_unmatched_completion", "langsmith_export_failed")]
    assert not trace.active and all(len(c.ends) == 1 for c in trace.root.children)
    assert len(model.requests) == (3 if protocol else 1)
    if protocol:
        assert result.state["metadata"]["protocol_failures"][0]["response"] is None
    else:
        assert not result.state["metadata"].get("protocol_failures")


def test_pre_request_error_does_not_finish_a_nonexistent_model_span(tmp_path, monkeypatch):
    import geological_agent.agent.runtime as runtime_module
    def bad_request(*args, **kwargs):
        raise ValueError("Request setup failed before invocation")
    monkeypatch.setattr(runtime_module, "intent_request", bad_request)
    path = tmp_path / "trace.jsonl"
    trace = recording_trace(path)
    model = Model()
    result = agent(model, trace_factory=lambda *args: trace).run("Say hello.", workspace=tmp_path / "work")
    assert result.status == "failed" and not model.requests
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert any(e["event"] == "intent_assessment_error" for e in events)
    assert not [e for e in events if e["event"] in ("model_failed", "langsmith_unmatched_completion", "langsmith_export_failed")]
    assert not trace.active

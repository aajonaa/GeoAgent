import json

import pytest

from geological_agent.bootstrap import create_agent
from geological_agent.contracts import Message, ModelResponse, ToolCall, ToolResult
from geological_agent.langsmith_tracing import LangSmithTrace
from geological_agent.tracing import JsonlTrace, configured_trace


class MemoryClient:
    def __init__(self):
        self.created, self.updated, self.feedback = [], [], []
        self.flushes = 0

    def create_run(self, **kwargs):
        self.created.append(kwargs)

    def update_run(self, run_id, **kwargs):
        self.updated.append({"id": run_id, **kwargs})

    def create_feedback(self, run_id, **kwargs):
        self.feedback.append({"run_id": run_id, **kwargs})

    def flush(self, timeout=None):
        self.flushes += 1


def sink(tmp_path, capture=False):
    local = JsonlTrace(tmp_path / "trace.jsonl", secrets=("credential-secret",))
    client = MemoryClient()
    return LangSmithTrace(local, client, project="offline-test", capture_content=capture, model="GeoGPT", release="test-release"), client


def exercise(trace):
    trace.emit("run_started", run_id="local-run", task="private-task credential-secret")
    trace.emit("model_requested", run_id="local-run", turn=1,
               messages=[Message("user", "private-prompt credential-secret")], tools=["read_file"], tool_choice="required")
    trace.emit("model_responded", run_id="local-run", turn=1,
               response=ModelResponse(tool_calls=(ToolCall("c1", "read_file", {"path": "private.txt"}),),
                   finish_reason="tool_calls", usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}))
    trace.emit("tool_requested", run_id="local-run", call=ToolCall("c1", "read_file", {"path": "private.txt"}))
    trace.emit("tool_completed", run_id="local-run", result=ToolResult("c1", "read_file", "ok", {"content": "private-data credential-secret"}))
    trace.emit("completion_rejected", run_id="local-run", answer="private-draft", feedback="private-feedback credential-secret")
    trace.emit("run_finished", run_id="local-run", status="completed", answer="private-answer", artifacts=[], metadata={}, model_turns=1)


def test_real_sdk_builds_parented_spans_and_usage_without_network(tmp_path):
    trace, client = sink(tmp_path)
    exercise(trace)
    assert not trace.failed
    assert len(client.created) == 4
    root = client.created[0]
    assert root["name"] == "GeoToolAgent task"
    assert all(child["parent_run_id"] == root["id"] for child in client.created[1:])
    assert client.created[1]["run_type"] == "llm"
    assert client.created[2]["run_type"] == "tool"
    assert client.updated[0]["outputs"]["usage_metadata"] == {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
    assert client.updated[-1]["outputs"]["model_turns"] == 1
    assert client.updated[-2]["error"] == "completion_rejected"
    assert client.flushes == 1


def test_metadata_only_mode_does_not_export_contents(tmp_path):
    trace, client = sink(tmp_path)
    exercise(trace)
    wire = json.dumps([client.created, client.updated], default=str)
    for private in ("private-task", "private-prompt", "private.txt", "private-data", "private-draft", "private-answer", "credential-secret"):
        assert private not in wire


def test_content_mode_redacts_known_credentials_before_sdk(tmp_path):
    trace, client = sink(tmp_path, capture=True)
    exercise(trace)
    wire = json.dumps([client.created, client.updated], default=str)
    assert "private-prompt" in wire and "private-data" in wire
    assert "credential-secret" not in wire and "[REDACTED]" in wire


def test_independent_failure_is_not_hidden_by_agent_completed_status(tmp_path):
    trace, client = sink(tmp_path, capture=True)
    exercise(trace)
    trace.acceptance(False, task="table", errors=("Wrong numbers",))
    assert client.updated[-1]["outputs"]["status"] == "completed"
    assert client.feedback[0]["score"] == 0
    assert client.feedback[0]["key"] == "independent_acceptance"
    assert "Wrong numbers" in client.feedback[0]["comment"]


def test_export_failure_keeps_local_logging_and_does_not_raise(tmp_path):
    trace, client = sink(tmp_path)
    def fail(**kwargs):
        raise RuntimeError("credential-secret must not leak")
    client.create_run = fail
    trace.emit("run_started", run_id="local", task="task")
    trace.emit("run_finished", status="failed", model_turns=0)
    records = [json.loads(line) for line in trace.local.path.read_text().splitlines()]
    assert trace.failed
    assert [record["event"] for record in records] == ["run_started", "langsmith_export_failed", "run_finished"]
    assert "credential-secret" not in json.dumps(records)


def test_export_disabled_by_default_even_if_key_exists(tmp_path, monkeypatch):
    monkeypatch.delenv("GEOTOOL_LANGSMITH_ENABLED", raising=False)
    monkeypatch.setenv("LANGSMITH_API_KEY", "credential-secret")
    trace = configured_trace(tmp_path / "disabled.jsonl")
    assert type(trace) is JsonlTrace


def test_explicit_opt_in_without_key_stays_local(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_LANGSMITH_ENABLED", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    trace = configured_trace(tmp_path / "missing-key.jsonl")
    assert type(trace) is JsonlTrace
    assert "langsmith_unavailable" in trace.path.read_text()


def test_automatic_graph_export_is_disabled_inside_execution_context(tmp_path, monkeypatch):
    from langsmith import get_tracing_context
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    trace = JsonlTrace(tmp_path / "local.jsonl")
    with trace.execution_context():
        assert get_tracing_context()["enabled"] is False


@pytest.mark.parametrize("choice", ("auto", "required", "none"))
def test_dummy_credential_does_not_hide_public_protocol_enum(tmp_path, choice):
    local = JsonlTrace(tmp_path / "trace.jsonl", secrets=(choice,))
    client = MemoryClient()
    trace = LangSmithTrace(local, client, project="offline-test", capture_content=True)
    trace.emit("run_started", run_id="local", task="Test tracing")
    trace.emit("model_requested", turn=1, tool_choice=choice, messages=[], tools=[],
               request={"tool_choice": choice, "messages": [{"content": choice}],
                        "api_key": choice, "authorization": choice})
    trace.emit("model_responded", turn=1, response=ModelResponse("A result"))
    trace.emit("run_finished", status="completed", model_turns=1)
    record = next(json.loads(line) for line in local.path.read_text().splitlines()
                  if json.loads(line)["event"] == "model_requested")
    assert record["tool_choice"] == record["request"]["tool_choice"] == choice
    assert record["request"]["api_key"] == record["request"]["authorization"] == "[REDACTED]"
    assert record["request"]["messages"][0]["content"] == "[REDACTED]"
    assert client.created[1]["extra"]["metadata"]["tool_choice"] == choice
    assert client.created[1]["inputs"]["messages"][0]["content"] == "[REDACTED]"


def test_nonstandard_tool_choice_still_redacts_credentials(tmp_path):
    trace = JsonlTrace(tmp_path / "trace.jsonl", secrets=("credential-secret",))
    assert trace._safe({"tool_choice": "credential-secret"}) == {"tool_choice": "[REDACTED]"}
    assert trace._safe({"tool_choice": {"function": {"name": "credential-secret"}}}) == {
        "tool_choice": {"function": {"name": "[REDACTED]"}}}


@pytest.mark.parametrize("capture", (False, True))
def test_runtime_traces_actual_disclosed_definitions_with_opt_in(tmp_path, capture):
    (tmp_path / "input.txt").write_text("42", encoding="utf-8")
    responses = iter((
        ModelResponse(tool_calls=(ToolCall("r1", "read_file", {"path": "input.txt"}),), finish_reason="tool_calls"),
        ModelResponse("input.txt contains 42."),
        ModelResponse(tool_calls=(ToolCall("readiness", "assess_completion", {
            "verdict": "complete", "feedback": "The requested file was read.",
            "required_outputs": [], "requires_python_execution": False,
            "evidence_call_ids": ["r1"]}),), finish_reason="tool_calls"),
        ModelResponse("input.txt contains 42."),
        ModelResponse(tool_calls=(ToolCall("review", "assess_completion", {
            "verdict": "complete", "feedback": "The answer matches the observed file.",
            "required_outputs": [], "requires_python_execution": False,
            "evidence_call_ids": ["r1"]}),), finish_reason="tool_calls"),
    ))
    class Model:
        def invoke(self, request):
            return next(responses)
    trace, client = sink(tmp_path, capture=capture)
    agent = create_agent(Model(), trace_factory=lambda run_id, workspace: trace)
    result = agent.run("Read input.txt", workspace=tmp_path)
    assert result.status == "completed" and not trace.failed
    request = next(json.loads(line) for line in trace.local.path.read_text().splitlines()
                   if json.loads(line)["event"] == "model_requested")
    definitions = request["tool_definitions"]
    assert request["tools"] == [definition["name"] for definition in definitions]
    read_definition = next(definition for definition in definitions if definition["name"] == "read_file")
    assert "path" in read_definition["input_schema"]["required"]
    assert read_definition["input_schema"]["properties"]["path"]["description"]
    decision = next(run for run in client.created if run["name"] == "Model decision")
    assert decision["inputs"] == ({"messages": request["messages"], "tools": definitions} if capture else {})


def test_review_recovery_phase_and_attempt_export_without_raw_content(tmp_path):
    trace, client = sink(tmp_path, capture=False)
    trace.emit("run_started", run_id="recovery", task="private task")
    for turn in (1, 2):
        trace.emit("completion_review_requested", turn=turn, phase="execution", attempt=turn,
                   request={"tool_choice": "required", "messages": [{"content": "private draft"}], "tools": []})
        trace.emit("completion_review_responded", turn=turn, phase="execution", attempt=turn,
                   response=ModelResponse("private response"))
        if turn == 1:
            trace.emit("completion_review_protocol_error", turn=turn, phase="execution", attempt=turn,
                       error="private invalid assessment")
    trace.emit("run_finished", status="completed", model_turns=2)
    assert not trace.failed
    reviews = [run for run in client.created if run["name"] == "Completion review"]
    assert [run["extra"]["metadata"]["attempt"] for run in reviews] == [1, 2]
    assert all(run["extra"]["metadata"]["phase"] == "execution" for run in reviews)
    failure = next(run for run in client.created if run["name"] == "completion_review_protocol_error")
    assert failure["extra"]["metadata"]["phase"] == "execution"
    assert all(not run["inputs"] for run in client.created)
    assert any(run.get("error") == "completion_review_protocol_error" for run in client.updated)
    assert "private" not in json.dumps([run.get("outputs") for run in client.updated])

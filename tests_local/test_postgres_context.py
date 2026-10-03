"""Real PostgreSQL acceptance. The deployment gate requires this suite to run."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import uuid

import pytest

from geological_agent.bootstrap import create_agent
from geological_agent.context_store import ContextScope, ContextStoreError, PostgresContextStore, private_dsn
from geological_agent.contracts import Message, ModelResponse, ToolCall
from geological_agent.settings import Settings


@pytest.fixture
def store():
    path = os.environ.get("GEOTOOL_TEST_POSTGRES_DSN_FILE")
    if not path:
        pytest.skip("Real PostgreSQL acceptance runs on A100 with a private test database")
    result = PostgresContextStore(private_dsn(path), ContextScope("test_" + uuid.uuid4().hex, "conversation"))
    return result


def begin(store, tmp_path):
    run_id = uuid.uuid4().hex
    store.begin_run(run_id, "acceptance", tmp_path)
    return run_id


def test_postgres_exact_roundtrip_pagination_and_null_character(store, tmp_path):
    run_id = begin(store, tmp_path)
    payload = {"value": 3.54813389233576e14, "unit": "J", "text": "source " * 4000 + "\0"}
    ref = store.put(run_id, "exchange", "first", payload, "GeoMagnitudeToEnergy c1")
    chunks, offset = [], 0
    while True:
        page = store.read(ref["evidence_id"], offset=offset, limit=1500)
        chunks.append(page["content"])
        assert page["sha256"] == ref["sha256"] and page["source_run_id"] == run_id
        if not page["has_more"]:
            break
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    assert json.loads("".join(chunks)) == payload


def test_postgres_owner_and_conversation_isolation(store, tmp_path):
    run_id = begin(store, tmp_path)
    reference = store.put(run_id, "exchange", "first", {"secret_marker": "alpha"})
    other_owner = PostgresContextStore(store._dsn, ContextScope(store.scope.owner_id + "_other", store.scope.conversation_id))
    other_conversation = PostgresContextStore(store._dsn, ContextScope(store.scope.owner_id, "different"))
    for other in (other_owner, other_conversation):
        with pytest.raises(KeyError):
            other.read(reference["evidence_id"])
        assert not other.search("alpha")["matches"]
        with pytest.raises(ContextStoreError):
            other.begin_run(run_id, "hijack", tmp_path)


def test_postgres_originals_cannot_be_overwritten_or_deleted(store, tmp_path):
    run_id = begin(store, tmp_path)
    first = store.put(run_id, "exchange", "same", {"value": 1})
    assert store.put(run_id, "exchange", "same", {"value": 1}) == first
    with pytest.raises(ContextStoreError):
        store.put(run_id, "exchange", "same", {"value": 1000})
    with pytest.raises(ContextStoreError):
        with store.connection() as conn:
            conn.execute("DELETE FROM geotool_context.evidence WHERE evidence_id=%s", (first["evidence_id"],))
    assert json.loads(store.read(first["evidence_id"])["content"]) == {"value": 1}


def test_postgres_search_returns_pages_and_literal_chinese_terms(store, tmp_path):
    run_id = begin(store, tmp_path)
    for index in range(7):
        store.put(run_id, "exchange", str(index), {"text": "北京结果", "index": index}, "inspect")
    first = store.search("北京", run_id=run_id, limit=3)
    second = store.search("北京", run_id=run_id, limit=3, after=first["next_after"])
    last = store.search("北京", run_id=run_id, limit=3, after=second["next_after"])
    assert [len(p["matches"]) for p in (first, second, last)] == [3, 3, 1]
    assert first["has_more"] and second["has_more"] and not last["has_more"]
    assert len({row["evidence_id"] for p in (first, second, last) for row in p["matches"]}) == 7


def test_postgres_compaction_stores_retrievable_original_exchanges(store, tmp_path):
    from geological_agent.agent.compaction import fit_request, request_size, unpack_data
    from geological_agent.contracts import ModelRequest, ToolResult
    run_id = begin(store, tmp_path)
    messages = [Message("user", "Retain the units.")]
    for i in range(6):
        call = ToolCall("c" + str(i), "inspect", {"part": i})
        messages += [Message("assistant", tool_calls=(call,)),
                     ToolResult(call.id, call.name, "ok", {"unit": "km", "text": chr(65 + i) * 7000}).message()]
    state = {"run_id": run_id, "task": messages[0].content, "messages": messages, "metadata": {}}
    store.sync_state(state)
    fitted = fit_request(ModelRequest(tuple(messages), ()), state, Settings(max_context_chars=12000), archive=store)
    assert request_size(fitted) <= 12000
    payload = next(unpack_data(json.loads(m.content)) for m in fitted.messages if m.content.startswith("{"))
    for ref in payload["recent_evidence"]:
        page = store.read(ref["evidence_id"], limit=12000)
        original = json.loads(page["content"])
        assert json.loads(original["messages"][1]["content"])["data"]["unit"] == "km"
    assert len(state["messages"]) == 13


class Scripted:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []
    def invoke(self, request):
        self.requests.append(request)
        return next(self.responses)


def test_postgres_checkpoint_human_resume_preserves_native_types(store, tmp_path):
    question = {"question": "Which sample?", "reason": "Sample not specified",
                "missing": ["sample"], "options": ["A", "B"]}
    model = Scripted(ModelResponse(tool_calls=(ToolCall("ask", "request_user_input", question),),
                                   finish_reason="tool_calls"))
    agent = create_agent(model, context_store=store, human_input=True,
                         settings=Settings(verify_completion=False))
    checkpoint = tmp_path / "legacy-unused.sqlite3"
    first = agent.run("Analyze the selected sample.", workspace=tmp_path, checkpoint_path=checkpoint)
    assert first.status == "needs_input", first.reason
    pending = first.state["metadata"]["pending_input"]
    fresh_store = PostgresContextStore(store._dsn, store.scope)
    resumed_model = Scripted(ModelResponse("You selected A."))
    fresh_agent = create_agent(resumed_model, context_store=fresh_store, human_input=True,
                               settings=Settings(verify_completion=False))
    resumed = fresh_agent.run("A", workspace=tmp_path, checkpoint_path=checkpoint,
        resume={"run_id": first.run_id, "request_id": pending["id"], "text": "A", "files": []})
    assert resumed.status == "completed", resumed.reason
    assert resumed.model_turns == 2 and len(resumed_model.requests) == 1
    assert not checkpoint.exists()
    original_call = next(call for message in resumed.state["messages"] for call in message.tool_calls)
    assert original_call.arguments["options"] == ["A", "B"]
    assert isinstance(original_call.arguments["options"], list)
    assert fresh_store.thread_id(first.run_id) != PostgresContextStore(
        store._dsn, ContextScope("different-user", store.scope.conversation_id)).thread_id(first.run_id)


def test_postgres_native_retrieval_and_archive_are_used_by_runtime(store, tmp_path):
    prior = begin(store, tmp_path)
    reference = store.put(prior, "exchange", "source", {"value": 17, "unit": "km"})
    model = Scripted(ModelResponse(tool_calls=(ToolCall("recall", "context_read",
                     {"evidence_id": reference["evidence_id"]}),), finish_reason="tool_calls"),
                     ModelResponse("The earlier recorded value was 17 km."))
    agent = create_agent(model, context_store=store, settings=Settings(verify_completion=False))
    result = agent.run("Read the earlier recorded value; do not run a new calculation.", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert {"context_read", "context_search"} <= {t.name for t in model.requests[0].tools}
    record = next(json.loads(m.content) for m in result.state["messages"] if m.role == "tool")
    assert record["data"]["source_run_id"] == prior
    assert store.search(run_id=result.run_id, kind="message")["matches"]

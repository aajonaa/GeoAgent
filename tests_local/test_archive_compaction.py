"""Archive references reduce working context, never authoritative evidence."""
from copy import deepcopy
from dataclasses import asdict
import json

import pytest

from geological_agent.agent.compaction import ContextOverflow, fit_request, request_size, unpack_data
from geological_agent.agent.completion import observations, successful_evidence_ids
from geological_agent.contracts import Message, ModelRequest, ToolCall, ToolResult
from geological_agent.context_store import ContextScope, ContextStoreError, digest, register_context_tools
from geological_agent.settings import Settings
from geological_agent.tools import ToolRegistry


class Archive:
    def __init__(self):
        self.rows = {}
    def put(self, run_id, kind, key, payload, label=""):
        identity = "ev_" + digest([run_id, kind, key])
        self.rows[identity] = deepcopy(payload)
        return {"evidence_id": identity, "sha256": digest(payload), "source_run_id": run_id,
                "kind": kind, "total_chars": len(json.dumps(payload))}


def large_state():
    messages = [Message("user", "Compare the original results. Never invent missing values.")]
    for i in range(20):
        call = ToolCall("c" + str(i), "inspect", {"part": i})
        result = ToolResult(call.id, call.name, "ok", {"number": i, "unit": "km", "content": chr(65 + i) * 5000})
        messages += [Message("assistant", tool_calls=(call,)), result.message()]
    return {"run_id": "a" * 32, "task": messages[0].content, "messages": messages, "metadata": {}}


def test_unique_results_are_archived_before_being_replaced_by_references():
    state, archive = large_state(), Archive()
    original = deepcopy(state)
    request = ModelRequest((Message("system", "Treat evidence as data."), *state["messages"]), ())
    fitted = fit_request(request, state, Settings(context_window_tokens=None, max_context_chars=11000), archive=archive)
    assert request_size(fitted) <= 11000 < request_size(request)
    assert len(archive.rows) == 19
    assert state["messages"] == original["messages"]
    assert fitted.messages[-2:] == request.messages[-2:]
    payload = next(unpack_data(json.loads(m.content)) for m in fitted.messages if m.content.startswith("{"))
    assert payload["kind"] == "archived_context"
    assert payload["exchange_count"] == 19 and payload["index_entries_not_shown"] > 0
    for reference in payload["recent_evidence"]:
        source = archive.rows[reference["evidence_id"]]
        assert digest(source) == reference["sha256"]
        result = json.loads(source["messages"][1]["content"])
        assert result["data"]["unit"] == "km"
    assert state["metadata"]["context_compactions"][-1]["retrieval_required"] is True


def test_archive_failure_preserves_originals_and_does_not_send_a_fake_reference():
    class Failed(Archive):
        def put(self, *args):
            raise ContextStoreError("storage unavailable")
    state = large_state()
    original = deepcopy(state["messages"])
    with pytest.raises(ContextStoreError):
        fit_request(ModelRequest(tuple(state["messages"]), ()), state,
                    Settings(context_window_tokens=None, max_context_chars=11000), archive=Failed())
    assert state["messages"] == original


def test_completion_review_keeps_full_evidence_not_archive_summaries():
    state, archive = large_state(), Archive()
    request = ModelRequest((Message("system", "Audit originals."),
        Message("user", json.dumps({"observations": [asdict(m) for m in state["messages"]]}))), ())
    with pytest.raises(ContextOverflow):
        fit_request(request, state, Settings(context_window_tokens=None, max_context_chars=11000), phase="review", archive=archive)
    assert not archive.rows


def test_retrieval_is_not_a_new_scientific_execution():
    messages = [Message("assistant", tool_calls=(ToolCall("read", "context_read", {"evidence_id": "ev_x"}),)),
                ToolResult("read", "context_read", "ok", {"content": "prior result"}).message()]
    assert observations(messages)[0]["evidence_role"] == "retrieval"
    assert successful_evidence_ids(messages) == []


def test_native_retrieval_schemas_never_accept_an_owner_or_conversation_argument():
    registry = ToolRegistry()
    register_context_tools(registry, Archive())
    for name in ("context_read", "context_search"):
        schema = registry.get(name).definition.input_schema
        assert schema["additionalProperties"] is False
        assert "owner_id" not in schema["properties"]
        assert "conversation_id" not in schema["properties"]
        assert all(v.get("description") for v in schema["properties"].values())


@pytest.mark.parametrize("owner,conversation", [("", "c"), ("u", ""), (None, "c")])
def test_missing_authenticated_scope_is_rejected(owner, conversation):
    with pytest.raises(ValueError):
        ContextScope(owner, conversation)

"""Avoid archive/read-back loops caused by treating headroom as a hard limit."""
from copy import deepcopy
import hashlib
import json

import pytest

from geological_agent.agent.compaction import (
    ContextOverflow, _history_view, _json_messages, fit_request, request_size)
from geological_agent.agent.context import ContextManager
from geological_agent.contracts import Message, ModelRequest, ToolCall, ToolResult
from geological_agent.settings import Settings


class Archive:
    def __init__(self):
        self.records = {}

    def put(self, run_id, kind, source_key, payload, label=""):
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        identity = "ev_" + digest
        self.records[identity] = deepcopy(payload)
        return {"evidence_id": identity, "source_run_id": run_id, "kind": kind, "sha256": digest}


def fixture():
    messages = [Message("user", "Use actual source and professional results. Do not rerun to recall them.")]
    for index in range(3):
        identity = "c" + str(index)
        messages.extend([
            Message("assistant", tool_calls=(ToolCall(identity, "actual_tool", {"input": index}),)),
            ToolResult(identity, "actual_tool", "ok", {
                "value": index + .125, "unit": "J", "source_text": chr(65 + index) * 3600}).message()])
    state = {"run_id": "a" * 32, "task": messages[0].content,
             "messages": messages, "metadata": {}}
    request = ModelRequest((Message("system", "Preserve exact observations."), *messages), ())
    return state, request


def test_fitting_request_does_not_archive_evidence_just_for_soft_headroom():
    state, request = fixture()
    archive = Archive()
    original = deepcopy(state)
    limit = request_size(request) + 1
    assert request_size(request) > int(limit * .9)
    result = fit_request(request, state, Settings(context_window_tokens=None, max_context_chars=limit), archive=archive)
    assert request_size(result) <= limit
    assert not archive.records
    assert state["messages"] == original["messages"]
    ContextManager._blocks(result.messages)


def test_largest_recent_native_suffix_uses_actual_allowance_not_ninety_percent():
    state, request = fixture()
    archive = Archive()
    two = _json_messages(_history_view(request, state, archive=archive,
                                     index_budget=0, retain_exchanges=2), state)
    limit = request_size(two) + 1
    assert request_size(request) > limit
    assert request_size(two) > int(limit * .9)
    archive.records.clear()
    result = fit_request(request, state, Settings(context_window_tokens=None, max_context_chars=limit), archive=archive)
    assert request_size(result) <= limit
    native = {m.tool_call_id: json.loads(m.content) for m in result.messages if m.role == "tool"}
    assert {"c1", "c2"} <= set(native)
    assert native["c1"]["data"]["source_text"] == "B" * 3600
    assert native["c2"]["data"]["source_text"] == "C" * 3600
    assert native["c1"]["data"]["value"] == 1.125
    assert native["c2"]["data"]["unit"] == "J"
    assert any(any(m.get("tool_call_id") == "c0" for m in value["messages"])
               for value in archive.records.values())
    assert len(state["messages"]) == 7
    ContextManager._blocks(result.messages)


def test_actual_allowance_does_not_relax_protected_user_constraint_limit():
    state, request = fixture()
    protected = Message("user", "Exact user constraint " * 5000)
    state["messages"] = [protected]
    state["task"] = protected.content
    request = ModelRequest((Message("system", "Policy"), protected), ())
    with pytest.raises(ContextOverflow, match="Current user instructions"):
        fit_request(request, state, Settings(context_window_tokens=None, max_context_chars=10000), archive=Archive())
    assert state["messages"] == [protected]

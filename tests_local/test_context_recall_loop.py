"""Regression for premature eviction and recursive archive read amplification."""
from copy import deepcopy
from dataclasses import asdict, replace
import json

from geological_agent.agent.compaction import _history_view, dumps, fingerprint, fit_request, request_size
from geological_agent.agent.context import ContextManager
from geological_agent.contracts import Message, ModelRequest, ToolCall, ToolResult
from geological_agent.llm import LocalChatClient
from geological_agent.model_context import native_context
from geological_agent.settings import Settings
from geological_agent.tools import ToolDefinition, object_schema


class Archive:
    def __init__(self):
        self.records = {}

    def put(self, run_id, kind, source_key, payload, label=""):
        identity = fingerprint([run_id, kind, source_key])
        raw = dumps(payload)
        if identity in self.records:
            assert self.records[identity] == raw, "Immutable originals changed"
        self.records[identity] = raw
        return {"evidence_id": identity, "source_run_id": run_id, "kind": kind,
                "sha256": fingerprint(payload), "total_chars": len(raw)}


def test_budget_matches_transmitted_native_context_not_unused_output_schema():
    tool = ToolDefinition("inspect", "Inspect", "When needed", object_schema({}),
                          {"description": "validation-only " * 10000})
    request = ModelRequest((Message("user", "Inspect the file."),), (tool,))
    client = LocalChatClient()
    try:
        wire = client._body(request)
    finally:
        client.close()
    transmitted = {key: wire[key] for key in ("messages", "tools", "tool_choice")}
    assert native_context(request) == transmitted
    assert request_size(request) == len(json.dumps(transmitted, ensure_ascii=False, allow_nan=False))
    assert request_size(request) < 1000
    enlarged_input = replace(tool, input_schema={"description": "input " * 1000})
    assert request_size(replace(request, tools=(enlarged_input,))) > request_size(request) + 5000


def test_compaction_keeps_recent_observations_when_they_fit():
    messages = [Message("user", "Use observed results.")]
    for i in range(8):
        call = ToolCall("c" + str(i), "inspect", {"i": i})
        messages += [Message("assistant", tool_calls=(call,)),
                     ToolResult(call.id, call.name, "ok", {"text": chr(65 + i) * 2600}).message()]
    state = {"run_id": "run", "task": messages[0].content, "messages": messages, "metadata": {}}
    before = deepcopy(messages)
    archive = Archive()
    fitted = fit_request(ModelRequest(tuple(messages), ()), state,
                         Settings(max_context_chars=12000), archive=archive)
    assert request_size(fitted) <= 12000
    ContextManager._blocks(fitted.messages)
    assert sum(m.role == "tool" for m in fitted.messages) >= 2
    assert fitted.messages[-1] == messages[-1]
    assert state["messages"] == before
    for i in range(8):
        result = messages[2 + i * 2]
        assert result in fitted.messages or any(result.content in
            [m.get("content") for m in json.loads(raw).get("messages", [])]
            for raw in archive.records.values())


def test_recursive_retrieval_receipts_are_linked_not_nested():
    archive = Archive()
    observed = {"value": 17.25, "unit": "km", "source": "test-only"}
    source_ref = archive.put("run", "exchange", "scientific", observed)
    messages = [Message("user", "Recover earlier observations.")]
    initial = deepcopy(messages)
    lengths = []
    for i in range(12):
        raw = archive.records[source_ref["evidence_id"]]
        call = ToolCall("read" + str(i), "context_read", {"evidence_id": source_ref["evidence_id"]})
        receipt = ToolResult(call.id, call.name, "ok", {**source_ref, "content": raw,
            "offset": 0, "next_offset": len(raw), "has_more": False}).message()
        block = [Message("assistant", tool_calls=(call,)), receipt]
        messages += block
        tail = [Message("assistant", tool_calls=(ToolCall("last", "inspect", {}),)),
                ToolResult("last", "inspect", "ok").message()]
        state = {"run_id": "run", "messages": [*messages, *tail], "metadata": {}}
        original = deepcopy(state["messages"])
        _history_view(ModelRequest(tuple(state["messages"]), ()), state,
                      archive=archive, index_budget=50000)
        # Locate this retrieval's linked exchange, not its full message receipt.
        entry = next(json.loads(value) for value in archive.records.values()
                     if json.loads(value).get("representation") == "linked-native-exchange-v1"
                     and json.loads(value)["messages"][0]["tool_calls"][0]["id"] == call.id)
        linked = entry["messages"][1]
        exact_receipt = json.loads(archive.records[linked["original_message"]["evidence_id"]])
        assert exact_receipt == json.loads(dumps(asdict(receipt)))
        assert json.loads(exact_receipt["content"])["data"]["content"] == raw
        assert state["messages"] == original
        source_ref = archive.put("run", "exchange", fingerprint(entry), entry)
        lengths.append(len(dumps(entry)))
    assert max(lengths) < 2000
    assert max(lengths) - min(lengths) < 100
    assert messages[0] == initial[0]
    assert json.loads(archive.records[archive.put("run", "exchange", "scientific", observed)["evidence_id"]]) == observed

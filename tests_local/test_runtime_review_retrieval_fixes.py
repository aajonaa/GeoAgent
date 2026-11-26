"""Synthetic regression data; no network or model service is needed."""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from threading import Event
from types import SimpleNamespace

import pytest

from geological_agent.agent.compaction import ContextOverflow, fit_request, request_size, unpack_data
from geological_agent.agent.completion import completion_evidence, review_request
from geological_agent.agent.knowledge_semantics import (
    SemanticReviewProtocolError, material, parse_semantic_review, semantic_request)
from geological_agent.agent.retrieval_progress import observation_key, redirect_request, unchanged
from geological_agent.agent.semantic_recovery import review_sources
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import ErrorInfo, Message, ModelEvent, ModelRequest, ModelResponse, ToolCall, ToolResult
from geological_agent.settings import Settings
from geological_agent.tools import ToolExecutionContext, ToolFailure, ToolRegistry
from geological_agent.tracing import NullTrace
from geological_agent import web_tools

CID = "K" + "a" * 32 + "_1"
NOTE = "Synthetic test source: hydrogen sulfide detector. Methane monitoring is a separate observation."


@pytest.fixture(autouse=True)
def isolated_flags(monkeypatch):
    for key in ("GEOTOOL_INTENT_REVIEW", "GEOTOOL_COMBINED_COMPLETION_REVIEW",
                "GEOTOOL_OPTIMIZE_ROUND_TRIPS", "GEOTOOL_REQUIREMENT_COVERAGE",
                "GEOTOOL_COMPACT_REVIEW", "GEOTOOL_COMPACT_DISCOVERY", "GEOTOOL_REVIEW_REFERENCE_SETS"):
        monkeypatch.delenv(key, raising=False)


def source_state():
    return {"run_id": "a" * 32, "task": "Summarize the supplied source.", "answer":
            "The source mentions a hydrogen sulfide detector [" + CID + "].\n\n"
            "It separately mentions Methane monitoring [" + CID + "].",
            "status": "running", "model_turns": 0, "metadata": {"usage": [], "knowledge": {
                "references": [{"citation_id": CID, "document_id": "a" * 32, "title": "Synthetic source",
                                "source": "Synthetic test record", "text": NOTE, "sha256": "b" * 64}]}}}


def supported():
    return {"verdict": "supported", "source_quotes": [
        {"source_id": CID, "field": "text", "quote": NOTE}], "translations": [], "feedback": ""}


def native(name, arguments, identity="audit"):
    return ModelResponse(tool_calls=(ToolCall(identity, name, arguments),), finish_reason="tool_calls")


class Model:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        item = next(self.responses)
        return item(request) if callable(item) else item

    def stream(self, request):
        yield ModelEvent("response", response=self.invoke(request))


def review():
    return native("assess_completion", {"verdict": "complete", "feedback": "", "required_outputs": [],
        "requires_python_execution": False, "evidence_call_ids": []})


def test_semantic_retry_keeps_valid_blocks_and_rechecks_only_failed_blocks():
    state = source_state()
    assert set(material(state)["answer_blocks"]) == {"b1", "b2"}
    request = semantic_request(state, Settings())
    with pytest.raises(SemanticReviewProtocolError) as caught:
        parse_semantic_review(native("assess_knowledge_semantics", {
            "checks": {"b1": supported(), "b2": {**supported(), "source_quotes": []}}}), request)
    assert set(caught.value.checks) == {"b1"} and not caught.value.issues
    assert set(caught.value.block_errors) == {"b2"}
    retry = semantic_request(state, Settings(), block_ids=["b2"])
    assert set(json.loads(retry.messages[1].content)["answer_blocks"]) == {"b2"}
    assert parse_semantic_review(native("assess_knowledge_semantics", {"checks": {"b2": supported()}}), retry)["passed"]


def test_valid_revision_survives_another_invalid_block_without_approval():
    request = semantic_request(source_state(), Settings())
    with pytest.raises(SemanticReviewProtocolError) as caught:
        parse_semantic_review(native("assess_knowledge_semantics", {"checks": {
            "b1": {**supported(), "verdict": "revise", "feedback": "Preserve the source limitation."},
            "b2": {**supported(), "source_quotes": []}}}), request)
    assert caught.value.issues == ["Source semantics b1: Preserve the source limitation."]
    assert "b2" not in caught.value.checks


def test_incremental_runtime_does_not_rerun_a_valid_block():
    state = source_state()
    model = Model(native("assess_knowledge_semantics", {"checks": {
                      "b1": supported(), "b2": {**supported(), "source_quotes": []}}}),
                  native("assess_knowledge_semantics", {"checks": {"b2": supported()}}))
    events = []
    result, issues = review_sources(state, settings=Settings(), model=model, cancel=Event(),
        record=lambda update, current: update, trace=NullTrace(),
        activity=lambda kind, **kw: events.append((kind, kw)),
        pause=lambda *args: pytest.fail("A corrected review must not pause"))
    assert not issues and result["status"] == "running" and result["model_turns"] == 2
    assert set(json.loads(model.requests[1].messages[1].content)["answer_blocks"]) == {"b2"}
    assert result["metadata"]["knowledge_semantic_reviews"][-1]["complete_coverage"]
    assert "semantic_pending_draft" not in result["metadata"]


def test_alternating_review_errors_are_detected_as_a_cycle():
    model = Model(ModelResponse("approved"), native("assess_knowledge_semantics", {"checks": {}}), ModelResponse("approved"))
    paused = []
    def pause(state, phase, error):
        paused.append((phase, error))
        return {**state, "status": "needs_input", "answer": ""}
    result, issues = review_sources(source_state(), settings=Settings(max_model_turns=None),
        model=model, cancel=Event(), record=lambda update, current: update,
        trace=NullTrace(), activity=lambda *args, **kwargs: None, pause=pause)
    assert not issues and result["status"] == "needs_input" and len(model.requests) == 3
    assert paused[0][0] == "knowledge_semantics"
    assert result["metadata"]["semantic_pending_draft"]["answer"]


def test_review_pause_resume_preserves_tools_and_candidate(tmp_path):
    first_model = Model(native("write_file", {"path": "actual.txt", "content": "42"}, "w1"),
                        ModelResponse("Created actual.txt with 42."), ModelResponse(""), ModelResponse(""))
    work, checkpoint = tmp_path / "work", tmp_path / "checkpoint.sqlite3"
    first = create_agent(first_model, human_input=True).run(
        "Create actual.txt containing 42.", workspace=work, checkpoint_path=checkpoint)
    assert first.status == "needs_input", first.reason
    pending = first.state["metadata"]["pending_input"]
    assert pending["recovery_phase"] == "review:execution"
    assert sum(m.role == "tool" for m in first.state["messages"]) == 1
    resumed_model = Model(review(), ModelResponse("Created actual.txt with 42."), review())
    resumed = create_agent(resumed_model, human_input=True).run("Continue", workspace=work,
        checkpoint_path=checkpoint, resume={"run_id": first.run_id, "request_id": pending["id"],
                                            "text": "Retry assessment", "files": []})
    assert resumed.status == "completed", resumed.reason
    assert resumed_model.requests[0].tools[0].name == "assess_completion"
    assert (work / "actual.txt").read_text() == "42"
    assert sum(m.role == "tool" for m in resumed.state["messages"]) == 1
    assert not resumed.state["metadata"].get("resume_review_candidate")
    assert not resumed.state["metadata"].get("protocol_recovery")


class Archive:
    def __init__(self):
        self.rows = {}

    def put(self, run_id, kind, key, payload, label=""):
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        identity = "ev_" + hashlib.sha256(raw.encode()).hexdigest()
        self.rows[identity] = deepcopy(payload)
        return {"evidence_id": identity, "sha256": identity[3:], "kind": kind,
                "source_run_id": run_id, "total_chars": len(raw)}


@pytest.mark.parametrize("phase", ["review", "final_answer"])
def test_completion_archive_keeps_successful_evidence_and_original_state(phase):
    messages = [Message("user", "Deliver the actually computed result.")]
    failed_data = {"execution_trace_path": ".agent/execution/bad.json",
                   "execution_events": [{"i": i, "failure": "different_" + str(i) + "_" * 50} for i in range(400)]}
    bad = ToolCall("bad", "execute_python", {"path": "bad.py"})
    good = ToolCall("good", "GeoSynthetic", {"value": 42})
    messages += [Message("assistant", tool_calls=(bad,)),
                 ToolResult("bad", bad.name, "error", failed_data, error=ErrorInfo("failed", "Original failure")).message(),
                 Message("assistant", tool_calls=(good,)),
                 ToolResult("good", good.name, "ok", {"value": 42, "unit": "km"}).message()]
    state = {"run_id": "b" * 32, "task": messages[0].content, "messages": messages,
             "metadata": {}, "artifacts": [], "answer": "42 km"}
    original = deepcopy(state)
    payload = completion_evidence(state, None)
    request = ModelRequest((Message("system", "Audit actual evidence."), Message("user", json.dumps(payload))), ())
    archive = Archive()
    fitted = fit_request(request, state, Settings(context_window_tokens=None, max_context_chars=8000), phase=phase, archive=archive)
    data = unpack_data(json.loads(fitted.messages[1].content))
    assert request_size(fitted) <= 8000 < request_size(request)
    assert state["messages"] == original["messages"] and state["answer"] == original["answer"]
    assert data["observed_actions"][1] == payload["observed_actions"][1]
    failed = data["observed_actions"][0]["result"]
    assert failed["error"] == payload["observed_actions"][0]["result"]["error"]
    assert archive.rows[failed["data"]["archived_data"]["evidence_id"]] == failed_data
    assert data["task"] == original["task"]
    assert state["metadata"]["context_compactions"][-1]["retrieval_required"]


def test_successful_execution_is_not_replaced_with_an_unseen_archive():
    data = {"actual_assertions": [{"n": n, "expression": "x" * 50 + str(n)} for n in range(300)]}
    state = {"run_id": "c" * 32, "task": "Verify every assertion.", "messages": [], "metadata": {}}
    payload = {"task": state["task"], "source_evidence_policy": "Keep proof.", "observed_actions": [
        {"call": {"id": "ok"}, "result": {"call_id": "ok", "name": "execute_python", "status": "ok", "data": data}}]}
    archive = Archive()
    with pytest.raises(ContextOverflow):
        fit_request(ModelRequest((Message("user", json.dumps(payload)),), ()), state,
                    Settings(context_window_tokens=None, max_context_chars=3000), phase="review", archive=archive)
    assert not archive.rows


def test_search_progress_ignores_timestamp_query_and_order_not_new_content():
    first = {"query": "a", "results": [{"url": "https://example.org", "snippet": "Source A"}], "retrieved_at": "yesterday"}
    later = {**first, "query": "different wording", "retrieved_at": "today", "cache_hit": True}
    assert unchanged("web_search", {"query": "a"}, later, "web_search", {"query": "b"}, first)
    changed = {**later, "results": [{"url": "https://example.org", "snippet": "Source B"}]}
    assert observation_key("web_search", changed) != observation_key("web_search", first)
    assert not unchanged("GeoSynthetic", {}, later, "GeoSynthetic", {}, first)


def test_search_redirect_lasts_only_one_request_and_preserves_original():
    tool = SimpleNamespace(name="web_search")
    inspect = SimpleNamespace(name="web_fetch")
    original = ModelRequest((Message("user", "Find a real dataset."),), (tool, inspect))
    redirected = redirect_request(original, ["web_search"])
    assert [t.name for t in redirected.tools] == ["web_fetch"]
    assert len(original.tools) == 2
    assert "next decision" in redirected.messages[-1].content


def test_search_snapshot_refresh_and_run_isolation(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(web_tools, "_post", lambda endpoint, payload, ctx:
                        calls.append(payload) or {"results": [{"url": "https://example.org", "content": "Real provider fixture"}]})
    ctx = ToolExecutionContext("run-one", tmp_path, ("web_search",), Settings(), Event())
    first = web_tools.web_search({"query": "LITHO node"}, ctx).data
    second = web_tools.web_search({"query": "  litho   NODE  "}, ctx).data
    assert len(calls) == 1 and second["cache_hit"] and not first["cache_hit"]
    assert second["retrieved_at"] == first["retrieved_at"] and second["results"] == first["results"]
    web_tools.web_search({"query": "LITHO node", "refresh": True}, ctx)
    assert len(calls) == 2
    web_tools.web_search({"query": "LITHO node"}, replace(ctx, run_id="run-two"))
    assert len(calls) == 3


def test_invalid_search_cache_is_explicit_not_replaced_silently(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(web_tools, "_post", lambda *args: calls.append(True) or {"results": []})
    ctx = ToolExecutionContext("one", tmp_path, ("web_search",), Settings(), Event())
    web_tools.web_search({"query": "public dataset"}, ctx)
    path = next((tmp_path / ".agent/web").glob("search-*.json"))
    path.write_text("corrupted", encoding="utf-8")
    with pytest.raises(ToolFailure, match="refresh=true"):
        web_tools.web_search({"query": "public dataset"}, ctx)
    assert len(calls) == 1


@pytest.mark.parametrize("phase", ["review", "final_answer"])
def test_completion_archives_old_file_reads_with_hashes_not_calculations(phase):
    task = "Report the observed result, retaining source provenance."
    source = "\n".join(f"source row {i}: unique field {i * 17}, raw geological observation" for i in range(500))
    checksum = hashlib.sha256(source.encode()).hexdigest()
    old_data = {"path": "input.txt", "content": source, "offset": 0,
                "next_offset": len(source), "truncated": False, "sha256": checksum}
    messages = [Message("user", task)]
    for identity in ("read1", "read2"):
        call = ToolCall(identity, "read_file", {"path": "input.txt"})
        messages += [Message("assistant", tool_calls=(call,)),
                     ToolResult(identity, call.name, "ok", old_data,
                                evidence={"source_kind": "user_supplied"}).message()]
    calculated = ToolCall("computed", "GeoSynthetic", {"value": 42})
    latest = ToolCall("latest", "read_file", {"path": "result.txt"})
    messages += [Message("assistant", tool_calls=(calculated,)),
                 ToolResult(calculated.id, calculated.name, "ok", {"value": 42, "unit": "km"}).message(),
                 Message("assistant", tool_calls=(latest,)),
                 ToolResult(latest.id, latest.name, "ok", {"path": "result.txt", "content": "42 km",
                     "sha256": hashlib.sha256(b"42 km").hexdigest(), "truncated": False}).message()]
    state = {"run_id": "d" * 32, "task": task, "messages": messages,
             "metadata": {}, "artifacts": [], "answer": "42 km"}
    original = deepcopy(state)
    payload = completion_evidence(state, None)
    request = ModelRequest((Message("system", "Audit exact source evidence."),
                            Message("user", json.dumps(payload))), ())
    archive = Archive()
    fitted = fit_request(request, state, Settings(context_window_tokens=None, max_context_chars=6000), phase=phase, archive=archive)
    records = unpack_data(json.loads(fitted.messages[1].content))["observed_actions"]
    assert request_size(fitted) <= 6000 < request_size(request)
    assert state["messages"] == original["messages"] and state["answer"] == original["answer"]
    for before, after in zip(payload["observed_actions"][:2], records[:2]):
        receipt = after["result"]["data"]
        assert receipt["sha256"] == checksum and receipt["path"] == old_data["path"]
        assert receipt["offset"] == 0 and receipt["next_offset"] == len(source) and not receipt["truncated"]
        assert archive.rows[receipt["archived_data"]["evidence_id"]] == old_data
        restored = deepcopy(after)
        restored["result"]["data"] = archive.rows[receipt["archived_data"]["evidence_id"]]
        assert restored == before
    assert records[2:] == payload["observed_actions"][2:]


def test_completion_does_not_externalize_the_only_file_read():
    source = "sole source " * 1000
    state = {"run_id": "e" * 32, "task": "Inspect the source.", "messages": [], "metadata": {}}
    payload = {"task": state["task"], "source_evidence_policy": "Read actual source.",
               "observed_actions": [{"call": {"id": "read"}, "result": {
                   "call_id": "read", "name": "read_file", "status": "ok",
                   "data": {"path": "only.txt", "content": source}}}]}
    archive = Archive()
    with pytest.raises(ContextOverflow):
        fit_request(ModelRequest((Message("user", json.dumps(payload)),), ()), state,
                    Settings(context_window_tokens=None, max_context_chars=3000), phase="review", archive=archive)
    assert not archive.rows

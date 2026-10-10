"""Transport/UI publication tests use synthetic packets, never a paid model."""
import json
from threading import Event
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from geological_agent.contracts import Message, ModelEvent, ModelRequest, ModelResponse, ToolCall
from geological_agent.llm import LocalChatClient, ModelProtocolError
from geological_agent.team.isolation import Cancelled
from geological_agent.team.streaming import RunProgress, StreamRedactor, consume_model_stream
from geological_agent.team.server import create_app
from test_team import group, NoTrace
from test_required_stream_transport import make_request, sse_response


@pytest.mark.parametrize("value", ["private-key-123456", "Bearer sk_abcd123456", "lsv2_pt_testsecret"])
def test_redaction_across_every_packet_boundary(value):
    raw = "before " + value + " after"
    for size in range(1, len(raw)):
        mask = StreamRedactor(("private-key-123456",))
        output = mask.feed(raw[:size]) + mask.feed(raw[size:]) + mask.feed("", final=True)
        assert value not in output
        assert output.startswith("before ") and output.endswith(" after")
        assert "[REDACTED]" in output


def test_normal_text_is_lossless_one_character_at_a_time():
    text = "B Bx lsvx everyday text.\n" + "\u5730\u8d28" * 2000
    mask = StreamRedactor(("private-secret",))
    assert "".join(mask.feed(c) for c in text) + mask.feed("", final=True) == text


def test_external_required_uses_stream_once_and_assembles_native_call():
    sent = []
    def http(request):
        sent.append(json.loads(request.content))
        return sse_response()
    client = LocalChatClient(transport=httpx.MockTransport(http), required_streaming=True)
    try:
        events = list(client.stream(make_request()))
        assert len(sent) == 1 and sent[0]["stream"] is True
        assert events[-1].response.tool_calls[0].id == "call_compute"
        assert json.loads(events[-1].response.tool_calls[0].arguments)["code"].startswith("def value")
    finally:
        client.close()


def test_live_fragments_arrive_before_completed_response_and_evidence_is_unchanged():
    events = []
    progress = RunProgress(events.append, ("sensitive-key",))
    response = ModelResponse("draft sensitive-key", (ToolCall("native-id", "tool", '{"x":[1,2]}'),), "tool_calls")
    class Client:
        def stream(self, request):
            yield ModelEvent("text_delta", "draft ")
            assert any(e["kind"] == "stream_delta" for e in events)
            assert not any(e["kind"] == "stream_end" for e in events)
            yield ModelEvent("text_delta", "sensitive-")
            yield ModelEvent("text_delta", "key")
            yield ModelEvent("response", response=response)
    actual = consume_model_stream(Client(), make_request("auto"), progress, progress.begin_model(), Event())
    assert actual is response
    assert actual.tool_calls[0].arguments == '{"x":[1,2]}'
    text = "".join(e["text"] for e in events if e["kind"] == "stream_delta")
    assert text == "draft [REDACTED]" and all(e.get("verified") is not True for e in events)
    progress.close()


@pytest.mark.parametrize("phase", ["review", "context_compaction", "vision"])
def test_internal_drafts_are_not_public(phase):
    events = []
    progress = RunProgress(events.append)
    progress.model_phase = phase
    class Client:
        def stream(self, request):
            yield ModelEvent("text_delta", "internal text")
            yield ModelEvent("reasoning_delta", "internal process")
            yield ModelEvent("response", response=ModelResponse("internal text"))
    consume_model_stream(Client(), make_request("auto"), progress, progress.begin_model(), Event())
    assert not any(e["kind"] == "stream_delta" for e in events)


def test_partial_stream_fails_without_retry_or_native_dispatch():
    events, attempts = [], []
    progress = RunProgress(events.append)
    class Client:
        def stream(self, request):
            attempts.append(True)
            yield ModelEvent("text_delta", "not a completed result")
    with pytest.raises(ModelProtocolError):
        consume_model_stream(Client(), make_request("auto"), progress, progress.begin_model(), Event())
    assert attempts == [True]
    assert [e["complete"] for e in events if e["kind"] == "stream_end"] == [False]


def test_cancelled_stream_cannot_publish_after_run_closed():
    events = []
    progress = RunProgress(events.append)
    cancel = Event()
    class Client:
        def stream(self, request):
            yield ModelEvent("text_delta", "initial")
            progress.close()
            cancel.set()
            yield ModelEvent("response", response=ModelResponse("must not return"))
    with pytest.raises(Cancelled):
        consume_model_stream(Client(), make_request("auto"), progress, progress.begin_model(), cancel)
    assert events[-1]["kind"] == "stage_timing" and events[-1]["active"] is None


def test_exclusive_timing_and_nested_model_return_to_tools():
    now, events = [0.0], []
    progress = RunProgress(events.append, clock=lambda: now[0], wall=lambda: 100 + now[0])
    now[0] = 1
    progress.observe("tool_requested", {"call": {"id": "tool"}})
    now[0] = 3
    call = progress.begin_model()
    assert call["return_stage"] == "tools"
    now[0] = 4
    progress.switch("model_wait")
    now[0] = 6
    progress.switch("model_stream")
    now[0] = 8
    progress.switch(call["return_stage"])
    now[0] = 9
    progress.observe("tool_completed", {"result": {"call_id": "tool"}})
    now[0] = 10
    progress.close()
    assert sum(events[-1]["totals_seconds"].values()) == 10
    assert events[-1]["totals_seconds"]["tools"] == 3
    assert progress.tool_durations["tool"] == 8


def test_history_owner_checks_snapshot_pagination_and_summary(group):
    app, clients = group
    alice, bob = clients["alice"], clients["bob"]
    store = app.state.store
    uid = alice.get("/api/me").json()["id"]
    cid = alice.post("/api/conversations").json()["id"]
    rid = store.begin(uid, cid, "history packet fixture")
    store.event(rid, {"kind": "model_config", "profile": {"model": "fixture"}})
    for index in range(85):
        store.event(rid, {"kind": "status", "message": str(index)})
    store.event(rid, {"kind": "stage_timing", "active": None, "totals_seconds": {"model_wait": 2.0}})
    store.finish(rid, status="completed", answer="fixture answer")
    assert bob.get(f"/api/runs/{rid}/history").status_code == 404
    assert clients["admin"].get(f"/api/runs/{rid}/history").status_code == 404
    first = alice.get(f"/api/runs/{rid}/history?limit=7").json()
    assert len(first["events"]) == 7 and first["has_more"]
    store.event(rid, {"kind": "status", "message": "outside snapshot"})
    seen, page = list(first["events"]), first
    while page["has_more"]:
        page = alice.get(f"/api/runs/{rid}/history?limit=7&after={page['next']}&through={first['through']}").json()
        seen.extend(page["events"])
    assert len(seen) == 88 and len({r["id"] for r in seen}) == 88
    assert not any(r["data"].get("message") == "outside snapshot" for r in seen)
    summary = alice.get(f"/api/runs/{rid}").json()
    assert summary["activity"]["profile"]["model"] == "fixture"
    assert summary["activity"]["timing"]["totals_seconds"]["model_wait"] == 2.0
    assert "events" not in summary
    assert alice.get(f"/api/runs/{rid}/history?limit=101").status_code == 400
    assert alice.get(f"/api/runs/{rid}/history?after=-1").status_code == 400
    assert store.receipt_events(uid, rid) == []


def test_history_never_slices_large_evidence(group):
    app, clients = group
    client = clients["alice"]
    uid = client.get("/api/me").json()["id"]
    cid = client.post("/api/conversations").json()["id"]
    store = app.state.store
    rid = store.begin(uid, cid, "large evidence fixture")
    raw = "x" * 180000
    store.event(rid, {"kind": "tool_result", "result": {"call_id": "large", "data": {"raw": raw}}})
    store.finish(rid, status="completed")
    result = client.get(f"/api/runs/{rid}/history").json()
    assert len(result["events"]) == 1 and result["has_more"]
    assert result["events"][0]["data"]["result"]["data"]["raw"] == raw
    assert store.receipt_events(uid, rid)[0]["result"]["data"]["raw"] == raw


def test_http_broker_publishes_delta_while_model_still_running(tmp_path):
    release, emitted = Event(), Event()
    class Client:
        def stream(self, request):
            yield ModelEvent("text_delta", "live unreviewed packet")
            emitted.set()
            assert release.wait(8)
            yield ModelEvent("response", response=ModelResponse("completed response"))
        def close(self):
            pass
    class Runner:
        def run(self, rid, query, files, cancel, model_call, on_trace, **kwargs):
            on_trace("model_requested", {"phase": "execution", "turn": 1})
            response = model_call(ModelRequest((Message("user", "fixture"),), ()), cancel)
            return {"status": "completed", "answer": response.content, "files": {}}
        def stop(self, rid):
            pass
    app = create_app(tmp_path, runner=Runner(), model_factory=Client, trace_factory=lambda _: NoTrace())
    store = app.state.store
    store.create_user("streamuser", "stream-fixture-password", role="admin", initial_admin=True)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        result = client.post("/api/login", json={"username":"streamuser", "password":"stream-fixture-password"})
        client.headers["x-csrf-token"] = result.json()["csrf"]
        cid = client.post("/api/conversations").json()["id"]
        rid = client.post(f"/api/conversations/{cid}/runs", json={"query":"test streaming"}).json()["id"]
        try:
            assert emitted.wait(5)
            run = client.get(f"/api/runs/{rid}").json()
            assert run["status"] == "running" and run["answer"] == ""
            page = client.get(f"/api/runs/{rid}/history").json()
            assert any(e["data"]["kind"] == "stream_delta" for e in page["events"])
            assert not any(e["data"]["kind"] == "finished" for e in page["events"])
        finally:
            release.set()
        for _ in range(100):
            run = client.get(f"/api/runs/{rid}").json()
            if run["status"] != "running":
                break
            time.sleep(.02)
        assert run["answer"] == "completed response"
        assert run["activity"]["timing"]["active"] is None


@pytest.mark.parametrize("channel", ["text_delta", "reasoning_delta"])
def test_stream_offsets_count_unicode_code_points(channel):
    now, events = [0.0], []
    progress = RunProgress(events.append, clock=lambda: now[0])
    pieces = ["\u5730\u8d28 ", "\U0001f30d", " e\u0301", "\U00020000",
              "\U0001f469\u200d\U0001f52c", "\U0001f1e8\U0001f1f3", "\ncomplete"]
    class Client:
        def stream(self, request):
            for piece in pieces:
                now[0] += 0.2
                yield ModelEvent(channel, piece)
            yield ModelEvent("response", response=ModelResponse("".join(pieces)))
    result = consume_model_stream(Client(), make_request("auto"), progress, progress.begin_model(), Event())
    deltas = [item for item in events if item["kind"] == "stream_delta"]
    expected, cursor = [], 0
    for piece in pieces:
        expected.append(cursor)
        cursor += len(piece)
    assert [item["offset"] for item in deltas] == expected
    assert "".join(item["text"] for item in deltas) == "".join(pieces) == result.content

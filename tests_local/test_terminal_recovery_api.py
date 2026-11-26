import queue
from threading import Condition, Event
from types import SimpleNamespace
import time

from fastapi.testclient import TestClient
import pytest

from geological_agent.team.server import COOKIE, create_app


class NoTrace:
    def emit(self, *args, **kwargs):
        pass


class SyntheticRunner:
    isolated = False
    description = "Synthetic terminal-recovery test runner; no model"

    def __init__(self):
        self.arrivals = queue.Queue()
        self.calls = []
        self.condition = Condition()

    def stop(self, rid):
        pass

    def run(self, rid, query, files, cancel, model_call, on_trace, **kwargs):
        call = {"rid": rid, "query": query, "files": dict(files), "release": Event()}
        with self.condition:
            self.calls.append(call)
            self.condition.notify_all()
        self.arrivals.put(call)
        if not call["release"].wait(10):
            raise RuntimeError("Synthetic runner was not released")
        return {"status": "completed", "answer": "Recovery result", "reason": "", "turns": 0, "files": files}

    def wait_call(self):
        return self.arrivals.get(timeout=3)

    def release_all(self):
        with self.condition:
            calls = list(self.calls)
        for call in calls:
            call["release"].set()


def unexpected_model(*args, **kwargs):
    raise AssertionError("Terminal recovery tests must not call a real model")


@pytest.fixture(scope="module")
def group(tmp_path_factory):
    runner = SyntheticRunner()
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("GEOTOOL_TEAM_EXECUTION", "trusted")
        patch.setenv("GEOTOOL_EXECUTION_POLICY", "standard")
        patch.setenv("GEOTOOL_TRUSTED_PROCESS_OWNERSHIP", "0")
        patch.setenv("GEOTOOL_SANDBOX_PROCESS_OWNERSHIP", "0")
        patch.setenv("GEOTOOL_ISOLATED_CPU_PROCESS_OWNERSHIP", "0")
        app = create_app(tmp_path_factory.mktemp("terminal-recovery-api"), runner=runner,
                         model_factory=unexpected_model, memory_summarizer=unexpected_model,
                         trace_factory=lambda path: NoTrace())
    store = app.state.store
    store.create_user("recoveryadmin", "Recovery-Admin-Test-Password-2026", role="admin", initial_admin=True)
    users = {}
    for name in ("recoveryowner", "recoveryother"):
        uid = store.create_user(name, name.title() + "-Test-Password-2026", invite=store.invite())
        token, csrf = store.create_session(uid)
        users[name] = {"uid": uid, "token": token, "csrf": csrf}
    try:
        with TestClient(app, base_url="http://127.0.0.1") as owner, \
                TestClient(app, base_url="http://127.0.0.1") as other, \
                TestClient(app, base_url="http://127.0.0.1") as anonymous:
            for client, name in ((owner, "recoveryowner"), (other, "recoveryother")):
                client.cookies.set(COOKIE, users[name]["token"])
                client.headers["x-csrf-token"] = users[name]["csrf"]
            yield SimpleNamespace(app=app, store=store, runner=runner, owner=owner, other=other,
                                  anonymous=anonymous, uid=users["recoveryowner"]["uid"],
                                  other_uid=users["recoveryother"]["uid"])
    finally:
        runner.release_all()


def source_run(group, status="completed", *, owner=None, reason="", answer="Saved answer", events=()):
    store, uid = group.store, owner or group.uid
    cid = store.create_conversation(uid)["id"]
    generation = store.snapshot(uid, cid, {"result.txt": b"original result"}) if status not in ("running", "stopping") else ""
    rid = store.begin(uid, cid, "Original geological question")
    for event in events:
        store.event(rid, event)
    if status in ("running", "stopping"):
        if status == "stopping":
            store.db.execute("UPDATE runs SET status='stopping' WHERE id=?", (rid,))
            store.db.commit()
    else:
        store.finish(rid, status="stopped" if status == "cancelled" else status,
                     answer=answer, reason=reason, generation=generation)
        if status == "cancelled":
            store.db.execute("UPDATE runs SET status='cancelled' WHERE id=?", (rid,))
            store.db.commit()
    return cid, rid, generation


@pytest.mark.parametrize("status,action,phrase", [
    ("completed", "follow_up", "上一轮答复"),
    ("completed", "derive", "新增文件使用新名称"),
    ("stopped", "resume", "中断位置继续"),
    ("cancelled", "resume", "中断位置继续"),
    ("failed", "retry", "保留同一对话中的原始问题"),
    ("incomplete", "resume", "未完成步骤"),
    ("budget_exhausted", "resume", "未完成步骤"),
    ("interrupted", "resume", "未完成步骤"),
])
def test_terminal_recovery_matches_status_and_prepares_new_agent_run(group, status, action, phrase):
    cid, rid, generation = source_run(group, status)
    before = group.store.run(group.uid, rid)
    events = group.store.events(group.uid, rid, 0)
    response = group.owner.post(f"/api/runs/{rid}/recovery", json={"action": action})
    assert response.status_code == 200, response.text
    result = response.json()
    assert phrase in result["query"]
    assert result["mode"] == "agent" and result["execution"] == "new_run"
    assert result["source_run_id"] == rid and result["conversation_id"] == cid
    assert group.store.run(group.uid, rid) == before
    assert group.store.events(group.uid, rid, 0) == events
    assert group.store.file(group.uid, cid, "result.txt", generation) == b"original result"


@pytest.mark.parametrize("payload", [{}, {"action": "unknown"}, {"action": ["resume"]},
                                     {"action": "resume", "query": "injected"}, {"action": None}])
def test_terminal_recovery_rejects_invalid_actions_without_starting_work(group, payload):
    _, rid, _ = source_run(group)
    before = group.runner.calls
    response = group.owner.post(f"/api/runs/{rid}/recovery", json=payload)
    assert response.status_code == 400, response.text
    assert group.runner.calls == before


@pytest.mark.parametrize("status,action", [
    ("completed", "retry"), ("completed", "resume"), ("stopped", "follow_up"),
    ("failed", "resume"), ("needs_input", "resume"), ("running", "resume"), ("stopping", "resume"),
])
def test_terminal_recovery_rejects_status_mismatch(group, status, action):
    _, rid, _ = source_run(group, status)
    try:
        response = group.owner.post(f"/api/runs/{rid}/recovery", json={"action": action})
        assert response.status_code == 409, response.text
    finally:
        if status in ("running", "stopping"):
            group.store.finish(rid, status="failed", reason="Synthetic active-run fixture cleanup")


def test_terminal_recovery_requires_owner_and_csrf(group):
    _, rid, _ = source_run(group)
    assert group.anonymous.post(f"/api/runs/{rid}/recovery", json={"action": "follow_up"}).status_code == 401
    assert group.other.post(f"/api/runs/{rid}/recovery", json={"action": "follow_up"}).status_code == 404
    client = TestClient(group.app, base_url="http://127.0.0.1")
    client.cookies.set(COOKIE, group.owner.cookies.get(COOKIE))
    assert client.post(f"/api/runs/{rid}/recovery", json={"action": "follow_up"}).status_code == 403
    assert group.owner.post(f"/api/runs/{rid}/recovery", json={"action": "follow_up"},
                            headers={"Origin": "https://attacker.example"}).status_code == 403
    assert group.owner.post(f"/api/runs/{rid}/recovery", json={"action": "follow_up"},
                            headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_legacy_deadline_uses_partial_recovery_without_rewriting_source(group):
    _, rid, _ = source_run(group, "failed", reason="TimeoutError: Managed task execution deadline exceeded")
    response = group.owner.post(f"/api/runs/{rid}/recovery", json={"action": "resume"})
    assert response.status_code == 200, response.text
    assert "中断位置继续" in response.json()["query"]
    assert group.store.run(group.uid, rid)["status"] == "failed"


@pytest.mark.parametrize("status,action,answer", [
    ("completed", "follow_up", "Saved answer"),
    ("completed", "derive", "Saved answer"),
    ("stopped", "resume", ""),
    ("failed", "retry", ""),
    ("incomplete", "resume", ""),
])
def test_recovery_creates_new_run_with_source_context_and_preserves_original(group, status, action, answer):
    cid, rid, generation = source_run(group, status, answer=answer, events=[
        {"kind": "status", "message": "Original execution started"},
        {"kind": "tool_start", "id": "lookup", "name": "web_search",
         "arguments": {"query": "regional geology"}},
        {"kind": "tool_result", "id": "lookup", "name": "web_search",
         "result": {"status": "error", "message": "Partial tool receipt"}},
    ])
    before = group.store.run(group.uid, rid)
    events = group.store.events(group.uid, rid, 0)
    prepared = group.owner.post(f"/api/runs/{rid}/recovery", json={"action": action}).json()
    response = group.owner.post(f"/api/conversations/{cid}/runs", json={
        "query": prepared["query"], "mode": "agent", "source_run_id": rid, "recovery_action": action,
    })
    assert response.status_code == 200, response.text
    new_rid = response.json()["id"]
    assert new_rid != rid
    call = group.runner.wait_call()
    try:
        assert call["query"].endswith("\nCurrent user request:\n" + prepared["query"])
        assert '"recovery_source"' in call["query"]
        assert '"run_id":"' + rid + '"' in call["query"]
        assert '"query":"Original geological question"' in call["query"]
        assert '"status":"' + status + '"' in call["query"]
        assert '"message":"Partial tool receipt"' in call["query"]
        assert call["files"] == {"result.txt": b"original result"}
    finally:
        call["release"].set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if group.store.run(group.uid, new_rid)["status"] == "completed":
            break
        time.sleep(0.01)
    assert group.store.run(group.uid, new_rid)["status"] == "completed"
    new_events = [item["data"] for item in group.store.history(group.uid, new_rid)["events"]]
    assert {"kind": "recovery_source", "run_id": rid, "action": action} in new_events
    assert group.store.run(group.uid, rid) == before
    assert group.store.events(group.uid, rid, 0) == events
    assert group.store.file(group.uid, cid, "result.txt", generation) == b"original result"


def test_new_run_rejects_invalid_or_unauthorized_recovery_sources(group):
    cid, rid, _ = source_run(group)
    other_cid, _, _ = source_run(group)
    _, foreign_rid, _ = source_run(group, owner=group.other_uid)
    base = {"query": "Continue", "mode": "agent"}
    cases = [
        ({**base, "source_run_id": rid}, 400),
        ({**base, "recovery_action": "follow_up"}, 400),
        ({**base, "source_run_id": "bad", "recovery_action": "follow_up"}, 400),
        ({**base, "source_run_id": rid, "recovery_action": "retry"}, 409),
        ({**base, "source_run_id": foreign_rid, "recovery_action": "follow_up"}, 404),
        ({**base, "source_run_id": rid, "recovery_action": "follow_up", "mode": "ask"}, 400),
    ]
    before = group.runner.calls
    for payload, expected in cases:
        response = group.owner.post(f"/api/conversations/{cid}/runs", json=payload)
        assert response.status_code == expected, (payload, response.text)
    response = group.owner.post(f"/api/conversations/{other_cid}/runs", json={
        **base, "source_run_id": rid, "recovery_action": "follow_up",
    })
    assert response.status_code == 409, response.text
    assert group.runner.calls == before


def test_new_run_rejects_active_recovery_source_without_leaking_it(group):
    cid, rid, _ = source_run(group, "running")
    try:
        response = group.owner.post(f"/api/conversations/{cid}/runs", json={
            "query": "Continue", "mode": "agent", "source_run_id": rid, "recovery_action": "resume",
        })
        assert response.status_code == 409, response.text
    finally:
        group.store.finish(rid, status="failed", reason="Synthetic active-run fixture cleanup")

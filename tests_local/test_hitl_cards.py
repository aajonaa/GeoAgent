"""Task-bound HITL HTTP contracts; isolated synthetic stores, no real model."""
import time
import uuid
from threading import Event

import pytest
from fastapi.testclient import TestClient

from geological_agent.team.server import COOKIE, create_app
from geological_agent.team.store import digest
from geological_agent.tracing import JsonlTrace


class Runner:
    isolated = False

    def __init__(self):
        self.store = None
        self.calls = []

    def stop(self, rid):
        pass

    def run(self, rid, query, files, cancel, model_call, on_trace, **kwargs):
        claimed = self.store.input_for_reply(rid)
        self.calls.append(claimed)
        return {"status": "completed", "answer": "Reply received", "files": files, "turns": 0}


@pytest.fixture
def group(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_HITL", "1")
    monkeypatch.setenv("GEOTOOL_TEAM_EXECUTION", "trusted")
    runner = Runner()
    app = create_app(tmp_path, runner=runner, trace_factory=lambda path: JsonlTrace(path))
    store = runner.store = app.state.store
    clients = []
    with TestClient(app, base_url="http://127.0.0.1"):
        for name in ("alice", "bob"):
            token = "synthetic-" + name
            with store.lock, store.db:
                store.db.execute("INSERT INTO users(id,username,password,role) VALUES (?,?,?,?)",
                                 (name, name, "not-used", "member"))
                store.db.execute("INSERT INTO auth VALUES (?,?,?,?)",
                                 (digest(token), name, token + "-csrf", time.time() + 600))
            client = TestClient(app, base_url="http://127.0.0.1")
            client.cookies.set(COOKIE, token)
            client.headers["x-csrf-token"] = token + "-csrf"
            clients.append(client)
        yield app, clients[0], clients[1], runner
    for client in clients:
        client.close()


def pause(store, uid="alice", **extra):
    cid = store.create_conversation(uid)["id"]
    rid = store.begin(uid, cid, "Choose the coefficient")
    payload = {"id": uuid.uuid4().hex, "question": "Which coefficient?",
               "reason": "This is your choice.", "missing": ["coefficient"], "options": ["2", "3"], **extra}
    store.pause_input(rid, uuid.uuid4().hex, rid, payload)
    store.finish(rid, status="needs_input", answer=payload["question"])
    return {"cid": cid, "rid": rid, "id": payload["id"]}


def reply_url(item):
    return "/api/hitl/requests/" + item["id"] + "/reply"


def reply_body(item, text="3"):
    return {"cid": item["cid"], "rid": item["rid"], "text": text}


def wait_finished(client, rid):
    for _ in range(100):
        result = client.get("/api/runs/" + rid).json()
        if result["status"] != "running":
            return result
        time.sleep(.01)
    pytest.fail("Synthetic task did not finish")


def test_notifications_are_conversation_scoped_and_identity_is_authoritative(group):
    app, alice, bob, runner = group
    first = pause(app.state.store, cid="forged-cid", rid="forged-rid", state="answered")
    second = pause(app.state.store)
    data = alice.get("/api/hitl/requests", params={"cid": first["cid"]}).json()
    assert [item["id"] for item in data["requests"]] == [first["id"]]
    assert data["requests"][0]["cid"] == first["cid"]
    assert data["requests"][0]["rid"] == first["rid"]
    assert data["requests"][0]["state"] == "pending"
    assert data["history"] == []
    assert len(alice.get("/api/hitl/requests").json()["requests"]) == 2
    assert bob.get("/api/hitl/requests").json()["requests"] == []
    assert bob.get("/api/hitl/requests", params={"cid": first["cid"]}).status_code == 404


def test_bound_reply_resumes_only_target_once_and_retains_history(group):
    app, alice, bob, runner = group
    first, second = pause(app.state.store), pause(app.state.store)
    response = alice.post(reply_url(first), json=reply_body(first))
    assert response.status_code == 200, response.text
    assert wait_finished(alice, response.json()["id"])["status"] == "completed"
    assert len(runner.calls) == 1
    assert runner.calls[0]["id"] == first["id"]
    assert runner.calls[0]["query"] == "3"
    duplicate = alice.post(reply_url(first), json=reply_body(first))
    assert duplicate.status_code == 409
    assert len(runner.calls) == 1
    data = alice.get("/api/hitl/requests", params={"cid": first["cid"]}).json()
    assert data["requests"] == []
    assert data["history"][0]["state"] == "answered"
    assert data["history"][0]["reply_rid"] == response.json()["id"]
    assert alice.get("/api/hitl/requests", params={"cid": second["cid"]}).json()["requests"][0]["id"] == second["id"]


@pytest.mark.parametrize("bad_field", ["cid", "rid"])
def test_mismatched_identity_does_not_claim_or_execute(group, bad_field):
    app, alice, bob, runner = group
    first, other = pause(app.state.store), pause(app.state.store)
    data = reply_body(first)
    data[bad_field] = other[bad_field]
    assert alice.post(reply_url(first), json=data).status_code == 404
    assert app.state.store.input_request("alice", first["id"])["state"] == "pending"
    assert runner.calls == []


def test_owner_csrf_and_body_checks_precede_resume(group):
    app, alice, bob, runner = group
    item = pause(app.state.store)
    assert bob.post(reply_url(item), json=reply_body(item)).status_code == 404
    assert alice.post(reply_url(item), json=reply_body(item), headers={"x-csrf-token": "wrong"}).status_code == 403
    assert alice.post(reply_url(item), json={"text": "3"}).status_code == 400
    assert alice.post(reply_url(item), json=reply_body(item, "")).status_code == 400
    assert alice.post(reply_url(item), json=reply_body(item, {"coefficient": 3})).status_code == 400
    assert runner.calls == []


def test_attachment_is_question_bound_and_available_to_resumed_runner(group):
    app, alice, bob, runner = group
    item = pause(app.state.store)
    path = "/api/hitl/requests/" + item["id"] + "/upload"
    params = {"cid": item["cid"], "rid": item["rid"], "name": "coefficient.txt"}
    assert bob.post(path, params=params, content=b"3").status_code == 404
    assert alice.post(path, params={**params, "rid": "wrong"}, content=b"3").status_code == 404
    upload = alice.post(path, params=params, content=b"3",
                        headers={"content-type": "application/octet-stream"})
    assert upload.status_code == 200, upload.text
    assert app.state.store.files("alice", item["cid"])["coefficient.txt"] == b"3"
    response = alice.post(reply_url(item), json=reply_body(item, "See coefficient.txt"))
    run = wait_finished(alice, response.json()["id"])
    assert run["status"] == "completed"
    assert app.state.store.files("alice", item["cid"])["coefficient.txt"] == b"3"
    assert alice.post(path, params=params, content=b"9").status_code == 409
    assert app.state.store.files("alice", item["cid"])["coefficient.txt"] == b"3"


def test_cancel_is_owner_scoped_and_cannot_be_resumed(group):
    app, alice, bob, runner = group
    item = pause(app.state.store)
    app.state.store.snapshot("alice", item["cid"], {"keep.txt": b"preserved"})
    cancel = "/api/hitl/requests/" + item["id"] + "/cancel"
    assert bob.post(cancel).status_code == 404
    assert alice.post(cancel).status_code == 200
    assert alice.post(reply_url(item), json=reply_body(item)).status_code == 409
    assert app.state.store.files("alice", item["cid"]) == {"keep.txt": b"preserved"}
    history = alice.get("/api/hitl/requests", params={"cid": item["cid"]}).json()["history"]
    assert history[0]["state"] == "cancelled"
    assert runner.calls == []


def test_reloaded_store_retains_card_identifiers(group):
    from geological_agent.team.store import Store
    app, alice, bob, runner = group
    item = pause(app.state.store)
    restored = Store(app.state.store.root)
    try:
        card = restored.pending_inputs("alice", item["cid"], include_closed=True)[0]
        assert (card["id"], card["cid"], card["rid"]) == (item["id"], item["cid"], item["rid"])
        assert restored.recover() == []
    finally:
        restored.db.close()

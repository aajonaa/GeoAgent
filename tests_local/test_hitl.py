import json
import uuid

import pytest
from fastapi.testclient import TestClient

from geological_agent.bootstrap import create_agent
from geological_agent.contracts import ModelResponse, ToolCall
from geological_agent.settings import Settings
from geological_agent.team.server import create_app
from geological_agent.team.store import Store


QUESTION = {"question": "Which coefficient should I use?", "reason": "The coefficient was not supplied.",
            "missing": ["coefficient"], "options": ["2", "3"]}


def call(name, arguments):
    return ToolCall(uuid.uuid4().hex, name, arguments)


def action(name, arguments):
    return ModelResponse(tool_calls=(call(name, arguments),))


class ScriptedModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        return next(self.responses)


def agent(model, human=True):
    return create_agent(model, human_input=human, settings=Settings(verify_completion=False))


def test_unmatched_search_is_empty_and_empty_query_lists_registry():
    model = ScriptedModel([action("skill_find", {"query": "nonexistent_litho_operation_xyz"}), ModelResponse("No matching skill.")])
    runtime = agent(model, False)
    assert runtime.skills.registry.list("nonexistent_litho_operation_xyz") == ()
    from geological_agent.geology.source_registry import READY, EXISTING_SKILLS, source_tools
    from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog
    expected = {EXISTING_SKILLS.get(s["id"], s["id"].replace("-", "_"))
                for s in catalog()["skills"]}
    assert {s.id for s in runtime.skills.registry.list()} == expected
    assert {"earthquake_energy", "geodesic_coordinate_analysis", "remote_sensing_trend_distribution",
            "natural_hazard_table_analytics"} <= expected
    assert runtime.skills.registry.list("energy")


def test_search_and_load_require_an_observation_boundary(tmp_path):
    model = ScriptedModel([ModelResponse(tool_calls=(call("skill_find", {"query": "energy"}),
                                                     call("skill_load", {"skill_id": "earthquake_energy"}))),
                           ModelResponse("I must inspect the search before loading.")])
    result = agent(model, False).run("Find a skill", workspace=tmp_path)
    observations = [json.loads(m.content) for m in result.state["messages"] if m.role == "tool"]
    assert observations[0]["status"] == "ok"
    assert observations[1]["error"]["code"] == "discovery_order"
    assert result.state["selected_skill_ids"] == []


def test_checkpoint_resume_after_new_runtime_keeps_tool_pairs_and_does_not_replay(tmp_path):
    workspace, checkpoint = tmp_path / "work", tmp_path / "state.sqlite3"
    first = ScriptedModel([action("write_file", {"path": "once.txt", "content": "first"}),
                           action("request_user_input", QUESTION)])
    paused = agent(first).run("Write once, then ask for a coefficient", workspace=workspace, checkpoint_path=checkpoint)
    assert paused.status == "needs_input"
    assert len(first.requests) == 2
    assert paused.state["pending_tool_calls"] == []
    question_id = paused.state["metadata"]["pending_input"]["id"]
    # A new runtime and a changed file detect accidental replay of the old write.
    (workspace / "once.txt").write_text("kept after pause")
    second = ScriptedModel([ModelResponse("The coefficient is 3. Saved work was retained.")])
    resumed = agent(second).run("3", workspace=workspace, checkpoint_path=checkpoint,
        resume={"run_id": paused.run_id, "request_id": question_id, "text": "3", "files": ["once.txt"]})
    assert resumed.status == "completed", resumed.reason
    assert resumed.run_id == paused.run_id
    assert len(second.requests) == 1
    assert (workspace / "once.txt").read_text() == "kept after pause"
    assert "pending_input" not in resumed.state["metadata"]
    messages = second.requests[0].messages
    assert any(m.role == "user" and m.content.startswith("3\n") for m in messages)
    assert any(m.role == "tool" and json.loads(m.content)["name"] == "request_user_input" for m in messages)


def test_stale_response_cannot_consume_checkpoint(tmp_path):
    checkpoint = tmp_path / "cp.sqlite3"
    paused = agent(ScriptedModel([action("request_user_input", QUESTION)])).run("Need a coefficient", workspace=tmp_path / "w", checkpoint_path=checkpoint)
    assert paused.status == "needs_input"
    model = ScriptedModel([])
    failed = agent(model).run("3", workspace=tmp_path / "w", checkpoint_path=checkpoint,
        resume={"run_id": paused.run_id, "request_id": uuid.uuid4().hex, "text": "3"})
    assert failed.status == "failed"
    assert "Stale" in failed.reason
    assert model.requests == []
    finished = agent(ScriptedModel([ModelResponse("Coefficient received.")])).run("3", workspace=tmp_path / "w", checkpoint_path=checkpoint,
        resume={"run_id": paused.run_id, "request_id": paused.state["metadata"]["pending_input"]["id"], "text": "3"})
    assert finished.status == "completed", finished.reason


def test_asking_and_writing_in_same_batch_executes_neither(tmp_path):
    model = ScriptedModel([ModelResponse(tool_calls=(call("request_user_input", QUESTION),
                                                    call("write_file", {"path": "must-not-exist.txt", "content": "bad"}))),
                           action("request_user_input", QUESTION)])
    paused = agent(model).run("Ask before writing", workspace=tmp_path / "w", checkpoint_path=tmp_path / "cp.sqlite3")
    assert paused.status == "needs_input"
    assert not (tmp_path / "w" / "must-not-exist.txt").exists()
    results = [json.loads(m.content) for m in paused.state["messages"] if m.role == "tool"]
    assert [r["error"]["code"] for r in results[:2]] == ["input_request_must_be_alone"] * 2


def test_human_input_requires_durable_storage(tmp_path):
    with pytest.raises(ValueError, match="durable checkpoint"):
        agent(ScriptedModel([])).run("Ask", workspace=tmp_path)


class NoRun:
    isolated = False
    description = "Test runner; no model"

    def stop(self, rid):
        pass


@pytest.fixture(scope="module")
def web_group(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("GEOTOOL_HITL", "1")
        patch.setenv("GEOTOOL_TEAM_EXECUTION", "trusted")
        root = tmp_path_factory.mktemp("hitl-web")
        app = create_app(root, runner=NoRun())
        store = app.state.store
        store.create_user("owner", "Owner-Test-Password-2026", role="admin", initial_admin=True)
        store.create_user("other", "Other-Test-Password-2026", invite=store.invite())
        with TestClient(app, base_url="http://127.0.0.1") as owner, TestClient(app, base_url="http://127.0.0.1") as other:
            for client, name, password in [(owner, "owner", "Owner-Test-Password-2026"), (other, "other", "Other-Test-Password-2026")]:
                login = client.post("/api/login", json={"username": name, "password": password})
                assert login.status_code == 200
                client.headers["x-csrf-token"] = login.json()["csrf"]
            yield app, owner, other


def pending_fixture(store):
    uid = store.user("owner")["id"]
    cid = store.create_conversation(uid)["id"]
    rid = store.begin(uid, cid, "A task needing a coefficient")
    payload = {"id": uuid.uuid4().hex, **QUESTION}
    store.pause_input(rid, uuid.uuid4().hex, rid, payload)
    store.finish(rid, status="needs_input", answer=payload["question"])
    return uid, cid, rid, payload


def test_pending_notifications_are_owner_scoped_and_cancellation_requires_csrf(web_group):
    app, owner, other = web_group
    uid, cid, rid, payload = pending_fixture(app.state.store)
    assert payload["id"] in [item["id"] for item in owner.get("/api/hitl/requests").json()["requests"]]
    assert other.get("/api/hitl/requests").json()["requests"] == []
    url = "/api/hitl/requests/" + payload["id"] + "/cancel"
    assert other.post(url).status_code == 404
    assert owner.post(url, headers={"x-csrf-token": "wrong"}).status_code == 403
    assert owner.post(url, headers={"origin": "https://evil.example"}).status_code == 403
    assert owner.post(url).status_code == 200
    assert owner.post(url).status_code == 409
    assert app.state.store.run(uid, rid)["status"] == "stopped"


def test_paused_request_survives_store_restart_and_reply_claim_is_atomic(web_group):
    app, owner, other = web_group
    store = app.state.store
    uid, cid, rid, payload = pending_fixture(store)
    restored = Store(store.root)
    try:
        assert restored.recover() == []
        assert payload["id"] in [r["id"] for r in restored.pending_inputs(uid)]
        reply_rid = restored.begin(uid, cid, "3")
        claimed = restored.input_for_reply(reply_rid)
        assert claimed["id"] == payload["id"]
        assert claimed["job_id"] == rid
        with pytest.raises(ValueError, match="running task"):
            restored.begin(uid, cid, "3")
        restored.finish(reply_rid, status="completed", answer="15")
        assert restored.input_for_reply(reply_rid) is None
        assert payload["id"] not in [r["id"] for r in restored.pending_inputs(uid)]
    finally:
        restored.db.close()


def test_notification_javascript_is_served_and_loaded(web_group):
    app, owner, other = web_group
    script = owner.get("/assets/hitl.js")
    assert script.status_code == 200
    assert "/api/hitl/requests" in script.text
    assert "/assets/hitl.js" in owner.get("/").text

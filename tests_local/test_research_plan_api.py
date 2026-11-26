import json
import queue
from threading import Condition, Event
import time
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient
import pytest

from geological_agent.team.server import COOKIE, create_app
from geological_agent.team.store import Store


TEXT_LIMITS = {
    "objective": 500,
    "scope": 1000,
    "materials": 1000,
    "tools": 500,
    "deliverables": 1000,
}
ORIGINAL_QUERY = "  Compare the supplied geological datasets and save a concise report.  "
PLAN_MARKER = "用户已确认的研究计划与验收标准："


def confirmed_plan():
    return {
        "objective": "Compare the two geological datasets",
        "scope": "Use only the supplied files and document the comparison boundary",
        "materials": "Uploaded datasets and their existing provenance records",
        "tools": "Use read-only inspection and deterministic tabular analysis",
        "deliverables": "A concise report and a machine-readable comparison table",
        "acceptance": [
            "The report answers the stated comparison question",
            "Each material claim cites a traceable source",
            "The report states data and method limitations",
        ],
    }


def padded_plan():
    return {
        **confirmed_plan(),
        "objective": "  Compare the two geological datasets  ",
        "acceptance": ["  The report answers the stated comparison question  ", *confirmed_plan()["acceptance"][1:]],
    }


class NoTrace:
    def emit(self, *args, **kwargs):
        pass


class SyntheticRunner:
    """Record execution input and wait for an explicit release; never call a model."""

    isolated = False
    description = "Synthetic research-plan test runner; no model"

    def __init__(self):
        self._condition = Condition()
        self._calls = []
        self._arrivals = queue.Queue()

    def stop(self, rid):
        pass

    def run(self, rid, query, files, cancel, model_call, on_trace, **kwargs):
        release = Event()
        call = {
            "rid": rid,
            "query": query,
            "files": dict(files),
            "kwargs": kwargs,
            "release": release,
        }
        with self._condition:
            self._calls.append(call)
            self._condition.notify_all()
        self._arrivals.put(call)
        if not release.wait(10):
            raise RuntimeError("Synthetic runner was not released")
        return {
            "status": "completed",
            "answer": "Synthetic research result",
            "reason": "",
            "turns": 0,
            "files": {},
        }

    def wait_call(self):
        return self._arrivals.get(timeout=3)

    @property
    def call_count(self):
        with self._condition:
            return len(self._calls)

    def release_all(self):
        with self._condition:
            calls = list(self._calls)
        for call in calls:
            call["release"].set()


def unexpected_model(*args, **kwargs):
    raise AssertionError("A research-plan API test must not call a real model")


@pytest.fixture(scope="module")
def group(tmp_path_factory):
    runner = SyntheticRunner()
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("GEOTOOL_TEAM_EXECUTION", "trusted")
        patch.setenv("GEOTOOL_EXECUTION_POLICY", "standard")
        patch.setenv("GEOTOOL_TRUSTED_PROCESS_OWNERSHIP", "0")
        patch.setenv("GEOTOOL_SANDBOX_PROCESS_OWNERSHIP", "0")
        patch.setenv("GEOTOOL_ISOLATED_CPU_PROCESS_OWNERSHIP", "0")
        app = create_app(
            tmp_path_factory.mktemp("research-plan-api"),
            runner=runner,
            model_factory=unexpected_model,
            memory_summarizer=unexpected_model,
            trace_factory=lambda path: NoTrace(),
        )
    store = app.state.store
    store.create_user("planadmin", "Plan-Admin-Test-Password-2026", role="admin", initial_admin=True)
    users = {}
    for name in ("planowner", "planother"):
        uid = store.create_user(name, name.title() + "-Test-Password-2026", invite=store.invite())
        token, csrf = store.create_session(uid)
        users[name] = {"uid": uid, "token": token, "csrf": csrf}
    admin_token, admin_csrf = store.create_session(store.user("planadmin")["id"])
    users["planadmin"] = {"uid": store.user("planadmin")["id"], "token": admin_token, "csrf": admin_csrf}
    try:
        with TestClient(app, base_url="http://127.0.0.1") as owner, \
                TestClient(app, base_url="http://127.0.0.1") as other, \
                TestClient(app, base_url="http://127.0.0.1") as admin:
            for client, name in ((owner, "planowner"), (other, "planother"), (admin, "planadmin")):
                client.cookies.set(COOKIE, users[name]["token"])
                client.headers["x-csrf-token"] = users[name]["csrf"]
            yield SimpleNamespace(
                app=app,
                store=store,
                runner=runner,
                owner=owner,
                other=other,
                admin=admin,
                uid=users["planowner"]["uid"],
                other_uid=users["planother"]["uid"],
            )
    finally:
        runner.release_all()


def new_conversation(client):
    response = client.post("/api/conversations")
    assert response.status_code == 200, response.text
    return response.json()["id"]


def wait_for_terminal(client, rid):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{rid}")
        assert response.status_code == 200, response.text
        run = response.json()
        if run["status"] not in ("running", "stopping"):
            return run
        time.sleep(0.01)
    pytest.fail(f"Run {rid} did not reach a terminal state")


def start_and_finish(group, client, cid, payload):
    response = client.post(f"/api/conversations/{cid}/runs", json=payload)
    assert response.status_code == 200, response.text
    rid = response.json()["id"]
    call = group.runner.wait_call()
    try:
        assert group.store.run(group.uid, rid)["status"] == "running"
    finally:
        call["release"].set()
    return rid, call, wait_for_terminal(client, rid)


def assert_invalid_plan(group, cid, value, detail="Invalid confirmed research plan"):
    before = group.runner.call_count
    response = group.owner.post(
        f"/api/conversations/{cid}/runs",
        json={"query": ORIGINAL_QUERY, "mode": "agent", "plan": value},
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == detail
    assert group.store.runs(group.uid, cid) == []
    assert group.runner.call_count == before


def test_confirmed_plan_is_persisted_emitted_and_only_augments_runner_query(group):
    cid = new_conversation(group.owner)
    response = group.owner.post(
        f"/api/conversations/{cid}/runs",
        json={"query": ORIGINAL_QUERY, "mode": "agent", "plan": padded_plan()},
    )
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"id"}
    rid = response.json()["id"]
    call = group.runner.wait_call()
    plan = confirmed_plan()
    execution_query = ORIGINAL_QUERY.strip() + "\n\n" + PLAN_MARKER + "\n" + json.dumps(plan, ensure_ascii=False)
    try:
        running = group.store.run(group.uid, rid)
        assert running["query"] == ORIGINAL_QUERY.strip()
        assert PLAN_MARKER not in running["query"]
        assert running["activity"]["plan"] == plan
        assert call["query"].endswith("\nCurrent user request:\n" + execution_query)
        assert call["query"].count(ORIGINAL_QUERY.strip()) == 1
        assert call["kwargs"].get("read_only", False) is False

        events = [item["data"] for item in group.store.history(group.uid, rid)["events"]]
        assert [item for item in events if item["kind"] == "plan_confirmed"] == [
            {"kind": "plan_confirmed", "plan": plan}
        ]
        api_events = group.owner.get(f"/api/runs/{rid}/history").json()["events"]
        assert [item["data"] for item in api_events if item["data"]["kind"] == "plan_confirmed"] == [
            {"kind": "plan_confirmed", "plan": plan}
        ]
    finally:
        call["release"].set()

    finished = wait_for_terminal(group.owner, rid)
    assert finished["status"] == "completed"
    assert finished["query"] == ORIGINAL_QUERY.strip()
    assert finished["activity"]["plan"] == plan
    conversation = group.owner.get(f"/api/conversations/{cid}").json()
    assert conversation["runs"][0]["query"] == ORIGINAL_QUERY.strip()
    assert conversation["runs"][0]["activity"]["plan"] == plan

    reloaded = Store(group.store.root)
    try:
        restored = reloaded.run(group.uid, rid)
        assert restored["status"] == "completed"
        assert restored["query"] == ORIGINAL_QUERY.strip()
        assert restored["activity"]["plan"] == plan
        restored_events = [item["data"] for item in reloaded.history(group.uid, rid)["events"]]
        assert [item for item in restored_events if item["kind"] == "plan_confirmed"] == [
            {"kind": "plan_confirmed", "plan": plan}
        ]
    finally:
        reloaded.db.close()


def test_confirmed_plan_accepts_exact_field_and_acceptance_limits(group):
    cid = new_conversation(group.owner)
    plan = {field: "x" * limit for field, limit in TEXT_LIMITS.items()}
    plan["acceptance"] = [(f"criterion-{index}-" + "y" * 300)[:300] for index in range(5)]
    assert all(len(item) == 300 for item in plan["acceptance"])
    rid, call, finished = start_and_finish(
        group, group.owner, cid, {"query": ORIGINAL_QUERY, "mode": "agent", "plan": plan}
    )
    assert finished["status"] == "completed"
    assert finished["activity"]["plan"] == plan
    assert call["query"].endswith(json.dumps(plan, ensure_ascii=False))
    assert group.store.run(group.uid, rid)["query"] == ORIGINAL_QUERY.strip()


@pytest.mark.parametrize("value", ["not-a-plan", [], 7, True])
def test_confirmed_plan_rejects_malformed_container(group, value):
    assert_invalid_plan(group, new_conversation(group.owner), value)


@pytest.mark.parametrize("field", [*TEXT_LIMITS, "acceptance"])
def test_confirmed_plan_rejects_missing_field(group, field):
    plan = confirmed_plan()
    del plan[field]
    assert_invalid_plan(group, new_conversation(group.owner), plan)


def test_confirmed_plan_rejects_extra_field(group):
    assert_invalid_plan(group, new_conversation(group.owner), {**confirmed_plan(), "unexpected": "value"})


@pytest.mark.parametrize("field", TEXT_LIMITS)
@pytest.mark.parametrize("kind", ["blank", "oversized"])
def test_confirmed_plan_rejects_blank_and_oversized_text_fields(group, field, kind):
    plan = confirmed_plan()
    plan[field] = " \t\n " if kind == "blank" else "x" * (TEXT_LIMITS[field] + 1)
    assert_invalid_plan(group, new_conversation(group.owner), plan)


@pytest.mark.parametrize("field", TEXT_LIMITS)
def test_confirmed_plan_rejects_non_string_text_fields(group, field):
    plan = confirmed_plan()
    plan[field] = 7
    assert_invalid_plan(group, new_conversation(group.owner), plan)


@pytest.mark.parametrize("acceptance", [None, "one criterion", {}, 7, True])
def test_confirmed_plan_rejects_non_list_acceptance(group, acceptance):
    assert_invalid_plan(group, new_conversation(group.owner), {**confirmed_plan(), "acceptance": acceptance},
                        "Invalid confirmed acceptance criteria")


@pytest.mark.parametrize("acceptance", [[], [f"criterion-{index}" for index in range(6)]])
def test_confirmed_plan_rejects_invalid_acceptance_count(group, acceptance):
    assert_invalid_plan(group, new_conversation(group.owner), {**confirmed_plan(), "acceptance": acceptance},
                        "Invalid confirmed acceptance criteria")


@pytest.mark.parametrize("item", [None, 7, True, {}, []])
def test_confirmed_plan_rejects_non_string_acceptance_items(group, item):
    assert_invalid_plan(group, new_conversation(group.owner), {**confirmed_plan(), "acceptance": [item]},
                        "Invalid confirmed acceptance criteria")


@pytest.mark.parametrize("item", [" \t\n ", "x" * 301])
def test_confirmed_plan_rejects_blank_and_oversized_acceptance_items(group, item):
    assert_invalid_plan(group, new_conversation(group.owner), {**confirmed_plan(), "acceptance": [item]},
                        "Invalid confirmed acceptance criteria")


def test_ask_rejects_plan_or_skill_before_starting(group):
    for extra in ({"plan": confirmed_plan()}, {"skill_id": "geodesic_coordinate_analysis"}):
        cid = new_conversation(group.owner)
        before = group.runner.call_count
        response = group.owner.post(
            f"/api/conversations/{cid}/runs",
            json={"query": ORIGINAL_QUERY, "mode": "ask", **extra},
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"] == "Switch to Agent mode to use a skill or confirmed plan"
        assert group.store.runs(group.uid, cid) == []
        assert group.runner.call_count == before


def test_ask_without_plan_remains_supported(group):
    cid = new_conversation(group.owner)
    rid, call, finished = start_and_finish(
        group, group.owner, cid, {"query": ORIGINAL_QUERY, "mode": "ask"}
    )
    assert finished["status"] == "completed"
    assert finished["query"] == ORIGINAL_QUERY.strip()
    assert finished["activity"]["mode"] == "ask"
    assert "plan" not in finished["activity"]
    assert call["kwargs"]["read_only"] is True
    assert PLAN_MARKER not in call["query"]
    assert all(item["data"]["kind"] != "plan_confirmed"
               for item in group.store.history(group.uid, rid)["events"])


def test_agent_without_plan_is_backward_compatible(group):
    cid = new_conversation(group.owner)
    rid, call, finished = start_and_finish(group, group.owner, cid, {"query": ORIGINAL_QUERY})
    assert finished["status"] == "completed"
    assert finished["query"] == ORIGINAL_QUERY.strip()
    assert finished["activity"]["mode"] == "agent"
    assert "plan" not in finished["activity"]
    assert call["kwargs"].get("read_only", False) is False
    assert call["query"].endswith("\nCurrent user request:\n" + ORIGINAL_QUERY.strip())
    assert PLAN_MARKER not in call["query"]
    assert all(item["data"]["kind"] != "plan_confirmed"
               for item in group.store.history(group.uid, rid)["events"])


def test_hitl_reply_rejects_plan_and_preserves_pending_request(group):
    cid = new_conversation(group.owner)
    rid = group.store.begin(group.uid, cid, "A task needing a coefficient")
    payload = {
        "id": uuid.uuid4().hex,
        "question": "Which coefficient should I use?",
        "reason": "The coefficient was not supplied.",
        "missing": ["coefficient"],
        "options": ["2", "3"],
    }
    group.store.pause_input(rid, uuid.uuid4().hex, rid, payload)
    group.store.finish(rid, status="needs_input", answer=payload["question"])
    before = group.runner.call_count
    response = group.owner.post(
        f"/api/hitl/requests/{payload['id']}/reply",
        json={"cid": cid, "rid": rid, "text": "3", "plan": confirmed_plan()},
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Expected cid, rid, and text"
    assert len(group.store.runs(group.uid, cid)) == 1
    assert group.store.run(group.uid, rid)["status"] == "needs_input"
    assert group.store.pending_inputs(group.uid, cid)[0]["id"] == payload["id"]
    assert group.runner.call_count == before


def test_confirmed_plan_run_enforces_authentication_ownership_and_csrf(group):
    cid = new_conversation(group.owner)
    url = f"/api/conversations/{cid}/runs"
    body = {"query": ORIGINAL_QUERY, "mode": "agent", "plan": confirmed_plan()}
    before = group.runner.call_count
    with TestClient(group.app, base_url="http://127.0.0.1") as anonymous:
        assert anonymous.post(url, json=body).status_code == 401
    assert group.other.post(url, json=body).status_code == 404
    assert group.admin.post(url, json=body).status_code == 404
    for headers in (
        {"x-csrf-token": ""},
        {"x-csrf-token": "wrong"},
        {"origin": "https://evil.example"},
        {"sec-fetch-site": "cross-site"},
    ):
        assert group.owner.post(url, json=body, headers=headers).status_code == 403
    assert group.store.runs(group.uid, cid) == []
    assert group.other.get(f"/api/conversations/{cid}").status_code == 404
    assert group.runner.call_count == before

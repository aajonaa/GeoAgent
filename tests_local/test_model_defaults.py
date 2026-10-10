"""Account defaults acceptance: synthetic accounts and HTTP fixtures only."""
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from geological_agent.contracts import Message, ModelRequest
from geological_agent.context_budget import input_allowance
from geological_agent.settings import Settings
from geological_agent.team.model_settings import ModelProfile, SessionModels, EndpointPolicy, profile_client
from geological_agent.team.server import COOKIE, create_app
from geological_agent.team.store import Store, digest

PRESET = {"context_window_tokens":1000000, "max_output_tokens":128000}
CUSTOM = {"source":"custom", "base_url":"https://models.example/v1", "model":"synthetic",
          "api_token":"test-only-token", "remember":True, "name":"synthetic connection"}


def sessions(store):
    for uid in ("alice", "bob"):
        token = "synthetic-session-" + uid
        with store.lock, store.db:
            store.db.execute("INSERT INTO users(id,username,password,role) VALUES (?,?,?,?)",
                             (uid, uid, "not-used", "member"))
            store.db.execute("INSERT INTO auth VALUES (?,?,?,?)",
                             (digest(token), uid, token+"-csrf", time.time()+600))
    return "synthetic-session-alice", "synthetic-session-bob"


@pytest.fixture
def models(tmp_path):
    store = Store(tmp_path)
    tokens = sessions(store)
    builtin = ModelProfile("builtin", "http://127.0.0.1:8000/v1", "local",
                           context_window_tokens=32768, max_output_tokens=4096)
    result = SessionModels(store, builtin, EndpointPolicy(builtin.base_url))
    yield result, tokens
    store.db.close()


def limits(context=256000, output=8192, revision=0):
    return {"context_window_tokens":context, "max_output_tokens":output, "revision":revision}


def test_defaults_persist_across_restart_and_are_account_scoped(models):
    manager, (alice, bob) = models
    initial = manager.get_defaults(alice)
    assert {k:initial[k] for k in PRESET} == PRESET and initial["revision"] == 0
    changed = manager.save_defaults(alice, limits())
    assert changed["input_budget_tokens"] == 256000 - 8192 - 12800
    restored = SessionModels(manager.store, manager.builtin, manager.policy)
    assert restored.get_defaults(alice) == changed
    assert {k:restored.get_defaults(bob)[k] for k in PRESET} == PRESET
    assert restored.get(bob).context_window_tokens == 32768


def test_new_connections_use_defaults_existing_connections_remain_fixed(models):
    manager, (alice, _) = models
    first = manager.save(alice, CUSTOM)
    frozen = first.runtime_settings()
    manager.save_defaults(alice, limits())
    second = manager.save(alice, {**CUSTOM, "model":"different-model", "name":"second"})
    assert second.context_window_tokens == 256000 and second.max_output_tokens == 8192
    assert manager.activate(alice, first.profile_id).runtime_settings() == frozen
    assert first.runtime_settings() == frozen
    assert manager.get(alice).api_token == "test-only-token"
    assert "test-only-token" not in json.dumps(manager.public(alice))
    explicit = manager.save(alice, {**CUSTOM, "model":"explicit", "context_window_tokens":64000,
                                   "max_output_tokens":2048})
    assert explicit.runtime_settings() == {"context_model":"explicit", "context_window_tokens":64000,
                                          "max_output_tokens":2048}
    assert input_allowance(Settings(**explicit.runtime_settings())) == 64000 - 2048 - 3200


def test_defaults_survive_switching_builtin_and_removing_last_connection(models):
    manager, (alice, _) = models
    changed = manager.save_defaults(alice, limits())
    profile = manager.save(alice, CUSTOM)
    assert manager.activate(alice, None).context_window_tokens == 32768
    assert manager.get_defaults(alice) == changed
    manager.remove(alice, profile.profile_id, profile.revision)
    assert manager.public(alice)["saved_profiles"] == []
    assert manager.get_defaults(alice) == changed


def test_defaults_optimistic_revision_prevents_lost_updates(models):
    manager, (alice, _) = models
    second = SessionModels(manager.store, manager.builtin, manager.policy)
    changed = manager.save_defaults(alice, limits())
    with pytest.raises(ValueError, match="another window"):
        second.save_defaults(alice, limits(512000, 4096))
    assert second.get_defaults(alice) == changed
    assert second.save_defaults(alice, limits(512000, 4096, changed["revision"]))["revision"] == 2


@pytest.mark.parametrize("key,value", [
    ("context_window_tokens", None), ("context_window_tokens", True), ("context_window_tokens", False),
    ("context_window_tokens", 0), ("context_window_tokens", -1), ("context_window_tokens", 8192.5),
    ("context_window_tokens", "128000"), ("context_window_tokens", 9007199254740992),
    ("max_output_tokens", None), ("max_output_tokens", True), ("max_output_tokens", 0),
    ("max_output_tokens", -1), ("max_output_tokens", 2.5), ("max_output_tokens", "4096"),
    ("max_output_tokens", 9007199254740992), ("revision", True), ("revision", -1),
])
def test_invalid_defaults_are_rejected_without_mutation(models, key, value):
    manager, (alice, _) = models
    original = manager.get_defaults(alice)
    with pytest.raises(ValueError):
        manager.save_defaults(alice, {**limits(), key:value})
    assert manager.get_defaults(alice) == original


def test_output_cannot_consume_entire_context_and_ownership_is_not_client_chosen(models):
    manager, (alice, _) = models
    for payload in (limits(8192, 8192), {**limits(), "uid":"bob"},
                    {"context_window_tokens":128000, "revision":0}):
        with pytest.raises(ValueError):
            manager.save_defaults(alice, payload)
    assert manager.get_defaults(alice)["revision"] == 0


def test_runtime_and_http_request_share_the_configured_output_limit():
    seen = []
    def reply(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices":[{"message":{"content":"synthetic response"},
                                                   "finish_reason":"stop"}]})
    class Policy:
        def transport(self, url):
            return httpx.MockTransport(reply)
    profile = ModelProfile("custom", "https://models.example/v1", "synthetic",
                           context_window_tokens=256000, max_output_tokens=1234)
    client = profile_client(profile, Policy())
    try:
        assert client.invoke(ModelRequest((Message("user","test"),), ())).content == "synthetic response"
    finally:
        client.close()
    assert seen[0]["max_tokens"] == 1234
    assert profile.runtime_settings()["max_output_tokens"] == 1234
    assert input_allowance(Settings(**profile.runtime_settings())) == 256000 - 1234 - 12800
    probe = profile_client(profile, Policy(), probe=True)
    try:
        assert probe.max_tokens == 256
    finally:
        probe.close()


def test_settings_api_auth_csrf_account_isolation_and_model_config_visibility(tmp_path):
    class Runner:
        isolated = False
        hitl_enabled = False
        def stop(self, rid):
            pass
    app = create_app(tmp_path, runner=Runner())
    alice, bob = sessions(app.state.store)
    with TestClient(app, base_url="http://localhost") as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "model-max-output" in page.text and "/assets/defaults.js" in page.text
        assert client.get("/assets/defaults.js").status_code == 200
        assert client.get("/assets/defaults.css").status_code == 200
        assert client.get("/assets/server.py").status_code == 404
        assert client.get("/api/settings/model-defaults").status_code == 401
        client.cookies.set(COOKIE, alice)
        assert client.put("/api/settings/model-defaults", json=limits()).status_code == 403
        response = client.put("/api/settings/model-defaults", json=limits(),
                              headers={"x-csrf-token":alice+"-csrf"})
        assert response.status_code == 200
        assert client.get("/api/model-settings").json()["defaults"]["max_output_tokens"] == 8192
        assert client.put("/api/settings/model-defaults", json=limits(),
                          headers={"x-csrf-token":alice+"-csrf"}).status_code == 400
        client.cookies.set(COOKIE, bob)
        assert client.get("/api/settings/model-defaults").json()["context_window_tokens"] == 1000000

"""Synthetic context-budget acceptance; no external model requests."""
import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from geological_agent.settings import Settings
from geological_agent.contracts import Message, ModelRequest
from geological_agent.context_budget import input_allowance, request_budget_size, budget_description
from geological_agent.agent.compaction import ContextOverflow, fit_request, request_size
from geological_agent.team.model_settings import ModelProfile, EndpointPolicy, SessionModels, parse_profile
from geological_agent.team.store import Store
from geological_agent.team.server import create_app


def connection(window=None, **extra):
    return {"source": "custom", "base_url": "https://model.example/v1",
            "model": "synthetic-model", "api_token": "synthetic-test-token",
            "context_window_tokens": window, "max_output_tokens":4096, **extra}


def test_default_uses_token_window_and_output_reserve():
    settings = Settings()
    request = ModelRequest((Message("user", "context budget"),), ())
    assert settings.context_window_tokens == 1000000
    assert settings.max_output_tokens == 128000
    assert input_allowance(settings) == 822000
    assert request_budget_size(request, settings) > 0
    assert budget_description(settings)["count_method"] == "tiktoken_cross_encoding_estimate"


def test_default_budget_accepts_large_protected_request_without_compaction():
    settings = Settings()
    request = ModelRequest((Message("user", "word " * 160000),), ())
    state = {"task": request.messages[0].content, "messages": list(request.messages), "metadata": {}}
    assert request_size(request) > 750000
    assert request_budget_size(request, settings) < input_allowance(settings)
    assert fit_request(request, state, settings) == request
    assert state["messages"] == list(request.messages)


def test_legacy_null_window_uses_token_fallback_not_character_limit():
    settings = Settings(context_window_tokens=None, max_context_chars=48000)
    assert settings.context_window_tokens == 1000000
    assert input_allowance(settings) == 822000
    assert budget_description(settings)["legacy_allowance_chars"] is None
    assert budget_description(settings)["count_method"] == "tiktoken_cross_encoding_estimate"


def test_token_window_reserves_output_and_safety_without_48000_char_ceiling():
    settings = Settings(context_window_tokens=128000, max_output_tokens=4096)
    request = ModelRequest((Message("user", "a" * 50000),), ())
    state = {"task": request.messages[0].content, "messages": list(request.messages), "metadata": {}}
    assert input_allowance(settings) == 117504
    assert request_size(request) > 48000
    assert request_budget_size(request, settings) < input_allowance(settings)
    assert fit_request(request, state, settings) == request
    assert state["messages"] == list(request.messages)
    assert budget_description(settings)["provider_capacity_verified"] is False


def test_unknown_bpe_estimate_does_not_claim_provider_accuracy():
    settings = Settings(context_window_tokens=128000, max_output_tokens=4096)
    request = ModelRequest((Message("user", "\u5730\u8d28" * 100),), ())
    assert request_budget_size(request, settings) > 0
    assert request_budget_size(request, settings) < len(json.dumps({"text":request.messages[0].content}, ensure_ascii=False).encode("utf-8"))
    assert budget_description(settings)["count_method"] == "tiktoken_cross_encoding_estimate"
    assert budget_description(settings)["provider_tokenizer_known"] is False


def test_protected_overflow_uses_correct_units_and_retains_originals():
    settings = Settings(context_window_tokens=8192, max_output_tokens=4096)
    query = "\u5c71" * 10000
    request = ModelRequest((Message("user", query),), ())
    state = {"task": query, "messages": list(request.messages), "metadata": {}}
    with pytest.raises(ContextOverflow, match="estimated tokens"):
        fit_request(request, state, settings)
    assert state["task"] == query and state["messages"] == list(request.messages)


def test_native_schemas_and_provider_reasoning_are_counted():
    settings = Settings(context_window_tokens=128000, max_output_tokens=4096)
    tool = SimpleNamespace(name="synthetic", description="d", when_to_use="test",
        input_schema={"type": "object", "properties": {"query": {"type": "string", "description": "x"*2000}}})
    short = ModelRequest((Message("assistant", "draft"),), ())
    long = ModelRequest((Message("assistant", "draft", reasoning_content="r"*1000),), (tool,))
    assert request_budget_size(long, settings) > request_budget_size(short, settings)
    reasoning = ModelRequest(long.messages, ())
    assert request_budget_size(reasoning, settings) > request_budget_size(short, settings)
    assert request_budget_size(long, settings) > request_budget_size(reasoning, settings)


@pytest.mark.parametrize("window", [True, False, 0, -1, 5120, 8192.5, "128000", 9007199254740992])
def test_invalid_window_is_rejected_without_coercion(window):
    with pytest.raises(ValueError):
        Settings(context_window_tokens=window, max_output_tokens=4096)


def test_profile_validation_does_not_change_native_endpoint_or_credentials():
    builtin = ModelProfile("builtin", "http://127.0.0.1:8000/v1", "local")
    policy = EndpointPolicy(builtin.base_url)
    profile = parse_profile(connection(128000), builtin, builtin, policy)
    assert profile.runtime_settings() == {"context_model":"synthetic-model", "context_window_tokens": 128000, "max_output_tokens":4096}
    assert profile.api_token == "synthetic-test-token"
    assert "synthetic-test-token" not in json.dumps(profile.public())
    assert profile.public()["context_budget"]["input_budget_tokens"] == 117504
    assert profile.identity() == {"source": "custom", "base_url": "https://model.example/v1", "model": "synthetic-model"}
    unchanged = parse_profile({k:v for k,v in connection().items() if k!="context_window_tokens"},
                              builtin, profile, policy)
    assert unchanged.context_window_tokens == 128000


def test_encrypted_connections_keep_independent_windows_after_restart(tmp_path):
    store = Store(tmp_path)
    store.create_user("budgetadmin", "Synthetic-password-12345", role="admin", initial_admin=True)
    token, _ = store.login("budgetadmin", "Synthetic-password-12345")
    builtin = ModelProfile("builtin", "http://127.0.0.1:8000/v1", "local")
    policy = EndpointPolicy(builtin.base_url)
    models = SessionModels(store, builtin, policy)
    first = models.save(token, connection(128000, name="one", remember=True))
    second = models.save(token, connection(256000, name="two", remember=True))
    restored = SessionModels(store, builtin, policy)
    assert restored.get(token).context_window_tokens == 256000
    assert restored.activate(token, first.profile_id).context_window_tokens == 128000
    assert len(restored.public(token)["saved_profiles"]) == 2
    assert restored.activate(token, second.profile_id).context_window_tokens == 256000
    clear = restored.save(token, {**connection(None, name="two", remember=True),
                                  "profile_id": second.profile_id, "revision": second.revision})
    assert clear.context_window_tokens == 1000000
    assert restored.activate(token, first.profile_id).context_window_tokens == 128000
    uid = store.authenticate(token)["id"]
    blob = bytes(store.db.execute("SELECT ciphertext FROM model_profiles WHERE uid=?", (uid,)).fetchone()[0])
    assert b"synthetic-test-token" not in blob


def test_legacy_encrypted_profile_defaults_without_rewriting_collection(tmp_path):
    store = Store(tmp_path)
    store.create_user("legacyadmin", "Synthetic-password-12345", role="admin", initial_admin=True)
    token, _ = store.login("legacyadmin", "Synthetic-password-12345")
    builtin = ModelProfile("builtin", "http://127.0.0.1:8000/v1", "local")
    models = SessionModels(store, builtin, EndpointPolicy(builtin.base_url))
    uid = store.authenticate(token)["id"]
    legacy = {k:v for k,v in connection().items() if k not in ("context_window_tokens", "max_output_tokens")}
    models.vault.put(uid, legacy)
    original = bytes(store.db.execute("SELECT ciphertext FROM model_profiles WHERE uid=?", (uid,)).fetchone()[0])
    assert models.get(token).context_window_tokens == 1000000
    assert models.public(token)["context_budget"]["input_budget_tokens"] == 945904
    assert bytes(store.db.execute("SELECT ciphertext FROM model_profiles WHERE uid=?", (uid,)).fetchone()[0]) == original


def test_authenticated_broker_passes_selected_window_to_runtime(tmp_path):
    class Runner:
        hitl_enabled = False
        isolated = False
        received = None
        def stop(self, rid):
            pass
        def run(self, rid, query, files, cancel, model_call, on_trace, **kwargs):
            self.received = kwargs.get("settings")
            return {"status":"completed", "answer":"synthetic completion", "turns":0, "files":files}

    runner = Runner()
    app = create_app(tmp_path, runner=runner)
    app.state.store.create_user("brokeradmin", "Synthetic-password-12345", role="admin", initial_admin=True)
    with TestClient(app, base_url="http://localhost") as client:
        login = client.post("/api/login", json={"username":"brokeradmin","password":"Synthetic-password-12345"})
        assert login.status_code == 200
        headers = {"x-csrf-token":login.json()["csrf"]}
        saved = client.put("/api/model-settings", json=connection(128000, name="probe", remember=True), headers=headers)
        assert saved.status_code == 200
        assert saved.json()["context_window_tokens"] == 128000
        cid = client.post("/api/conversations", headers=headers).json()["id"]
        launched = client.post("/api/conversations/"+cid+"/runs", json={"query":"synthetic task"}, headers=headers)
        assert launched.status_code == 200
        deadline = time.monotonic()+5
        while runner.received is None and time.monotonic()<deadline:
            time.sleep(.01)
        assert runner.received == {"context_model":"synthetic-model", "context_window_tokens":128000, "max_output_tokens":4096}
        rid = launched.json()["id"]
        while app.state.jobs and time.monotonic()<deadline:
            time.sleep(.01)
        assert client.get("/api/runs/"+rid).json()["status"] == "completed"

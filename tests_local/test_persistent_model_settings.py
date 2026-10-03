"""Encrypted model-setting persistence, using synthetic credentials only."""
import json
import os
import stat
import time

from fastapi.testclient import TestClient
import pytest

from geological_agent.team.model_settings import SessionModels
from geological_agent.team.model_vault import ModelVaultError
from geological_agent.team.server import COOKIE, create_app
from geological_agent.team.store import Store, digest
from test_model_settings import BUILTIN, POLICY, TOKEN, Runner, custom, group, wait_run


def saved(**kwargs):
    return custom(remember=True, **kwargs)


def ciphertext(app, uid="alice"):
    return bytes(app.state.store.db.execute(
        "SELECT ciphertext FROM model_profiles WHERE uid=?", (uid,)
    ).fetchone()[0])


def session(store, uid, name):
    token = "new-session-" + name
    with store.lock, store.db:
        store.db.execute("INSERT INTO auth VALUES (?,?,?,?)",
                         (digest(token), uid, token + "-csrf", time.time() + 600))
    return token


def test_remember_is_account_scoped_and_response_never_contains_credentials(group):
    app, (alice, bob, other), _, _ = group
    result = alice.put("/api/model-settings", json=saved())
    assert result.status_code == 200
    assert result.json()["storage"] == "account_encrypted"
    assert TOKEN not in result.text
    assert other.get("/api/model-settings").json()["model"] == "model-one"
    assert other.get("/api/model-settings").json()["has_token"]
    assert bob.get("/api/model-settings").json()["source"] == "builtin"
    assert not app.state.model_settings.profiles
    assert TOKEN.encode() not in ciphertext(app)
    assert TOKEN not in "\n".join(app.state.store.db.iterdump())
    assert "models.example" not in "\n".join(app.state.store.db.iterdump())


def test_restart_reloads_persistent_profile_with_same_key(group):
    app, (alice, _, _), _, _ = group
    assert alice.put("/api/model-settings", json=saved()).status_code == 200
    key_path = app.state.model_settings.vault.key_path
    key = key_path.read_bytes()
    app.state.model_settings.clear()
    new_store = Store(app.state.store.root)
    restarted = SessionModels(new_store, BUILTIN, POLICY)
    profile = restarted.get("session-alice")
    assert profile.api_token == TOKEN and profile.model == "model-one"
    assert profile.storage == "account_encrypted"
    assert key_path.read_bytes() == key
    new_store.db.close()


def test_http_app_restart_and_new_login_restore_without_token_entry(group):
    app, (alice, _, _), _, _ = group
    assert alice.put("/api/model-settings", json=saved()).status_code == 200
    assert alice.post("/api/logout").status_code == 200
    restarted = create_app(app.state.store.root, runner=Runner())
    token = session(restarted.state.store, "alice", "after-restart")
    with TestClient(restarted, base_url="http://127.0.0.1") as client:
        client.cookies.set(COOKIE, token)
        response = client.get("/api/model-settings")
        assert response.status_code == 200
        assert response.json()["storage"] == "account_encrypted"
        assert response.json()["model"] == "model-one"
        assert TOKEN not in response.text
    restarted.state.store.db.close()


def test_expired_or_disabled_accounts_cannot_read_saved_token(group):
    app, (alice, _, _), _, _ = group
    alice.put("/api/model-settings", json=saved())
    with app.state.store.lock, app.state.store.db:
        app.state.store.db.execute("UPDATE auth SET expires=0 WHERE uid='alice'")
    with pytest.raises(PermissionError):
        app.state.model_settings.get("session-alice")
    token = session(app.state.store, "alice", "disabled")
    with app.state.store.lock, app.state.store.db:
        app.state.store.db.execute("UPDATE users SET disabled=1 WHERE id='alice'")
    with pytest.raises(PermissionError):
        app.state.model_settings.get(token)
    assert ciphertext(app)


def test_clear_is_csrf_protected_account_scoped_and_survives_restart(group):
    app, (alice, bob, other), _, _ = group
    alice.put("/api/model-settings", json=saved())
    bob.put("/api/model-settings", json=saved(model="bob-model"))
    assert alice.delete("/api/model-settings", headers={"x-csrf-token": "wrong"}).status_code == 403
    assert other.get("/api/model-settings").json()["has_token"]
    assert alice.delete("/api/model-settings").status_code == 200
    assert alice.get("/api/model-settings").json()["source"] == "builtin"
    assert other.get("/api/model-settings").json()["source"] == "builtin"
    assert bob.get("/api/model-settings").json()["model"] == "bob-model"
    new_store = Store(app.state.store.root)
    assert SessionModels(new_store, BUILTIN, POLICY).get("session-alice").source == "builtin"
    new_store.db.close()


def test_session_only_use_preserves_saved_account_connections(group):
    app, (alice, _, other), _, _ = group
    alice.put("/api/model-settings", json=saved())
    result = alice.put("/api/model-settings", json=custom(model="temporary", remember=False))
    assert result.json()["storage"] == "login_session"
    assert other.get("/api/model-settings").json()["model"] == "model-one"
    app.state.model_settings.clear()
    assert app.state.model_settings.get("session-alice").model == "model-one"
    assert len(alice.get("/api/model-settings").json()["saved_profiles"]) == 1


def test_builtin_selection_keeps_saved_custom_connections(group):
    app, (alice, _, other), _, _ = group
    original = alice.put("/api/model-settings", json=saved()).json()
    assert alice.put("/api/model-settings", json={"source": "builtin"}).status_code == 200
    assert other.get("/api/model-settings").json()["source"] == "builtin"
    assert len(alice.get("/api/model-settings").json()["saved_profiles"]) == 1
    assert alice.post("/api/model-settings/activate", json={"profile_id": original["profile_id"]}).status_code == 200
    assert app.state.model_settings.get("session-alice").api_token == TOKEN


def test_remember_refreshes_other_session_overrides_without_cross_user_effect(group):
    app, (alice, bob, other), _, _ = group
    other.put("/api/model-settings", json=custom(model="session-only"))
    bob.put("/api/model-settings", json=custom(model="bob-temporary"))
    assert alice.put("/api/model-settings", json=saved()).status_code == 200
    assert other.get("/api/model-settings").json()["model"] == "model-one"
    assert bob.get("/api/model-settings").json()["model"] == "bob-temporary"


def test_save_uses_fresh_nonce_and_keeps_key_and_token(group):
    app, (alice, _, _), _, _ = group
    alice.put("/api/model-settings", json=saved())
    first = ciphertext(app)
    key = app.state.model_settings.vault.key_path.read_bytes()
    response = alice.put("/api/model-settings", json=saved(api_token="", keep_token=True))
    assert response.status_code == 200
    assert ciphertext(app) != first
    assert ciphertext(app)[1:13] != first[1:13]
    assert app.state.model_settings.vault.key_path.read_bytes() == key
    assert app.state.model_settings.get("session-alice").api_token == TOKEN


def test_persisted_token_cannot_follow_endpoint_change(group):
    app, (alice, _, _), _, _ = group
    alice.put("/api/model-settings", json=saved())
    before = ciphertext(app)
    response = alice.put("/api/model-settings", json=saved(
        base_url="https://another.example/v1", api_token="", keep_token=True))
    assert response.status_code == 400
    assert ciphertext(app) == before


@pytest.mark.parametrize("remember", ["true", 1, None, {}, []])
def test_remember_requires_boolean_and_never_saves_invalid_input(group, remember):
    app, (alice, _, _), _, _ = group
    assert alice.put("/api/model-settings", json=custom(remember=remember)).status_code == 400
    assert not app.state.store.db.execute("SELECT 1 FROM model_profiles").fetchone()
    assert not app.state.model_settings.vault.key_path.exists()


def test_encrypted_row_is_bound_to_owner_and_not_replayable_across_users(group):
    app, (alice, bob, _), _, _ = group
    alice.put("/api/model-settings", json=saved())
    with app.state.store.lock, app.state.store.db:
        app.state.store.db.execute("INSERT INTO model_profiles VALUES (?,?,?)",
                                   ("bob", ciphertext(app), time.time()))
    with pytest.raises(ModelVaultError):
        app.state.model_settings.get("session-bob")
    public = bob.get("/api/model-settings")
    assert public.status_code == 200
    assert public.json()["storage"] == "account_unavailable"
    assert TOKEN not in public.text
    assert alice.get("/api/model-settings").json()["storage"] == "account_encrypted"
    assert bob.delete("/api/model-settings").status_code == 200


@pytest.mark.parametrize("damage", ["tag", "version", "empty", "missing-key", "wrong-key"])
def test_corruption_fails_closed_and_can_be_cleared(group, damage):
    app, (alice, _, _), _, _ = group
    alice.put("/api/model-settings", json=saved())
    vault = app.state.model_settings.vault
    if damage == "missing-key":
        vault.key_path.unlink()
    elif damage == "wrong-key":
        vault.key_path.write_bytes(b"x" * 32)
    else:
        blob = ciphertext(app)
        broken = blob[:-1] + bytes([blob[-1] ^ 1]) if damage == "tag" else b""
        if damage == "version":
            broken = b"\x02" + blob[1:]
        with app.state.store.lock, app.state.store.db:
            app.state.store.db.execute("UPDATE model_profiles SET ciphertext=? WHERE uid='alice'", (broken,))
    with pytest.raises(ModelVaultError):
        app.state.model_settings.get("session-alice")
    cid = alice.post("/api/conversations").json()["id"]
    response = alice.post(f"/api/conversations/{cid}/runs", json={"query": "must not silently use builtin"})
    assert response.status_code == 400
    assert not app.state.store.db.execute("SELECT 1 FROM runs").fetchone()
    assert TOKEN not in response.text
    assert alice.delete("/api/model-settings").status_code == 200
    assert alice.get("/api/model-settings").json()["source"] == "builtin"


def test_missing_key_is_not_silently_regenerated(group):
    app, (alice, bob, _), _, _ = group
    alice.put("/api/model-settings", json=saved())
    key = app.state.model_settings.vault.key_path
    key.unlink()
    assert bob.put("/api/model-settings", json=saved()).status_code == 400
    assert not key.exists()
    assert app.state.store.db.execute("SELECT count(*) FROM model_profiles").fetchone()[0] == 1


def test_probe_with_remember_true_is_read_only(group):
    app, (alice, _, _), _, _ = group
    response = alice.post("/api/model-settings/test", json=saved())
    assert response.status_code == 400  # Synthetic provider deliberately returns no native call.
    assert not app.state.store.db.execute("SELECT 1 FROM model_profiles").fetchone()
    assert not app.state.model_settings.vault.key_path.exists()


def test_saved_profile_used_by_runtime_and_credential_masking(group):
    app, (alice, _, _), _, calls = group
    alice.put("/api/model-settings", json=saved())
    app.state.model_settings.clear()
    cid = alice.post("/api/conversations").json()["id"]
    rid = alice.post(f"/api/conversations/{cid}/runs", json={"query": "synthetic run"}).json()["id"]
    assert wait_run(alice, rid)["status"] == "completed"
    assert all(call[1] == TOKEN for call in calls)
    trace = (app.state.store.root / "traces" / (rid + ".jsonl")).read_text()
    assert TOKEN not in trace and "[REDACTED]" in trace
    assert TOKEN not in alice.get(f"/api/runs/{rid}/events").text


def test_posix_key_permissions_are_private_and_insecure_key_is_rejected(group):
    app, (alice, _, _), _, _ = group
    alice.put("/api/model-settings", json=saved())
    vault = app.state.model_settings.vault
    if os.name == "posix":
        assert stat.S_IMODE(vault.key_directory.stat().st_mode) == 0o700
        assert stat.S_IMODE(vault.key_path.stat().st_mode) == 0o600
        vault.key_path.chmod(0o644)
        with pytest.raises(ModelVaultError):
            app.state.model_settings.get("session-alice")


def test_ui_describes_account_persistence_and_has_clear_control(group):
    _, (alice, _, _), _, _ = group
    html = alice.get("/").text
    js = alice.get("/assets/app.js").text
    assert 'id="model-remember"' in html
    assert 'id="model-clear"' in html
    assert "remember:$('model-remember').checked" in js
    assert "method:'DELETE'" in js
    assert "localStorage" not in js and "sessionStorage" not in js

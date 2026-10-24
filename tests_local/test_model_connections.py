"""Named connections: synthetic credentials only; no external model requests."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from geological_agent.team.model_settings import SessionModels
from geological_agent.team.store import Store
from test_model_settings import BUILTIN, POLICY, TOKEN, custom, group

SECOND = "synthetic-second-token-for-profile-tests"


def saved(client, model, **kw):
    response = client.put("/api/model-settings", json=custom(model, remember=True, name=model, **kw))
    assert response.status_code == 200, response.text
    return response.json()


def current(client):
    response = client.get("/api/model-settings")
    assert response.status_code == 200
    return response.json()


def activate(client, profile):
    return client.post("/api/model-settings/activate", json={"profile_id": profile["profile_id"] if profile else None})


def test_multiple_connections_persist_and_switch_without_credentials(group):
    app, (alice, bob, other), _, _ = group
    first = saved(alice, "first")
    second = saved(alice, "second", api_token=SECOND, base_url="https://second.example/v1")
    assert first["profile_id"] != second["profile_id"]
    assert len(current(alice)["saved_profiles"]) == 2
    assert activate(alice, first).status_code == 200
    assert app.state.model_settings.get("session-alice").api_token == TOKEN
    assert current(other)["profile_id"] == first["profile_id"]
    assert not current(bob)["saved_profiles"]
    assert activate(alice, second).status_code == 200
    app.state.model_settings.clear()
    restarted = SessionModels(app.state.store, BUILTIN, POLICY)
    assert restarted.get("session-alice").api_token == SECOND
    assert len(restarted.public("session-alice")["saved_profiles"]) == 2
    assert TOKEN not in str(current(alice)) and SECOND not in str(current(alice))
    dump = "\n".join(app.state.store.db.iterdump())
    assert TOKEN not in dump and SECOND not in dump and "second.example" not in dump


def test_legacy_ciphertext_is_read_without_mutation_then_migrated_on_save(group):
    app, (alice, _, _), _, _ = group
    vault = app.state.model_settings.vault
    vault.put("alice", custom("legacy"))
    before = bytes(app.state.store.db.execute("SELECT ciphertext FROM model_profiles WHERE uid='alice'").fetchone()[0])
    legacy = current(alice)
    assert legacy["saved_profiles"][0]["name"] == "legacy"
    assert current(alice)["profile_id"] == legacy["profile_id"]
    after = bytes(app.state.store.db.execute("SELECT ciphertext FROM model_profiles WHERE uid='alice'").fetchone()[0])
    assert before == after
    saved(alice, "new")
    assert len(current(alice)["saved_profiles"]) == 2
    assert vault.get("alice")["format"] == "connections-v1"
    assert activate(alice, legacy).status_code == 200
    assert app.state.model_settings.get("session-alice").api_token == TOKEN


def test_edit_retains_token_from_selected_profile_not_current_profile(group):
    app, (alice, _, _), _, _ = group
    first = saved(alice, "first")
    second = saved(alice, "second", api_token=SECOND)
    edited = saved(alice, "first-renamed", api_token="", keep_token=True,
                   profile_id=first["profile_id"], revision=first["revision"])
    assert edited["revision"] == first["revision"] + 1
    assert edited["profile_id"] == first["profile_id"]
    assert app.state.model_settings.get("session-alice").api_token == TOKEN
    assert len(current(alice)["saved_profiles"]) == 2
    assert activate(alice, second).status_code == 200
    assert app.state.model_settings.get("session-alice").api_token == SECOND


def test_stale_edits_and_deletions_cannot_overwrite_newer_settings(group):
    _, (alice, _, _), _, _ = group
    first = saved(alice, "first")
    updated = saved(alice, "changed", profile_id=first["profile_id"], revision=first["revision"])
    stale = custom("stale", remember=True, name="stale", profile_id=first["profile_id"], revision=first["revision"])
    assert alice.put("/api/model-settings", json=stale).status_code == 400
    assert alice.request("DELETE", "/api/model-settings/profiles/" + first["profile_id"],
                         json={"revision": first["revision"]}).status_code == 400
    assert current(alice)["model"] == "changed"
    assert current(alice)["revision"] == updated["revision"]


def test_switch_builtin_and_delete_only_one_connection(group):
    _, (alice, _, _), _, _ = group
    first = saved(alice, "first")
    second = saved(alice, "second")
    assert activate(alice, None).status_code == 200
    assert current(alice)["source"] == "builtin"
    assert len(current(alice)["saved_profiles"]) == 2
    activate(alice, second)
    assert alice.request("DELETE", "/api/model-settings/profiles/" + first["profile_id"],
                         json={"revision": first["revision"]}).status_code == 200
    assert current(alice)["profile_id"] == second["profile_id"]
    assert alice.request("DELETE", "/api/model-settings/profiles/" + second["profile_id"],
                         json={"revision": second["revision"]}).status_code == 200
    assert current(alice)["source"] == "builtin" and not current(alice)["saved_profiles"]


def test_cross_account_ids_and_csrf_are_rejected(group):
    _, (alice, bob, _), _, _ = group
    first = saved(alice, "first")
    assert activate(bob, first).status_code == 404
    assert bob.request("DELETE", "/api/model-settings/profiles/" + first["profile_id"],
                       json={"revision": first["revision"]}).status_code == 404
    assert bob.put("/api/model-settings", json=custom(remember=True, profile_id=first["profile_id"],
                                                     revision=first["revision"])).status_code == 404
    assert alice.post("/api/model-settings/activate", json={"profile_id": None},
                      headers={"x-csrf-token": "wrong"}).status_code == 403
    assert alice.request("DELETE", "/api/model-settings/profiles/" + first["profile_id"],
                         json={"revision": first["revision"]}, headers={"x-csrf-token": "wrong"}).status_code == 403
    assert current(alice)["profile_id"] == first["profile_id"]


def test_temporary_edits_do_not_change_any_saved_profile(group):
    app, (alice, _, other), _, _ = group
    first = saved(alice, "first")
    result = alice.put("/api/model-settings", json=custom("temporary", api_token="", keep_token=True,
        profile_id=first["profile_id"], revision=first["revision"], remember=False, name="temporary"))
    assert result.status_code == 200 and result.json()["storage"] == "login_session"
    assert current(other)["model"] == "first"
    assert current(alice)["saved_profiles"][0]["model"] == "first"
    app.state.model_settings.clear()
    assert current(alice)["model"] == "first"


def test_selected_profile_probe_neither_activates_nor_mutates(group):
    app, (alice, _, _), _, calls = group
    first = saved(alice, "first")
    second = saved(alice, "second", api_token=SECOND)
    activate(alice, first)
    result = alice.post("/api/model-settings/test", json=custom("second", api_token="", keep_token=True,
        profile_id=second["profile_id"], revision=second["revision"], name="second", remember=True))
    assert result.status_code == 400  # Deliberate fake provider without a native call.
    assert calls[-1][1] == SECOND
    assert current(alice)["profile_id"] == first["profile_id"]
    assert current(alice)["saved_profiles"][1]["revision"] == 1


def test_concurrent_additions_from_separate_store_connections_are_not_lost(group):
    app, (alice, _, _), _, _ = group
    saved(alice, "initial")
    stores = [Store(app.state.store.root), Store(app.state.store.root)]
    managers = [SessionModels(store, BUILTIN, POLICY) for store in stores]
    barrier = Barrier(2)
    def add(index):
        barrier.wait(timeout=5)
        return managers[index].save("session-alice", custom("parallel-" + str(index), remember=True))
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(add, [0, 1]))
        assert len(current(alice)["saved_profiles"]) == 3
        assert {r.profile_id for r in results}.issubset({p["profile_id"] for p in current(alice)["saved_profiles"]})
    finally:
        for store in stores:
            store.db.close()


@pytest.mark.parametrize("field,value", [("name", ""), ("name", "x"*97), ("name", "\nsecret"),
                                         ("profile_id", 123), ("revision", True)])
def test_invalid_metadata_does_not_overwrite_saved_connections(group, field, value):
    _, (alice, _, _), _, _ = group
    saved(alice, "original")
    bad = custom("bad", remember=True, **{field:value})
    assert alice.put("/api/model-settings", json=bad).status_code == 400
    assert len(current(alice)["saved_profiles"]) == 1 and current(alice)["model"] == "original"


def test_new_controls_and_styles_are_served_without_browser_token_storage(group):
    _, (alice, _, _), _, _ = group
    html = alice.get("/").text
    assert 'id="model-profile-select"' in html
    assert 'id="model-profile-name"' in html
    assert 'id="model-new"' in html
    assert alice.get("/assets/model-profiles.css").status_code == 200
    source = alice.get("/assets/app.js").text
    assert "modelEditing.profile_id" in source and "modelEditing.revision" in source
    assert "localStorage" not in source and "sessionStorage" not in source

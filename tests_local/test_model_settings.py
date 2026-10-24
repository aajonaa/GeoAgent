"""Model settings acceptance: no live external APIs, with native HTTP fixtures."""
import json
from threading import Event
import time

from fastapi.testclient import TestClient
import httpx
import pytest

from geological_agent.contracts import Message, ModelRequest, ModelResponse, ToolCall
from geological_agent.langsmith_tracing import LangSmithTrace
from geological_agent.llm import LocalChatClient
from geological_agent.team.model_settings import (
    EndpointPolicy, ModelProfile, PinnedTransport, parse_profile, probe_model, redact,
)
from geological_agent.team.server import COOKIE, create_app
from geological_agent.team.store import digest
from geological_agent.tracing import JsonlTrace


TOKEN = "test-only-credential-DO-NOT-PERSIST"
BUILTIN = ModelProfile("builtin", "http://127.0.0.1:8000/v1", "builtin")
POLICY = EndpointPolicy(BUILTIN.base_url)


def custom(model="model-one", **kwargs):
    return {"source": "custom", "base_url": "https://models.example/v1", "model": model, "api_token": TOKEN, **kwargs}


@pytest.mark.parametrize("url", [
    "http://public.example/v1", "https://localhost/v1", "https://127.0.0.1/v1",
    "https://169.254.169.254/v1", "https://[::1]/v1", "https://10.1.2.3/v1",
    "https://224.0.0.1/v1", "https://user:password@models.example/v1",
    "https://models.example/v1?token=secret", "https://models.example/v1#key",
    "file:///etc/passwd", "https://models.example/v1/chat/completions",
    "https://models.example\\@localhost/v1", "https://models.example/\nkey",
])
def test_reject_unsafe_endpoints(url):
    with pytest.raises(ValueError):
        POLICY.normalize(url)


def test_tokens_never_follow_endpoint_changes():
    first = parse_profile(custom(), BUILTIN, BUILTIN, POLICY)
    assert TOKEN not in repr(first)
    assert TOKEN not in json.dumps(first.public())
    kept = parse_profile(custom(api_token="", keep_token=True), BUILTIN, first, POLICY)
    assert kept.api_token == TOKEN
    changed = custom(base_url="https://different.example/v1", api_token="", keep_token=True)
    with pytest.raises(ValueError, match="same API endpoint"):
        parse_profile(changed, BUILTIN, first, POLICY)
    cleared = parse_profile(custom(api_token=""), BUILTIN, first, POLICY)
    assert cleared.api_token == ""
    assert parse_profile({"source": "builtin"}, BUILTIN, first, POLICY) is BUILTIN


def dns(addresses):
    return lambda *args, **kwargs: [(2, 1, 6, "", (ip, 443)) for ip in addresses]


def test_transport_pins_public_ip_preserving_tls_identity():
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})
    transport = PinnedTransport("https://models.example/v1", POLICY, inner=httpx.MockTransport(handle),
                                resolver=dns(["93.184.216.34"]))
    with httpx.Client(transport=transport) as client:
        response = client.post("https://models.example/v1/chat/completions", json={"x": 1},
                               headers={"Authorization": "Bearer " + TOKEN})
    assert response.status_code == 200
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].headers["host"] == "models.example"
    assert seen[0].extensions["sni_hostname"] == "models.example"
    assert seen[0].headers["authorization"] == "Bearer " + TOKEN


@pytest.mark.parametrize("addresses", [["10.0.0.1"], ["93.184.216.34", "127.0.0.1"], ["::1"], []])
def test_dns_rebinding_and_mixed_answers_fail_closed(addresses):
    transport = PinnedTransport("https://models.example/v1", POLICY,
                                inner=httpx.MockTransport(lambda request: pytest.fail("No request allowed")),
                                resolver=dns(addresses))
    with httpx.Client(transport=transport) as client, pytest.raises(ValueError):
        client.post("https://models.example/v1/chat/completions")


def test_redirect_is_not_followed_and_other_paths_are_rejected():
    seen = []
    def redirect(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest"})
    transport = PinnedTransport("https://models.example/v1", POLICY, inner=httpx.MockTransport(redirect),
                                resolver=dns(["93.184.216.34"]))
    with httpx.Client(transport=transport) as client:
        assert client.post("https://models.example/v1/chat/completions").status_code == 302
        with pytest.raises(ValueError):
            client.post("https://models.example/other")
    assert len(seen) == 1


@pytest.mark.parametrize("first_finish_reason", ["tool_calls", "stop"])
def test_native_probe_uses_real_http_contract_not_text_json(first_finish_reason):
    requests = []
    def handle(request):
        data = json.loads(request.content)
        requests.append(data)
        assert request.headers["authorization"] == "Bearer " + TOKEN
        if len(requests) == 1:
            message = {"content": None, "tool_calls": [{"id": "probe", "type": "function",
                "function": {"name": "connection_probe", "arguments": '{"ok":true}'}}]}
            reason = first_finish_reason
        else:
            assert data["messages"][-2]["role"] == "tool"
            assert data["messages"][-2]["tool_call_id"] == "probe"
            assert data["messages"][-1]["role"] == "user"
            result = json.loads(data["messages"][-2]["content"])
            assert result["ok"] is True and len(result["receipt"]) == 32
            assert result["receipt"] not in data["messages"][-1]["content"]
            message, reason = {"content": result["receipt"]}, "stop"
        return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": reason}]})
    client = LocalChatClient("https://models.example/v1", "chosen-model", TOKEN, transport=httpx.MockTransport(handle))
    try:
        assert probe_model(client)["ok"]
    finally:
        client.close()
    assert [r["tool_choice"] for r in requests] == ["required", "auto"]
    assert all(r["model"] == "chosen-model" for r in requests)
    assert TOKEN not in json.dumps(requests)


@pytest.mark.parametrize("reason,arguments", [
    ("length", '{"ok":true}'), ("", '{"ok":true}'),
    ("stop", '{"ok":'), ("stop", '{"ok":1}'),
    ("stop", '{"ok":true,"unexpected":1}'),
])
def test_probe_rejects_truncated_or_invalid_native_calls(reason, arguments):
    class Client:
        def invoke(self, request):
            return ModelResponse("", (ToolCall("id", "connection_probe", arguments),), reason)
    with pytest.raises(ValueError):
        probe_model(Client())


def test_probe_rejects_plain_text_and_malformed_arguments():
    class Client:
        def invoke(self, request):
            return ModelResponse('{"name":"connection_probe","arguments":{"ok":true}}')
    with pytest.raises(ValueError, match="native tool"):
        probe_model(Client())


def test_redaction_preserves_contracts_and_masks_nested_credentials():
    response = ModelResponse("echo " + TOKEN, (ToolCall("id", "x", {"api_token": TOKEN, "values": [1, 2]}),))
    safe = redact(response, (TOKEN,))
    assert isinstance(safe, ModelResponse)
    assert safe.content == "echo [REDACTED]"
    assert safe.tool_calls[0].arguments == {"api_token": "[REDACTED]", "values": [1, 2]}


class Calls:
    def __init__(self, profile, log):
        self.profile, self.log = profile, log
    def invoke(self, request):
        self.log.append((self.profile.model, self.profile.api_token, request))
        return ModelResponse(self.profile.model)
    def close(self):
        pass


class Runner:
    isolated = False
    def __init__(self):
        self.entered, self.release = Event(), Event()
        self.results = []
    def stop(self, rid):
        pass
    def run(self, rid, query, files, cancel, model_call, on_trace, **kwargs):
        request = ModelRequest((Message("user", "synthetic acceptance"),), ())
        first = model_call(request, cancel)
        if "HOLD" in query:
            self.entered.set()
            assert self.release.wait(10)
        second = model_call(request, cancel)
        self.results.append((first, second))
        on_trace("diagnostic", {"text": TOKEN, "api_token": TOKEN})
        return {"status": "completed", "answer": second.content, "files": {}, "turns": 2}


@pytest.fixture
def group(tmp_path, monkeypatch):
    monkeypatch.delenv("GEOTOOL_LANGSMITH_ENABLED", raising=False)
    runner, calls = Runner(), []
    app = create_app(tmp_path, runner=runner,
        model_factory=lambda: Calls(BUILTIN, calls),
        profile_factory=lambda profile, **kw: Calls(profile, calls))
    store = app.state.store
    clients = []
    # Authentication boundary is exercised with real session rows, without
    # repeating expensive password-hash coverage from test_team.py.
    with TestClient(app, base_url="http://127.0.0.1") as lifecycle:
        for i, name in enumerate(("alice", "bob", "alice-other-session")):
            uid = "alice" if i == 2 else name
            token = "session-" + name
            with store.lock, store.db:
                if i < 2:
                    store.db.execute("INSERT INTO users(id,username,password,role) VALUES (?,?,?,?)",
                                     (uid, name, "not-used", "member"))
                store.db.execute("INSERT INTO auth VALUES (?,?,?,?)", (digest(token), uid, token + "-csrf", time.time() + 600))
            client = TestClient(app, base_url="http://127.0.0.1")
            client.cookies.set(COOKIE, token)
            client.headers["x-csrf-token"] = token + "-csrf"
            clients.append(client)
        yield app, clients, runner, calls
    for client in clients:
        client.close()


def wait_run(client, rid):
    for _ in range(100):
        run = client.get("/api/runs/" + rid).json()
        if run["status"] != "running":
            return run
        time.sleep(.02)
    pytest.fail("Run did not finish")


def test_configs_are_user_and_session_scoped_and_never_persisted(group):
    app, (alice, bob, other), _, _ = group
    result = alice.put("/api/model-settings", json=custom())
    assert result.status_code == 200
    assert result.json()["has_token"] is True
    assert TOKEN not in result.text
    assert alice.get("/api/model-settings").json()["model"] == "model-one"
    assert bob.get("/api/model-settings").json()["source"] == "builtin"
    assert other.get("/api/model-settings").json()["source"] == "builtin"
    assert alice.put("/api/model-settings", json=custom(), headers={"x-csrf-token": "wrong"}).status_code == 403
    assert alice.put("/api/model-settings", json={**custom(), "uid": "bob"}).status_code == 400
    assert TOKEN not in "\n".join(app.state.store.db.iterdump())


def test_all_calls_use_frozen_profile_after_settings_change_and_trace_masks_token(group):
    app, (alice, _, _), runner, calls = group
    assert alice.put("/api/model-settings", json=custom()).status_code == 200
    cid = alice.post("/api/conversations").json()["id"]
    rid = alice.post(f"/api/conversations/{cid}/runs", json={"query": "HOLD"}).json()["id"]
    assert runner.entered.wait(5)
    assert alice.put("/api/model-settings", json=custom("model-two", api_token="second-key")).status_code == 200
    runner.release.set()
    assert wait_run(alice, rid)["answer"] == "model-one"
    assert [c[:2] for c in calls] == [("model-one", TOKEN), ("model-one", TOKEN)]
    trace = (app.state.store.root / "traces" / (rid + ".jsonl")).read_text()
    assert TOKEN not in trace
    assert "[REDACTED]" in trace
    assert TOKEN not in "\n".join(app.state.store.db.iterdump())
    events = alice.get(f"/api/runs/{rid}/events").text
    assert TOKEN not in events
    assert '"model": "model-one"' in events


def test_logout_expiry_and_restart_remove_session_credentials(group):
    app, (alice, bob, _), _, _ = group
    alice.put("/api/model-settings", json=custom())
    assert alice.post("/api/logout").status_code == 200
    assert not app.state.model_settings.profiles
    bob.put("/api/model-settings", json=custom())
    with app.state.store.lock, app.state.store.db:
        app.state.store.db.execute("UPDATE auth SET expires=0 WHERE uid='bob'")
    assert bob.get("/api/model-settings").status_code == 401
    assert not app.state.model_settings.profiles
    restarted = create_app(app.state.store.root, runner=Runner())
    assert not restarted.state.model_settings.profiles


def test_resume_cannot_silently_switch_model(group):
    app, (alice, _, _), _, _ = group
    alice.put("/api/model-settings", json=custom())
    store = app.state.store
    cid = alice.post("/api/conversations").json()["id"]
    rid = store.begin("alice", cid, "original task")
    original = app.state.model_settings.get("session-alice").identity()
    store.event(rid, {"kind": "model_config", "profile": original})
    store.pause_input(rid, "a" * 32, "b" * 32, {"id": "c" * 32, "question": "Choose scope"})
    store.finish(rid, status="needs_input", answer="Choose scope")
    alice.put("/api/model-settings", json=custom("different-model"))
    response = alice.post(f"/api/conversations/{cid}/runs", json={"query": "my answer"})
    assert response.status_code == 409
    assert store.db.execute("SELECT state FROM input_requests").fetchone()[0] == "pending"
    alice.put("/api/model-settings", json=custom())
    response = alice.post(f"/api/conversations/{cid}/runs", json={"query": "my answer"})
    assert response.status_code == 200
    assert wait_run(alice, response.json()["id"])["status"] == "completed"


def test_probe_failures_hide_provider_secrets_and_do_not_save_configuration(group):
    app, (alice, _, _), _, _ = group
    # This fake model emits no native call, so the synthetic probe must fail.
    response = alice.post("/api/model-settings/test", json=custom())
    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert TOKEN not in response.text
    assert alice.get("/api/model-settings").json()["source"] == "builtin"


def test_langsmith_metadata_uses_selected_model_and_provider(tmp_path):
    trace = LangSmithTrace(JsonlTrace(tmp_path / "trace.jsonl"), None,
                           project="offline-fixture", run_factory=lambda **kw: None)
    trace.set_model("selected-custom-model", "openai-compatible")
    captured = []
    trace._begin = lambda *args: captured.append(args)
    trace.root = object()
    trace._export("model_requested", {"turn": 1, "request": {"messages": [], "tools": []}})
    assert captured[0][-1]["ls_model_name"] == "selected-custom-model"
    assert captured[0][-1]["ls_provider"] == "openai-compatible"

def test_credential_redaction_never_mutates_executable_protocol(group, monkeypatch):
    app, (alice, _, _), runner, calls = group
    # A local server's placeholder key can equal a valid native protocol value.
    assert alice.put("/api/model-settings", json=custom(api_token="none")).status_code == 200
    observed = []
    def run(rid, query, files, cancel, model_call, on_trace, **kwargs):
        request = ModelRequest((Message("user", "Answer without tools."),), (), "none")
        reply = model_call(request, cancel)
        observed.append(reply)
        on_trace("diagnostic", {"api_token": "none", "text": "placeholder=none"})
        return {"status": "completed", "answer": reply.content, "files": {}, "turns": 1}
    monkeypatch.setattr(runner, "run", run)
    cid = alice.post("/api/conversations").json()["id"]
    rid = alice.post(f"/api/conversations/{cid}/runs", json={"query": "Answer only."}).json()["id"]
    assert wait_run(alice, rid)["status"] == "completed"
    assert len(calls) == 1 and calls[0][2].tool_choice == "none"
    assert observed[0].content == "model-one"
    trace = (app.state.store.root / "traces" / (rid + ".jsonl")).read_text()
    assert '"api_token": "none"' not in trace
    assert "placeholder=none" not in trace
    assert "[REDACTED]" in trace

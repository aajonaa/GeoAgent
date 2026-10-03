from dataclasses import dataclass
from pathlib import Path
import time

from fastapi.testclient import TestClient

from geological_agent.contracts import ArtifactRef, RunResult
from geological_agent.web_server import make_app, Store


class Model:
    def close(self):
        self.closed = True


class Agent:
    def run(self, text, *, workspace, cancel_event):
        (workspace / "total.json").write_text('{"total":16}')
        return RunResult("test-run", "completed", "Total: 16. File: total.json", (ArtifactRef("total.json", "application/json", "p1"),),
                         None, 1, {"answer": "Total: 16. File: total.json"})


def app(tmp_path):
    return make_app(tmp_path, "operator-key", model_factory=Model, agent_builder=lambda *args, **kwargs: Agent())


def session(client):
    response = client.post("/api/sessions", headers={"Authorization": "Bearer operator-key"})
    assert response.status_code == 200
    data = response.json()
    return "/api/sessions/" + data["id"], {"Authorization": "Bearer " + data["token"]}


def test_auth_origin_and_release(tmp_path):
    with TestClient(app(tmp_path), base_url="http://127.0.0.1") as client:
        health = client.get("/api/health").json()
        assert health["runtime"] == "geological_agent.agent.runtime.AgentRuntime"
        assert health["sandbox"] is False and health["answer_publication"] == "after_review"
        assert client.post("/api/sessions").status_code == 401
        assert client.post("/api/auth", headers={"Authorization": "Bearer operator-key", "Origin": "https://evil.example"}).status_code == 403
        assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 403
        url, headers = session(client)
        assert client.get(url).status_code == 401
        assert "token_hash" not in client.get(url, headers=headers).json()


def test_upload_boundaries_and_new_workspace_example(tmp_path):
    with TestClient(app(tmp_path), base_url="http://127.0.0.1") as client:
        url, headers = session(client)
        for name in ("../outside", ".agent/secret", "/etc/passwd", "C:\\secret"):
            assert client.post(url + "/upload", params={"name": name}, headers=headers, content=b"x").status_code == 400
        assert client.post(url + "/upload?name=samples.csv", headers=headers, content=b"a,b\n1,2\n").status_code == 200
        assert client.post(url + "/upload?name=samples.csv", headers=headers, content=b"replace").status_code == 409
        assert client.post(url + "/example", headers=headers).status_code == 200
        assert client.post(url + "/example", headers=headers).status_code == 409
        names = {item["path"] for item in client.get(url + "/files", headers=headers).json()["result"]["items"]}
        assert names == {"calc.py", "samples.csv"}


def test_native_worker_publication_and_download(tmp_path):
    application = app(tmp_path)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        url, headers = session(client)
        assert client.post(url + "/messages", headers=headers, json={"text": "calculate"}).status_code == 200
        sid = url.rsplit("/", 1)[1]
        application.state.jobs[sid][0].join(5)
        state = client.get(url, headers=headers).json()
        assert state["status"] == "completed" and "16" in state["answer"]
        rows = application.state.store.events(sid, 0)
        assert [row["kind"] for row in rows] == ["user", "status", "answer_start", "answer_delta", "completed"]
        assert application.state.store.events(sid, rows[-1]["id"]) == []
        aid = state["artifacts"][0]["id"]
        assert client.get(url + "/artifacts/" + aid).status_code == 401
        assert client.post(url + "/download-access", headers=headers).status_code == 200
        response = client.get(url + "/artifacts/" + aid)
        assert response.status_code == 200 and response.json()["total"] == 16
        assert "attachment" in response.headers["content-disposition"]


def test_restart_marks_running_task_interrupted(tmp_path):
    store = Store(tmp_path)
    sid = store.create()["id"]
    store.patch(sid, status="running")
    restored = Store(tmp_path)
    assert restored.get(sid)["status"] == "interrupted"
    assert restored.events(sid, 0)[-1]["kind"] == "finished"

"""Private HTTP/SSE entry point for the native, tested AgentRuntime.

Transport only: no alternate planner, tool adapter, or completion policy.
Trusted single operator; execute_python is NOT a security sandbox.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
from threading import Event, RLock, Thread
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .bootstrap import create_agent
from .llm import LocalChatClient
from .settings import Settings
from .tracing import configured_trace


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = RLock()
        self.db = sqlite3.connect(self.root / "web.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,data TEXT NOT NULL);"
                             "CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,sid TEXT,kind TEXT,data TEXT);"
                             "CREATE INDEX IF NOT EXISTS event_session ON events(sid,id);")
        with self.lock, self.db:
            for sid, raw in self.db.execute("SELECT id,data FROM sessions").fetchall():
                state = json.loads(raw)
                if state["status"] == "running":
                    state["status"] = "interrupted"
                    self.save(state)
                    self.event(sid, "finished", {"status": "interrupted", "message": "Server restarted. Files are retained; submit a new task to continue."})

    def private(self, sid):
        if not re.fullmatch(r"[a-f0-9]{32}", sid):
            raise HTTPException(404, "Unknown workspace")
        return self.root / sid

    def get(self, sid):
        self.private(sid)
        with self.lock:
            row = self.db.execute("SELECT data FROM sessions WHERE id=?", (sid,)).fetchone()
        if row is None:
            raise HTTPException(404, "Unknown workspace")
        return json.loads(row[0])

    def save(self, state):
        with self.lock, self.db:
            self.db.execute("INSERT INTO sessions VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                            (state["id"], json.dumps(state)))

    def patch(self, sid, **fields):
        with self.lock:
            state = {**self.get(sid), **fields}
            self.save(state)
            return state

    def create(self):
        sid, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
        for name in ("workspace", "artifacts", "results"):
            (self.private(sid) / name).mkdir(parents=True, mode=0o700)
        self.save({"id": sid, "token_hash": hashlib.sha256(token.encode()).hexdigest(), "status": "idle",
                   "task": "", "answer": "", "artifacts": [], "turn": 0, "step": 0, "active_seconds": 0})
        return {"id": sid, "token": token}

    def event(self, sid, kind, data):
        with self.lock, self.db:
            self.db.execute("INSERT INTO events(sid,kind,data) VALUES (?,?,?)", (sid, kind, json.dumps(data)))

    def events(self, sid, after):
        with self.lock:
            rows = self.db.execute("SELECT id,kind,data FROM events WHERE sid=? AND id>? ORDER BY id LIMIT 250", (sid, after)).fetchall()
        return [{"id": row[0], "kind": row[1], "data": json.loads(row[2])} for row in rows]

    def path(self, sid, relative):
        base = (self.private(sid) / "workspace").resolve()
        path = (base / relative).resolve()
        if not relative or "\\" in relative or ":" in relative or Path(relative).is_absolute() or not path.is_relative_to(base) or ".agent" in Path(relative).parts:
            raise HTTPException(400, "Use a relative workspace filename outside .agent")
        return path

    def artifacts(self, sid, references):
        items = []
        for ref in references:
            path = self.path(sid, ref.path)
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            aid = hashlib.sha256((ref.path + "\0" + digest).encode()).hexdigest()
            target = self.private(sid) / "artifacts" / aid
            target.write_bytes(raw)
            item = {"id": aid, "name": ref.path, "bytes": len(raw), "sha256": digest}
            target.with_suffix(".json").write_text(json.dumps(item), encoding="utf-8")
            items.append(item)
        return items


class WebTrace:
    def __init__(self, inner, store, sid):
        self.inner, self.store, self.sid = inner, store, sid

    def execution_context(self):
        return self.inner.execution_context()

    def emit(self, event, **fields):
        self.inner.emit(event, **fields)
        send = lambda kind, data: self.store.event(self.sid, kind, data)
        if event == "model_requested":
            turn = fields.get("turn", 0)
            self.store.patch(self.sid, turn=turn)
            label = "Preparing verified answer" if fields.get("phase") == "final_answer" else "GeoGPT working"
            send("status", {"message": f"{label} / turn {turn}"})
        elif event == "completion_review_requested":
            send("status", {"message": "Checking " + fields.get("phase", "completion")})
        elif event in ("completion_rejected", "completion_review_protocol_error", "model_protocol_error"):
            send("status", {"message": "Correcting the previous attempt"})
        elif event == "tool_requested":
            call = fields["call"]
            args = json.loads(call.arguments) if isinstance(call.arguments, str) else call.arguments
            send("tool_start", {"id": call.id, "tool": call.name, "arguments": args,
                                "summary": args.get("path") or args.get("skill_id") or call.name})
        elif event in ("tool_completed", "tool_failed"):
            result = fields["result"]
            data = result.data
            output = data.get("stdout") or data.get("content") or data.get("stderr") or ""
            send("tool_result", {"id": result.call_id, "result": {"ok": result.status == "ok",
                 "summary": "Completed" if result.status == "ok" else (result.error.message if result.error else result.status),
                 "output": output, "result": data}})


def make_app(root=None, access_key=None, *, model_factory=None, agent_builder=create_agent):
    root = root or os.environ.get("GEOTOOL_WEB_STATE", str(Path.home() / ".local/state/geotoolagent-web"))
    if access_key is None:
        access_key = Path(os.environ["GEOTOOL_WEB_KEY_FILE"]).read_text().strip()
    if not access_key:
        raise ValueError("A nonempty access key is required")
    store, jobs, guard = Store(root), {}, RLock()
    settings = Settings()
    release = os.environ.get("GEOTOOL_RELEASE", "native-web-local")
    assets = Path(__file__).parent / "web"
    model_key = os.environ.get("GEOTOOL_MODEL_KEY") or os.environ.get("WORKSPACE_MODEL_KEY", "")
    model_factory = model_factory or (lambda: LocalChatClient(
        os.environ.get("GEOTOOL_MODEL_URL") or os.environ.get("WORKSPACE_MODEL_URL", "http://127.0.0.1:8000/v1"),
        os.environ.get("GEOTOOL_MODEL") or os.environ.get("WORKSPACE_MODEL") or "GeoGPT-Research-Project/Qwen2.5-72B-GeoGPT", model_key))

    @asynccontextmanager
    async def lifespan(app):
        yield
        for thread, cancel in list(jobs.values()):
            cancel.set()
        for thread, cancel in list(jobs.values()):
            await asyncio.to_thread(thread.join, 2)

    app = FastAPI(title="GeoToolAgent Native LangGraph", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.jobs = store, jobs

    def token(request):
        return request.headers.get("authorization", "").removeprefix("Bearer ")

    def operator(request):
        if not secrets.compare_digest(token(request).encode(), access_key.encode()):
            raise HTTPException(401, "Workspace access key required")

    def authorize(request, sid, download=False):
        value = token(request) or (request.cookies.get("workspace_download", "") if download else "")
        if not secrets.compare_digest(hashlib.sha256(value.encode()).hexdigest(), store.get(sid)["token_hash"]):
            raise HTTPException(401, "Workspace session token required")

    @app.middleware("http")
    async def boundary(request, call_next):
        origin = request.headers.get("origin")
        if request.url.hostname not in ("127.0.0.1", "localhost") or (origin and origin.rstrip("/") != str(request.base_url).rstrip("/")):
            return JSONResponse({"detail": "Only same-origin loopback access is allowed"}, status_code=403)
        response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    @app.get("/api/health")
    def health():
        return {"ok": True, "release": release, "runtime": "geological_agent.agent.runtime.AgentRuntime",
                "sandbox": False, "single_operator": True, "progress_protocol": "SSE", "answer_publication": "after_review"}

    @app.post("/api/auth")
    def auth(request: Request):
        operator(request)
        return {"ok": True}

    @app.post("/api/sessions")
    def create(request: Request):
        operator(request)
        return store.create()

    @app.get("/api/sessions/{sid}")
    def session(sid: str, request: Request):
        authorize(request, sid)
        return {key: value for key, value in store.get(sid).items() if key != "token_hash"}

    def worker(sid, text, cancel):
        model = None
        started = time.monotonic()
        try:
            model = model_factory()
            def traces(run_id, workspace):
                return WebTrace(configured_trace(workspace / ".agent/traces" / (run_id + ".jsonl"), secrets=(model_key, access_key)), store, sid)
            agent = agent_builder(model, settings=settings, trace_factory=traces)
            result = agent.run(text, workspace=store.private(sid) / "workspace", cancel_event=cancel)
            saved = store.private(sid) / "results" / (result.run_id + ".json")
            saved.write_text(json.dumps(asdict(result), ensure_ascii=False), encoding="utf-8")
            attachments = store.artifacts(sid, result.artifacts)
            store.patch(sid, status=result.status, answer=result.answer, artifacts=attachments,
                        run_id=result.run_id, turn=result.model_turns, active_seconds=time.monotonic() - started)
            if result.answer:
                store.event(sid, "answer_start", {"provisional": False})
                store.event(sid, "answer_delta", {"text": result.answer})
            if result.status == "completed":
                store.event(sid, "completed", {"artifacts": attachments})
            else:
                store.event(sid, "finished", {"status": result.status, "message": result.reason or result.status, "artifacts": attachments})
        except Exception as exc:
            message = f"Run failed ({type(exc).__name__}). Files and local trace are retained."
            store.patch(sid, status="failed", active_seconds=time.monotonic() - started)
            store.event(sid, "finished", {"status": "failed", "message": message})
        finally:
            if model is not None:
                model.close()

    @app.post("/api/sessions/{sid}/messages")
    async def send(sid: str, request: Request):
        authorize(request, sid)
        data = await request.json()
        text = data.get("text") if isinstance(data, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(400, "A nonempty task is required")
        with guard:
            if sid in jobs and jobs[sid][0].is_alive():
                raise HTTPException(409, "Wait for the current run to finish or stop")
            cancel = Event()
            thread = Thread(target=worker, args=(sid, text, cancel), daemon=True)
            store.patch(sid, status="running", task=text, answer="", artifacts=[], turn=0)
            store.event(sid, "user", {"text": text})
            store.event(sid, "status", {"message": "Starting native LangGraph run"})
            jobs[sid] = thread, cancel
            thread.start()
        return {"status": "running"}

    @app.post("/api/sessions/{sid}/cancel")
    def cancel(sid: str, request: Request):
        authorize(request, sid)
        if sid in jobs:
            jobs[sid][1].set()
        store.event(sid, "status", {"message": "Stop requested; waiting for the current operation to return"})
        return {"status": "stopping"}

    @app.post("/api/sessions/{sid}/upload")
    async def upload(sid: str, request: Request, name: str):
        authorize(request, sid)
        if store.get(sid)["status"] == "running":
            raise HTTPException(409, "Wait for the current run before uploading")
        path = store.path(sid, name)
        if path.exists():
            raise HTTPException(409, "File already exists; use a new filename")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > settings.max_file_bytes:
                raise HTTPException(413, "File exceeds the current tool file-size allowance")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(raw)
        return {"ok": True}

    @app.post("/api/sessions/{sid}/example")
    def example(sid: str, request: Request):
        authorize(request, sid)
        if store.get(sid)["status"] == "running":
            raise HTTPException(409, "Wait for the current run")
        path = store.path(sid, "calc.py")
        if path.exists():
            raise HTTPException(409, "Load this example into a new workspace")
        path.write_text("def contained_metal(ore_tonnes, grade_pct):\n    return ore_tonnes * grade_pct\n\nif __name__ == '__main__':\n    print(contained_metal(200, 1.5))\n", encoding="utf-8")
        return {"ok": True}

    @app.get("/api/sessions/{sid}/files")
    def files(sid: str, request: Request):
        authorize(request, sid)
        base = store.private(sid) / "workspace"
        items = [{"path": path.relative_to(base).as_posix(), "bytes": path.stat().st_size}
                 for path in base.rglob("*") if ".agent" not in path.relative_to(base).parts and path.is_file()
                 and not path.is_symlink() and path.resolve().is_relative_to(base.resolve())]
        return {"ok": True, "result": {"items": sorted(items, key=lambda item: item["path"])}}

    @app.get("/api/sessions/{sid}/events")
    async def events(sid: str, request: Request, after: int = 0):
        authorize(request, sid)
        async def stream():
            cursor, tick = after, 0
            while not await request.is_disconnected():
                for event in store.events(sid, cursor):
                    cursor = event["id"]
                    yield "id: " + str(cursor) + "\ndata: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                tick += 1
                if tick % 25 == 0:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.4)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    @app.post("/api/sessions/{sid}/download-access")
    def download_access(sid: str, request: Request):
        authorize(request, sid)
        response = JSONResponse({"ok": True})
        response.set_cookie("workspace_download", token(request), httponly=True, secure=request.url.scheme == "https",
                            samesite="strict", path="/api/sessions/" + sid + "/artifacts/")
        return response

    @app.get("/api/sessions/{sid}/artifacts/{aid}")
    def artifact(sid: str, aid: str, request: Request):
        authorize(request, sid, download=True)
        if not re.fullmatch(r"[a-f0-9]{64}", aid):
            raise HTTPException(404, "Unknown artifact")
        path = store.private(sid) / "artifacts" / aid
        if not path.is_file() or not path.with_suffix(".json").is_file():
            raise HTTPException(404, "Unknown artifact")
        meta = json.loads(path.with_suffix(".json").read_text())
        return FileResponse(path, filename=Path(meta["name"]).name, media_type="application/octet-stream")

    @app.get("/{name:path}")
    def static(name: str):
        name = name or "index.html"
        if name not in {"index.html", "app.js", "style.css", "vendor/katex.min.js", "vendor/auto-render.min.js", "vendor/katex-LICENSE"}:
            raise HTTPException(404, "Not found")
        return FileResponse(assets / name)

    return app


def main():
    import uvicorn
    os.umask(0o077)
    uvicorn.run(make_app(), host="127.0.0.1", port=int(os.environ.get("GEOTOOL_WEB_PORT", "50012")),
                access_log=False, proxy_headers=False)


if __name__ == "__main__":
    main()

"""Authenticated MemoraX settings and explicit approvals, separate from RAG/evidence."""
from dataclasses import asdict
import hashlib
import json
import os
import re
import time
import uuid

import asyncio
from fastapi import Request

from ..memorax import MemoraXClient, MemoryUnavailable, MAX_NOTE, MAX_QUERY, SECRET_PATTERN


class AccountMemory:
    def __init__(self, store, *, client_factory=None):
        self.store = store
        self.client_factory = client_factory or MemoraXClient
        self.injected_client = client_factory is not None
        with store.lock, store.db:
            store.db.executescript("""
            CREATE TABLE IF NOT EXISTS memorax_settings(
              uid TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
              enabled INTEGER NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS memorax_namespace(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memorax_automatic(
              uid TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
              enabled INTEGER NOT NULL, since REAL NOT NULL, epoch TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memorax_bindings(
              cid TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
              uid TEXT NOT NULL REFERENCES users(id), project_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memorax_approvals(
              uid TEXT NOT NULL REFERENCES users(id), project_id TEXT NOT NULL, approval_id TEXT NOT NULL,
              fingerprint TEXT NOT NULL, receipt TEXT NOT NULL, created REAL NOT NULL,
              PRIMARY KEY(uid,project_id,approval_id));
            """)
            store.db.execute("INSERT OR IGNORE INTO memorax_namespace VALUES(1,?)", (uuid.uuid4().hex,))
            self.namespace = store.db.execute("SELECT value FROM memorax_namespace WHERE id=1").fetchone()[0]

    def public(self, uid):
        with self.store.lock:
            row = self.store.db.execute("SELECT enabled,project_id,revision FROM memorax_settings WHERE uid=?", (uid,)).fetchone()
            auto = self.store.db.execute("SELECT enabled,since,epoch FROM memorax_automatic WHERE uid=?", (uid,)).fetchone()
        automatic = bool(row and row[0] and auto and auto[0])
        return {"enabled": bool(row[0]) if row else False, "project_id": row[1] if row else "default",
                "revision": row[2] if row else 0,
                "configured": self.injected_client or bool(os.environ.get("GEOTOOL_MEMORAX_KEY_FILE") or os.environ.get("GEOTOOL_MEMORAX_API_KEY")),
                "write_policy": "future_user_quotes_automatic" if automatic else "explicit_approval_only",
                "automatic_enabled": automatic, "automatic_since": auto[1] if auto else 0,
                "automatic_epoch": auto[2] if auto else ""}

    def save(self, uid, value):
        if (set(value) not in ({"enabled", "project_id", "revision"}, {"enabled", "project_id", "revision", "automatic_enabled"})
                or type(value["enabled"]) is not bool
                or ("automatic_enabled" in value and type(value["automatic_enabled"]) is not bool)
                or not isinstance(value["project_id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value["project_id"])
                or type(value["revision"]) is not int or value["revision"] < 0):
            raise ValueError("Provide enabled, a lowercase project ID, and the current revision")
        with self.store.lock, self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            previous = self.public(uid)
            if previous["revision"] != value["revision"]:
                raise ValueError("Memory settings changed; reload before saving")
            self.store.db.execute("INSERT INTO memorax_settings VALUES(?,?,?,?) ON CONFLICT(uid) DO UPDATE SET "
                                  "enabled=excluded.enabled,project_id=excluded.project_id,revision=excluded.revision",
                                  (uid, value["enabled"], value["project_id"], value["revision"] + 1))
            automatic = value["enabled"] and value.get("automatic_enabled", previous["automatic_enabled"])
            if automatic != previous["automatic_enabled"]:
                self.store.db.execute("INSERT INTO memorax_automatic VALUES(?,?,?,?) ON CONFLICT(uid) DO UPDATE SET "
                    "enabled=excluded.enabled,since=excluded.since,epoch=excluded.epoch",
                    (uid, automatic, time.time(), uuid.uuid4().hex))
        return self.public(uid)

    def scope(self, uid, cid, project):
        self.store.conversation(uid, cid)
        with self.store.lock, self.store.db:
            self.store.db.execute("INSERT OR IGNORE INTO memorax_bindings VALUES(?,?,?)", (cid, uid, project))
            row = self.store.db.execute("SELECT project_id FROM memorax_bindings WHERE cid=? AND uid=?", (cid, uid)).fetchone()
        if row is None:
            raise PermissionError("Memory scope ownership mismatch")
        project = row[0]
        digest = hashlib.sha256(json.dumps(["geoagent-memorax-v1", self.namespace, uid, project]).encode()).hexdigest()
        return project, "geoagent-" + digest

    def recall(self, uid, cid, query, *, supported=True):
        settings = self.public(uid)
        if not settings["enabled"]:
            return {"status": "disabled", "records": []}
        if not supported:
            return {"status": "unsupported_runner", "records": []}
        if not isinstance(query, str) or not 1 <= len(query) <= MAX_QUERY or SECRET_PATTERN.search(query):
            return {"status": "query_not_eligible", "records": []}
        project, user_id = self.scope(uid, cid, settings["project_id"])
        try:
            records = self.client_factory().search(user_id, query, limit=3)
            return {"status": "recalled" if records else "empty", "records": [asdict(row) for row in records], "project_id": project}
        except MemoryUnavailable as exc:
            return {"status": "unavailable", "records": [], "code": exc.code}

    def approve(self, uid, cid, value):
        if set(value) != {"approved", "approval_id", "kind", "text"} or value["approved"] is not True:
            raise ValueError("Explicit approval and an approval ID are required")
        if (value["kind"] not in ("preference", "decision") or not isinstance(value["text"], str)
                or not 1 <= len(value["text"].strip()) <= MAX_NOTE or SECRET_PATTERN.search(value["text"])):
            raise ValueError("Approve only a preference or confirmed decision, without credentials")
        try:
            if str(uuid.UUID(value["approval_id"])) != value["approval_id"]:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Use a canonical UUID approval ID") from None
        settings = self.public(uid)
        if not settings["enabled"]:
            raise ValueError("Memory is disabled for this account")
        project, user_id = self.scope(uid, cid, settings["project_id"])
        source_run = ""
        if value["kind"] == "decision":
            completed = [row for row in self.store.runs(uid, cid) if row["status"] == "completed"]
            if not completed:
                raise ValueError("A confirmed task decision requires a completed run in this conversation")
            source_run = completed[-1]["id"]
        fingerprint = hashlib.sha256(json.dumps([cid, value["kind"], value["text"]], ensure_ascii=False).encode()).hexdigest()
        pending = {"status": "pending", "approval_id": value["approval_id"], "source_run_id": source_run,
                   "project_id": project, "request_id": "", "task_id": ""}
        with self.store.lock, self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            previous = self.store.db.execute("SELECT fingerprint,receipt FROM memorax_approvals WHERE uid=? AND project_id=? AND approval_id=?",
                                             (uid, project, value["approval_id"])).fetchone()
            if previous:
                if previous[0] != fingerprint:
                    raise ValueError("Approval ID was already used for different content")
                return json.loads(previous[1])
            # Reserve before any network I/O. A crash/timeout must not cause a duplicate write.
            self.store.db.execute("INSERT INTO memorax_approvals VALUES(?,?,?,?,?,?)",
                                  (uid, project, value["approval_id"], fingerprint, json.dumps(pending), time.time()))
        try:
            receipt = asdict(self.client_factory().add(user_id, value["text"], kind=value["kind"]))
            pending.update(receipt)
        except MemoryUnavailable as exc:
            pending.update(status="unknown" if exc.outcome_unknown else "failed", code=exc.code,
                           request_id=exc.request_id, task_id=exc.task_id, diagnostics=exc.diagnostics)
        with self.store.lock, self.store.db:
            self.store.db.execute("UPDATE memorax_approvals SET receipt=? WHERE uid=? AND project_id=? AND approval_id=?",
                                  (json.dumps(pending), uid, project, value["approval_id"]))
        return pending


def install_memory_routes(app, auth, body, store, *, client_factory=None):
    service = AccountMemory(store, client_factory=client_factory)
    app.state.memorax = service

    @app.get("/api/settings/memory")
    def settings(request: Request):
        return service.public(auth(request)["id"])

    @app.put("/api/settings/memory")
    async def save(request: Request):
        uid = auth(request, mutate=True)["id"]
        return service.save(uid, await body(request))

    @app.post("/api/conversations/{cid}/memory/approve")
    async def approve(cid: str, request: Request):
        uid = auth(request, mutate=True)["id"]
        store.conversation(uid, cid)
        value = await body(request)
        return await asyncio.to_thread(service.approve, uid, cid, value)

    return service

"""PostgreSQL business store adapter + idempotent SQLite-to-PostgreSQL migrator.

Implements the exact public interface of `team.store.Store` backed by PostgreSQL
(`geotool_team` schema) and Content-Addressed Storage (`ContentAddressedStore`)
so multi-worker/concurrent requests avoid SQLite's single-writer lock while
keeping file attachments deduplicated outside the database.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
from threading import RLock
import time
import uuid

from ..context_store import private_dsn
from .cas import ContentAddressedStore
from .protocol import MAX_FILE, MAX_FILES_TOTAL, relative_name
from .store import SESSION_SECONDS, USER_QUOTA, Store, digest, password_hash, password_matches

_SCHEMA_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class TeamStoreError(RuntimeError):
    pass


def _build_pg_schema(schema: str) -> str:
    if not _SCHEMA_NAME_RE.fullmatch(schema):
        raise ValueError(f"Invalid PostgreSQL schema name: {schema!r}")
    return f"""
CREATE SCHEMA IF NOT EXISTS {schema};
CREATE TABLE IF NOT EXISTS {schema}.users(
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin','member')),
    disabled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS {schema}.auth(
    token TEXT PRIMARY KEY,
    uid TEXT REFERENCES {schema}.users(id),
    csrf TEXT,
    expires DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS {schema}.invites(
    token TEXT PRIMARY KEY,
    expires DOUBLE PRECISION,
    used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS {schema}.conversations(
    id TEXT PRIMARY KEY,
    uid TEXT REFERENCES {schema}.users(id),
    title TEXT,
    generation TEXT NOT NULL,
    created DOUBLE PRECISION,
    updated DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS {schema}.files(
    cid TEXT REFERENCES {schema}.conversations(id),
    generation TEXT,
    name TEXT,
    sha256 TEXT NOT NULL,
    byte_size BIGINT NOT NULL,
    PRIMARY KEY(cid,generation,name)
);
CREATE TABLE IF NOT EXISTS {schema}.file_origins(
    cid TEXT,
    generation TEXT,
    name TEXT,
    sha256 TEXT NOT NULL,
    record TEXT NOT NULL,
    PRIMARY KEY(cid,generation,name)
);
CREATE TABLE IF NOT EXISTS {schema}.generation_audit(
    cid TEXT REFERENCES {schema}.conversations(id),
    generation TEXT,
    action TEXT NOT NULL,
    source_generation TEXT,
    created DOUBLE PRECISION NOT NULL,
    PRIMARY KEY(cid,generation)
);
CREATE TABLE IF NOT EXISTS {schema}.runs(
    id TEXT PRIMARY KEY,
    cid TEXT REFERENCES {schema}.conversations(id),
    query TEXT,
    status TEXT,
    answer TEXT DEFAULT '',
    reason TEXT DEFAULT '',
    generation TEXT DEFAULT '',
    created DOUBLE PRECISION,
    turns INTEGER DEFAULT 0,
    finished_at DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS {schema}.events(
    seq BIGSERIAL PRIMARY KEY,
    rid TEXT REFERENCES {schema}.runs(id),
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS {schema}_event_run ON {schema}.events(rid,seq);
CREATE TABLE IF NOT EXISTS {schema}.run_activity(
    rid TEXT PRIMARY KEY REFERENCES {schema}.runs(id),
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS {schema}_conversation_owner ON {schema}.conversations(uid,updated);
CREATE INDEX IF NOT EXISTS {schema}_run_conversation ON {schema}.runs(cid,created);
CREATE TABLE IF NOT EXISTS {schema}.input_requests(
    id TEXT PRIMARY KEY,
    cid TEXT REFERENCES {schema}.conversations(id),
    origin_rid TEXT REFERENCES {schema}.runs(id),
    core_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    reply_rid TEXT UNIQUE REFERENCES {schema}.runs(id),
    created DOUBLE PRECISION NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS {schema}_one_pending_input
    ON {schema}.input_requests(cid) WHERE state IN ('pending','resuming');
"""


class PostgresTeamStore:
    """PostgreSQL + CAS implementation of the OreBOGAO team business store."""

    backend = "postgres"

    def __init__(self, root: str | Path, dsn: str, *, schema: str = "geotool_team", setup_schema: bool = True):
        if not _SCHEMA_NAME_RE.fullmatch(schema):
            raise ValueError(f"Invalid PostgreSQL schema name: {schema!r}")
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("A non-empty PostgreSQL DSN is required")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.root.chmod(0o700)
        self._dsn = dsn
        self.schema = schema
        self.lock = RLock()
        self.cas = ContentAddressedStore(self.root / "cas-blobs")
        self._closed = False
        if setup_schema:
            self.setup()

    @contextmanager
    def connection(self, *, autocommit: bool = False):
        if self._closed:
            raise TeamStoreError("PostgresTeamStore is closed")
        import psycopg
        from psycopg.rows import dict_row
        try:
            with psycopg.connect(
                self._dsn,
                autocommit=autocommit,
                row_factory=dict_row,
                connect_timeout=8,
                prepare_threshold=0,
                options=f"-c search_path={self.schema},public -c statement_timeout=15000",
            ) as conn:
                yield conn
        except psycopg.Error as exc:
            # Never expose raw DSN or secret payload data in error messages.
            raise TeamStoreError(f"PostgreSQL team store operation failed ({type(exc).__name__})") from None

    def setup(self) -> None:
        with self.connection(autocommit=True) as conn:
            conn.execute(_build_pg_schema(self.schema), prepare=False)

    def close(self) -> None:
        self._closed = True

    def user(self, username: str):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE username=%s", (username,)).fetchone()
            return dict(row) if row else None

    def create_user(self, username: str, password: str, *, role: str = "member", invite: str | None = None, initial_admin: bool = False):
        Store.validate_user_identity(username, role, initial_admin)
        encoded = password_hash(password)
        uid = uuid.uuid4().hex
        with self.connection() as conn:
            if initial_admin:
                if conn.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
                    raise ValueError("An administrator already exists")
            else:
                tok = digest(invite or "")
                row = conn.execute("SELECT * FROM invites WHERE token=%s FOR UPDATE", (tok,)).fetchone()
                if not row or row["used"] or row["expires"] <= time.time():
                    raise ValueError("Invitation is invalid, expired, or already used")
            conn.execute(
                "INSERT INTO users(id,username,password,role) VALUES (%s,%s,%s,%s)",
                (uid, username, encoded, role),
            )
            if not initial_admin:
                conn.execute("UPDATE invites SET used=1 WHERE token=%s", (digest(invite or ""),))
            conn.commit()
        return uid

    def invite(self) -> str:
        token = secrets.token_urlsafe(32)
        with self.connection() as conn:
            conn.execute("INSERT INTO invites(token,expires) VALUES (%s,%s)", (digest(token), time.time() + 86400))
            conn.commit()
        return token

    def login(self, username: str, password: str):
        identifier = username.strip() if isinstance(username, str) else ""
        user = self.user(identifier)
        if not password_matches(password, user["password"] if user else None) or user["disabled"]:
            raise PermissionError("Invalid username or password")
        return self.create_session(user["id"], password_snapshot=user["password"])

    def create_session(self, uid: str, *, password_snapshot: str | None = None):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.connection() as conn:
            current = conn.execute("SELECT password,disabled FROM users WHERE id=%s FOR UPDATE", (uid,)).fetchone()
            if not current or current["disabled"]:
                raise PermissionError("Please sign in")
            if password_snapshot is not None and not hmac.compare_digest(current["password"], password_snapshot):
                raise PermissionError("Invalid username or password")
            conn.execute("DELETE FROM auth WHERE expires<%s", (time.time(),))
            conn.execute(
                "INSERT INTO auth(token,uid,csrf,expires) VALUES (%s,%s,%s,%s)",
                (digest(token), uid, csrf, time.time() + SESSION_SECONDS),
            )
            conn.commit()
        return token, csrf

    def authenticate(self, token: str):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT users.id,username,role,csrf FROM auth JOIN users ON users.id=auth.uid "
                "WHERE token=%s AND expires>%s AND disabled=0",
                (digest(token), time.time()),
            ).fetchone()
        if not row:
            raise PermissionError("Please sign in")
        return dict(row)

    def logout(self, token: str):
        with self.connection() as conn:
            conn.execute("DELETE FROM auth WHERE token=%s", (digest(token),))
            conn.commit()

    def change_password(self, uid: str, old: str, new: str):
        with self.connection() as conn:
            row = conn.execute("SELECT password FROM users WHERE id=%s", (uid,)).fetchone()
        if not row or not password_matches(old, row["password"]):
            raise PermissionError("Current password is incorrect")
        encoded = password_hash(new)
        with self.connection() as conn:
            cur = conn.execute(
                "UPDATE users SET password=%s WHERE id=%s AND password=%s AND disabled=0",
                (encoded, uid, row["password"]),
            )
            if cur.rowcount != 1:
                raise PermissionError("Password changed; authenticate again")
            conn.execute("DELETE FROM auth WHERE uid=%s", (uid,))
            conn.commit()

    def disable(self, username: str):
        with self.connection() as conn:
            conn.execute("UPDATE users SET disabled=1 WHERE username=%s AND role!='admin'", (username,))
            conn.execute("DELETE FROM auth WHERE uid IN (SELECT id FROM users WHERE disabled=1)")
            conn.commit()

    def conversation(self, uid: str, cid: str):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM conversations WHERE id=%s AND uid=%s", (cid, uid)).fetchone()
        if not row:
            raise KeyError("Conversation not found")
        return dict(row)

    def conversations(self, uid: str):
        with self.connection() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT id,title,created,updated FROM conversations WHERE uid=%s ORDER BY updated DESC",
                    (uid,),
                ).fetchall()
            ]

    def create_conversation(self, uid: str):
        cid = uuid.uuid4().hex
        now = time.time()
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO conversations(id,uid,title,generation,created,updated) VALUES (%s,%s,%s,%s,%s,%s)",
                (cid, uid, "New conversation", uuid.uuid4().hex, now, now),
            )
            conn.commit()
        return self.conversation(uid, cid)

    def run(self, uid: str, rid: str):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT runs.*,run_activity.data AS activity FROM runs "
                "JOIN conversations ON runs.cid=conversations.id "
                "LEFT JOIN run_activity ON run_activity.rid=runs.id "
                "WHERE runs.id=%s AND conversations.uid=%s",
                (rid, uid),
            ).fetchone()
        if not row:
            raise KeyError("Run not found")
        return Store._run_view(row, time.time())

    def runs(self, uid: str, cid: str):
        self.conversation(uid, cid)
        with self.connection() as conn:
            now = time.time()
            rows = conn.execute(
                "SELECT runs.*,run_activity.data AS activity FROM runs "
                "LEFT JOIN run_activity ON run_activity.rid=runs.id "
                "WHERE runs.cid=%s ORDER BY runs.created",
                (cid,),
            ).fetchall()
        return [Store._run_view(r, now) for r in rows]

    def active_runs(self, uid: str):
        with self.connection() as conn:
            now = time.time()
            rows = conn.execute(
                "SELECT runs.*,conversations.title,run_activity.data AS activity "
                "FROM runs JOIN conversations ON conversations.id=runs.cid "
                "LEFT JOIN run_activity ON run_activity.rid=runs.id "
                "WHERE conversations.uid=%s AND runs.status IN ('running','stopping') "
                "ORDER BY runs.created",
                (uid,),
            ).fetchall()
        return [{**Store._run_view(row, now), "title": row["title"]} for row in rows]

    def begin(self, uid: str, cid: str, query: str, *, expected_input=None, _rid=None):
        self.conversation(uid, cid)
        rid = _rid or uuid.uuid4().hex
        with self.connection() as conn:
            # Row-level lock on user serializes concurrent task starts for the same account.
            conn.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (uid,))
            if expected_input is not None:
                self.input_request(uid, expected_input[0], cid=cid, rid=expected_input[1], pending=True)
            if conn.execute(
                "SELECT 1 FROM runs JOIN conversations ON runs.cid=conversations.id "
                "WHERE conversations.uid=%s AND runs.status IN ('running','stopping')",
                (uid,),
            ).fetchone():
                raise ValueError("You already have a running task; stop it or wait for it to finish")
            now = time.time()
            conn.execute(
                "INSERT INTO runs(id,cid,query,status,created) VALUES (%s,%s,%s,'running',%s)",
                (rid, cid, query, now),
            )
            conn.execute(
                "UPDATE input_requests SET state='resuming',reply_rid=%s WHERE cid=%s AND state='pending'",
                (rid, cid),
            )
            conn.execute(
                "UPDATE conversations SET title=CASE WHEN title='New conversation' THEN %s ELSE title END, updated=%s WHERE id=%s",
                (query[:70], now, cid),
            )
            conn.commit()
        return rid

    def _finish_in_conn(self, conn, rid: str, *, status: str, answer="", reason="", generation="", turns=0):
        allowed = {"completed", "incomplete", "needs_input", "failed", "stopped", "budget_exhausted", "interrupted"}
        if status not in allowed:
            raise ValueError("Invalid task terminal status")
        row = conn.execute("SELECT * FROM runs WHERE id=%s FOR UPDATE", (rid,)).fetchone()
        if row is None:
            raise KeyError("Run not found")
        current = row["status"]
        cancel_paused = current == "needs_input" and status == "stopped" and conn.execute(
            "SELECT 1 FROM input_requests WHERE origin_rid=%s AND state='cancelled'", (rid,)
        ).fetchone()
        if current not in ("running", "stopping") and not cancel_paused:
            return current
        now = time.time()
        cur = conn.execute(
            "UPDATE runs SET status=%s,answer=%s,reason=%s,generation=%s,turns=%s,finished_at=COALESCE(finished_at,%s) "
            "WHERE id=%s AND status=%s",
            (status, answer, reason or "", generation, turns, now, rid, current),
        )
        if cur.rowcount != 1:
            return current
        row = conn.execute("SELECT * FROM runs WHERE id=%s", (rid,)).fetchone()
        elapsed = Store._run_view(row, now)["elapsed_seconds"]
        if status != "needs_input":
            state = "answered" if status == "completed" else "interrupted"
            conn.execute("UPDATE input_requests SET state=%s WHERE reply_rid=%s AND state='resuming'", (state, rid))
            conn.execute("UPDATE input_requests SET state='interrupted' WHERE origin_rid=%s AND state='pending'", (rid,))
        conn.execute(
            "INSERT INTO events(rid,data) VALUES (%s,%s)",
            (rid, json.dumps({
                "kind": "finished", "status": status, "answer": answer, "reason": reason or "",
                "generation": generation, "turns": turns, "elapsed_seconds": elapsed,
                "created": row["created"], "finished_at": row["finished_at"],
            }, ensure_ascii=False)),
        )
        return status

    def finish(self, rid: str, *, status: str, answer="", reason="", generation="", turns=0):
        with self.connection() as conn:
            result = self._finish_in_conn(conn, rid, status=status, answer=answer, reason=reason, generation=generation, turns=turns)
            conn.commit()
            return result

    def fail_start(self, uid: str, rid: str, *, reason: str):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT r.status,c.uid FROM runs r JOIN conversations c ON r.cid=c.id WHERE r.id=%s FOR UPDATE",
                (rid,),
            ).fetchone()
            if row is not None and row["uid"] != uid:
                raise PermissionError("Run ownership mismatch")
            if row is None or row["status"] not in ("running", "stopping"):
                return row["status"] if row is not None else None
            conn.execute(
                "UPDATE input_requests SET state='pending',reply_rid=NULL WHERE reply_rid=%s AND state='resuming'",
                (rid,),
            )
            self._finish_in_conn(conn, rid, status="failed", reason=reason)
            conn.commit()
            return "failed"

    def publish(self, uid: str, cid: str, rid: str, files: dict, *, base_generation: str, origins=None, **outcome):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT r.*,c.uid,c.generation AS conv_generation FROM runs r "
                "JOIN conversations c ON r.cid=c.id WHERE r.id=%s FOR UPDATE",
                (rid,),
            ).fetchone()
            if not row or row["uid"] != uid:
                raise KeyError("Run not found")
            if row["cid"] != cid:
                raise PermissionError("Run conversation mismatch")
            if row["status"] not in ("running", "stopping"):
                return row["status"]
            if row["conv_generation"] != base_generation:
                raise ValueError("Conversation files changed before result publication")
            generation = self._snapshot_in_conn(conn, uid, cid, files, origins=origins, action="run")
            status = self._finish_in_conn(conn, rid, generation=generation, **outcome)
            conn.commit()
            return status

    def event(self, rid: str, data: dict):
        with self.connection() as conn:
            conn.execute("INSERT INTO events(rid,data) VALUES (%s,%s)", (rid, json.dumps(data, ensure_ascii=False)))
            if data.get("kind") in ("stage_timing", "model_config", "tool_start", "skill_selected", "skill_loaded", "run_mode", "plan_confirmed"):
                row = conn.execute("SELECT data FROM run_activity WHERE rid=%s FOR UPDATE", (rid,)).fetchone()
                summary = json.loads(row["data"]) if row else {}
                if data["kind"] == "stage_timing":
                    summary["timing"] = data
                elif data["kind"] == "plan_confirmed":
                    summary["plan"] = data.get("plan")
                elif data["kind"] == "model_config":
                    summary["profile"] = data.get("profile", {})
                elif data["kind"] == "run_mode":
                    summary["mode"] = data["mode"]
                    summary.setdefault("loaded_skills", {})
                elif data["kind"] == "skill_selected":
                    summary["skill"] = data["skill"]
                elif data["kind"] == "skill_loaded":
                    summary.setdefault("loaded_skills", {})[data["id"]] = data
                else:
                    summary["tool_count"] = summary.get("tool_count", 0) + 1
                conn.execute(
                    "INSERT INTO run_activity(rid,data) VALUES (%s,%s) "
                    "ON CONFLICT(rid) DO UPDATE SET data=EXCLUDED.data",
                    (rid, json.dumps(summary, ensure_ascii=False)),
                )
            conn.commit()

    def history(self, uid: str, rid: str, *, after: int = 0, through: int | None = None, limit: int = 60):
        self.run(uid, rid)
        if after < 0 or limit < 1 or limit > 100 or (through is not None and through < 0):
            raise ValueError("Invalid history page")
        with self.connection() as conn:
            maximum = conn.execute("SELECT COALESCE(MAX(seq),0) AS m FROM events WHERE rid=%s", (rid,)).fetchone()["m"]
            through = min(maximum, through) if through is not None else maximum
            rows = conn.execute(
                "SELECT seq,data FROM events WHERE rid=%s AND seq>%s AND seq<=%s ORDER BY seq LIMIT %s",
                (rid, after, through, limit + 1),
            ).fetchall()
        page, size = [], 0
        for row in rows[:limit]:
            if page and size + len(row["data"]) > 131072:
                break
            page.append({"id": row["seq"], "data": json.loads(row["data"])})
            size += len(row["data"])
        cursor = page[-1]["id"] if page else after
        return {"run_id": rid, "events": page, "next": cursor, "through": through,
                "has_more": any(row["seq"] > cursor for row in rows)}

    def events(self, uid: str, rid: str, after: int):
        self.run(uid, rid)
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT seq,data FROM events WHERE rid=%s AND seq>%s ORDER BY seq LIMIT 100",
                (rid, after),
            ).fetchall()
        return [{"id": r["seq"], "data": json.loads(r["data"])} for r in rows]

    def receipt_events(self, uid: str, rid: str):
        self.run(uid, rid)
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT data FROM events WHERE rid=%s AND (data::jsonb ->> 'kind') IN ('tool_result','knowledge_sources') ORDER BY seq",
                (rid,),
            ).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def files(self, uid: str, cid: str, generation: str | None = None):
        conv = self.conversation(uid, cid)
        generation = generation or conv["generation"]
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT name,sha256 FROM files WHERE cid=%s AND generation=%s",
                (cid, generation),
            ).fetchall()
        return {r["name"]: self.cas.get(r["sha256"]) for r in rows}

    def file(self, uid: str, cid: str, name: str, generation: str | None = None):
        conv = self.conversation(uid, cid)
        generation = generation or conv["generation"]
        with self.connection() as conn:
            row = conn.execute(
                "SELECT sha256 FROM files WHERE cid=%s AND generation=%s AND name=%s",
                (cid, generation, name),
            ).fetchone()
        return self.cas.get(row["sha256"]) if row is not None else None

    def file_manifest(self, uid: str, cid: str, generation: str | None = None):
        conv = self.conversation(uid, cid)
        generation = generation or conv["generation"]
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT name,byte_size AS bytes,sha256 FROM files WHERE cid=%s AND generation=%s ORDER BY name",
                (cid, generation),
            ).fetchall()
        return [dict(r) for r in rows]

    def file_origins(self, uid: str, cid: str, generation: str | None = None):
        conv = self.conversation(uid, cid)
        generation = generation or conv["generation"]
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT f.name,f.sha256,o.record FROM files f LEFT JOIN file_origins o "
                "ON f.cid=o.cid AND f.generation=o.generation AND f.name=o.name AND f.sha256=o.sha256 "
                "WHERE f.cid=%s AND f.generation=%s",
                (cid, generation),
            ).fetchall()
        return {
            row["name"]: json.loads(row["record"]) if row["record"] else {
                "origin": "unknown", "sha256": row["sha256"], "scope": "legacy file; acquisition not recorded"
            }
            for row in rows
        }

    def generations(self, uid: str, cid: str):
        conv = self.conversation(uid, cid)
        with self.connection() as conn:
            rows = conn.execute(
                """
                WITH snapshots AS (
                  SELECT generation,name,byte_size AS bytes FROM files WHERE cid=%s
                  UNION ALL SELECT %s, '', 0
                  UNION ALL SELECT generation,'',0 FROM generation_audit WHERE cid=%s
                  UNION ALL SELECT generation,'',0 FROM runs WHERE cid=%s AND generation IS NOT NULL AND generation<>''
                ), totals AS (
                  SELECT generation,count(NULLIF(name,'')) AS file_count,COALESCE(sum(bytes),0)::bigint AS bytes
                  FROM snapshots GROUP BY generation
                )
                SELECT t.generation,t.file_count,t.bytes,a.action,a.source_generation,
                  COALESCE(a.created,min(r.created)) AS created,min(r.id) AS run_id
                FROM totals t
                LEFT JOIN generation_audit a ON a.cid=%s AND a.generation=t.generation
                LEFT JOIN runs r ON r.cid=%s AND r.generation=t.generation
                GROUP BY t.generation,t.file_count,t.bytes,a.action,a.source_generation,a.created
                ORDER BY COALESCE(COALESCE(a.created,min(r.created)),0) DESC,t.generation
                """,
                (cid, conv["generation"], cid, cid, cid, cid),
            ).fetchall()
        return [{**dict(row), "current": row["generation"] == conv["generation"],
                 "created_known": row["created"] is not None} for row in rows]

    def generation_exists(self, uid: str, cid: str, generation: str) -> bool:
        conv = self.conversation(uid, cid)
        if not isinstance(generation, str) or not re.fullmatch(r"[a-f0-9]{32}", generation):
            return False
        if generation == conv["generation"]:
            return True
        with self.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM generation_audit WHERE cid=%s AND generation=%s "
                "UNION ALL SELECT 1 FROM files WHERE cid=%s AND generation=%s "
                "UNION ALL SELECT 1 FROM runs WHERE cid=%s AND generation=%s LIMIT 1",
                (cid, generation, cid, generation, cid, generation),
            ).fetchone()
        return row is not None

    def generation(self, uid: str, cid: str, generation: str):
        conv = self.conversation(uid, cid)
        if not self.generation_exists(uid, cid, generation):
            raise KeyError("Generation not found")
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT a.action,a.source_generation,
                  COALESCE(a.created,(SELECT min(created) FROM runs WHERE cid=%s AND generation=%s)) AS created,
                  (SELECT id FROM runs WHERE cid=%s AND generation=%s ORDER BY created LIMIT 1) AS run_id
                FROM (SELECT 1) AS dummy LEFT JOIN generation_audit a
                  ON a.cid=%s AND a.generation=%s
                """,
                (cid, generation, cid, generation, cid, generation),
            ).fetchone()
        return {**dict(row), "generation": generation, "file_count": None, "bytes": None,
                "current": generation == conv["generation"], "created_known": row["created"] is not None}

    def _snapshot_in_conn(self, conn, uid: str, cid: str, files: dict, *, origins=None, action="snapshot", source_generation=None):
        conv = conn.execute("SELECT * FROM conversations WHERE id=%s AND uid=%s FOR UPDATE", (cid, uid)).fetchone()
        if not conv:
            raise KeyError("Conversation not found")
        total = 0
        if len(files) > 1024:
            raise ValueError("Snapshot exceeds 1024 files")
        for name, data in files.items():
            relative_name(name)
            if not isinstance(data, bytes) or len(data) > MAX_FILE:
                raise ValueError("Each file must be at most 8 MiB")
            total += len(data)
        if total > MAX_FILES_TOTAL:
            raise ValueError("Conversation files exceed the 64 MiB transfer quota")

        prev_rows = conn.execute(
            "SELECT f.name,f.sha256,o.record FROM files f LEFT JOIN file_origins o "
            "ON f.cid=o.cid AND f.generation=o.generation AND f.name=o.name AND f.sha256=o.sha256 "
            "WHERE f.cid=%s AND f.generation=%s",
            (cid, conv["generation"]),
        ).fetchall()
        previous_origins = {
            r["name"]: json.loads(r["record"]) if r["record"] else {"origin": "unknown", "sha256": r["sha256"]}
            for r in prev_rows
        }
        used = conn.execute(
            "SELECT COALESCE(sum(f.byte_size),0) AS used FROM files f "
            "JOIN conversations c ON f.cid=c.id WHERE c.uid=%s",
            (uid,),
        ).fetchone()["used"]
        if used + total > USER_QUOTA:
            raise ValueError("User storage quota exceeded; snapshot was not committed")

        generation = uuid.uuid4().hex
        now = time.time()
        for name, data in files.items():
            sha, nbytes = self.cas.put(data)
            supplied = (origins or {}).get(name)
            prior = previous_origins.get(name, {})
            origin = supplied if supplied is not None else prior if prior.get("sha256") == sha else None
            if not isinstance(origin, dict) or origin.get("sha256") != sha:
                origin = {"origin": "unknown", "sha256": sha, "scope": "no matching runtime acquisition record"}
            conn.execute(
                "INSERT INTO files(cid,generation,name,sha256,byte_size) VALUES (%s,%s,%s,%s,%s)",
                (cid, generation, name, sha, nbytes),
            )
            conn.execute(
                "INSERT INTO file_origins(cid,generation,name,sha256,record) VALUES (%s,%s,%s,%s,%s)",
                (cid, generation, name, sha, json.dumps(origin, ensure_ascii=False)),
            )
        conn.execute(
            "INSERT INTO generation_audit(cid,generation,action,source_generation,created) VALUES (%s,%s,%s,%s,%s)",
            (cid, generation, action, source_generation, now),
        )
        conn.execute("UPDATE conversations SET generation=%s,updated=%s WHERE id=%s", (generation, now, cid))
        return generation

    def snapshot(self, uid: str, cid: str, files: dict, *, origins=None, action="snapshot", source_generation=None):
        with self.connection() as conn:
            gen = self._snapshot_in_conn(conn, uid, cid, files, origins=origins, action=action, source_generation=source_generation)
            conn.commit()
            return gen

    def restore(self, uid: str, cid: str, generation: str):
        if not self.generation_exists(uid, cid, generation):
            raise KeyError("Generation not found")
        with self.connection() as conn:
            if conn.execute(
                "SELECT 1 FROM runs JOIN conversations ON runs.cid=conversations.id "
                "WHERE conversations.id=%s AND conversations.uid=%s AND runs.status IN ('running','stopping')",
                (cid, uid),
            ).fetchone():
                raise ValueError("Wait for your active task before restoring files")
            files = self.files(uid, cid, generation)
            origins = self.file_origins(uid, cid, generation)
            for rec in origins.values():
                rec["restored_from"] = generation
            gen = self._snapshot_in_conn(conn, uid, cid, files, origins=origins, action="restore", source_generation=generation)
            conn.commit()
            return gen

    def input_for_reply(self, rid: str):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT input_requests.*,runs.query FROM input_requests "
                "JOIN runs ON reply_rid=runs.id AND input_requests.cid=runs.cid "
                "WHERE reply_rid=%s AND state='resuming'",
                (rid,),
            ).fetchone()
        return {**dict(row), "payload": json.loads(row["payload"])} if row else None

    def pause_input(self, rid: str, core_id: str, job_id: str, payload: dict):
        if not all(re.fullmatch(r"[a-f0-9]{32}", value) for value in (rid, core_id, job_id, payload["id"])):
            raise ValueError("Invalid human-input identity")
        with self.connection() as conn:
            run = conn.execute("SELECT cid,status FROM runs WHERE id=%s FOR UPDATE", (rid,)).fetchone()
            if not run or run["status"] != "running":
                raise ValueError("Only a running task can publish a new input request")
            conn.execute("UPDATE input_requests SET state='answered' WHERE reply_rid=%s AND state='resuming'", (rid,))
            conn.execute(
                "INSERT INTO input_requests(id,cid,origin_rid,core_id,job_id,payload,created) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (payload["id"], run["cid"], rid, core_id, job_id, json.dumps(payload, ensure_ascii=False), time.time()),
            )
            conn.commit()

    def input_request(self, uid: str, request_id: str, *, cid=None, rid=None, pending=False):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT input_requests.*,runs.status AS run_status,conversations.title "
                "FROM input_requests JOIN conversations ON input_requests.cid=conversations.id "
                "JOIN runs ON input_requests.origin_rid=runs.id WHERE input_requests.id=%s AND conversations.uid=%s",
                (request_id, uid),
            ).fetchone()
        if not row or (cid is not None and row["cid"] != cid) or (rid is not None and row["origin_rid"] != rid):
            raise KeyError("Input request not found")
        if pending and (row["state"] != "pending" or row["run_status"] != "needs_input"):
            raise ValueError("This input request has already been answered or closed")
        return dict(row)

    def pending_inputs(self, uid: str, cid=None, *, include_closed=False):
        if cid is not None:
            self.conversation(uid, cid)
        clauses, args = ["conversations.uid=%s"], [uid]
        if cid is not None:
            clauses.append("input_requests.cid=%s")
            args.append(cid)
        if include_closed:
            clauses.append("(input_requests.state!='pending' OR runs.status='needs_input')")
        else:
            clauses.append("input_requests.state='pending' AND runs.status='needs_input'")
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT input_requests.id,input_requests.cid,input_requests.origin_rid,input_requests.state,"
                "input_requests.reply_rid,input_requests.payload,conversations.title "
                "FROM input_requests JOIN conversations ON input_requests.cid=conversations.id "
                "JOIN runs ON origin_rid=runs.id WHERE " + " AND ".join(clauses) +
                " ORDER BY input_requests.created",
                args,
            ).fetchall()
        return [{**json.loads(row["payload"]), "id": row["id"], "cid": row["cid"],
                 "rid": row["origin_rid"], "state": row["state"], "reply_rid": row["reply_rid"],
                 "title": row["title"]} for row in rows]

    def cancel_input(self, uid: str, request_id: str, *, _retry=False):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT input_requests.origin_rid,input_requests.state FROM input_requests "
                "JOIN conversations ON input_requests.cid=conversations.id "
                "WHERE input_requests.id=%s AND conversations.uid=%s FOR UPDATE",
                (request_id, uid),
            ).fetchone()
            if not row:
                raise KeyError("Input request not found")
            if row["state"] != "pending" and not (_retry and row["state"] == "cancelled"):
                raise ValueError("This input request has already been answered or closed")
            conn.execute("UPDATE input_requests SET state='cancelled' WHERE id=%s AND state='pending'", (request_id,))
            status = self._finish_in_conn(
                conn,
                row["origin_rid"],
                status="stopped",
                reason="The user cancelled the pending input request; saved files were retained",
            )
            conn.commit()
            return status

    def recover(self, *, after: str = "", limit: int = 64):
        if not isinstance(after, str) or not 1 <= limit <= 64:
            raise ValueError("Invalid recovery page")
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT id FROM runs WHERE status IN ('running','stopping') AND id>%s ORDER BY id LIMIT %s",
                (after, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def gc_cas_blobs(self) -> dict:
        with self.connection() as conn:
            live = {r["sha256"] for r in conn.execute("SELECT DISTINCT sha256 FROM files WHERE sha256 IS NOT NULL").fetchall()}
        return self.cas.gc(live)


def migrate_sqlite_to_postgres(sqlite_root: str | Path, pg_store: PostgresTeamStore, *, verify: bool = True) -> dict:
    """Idempotently migrate all business tables + file blobs from SQLite `Store` to `PostgresTeamStore`."""
    src = Store(sqlite_root)
    counts: dict[str, int] = {}
    unique_blobs: set[str] = set()
    try:
        with src.lock:
            users = [dict(r) for r in src.db.execute("SELECT id,username,password,role,disabled FROM users").fetchall()]
            auths = [dict(r) for r in src.db.execute("SELECT token,uid,csrf,expires FROM auth").fetchall()]
            invites = [dict(r) for r in src.db.execute("SELECT token,expires,used FROM invites").fetchall()]
            convs = [dict(r) for r in src.db.execute("SELECT id,uid,title,generation,created,updated FROM conversations").fetchall()]
            file_rows = src.db.execute(
                "SELECT f.cid,f.generation,f.name,f.content,f.sha256,c.sha256 AS cas_sha "
                "FROM files f LEFT JOIN file_cas_index c "
                "ON f.cid=c.cid AND f.generation=c.generation AND f.name=c.name"
            ).fetchall()
            origins = [dict(r) for r in src.db.execute("SELECT cid,generation,name,sha256,record FROM file_origins").fetchall()]
            gen_audit = [dict(r) for r in src.db.execute("SELECT cid,generation,action,source_generation,created FROM generation_audit").fetchall()]
            runs = [dict(r) for r in src.db.execute("SELECT id,cid,query,status,answer,reason,generation,created,turns,finished_at FROM runs").fetchall()]
            events = [dict(r) for r in src.db.execute("SELECT seq,rid,data FROM events ORDER BY seq").fetchall()]
            activities = [dict(r) for r in src.db.execute("SELECT rid,data FROM run_activity").fetchall()]
            inputs = [dict(r) for r in src.db.execute("SELECT id,cid,origin_rid,core_id,job_id,payload,state,reply_rid,created FROM input_requests").fetchall()]

        prepared_files = []
        for row in file_rows:
            raw = src.cas.get(row["cas_sha"]) if row["cas_sha"] is not None else bytes(row["content"])
            sha, nbytes = pg_store.cas.put(raw)
            expected = row["cas_sha"] or row["sha256"]
            if expected and expected != sha:
                raise TeamStoreError(f"File SHA-256 mismatch during migration for {row['name']}")
            unique_blobs.add(sha)
            prepared_files.append((row["cid"], row["generation"], row["name"], sha, nbytes))

        with pg_store.connection() as conn:
            for r in users:
                conn.execute(
                    "INSERT INTO users(id,username,password,role,disabled) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                    (r["id"], r["username"], r["password"], r["role"], r["disabled"]),
                )
            for r in auths:
                conn.execute(
                    "INSERT INTO auth(token,uid,csrf,expires) VALUES (%s,%s,%s,%s) ON CONFLICT(token) DO NOTHING",
                    (r["token"], r["uid"], r["csrf"], r["expires"]),
                )
            for r in invites:
                conn.execute(
                    "INSERT INTO invites(token,expires,used) VALUES (%s,%s,%s) ON CONFLICT(token) DO NOTHING",
                    (r["token"], r["expires"], r["used"]),
                )
            for r in convs:
                conn.execute(
                    "INSERT INTO conversations(id,uid,title,generation,created,updated) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                    (r["id"], r["uid"], r["title"], r["generation"], r["created"], r["updated"]),
                )
            for cid, gen, name, sha, nbytes in prepared_files:
                conn.execute(
                    "INSERT INTO files(cid,generation,name,sha256,byte_size) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(cid,generation,name) DO NOTHING",
                    (cid, gen, name, sha, nbytes),
                )
            for r in origins:
                conn.execute(
                    "INSERT INTO file_origins(cid,generation,name,sha256,record) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(cid,generation,name) DO NOTHING",
                    (r["cid"], r["generation"], r["name"], r["sha256"], r["record"]),
                )
            for r in gen_audit:
                conn.execute(
                    "INSERT INTO generation_audit(cid,generation,action,source_generation,created) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(cid,generation) DO NOTHING",
                    (r["cid"], r["generation"], r["action"], r["source_generation"], r["created"]),
                )
            for r in runs:
                conn.execute(
                    "INSERT INTO runs(id,cid,query,status,answer,reason,generation,created,turns,finished_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                    (r["id"], r["cid"], r["query"], r["status"], r["answer"], r["reason"],
                     r["generation"], r["created"], r["turns"], r["finished_at"]),
                )
            for r in events:
                conn.execute(
                    "INSERT INTO events(seq,rid,data) VALUES (%s,%s,%s) ON CONFLICT(seq) DO NOTHING",
                    (r["seq"], r["rid"], r["data"]),
                )
            if events:
                conn.execute(
                    "SELECT setval(pg_get_serial_sequence(%s, 'seq'), COALESCE((SELECT MAX(seq) FROM events), 1), true)",
                    (f"{pg_store.schema}.events",),
                )
            for r in activities:
                conn.execute(
                    "INSERT INTO run_activity(rid,data) VALUES (%s,%s) ON CONFLICT(rid) DO NOTHING",
                    (r["rid"], r["data"]),
                )
            for r in inputs:
                conn.execute(
                    "INSERT INTO input_requests(id,cid,origin_rid,core_id,job_id,payload,state,reply_rid,created) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                    (r["id"], r["cid"], r["origin_rid"], r["core_id"], r["job_id"],
                     r["payload"], r["state"], r["reply_rid"], r["created"]),
                )
            conn.commit()

            counts = {
                "users": len(users),
                "conversations": len(convs),
                "files": len(prepared_files),
                "unique_cas_blobs": len(unique_blobs),
                "runs": len(runs),
                "events": len(events),
                "input_requests": len(inputs),
            }
            if verify:
                for table, expected in (("users", len(users)), ("conversations", len(convs)),
                                        ("files", len(prepared_files)), ("runs", len(runs)),
                                        ("events", len(events))):
                    actual = conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
                    if actual < expected:
                        raise TeamStoreError(f"Post-migration verification failed on {table}: {actual} < {expected}")
        return {"ok": True, "counts": counts}
    finally:
        src.close()


def open_team_store(root: str | Path, *, backend: str | None = None, dsn_file: str | Path | None = None, schema: str = "geotool_team"):
    """Select SQLite (default) or PostgreSQL team business store via explicit configuration."""
    chosen = (backend if backend is not None else os.environ.get("GEOTOOL_TEAM_DB_BACKEND", "sqlite")).strip().lower()
    if chosen == "sqlite":
        return Store(root)
    if chosen == "postgres":
        path = dsn_file or os.environ.get("GEOTOOL_TEAM_DSN_FILE", "").strip()
        if not path:
            raise ValueError("GEOTOOL_TEAM_DB_BACKEND=postgres requires GEOTOOL_TEAM_DSN_FILE")
        return PostgresTeamStore(root, private_dsn(path), schema=schema)
    raise ValueError("GEOTOOL_TEAM_DB_BACKEND must be 'sqlite' or 'postgres'; automatic fallback is forbidden")

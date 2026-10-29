"""Account ownership and immutable file snapshots; no client-supplied host paths."""
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

from .protocol import MAX_FILE, MAX_FILES_TOTAL, relative_name

SESSION_SECONDS = 12 * 60 * 60
USER_QUOTA = 512 * 1024 * 1024


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def password_hash(password, salt=None):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError("Password must contain 12 to 256 characters")
    salt = salt or secrets.token_hex(16)
    key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**17, r=8, p=1, maxmem=256 * 1024 * 1024)
    return salt + ":" + key.hex()


def password_matches(password, encoded):
    if not isinstance(password, str) or len(password) > 256:
        return False
    # Perform the same expensive operation even for unknown usernames.
    salt = encoded.split(":", 1)[0] if encoded else "00" * 16
    candidate = password_hash(password if len(password) >= 12 else password.ljust(12), salt)
    return bool(encoded) and hmac.compare_digest(candidate, encoded) and len(password) >= 12


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.root.chmod(0o700)
        self.lock = RLock()
        self.db = sqlite3.connect(self.root / "team.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
          password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','member')), disabled INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS auth(token TEXT PRIMARY KEY, uid TEXT REFERENCES users(id), csrf TEXT, expires REAL);
        CREATE TABLE IF NOT EXISTS invites(token TEXT PRIMARY KEY, expires REAL, used INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, uid TEXT REFERENCES users(id), title TEXT,
          generation TEXT NOT NULL, created REAL, updated REAL);
        CREATE TABLE IF NOT EXISTS files(cid TEXT REFERENCES conversations(id), generation TEXT, name TEXT,
          content BLOB NOT NULL, sha256 TEXT, PRIMARY KEY(cid,generation,name));
        CREATE TABLE IF NOT EXISTS file_origins(cid TEXT, generation TEXT, name TEXT,
          sha256 TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(cid,generation,name));
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, cid TEXT REFERENCES conversations(id), query TEXT,
          status TEXT, answer TEXT DEFAULT '', reason TEXT DEFAULT '', generation TEXT DEFAULT '', created REAL, turns INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, rid TEXT REFERENCES runs(id), data TEXT);
        CREATE INDEX IF NOT EXISTS event_run ON events(rid,seq);
        CREATE TABLE IF NOT EXISTS run_activity(rid TEXT PRIMARY KEY REFERENCES runs(id), data TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS conversation_owner ON conversations(uid,updated);
        CREATE INDEX IF NOT EXISTS run_conversation ON runs(cid,created);
        CREATE TABLE IF NOT EXISTS input_requests(id TEXT PRIMARY KEY, cid TEXT REFERENCES conversations(id),
          origin_rid TEXT REFERENCES runs(id), core_id TEXT NOT NULL, job_id TEXT NOT NULL, payload TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'pending', reply_rid TEXT UNIQUE REFERENCES runs(id), created REAL NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS one_pending_input ON input_requests(cid) WHERE state IN ('pending','resuming');
        """)
        # Additive timing metadata; old runs remain unknown rather than getting
        # a fabricated completion time. BEGIN IMMEDIATE serializes startup.
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if "finished_at" not in {row[1] for row in self.db.execute("PRAGMA table_info(runs)")}:
                self.db.execute("ALTER TABLE runs ADD COLUMN finished_at REAL")
        if os.name != "nt":
            (self.root / "team.sqlite3").chmod(0o600)

    def user(self, username):
        with self.lock:
            row = self.db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            return dict(row) if row else None

    def create_user(self, username, password, *, role="member", invite=None, initial_admin=False):
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{3,40}", username):
            raise ValueError("Username must be 3-40 letters, numbers, dots, underscores, or hyphens")
        if role not in ("member", "admin") or (role == "admin" and not initial_admin):
            raise ValueError("Administrator creation requires the local administration command")
        encoded = password_hash(password)
        with self.lock, self.db:
            if initial_admin and self.db.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
                raise ValueError("An administrator already exists")
            if not initial_admin:
                row = self.db.execute("SELECT * FROM invites WHERE token=?", (digest(invite or ""),)).fetchone()
                if not row or row["used"] or row["expires"] < time.time():
                    raise ValueError("Invitation is invalid, expired, or already used")
            uid = uuid.uuid4().hex
            self.db.execute("INSERT INTO users(id,username,password,role) VALUES (?,?,?,?)", (uid, username, encoded, role))
            if not initial_admin:
                self.db.execute("UPDATE invites SET used=1 WHERE token=?", (digest(invite),))
            return uid

    def invite(self):
        token = secrets.token_urlsafe(32)
        with self.lock, self.db:
            self.db.execute("INSERT INTO invites(token,expires) VALUES (?,?)", (digest(token), time.time() + 86400))
        return token

    def login(self, username, password):
        user = self.user(username)
        if not password_matches(password, user["password"] if user else None) or user["disabled"]:
            raise PermissionError("Invalid username or password")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.lock, self.db:
            self.db.execute("DELETE FROM auth WHERE expires<?", (time.time(),))
            self.db.execute("INSERT INTO auth VALUES (?,?,?,?)", (digest(token), user["id"], csrf, time.time() + SESSION_SECONDS))
        return token, csrf

    def authenticate(self, token):
        with self.lock:
            row = self.db.execute("SELECT users.id,username,role,csrf FROM auth JOIN users ON users.id=auth.uid "
                                  "WHERE token=? AND expires>? AND disabled=0", (digest(token), time.time())).fetchone()
        if not row:
            raise PermissionError("Please sign in")
        return dict(row)

    def logout(self, token):
        with self.lock, self.db:
            self.db.execute("DELETE FROM auth WHERE token=?", (digest(token),))

    def change_password(self, uid, old, new):
        with self.lock:
            row = self.db.execute("SELECT password FROM users WHERE id=?", (uid,)).fetchone()
        if not row or not password_matches(old, row[0]):
            raise PermissionError("Current password is incorrect")
        encoded = password_hash(new)
        with self.lock, self.db:
            self.db.execute("UPDATE users SET password=? WHERE id=?", (encoded, uid))
            self.db.execute("DELETE FROM auth WHERE uid=?", (uid,))

    def disable(self, username):
        with self.lock, self.db:
            self.db.execute("UPDATE users SET disabled=1 WHERE username=? AND role!='admin'", (username,))
            self.db.execute("DELETE FROM auth WHERE uid IN (SELECT id FROM users WHERE disabled=1)")

    def conversation(self, uid, cid):
        with self.lock:
            row = self.db.execute("SELECT * FROM conversations WHERE id=? AND uid=?", (cid, uid)).fetchone()
        if not row:
            raise KeyError("Conversation not found")
        return dict(row)

    def conversations(self, uid):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT id,title,created,updated FROM conversations WHERE uid=? ORDER BY updated DESC", (uid,))]

    def create_conversation(self, uid):
        cid = uuid.uuid4().hex
        with self.lock, self.db:
            if self.db.execute("SELECT count(*) FROM conversations WHERE uid=?", (uid,)).fetchone()[0] >= 200:
                raise ValueError("Conversation quota reached; ask your administrator to archive older data")
            self.db.execute("INSERT INTO conversations VALUES (?,?,?,?,?,?)", (cid, uid, "New conversation", uuid.uuid4().hex, time.time(), time.time()))
        return self.conversation(uid, cid)

    @staticmethod
    def _run_view(row, now):
        result = dict(row)
        result["activity"] = json.loads(result.get("activity") or "{}")
        end = now if result["status"] in ("running", "stopping") else result["finished_at"]
        result["elapsed_seconds"] = max(0.0, end - result["created"]) if end is not None else None
        timing = result["activity"].get("timing")
        if timing:
            timing["active_seconds"] = max(0.0, now - timing.get("recorded_at", now)) if timing.get("active") and result["status"] in ("running", "stopping") else 0.0
        return result

    def run(self, uid, rid):
        with self.lock:
            row = self.db.execute("SELECT runs.*,run_activity.data AS activity FROM runs JOIN conversations ON cid=conversations.id "
                                  "LEFT JOIN run_activity ON run_activity.rid=runs.id WHERE runs.id=? AND uid=?", (rid, uid)).fetchone()
        if not row:
            raise KeyError("Run not found")
        return self._run_view(row, time.time())

    def runs(self, uid, cid):
        self.conversation(uid, cid)
        with self.lock:
            now = time.time()
            return [self._run_view(r, now) for r in self.db.execute("SELECT runs.*,run_activity.data AS activity FROM runs LEFT JOIN run_activity ON run_activity.rid=runs.id WHERE cid=? ORDER BY created", (cid,))]

    def begin(self, uid, cid, query, *, expected_input=None):
        self.conversation(uid, cid)
        rid = uuid.uuid4().hex
        with self.lock, self.db:
            if expected_input is not None:
                self.input_request(uid, expected_input[0], cid=cid, rid=expected_input[1], pending=True)
            if self.db.execute("SELECT 1 FROM runs JOIN conversations ON cid=conversations.id WHERE uid=? AND status IN ('running','stopping')", (uid,)).fetchone():
                raise ValueError("You already have a running task; stop it or wait for it to finish")
            self.db.execute("INSERT INTO runs(id,cid,query,status,created) VALUES (?,?,?,'running',?)", (rid, cid, query, time.time()))
            self.db.execute("UPDATE input_requests SET state='resuming',reply_rid=? WHERE cid=? AND state='pending'", (rid, cid))
            self.db.execute("UPDATE conversations SET title=CASE WHEN title='New conversation' THEN ? ELSE title END, updated=? WHERE id=?", (query[:70], time.time(), cid))
        return rid

    def finish(self, rid, *, status, answer="", reason="", generation="", turns=0):
        with self.lock, self.db:
            self.db.execute("UPDATE runs SET status=?,answer=?,reason=?,generation=?,turns=?,finished_at=COALESCE(finished_at,?) WHERE id=?",
                            (status, answer, reason or "", generation, turns, time.time(), rid))
            row = self.db.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
            elapsed = self._run_view(row, time.time())["elapsed_seconds"] if row else None
            if status != "needs_input":
                state = "answered" if status == "completed" else "interrupted"
                self.db.execute("UPDATE input_requests SET state=? WHERE reply_rid=? AND state='resuming'", (state, rid))
                self.db.execute("UPDATE input_requests SET state='interrupted' WHERE origin_rid=? AND state='pending'", (rid,))
            # Persist completion and its elapsed time atomically, so SSE replay
            # and a refreshed conversation show the same frozen duration.
            self.db.execute("INSERT INTO events(rid,data) VALUES (?,?)", (rid, json.dumps({
                "kind": "finished", "status": status, "answer": answer, "reason": reason or "",
                "generation": generation, "turns": turns, "elapsed_seconds": elapsed,
                "created": row["created"] if row else None, "finished_at": row["finished_at"] if row else None,
            }, ensure_ascii=False)))

    def event(self, rid, data):
        with self.lock, self.db:
            self.db.execute("INSERT INTO events(rid,data) VALUES (?,?)", (rid, json.dumps(data, ensure_ascii=False)))
            if data.get("kind") in ("stage_timing", "model_config", "tool_start"):
                row = self.db.execute("SELECT data FROM run_activity WHERE rid=?", (rid,)).fetchone()
                summary = json.loads(row[0]) if row else {}
                if data["kind"] == "stage_timing":
                    summary["timing"] = data
                elif data["kind"] == "model_config":
                    summary["profile"] = data.get("profile", {})
                else:
                    summary["tool_count"] = summary.get("tool_count", 0) + 1
                self.db.execute("INSERT INTO run_activity VALUES (?,?) ON CONFLICT(rid) DO UPDATE SET data=excluded.data",
                                (rid, json.dumps(summary, ensure_ascii=False)))

    def history(self, uid, rid, *, after=0, through=None, limit=60):
        self.run(uid, rid)
        if after < 0 or limit < 1 or limit > 100 or (through is not None and through < 0):
            raise ValueError("Invalid history page")
        with self.lock:
            maximum = self.db.execute("SELECT COALESCE(MAX(seq),0) FROM events WHERE rid=?", (rid,)).fetchone()[0]
            through = min(maximum, through) if through is not None else maximum
            rows = self.db.execute("SELECT seq,data FROM events WHERE rid=? AND seq>? AND seq<=? ORDER BY seq LIMIT ?",
                                   (rid, after, through, limit + 1)).fetchall()
        # Keep individual receipts intact. A large receipt occupies a page by itself.
        page, size = [], 0
        for row in rows[:limit]:
            if page and size + len(row[1]) > 131072:
                break
            page.append({"id": row[0], "data": json.loads(row[1])})
            size += len(row[1])
        cursor = page[-1]["id"] if page else after
        return {"run_id": rid, "events": page, "next": cursor, "through": through,
                "has_more": any(row[0] > cursor for row in rows)}


    def events(self, uid, rid, after):
        self.run(uid, rid)
        with self.lock:
            return [{"id": r[0], "data": json.loads(r[1])} for r in self.db.execute("SELECT seq,data FROM events WHERE rid=? AND seq>? ORDER BY seq LIMIT 100", (rid, after))]

    def receipt_events(self, uid, rid):
        self.run(uid, rid)
        with self.lock:
            rows = self.db.execute("SELECT data FROM events WHERE rid=? AND json_extract(data,'$.kind') "
                                   "IN ('tool_result','knowledge_sources') ORDER BY seq", (rid,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def files(self, uid, cid, generation=None):
        conv = self.conversation(uid, cid)
        generation = generation or conv["generation"]
        with self.lock:
            return {r[0]: bytes(r[1]) for r in self.db.execute("SELECT name,content FROM files WHERE cid=? AND generation=?", (cid, generation))}

    def file_origins(self, uid, cid, generation=None):
        conv = self.conversation(uid, cid)
        generation = generation or conv["generation"]
        with self.lock:
            rows = self.db.execute(
                "SELECT f.name,f.sha256,o.record FROM files f LEFT JOIN file_origins o "
                "ON f.cid=o.cid AND f.generation=o.generation AND f.name=o.name AND f.sha256=o.sha256 "
                "WHERE f.cid=? AND f.generation=?", (cid, generation)).fetchall()
        return {row[0]: json.loads(row[2]) if row[2] else {
            "origin": "unknown", "sha256": row[1], "scope": "legacy file; acquisition not recorded"}
                for row in rows}

    def snapshot(self, uid, cid, files, *, origins=None):
        self.conversation(uid, cid)
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
        generation = uuid.uuid4().hex
        with self.lock, self.db:
            previous_origins = self.file_origins(uid, cid)
            records = []
            for name, data in files.items():
                sha = hashlib.sha256(data).hexdigest()
                supplied = (origins or {}).get(name)
                prior = previous_origins.get(name, {})
                origin = supplied if supplied is not None else prior if prior.get("sha256") == sha else None
                if not isinstance(origin, dict) or origin.get("sha256") != sha:
                    origin = {"origin": "unknown", "sha256": sha,
                              "scope": "no matching runtime acquisition record"}
                records.append((cid, generation, name, sha, json.dumps(origin, ensure_ascii=False)))
            used = self.db.execute("SELECT COALESCE(sum(length(content)),0) FROM files JOIN conversations ON cid=conversations.id WHERE uid=?", (uid,)).fetchone()[0]
            if used + total > USER_QUOTA:
                raise ValueError("User storage quota exceeded; snapshot was not committed")
            self.db.executemany("INSERT INTO files VALUES (?,?,?,?,?)", [(cid, generation, name, data, hashlib.sha256(data).hexdigest()) for name, data in files.items()])
            self.db.executemany("INSERT INTO file_origins VALUES (?,?,?,?,?)", records)
            self.db.execute("UPDATE conversations SET generation=?,updated=? WHERE id=?", (generation, time.time(), cid))
        return generation

    def input_for_reply(self, rid):
        with self.lock:
            row = self.db.execute("SELECT input_requests.*,runs.query FROM input_requests JOIN runs ON reply_rid=runs.id AND input_requests.cid=runs.cid WHERE reply_rid=? AND state='resuming'", (rid,)).fetchone()
        return {**dict(row), "payload": json.loads(row["payload"])} if row else None

    def pause_input(self, rid, core_id, job_id, payload):
        if not all(re.fullmatch(r"[a-f0-9]{32}", value) for value in (rid, core_id, job_id, payload["id"])):
            raise ValueError("Invalid human-input identity")
        with self.lock, self.db:
            run = self.db.execute("SELECT cid,status FROM runs WHERE id=?", (rid,)).fetchone()
            if not run or run["status"] != "running":
                raise ValueError("Only a running task can publish a new input request")
            self.db.execute("UPDATE input_requests SET state='answered' WHERE reply_rid=? AND state='resuming'", (rid,))
            self.db.execute("INSERT INTO input_requests(id,cid,origin_rid,core_id,job_id,payload,created) VALUES (?,?,?,?,?,?,?)",
                            (payload["id"], run["cid"], rid, core_id, job_id, json.dumps(payload, ensure_ascii=False), time.time()))

    def input_request(self, uid, request_id, *, cid=None, rid=None, pending=False):
        with self.lock:
            row = self.db.execute(
                "SELECT input_requests.*,runs.status AS run_status,conversations.title "
                "FROM input_requests JOIN conversations ON input_requests.cid=conversations.id "
                "JOIN runs ON input_requests.origin_rid=runs.id WHERE input_requests.id=? AND uid=?",
                (request_id, uid)).fetchone()
            if not row or (cid is not None and row["cid"] != cid) or (rid is not None and row["origin_rid"] != rid):
                raise KeyError("Input request not found")
            if pending and (row["state"] != "pending" or row["run_status"] != "needs_input"):
                raise ValueError("This input request has already been answered or closed")
            return dict(row)

    def pending_inputs(self, uid, cid=None, *, include_closed=False):
        if cid is not None:
            self.conversation(uid, cid)
        clauses, args = ["uid=?"], [uid]
        if cid is not None:
            clauses.append("input_requests.cid=?")
            args.append(cid)
        if include_closed:
            clauses.append("(input_requests.state!='pending' OR runs.status='needs_input')")
        else:
            clauses.append("input_requests.state='pending' AND runs.status='needs_input'")
        with self.lock:
            rows = self.db.execute(
                "SELECT input_requests.id,input_requests.cid,input_requests.origin_rid,input_requests.state,"
                "input_requests.reply_rid,input_requests.payload,conversations.title "
                "FROM input_requests JOIN conversations ON input_requests.cid=conversations.id "
                "JOIN runs ON origin_rid=runs.id WHERE " + " AND ".join(clauses) +
                " ORDER BY input_requests.created", args).fetchall()
        return [{**json.loads(row["payload"]), "id": row["id"], "cid": row["cid"],
                 "rid": row["origin_rid"], "state": row["state"], "reply_rid": row["reply_rid"],
                 "title": row["title"]} for row in rows]

    def cancel_input(self, uid, request_id):
        with self.lock, self.db:
            row = self.db.execute("SELECT input_requests.origin_rid,input_requests.state FROM input_requests JOIN conversations ON input_requests.cid=conversations.id WHERE input_requests.id=? AND uid=?", (request_id, uid)).fetchone()
            if not row:
                raise KeyError("Input request not found")
            if row["state"] != "pending":
                raise ValueError("This input request has already been answered or closed")
            self.db.execute("UPDATE input_requests SET state='cancelled' WHERE id=?", (request_id,))
        self.finish(row["origin_rid"], status="stopped", reason="The user cancelled the pending input request; saved files were retained")

    def recover(self):
        with self.lock:
            ids = [r[0] for r in self.db.execute("SELECT id FROM runs WHERE status IN ('running','stopping')")]
        for rid in ids:
            self.finish(rid, status="interrupted", reason="Service restarted. The last committed files are retained; there is no automatic replay.")
        return ids

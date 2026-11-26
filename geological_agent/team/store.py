"""Account ownership and immutable file snapshots; no client-supplied host paths."""
import hashlib
from contextlib import nullcontext
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
        CREATE TABLE IF NOT EXISTS generation_audit(cid TEXT REFERENCES conversations(id), generation TEXT,
          action TEXT NOT NULL, source_generation TEXT, created REAL NOT NULL, PRIMARY KEY(cid,generation));
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

    @staticmethod
    def validate_user_identity(username, role="member", initial_admin=False):
        if not isinstance(username, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{3,40}", username):
            raise ValueError("Username must be 3-40 letters, numbers, dots, underscores, or hyphens")
        if role not in ("member", "admin") or (role == "admin" and not initial_admin):
            raise ValueError("Administrator creation requires the local administration command")

    def create_user_in_transaction(self, connection, username, encoded_password, *, role="member", initial_admin=False):
        """Trusted account insert only. Caller holds Store.lock and owns COMMIT/ROLLBACK.

        Password hashing must finish before the write transaction. Invitation and
        profile/OTP policy belong to the registration service, not this primitive.
        """
        if connection is not self.db or not connection.in_transaction:
            raise RuntimeError("Explicit transaction on Store.db is required")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise RuntimeError("Foreign key enforcement is required")
        self.validate_user_identity(username, role, initial_admin)
        if not isinstance(encoded_password, str) or not re.fullmatch(r"[0-9a-f]{32}:[0-9a-f]{128}", encoded_password):
            raise ValueError("A prepared scrypt password hash is required")
        if initial_admin and connection.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
            raise ValueError("An administrator already exists")
        uid = uuid.uuid4().hex
        connection.execute("INSERT INTO users(id,username,password,role) VALUES (?,?,?,?)", (uid, username, encoded_password, role))
        return uid

    def create_user(self, username, password, *, role="member", invite=None, initial_admin=False):
        # Backward-compatible trusted/local wrapper. Public signup never calls it.
        self.validate_user_identity(username, role, initial_admin)
        encoded = password_hash(password)
        with self.lock, self.db:
            if not self.db.in_transaction:
                self.db.execute("BEGIN IMMEDIATE")
            if not initial_admin:
                row = self.db.execute("SELECT * FROM invites WHERE token=?", (digest(invite or ""),)).fetchone()
                multi=bool(self.db.execute("SELECT 1 FROM sqlite_master WHERE name='invitation_limits' AND type='table'").fetchone())
                quota=self.db.execute('SELECT used_count,max_uses FROM invitation_limits WHERE token=?',(digest(invite or ''),)).fetchone() if multi else None
                unavailable=(not quota or quota['used_count']>=quota['max_uses']) if multi else bool(row and row['used'])
                if not row or unavailable or row["expires"] <= time.time() or ('revoked_at' in row.keys() and row['revoked_at'] is not None):
                    raise ValueError("Invitation is invalid, expired, or already used")
            uid = self.create_user_in_transaction(self.db, username, encoded, role=role, initial_admin=initial_admin)
            if not initial_admin:
                if multi:
                    from .activity_store import ActivityStore
                    repo=ActivityStore(self.db)
                    if not repo.mark_invite_used(digest(invite),now=time.time()):raise ValueError('Invitation capacity exhausted')
                    repo.record_invite_use(digest(invite),uid,used_at=time.time(),registration_request_id=uuid.uuid4().hex)
                else:
                    self.db.execute("UPDATE invites SET used=1 WHERE token=?", (digest(invite),))
            return uid

    def invite(self):
        token = secrets.token_urlsafe(32)
        with self.lock, self.db:
            self.db.execute("INSERT INTO invites(token,expires) VALUES (?,?)", (digest(token), time.time() + 86400))
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='invitation_limits' AND type='table'").fetchone():
                self.db.execute('INSERT INTO invitation_limits(token,max_uses,used_count,legacy_used) VALUES (?,50,0,0)',(digest(token),))
        return token

    def login(self, username, password):
        identifier = username.strip() if isinstance(username,str) else ''
        with self.lock:
            if '@' in identifier:
                exists=self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='email_identities'").fetchone()
                row=self.db.execute('SELECT u.* FROM users u JOIN email_identities e ON e.user_id=u.id WHERE e.email=? COLLATE NOCASE', (identifier.lower(),)).fetchone() if exists else None
                user=dict(row) if row else None
            else:
                user=self.user(identifier)
        if not password_matches(password, user["password"] if user else None) or user["disabled"]:
            raise PermissionError("Invalid username or password")
        return self.create_session(user['id'],password_snapshot=user['password'])

    def create_session_in_transaction(self, connection, uid):
        """Existing auth/Cookie contract, after the caller verified identity."""
        if connection is not self.db or not connection.in_transaction:
            raise RuntimeError('Explicit transaction on Store.db is required')
        if not connection.execute('SELECT 1 FROM users WHERE id=? AND disabled=0', (uid,)).fetchone():
            raise PermissionError('Please sign in')
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        connection.execute('DELETE FROM auth WHERE expires<?', (time.time(),))
        connection.execute('INSERT INTO auth VALUES (?,?,?,?)', (digest(token), uid, csrf, time.time() + SESSION_SECONDS))
        return token, csrf

    def create_session(self, uid, *, password_snapshot=None):
        with self.lock, self.db:
            self.db.execute('BEGIN IMMEDIATE')
            # A password reset may finish during scrypt or after registration
            # commits. Fence Session issuance against the verified hash snapshot.
            if password_snapshot is not None:
                current=self.db.execute('SELECT password,disabled FROM users WHERE id=?',(uid,)).fetchone()
                if not current or current['disabled'] or not hmac.compare_digest(current['password'],password_snapshot):
                    raise PermissionError('Invalid username or password')
            return self.create_session_in_transaction(self.db, uid)

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
            self.db.execute('BEGIN IMMEDIATE')
            if self.db.execute("UPDATE users SET password=? WHERE id=? AND password=? AND disabled=0", (encoded, uid, row[0])).rowcount!=1:
                raise PermissionError('Password changed; authenticate again')
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

    def active_runs(self, uid):
        with self.lock:
            now = time.time()
            rows = self.db.execute(
                "SELECT runs.*,conversations.title,run_activity.data AS activity "
                "FROM runs JOIN conversations ON conversations.id=runs.cid "
                "LEFT JOIN run_activity ON run_activity.rid=runs.id "
                "WHERE conversations.uid=? AND runs.status IN ('running','stopping') "
                "ORDER BY runs.created", (uid,)).fetchall()
            return [{**self._run_view(row, now), "title": row["title"]} for row in rows]

    def begin(self, uid, cid, query, *, expected_input=None, _rid=None):
        self.conversation(uid, cid)
        rid = _rid or uuid.uuid4().hex
        with self.lock, self.db:
            if expected_input is not None:
                self.input_request(uid, expected_input[0], cid=cid, rid=expected_input[1], pending=True)
            if self.db.execute("SELECT 1 FROM runs JOIN conversations ON cid=conversations.id WHERE uid=? AND status IN ('running','stopping')", (uid,)).fetchone():
                raise ValueError("You already have a running task; stop it or wait for it to finish")
            self.db.execute("INSERT INTO runs(id,cid,query,status,created) VALUES (?,?,?,'running',?)", (rid, cid, query, time.time()))
            self.db.execute("UPDATE input_requests SET state='resuming',reply_rid=? WHERE cid=? AND state='pending'", (rid, cid))
            self.db.execute("UPDATE conversations SET title=CASE WHEN title='New conversation' THEN ? ELSE title END, updated=? WHERE id=?", (query[:70], time.time(), cid))
        return rid

    def fail_start(self, uid, rid, *, reason):
        """Only for a fenced, unexecuted startup; not a general finish replacement."""
        with self.lock:
            def current():
                row = self.db.execute(
                    "SELECT r.status,c.uid FROM runs r JOIN conversations c ON r.cid=c.id WHERE r.id=?",
                    (rid,)).fetchone()
                if row is not None and row['uid'] != uid:
                    raise PermissionError("Run ownership mismatch")
                return row
            row = current()
            if row is None or row['status'] not in ('running', 'stopping'):
                return row['status'] if row is not None else None
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                row = current()  # Revalidate after obtaining the SQLite write lock.
                if row is None or row['status'] not in ('running', 'stopping'):
                    return row['status'] if row is not None else None
                # This reply never reached the runner. Restore its existing question.
                # The following existing finish commits this change and failed+event
                # on the same connection; an exception rolls the transaction back.
                self.db.execute("UPDATE input_requests SET state='pending',reply_rid=NULL "
                                "WHERE reply_rid=? AND state='resuming'", (rid,))
                self.finish(rid, status='failed', reason=reason)
                return 'failed'

    def finish(self, rid, *, status, answer="", reason="", generation="", turns=0):
        # First legal committed outcome wins; retries cannot rewrite or re-emit it.
        allowed = {'completed', 'incomplete', 'needs_input', 'failed', 'stopped', 'budget_exhausted', 'interrupted'}
        if status not in allowed:
            raise ValueError("Invalid task terminal status")
        with self.lock, self.db:
            if not self.db.in_transaction:
                self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
            if row is None:
                raise KeyError("Run not found")
            current = row['status']
            cancel_paused = current == 'needs_input' and status == 'stopped' and self.db.execute(
                "SELECT 1 FROM input_requests WHERE origin_rid=? AND state='cancelled'", (rid,)).fetchone()
            if current not in ('running', 'stopping') and not cancel_paused:
                return current
            changed = self.db.execute(
                "UPDATE runs SET status=?,answer=?,reason=?,generation=?,turns=?,finished_at=COALESCE(finished_at,?) "
                "WHERE id=? AND status=?", (status, answer, reason or "", generation, turns, time.time(), rid, current)).rowcount
            if not changed:
                return current
            row = self.db.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
            elapsed = self._run_view(row, time.time())["elapsed_seconds"]
            if status != "needs_input":
                state = "answered" if status == "completed" else "interrupted"
                self.db.execute("UPDATE input_requests SET state=? WHERE reply_rid=? AND state='resuming'", (state, rid))
                self.db.execute("UPDATE input_requests SET state='interrupted' WHERE origin_rid=? AND state='pending'", (rid,))
            self.db.execute("INSERT INTO events(rid,data) VALUES (?,?)", (rid, json.dumps({
                "kind": "finished", "status": status, "answer": answer, "reason": reason or "",
                "generation": generation, "turns": turns, "elapsed_seconds": elapsed,
                "created": row["created"], "finished_at": row["finished_at"],
            }, ensure_ascii=False)))
            return status

    def publish(self, uid, cid, rid, files, *, base_generation, origins=None, **outcome):
        """File generation, terminal row and event share one SQLite commit."""
        with self.lock, self.db:
            if not self.db.in_transaction:
                self.db.execute("BEGIN IMMEDIATE")
            row = self.run(uid, rid)
            if row['cid'] != cid:
                raise PermissionError("Run conversation mismatch")
            if row['status'] not in ('running', 'stopping'):
                return row['status']
            if self.conversation(uid, cid)['generation'] != base_generation:
                raise ValueError("Conversation files changed before result publication")
            generation = self.snapshot(uid, cid, files, origins=origins, _transaction=True, action='run')
            return self.finish(rid, generation=generation, **outcome)

    def event(self, rid, data):
        with self.lock, self.db:
            self.db.execute("INSERT INTO events(rid,data) VALUES (?,?)", (rid, json.dumps(data, ensure_ascii=False)))
            if data.get("kind") in ("stage_timing", "model_config", "tool_start", "skill_selected", "skill_loaded", "run_mode", "plan_confirmed"):
                row = self.db.execute("SELECT data FROM run_activity WHERE rid=?", (rid,)).fetchone()
                summary = json.loads(row[0]) if row else {}
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

    def file(self, uid, cid, name, generation=None):
        conv = self.conversation(uid, cid)
        generation = generation or conv["generation"]
        with self.lock:
            row = self.db.execute("SELECT content FROM files WHERE cid=? AND generation=? AND name=?",
                                  (cid, generation, name)).fetchone()
        return bytes(row[0]) if row is not None else None

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

    def generations(self, uid, cid):
        conv = self.conversation(uid, cid)
        with self.lock:
            rows = self.db.execute("""
                WITH snapshots AS (
                  SELECT generation,name,length(content) AS bytes FROM files WHERE cid=?
                  UNION ALL SELECT ?, '', 0
                  UNION ALL SELECT generation,'',0 FROM generation_audit WHERE cid=?
                  UNION ALL SELECT generation,'',0 FROM runs WHERE cid=? AND generation IS NOT NULL AND generation<>''
                ), totals AS (
                  SELECT generation,count(NULLIF(name,'')) AS file_count,sum(bytes) AS bytes FROM snapshots GROUP BY generation
                )
                SELECT t.generation,t.file_count,t.bytes,a.action,a.source_generation,
                  COALESCE(a.created,min(r.created)) AS created,r.id AS run_id
                FROM totals t
                LEFT JOIN generation_audit a ON a.cid=? AND a.generation=t.generation
                LEFT JOIN runs r ON r.cid=? AND r.generation=t.generation
                GROUP BY t.generation ORDER BY COALESCE(COALESCE(a.created,min(r.created)),0) DESC,t.generation
                """, (cid, conv['generation'], cid, cid, cid, cid)).fetchall()
        return [{**dict(row), 'current': row['generation'] == conv['generation'],
                 'created_known': row['created'] is not None} for row in rows]

    def generation(self, uid, cid, generation):
        conv = self.conversation(uid, cid)
        if not self.generation_exists(uid, cid, generation):
            raise KeyError('Generation not found')
        with self.lock:
            row = self.db.execute("""
                SELECT a.action,a.source_generation,
                  COALESCE(a.created,(SELECT min(created) FROM runs WHERE cid=? AND generation=?)) AS created,
                  (SELECT id FROM runs WHERE cid=? AND generation=? ORDER BY created LIMIT 1) AS run_id
                FROM (SELECT 1) LEFT JOIN generation_audit a
                  ON a.cid=? AND a.generation=?
                """, (cid, generation, cid, generation, cid, generation)).fetchone()
        return {**dict(row), 'generation': generation, 'file_count': None, 'bytes': None,
                'current': generation == conv['generation'], 'created_known': row['created'] is not None}

    def generation_exists(self, uid, cid, generation):
        conv = self.conversation(uid, cid)
        if not isinstance(generation, str) or not re.fullmatch(r'[a-f0-9]{32}', generation):
            return False
        if generation == conv['generation']:
            return True
        with self.lock:
            return self.db.execute("SELECT 1 FROM generation_audit WHERE cid=? AND generation=? "
                                   "UNION ALL SELECT 1 FROM files WHERE cid=? AND generation=? "
                                   "UNION ALL SELECT 1 FROM runs WHERE cid=? AND generation=? LIMIT 1",
                                   (cid, generation, cid, generation, cid, generation)).fetchone() is not None

    def restore(self, uid, cid, generation):
        if not self.generation_exists(uid, cid, generation):
            raise KeyError('Generation not found')
        with self.lock, self.db:
            if not self.db.in_transaction:
                self.db.execute('BEGIN IMMEDIATE')
            if self.db.execute("SELECT 1 FROM runs JOIN conversations ON cid=conversations.id "
                               "WHERE conversations.id=? AND uid=? AND status IN ('running','stopping')",
                               (cid, uid)).fetchone():
                raise ValueError('Wait for your active task before restoring files')
            files = self.files(uid, cid, generation)
            origins = self.file_origins(uid, cid, generation)
            for record in origins.values():
                record['restored_from'] = generation
            return self.snapshot(uid, cid, files, origins=origins, _transaction=True,
                                 action='restore', source_generation=generation)

    def snapshot(self, uid, cid, files, *, origins=None, _transaction=False, action='snapshot', source_generation=None):
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
        with self.lock, (nullcontext() if _transaction else self.db):
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
            self.db.execute("INSERT INTO generation_audit VALUES (?,?,?,?,?)",
                            (cid, generation, action, source_generation, time.time()))
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

    def cancel_input(self, uid, request_id, *, _retry=False):
        with self.lock, self.db:
            if not self.db.in_transaction:
                self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT input_requests.origin_rid,input_requests.state FROM input_requests JOIN conversations ON input_requests.cid=conversations.id WHERE input_requests.id=? AND uid=?", (request_id, uid)).fetchone()
            if not row:
                raise KeyError("Input request not found")
            if row["state"] != "pending" and not (_retry and row['state'] == 'cancelled'):
                raise ValueError("This input request has already been answered or closed")
            self.db.execute("UPDATE input_requests SET state='cancelled' WHERE id=? AND state='pending'", (request_id,))
            return self.finish(row["origin_rid"], status="stopped", reason="The user cancelled the pending input request; saved files were retained")

    def recover(self, *, after='', limit=64):
        """Bounded discovery only; persistent evidence owns any recovery decision."""
        if not isinstance(after, str) or not 1 <= limit <= 64:
            raise ValueError("Invalid recovery page")
        with self.lock:
            timeout = self.db.execute("PRAGMA busy_timeout").fetchone()[0]
            deadline = time.monotonic() + .05
            self.db.execute("PRAGMA busy_timeout=" + str(min(timeout, 100)))
            self.db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            try:
                return [dict(row) for row in self.db.execute(
                    "SELECT r.id FROM runs r WHERE r.status IN ('running','stopping') AND r.id>? ORDER BY r.id LIMIT ?",
                    (after, limit))]
            finally:
                self.db.set_progress_handler(None, 0)
                self.db.execute("PRAGMA busy_timeout=" + str(timeout))

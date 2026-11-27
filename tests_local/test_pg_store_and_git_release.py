"""P2-1 tests: PostgreSQL business store adapter, SQLite->PG migration, and Git-first atomic release."""
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import uuid

import pytest

from geological_agent.context_store import ContextStoreError
from geological_agent.team.pg_store import (
    PostgresTeamStore,
    TeamStoreError,
    _build_pg_schema,
    migrate_sqlite_to_postgres,
    open_team_store,
)
from geological_agent.team.store import Store

_RELEASE_SPEC = importlib.util.spec_from_file_location(
    "git_release", Path(__file__).resolve().parents[1] / "scripts" / "git_release.py"
)
git_release = importlib.util.module_from_spec(_RELEASE_SPEC)
_RELEASE_SPEC.loader.exec_module(git_release)


class _SqlitePgShimConn:
    """Deterministic in-memory SQLite shim mimicking psycopg3 dict_row connection for unit tests."""

    def __init__(self, db: sqlite3.Connection):
        self._db = db

    @staticmethod
    def _translate(sql: str) -> str:
        out = sql.replace("%s", "?")
        out = re.sub(r"\s+FOR UPDATE\b", "", out, flags=re.I)
        out = out.replace("::bigint", "")
        out = out.replace("(data::jsonb ->> 'kind')", "json_extract(data,'$.kind')")
        out = re.sub(r"\bFROM \(SELECT 1\) AS dummy\b", "FROM (SELECT 1)", out)
        return out

    def execute(self, sql: str, params=None, **_kwargs):
        if "pg_get_serial_sequence" in sql:
            return self._db.execute("SELECT 1")
        translated = self._translate(sql)
        cur = self._db.execute(translated, tuple(params) if params is not None else ())
        return cur

    def commit(self):
        self._db.commit()


def _make_shimmed_pg_store(root: Path) -> PostgresTeamStore:
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE auth(token TEXT PRIMARY KEY, uid TEXT REFERENCES users(id), csrf TEXT, expires REAL);
        CREATE TABLE invites(token TEXT PRIMARY KEY, expires REAL, used INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE conversations(id TEXT PRIMARY KEY, uid TEXT REFERENCES users(id), title TEXT, generation TEXT NOT NULL, created REAL, updated REAL);
        CREATE TABLE files(cid TEXT REFERENCES conversations(id), generation TEXT, name TEXT, sha256 TEXT NOT NULL, byte_size INTEGER NOT NULL, PRIMARY KEY(cid,generation,name));
        CREATE TABLE file_origins(cid TEXT, generation TEXT, name TEXT, sha256 TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(cid,generation,name));
        CREATE TABLE generation_audit(cid TEXT REFERENCES conversations(id), generation TEXT, action TEXT NOT NULL, source_generation TEXT, created REAL NOT NULL, PRIMARY KEY(cid,generation));
        CREATE TABLE runs(id TEXT PRIMARY KEY, cid TEXT REFERENCES conversations(id), query TEXT, status TEXT, answer TEXT DEFAULT '', reason TEXT DEFAULT '', generation TEXT DEFAULT '', created REAL, turns INTEGER DEFAULT 0, finished_at REAL);
        CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT, rid TEXT REFERENCES runs(id), data TEXT NOT NULL);
        CREATE TABLE run_activity(rid TEXT PRIMARY KEY REFERENCES runs(id), data TEXT NOT NULL);
        CREATE TABLE input_requests(id TEXT PRIMARY KEY, cid TEXT REFERENCES conversations(id), origin_rid TEXT REFERENCES runs(id), core_id TEXT NOT NULL, job_id TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', reply_rid TEXT UNIQUE REFERENCES runs(id), created REAL NOT NULL);
    """)
    store = PostgresTeamStore(root, "postgresql://shimmed.local/test", setup_schema=False)

    @contextmanager
    def _conn(*, autocommit: bool = False):
        yield _SqlitePgShimConn(db)

    store.connection = _conn
    return store


def test_pg_schema_and_backend_factory_fail_closed(tmp_path, monkeypatch):
    # Valid schema builds complete DDL; invalid/injection names fail closed.
    ddl = _build_pg_schema("geotool_team")
    assert "CREATE SCHEMA IF NOT EXISTS geotool_team;" in ddl
    assert "geotool_team.files(" in ddl
    assert "BIGSERIAL PRIMARY KEY" in ddl
    for bad in ("bad-name", "1starts_digit", "a; DROP TABLE users;--", "UPPER"):
        with pytest.raises(ValueError, match="Invalid PostgreSQL schema"):
            _build_pg_schema(bad)

    # Default backend is SQLite Store
    monkeypatch.delenv("GEOTOOL_TEAM_DB_BACKEND", raising=False)
    s = open_team_store(tmp_path / "default_state")
    try:
        assert isinstance(s, Store)
    finally:
        s.close()

    # Unknown backend fails closed (no silent fallback)
    monkeypatch.setenv("GEOTOOL_TEAM_DB_BACKEND", "mysql")
    with pytest.raises(ValueError, match="automatic fallback"):
        open_team_store(tmp_path / "bad_backend")

    # Postgres backend without DSN file fails closed
    monkeypatch.setenv("GEOTOOL_TEAM_DB_BACKEND", "postgres")
    monkeypatch.delenv("GEOTOOL_TEAM_DSN_FILE", raising=False)
    with pytest.raises(ValueError, match="GEOTOOL_TEAM_DSN_FILE"):
        open_team_store(tmp_path / "missing_dsn")

    # On POSIX, world-readable DSN file is rejected by private_dsn()
    if os.name != "nt":
        dsn_file = tmp_path / "public.dsn"
        dsn_file.write_text("postgresql://127.0.0.1/test", encoding="utf-8")
        dsn_file.chmod(0o644)
        monkeypatch.setenv("GEOTOOL_TEAM_DSN_FILE", str(dsn_file))
        with pytest.raises(ContextStoreError, match="0600"):
            open_team_store(tmp_path / "unsafe_dsn")


def test_pg_store_full_lifecycle_and_sqlite_migration_idempotent(tmp_path):
    # 1. Build a rich SQLite Store containing both legacy inline BLOBs and CAS snapshots.
    sqlite_root = tmp_path / "sqlite_state"
    src = Store(sqlite_root)
    try:
        admin_id = src.create_user("admin", "Admin-Test-Password-2026", role="admin", initial_admin=True)
        inv = src.invite()
        member_id = src.create_user("geologist", "Member-Test-Password-2026", invite=inv)
        token, csrf = src.login("geologist", "Member-Test-Password-2026")
        conv = src.create_conversation(member_id)
        cid = conv["id"]

        # Legacy inline BLOB row directly in SQLite `files`
        legacy_bytes = b"legacy-core-sample-bytes"
        legacy_sha = hashlib.sha256(legacy_bytes).hexdigest()
        with src.lock, src.db:
            src.db.execute(
                "INSERT INTO files(cid,generation,name,content,sha256) VALUES (?,?,?,?,?)",
                (cid, conv["generation"], "legacy.txt", legacy_bytes, legacy_sha),
            )

        # New CAS snapshot row via Store.snapshot()
        csv_bytes = b"sample,au_ppm\nS1,2.4\nS2,3.1\n"
        gen1 = src.snapshot(member_id, cid, {"assay.csv": csv_bytes}, action="upload")
        rid = src.begin(member_id, cid, "Analyze assay.csv")
        src.event(rid, {"kind": "run_mode", "mode": "agent"})
        src.event(rid, {"kind": "tool_result", "name": "read_file", "result": {"status": "ok"}})
        src.publish(
            member_id, cid, rid,
            {"assay.csv": csv_bytes, "report.md": b"# Summary\nMean Au = 2.75 ppm\n"},
            base_generation=gen1, status="completed", answer="Done", turns=2,
        )
    finally:
        src.close()

    # 2. Migrate SQLite -> PostgresTeamStore (shimmed) and verify byte-exact parity!
    pg_store = _make_shimmed_pg_store(tmp_path / "pg_state")
    report = migrate_sqlite_to_postgres(sqlite_root, pg_store, verify=True)
    assert report["ok"] is True
    assert report["counts"]["users"] == 2
    assert report["counts"]["conversations"] == 1
    assert report["counts"]["files"] == 4
    assert report["counts"]["runs"] == 1
    assert report["counts"]["events"] >= 3

    # Verify authenticated session, conversation, files, manifest, receipts, and restore!
    assert pg_store.authenticate(token)["username"] == "geologist"
    assert pg_store.file(member_id, cid, "legacy.txt", conv["generation"]) == legacy_bytes
    assert pg_store.file(member_id, cid, "assay.csv") == csv_bytes
    assert pg_store.file(member_id, cid, "report.md") == b"# Summary\nMean Au = 2.75 ppm\n"
    manifest = {m["name"]: m["bytes"] for m in pg_store.file_manifest(member_id, cid)}
    assert manifest == {"assay.csv": len(csv_bytes), "report.md": len(b"# Summary\nMean Au = 2.75 ppm\n")}
    assert len(pg_store.receipt_events(member_id, cid if False else rid)) == 1
    assert pg_store.run(member_id, rid)["status"] == "completed"

    # Second migration run is cleanly idempotent!
    report2 = migrate_sqlite_to_postgres(sqlite_root, pg_store, verify=True)
    assert report2["ok"] is True

    # Native PostgresTeamStore operations: restore + new run + pause/cancel HITL + CAS GC
    restored = pg_store.restore(member_id, cid, gen1)
    assert pg_store.files(member_id, cid, restored) == {"assay.csv": csv_bytes}
    rid2 = pg_store.begin(member_id, cid, "Follow-up task")
    req_id = "1" * 32
    pg_store.pause_input(rid2, "2" * 32, "3" * 32, {"id": req_id, "question": "Confirm CRS?"})
    pg_store.finish(rid2, status="needs_input", answer="Confirm CRS?")
    assert len(pg_store.pending_inputs(member_id, cid)) == 1
    assert pg_store.cancel_input(member_id, req_id) == "stopped"
    assert pg_store.pending_inputs(member_id, cid) == []
    assert pg_store.gc_cas_blobs()["removed_blobs"] == 0


def test_pg_store_live_postgres_if_configured(tmp_path):
    """Real PostgreSQL end-to-end verification when GEOTOOL_TEST_POSTGRES_DSN_FILE is provided."""
    dsn_path = os.environ.get("GEOTOOL_TEST_POSTGRES_DSN_FILE")
    if not dsn_path:
        pytest.skip("Set GEOTOOL_TEST_POSTGRES_DSN_FILE to run live PostgreSQL test")
    from geological_agent.context_store import private_dsn
    schema = f"test_p2_1_{uuid.uuid4().hex[:12]}"
    pg_store = PostgresTeamStore(tmp_path / "live_pg", private_dsn(dsn_path), schema=schema)
    try:
        uid = pg_store.create_user("admin", "Admin-Test-Password-2026", role="admin", initial_admin=True)
        tok, _ = pg_store.login("admin", "Admin-Test-Password-2026")
        assert pg_store.authenticate(tok)["id"] == uid
        cid = pg_store.create_conversation(uid)["id"]
        gen = pg_store.snapshot(uid, cid, {"live.csv": b"x,y\n1,2\n"}, action="upload")
        assert pg_store.file(uid, cid, "live.csv", gen) == b"x,y\n1,2\n"
    finally:
        with pg_store.connection(autocommit=True) as conn:
            conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE", prepare=False)
        pg_store.close()


def test_git_release_stage_activate_add_delete_drain_and_auto_rollback(tmp_path):
    deploy = tmp_path / "deploy"

    # Build v1 source tree
    src_v1 = tmp_path / "src_v1"
    (src_v1 / "app").mkdir(parents=True)
    (src_v1 / "app" / "main.py").write_text("VERSION = '0.31'\n", encoding="utf-8")
    (src_v1 / "app" / "legacy_removed.py").write_text("# will be removed in v2\n", encoding="utf-8")

    m1 = git_release.stage_release(deploy, src_v1, version="0.31", notes="baseline", git_sha="a" * 40, release_id="rel-v1")
    assert m1["file_count"] == 2
    r1 = git_release.activate_release(deploy, "rel-v1")
    assert r1["release_id"] == "rel-v1"
    cur_v1 = git_release._read_link_target(deploy / "current")
    assert cur_v1 is not None and (cur_v1 / "app" / "legacy_removed.py").is_file()

    # Build v2 source tree: modifies main.py, DELETES legacy_removed.py, ADDS new_pkg/feature.py!
    src_v2 = tmp_path / "src_v2"
    (src_v2 / "app" / "new_pkg").mkdir(parents=True)
    (src_v2 / "app" / "main.py").write_text("VERSION = '0.32'\n", encoding="utf-8")
    (src_v2 / "app" / "new_pkg" / "feature.py").write_text("ENABLED = True\n", encoding="utf-8")
    m2 = git_release.stage_release(deploy, src_v2, version="0.32", notes="p0+p1", git_sha="b" * 40, release_id="rel-v2")
    assert m2["source_sha256"] != m1["source_sha256"]

    # Drain guard rejects switch if active tasks remain (without touching `current`!)
    with pytest.raises(git_release.ReleaseDrainError):
        git_release.activate_release(deploy, "rel-v2", drain_check=lambda: False)
    assert git_release.release_status(deploy)["current"] == "rel-v1"

    # Activate v2 cleanly -> verifies added/deleted files reflected atomically and previous=rel-v1
    r2 = git_release.activate_release(deploy, "rel-v2", drain_check=lambda: True, health_check=lambda d, meta: (d / "app" / "new_pkg" / "feature.py").is_file())
    assert r2["previous_release_id"] == "rel-v1"
    cur_v2 = git_release._read_link_target(deploy / "current")
    assert cur_v2 is not None
    assert (cur_v2 / "app" / "new_pkg" / "feature.py").is_file()
    assert not (cur_v2 / "app" / "legacy_removed.py").exists()

    # Stage bad v3 whose health_check fails -> MUST automatically roll back to rel-v2!
    src_v3 = tmp_path / "src_v3"
    (src_v3 / "app").mkdir(parents=True)
    (src_v3 / "app" / "main.py").write_text("VERSION = '0.33-broken'\n", encoding="utf-8")
    git_release.stage_release(deploy, src_v3, version="0.33", notes="broken", git_sha="c" * 40, release_id="rel-v3")

    with pytest.raises(git_release.ReleaseActivationError) as exc_info:
        git_release.activate_release(deploy, "rel-v3", health_check=lambda d, meta: False)
    assert exc_info.value.rolled_back is True
    assert exc_info.value.rollback_target == "rel-v2"
    assert git_release.release_status(deploy)["current"] == "rel-v2"

    # Manual instant O(1) rollback from rel-v2 -> rel-v1
    rb = git_release.rollback_release(deploy)
    assert rb["release_id"] == "rel-v1"
    assert rb["rolled_back_from"] == "rel-v2"
    assert git_release.release_status(deploy)["current"] == "rel-v1"

    # Tampering detection: modifying a file inside a staged release fails verify_release()
    rel_v3_dir = deploy / "releases" / "rel-v3"
    git_release._make_writable_tree(rel_v3_dir)
    (rel_v3_dir / "app" / "main.py").write_text("TAMPERED\n", encoding="utf-8")
    with pytest.raises(git_release.ReleaseError, match="integrity check failed"):
        git_release.verify_release(rel_v3_dir)

    # CLI status check returns valid JSON
    assert git_release.main(["--deploy-root", str(deploy), "status"]) == 0

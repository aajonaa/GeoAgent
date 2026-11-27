"""P1-4 tests: Content-Addressed Storage (CAS), SQLite BLOB migration, and modular runtime/server."""
import hashlib
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from geological_agent.agent import runtime as runtime_mod
from geological_agent.agent.runtime_knowledge import (
    bounded_json_call,
    knowledge_query,
    missing_attachment,
    requested_library,
    source_context,
)
from geological_agent.agent.runtime_recovery import pause_review_protocol_state
from geological_agent.contracts import Message, ModelResponse
from geological_agent.settings import Settings
from geological_agent.team.cas import ContentAddressedStore
from geological_agent.team import server as server_mod
from geological_agent.team.server import COOKIE, create_app
from geological_agent.team.store import Store


def test_cas_deduplication_integrity_and_gc(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    payload = b"geology-sample-data-" * 1000
    sha1, size1 = cas.put(payload)
    sha2, size2 = cas.put(payload)
    assert sha1 == sha2 == hashlib.sha256(payload).hexdigest()
    assert size1 == size2 == len(payload)
    assert cas.exists(sha1)
    assert cas.size(sha1) == len(payload)
    assert cas.get(sha1) == payload

    # Only one physical blob file exists for deduplicated writes.
    blobs = [p for p in (tmp_path / "cas").rglob("*") if p.is_file()]
    assert len(blobs) == 1

    # Add a second blob and verify GC removes only unreferenced blobs.
    sha_orphan, _ = cas.put(b"orphan-blob-bytes")
    gc_report = cas.gc({sha1})
    assert gc_report["removed_blobs"] == 1
    assert gc_report["reclaimed_bytes"] == len(b"orphan-blob-bytes")
    assert cas.exists(sha1)
    assert not cas.exists(sha_orphan)

    # Corruption on disk fails closed on read.
    cas.path_for(sha1).write_bytes(b"corrupted-bytes")
    with pytest.raises(RuntimeError, match="integrity mismatch"):
        cas.get(sha1)

    with pytest.raises(ValueError, match="Invalid CAS SHA-256"):
        cas.get("../not-a-hash")


def test_store_snapshot_uses_cas_and_deduplicates_across_generations(tmp_path):
    store = Store(tmp_path / "state")
    uid = store.create_user("admin", "Admin-Test-Password-2026", role="admin", initial_admin=True)
    conv = store.create_conversation(uid)
    cid = conv["id"]

    big = b"SiO2,TiO2,Al2O3\n68.5,0.45,15.2\n" * 4000
    gens = []
    for i in range(4):
        g = store.snapshot(
            uid,
            cid,
            {"geochem.csv": big, f"note_{i}.txt": f"turn {i}".encode("utf-8")},
            action="run",
        )
        gens.append(g)

    # SQLite `files` table holds zero inline BLOB bytes for CAS rows!
    with store.lock:
        rows = store.db.execute(
            "SELECT f.name, length(f.content) AS inline_len, c.byte_size, c.sha256 "
            "FROM files f JOIN file_cas_index c ON f.cid=c.cid AND f.generation=c.generation AND f.name=c.name "
            "WHERE f.cid=?",
            (cid,),
        ).fetchall()
    assert len(rows) == 8
    assert all(r["inline_len"] == 0 for r in rows)

    # The 4 identical copies of `geochem.csv` share a single CAS blob on disk.
    big_sha = hashlib.sha256(big).hexdigest()
    assert store.cas.exists(big_sha)
    all_blobs = [p for p in (tmp_path / "state" / "cas-blobs").rglob("*") if p.is_file()]
    # 1 shared big blob + 4 distinct note blobs = 5 physical blobs instead of 8.
    assert len(all_blobs) == 5

    # All reads, manifests, generations, and restores remain byte-identical.
    assert store.file(uid, cid, "geochem.csv") == big
    manifest = store.file_manifest(uid, cid)
    by_name = {m["name"]: m for m in manifest}
    assert by_name["geochem.csv"]["bytes"] == len(big)
    assert by_name["geochem.csv"]["sha256"] == big_sha

    gen_rows = store.generations(uid, cid)
    latest_gen = next(g for g in gen_rows if g["generation"] == gens[-1])
    assert latest_gen["file_count"] == 2
    assert latest_gen["bytes"] == len(big) + len(b"turn 3")

    restored_gen = store.restore(uid, cid, gens[0])
    assert store.file(uid, cid, "note_0.txt", restored_gen) == b"turn 0"
    assert store.file(uid, cid, "geochem.csv", restored_gen) == big


def test_store_reads_legacy_inline_blobs_and_migrates_idempotently(tmp_path):
    store = Store(tmp_path / "legacy-state")
    uid = store.create_user("admin", "Admin-Test-Password-2026", role="admin", initial_admin=True)
    conv = store.create_conversation(uid)
    cid, gen = conv["id"], conv["generation"]

    # Simulate legacy pre-CAS inline BLOB rows written directly into `files`.
    dup_bytes = b"legacy-shared-payload-" * 500
    dup_sha = hashlib.sha256(dup_bytes).hexdigest()
    unique_bytes = b"legacy-unique-payload"
    unique_sha = hashlib.sha256(unique_bytes).hexdigest()
    gen2 = "b" * 32
    with store.lock, store.db:
        store.db.executemany(
            "INSERT INTO files(cid,generation,name,content,sha256) VALUES (?,?,?,?,?)",
            [
                (cid, gen, "a.bin", dup_bytes, dup_sha),
                (cid, gen, "b.bin", unique_bytes, unique_sha),
                (cid, gen2, "a_copy.bin", dup_bytes, dup_sha),
            ],
        )

    # Pre-migration reads work transparently on legacy inline rows.
    assert store.file(uid, cid, "a.bin", gen) == dup_bytes
    assert store.files(uid, cid, gen) == {"a.bin": dup_bytes, "b.bin": unique_bytes}
    manifest = {m["name"]: m for m in store.file_manifest(uid, cid, gen)}
    assert manifest["a.bin"]["bytes"] == len(dup_bytes)

    # Run idempotent batch migration to CAS.
    report = store.migrate_blobs_to_cas(batch_size=2, vacuum=True)
    assert report["migrated_rows"] == 3
    assert report["unique_blobs"] == 2
    assert report["reclaimed_blob_bytes"] == 2 * len(dup_bytes) + len(unique_bytes)

    # Post-migration: SQLite inline blobs are empty, CAS reads are byte-identical.
    with store.lock:
        inline_left = store.db.execute(
            "SELECT count(*) FROM files f LEFT JOIN file_cas_index c "
            "ON f.cid=c.cid AND f.generation=c.generation AND f.name=c.name WHERE c.cid IS NULL"
        ).fetchone()[0]
        inline_bytes = store.db.execute("SELECT COALESCE(sum(length(content)),0) FROM files").fetchone()[0]
    assert inline_left == 0
    assert inline_bytes == 0
    assert store.file(uid, cid, "a.bin", gen) == dup_bytes
    assert store.file(uid, cid, "b.bin", gen) == unique_bytes
    assert store.file(uid, cid, "a_copy.bin", gen2) == dup_bytes

    # Second migration call is a clean idempotent no-op.
    second = store.migrate_blobs_to_cas()
    assert second == {"migrated_rows": 0, "unique_blobs": 0, "reclaimed_blob_bytes": 0}


def test_modular_server_routes_and_presentation_with_cas(tmp_path):
    class FakeRunner:
        description = "cas test runner"
        def stop(self, rid):
            pass
        def run(self, rid, query, files, cancel, model_call, on_trace, **kwargs):
            return {
                "status": "completed",
                "answer": "Analyzed data.csv",
                "reason": "",
                "turns": 1,
                "files": {**files, "summary.csv": b"site,grade\nA,1.5\nB,2.1\n"},
            }

    app = create_app(tmp_path / "team", runner=FakeRunner(), trace_factory=lambda *_: SimpleNamespace(emit=lambda *a, **k: None))
    store = app.state.store
    store.create_user("admin", "Admin-Test-Password-2026", role="admin", initial_admin=True)

    with TestClient(app, base_url="http://127.0.0.1") as client:
        login = client.post("/api/login", json={"username": "admin", "password": "Admin-Test-Password-2026"})
        assert login.status_code == 200
        client.headers["x-csrf-token"] = login.json()["csrf"]

        # Modular auth & model settings routes
        me = client.get("/api/me")
        assert me.status_code == 200 and me.json()["username"] == "admin"
        assert client.get("/api/model-settings").status_code == 200
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/assets/nonexistent.js").status_code == 404

        # Modular conversation + CAS upload/files/download/table-preview routes
        cid = client.post("/api/conversations").json()["id"]
        csv_bytes = b"sample,cu_pct\nS1,0.85\nS2,1.20\n"
        up = client.post(f"/api/conversations/{cid}/upload?name=samples.csv", content=csv_bytes)
        assert up.status_code == 200
        gen = up.json()["generation"]

        listing = client.get(f"/api/conversations/{cid}/files").json()
        assert listing["generation"] == gen
        assert listing["files"] == [{
            "name": "samples.csv",
            "bytes": len(csv_bytes),
            "sha256": hashlib.sha256(csv_bytes).hexdigest(),
        }]
        assert client.get(f"/api/conversations/{cid}/download?name=samples.csv").content == csv_bytes

        # Presentation table preview works seamlessly over CAS storage!
        preview = client.get(f"/api/conversations/{cid}/table-preview?name=samples.csv&generation={gen}")
        assert preview.status_code == 200
        assert preview.json()["columns"] == ["sample", "cu_pct"]
        assert len(preview.json()["rows"]) == 2

        # Run a task that outputs a CAS-backed CSV and verify presentation + run table routes.
        rid = client.post(f"/api/conversations/{cid}/runs", json={"query": "summarize samples.csv"}).json()["id"]
        import time
        for _ in range(60):
            run_data = client.get(f"/api/runs/{rid}").json()
            if run_data["status"] != "running":
                break
            time.sleep(0.05)
        assert run_data["status"] == "completed"

        pres = client.get(f"/api/runs/{rid}/presentation")
        assert pres.status_code == 200
        assert any(f["name"] == "summary.csv" and f["bytes"] == len(b"site,grade\nA,1.5\nB,2.1\n") for f in pres.json()["files"])
        tbl = client.get(f"/api/runs/{rid}/table?name=summary.csv")
        assert tbl.status_code == 200
        assert tbl.json()["columns"] == ["site", "grade"]


def test_extracted_runtime_and_server_helpers_reexports(tmp_path):
    # Re-exports preserve backward compatibility for callers importing from runtime/server.
    assert runtime_mod.knowledge_query is knowledge_query
    assert runtime_mod.requested_library is requested_library
    assert runtime_mod.source_context is source_context
    assert hasattr(server_mod, "_ModelSlotLease")
    assert hasattr(server_mod, "_TaskStartup")
    assert hasattr(server_mod, "_confirmed_research_plan")
    assert hasattr(server_mod, "_deadline_evidence")

    # Direct unit test of extracted runtime_knowledge helpers
    assert requested_library("请查询共享知识库中的吉林金矿资料") is True
    assert requested_library("计算圆面积") is False
    assert missing_attachment({"task": "我还没有上传附件，请分析附件", "metadata": {}}, tmp_path) is True
    (tmp_path / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    assert missing_attachment({"task": "我还没有上传附件，请分析附件", "metadata": {}}, tmp_path) is False

    # Direct unit test of extracted bounded_json_call + pause_review_protocol_state
    class FakeModel:
        def invoke(self, req):
            return ModelResponse('{"source": "library", "query": "吉林金矿"}', (), "stop", usage={"total_tokens": 10})

    state = {"task": "吉林金矿成因", "model_turns": 0, "answer": "draft", "metadata": {"usage": []}}
    trace = SimpleNamespace(emit=lambda *a, **k: None)
    parsed = bounded_json_call(
        state, "source_selection", "Return JSON", {"q": "test"},
        settings=Settings(), model=FakeModel(), cancel=Event(), run_id="r1",
        record=lambda u, s: u, trace=trace, activity=lambda *a, **k: None,
    )
    assert parsed == {"source": "library", "query": "吉林金矿"}
    assert state["model_turns"] == 1

    paused = pause_review_protocol_state(
        state, "review:answer", "schema invalid",
        settings=Settings(), cancel=Event(), run_id="r1", trace=trace,
    )
    assert paused["status"] == "incomplete"
    assert paused["metadata"]["protocol_recovery"]["phase"] == "review:answer"

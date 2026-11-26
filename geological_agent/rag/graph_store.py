"""Account-scoped graph index beside the existing PostgreSQL knowledge tables."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .knowledge_graph import VERSION, TYPES, ENTITIES, extract_document


class GraphBusy(RuntimeError):
    pass


class GraphStore:
    def __init__(self, index, organization=None):
        self.index, self.owner = index, index.owner_id
        self.organization = organization or {}

    def setup(self):
        """Idempotent additive migration. Never modifies document/chunk tables."""
        with self.index.connection() as db:
            db.execute("SELECT pg_advisory_xact_lock(178430901)")
            db.execute("""CREATE TABLE IF NOT EXISTS geotool_knowledge.kg_documents (
                owner_id text NOT NULL, document_id text NOT NULL, sha256 text NOT NULL,
                version text NOT NULL, groups jsonb NOT NULL, diagnostics jsonb NOT NULL,
                built_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(owner_id,document_id),
                FOREIGN KEY(owner_id,document_id) REFERENCES geotool_knowledge.documents(owner_id,id) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS geotool_knowledge.kg_mentions (
                owner_id text NOT NULL, document_id text NOT NULL, id text NOT NULL,
                entity_id text NOT NULL, label text NOT NULL, kind text NOT NULL, evidence jsonb NOT NULL,
                PRIMARY KEY(owner_id,id), FOREIGN KEY(owner_id,document_id)
                REFERENCES geotool_knowledge.kg_documents(owner_id,document_id) ON DELETE CASCADE);
                CREATE INDEX IF NOT EXISTS kg_mentions_entity ON geotool_knowledge.kg_mentions(owner_id,entity_id,document_id);
                CREATE TABLE IF NOT EXISTS geotool_knowledge.kg_jobs (
                owner_id text PRIMARY KEY, status text NOT NULL, completed integer NOT NULL DEFAULT 0,
                total integer NOT NULL DEFAULT 0, failed integer NOT NULL DEFAULT 0,
                updated_at timestamptz NOT NULL DEFAULT now(), detail text NOT NULL DEFAULT '');""")
            for name in ("kg_documents", "kg_mentions", "kg_jobs"):
                # All identifiers are fixed application constants.
                db.execute(f"ALTER TABLE geotool_knowledge.{name} ENABLE ROW LEVEL SECURITY")
                db.execute(f"ALTER TABLE geotool_knowledge.{name} FORCE ROW LEVEL SECURITY")
                exists = db.execute("SELECT 1 FROM pg_policies WHERE schemaname='geotool_knowledge' AND tablename=%s AND policyname='kg_owner_scope'", (name,)).fetchone()
                if not exists:
                    db.execute(f"CREATE POLICY kg_owner_scope ON geotool_knowledge.{name} USING (owner_id=current_setting('geotool.knowledge_owner',true)) WITH CHECK (owner_id=current_setting('geotool.knowledge_owner',true))")

    def _job(self, status, completed, total, failed=0, detail=""):
        with self.index.connection() as db:
            db.execute("""INSERT INTO geotool_knowledge.kg_jobs(owner_id,status,completed,total,failed,detail)
                VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(owner_id) DO UPDATE SET status=EXCLUDED.status,
                completed=EXCLUDED.completed,total=EXCLUDED.total,failed=EXCLUDED.failed,
                detail=EXCLUDED.detail,updated_at=now()""", (self.owner,status,completed,total,failed,detail))

    def build(self):
        """One owner at a time; completed documents survive a restart/retry."""
        completed = total = failed = 0
        # A dedicated session owns this lock until completion or process death.
        with self.index.connection() as lock:
            locked = lock.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 178430902)) AS ok", (self.owner,)).fetchone()["ok"]
            if not locked:
                raise GraphBusy("Graph build is already running")
            try:
                with self.index.connection() as db:
                    docs = db.execute("SELECT id,sha256 FROM geotool_knowledge.documents WHERE owner_id=%s ORDER BY id", (self.owner,)).fetchall()
                total = len(docs)
                self._job("running", 0, total)
                for source in docs:
                    groups = sorted(set(self.organization.get(source["id"], {}).get("groups", [])))
                    with self.index.connection() as db:
                        old = db.execute("SELECT sha256,version,groups,diagnostics FROM geotool_knowledge.kg_documents WHERE owner_id=%s AND document_id=%s", (self.owner,source["id"])).fetchone()
                        if old and old["sha256"] == source["sha256"] and old["version"] == VERSION and old["groups"] == groups and not old["diagnostics"].get("error"):
                            completed += 1
                            self._job("running", completed, total, failed)
                            continue
                        doc = db.execute("SELECT id,title,source,sha256,body FROM geotool_knowledge.documents WHERE owner_id=%s AND id=%s", (self.owner,source["id"])).fetchone()
                        if doc is None:
                            completed += 1
                            continue
                        chunks = db.execute("SELECT id,document_id,start_char,end_char,body,metadata FROM geotool_knowledge.chunks_qwen3_1024 WHERE owner_id=%s AND document_id=%s ORDER BY ordinal", (self.owner,doc["id"])).fetchall()
                    try:
                        result = extract_document(doc, chunks)
                    except ValueError:
                        result = {"id":doc["id"],"sha256":doc["sha256"],"version":VERSION,"mentions":[],
                                  "diagnostics":{"error":"source_hash_mismatch","chunks":len(chunks)}}
                        failed += 1
                    with self.index.connection() as db:
                        # Recheck and lock the source before publishing an atomic document graph.
                        current = db.execute("SELECT sha256 FROM geotool_knowledge.documents WHERE owner_id=%s AND id=%s FOR SHARE", (self.owner,doc["id"])).fetchone()
                        if current and current["sha256"] == doc["sha256"]:
                            db.execute("DELETE FROM geotool_knowledge.kg_documents WHERE owner_id=%s AND document_id=%s", (self.owner,doc["id"]))
                            db.execute("INSERT INTO geotool_knowledge.kg_documents(owner_id,document_id,sha256,version,groups,diagnostics) VALUES(%s,%s,%s,%s,%s::jsonb,%s::jsonb)", (self.owner,doc["id"],doc["sha256"],VERSION,json.dumps(groups),json.dumps(result["diagnostics"])))
                            with db.cursor() as cursor:
                                cursor.executemany("INSERT INTO geotool_knowledge.kg_mentions(owner_id,document_id,id,entity_id,label,kind,evidence) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb)",
                                    [(self.owner,doc["id"],m["id"],m["entity_id"],m["label"],m["kind"],json.dumps(m,ensure_ascii=False)) for m in result["mentions"]])
                    completed += 1
                    self._job("running", completed, total, failed)
                self._job("partial" if failed else "completed", completed, total, failed)
            except Exception:
                self._job("failed", completed, total, failed, "构建中断，已完成的文献保留，可重试。")
                raise
            finally:
                lock.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 178430902))", (self.owner,))
        return self.overview()

    @staticmethod
    def _live():
        return """ FROM geotool_knowledge.kg_mentions m JOIN geotool_knowledge.kg_documents g
            ON g.owner_id=m.owner_id AND g.document_id=m.document_id
            JOIN geotool_knowledge.documents d ON d.owner_id=g.owner_id AND d.id=g.document_id
            WHERE m.owner_id=%s AND g.sha256=d.sha256 AND g.version=%s """

    def overview(self):
        with self.index.connection() as db:
            counts = db.execute("""SELECT count(*) AS documents,
                count(*) FILTER(WHERE g.sha256=d.sha256 AND g.version=%s) AS built_documents,
                count(*) FILTER(WHERE g.sha256=d.sha256 AND g.version=%s AND g.diagnostics ? 'error') AS failed_documents
                FROM geotool_knowledge.documents d LEFT JOIN geotool_knowledge.kg_documents g
                ON g.owner_id=d.owner_id AND g.document_id=d.id WHERE d.owner_id=%s""", (VERSION,VERSION,self.owner)).fetchone()
            counts.update(db.execute("SELECT count(*) AS mentions,count(DISTINCT m.entity_id) AS entities,count(DISTINCT m.document_id) AS connected_documents" + self._live(), (self.owner,VERSION)).fetchone())
            counts["missing_or_stale_documents"] = counts["documents"] - counts["built_documents"]
            groups = db.execute("""SELECT DISTINCT jsonb_array_elements_text(g.groups) AS name FROM geotool_knowledge.kg_documents g
                JOIN geotool_knowledge.documents d ON d.owner_id=g.owner_id AND d.id=g.document_id
                WHERE g.owner_id=%s AND g.sha256=d.sha256 AND g.version=%s ORDER BY name""", (self.owner,VERSION)).fetchall()
            job = db.execute("SELECT status,completed,total,failed,updated_at,detail FROM geotool_knowledge.kg_jobs WHERE owner_id=%s", (self.owner,)).fetchone()
            if job:
                job["updated_at"] = job["updated_at"].isoformat()
                if job["status"] == "running":
                    unlocked = db.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 178430902)) AS ok", (self.owner,)).fetchone()["ok"]
                    if unlocked:
                        job["status"] = "interrupted"
            return {"version":VERSION,"counts":counts,"groups":[g["name"] for g in groups],
                    "types":TYPES,"job":job,"relation":"mentions","vocabulary_size":len(ENTITIES),
                    "scope":"all_account_documents", "scientific_claims_verified":0}

    def entities(self, query="", kind="", group="", offset=0, limit=40):
        params = [self.owner,VERSION]
        where = self._live()
        if query:
            where += " AND position(lower(%s) in lower(m.label))>0"
            params.append(query)
        if kind:
            where += " AND m.kind=%s"
            params.append(kind)
        if group:
            where += " AND g.groups ? %s"
            params.append(group)
        with self.index.connection() as db:
            total = db.execute("SELECT count(DISTINCT m.entity_id) AS n" + where, params).fetchone()["n"]
            rows = db.execute("SELECT m.entity_id AS id,m.label,m.kind,count(*) AS mentions,count(DISTINCT m.document_id) AS documents" + where + " GROUP BY m.entity_id,m.label,m.kind ORDER BY documents DESC,m.label,m.entity_id LIMIT %s OFFSET %s", params + [limit,offset]).fetchall()
        return {"items":rows,"total":total,"offset":offset,"limit":limit}

    def evidence(self, entity_id, group="", offset=0, limit=20):
        params = [self.owner,VERSION,entity_id]
        where = self._live() + " AND m.entity_id=%s"
        if group:
            where += " AND g.groups ? %s"
            params.append(group)
        with self.index.connection() as db:
            total = db.execute("SELECT count(*) AS n" + where, params).fetchone()["n"]
            rows = db.execute("SELECT m.evidence,d.title,d.source,g.groups" + where + " ORDER BY d.title,m.document_id,(m.evidence->>'mention_start')::integer,m.id LIMIT %s OFFSET %s", params + [limit,offset]).fetchall()
        return {"items":[{**r["evidence"],"title":r["title"],"source":r["source"],"groups":r["groups"]} for r in rows],"total":total,"offset":offset,"limit":limit}

    def documents(self, offset=0, limit=30):
        """All documents, including those with no matches or unverified chunks."""
        with self.index.connection() as db:
            rows = db.execute("""SELECT d.id,d.title,d.sha256,g.groups,g.diagnostics,
                (g.sha256=d.sha256 AND g.version=%s) AS current,
                (SELECT count(*) FROM geotool_knowledge.kg_mentions m WHERE m.owner_id=d.owner_id AND m.document_id=d.id) AS mentions
                FROM geotool_knowledge.documents d LEFT JOIN geotool_knowledge.kg_documents g ON g.owner_id=d.owner_id AND g.document_id=d.id
                WHERE d.owner_id=%s ORDER BY d.title,d.id LIMIT %s OFFSET %s""", (VERSION,self.owner,limit,offset)).fetchall()
        for row in rows:
            if not row["current"]:
                row["mentions"] = 0
        return {"items":rows,"offset":offset,"limit":limit}

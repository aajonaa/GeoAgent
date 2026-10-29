"""Run explicitly with KG_TEST_DSN_FILE against a disposable private schema.

No production documents are inserted, edited or deleted. No model is involved.
"""
import contextlib
import json
import os
import pathlib
import unittest
import uuid

from geological_agent.rag.graph_store import GraphStore
from geological_agent.rag.knowledge_graph import digest, VERSION


class SQLProxy:
    def __init__(self, value, schema): self.value,self.schema=value,schema
    def execute(self, query, params=None, **kw): return self.value.execute(query.replace("geotool_knowledge", self.schema),params,**kw)
    def executemany(self, query, params): return self.value.executemany(query.replace("geotool_knowledge",self.schema),params)
    @contextlib.contextmanager
    def cursor(self):
        with self.value.cursor() as cursor: yield SQLProxy(cursor,self.schema)


class Index:
    def __init__(self, dsn, schema, owner):self.dsn,self.schema,self.owner_id=dsn,schema,owner
    @contextlib.contextmanager
    def connection(self):
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(self.dsn,row_factory=dict_row) as db:
            db.execute("SELECT set_config('geotool.knowledge_owner',%s,true)",(self.owner_id,))
            yield SQLProxy(db,self.schema)


class GraphPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.dsn=pathlib.Path(os.environ["KG_TEST_DSN_FILE"]).read_text().strip()
        cls.schema="kg_test_"+uuid.uuid4().hex
        with psycopg.connect(cls.dsn) as db:
            db.execute(f"CREATE SCHEMA {cls.schema}")
            db.execute(f"CREATE TABLE {cls.schema}.documents (id text PRIMARY KEY,owner_id text NOT NULL,title text,source text,sha256 text,body text,UNIQUE(owner_id,id))")
            db.execute(f"CREATE TABLE {cls.schema}.chunks_qwen3_1024 (id text PRIMARY KEY,owner_id text,document_id text,start_char integer,end_char integer,body text,metadata jsonb,ordinal integer)")
        cls.a=Index(cls.dsn,cls.schema,"owner-a");cls.b=Index(cls.dsn,cls.schema,"owner-b")
        GraphStore(cls.a).setup()

    @classmethod
    def tearDownClass(cls):
        import psycopg
        # The name was generated locally and is not supplied by a request.
        assert cls.schema.startswith("kg_test_") and cls.schema[8:].isalnum()
        with psycopg.connect(cls.dsn) as db:db.execute(f"DROP SCHEMA {cls.schema} CASCADE")

    def setUp(self):
        with self.a.connection() as db:
            db.execute("DELETE FROM geotool_knowledge.documents")
            db.execute("DELETE FROM geotool_knowledge.chunks_qwen3_1024")
            db.execute("DELETE FROM geotool_knowledge.kg_jobs")
        self.add(self.a,"doc-a","A文献","李坝金矿中未发现自然金与黄铁矿共生。")
        self.add(self.b,"doc-b","B机密文献","黄铁矿与方解石。")
        self.ga=GraphStore(self.a,{"doc-a":{"groups":["高相关"]}});self.gb=GraphStore(self.b)

    def add(self,index,identifier,title,text,chunks=True):
        with index.connection() as db:
            db.execute("INSERT INTO geotool_knowledge.documents VALUES(%s,%s,%s,%s,%s,%s)",(identifier,index.owner_id,title,"Explicit synthetic regression fixture",digest(text),text))
            if chunks:db.execute("INSERT INTO geotool_knowledge.chunks_qwen3_1024 VALUES(%s,%s,%s,0,%s,%s,%s::jsonb,1)",("K"+identifier,index.owner_id,identifier,len(text),text,json.dumps({"sources":[{"page":2}],"quality_status":"manual_review_required"})))

    def test_build_query_and_owner_isolation(self):
        a=self.ga.build();self.gb.build()
        self.assertEqual(a["counts"]["documents"],1)
        self.assertEqual(a["counts"]["built_documents"],1)
        pyrite=self.ga.entities("黄铁矿")["items"][0]
        rows=self.ga.evidence(pyrite["id"])["items"]
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]["document_id"],"doc-a")
        self.assertIn("未发现",rows[0]["text"])
        self.assertEqual(self.ga.entities("方解石")["items"],[])
        self.assertEqual(self.gb.overview()["groups"],[])
        self.assertEqual(self.ga.evidence(pyrite["id"],"低相关")["items"],[])

    def test_rebuild_idempotent(self):
        self.ga.build()
        first=self.ga.entities()
        self.ga.build()
        self.assertEqual(first,self.ga.entities())

    def test_deleted_source_cascades(self):
        self.ga.build()
        with self.a.connection() as db:db.execute("DELETE FROM geotool_knowledge.documents WHERE owner_id=%s",("owner-a",))
        self.assertEqual(self.ga.entities()["total"],0)
        self.assertEqual(self.ga.overview()["counts"]["documents"],0)

    def test_changed_source_hides_stale_evidence(self):
        self.ga.build()
        with self.a.connection() as db:db.execute("UPDATE geotool_knowledge.documents SET sha256=%s WHERE owner_id=%s",(digest("改动"),"owner-a"))
        self.assertEqual(self.ga.entities()["total"],0)
        self.assertEqual(self.ga.overview()["counts"]["missing_or_stale_documents"],1)

    def test_corrupt_source_recorded_without_false_pass(self):
        with self.a.connection() as db:db.execute("UPDATE geotool_knowledge.documents SET sha256='bad' WHERE owner_id=%s",("owner-a",))
        result=self.ga.build()
        self.assertEqual(result["job"]["status"],"partial")
        self.assertEqual(result["counts"]["failed_documents"],1)
        self.assertEqual(result["counts"]["entities"],0)

    def test_empty_and_unmatched_documents_in_coverage(self):
        self.add(self.a,"doc-none","没有术语","原始资料未涉及受控术语。",False)
        self.ga.build()
        rows=self.ga.documents()["items"]
        self.assertEqual(len(rows),2)
        self.assertEqual(next(r for r in rows if r["id"]=="doc-none")["mentions"],0)
        self.assertEqual(self.ga.overview()["counts"]["built_documents"],2)

    def test_classification_changes_rebuild(self):
        self.ga.build();self.ga.organization["doc-a"]["groups"]=["中相关"]
        self.ga.build()
        self.assertEqual(self.ga.overview()["groups"],["中相关"])

    def test_pagination_and_literal_query(self):
        self.ga.build()
        first=self.ga.entities(limit=1)
        second=self.ga.entities(offset=1,limit=1)
        self.assertNotEqual(first["items"][0]["id"],second["items"][0]["id"])
        self.assertEqual(self.ga.entities("%';DROP TABLE")["total"],0)

    def test_migration_is_idempotent_and_rls_policies_present(self):
        self.ga.setup()
        with self.a.connection() as db:
            rows=db.execute("SELECT tablename,qual,with_check FROM pg_policies WHERE schemaname='geotool_knowledge'").fetchall()
        self.assertEqual(len(rows),3)
        self.assertTrue(all("geotool.knowledge_owner" in r["qual"] and "geotool.knowledge_owner" in r["with_check"] for r in rows))

    def test_authenticated_api_rejects_other_owner_and_bad_pagination(self):
        from unittest.mock import patch
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient
        from geological_agent.team.knowledge_graph import install_graph_routes
        self.ga.build();self.gb.build()
        app=FastAPI()
        def auth(request,mutate=False):
            owner=request.headers.get("x-test-owner")
            if owner not in ("owner-a","owner-b"):raise HTTPException(401)
            if mutate and request.headers.get("x-test-csrf")!="verified":raise HTTPException(403)
            return {"id":owner}
        with patch("geological_agent.team.knowledge_graph.configured_index",side_effect=lambda owner:Index(self.dsn,self.schema,owner)):
            install_graph_routes(app,auth)
            with TestClient(app) as client:
                self.assertEqual(client.get('/api/knowledge-graph').status_code,401)
                headers={"x-test-owner":"owner-a"}
                self.assertEqual(client.post('/api/knowledge-graph/build',headers=headers).status_code,403)
                self.assertEqual(client.get('/api/knowledge-graph/entities?limit=10000',headers=headers).status_code,400)
                self.assertEqual(client.get('/api/knowledge-graph/entities?offset=-1',headers=headers).status_code,400)
                self.assertEqual(client.get('/api/knowledge-graph/entities?q=方解石&owner_id=owner-b',headers=headers).json()['total'],0)
                self.assertEqual(client.get('/api/knowledge-graph/documents',headers=headers).json()['items'][0]['id'],'doc-a')


if __name__=="__main__":unittest.main()

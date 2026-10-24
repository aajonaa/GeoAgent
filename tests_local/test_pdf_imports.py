"""PDF import contract tests. All parser/index outputs here are synthetic."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

MODULE=Path(__file__).resolve().parents[1]/"geological_agent"/"team"/"pdf_imports.py"
spec=importlib.util.spec_from_file_location("pdf_imports_under_test",MODULE)
pdf=importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)

BODY=b"%PDF-1.4\nsynthetic-unit-fixture-not-for-real-parsing\n"
TEXT="# Synthetic fixture\n\nLeft column evidence. Right column evidence.\n"

class Parser:
    def __init__(self):
        self.calls=[]
        self.uploaded=None
        self.status="completed"
        self.reuse=False
        self.bad_identity=False
        self.upload_size=None
        self.upload_sha=None
        self.outputs={
            "markdown":TEXT.encode(),
            "middle_json":json.dumps({"pdf_info":[{"page_idx":0}]}).encode(),
            "structured_content":b"[]",
            "zip":b"synthetic-test-placeholder",
        }
    def json(self,method,path,payload=None):
        self.calls.append((method,path,payload))
        if method=="POST" and path=="/v1/uploads":
            self.upload_size=payload["bytes"]
            self.upload_sha=payload["sha256sum"]
            return {"id":"upload_test","bytes":self.upload_size,
                    "sha256sum":self.upload_sha if not self.bad_identity else "0"*64,
                    "status":"completed" if self.reuse else "pending",
                    "file":{"id":"file_test","bytes":self.upload_size,"sha256sum":self.upload_sha} if self.reuse else None}
        if path.endswith("/complete"):
            return {"status":"completed","bytes":self.upload_size,"sha256sum":self.upload_sha,
                    "file":{"id":"file_test","bytes":self.upload_size,"sha256sum":self.upload_sha}}
        if method=="POST" and path=="/v1/parse/jobs":
            return {"job_id":"job_test"}
        if method=="GET":
            return {"status":self.status,"progress":{"completed":1,"total":1,"failed":0},
                    "files":[{"status":"completed","parse":{"model_used":"synthetic","parser_version":"test"},
                              "output_files":{k:{"file_id":k,"bytes":len(v)} for k,v in self.outputs.items()}}]}
        raise AssertionError((method,path))
    def upload(self,upload_id,path):
        self.uploaded=path.read_bytes()
    def download(self,file_id,target,expected_size):
        assert len(self.outputs[file_id])==expected_size
        target.write_bytes(self.outputs[file_id])

class Index:
    def __init__(self):
        self.calls=[]
        self.chunks=2
    def ingest(self,title,text,source):
        self.calls.append((title,text,source))
        return {"id":"document_test","chunks":self.chunks,"reused":len(self.calls)>1}

class PdfTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.parser=Parser()
        self.index=Index()
        self.app=FastAPI()
        self.app.state.store=SimpleNamespace(root=self.root)
        def auth(request,mutate=False):
            if request.headers.get("x-test-user") not in {"alice","bob"}:
                raise HTTPException(401,"Sign in")
            if mutate and request.headers.get("x-csrf-token")!="test-csrf":
                raise HTTPException(403,"CSRF")
            return {"id":request.headers["x-test-user"]}
        async def body(request):
            return await request.json()
        self.imports=pdf.install_pdf_routes(self.app,auth,body,lambda user:self.index)
        self.imports.client=lambda:self.parser
        self.client=TestClient(self.app)
        self.headers={"x-test-user":"alice","x-csrf-token":"test-csrf"}

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def create(self):
        r=self.client.post("/api/knowledge/pdf/jobs",headers=self.headers,
                           json={"filename":"synthetic.pdf","title":"Synthetic test only","bytes":len(BODY)})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()
    def upload(self):
        job=self.create()
        r=self.client.put("/api/knowledge/pdf/jobs/"+job["id"]+"/file",
                          headers={**self.headers,"x-pdf-upload-token":job["upload_token"]},content=BODY)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["state"],"queued")
        return job
    def parsed(self):
        job=self.upload()
        r=self.client.get("/api/knowledge/pdf/jobs/"+job["id"],headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["state"],"parsed")
        return job

    def test_create_requires_login_and_csrf(self):
        for headers,status in [({},401),({"x-test-user":"alice"},403)]:
            self.assertEqual(self.client.post("/api/knowledge/pdf/jobs",headers=headers,json={}).status_code,status)

    def test_owner_isolation_and_secret_fields(self):
        job=self.create()
        r=self.client.get("/api/knowledge/pdf/jobs",headers=self.headers)
        self.assertNotIn("upload_token",r.text)
        self.assertNotIn("upload_token_hash",r.text)
        self.assertNotIn('"owner"',r.text)
        for suffix in ["","/preview","/artifacts/original"]:
            r=self.client.get("/api/knowledge/pdf/jobs/"+job["id"]+suffix,headers={"x-test-user":"bob"})
            self.assertEqual(r.status_code,404)
        self.assertEqual(self.client.get("/api/knowledge/pdf/jobs",headers={"x-test-user":"bob"}).json()["jobs"],[])

    def test_upload_token_and_duplicate_submission(self):
        job=self.create()
        url="/api/knowledge/pdf/jobs/"+job["id"]+"/file"
        self.assertEqual(self.client.put(url,headers=self.headers,content=BODY).status_code,403)
        headers={**self.headers,"x-pdf-upload-token":job["upload_token"]}
        self.assertEqual(self.client.put(url,headers=headers,content=BODY).status_code,200)
        self.assertEqual(self.client.put(url,headers=headers,content=BODY).status_code,409)
        self.assertEqual(sum(m=="POST" and p=="/v1/parse/jobs" for m,p,_ in self.parser.calls),1)
        self.assertEqual(self.parser.uploaded,BODY)

    def test_bad_header_never_submitted(self):
        job=self.create()
        r=self.client.put("/api/knowledge/pdf/jobs/"+job["id"]+"/file",
                          headers={**self.headers,"x-pdf-upload-token":job["upload_token"]},
                          content=b"x"*len(BODY))
        self.assertEqual(r.status_code,400)
        self.assertEqual(self.parser.calls,[])

    def test_declared_size_and_filename_constraints(self):
        for changes in [{"bytes":True},{"bytes":0},{"bytes":pdf.MAX_PDF+1},
                        {"filename":"../secret.pdf"},{"filename":"test.txt"}]:
            with self.subTest(changes=changes):
                payload={"title":"Synthetic","filename":"test.pdf","bytes":len(BODY),**changes}
                self.assertEqual(self.client.post("/api/knowledge/pdf/jobs",headers=self.headers,json=payload).status_code,400)

    def test_preview_original_hash_and_no_automatic_indexing(self):
        job=self.parsed()
        prefix="/api/knowledge/pdf/jobs/"+job["id"]
        r=self.client.get(prefix+"/preview",headers=self.headers)
        self.assertEqual(r.json()["text"],TEXT)
        self.assertFalse(r.json()["preview_truncated"])
        self.assertEqual(r.json()["job"]["text_sha256"],hashlib.sha256(TEXT.encode()).hexdigest())
        self.assertEqual(r.json()["job"]["pages"],1)
        self.assertEqual(self.index.calls,[])
        file=self.client.get(prefix+"/artifacts/original",headers=self.headers)
        self.assertEqual(file.content,BODY)
        self.assertEqual(file.headers["x-content-type-options"],"nosniff")
        self.assertIn("attachment",file.headers["content-disposition"])

    def test_explicit_confirm_and_duplicate_index(self):
        job=self.parsed()
        url="/api/knowledge/pdf/jobs/"+job["id"]+"/ingest"
        self.assertEqual(self.client.post(url,headers=self.headers,json={}).status_code,400)
        a=self.client.post(url,headers=self.headers,json={"confirmed":True})
        self.assertEqual(a.json()["state"],"indexed")
        b=self.client.post(url,headers=self.headers,json={"confirmed":True})
        self.assertEqual(b.json()["state"],"indexed")
        self.assertEqual(len(self.index.calls),1)
        self.assertEqual(self.index.calls[0][1],TEXT)
        self.assertIn(hashlib.sha256(BODY).hexdigest(),self.index.calls[0][2])

    def test_changed_text_refuses_index(self):
        job=self.parsed()
        (self.imports.folder(job["id"])/"parsed.md").write_text("tampered",encoding="utf-8")
        r=self.client.post("/api/knowledge/pdf/jobs/"+job["id"]+"/ingest",
                           headers=self.headers,json={"confirmed":True})
        self.assertEqual(r.json()["state"],"parsed")
        self.assertTrue(r.json()["error"])
        self.assertEqual(self.index.calls,[])

    def test_zero_chunk_result_not_claimed_indexed(self):
        job=self.parsed()
        self.index.chunks=0
        r=self.client.post("/api/knowledge/pdf/jobs/"+job["id"]+"/ingest",
                           headers=self.headers,json={"confirmed":True})
        self.assertEqual(r.json()["state"],"parsed")
        self.assertTrue(r.json()["error"])

    def test_oversize_preview_preserves_complete_source(self):
        self.parser.outputs["markdown"]=("X"*(pdf.MAX_PREVIEW+1)).encode()
        job=self.parsed()
        prefix="/api/knowledge/pdf/jobs/"+job["id"]
        preview=self.client.get(prefix+"/preview",headers=self.headers).json()
        self.assertTrue(preview["preview_truncated"])
        self.assertEqual(preview["total_characters"],pdf.MAX_PREVIEW+1)
        self.assertFalse(preview["job"]["can_index"])
        self.assertEqual(len(self.client.get(prefix+"/artifacts/markdown",headers=self.headers).content),pdf.MAX_PREVIEW+1)
        self.assertEqual(self.client.post(prefix+"/ingest",headers=self.headers,json={"confirmed":True}).status_code,409)

    def test_partial_parser_result_not_indexed(self):
        job=self.upload()
        self.parser.status="partial"
        r=self.client.get("/api/knowledge/pdf/jobs/"+job["id"],headers=self.headers)
        self.assertEqual(r.json()["state"],"failed")
        self.assertEqual(self.index.calls,[])

    def test_restart_recovery_does_not_repeat_gpu_submission(self):
        saved=[]
        states={"receiving":"failed","submitting":"submission_unknown","indexing":"parsed",
                "queued":"queued","parsing":"parsing","fetching":"fetching","parsed":"parsed","indexed":"indexed"}
        for state in states:
            public=self.create()
            job=self.imports.get("alice",public["id"])
            job["state"]=state
            self.imports.save(job)
            saved.append((job["id"],states[state],state))
        restarted=pdf.PdfImports(self.root)
        actual={job["id"]:job for job in restarted.listing("alice")}
        for id,expected,old in saved:
            self.assertEqual(actual[id]["state"],expected)
            if old in {"receiving","submitting","indexing"}:
                self.assertTrue(actual[id]["error"])
                self.assertIn("recovered_at",actual[id])
        self.assertEqual(self.parser.calls,[])

    def test_restart_preserves_remote_job_and_parsed_evidence(self):
        job=self.parsed()
        stored=self.imports.get("alice",job["id"])
        stored["state"]="submitting"
        self.imports.save(stored)
        before=(self.imports.folder(job["id"])/"parsed.md").read_bytes()
        restarted=pdf.PdfImports(self.root)
        restored=restarted.get("alice",job["id"])
        self.assertEqual(restored["state"],"queued")
        self.assertEqual(restored["remote_job"],"job_test")
        self.assertEqual((restarted.folder(job["id"])/"parsed.md").read_bytes(),before)


    def test_completed_upload_reused_without_put(self):
        self.parser.reuse=True
        job=self.upload()
        self.assertIsNone(self.parser.uploaded)
        self.assertFalse(any(path.endswith("/complete") for _,path,_ in self.parser.calls))
        self.assertTrue(self.imports.get("alice",job["id"])["upload_reused"])
        self.assertEqual(sum(m=="POST" and p=="/v1/parse/jobs" for m,p,_ in self.parser.calls),1)

    def test_mismatched_completed_upload_not_submitted(self):
        self.parser.reuse=True
        self.parser.bad_identity=True
        job=self.create()
        result=self.client.put("/api/knowledge/pdf/jobs/"+job["id"]+"/file",
                               headers={**self.headers,"x-pdf-upload-token":job["upload_token"]},content=BODY)
        self.assertEqual(result.json()["state"],"submission_unknown")
        self.assertIsNone(self.parser.uploaded)
        self.assertFalse(any(path=="/v1/parse/jobs" for _,path,_ in self.parser.calls))

    def test_completed_file_hash_is_checked_independently(self):
        original=self.parser.json
        def corrupt(method,path,payload=None):
            result=original(method,path,payload)
            if path.endswith("/complete"):
                result["file"]["sha256sum"]="0"*64
            return result
        self.parser.json=corrupt
        job=self.create()
        result=self.client.put("/api/knowledge/pdf/jobs/"+job["id"]+"/file",
                               headers={**self.headers,"x-pdf-upload-token":job["upload_token"]},content=BODY)
        self.assertEqual(result.json()["state"],"submission_unknown")
        self.assertFalse(any(path=="/v1/parse/jobs" for _,path,_ in self.parser.calls))

    def test_advanced_tier_matches_advertised_service(self):
        self.upload()
        calls = [payload for method, path, payload in self.parser.calls
                 if method == "POST" and path == "/v1/parse/jobs"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["tier"], "advanced")
        self.assertEqual(self.imports.capabilities()["tier"], "advanced")
        self.assertEqual(calls[0]["ocr_mode"], "auto")
        self.assertEqual(self.index.calls, [])

    def test_invalid_parser_destination_rejected(self):
        for url in ["https://example.com","http://127.0.0.1:50016/path",
                    "http://user:pass@127.0.0.1:50016","http://0.0.0.0:50016"]:
            with self.subTest(url=url), self.assertRaises(pdf.ParserError):
                pdf.ParserClient({"url":url,"key_file":str(self.root/"not-used")})

if __name__=="__main__":
    unittest.main(verbosity=2)

"""Account-scoped structured PDF inspection and explicitly confirmed ingestion."""
import hashlib
import json
import time
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from ..rag.literature import document, split, digest, LiteratureError, POLICY
from .pdf_content import load_content
from .pdf_quality import enforce_page_quality
from .pdf_partial import apply_partial_context, annotate_partial_chunks


def prepare(imports, owner, job_id, *, with_chunks=True):
    job = imports.get(owner, job_id)
    folder = imports.folder(job_id)
    enforce_page_quality(job, folder)
    if "structured_content" not in job.get("artifacts", []):
        raise LiteratureError("Structured parser output is not available; original retained")
    original = hashlib.sha256()
    with (folder/"source.pdf").open("rb") as stream:
        for value in iter(lambda: stream.read(1024*1024), b""):
            original.update(value)
    if original.hexdigest() != job.get("sha256"):
        raise LiteratureError("Original PDF hash mismatch")
    _, content_record, _ = load_content(folder, job)
    raw = (folder/"structure.json").read_bytes()
    if len(raw) > 100*1024*1024 or digest(raw) != content_record["structure_sha256"]:
        raise LiteratureError("Structured source hash mismatch")
    structured = json.loads(raw)
    quality_record = enforce_page_quality(job, folder, structure_sha256=digest(raw),
        structured_recovery=isinstance(structured, dict) and bool(structured.get("extensions", {}).get("source_bound_recovery")))
    doc = document(structured, title=job["title"], original_sha256=job["sha256"],
                   raw_sha256=job["text_sha256"], parser=job.get("parser"), page_count=job.get("pages"))
    coverage = apply_partial_context(doc, quality_record)
    package = {"document": doc, "chunks": [], "can_index": doc["quality_status"] != "blocked",
               "assets": content_record["assets"], "policy": POLICY}
    if with_chunks and package["can_index"]:
        try:
            package["chunks"] = split(doc)
        except LiteratureError as exc:
            package["can_index"] = False
            doc["quality_status"] = "blocked"
            doc["issues"].append({"severity":"error","code":"chunk_contract","message":str(exc)})
    if coverage:
        annotate_partial_chunks(doc, package["chunks"], coverage)
        package["coverage"] = coverage
    basis = {"sha":doc["sha256"],"structure":doc["structure_sha256"],
        "raw":doc["raw_sha256"],"policy":POLICY,"title":doc["title"],
        "tokenizer":package["chunks"][0]["metadata"]["tokenizer_sha256"] if package["chunks"] else None}
    if coverage:
        basis["coverage"] = coverage
        basis["quality_record"] = job["page_quality"]["sha256"]
    if doc.get("segmentation"):
        basis["segmentation"] = doc["segmentation"]
    package["blocking_issues"] = [issue for issue in doc["issues"] if issue.get("severity") == "error"]
    package["recovery"] = {"stage": "index_preparation", "reuse_parser_output": True,
        "retry_parser": False, "action": "inspect_blocking_issues" if package["blocking_issues"] else "ready"}
    package["basis"] = digest(json.dumps(basis, sort_keys=True))
    return package


def ingest(imports, owner, job_id, factory, basis):
    with imports.lock(job_id):
        job = imports.get(owner, job_id)
        enforce_page_quality(job, imports.folder(job_id))
        if job["state"] not in {"parsed", "indexed", "partially_indexed"}:
            raise HTTPException(409,"Wait for parsing/indexing to finish")
        package = prepare(imports, owner, job_id)
        if not package["can_index"] or package["basis"] != basis:
            raise HTTPException(409,"Quality checks failed or the preview changed; inspect the structured preview again")
        previous_state = job["state"]
        previous = {"index":job.get("index"),"text_sha256":job.get("index_text_sha256") or job.get("text_sha256")}
        job.update(state="indexing",error="")
        imports.save(job)
        try:
            source = job["source"]+"; PDF SHA256="+job["sha256"]+"; structured MinerU; filename="+job["filename"]
            result = factory({"id":owner}).ingest_literature(package,source)
            if not result.get("chunks"):
                raise LiteratureError("No indexed chunks returned")
            if previous["index"] and previous["index"].get("id") != result["id"]:
                history = job.setdefault("index_history",[])
                if previous not in history:
                    history.append(previous)
            coverage = package.get("coverage")
            if coverage:
                result = {**result, "coverage": coverage}
            job.update(state="partially_indexed" if coverage else "indexed",index=result,index_text_sha256=package["document"]["sha256"],
                       literature_basis=package["basis"],literature_policy=POLICY,
                       reviewed_at=time.time(),error="")
            if result.get("segmentation"):
                job["index_note"] = "Full structured source indexed in bounded page segments; original PDF and exact source locations retained."
            if coverage:
                job["index_note"] = "Partial publication: "+str(len(coverage["included_section_pages"]))+"/"+str(coverage["source_pages"])+" source pages released; original PDF page(s) "+", ".join(map(str,coverage["excluded_original_pdf_pages"]))+" retained pending review. Not complete."
        except Exception:
            job.update(state=previous_state,error="Structured indexing failed; original and previous index retained. Refresh before retrying.")
            imports.save(job)
            raise
        imports.save(job)
        return imports.public(job)


def install_literature_routes(app,auth,body,imports,index):
    async def perform(fn,*args):
        from ..rag.store import KnowledgeError
        try:
            return await run_in_threadpool(fn,*args)
        except HTTPException:
            raise
        except (LiteratureError,ValueError) as exc:
            raise HTTPException(409,str(exc)) from None
        except (OSError,KeyError,KnowledgeError):
            raise HTTPException(503,"Structured literature service unavailable; original and existing indexes retained") from None

    @app.get("/api/knowledge/pdf/jobs/{job_id}/literature")
    async def view(job_id:str,request:Request):
        return await perform(prepare,imports,auth(request)["id"],job_id)

    @app.post("/api/knowledge/pdf/jobs/{job_id}/literature/ingest")
    async def confirm(job_id:str,request:Request):
        user=auth(request,mutate=True)
        payload=await body(request)
        if payload.get("confirmed") is not True or not isinstance(payload.get("basis"),str):
            raise HTTPException(400,"Explicit review confirmation and preview version are required")
        return await perform(ingest,imports,user["id"],job_id,index,payload["basis"])


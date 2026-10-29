from fastapi import HTTPException, Request
from .pdf_imports import install_pdf_routes
from .pdf_reader import install_reader_routes, document_source
from .literature import install_literature_routes
from starlette.concurrency import run_in_threadpool
from ..rag.store import configured_index, KnowledgeError
from ..rag.profile import retrieval_profile
from .knowledge_catalog import install_catalog_routes

def install_knowledge_routes(app,auth,body):
    def index(user):
        try: value=configured_index(user["id"])
        except KnowledgeError: raise HTTPException(503,"Knowledge service configuration unavailable") from None
        if value is None: raise HTTPException(503,"Knowledge retrieval is not enabled in this deployment")
        return value
    async def perform(fn,*args):
        try: return await run_in_threadpool(fn,*args)
        except ValueError as exc: raise HTTPException(400,str(exc)) from None
        except KnowledgeError as exc: raise HTTPException(503,str(exc)) from None
    imports=install_pdf_routes(app,auth,body,index)
    install_reader_routes(app,auth,imports)
    install_literature_routes(app,auth,body,imports,index)
    organization=install_catalog_routes(app,auth)
    @app.get("/api/knowledge")
    async def listing(request: Request):
        user=auth(request)
        return {"documents":await perform(index(user).documents),
                "formats":["text","markdown","pdf"],"pdf_service":imports.capabilities(),"max_characters":120000,
                "organization":await perform(organization.listing,user["id"]),
                "retrieval":"Qwen3 1024d + PostgreSQL lexical / RRF / Qwen3 Reranker",
                "retrieval_profile":retrieval_profile(),
                "privacy":"Account-scoped; selected excerpts go to your selected LLM and research-group traces."}
    @app.post("/api/knowledge")
    async def ingest(request: Request):
        user=auth(request,mutate=True); p=await body(request)
        return await perform(index(user).ingest,p.get("title"),p.get("text"),p.get("source","User supplied text"))
    @app.post("/api/knowledge/search")
    async def search(request: Request):
        user=auth(request,mutate=True); p=await body(request)
        return await perform(index(user).retrieve,p.get("query"))
    @app.get("/api/knowledge/{document_id}")
    async def document(document_id:str,request:Request):
        user=auth(request); row=await perform(index(user).document,document_id)
        if row is None: raise HTTPException(404,"Document not found")
        return {**row,"pdf_source":await perform(document_source,imports,user["id"],document_id,row.get("sha256"))}
    @app.delete("/api/knowledge/{document_id}")
    async def delete(document_id:str,request:Request):
        user=auth(request,mutate=True)
        if not await perform(index(user).delete,document_id): raise HTTPException(404,"Document not found")
        imports.unlink_document(user["id"],document_id)
        return {"deleted":True}

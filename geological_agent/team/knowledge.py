from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from ..rag.store import configured_index, KnowledgeError

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
    @app.get("/api/knowledge")
    async def listing(request: Request):
        user=auth(request)
        return {"documents":await perform(index(user).documents),
                "formats":["text","markdown"],"max_characters":120000,
                "retrieval":"PostgreSQL dense + lexical / RRF / multilingual cross-encoder",
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
        return row
    @app.delete("/api/knowledge/{document_id}")
    async def delete(document_id:str,request:Request):
        user=auth(request,mutate=True)
        if not await perform(index(user).delete,document_id): raise HTTPException(404,"Document not found")
        return {"deleted":True}

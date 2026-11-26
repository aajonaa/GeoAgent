"""Authenticated knowledge graph routes; no model or embedding calls."""
import logging
import threading
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from ..rag.graph_store import GraphStore, GraphBusy
from ..rag.store import configured_index, KnowledgeError

LOG = logging.getLogger(__name__)


def install_graph_routes(app, auth):
    ready = False
    setup_lock = threading.Lock()
    workers = {}
    workers_lock = threading.Lock()

    def service(owner):
        nonlocal ready
        index = configured_index(owner)
        if index is None:
            raise KnowledgeError("Knowledge storage is not configured")
        catalog = getattr(app.state, "knowledge_catalog", None)
        organization = catalog.listing(owner).get("documents", {}) if catalog else {}
        graph = GraphStore(index, organization)
        with setup_lock:
            if not ready:
                graph.setup()
                ready = True
        return graph

    async def invoke(owner, method, *args):
        def call():
            return getattr(service(owner), method)(*args)
        try:
            return await run_in_threadpool(call)
        except KnowledgeError:
            raise HTTPException(503, "图谱存储暂不可用，原有知识资料不受影响。") from None

    def bounds(request, default):
        try:
            offset = int(request.query_params.get("offset", "0"))
            limit = int(request.query_params.get("limit", str(default)))
        except ValueError:
            raise HTTPException(400, "分页参数必须为整数。") from None
        if offset < 0 or offset > 1000000 or not 1 <= limit <= 100:
            raise HTTPException(400, "分页参数超出范围。")
        return offset, limit

    @app.get("/api/knowledge-graph")
    async def overview(request: Request):
        user = auth(request)
        return await invoke(user["id"], "overview")

    @app.post("/api/knowledge-graph/build", status_code=202)
    async def build(request: Request):
        user = auth(request, mutate=True)
        owner = user["id"]
        # Configuration and migration failures are returned before accepting work.
        try:
            graph = await run_in_threadpool(service, owner)
        except KnowledgeError:
            raise HTTPException(503, "图谱存储暂不可用。") from None

        def work():
            try:
                graph.build()
            except GraphBusy:
                pass
            except Exception:
                LOG.exception("Knowledge graph build failed")
            finally:
                with workers_lock:
                    workers.pop(owner, None)

        with workers_lock:
            existing = workers.get(owner)
            if existing and existing.is_alive():
                return {"accepted":True,"already_running":True}
            thread = threading.Thread(target=work, name="knowledge-graph-build", daemon=True)
            workers[owner] = thread
            thread.start()
        return {"accepted":True,"already_running":False}

    @app.get("/api/knowledge-graph/entities")
    async def entities(request: Request):
        user = auth(request)
        query = request.query_params.get("q", "").strip()
        kind, group = request.query_params.get("kind", ""), request.query_params.get("group", "")
        if len(query) > 200 or len(kind) > 40 or len(group) > 200:
            raise HTTPException(400, "筛选条件过长。")
        return await invoke(user["id"], "entities", query, kind, group, *bounds(request,40))

    @app.get("/api/knowledge-graph/entities/{entity_id}")
    async def evidence(entity_id: str, request: Request):
        user = auth(request)
        group = request.query_params.get("group", "")
        if len(entity_id) != 24 or any(c not in "0123456789abcdef" for c in entity_id) or len(group) > 200:
            raise HTTPException(404, "图谱实体不存在。")
        return await invoke(user["id"], "evidence", entity_id, group, *bounds(request,20))

    @app.get("/api/knowledge-graph/documents")
    async def documents(request: Request):
        user = auth(request)
        return await invoke(user["id"], "documents", *bounds(request,30))

    @app.get("/knowledge-graph-assets/{name}")
    async def asset(name: str):
        if name not in ("knowledge-graph.js", "knowledge-graph.css"):
            raise HTTPException(404)
        return FileResponse(Path(__file__).with_name("web") / name)

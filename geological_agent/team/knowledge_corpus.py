"""Paginated account-scoped access to source-bound large literature collections."""
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool
from ..rag.corpus import Corpus, enabled
from ..rag.corpus_text import load_record
from ..rag.store import configured_index, KnowledgeError
import json


def install_corpus_routes(app, auth):
    def corpus(request):
        user = auth(request)
        if not enabled():
            raise HTTPException(503, 'Large corpus is not enabled')
        index = configured_index(user['id'])
        if index is None:
            raise HTTPException(503, 'Knowledge service is not enabled')
        return Corpus(index)

    async def perform(fn, **kwargs):
        try:
            return await run_in_threadpool(fn, **kwargs)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except KnowledgeError:
            raise HTTPException(503, 'Knowledge database temporarily unavailable') from None

    @app.get('/api/knowledge-corpus')
    async def overview(request: Request):
        return await perform(corpus(request).overview)

    @app.get('/api/knowledge-corpus/papers')
    async def listing(request: Request, q: str = '', category: str = '', state: str = '',
                      collection: str = '', after: str = '', limit: int = 50):
        return await perform(corpus(request).listing, q=q, category=category, state=state,
                             collection=collection, after=after, limit=limit)

    @app.get('/api/knowledge-corpus/papers/{document_id}')
    async def document(document_id: str, request: Request, start: int = 0):
        value = await perform(corpus(request).document, doc=document_id, start=start)
        if value is None:
            raise HTTPException(404, 'Document not found')
        return value

    @app.get('/api/knowledge-corpus/papers/{document_id}/source')
    async def original(document_id: str, request: Request):
        instance = corpus(request)
        row = await run_in_threadpool(instance.row, document_id)
        if row is None:
            raise HTTPException(404, 'Document not found')
        # Validate the exact archived bytes, including the newline, before serving.
        await run_in_threadpool(load_record, row['root'], row['record_path'], row['record_offset'],
                                row['record_length'], row['record_sha'])
        def read():
            with (Path(row['root']) / row['record_path']).open('rb') as stream:
                stream.seek(row['record_offset'])
                raw = stream.read(row['record_length'])
            import hashlib
            if hashlib.sha256(raw).hexdigest() != row['record_sha']:
                raise ValueError('Source changed during reading')
            return raw
        raw = await run_in_threadpool(read)
        return Response(raw, media_type='application/x-ndjson', headers={
            'Content-Disposition': f'attachment; filename="{document_id}.jsonl"',
            'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})

    @app.get('/knowledge-corpus-assets/{name}')
    async def asset(name: str):
        if name not in ('knowledge-corpus.js', 'knowledge-corpus.css'):
            raise HTTPException(404)
        return FileResponse(Path(__file__).parent / 'web' / name, headers={'Cache-Control': 'no-cache'})

from fastapi import Request, HTTPException
from starlette.concurrency import run_in_threadpool
from ..rag.store import configured_index, KnowledgeError
from ..rag.shared import sources, SharedIndex, SharedCorpus


def install_shared_routes(app, auth, body, audit):
    def index(user, source):
        rows=sources()
        if not 0<=source<len(rows):raise HTTPException(404,'Shared source not found')
        base=configured_index(user['id'])
        if base is None:raise HTTPException(503,'Knowledge service unavailable')
        return SharedIndex(base,rows[source])

    async def work(fn,*args,**kwargs):
        try:return await run_in_threadpool(fn,*args,**kwargs)
        except KnowledgeError:raise HTTPException(503,'Shared knowledge temporarily unavailable') from None
        except ValueError:raise HTTPException(400,'Invalid shared knowledge request') from None

    @app.get('/api/shared-knowledge')
    async def listing(request:Request,source:int=0,kind:str='documents',q:str='',offset:int=0,limit:int=50):
        user=auth(request)
        if kind not in ('documents','corpus') or len(q)>200 or not 0<=offset<=1000000 or not 1<=limit<=100:
            raise HTTPException(400,'Invalid paging or search')
        instance=index(user,source)
        result=await work(instance.listing if kind=='documents' else SharedCorpus(instance).listing,q=q,offset=offset,limit=limit)
        return {**result,'scope':'shared','read_only':True,'kind':kind,
            'sources':[{'id':i,'name':s.get('name','研究组公共资料'),'published_documents':len(s['document_ids']),
                'published_collections':len(s['collection_ids']),'published_at':s.get('published_at')} for i,s in enumerate(sources())]}

    @app.get('/api/shared-knowledge/{doc}')
    async def preview(doc:str,request:Request,source:int=0,kind:str='documents',start:int=0,chunk_offset:int=0):
        user=auth(request)
        if kind not in ('documents','corpus') or not 0<=start<=20000000 or not 0<=chunk_offset<=1000000 or len(doc)!=32:
            raise HTTPException(400,'Invalid preview request')
        instance=index(user,source)
        row=await work(instance.preview,doc,start,chunk_offset) if kind=='documents' else await work(SharedCorpus(instance).document,doc,start=start)
        if row is None:raise HTTPException(404,'Shared document not found')
        # A read grant never exposes filesystem roots, job IDs or DB credentials.
        allowed={'id','title','sha256','body','total_characters','start_char','end_char','next_start','chunks_detail','next_chunk_offset','index_state','chunks','year','l1_labels','l2_labels'}
        return {k:v for k,v in row.items() if k in allowed}|{'scope':'shared','read_only':True}

    @app.post('/api/shared-knowledge/search')
    async def search(request:Request):
        user=auth(request,mutate=True);data=await body(request)
        if set(data)!={'query'}:raise HTTPException(400,'Only query is accepted')
        base=configured_index(user['id'])
        if base is None:raise HTTPException(503,'Knowledge service unavailable')
        from ..rag.shared import merge_retrieval
        result=await work(merge_retrieval,base,data['query'],4,{'status':'empty','references':[],'candidates':[]})
        audit.record(user['id'],'knowledge_search',query=data['query'],status=result.get('status'),
            references=result.get('references',[]),candidates=len(result.get('candidates',[])),source='shared_browser',duration_ms=result.get('duration_ms'))
        return result

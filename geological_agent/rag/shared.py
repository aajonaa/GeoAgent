"""Explicit curated read grants. Personal uploads never become shared implicitly."""
from pathlib import Path
import json, os, re, threading, time
from .store import KnowledgeIndex, KnowledgeError, COMPATIBLE_KEYS
from .corpus import Corpus

_lock = threading.RLock()
_cached = None


def sources():
    global _cached
    name = os.environ.get('GEOTOOL_SHARED_KNOWLEDGE_FILE')
    if not name:
        return []
    path = Path(name)
    try:
        stamp = (str(path), path.stat().st_mtime_ns)
        with _lock:
            if _cached and _cached[0] == stamp:
                return _cached[1]
            data = json.loads(path.read_text(encoding='utf-8'))
            assert data['version'] == 1 and len(data['sources']) <= 8
            for row in data['sources']:
                assert re.fullmatch('[a-f0-9]{32}', row['owner_id'])
                assert all(re.fullmatch('[a-f0-9]{32}', n) for n in row['document_ids'])
                assert all(isinstance(n,str) and 0<len(n)<=80 for n in row['collection_ids'])
                row['_ids'] = frozenset(row['document_ids'])
            _cached = (stamp, data['sources'])
            return data['sources']
    except (OSError, KeyError, ValueError, AssertionError, TypeError):
        raise KnowledgeError('Shared knowledge publication configuration unavailable') from None


class SharedIndex(KnowledgeIndex):
    def __init__(self, base, publication):
        super().__init__(base.dsn, publication['owner_id'], base.encoder)
        self.publication = publication
        self.read_document_ids = publication['document_ids']
        self.read_collection_ids = publication['collection_ids']

    def documents(self):
        with self.connection() as db:
            rows = db.execute('''SELECT d.id,d.title,d.sha256,d.embedding_key,d.created_at,
                count(c.id) chunks FROM geotool_knowledge.documents d
                LEFT JOIN geotool_knowledge.chunks_qwen3_1024 c ON c.document_id=d.id AND c.owner_id=d.owner_id
                AND d.embedding_key=ANY(%s) WHERE d.owner_id=%s AND d.id=ANY(%s)
                GROUP BY d.id ORDER BY d.id''',(COMPATIBLE_KEYS,self.owner_id,self.read_document_ids)).fetchall()
        for r in rows:r['created_at']=r['created_at'].isoformat()
        return rows

    def document(self, doc):
        if doc not in self.publication['_ids']:
            return None
        row = super().document(doc)
        if row:
            row.update(scope='shared',read_only=True,source='Research group curated document; SHA256='+row['sha256'])
        return row

    def listing(self, q='', offset=0, limit=50):
        pattern='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        with self.connection() as db:
            rows=db.execute('''SELECT d.id,d.title,d.sha256,
                (SELECT count(*) FROM geotool_knowledge.chunks_qwen3_1024 c WHERE c.owner_id=d.owner_id AND c.document_id=d.id) chunks
                FROM geotool_knowledge.documents d WHERE d.owner_id=%s AND d.id=ANY(%s)
                AND d.title ILIKE %s ESCAPE '\\' ORDER BY d.id LIMIT %s OFFSET %s''',
                (self.owner_id,self.read_document_ids,pattern,limit+1,offset)).fetchall()
        return {'documents':rows[:limit],'next_offset':offset+limit if len(rows)>limit else None}

    def preview(self, doc, start=0, chunk_offset=0):
        if doc not in self.publication['_ids']:return None
        with self.connection() as db:
            row=db.execute('''SELECT id,title,sha256,substring(body from %s for 24000) body,length(body) total_characters
                FROM geotool_knowledge.documents WHERE owner_id=%s AND id=%s''',(start+1,self.owner_id,doc)).fetchone()
            if row is None:return None
            parts=db.execute('''SELECT id citation_id,document_id,ordinal,start_char,end_char,body text
                FROM geotool_knowledge.chunks_qwen3_1024 WHERE owner_id=%s AND document_id=%s
                ORDER BY ordinal LIMIT 51 OFFSET %s''',(self.owner_id,doc,chunk_offset)).fetchall()
        return {**row,'chunks_detail':parts[:50],'next_chunk_offset':chunk_offset+50 if len(parts)>50 else None,
            'start_char':start,'next_start':start+24000 if start+24000<row['total_characters'] else None,
            'scope':'shared','read_only':True}

    def ingest(self,*args,**kwargs):
        raise PermissionError('Shared knowledge is read-only')

    def delete(self,*args,**kwargs):
        raise PermissionError('Shared knowledge is read-only')


class SharedCorpus(Corpus):
    def listing(self, *, q='', offset=0, limit=50):
        pattern='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        with self.index.connection() as db:
            rows=db.execute('''SELECT id,title,year,index_state,chunk_count chunks,l1_labels,l2_labels
                FROM geotool_corpus.papers WHERE owner_id=%s AND collection_id=ANY(%s)
                AND title ILIKE %s ESCAPE '\\' ORDER BY id LIMIT %s OFFSET %s''',
                (self.owner,self.index.read_collection_ids,pattern,limit+1,offset)).fetchall()
        return {'documents':rows[:limit],'next_offset':offset+limit if len(rows)>limit else None}

    def row(self, doc):
        if not re.fullmatch('[a-f0-9]{32}', doc):return None
        with self.index.connection() as db:
            return db.execute('''SELECT p.*,c.root FROM geotool_corpus.papers p
                JOIN geotool_corpus.collections c ON c.owner_id=p.owner_id AND c.id=p.collection_id
                WHERE p.owner_id=%s AND p.id=%s AND p.collection_id=ANY(%s)''',
                (self.owner,doc,self.index.read_collection_ids)).fetchone()


def indices(base):
    return [SharedIndex(base, source) for source in sources()]


def document(base, doc):
    for index in indices(base):
        row=index.document(doc)
        if row:return row
        row=SharedCorpus(index).document(doc)
        if row:
            # Corpus metadata can contain operational source locations.
            return {k:v for k,v in row.items() if k not in ('metadata',)} | {'scope':'shared','read_only':True,'pdf_source':None}
    return None


def merge_retrieval(base, query, limit, personal):
    from .theory import select, subject

    if not sources() or personal.get('document_scope',{}).get('mode')=='scoped' or personal.get('document_scope',{}).get('requires_clarification'):
        return personal
    started=time.monotonic()
    batches=[personal]
    for source_index, index in enumerate(indices(base)):
        result=index._retrieve_personal(query,limit)
        result['scope']='published_shared'
        for field in ('references','candidates'):
            for row in result.get(field,[]):
                row['scope']='shared';row['read_only']=True
                row['shared_source_index'] = source_index
                row['shared_source_kind'] = 'corpus' if row.get('record_sha') else 'documents'
                if isinstance(row.get('source'),str) and row['source'].startswith('/'):
                    row['source']=Path(row['source']).name
        batches.append(result)
    scoped=[r for r in batches if r.get('document_scope',{}).get('mode')=='scoped']
    if scoped:batches=scoped
    ambiguous=[r for r in batches if r.get('document_scope',{}).get('requires_clarification')]
    if ambiguous:return ambiguous[0]
    def combine(field):
        rows={}
        for batch in batches:
            for row in batch.get(field,[]):rows.setdefault(row['citation_id'],row)
        return sorted(rows.values(),key=lambda row:(-row.get('rerank_score',0),row['citation_id']))
    refs=combine('references')[:max(1,min(8,int(limit)))];candidates=combine('candidates')
    terms = subject(query) if not scoped else ()
    if terms:
        refs = select(candidates, terms, limit) or refs
    base_result=scoped[0] if scoped else personal
    unavailable = any(batch.get('status') == 'unavailable' for batch in batches)
    status = 'matched' if refs else 'unavailable' if unavailable else 'no_match' if candidates else base_result.get('status', 'empty')
    return {**base_result,'status':status,'references':refs,'candidates':candidates,
        'scope':'personal_and_published_shared','shared_sources':sum(b.get('scope')=='published_shared' for b in batches),
        'duration_ms':round((time.monotonic()-started)*1000)+(personal.get('duration_ms') or 0),
        'shared_retrieval_policy':{'legacy':'dense mode reported per source; bounded lexical recall and Qwen rerank','legacy_dense_channels':sorted({b.get('dense_retrieval','empty') for b in batches if b.get('scope')=='published_shared'}),'legacy_candidate_limit':1000,'corpus':'existing HNSW dense recall and Qwen rerank; shared lexical channel not enabled'},
        'source_results':[{'status':b.get('status'),'scope':b.get('scope'),'duration_ms':b.get('duration_ms'),
                           'references':len(b.get('references',[])), 'recall_channels':b.get('recall_channels',[]),
                           'dense_retrieval':b.get('dense_retrieval'),
                           'corpus_recall':b.get('corpus_recall',{})} for b in batches]}

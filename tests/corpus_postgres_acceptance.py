"""Explicit isolated-schema acceptance; no model calls and no production-row writes."""
import collections,csv,hashlib,json,os,sys,uuid
from pathlib import Path
from contextlib import contextmanager
from geological_agent.rag.store import configured_index,KnowledgeIndex
from geological_agent.rag.corpus import Corpus
from geological_agent.rag.corpus_import import run
from geological_agent.rag.corpus_worker import claim,process
from geological_agent.rag.profile import CHUNK_POLICY

base=Path(sys.argv[1]);source=Path(sys.argv[2]);base.mkdir(exist_ok=False)
schema='corpus_test_'+uuid.uuid4().hex
owner='acceptance_'+uuid.uuid4().hex
real=configured_index(owner)
class Connection:
    def __init__(self,db):self.db=db
    def execute(self,sql,*a,**kw):return self.db.execute(sql.replace('geotool_corpus',schema),*a,**kw)
    def cursor(self):return Cursor(self.db.cursor())
class Cursor:
    def __init__(self,c):self.c=c
    def __enter__(self):self.c.__enter__();return self
    def __exit__(self,*a):return self.c.__exit__(*a)
    def executemany(self,sql,*a,**kw):return self.c.executemany(sql.replace('geotool_corpus',schema),*a,**kw)
class Index(KnowledgeIndex):
    @contextmanager
    def connection(self):
        with super().connection() as db:yield Connection(db)
index=Index(real.dsn,owner,real.encoder)
checks=[]
def check(name,condition):
    assert condition,name
    checks.append(name)
try:
    root=base/'source';root.mkdir();rows=[];counts=collections.Counter()
    with (source/'文献目录.csv').open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f);fields=reader.fieldnames
        for i,row in enumerate(reader):
            with (source/row['record_path']).open('rb') as stream:
                stream.seek(int(row['record_offset']));raw=stream.read(int(row['record_length']))
            check('sample SHA '+str(i),hashlib.sha256(raw).hexdigest()==row['record_sha256'])
            row['record_path']='sample-'+str(i)+'.jsonl';row['record_offset']='0';(root/row['record_path']).write_bytes(raw)
            rows.append(row);counts.update(json.loads(row['matched_l2_ids']))
            if len(rows)==3:break
    with (root/'文献目录.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fields);w.writeheader();w.writerows(rows)
    files={p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in root.iterdir()}
    (root/'manifest.json').write_text(json.dumps({'schema_version':'earth-esks-subject-subset-v1','documents':3,'files':files,'counts_by_l2':{k:{'deduplicated':v} for k,v in counts.items()}}))
    run(index,root,'acceptance',base/'import.json')
    run(index,root,'acceptance',base/'resume.json')
    c=Corpus(index);first=c.listing(limit=2);second=c.listing(limit=2,after=first['next_cursor'])
    check('pagination 2+1',len(first['documents'])==2 and len(second['documents'])==1 and second['next_cursor'] is None)
    check('no duplicate IDs',len({d['id'] for d in first['documents']+second['documents']})==3)
    check('resume idempotent',c.overview()['collections'][0]['imported_documents']==3)
    check('category filtering',len(c.listing(category=next(iter(counts)))['documents'])==counts[next(iter(counts))])
    other=Index(real.dsn,'other_acceptance',real.encoder)
    check('owner list isolation',not Corpus(other).listing()['documents'])
    check('owner source isolation',Corpus(other).document(first['documents'][0]['id']) is None)
    d=c.document(first['documents'][0]['id']);check('bounded reading',len(d['body'])<=24000 and d['total_characters']>=len(d['body']))
    class FakeEncoder:
        fail=False;calls=0
        def split_embed(self,text):
            self.calls+=1
            if self.fail and self.calls==2:raise RuntimeError('intentional segment failure')
            parts=[{'start_char':i,'end_char':min(len(text),i+800),'text':text[i:i+800],
                    'metadata':{'chunker':CHUNK_POLICY,'token_count':200}} for i in range(0,len(text),800)]
            return {'chunks':parts,'vectors':[[1.0]+[0.0]*1023 for p in parts]}
    index.encoder=FakeEncoder();row=claim(index);result=process(index,row,pause=0,encode=lambda encoder,text:encoder.split_embed(text))
    check('complete worker',result['state']=='ready' and c.row(row['id'])['index_offset']==len(c.document(row['id'],full=True)['body']))
    # Replay must fail before writing duplicates rather than silently append.
    try:process(index,row,pause=0,encode=lambda encoder,text:encoder.split_embed(text))
    except ValueError:check('stale checkpoint rejected',True)
    else:raise AssertionError('Stale checkpoint accepted')
    with index.connection() as db:
        n=db.execute('SELECT count(*) n,count(DISTINCT id) u FROM geotool_corpus.chunks').fetchone()
        check('no duplicate chunks',n['n']==n['u']==result['chunks'])
    from fastapi import FastAPI,HTTPException
    from fastapi.testclient import TestClient
    import geological_agent.team.knowledge_corpus as routes
    original=routes.configured_index;routes.configured_index=lambda who:index if who==owner else other
    app=FastAPI()
    def auth(request):
        if not request.headers.get('x-test-owner'):raise HTTPException(401)
        return {'id':request.headers['x-test-owner']}
    routes.install_corpus_routes(app,auth);client=TestClient(app)
    check('HTTP unauthenticated rejected',client.get('/api/knowledge-corpus').status_code==401)
    headers={'x-test-owner':owner}
    check('HTTP listing',len(client.get('/api/knowledge-corpus/papers',headers=headers).json()['documents'])==3)
    raw=client.get('/api/knowledge-corpus/papers/'+row['id']+'/source',headers=headers)
    check('raw download hash',raw.status_code==200 and hashlib.sha256(raw.content).hexdigest()==row['record_sha'])
    check('cross-owner HTTP404',client.get('/api/knowledge-corpus/papers/'+row['id'],headers={'x-test-owner':'other'}).status_code==404)
    check('asset traversal refused',client.get('/knowledge-corpus-assets/secret').status_code==404)
    routes.configured_index=original
    print(json.dumps({'passed':len(checks),'checks':checks,'models_called':0}))
    (base/'result.json').write_text(json.dumps({'passed':len(checks),'checks':checks}))
finally:
    with real.connection() as db:db.execute('DROP SCHEMA IF EXISTS '+schema+' CASCADE')

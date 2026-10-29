"""Resumable single-worker indexing; model service owns GPU allocation."""
import argparse
import hashlib
import json
import time
import uuid
from .corpus import Corpus
from .corpus_text import projected_document, bindings
from .profile import EMBEDDING_KEY, CHUNK_POLICY
from .store import configured_index, vector, lexical


def validate_parts(text, payload):
    parts, embeddings = payload['chunks'], payload['vectors']
    if (not parts and text.strip()) or len(parts) != len(embeddings):
        raise ValueError('Incomplete chunk payload')
    covered, encoded = 0, []
    for part, embedding in zip(parts, embeddings):
        start, end, meta = part['start_char'], part['end_char'], part.get('metadata', {})
        if type(start) is not int or type(end) is not int or not 0<=start<end<=len(text):
            raise ValueError('Invalid chunk offsets')
        if (start > covered and text[covered:start].strip()) or end <= covered or part['text'] != text[start:end]:
            raise ValueError('Source coverage mismatch')
        if meta.get('chunker') != CHUNK_POLICY or type(meta.get('token_count')) is not int or not 1<=meta['token_count']<=512:
            raise ValueError('Chunk policy mismatch')
        encoded.append(vector(embedding)); covered=end
    if text[covered:].strip():
        raise ValueError('Source text was truncated')
    return parts, encoded


def segment_end(body, start, size=16000):
    end=min(len(body),start+size)
    if end<len(body):
        paragraph=body.rfind('\n\n',start+size//2,end)
        if paragraph>start: end=paragraph+2
    return end


def claim(index):
    token=uuid.uuid4().hex
    with index.connection() as db:
        row=db.execute("""SELECT id FROM geotool_corpus.papers WHERE owner_id=%s AND
           (index_state='pending' OR (index_state='running' AND lease_until<now())
            OR (index_state='failed' AND attempts<3 AND lease_until<now()))
           ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1""",(index.owner_id,)).fetchone()
        if not row:return None
        db.execute("UPDATE geotool_corpus.papers SET index_state='running',claim_token=%s,lease_until=now()+interval '20 minutes',attempts=attempts+1 WHERE owner_id=%s AND id=%s",(token,index.owner_id,row['id']))
    return {**Corpus(index).row(row['id']), 'claim_token':token}


def process(index, row, pause=2, encode=None):
    if encode is None:
        from .corpus_chunker import encode_segment
        encode = encode_segment
    projection=projected_document(row['root'],row)
    body=projection['body']; offset=row['index_offset']; ordinal=row['chunk_count']
    if not body or offset>len(body):raise ValueError('Invalid source checkpoint')
    while offset<len(body):
        end=segment_end(body,offset)
        segment=body[offset:end]
        parts,vectors=validate_parts(segment,encode(index.encoder,segment))
        gaps=[];covered=0
        for part in parts:
            if part['start_char']>covered:gaps.append([offset+covered,offset+part['start_char']])
            covered=max(covered,part['end_char'])
        if covered<len(segment):gaps.append([offset+covered,end])
        values=[]
        for number,(part,embedding) in enumerate(zip(parts,vectors),ordinal+1):
            start_char,end_char=offset+part['start_char'],offset+part['end_char']
            cid='K'+row['id']+'_'+str(number)
            meta={**part['metadata'],'source_record_sha256':row['record_sha'],
                  'source_body_sha256':row['body_sha'],'source_bindings':bindings(projection['spans'],start_char,end_char),
                  'projection_policy':projection['policy'],'segment_start_char':offset,'segment_end_char':end,
                  'segmentation_policy':'source-complete-paragraph-segments-16000-v1',
                  'layout_policy':'source-retained-whitespace-only-gaps-v1'}
            values.append((index.owner_id,cid,row['id'],number,start_char,end_char,part['text'],
                           lexical(row['title']+' '+part['text']),embedding,json.dumps(meta)))
        with index.connection() as db:
            live=db.execute('SELECT index_offset,claim_token FROM geotool_corpus.papers WHERE owner_id=%s AND id=%s FOR UPDATE',(index.owner_id,row['id'])).fetchone()
            if live['claim_token']!=row['claim_token'] or live['index_offset']!=offset:
                raise ValueError('Worker lease or checkpoint changed')
            with db.cursor() as cursor:
                cursor.executemany('''INSERT INTO geotool_corpus.chunks(owner_id,id,document_id,ordinal,start_char,end_char,body,lexical,embedding,metadata)
                  VALUES(%s,%s,%s,%s,%s,%s,%s,to_tsvector('simple',%s),%s::vector,%s::jsonb)''',values)
            ordinal+=len(parts)
            state='ready' if end==len(body) else 'running'
            db.execute("UPDATE geotool_corpus.papers SET index_offset=%s,chunk_count=%s,index_state=%s,embedding_key=%s,lease_until=now()+interval '20 minutes',error='' WHERE owner_id=%s AND id=%s",(end,ordinal,state,EMBEDDING_KEY,index.owner_id,row['id']))
            if gaps:
                db.execute("UPDATE geotool_corpus.papers SET metadata=jsonb_set(metadata,'{layout_only_gaps}',COALESCE(metadata->'layout_only_gaps','[]'::jsonb)||%s::jsonb) WHERE owner_id=%s AND id=%s",(json.dumps(gaps),index.owner_id,row['id']))
        offset=end
        if pause:time.sleep(pause)
    return {'id':row['id'],'chunks':ordinal,'characters':offset,'state':'ready'}


def run(index, maximum=0, pause=2):
    completed=0
    while not maximum or completed<maximum:
        row=claim(index)
        if row is None:
            if maximum:return
            time.sleep(30)
            continue
        try:
            result=process(index,row,pause)
            print(json.dumps(result),flush=True)
        except Exception as exc:
            with index.connection() as db:
                db.execute("UPDATE geotool_corpus.papers SET index_state='failed',error=%s,lease_until=CASE WHEN %s THEN now()+interval '5 minutes' ELSE NULL END WHERE owner_id=%s AND id=%s AND claim_token=%s",(type(exc).__name__+': '+str(exc)[:1500],not isinstance(exc,ValueError),index.owner_id,row['id'],row['claim_token']))
            print(json.dumps({'id':row['id'],'state':'failed','error':type(exc).__name__+': '+str(exc)[:1500]}),flush=True)
            # Avoid hammering an unavailable inference service.
            time.sleep(15)
        completed+=1


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--owner',required=True);p.add_argument('--max-documents',type=int,default=0);p.add_argument('--pause',type=float,default=2)
    args=p.parse_args();index=configured_index(args.owner)
    if index is None:raise SystemExit('Knowledge service is unavailable')
    run(index,args.max_documents,args.pause)

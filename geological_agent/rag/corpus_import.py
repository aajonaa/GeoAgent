"""Operator CLI: validated, resumable corpus ingestion. Never downloads or calls a model."""
import argparse
import collections
import csv
import hashlib
import json
import time
import uuid
from pathlib import Path
from .corpus import setup
from .corpus_text import project, load_record, POLICY
from .limits import account_limits
from .store import configured_index


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def safe_json(value):
    # Metadata also cannot store NUL in PostgreSQL. Original JSONL remains exact.
    if isinstance(value, str):
        return value.replace('\x00', '\u2400')
    if isinstance(value, list):
        return [safe_json(item) for item in value]
    if isinstance(value, dict):
        return {safe_json(k): safe_json(v) for k, v in value.items()}
    return value


def run(index, root, collection, receipt):
    root = Path(root).resolve()
    manifest_path = root / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    if manifest['schema_version'] != 'earth-esks-subject-subset-v1':
        raise ValueError('Unexpected corpus format')
    expected = int(manifest['documents'])
    manifest_sha = digest(manifest_path)
    started = time.time()

    def report(**values):
        data = {'owner': index.owner_id, 'collection': collection, 'expected': expected,
                'manifest_sha256': manifest_sha, 'elapsed_seconds': round(time.time()-started, 2), **values}
        tmp = Path(str(receipt)+'.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(receipt)
        print(json.dumps(data, ensure_ascii=False), flush=True)

    # Validate complete files again on the destination before mutating the catalog.
    for number, (name, spec) in enumerate(manifest['files'].items(), 1):
        path = (root / name).resolve()
        if not path.is_relative_to(root) or path.stat().st_size != spec['bytes'] or digest(path) != spec['sha256']:
            raise ValueError('Transferred file failed SHA-256 validation: '+name)
        if number % 25 == 0:
            report(stage='verifying_files', files=number)
    setup(index)
    owner = index.owner_id
    with index.connection() as db:
        db.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ('knowledge:'+owner,))
        old = db.execute('SELECT * FROM geotool_corpus.collections WHERE owner_id=%s AND id=%s', (owner,collection)).fetchone()
        if old and (old['manifest_sha'] != manifest_sha or old['root'] != str(root)):
            raise ValueError('Existing collection is bound to a different source')
        occupied = db.execute('SELECT (SELECT count(*) FROM geotool_knowledge.documents WHERE owner_id=%s)+(SELECT count(*) FROM geotool_corpus.papers WHERE owner_id=%s AND collection_id<>%s) n', (owner,owner,collection)).fetchone()['n']
        if occupied + expected > account_limits(owner)['max_documents']:
            raise ValueError('Corpus exceeds combined account capacity')
        metadata = {'source_schema': manifest['schema_version'], 'categories': manifest['counts_by_l2'],
                    'original_pdf_available': False, 'original_classifications_preserved': True,
                    'scientific_quality_verified': False, 'projection_policy': POLICY}
        db.execute('INSERT INTO geotool_corpus.collections(owner_id,id,name,root,manifest_sha,expected_documents,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT(owner_id,id) DO NOTHING',
                   (owner,collection,'EarthLiteratures · 地学文献总库',str(root),manifest_sha,expected,json.dumps(metadata)))
        existing = {r['source_sha']: r['record_sha'] for r in db.execute('SELECT source_sha,record_sha FROM geotool_corpus.papers WHERE owner_id=%s AND collection_id=%s', (owner,collection))}

    csv.field_size_limit(32*1024*1024)
    pending, counts, categories, seen = [], collections.Counter(), collections.Counter(), set()
    category_labels = {}

    def flush():
        if not pending:
            return
        with index.connection() as db:
            db.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ('knowledge:'+owner,))
            capacity = account_limits(owner)['max_documents']
            total = db.execute('SELECT (SELECT count(*) FROM geotool_knowledge.documents WHERE owner_id=%s)+(SELECT count(*) FROM geotool_corpus.papers WHERE owner_id=%s) n', (owner,owner)).fetchone()['n']
            if total + len(pending) > capacity:
                raise ValueError('Account capacity changed during import')
            with db.cursor() as cursor:
                cursor.executemany('''INSERT INTO geotool_corpus.papers(owner_id,id,collection_id,source_sha,title,year,
                 l1_ids,l2_ids,l1_labels,l2_labels,metadata,record_path,record_offset,record_length,record_sha,
                 body_sha,body_chars,text_policy,index_state,error)
                 VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s)''', pending)
            db.execute('UPDATE geotool_corpus.collections SET imported_documents=(SELECT count(*) FROM geotool_corpus.papers WHERE owner_id=%s AND collection_id=%s) WHERE owner_id=%s AND id=%s', (owner,collection,owner,collection))
        pending.clear()

    with (root / '文献目录.csv').open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            source = row['source_sha256']
            if len(source)!=64 or any(c not in '0123456789abcdef' for c in source) or source in seen:
                raise ValueError('Invalid or duplicate source identity')
            seen.add(source)
            categories.update(json.loads(row['matched_l2_ids']))
            category_labels.update(zip(json.loads(row['l2_ids']),json.loads(row['l2_labels_zh'])))
            if source in existing:
                if existing[source] != row['record_sha256']:
                    raise ValueError('Resume source hash mismatch')
                counts['reused'] += 1
                continue
            record = load_record(root,row['record_path'],int(row['record_offset']),int(row['record_length']),row['record_sha256'])
            projection = project(record)
            unsupported = [i for i in projection['issues'] if i['code'] != 'nul_display_projection']
            state = 'blocked' if unsupported else 'pending'
            metadata = {'source_doc_id': row['doc_id'], 'source_batch': row['batch'],
                        'source_records': json.loads(row['source_records']), 'source_locator': row['source_locator'],
                        'classification_source': row['classification_source'],
                        'matched_l2_ids': json.loads(row['matched_l2_ids']),
                        'identity_status': record.get('_identity',{}).get('status','unrecorded'),
                        'source_identity': record.get('_identity'),
                        'doi': record.get('doi'), 'authors': record.get('authors',record.get('author')),
                        'projection_issues': projection['issues'], 'spans_count': len(projection['spans']),
                        'original_pdf_available': False, 'scientific_quality_verified': False}
            paper_id = uuid.uuid5(uuid.NAMESPACE_URL, owner+'/'+collection+'/'+source).hex
            pending.append((owner,paper_id,collection,source,safe_json(row['title']),row['publication_year'],
                json.loads(row['l1_ids']),json.loads(row['l2_ids']),json.loads(row['l1_labels_zh']),json.loads(row['l2_labels_zh']),
                json.dumps(safe_json(metadata),ensure_ascii=False),row['record_path'],int(row['record_offset']),int(row['record_length']),
                row['record_sha256'],projection['sha256'],len(projection['body']),POLICY,state,
                json.dumps(unsupported,ensure_ascii=False) if unsupported else ''))
            counts[state] += 1
            counts['body_characters'] += len(projection['body'])
            if len(pending) >= 500:
                flush()
            if len(seen) % 5000 == 0:
                report(stage='importing', records=len(seen), **counts)
    flush()
    if len(seen) != expected or dict(categories) != {k:v['deduplicated'] for k,v in manifest['counts_by_l2'].items()}:
        raise ValueError('Final count or classification reconciliation failed')
    with index.connection() as db:
        actual = db.execute('SELECT count(*) n FROM geotool_corpus.papers WHERE owner_id=%s AND collection_id=%s',(owner,collection)).fetchone()['n']
        if actual != expected:
            raise ValueError('Database count mismatch')
        metadata['categories'] = {k:{**v,'label':category_labels.get(k,k)} for k,v in manifest['counts_by_l2'].items()}
        db.execute("UPDATE geotool_corpus.collections SET state='imported',imported_documents=%s,metadata=%s::jsonb WHERE owner_id=%s AND id=%s",(actual,json.dumps(metadata),owner,collection))
    report(stage='imported', records=len(seen), category_reconciliation=True, **counts)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--owner',required=True);parser.add_argument('--root',required=True)
    parser.add_argument('--collection',default='earthliteratures-esks-20261026');parser.add_argument('--receipt',required=True)
    args=parser.parse_args()
    index=configured_index(args.owner)
    if index is None: raise SystemExit('Knowledge configuration unavailable')
    run(index,args.root,args.collection,Path(args.receipt))

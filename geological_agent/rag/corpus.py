"""Bounded owner-scoped corpus catalog, exact source reading and hybrid recall."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re

from .corpus_text import projected_document, POLICY as TEXT_POLICY

LEXICAL_TIMEOUT = '1500ms'
LEXICAL_CANDIDATE_LIMIT = 1000
LEXICAL_SUPPLEMENT_LIMIT = 12

SCHEMA = '''
CREATE SCHEMA IF NOT EXISTS geotool_corpus;
CREATE TABLE IF NOT EXISTS geotool_corpus.collections (
 owner_id text NOT NULL, id text NOT NULL, name text NOT NULL, root text NOT NULL,
 manifest_sha text NOT NULL, expected_documents bigint NOT NULL, imported_documents bigint NOT NULL DEFAULT 0,
 metadata jsonb NOT NULL DEFAULT '{}', state text NOT NULL DEFAULT 'importing',
 PRIMARY KEY(owner_id,id));
CREATE TABLE IF NOT EXISTS geotool_corpus.papers (
 owner_id text NOT NULL, id text NOT NULL, collection_id text NOT NULL, source_sha text NOT NULL,
 title text NOT NULL, year text NOT NULL, l1_ids text[] NOT NULL, l2_ids text[] NOT NULL,
 l1_labels text[] NOT NULL, l2_labels text[] NOT NULL, metadata jsonb NOT NULL,
 record_path text NOT NULL, record_offset bigint NOT NULL, record_length bigint NOT NULL, record_sha text NOT NULL,
 body_sha text NOT NULL, body_chars bigint NOT NULL, text_policy text NOT NULL,
 index_state text NOT NULL DEFAULT 'pending', index_offset bigint NOT NULL DEFAULT 0,
 chunk_count integer NOT NULL DEFAULT 0, attempts integer NOT NULL DEFAULT 0,
 lease_until timestamptz, claim_token text, error text NOT NULL DEFAULT '', embedding_key text,
 PRIMARY KEY(owner_id,id), UNIQUE(owner_id,collection_id,source_sha),
 FOREIGN KEY(owner_id,collection_id) REFERENCES geotool_corpus.collections(owner_id,id));
CREATE INDEX IF NOT EXISTS corpus_listing ON geotool_corpus.papers(owner_id,collection_id,id);
CREATE INDEX IF NOT EXISTS corpus_pending ON geotool_corpus.papers(owner_id,index_state,id);
CREATE INDEX IF NOT EXISTS corpus_l1 ON geotool_corpus.papers USING gin(l1_ids);
CREATE INDEX IF NOT EXISTS corpus_l2 ON geotool_corpus.papers USING gin(l2_ids);
CREATE INDEX IF NOT EXISTS corpus_title ON geotool_corpus.papers USING gin(to_tsvector('simple', title));
CREATE TABLE IF NOT EXISTS geotool_corpus.chunks (
 owner_id text NOT NULL,id text NOT NULL,document_id text NOT NULL,ordinal integer NOT NULL,
 start_char bigint NOT NULL,end_char bigint NOT NULL,body text NOT NULL,
 lexical tsvector NOT NULL,embedding vector(1024) NOT NULL,metadata jsonb NOT NULL,
 PRIMARY KEY(owner_id,id), UNIQUE(owner_id,document_id,ordinal),
 FOREIGN KEY(owner_id,document_id) REFERENCES geotool_corpus.papers(owner_id,id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS corpus_chunk_doc ON geotool_corpus.chunks(owner_id,document_id);
CREATE INDEX IF NOT EXISTS corpus_chunk_lexical ON geotool_corpus.chunks USING gin(lexical);
CREATE INDEX IF NOT EXISTS corpus_chunk_hnsw ON geotool_corpus.chunks USING hnsw(embedding vector_cosine_ops);
'''


def setup(index):
    with index.connection() as db:
        db.execute(SCHEMA, prepare=False)
        for table in ('collections', 'papers', 'chunks'):
            db.execute(f'''ALTER TABLE geotool_corpus.{table} ENABLE ROW LEVEL SECURITY;
                ALTER TABLE geotool_corpus.{table} FORCE ROW LEVEL SECURITY;
                DROP POLICY IF EXISTS owner_scope ON geotool_corpus.{table};
                CREATE POLICY owner_scope ON geotool_corpus.{table}
                USING(owner_id=current_setting('geotool.knowledge_owner',true))
                WITH CHECK(owner_id=current_setting('geotool.knowledge_owner',true));''', prepare=False)


def enabled():
    return os.environ.get('GEOTOOL_LARGE_CORPUS') == '1'


def recall_with_savepoint(db, read, *, timeout=None):
    from psycopg.errors import QueryCanceled

    try:
        with db.transaction():
            if timeout is not None:
                previous = db.execute('SHOW statement_timeout').fetchone()['statement_timeout']
                db.execute("SELECT set_config('statement_timeout',%s,true)", (timeout,))
            rows = read()
            if timeout is not None:
                db.execute("SELECT set_config('statement_timeout',%s,true)", (previous,))
    except QueryCanceled as exc:
        if exc.diag.message_primary != 'canceling statement due to statement timeout':
            raise
        return [], 'timed_out'
    return rows, 'completed'


def dense_recall(db, columns, base, scope_args, encoded):
    def read():
        db.execute("SET LOCAL hnsw.iterative_scan='strict_order'")
        return db.execute(
            'SELECT ' + columns + base + 'ORDER BY c.embedding <=> %s::vector LIMIT 50',
            (*scope_args, encoded),
        ).fetchall()

    return recall_with_savepoint(db, read)


def lexical_recall(db, columns, base, scope_args, terms, *, bounded=True):
    from psycopg.errors import QueryCanceled

    # A savepoint keeps a canceled supplementary query from aborting the
    # transaction that read the dense candidates and set the owner scope.
    try:
        with db.transaction():
            timeout = db.execute('SHOW statement_timeout').fetchone()['statement_timeout']
            db.execute("SELECT set_config('statement_timeout',%s,true)", (LEXICAL_TIMEOUT,))
            matches = base + "AND c.lexical @@ to_tsquery('simple',%s) "
            if bounded:
                rows = db.execute(
                    'WITH keyword_candidates AS MATERIALIZED (SELECT c.lexical,' + columns + matches +
                    'LIMIT %s) SELECT * FROM keyword_candidates '
                    "ORDER BY ts_rank_cd(lexical,to_tsquery('simple',%s)) DESC, citation_id LIMIT 50",
                    (*scope_args, terms, LEXICAL_CANDIDATE_LIMIT, terms),
                ).fetchall()
            else:
                rows = db.execute(
                    'SELECT ' + columns + matches +
                    "ORDER BY ts_rank_cd(c.lexical,to_tsquery('simple',%s)) DESC, citation_id LIMIT 50",
                    (*scope_args, terms, terms),
                ).fetchall()
            db.execute("SELECT set_config('statement_timeout',%s,true)", (timeout,))
    except QueryCanceled as exc:
        if exc.diag.message_primary != 'canceling statement due to statement timeout':
            raise
        return [], 'timed_out'
    for row in rows:
        row.pop('lexical', None)
    return rows, 'completed'


def document_title_recall(db, columns, owner, key, collections, terms, encoded):
    from psycopg.errors import QueryCanceled
    from .theory import parent_patterns, parent_score

    where = "owner_id=%s AND index_state='ready' AND embedding_key=%s"
    params = [owner, key]
    if collections is not None:
        where += ' AND collection_id=ANY(%s)'
        params.append(collections)
    try:
        with db.transaction():
            timeout = db.execute('SHOW statement_timeout').fetchone()['statement_timeout']
            db.execute("SELECT set_config('statement_timeout','950ms',true)")
            matches = db.execute(
                'SELECT id,title FROM geotool_corpus.papers WHERE ' + where
                + ' AND title ILIKE ANY(%s) AND title ILIKE ANY(%s) LIMIT 64', (*params, *parent_patterns(terms)),
            ).fetchall()
            ranked = sorted(matches, key=lambda row: (-parent_score(row['title'], terms), row['id']))
            ids = [row['id'] for row in ranked if parent_score(row['title'], terms) >= 2][:8]
            rows = []
            if ids:
                rows = db.execute(
                    'WITH scoped_papers AS (SELECT * FROM geotool_corpus.papers WHERE ' + where +
                    ' AND id=ANY(%s)) SELECT ' + columns +
                    ' FROM scoped_papers p JOIN LATERAL (SELECT * FROM geotool_corpus.chunks '
                    'WHERE owner_id=p.owner_id AND document_id=p.id '
                    'ORDER BY (embedding <=> %s::vector)+0,id LIMIT 3) c ON true '
                    'ORDER BY c.embedding <=> %s::vector,c.id LIMIT 14', (*params, ids, encoded, encoded),
                ).fetchall()
            db.execute("SELECT set_config('statement_timeout',%s,true)", (timeout,))
            return rows, 'completed'
    except QueryCanceled as exc:
        if exc.diag.message_primary != 'canceling statement due to statement timeout':
            raise
        return [], 'timed_out'


def cursor_encode(after, signature):
    return base64.urlsafe_b64encode(json.dumps([after, signature]).encode()).decode().rstrip('=')


def cursor_decode(value, signature):
    if not value:
        return ''
    try:
        if len(value) > 400:
            raise ValueError()
        after, digest = json.loads(base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)))
        if digest != signature or not isinstance(after, str) or not re.fullmatch('[a-f0-9]{32}', after):
            raise ValueError()
        return after
    except Exception:
        raise ValueError('Invalid or stale page cursor') from None


class Corpus:
    def __init__(self, index):
        self.index, self.owner = index, index.owner_id

    def overview(self):
        from .limits import account_limits
        from .store import COMPATIBLE_KEYS
        with self.index.connection() as db:
            rows = db.execute('SELECT id,name,expected_documents,imported_documents,metadata,state FROM geotool_corpus.collections WHERE owner_id=%s ORDER BY id', (self.owner,)).fetchall()
            states = db.execute('SELECT index_state,count(*) n,coalesce(sum(chunk_count),0) chunks FROM geotool_corpus.papers WHERE owner_id=%s GROUP BY index_state', (self.owner,)).fetchall()
            legacy = db.execute('''SELECT count(*) documents,
                count(*) FILTER (WHERE chunks>0) indexed_documents,
                coalesce(sum(chunks),0) chunks FROM (
                    SELECT d.id,count(c.id) chunks FROM geotool_knowledge.documents d
                    LEFT JOIN geotool_knowledge.chunks_qwen3_1024 c
                    ON c.document_id=d.id AND c.owner_id=d.owner_id AND d.embedding_key=ANY(%s)
                    WHERE d.owner_id=%s GROUP BY d.id
                ) documents''', (COMPATIBLE_KEYS,self.owner)).fetchone()
        corpus = {'documents':sum(r['n'] for r in states),
                  'indexed_documents':sum(r['n'] for r in states if r['index_state']=='ready'),
                  'chunks':int(sum(r['chunks'] for r in states))}
        legacy = {key:int(value) for key,value in legacy.items()}
        return {'collections': rows, 'states': {r['index_state']: r['n'] for r in states},
                'account_capacity': account_limits(self.owner)['max_documents'], 'legacy_documents': legacy['documents'],
                'statistics': {'legacy':legacy, 'corpus':corpus,
                    'total':{key:legacy[key]+corpus[key] for key in corpus}},
                'scope': 'current_account', 'text_policy': TEXT_POLICY}

    def listing(self, *, q='', category='', state='', collection='', after='', limit=50):
        if not isinstance(q, str) or len(q) > 300 or len(category) > 80 or len(collection) > 80:
            raise ValueError('Invalid filter')
        if state not in ('', 'pending', 'running', 'ready', 'failed', 'blocked'):
            raise ValueError('Invalid index state')
        limit = max(1, min(100, int(limit)))
        signature = hashlib.sha256(json.dumps([self.owner, q, category, state, collection]).encode()).hexdigest()[:24]
        after = cursor_decode(after, signature)
        where, args = ['owner_id=%s', 'id>%s'], [self.owner, after]
        if collection:
            where.append('collection_id=%s'); args.append(collection)
        if category:
            if category.count('.'):
                where.append('l2_ids @> ARRAY[%s]'); args.append(category)
            else:
                where.append('l1_ids @> ARRAY[%s]'); args.append(category)
        if state:
            where.append('index_state=%s'); args.append(state)
        if q.strip():
            if re.search('[\u3400-\u9fff]', q):
                where.append('position(%s in title)>0'); args.append(q.strip())
            else:
                where.append("to_tsvector('simple',title) @@ plainto_tsquery('simple',%s)"); args.append(q.strip())
        with self.index.connection() as db:
            rows = db.execute('SELECT id,title,year,l1_labels,l2_labels,index_state,chunk_count,body_chars,metadata->>\'identity_status\' identity_status FROM geotool_corpus.papers WHERE ' + ' AND '.join(where) + ' ORDER BY id LIMIT %s', (*args, limit + 1)).fetchall()
        return {'documents': rows[:limit], 'next_cursor': cursor_encode(rows[limit - 1]['id'], signature) if len(rows) > limit else None,
                'page_size': limit, 'scope': 'current_account'}

    def row(self, doc):
        if not re.fullmatch('[a-f0-9]{32}', doc):
            return None
        with self.index.connection() as db:
            return db.execute('SELECT p.*,c.root FROM geotool_corpus.papers p JOIN geotool_corpus.collections c ON c.owner_id=p.owner_id AND c.id=p.collection_id WHERE p.owner_id=%s AND p.id=%s', (self.owner, doc)).fetchone()

    def document(self, doc, *, start=0, length=24000, full=False):
        row = self.row(doc)
        if row is None:
            return None
        source = projected_document(row['root'], row)
        start, length = max(0, int(start)), max(1, min(50000, int(length)))
        if full:
            start, length = 0, len(source['body'])
        end = min(len(source['body']), start + length)
        return {'id': row['id'], 'title': row['title'], 'source': self.source(row), 'sha256': row['body_sha'],
                'body': source['body'] if full else source['body'][start:end],
                'start_char': start, 'end_char': end, 'total_characters': len(source['body']),
                'next_start': end if end < len(source['body']) else None,
                'metadata': row['metadata'], 'l1_labels': row['l1_labels'], 'l2_labels': row['l2_labels'],
                'index_state': row['index_state'], 'chunks': row['chunk_count'],
                'original_pdf_available': False, 'projection_issues': source['issues']}

    @staticmethod
    def source(row):
        return 'EarthLiteratures; source SHA256=' + row['source_sha'] + '; source record SHA256=' + row['record_sha']

    def _availability(self):
        scope = ' FROM geotool_corpus.papers WHERE owner_id=%s'
        args = (self.owner,)
        if hasattr(self.index, 'read_collection_ids'):
            scope += ' AND collection_id=ANY(%s)'
            args += (self.index.read_collection_ids,)
        with self.index.connection() as db:
            if db.execute('SELECT 1' + scope + " AND index_state='ready' LIMIT 1", args).fetchone():
                return 'ready'
            return 'indexing' if db.execute('SELECT 1' + scope + ' LIMIT 1', args).fetchone() else 'empty'

    def retrieve(self, query, limit=4):
        from .store import vector, lexical, ranking_policy, ranking_views
        from .evidence import prepare_passage, catalog_requested, selection_reason, requested_catalog_fields, supports_catalog_field, prioritize_numeric_evidence
        from .profile import EMBEDDING_KEY, retrieval_profile
        from .theory import context_input, select, subject
        if not isinstance(query, str) or not query.strip() or len(query) > 24000:
            raise ValueError('Invalid retrieval query')
        availability = self._availability()
        if availability != 'ready':
            return {'status': availability, 'references': [], 'candidates': []}
        encoded = vector(self.index.encoder.embed([query], query=True)[0])
        theory_terms = subject(query)
        columns = 'c.id citation_id,c.document_id,c.ordinal,c.start_char,c.end_char,c.body text,c.metadata,p.title,p.body_sha sha256,p.source_sha,p.record_sha'
        base = " FROM geotool_corpus.chunks c JOIN geotool_corpus.papers p ON p.owner_id=c.owner_id AND p.id=c.document_id WHERE c.owner_id=%s AND p.index_state='ready' AND p.embedding_key=%s "
        scope_args=(self.owner,EMBEDDING_KEY)
        if hasattr(self.index,'read_collection_ids'):
            base+=' AND p.collection_id=ANY(%s) '
            scope_args+=(self.index.read_collection_ids,)
        terms = ' | '.join(sorted(set(lexical(query).split()))[:300]) or 'zznomatchzz'
        with self.index.connection() as db:
            dense, dense_status = dense_recall(db, columns, base, scope_args, encoded)
            if hasattr(self.index,'read_collection_ids'):
                # Shared corpus uses the existing HNSW channel. Its lexical
                # query exceeded the read budget even with a bounded result set.
                sparse, lexical_status = [], 'disabled_for_shared'
            else:
                sparse, lexical_status = lexical_recall(db, columns, base, scope_args, terms)
            parent, parent_status = (document_title_recall(
                db, columns, self.owner, EMBEDDING_KEY,
                getattr(self.index, 'read_collection_ids', None), theory_terms, encoded,
            ) if theory_terms else ([], 'not_requested'))
        recall = {
            'recall_channels': [name for name, status in (('dense', dense_status), ('lexical', lexical_status))
                                if status == 'completed'],
            'dense_status': dense_status, 'lexical_status': lexical_status,
        }
        empty_status = 'timed_out' if dense_status == 'timed_out' else 'no_match'
        if theory_terms:
            recall['document_title_status'] = parent_status
            if parent:
                recall['recall_channels'].append('document_title')
        fused = {row['citation_id']: {**row, 'rrf_score': 1 / (60 + rank)}
                 for rank, row in enumerate(dense, 1)}
        supplemental = 0
        for rank, row in enumerate(sparse, 1):
            citation_id = row['citation_id']
            if citation_id not in fused:
                if supplemental >= LEXICAL_SUPPLEMENT_LIMIT:
                    continue
                fused[citation_id] = {**row, 'rrf_score': 0}
                supplemental += 1
            fused[citation_id]['rrf_score'] += 1 / (60 + rank)
        for rank, row in enumerate(parent, 1):
            selected = fused.setdefault(row['citation_id'], {**row, 'rrf_score': 0})
            selected['rrf_score'] += 1 / (60 + rank)
        candidates = sorted(fused.values(), key=lambda row: -row['rrf_score'])
        if not candidates:
            return {'status': empty_status, 'references': [], 'candidates': [], **recall}
        # Validate original binding for every reranked candidate, with one source
        # read per document. Database passage text is never execution proof.
        bodies = {}
        for row in candidates:
            if row['document_id'] not in bodies:
                bodies[row['document_id']] = self.document(row['document_id'], full=True)
            doc = bodies[row['document_id']]
            if not doc or doc['sha256'] != row['sha256'] or doc['body'][row['start_char']:row['end_char']] != row['text']:
                raise ValueError('Corpus passage source binding failed')
            row['source'] = doc['source']
        requested = requested_catalog_fields(query)
        metadata_requested = catalog_requested(query)
        for row in candidates:
            row.update(prepare_passage(row, metadata_requested=metadata_requested))
        if requested:
            candidates = [row for row in candidates if any(supports_catalog_field(row, field) for field in requested)]
        if not candidates:
            return {'status': empty_status, 'references': [], 'candidates': [], **recall}
        inputs = [context_input(row) if theory_terms else row['rerank_input'] for row in candidates]
        ranked_views = [self.index.encoder.rerank(view, inputs) for view in ranking_views(query)]
        ranked = ranked_views[0]
        policy = ranking_policy(ranked['model'])
        for result in ranked_views:
            if result['model'] != ranked['model'] or len(result['scores']) != len(candidates):
                raise ValueError('Rerank contract changed')
        for i, row in enumerate(candidates):
            row['rerank_scores'] = [r['scores'][i] for r in ranked_views]
            row['rerank_score'] = max(row['rerank_scores'])
            row['selection_reason'] = selection_reason(row, policy['threshold'], metadata_requested, requested_fields=requested, query=query)
        candidates.sort(key=lambda row: (-row['rerank_score'], row['citation_id']))
        candidates = prioritize_numeric_evidence(candidates, query, policy['threshold'])
        from .document_scope import select_document_coverage
        selected, _ = select_document_coverage(candidates, None, max(1,min(8,int(limit))))
        if theory_terms:
            selected = select(candidates, theory_terms, limit) or selected
        return {'status': 'matched' if selected else empty_status, 'references': selected, 'candidates': candidates,
                'embedding_key': EMBEDDING_KEY, 'reranker': ranked['model'], 'rerank_policy': policy,
                'retrieval_profile': retrieval_profile([r['metadata'] for r in selected]),
                **recall,
                'scope': 'Current authenticated user; only fully indexed corpus documents'}

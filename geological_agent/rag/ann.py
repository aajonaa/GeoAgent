"""Opt-in shared legacy ANN; database migration is a separate operator action."""
import os

INDEX_READY = '''SELECT 1 FROM pg_index i
 JOIN pg_class ix ON ix.oid=i.indexrelid JOIN pg_am am ON am.oid=ix.relam
 JOIN pg_opclass op ON op.oid=i.indclass[0]
 WHERE i.indexrelid=to_regclass('geotool_knowledge.knowledge_qwen3_hnsw')
 AND i.indrelid=to_regclass('geotool_knowledge.chunks_qwen3_1024')
 AND i.indisvalid AND i.indisready AND am.amname='hnsw'
 AND op.opcname='vector_cosine_ops' AND pg_get_indexdef(i.indexrelid,1,true)='embedding' '''

QUERY = '''WITH neighbors AS MATERIALIZED (
 SELECT id,owner_id,document_id,embedding <=> %s::vector AS distance
 FROM geotool_knowledge.chunks_qwen3_1024
 WHERE owner_id=%s AND document_id=ANY(%s)
 ORDER BY embedding <=> %s::vector LIMIT 50)
 SELECT c.id AS citation_id,c.document_id,c.ordinal,c.start_char,c.end_char,c.body AS text,
 d.title,d.source,d.sha256,c.metadata,1-n.distance AS dense_score
 FROM neighbors n JOIN geotool_knowledge.chunks_qwen3_1024 c
 ON c.id=n.id AND c.owner_id=n.owner_id AND c.document_id=n.document_id
 JOIN geotool_knowledge.documents d ON d.id=c.document_id AND d.owner_id=c.owner_id
 WHERE c.owner_id=%s AND d.embedding_key=ANY(%s)
 ORDER BY n.distance,c.id LIMIT 50'''

def shared_dense(conn,owner,documents,published_ids,compatible_keys,query_vector):
    """None requests the existing bounded lexical fallback; [] means empty scope.

    All IDs originate from authenticated publication metadata, never model input.
    Publication and embedding-compatible membership constrain ANN before LIMIT;
    owner/version joins, RLS and later original-source checks remain in force.
    """
    if os.environ.get('GEOTOOL_KNOWLEDGE_SHARED_ANN')!='1':
        return None
    if conn.execute(INDEX_READY,prepare=False).fetchone() is None:
        return None
    published=set(published_ids)
    allowed=sorted({row['id'] for row in documents
                    if row['id'] in published and row['embedding_key'] in compatible_keys and row['chunks']>0})
    if not allowed:
        return []
    conn.execute('SET LOCAL hnsw.ef_search=200')
    conn.execute("SET LOCAL hnsw.iterative_scan='strict_order'")
    # Prevent generic prepared plans from choosing an owner/document scan and sort.
    return conn.execute(QUERY,(query_vector,owner,allowed,query_vector,owner,compatible_keys),prepare=False).fetchall()

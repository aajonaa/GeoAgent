"""Versioned retrieval contract; not chat-model settings."""
EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
EMBEDDING_REVISION = "sha256:395a0c5276fed1d36c52e29429e444ba71470749bd9260e4e4e4440028e2b340"
RERANK_MODEL = "Qwen/Qwen3-Reranker-0.6B"
RERANK_REVISION = "sha256:4f4ff43ffd7f36b4402007b27276748628c03ba6f2259b613ce51cec46c6813b"
DIMENSIONS = 1024
CHUNK_POLICY = "markdown-structure-qwen512-overlap64-v1"
EMBEDDING_KEY = EMBEDDING_MODEL + "@" + EMBEDDING_REVISION + ":1024:geoscience-v1:" + CHUNK_POLICY
RERANK_KEY = RERANK_MODEL + "@" + RERANK_REVISION

def retrieval_profile(chunk_metadata=None):
    result = {
        "embedding_model": EMBEDDING_MODEL, "embedding_revision": EMBEDDING_REVISION,
        "dimensions": DIMENSIONS, "rerank_model": RERANK_MODEL,
        "rerank_revision": RERANK_REVISION,
        "chunker": CHUNK_POLICY, "chunk_max_tokens": 512,
        "long_block_overlap_tokens": 64,
        "lexical": "PostgreSQL simple + CJK bigrams (not BM25)",
        "fusion": "RRF", "service_max_input_tokens": 4096,
        "literature_chunker": "literature-qwen512-chart-source-separation-v5",
        "previous_literature_chunkers": ["literature-qwen512-source-mapped-refinements-v4", "literature-qwen512-context-table-headers-v2", "literature-qwen512-merged-sections-tables-v3"],
        "dense_candidates": 50, "lexical_candidates": 50, "rerank_candidates": 50,
        "originals_preserved": True, "automatic_legacy_reindex": False,
    }

    if chunk_metadata is not None:
        counts = {}
        for metadata in chunk_metadata:
            name = metadata.get("chunker") if isinstance(metadata, dict) else None
            name = name if isinstance(name, str) and name else "unknown"
            counts[name] = counts.get(name, 0) + 1
        result["active_chunkers"] = [{"id": name, "chunks": counts[name]} for name in sorted(counts)]
        result["chunker"] = next(iter(counts)) if len(counts) == 1 else "mixed" if counts else None
        result["chunker_scope"] = "returned_chunks"
    return result

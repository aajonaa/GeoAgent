"""Answer inventory requests from the databases visible to the signed-in user."""

import re
import unicodedata

from ..rag.corpus import Corpus, enabled as corpus_enabled
from ..rag.shared import SharedIndex, sources
from ..rag.store import KnowledgeError, configured_index


_INVENTORY = re.compile(
    r"(?:请(?:问|帮我)?|帮我|给我|告诉我|查一下|看一下|统计一下|统计)?"
    r"(?:你(?:的)?|我(?:的)?|我们(?:的)?|平台(?:的)?)?(?:目前|当前|现有|现在|已有|的)*"
    r"(?P<scope>个人|共享|课题组|全部)?知识库(?:目前|当前|现有|现在|一共|总共|的|里|中)*"
    r"(?:统计(?:一下|信息|数据|概况)?|概况|规模|库存|收录量|文献(?:总数|数量)|"
    r"(?:一共|总共)?(?:有|收录了|包含)?多少(?:篇|条|份|个)?(?:文献|论文|文章|文档|知识片段|索引片段)?)"
    r"(?:是多少|是多少呢|吧|呢)?"
)
_LABELS = {
    "personal": "个人知识库",
    "shared": "已发布共享库",
    "all": "当前可见知识库",
}


def inventory_scope(query):
    if len(query) > 100:
        return None
    normalized = unicodedata.normalize("NFKC", query)
    text = re.sub(r"\s+", "", normalized).strip("?!。！？，,")
    matched = _INVENTORY.fullmatch(text)
    if matched is None:
        return None
    return {"个人": "personal", "共享": "shared", "课题组": "shared"}.get(
        matched["scope"], "all"
    )


def _legacy_totals(rows):
    counts = [row["chunks"] for row in rows]
    return len(counts), sum(count > 0 for count in counts), sum(counts)


def _personal_totals(index):
    if not corpus_enabled():
        return _legacy_totals(index.documents())
    total = Corpus(index).overview()["statistics"]["total"]
    return total["documents"], total["indexed_documents"], total["chunks"]


def _shared_totals(index):
    publications = {}
    for row in sources():
        owner = row["owner_id"]
        documents, collections = publications.setdefault(owner, (set(), set()))
        documents.update(row["document_ids"])
        collections.update(row["collection_ids"])

    totals = [0, 0, 0]
    overlap = (0, 0, 0)
    for owner, (documents, collections) in publications.items():
        shared = SharedIndex(index, {
            "owner_id": owner, "document_ids": sorted(documents), "collection_ids": sorted(collections),
        })
        legacy = _legacy_totals(shared.documents()) if documents else (0, 0, 0)
        corpus = (0, 0, 0)
        if collections and corpus_enabled():
            with shared.connection() as db:
                row = db.execute(
                    """SELECT count(*) documents, count(*) FILTER (WHERE index_state='ready') indexed,
                              coalesce(sum(chunk_count), 0) chunks
                       FROM geotool_corpus.papers WHERE owner_id=%s AND collection_id=ANY(%s)""",
                    (shared.owner_id, shared.read_collection_ids),
                ).fetchone()
            corpus = tuple(row[key] for key in ("documents", "indexed", "chunks"))
        counts = tuple(a + b for a, b in zip(legacy, corpus))
        for i, value in enumerate(counts):
            totals[i] += value
        if owner == index.owner_id:
            overlap = counts
    return totals, overlap


def inventory_answer(uid, scope):
    try:
        index = configured_index(uid)
        if index is None:
            return {"status": "failed", "reason": "knowledge_disabled", "turns": 0,
                    "answer": "当前部署尚未启用知识库服务，暂时无法查询统计。"}
        visible = {}
        overlap = (0, 0, 0)
        if scope != "shared":
            visible["personal"] = _personal_totals(index)
        if scope != "personal":
            shared, own_published = _shared_totals(index)
            visible["shared"] = shared
            if scope == "all":
                overlap = own_published
    except KnowledgeError:
        return {"status": "failed", "reason": "knowledge_inventory_unavailable", "turns": 0,
                "answer": "知识库统计暂时不可用，请稍后重试。"}

    totals = tuple(sum(values) - common for values, common in zip(zip(*visible.values()), overlap))
    if scope == "all":
        visible["all"] = totals
    lines = [
        f"**{_LABELS[scope]}共收录 {totals[0]:,} 篇文献，已建立索引 {totals[1]:,} 篇。**",
        "",
        "| 范围 | 已收录文献 | 已建立索引 | 索引片段 |",
        "|---|---:|---:|---:|",
    ]
    lines.extend(
        f"| {_LABELS[key]} | {documents:,} | {indexed:,} | {chunks:,} |"
        for key, (documents, indexed, chunks) in visible.items()
    )
    lines.extend(("", "合计按文献记录去重。个人库与共享库可能包含同一条记录。"))
    return {"status": "completed", "answer": "\n".join(lines), "turns": 0}

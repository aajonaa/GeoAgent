"""Read-only citation presentation. Never changes evidence or review decisions."""
import json
import re


_CITATION = re.compile(r"\[(K[0-9a-f]{16,64}_[0-9]+)\]")


def answer_citations(store, uid, run):
    """Resolve exact IDs only within this owner's conversation, up to this run.

    Resumed answers can refer to a preceding retrieval. Its saved snapshot is
    displayed with provenance, not promoted to a fresh retrieval or approval.
    Conflicting snapshots are deliberately left unresolved.
    """
    requested = list(dict.fromkeys(_CITATION.findall(str(run.get("answer") or ""))))
    if not requested:
        return {"items": [], "unavailable_ids": [], "conflicting_ids": []}
    wanted = set(requested)
    found, identities, conflicts = {}, {}, set()
    with store.lock:
        rows = store.db.execute(
            "SELECT e.rid,e.data FROM events e "
            "JOIN runs r ON r.id=e.rid JOIN conversations c ON c.id=r.cid "
            "WHERE c.uid=? AND r.cid=? AND r.created<=? "
            "AND json_extract(e.data,'$.kind')='knowledge_sources' "
            "ORDER BY r.created,e.seq",
            (uid, run["cid"], run["created"]),
        ).fetchall()
    for rid, raw in rows:
        event = json.loads(raw)
        references = event.get("references", [])
        if not isinstance(references, list):
            continue
        for ref in references:
            if not isinstance(ref, dict) or ref.get("citation_id") not in wanted:
                continue
            cid = ref["citation_id"]
            metadata = ref.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            anchors = metadata.get("sources")
            anchors = anchors if isinstance(anchors, list) else []
            pages = sorted({a["page"] for a in anchors
                            if isinstance(a, dict) and type(a.get("page")) is int
                            and a["page"] > 0})
            item = {key: ref.get(key, "") for key in
                    ("citation_id", "document_id", "title", "source", "text", "sha256")}
            item.update({"pages": pages, "anchors": anchors,
                         "quality_status": metadata.get("quality_status", ""),
                         "original_sha256": metadata.get("original_sha256", ""),
                         "section_path": metadata.get("section_path", []),
                         "start_char": ref.get("start_char"),
                         "end_char": ref.get("end_char")})
            identity = json.dumps(item, sort_keys=True, ensure_ascii=False)
            if cid in identities and identities[cid] != identity:
                conflicts.add(cid)
            identities[cid] = identity
            item.update({"origin_run_id": rid, "reused": rid != run["id"]})
            found[cid] = item
    return {
        "items": [found[cid] for cid in requested if cid in found and cid not in conflicts],
        "unavailable_ids": [cid for cid in requested if cid not in found or cid in conflicts],
        "conflicting_ids": [cid for cid in requested if cid in conflicts],
    }

"""Deterministic document scope, resolved only against owner-visible metadata."""
import re
import unicodedata

POLICY = "explicit-document-scope-v1"
_YEAR = r"(?:19|20)\d{2}"
_AUTHOR_YEAR = re.compile(
    r"(?<![a-z0-9_])([a-z][a-z'\-]{1,60})(?:\s+et\s+al\.?)?\s*"
    r"[\(\[,:\-\u2013\u2014]?\s*(" + _YEAR + r")[a-z]?(?!\d)", re.I)
_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/a-z0-9]+", re.I)
_CITATION = re.compile(r"(?<![a-z0-9_])K([a-f0-9]{32})_\d+(?![a-z0-9_])", re.I)
_STOP = {"the", "in", "from", "for", "of", "on", "and", "with", "paper", "study",
         "article", "model", "data", "year", "published", "accepted", "received"}
_BIB_REQUEST = re.compile(r"\b(?:papers?|articles?|authors?|e-?mails?|affiliations?)\b|"
                          r"\u8bba\u6587|\u4f5c\u8005|\u90ae\u7bb1|\u673a\u6784", re.I)
_BROAD = re.compile(r"\b(?:other|all|remaining)\s+(?:papers?|studies|documents?|literature)\b|"
                    r"\u5176\u4ed6\u6587\u732e|\u5176\u4ed6\u8bba\u6587|"
                    r"\u6240\u6709\u8bba\u6587|\u5168\u90e8\u6587\u732e", re.I)

def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", str(text or "")).casefold().split())

def dois(text):
    return {m.group().rstrip(".,;)") for m in _DOI.finditer(normalized(text))}

def resolve_document_scope(query, documents):
    """Never infer identity from chunk text, similarity, or a bibliography citation."""
    query = normalized(query)
    records = {d["id"]: d for d in documents if d.get("id") and d.get("chunks", 0) > 0}
    aliases = {}
    for doc_id, doc in records.items():
        match = _AUTHOR_YEAR.match(normalized(doc.get("title")))
        if match and match.group(1) not in _STOP:
            aliases.setdefault((match.group(1), match.group(2)), set()).add(doc_id)
    requests = []
    for match in _CITATION.finditer(query):
        doc_id = match.group(1)
        requests.append(("citation", match.group(), {doc_id} if doc_id in records else set()))
    for doi in sorted(dois(query)):
        matches = {doc_id for doc_id, doc in records.items()
                   if doi in dois(doc.get("source", "")) or doi in dois(doc.get("title", ""))}
        requests.append(("doi", doi, matches))
    titles = {}
    for doc_id, doc in records.items():
        title = normalized(doc.get("title"))
        if len(title) >= 12 and title in query:
            titles.setdefault(title, set()).add(doc_id)
    requests.extend(("title", title, ids) for title, ids in titles.items())
    names = {name for name, _ in aliases}
    author_query = _CITATION.sub(" ", _DOI.sub(" ", query))
    for match in _AUTHOR_YEAR.finditer(author_query):
        name, year = match.groups()
        if name in _STOP:
            continue
        if name in names or "et al" in match.group() or _BIB_REQUEST.search(query):
            requests.append(("author_year", match.group(), aliases.get((name, year), set())))
    def result(mode, reason, ids=(), unresolved=()):
        ids = sorted(set(ids))
        return {"policy": POLICY, "mode": mode, "reason": reason, "document_ids": ids,
                "documents": [{"id": i, "title": records[i].get("title", "")} for i in ids],
                "unresolved": list(unresolved), "requires_clarification": mode in {"ambiguous", "unresolved"}}
    if not requests:
        return result("all", "no_explicit_document_identity")
    missing = [label for _, label, ids in requests if not ids]
    if missing:
        return result("unresolved", "requested_document_not_in_index", unresolved=missing)
    precise = set().union(*(ids for kind, _, ids in requests if kind != "author_year" and len(ids) == 1))
    resolved, ambiguous = set(), []
    for kind, label, ids in requests:
        if kind == "author_year" and ids & precise:
            resolved.update(ids & precise)
        elif len(ids) == 1:
            resolved.update(ids)
        else:
            ambiguous.append(label)
    if ambiguous:
        return result("ambiguous", "multiple_documents_share_identity", unresolved=ambiguous)
    if _BROAD.search(query):
        return result("all", "explicit_cross_document_request")
    return result("scoped", "explicit_document_identity", resolved)


def scoped_content_query(query, scope, documents):
    """Replace resolved routing identities only; keep content constraints and original query."""
    if scope.get("mode") != "scoped":
        return {"text": query, "identity_spans": []}
    allowed = set(scope["document_ids"])
    docs = [d for d in documents if d.get("id") in allowed]
    aliases = set()
    known_dois = set()
    spans = []
    for doc in docs:
        title = str(doc.get("title") or "")
        if len(title) >= 12:
            spans.extend((m.start(), m.end()) for m in re.finditer(re.escape(title), query, re.I))
        match = _AUTHOR_YEAR.match(normalized(title))
        if match:
            aliases.add(match.groups())
        known_dois.update(dois(doc.get("source", "")) | dois(title))
    for match in _DOI.finditer(query):
        value = match.group().rstrip(".,;)")
        if normalized(value) in known_dois:
            start = match.start()
            prefix = re.search(r"\bdoi\s*:\s*$", query[:start], re.I)
            spans.append((prefix.start() if prefix else start, start + len(value)))
    for match in _AUTHOR_YEAR.finditer(query):
        if tuple(normalized(x) for x in match.groups()) in aliases:
            end = match.end()
            if "(" in match.group() and query[end:end + 1] == ")":
                end += 1
            spans.append((match.start(), end))
    accepted = []
    for start, end in sorted(set(spans), key=lambda x: (-(x[1] - x[0]), x[0])):
        if not any(start < b and end > a for a, b in accepted):
            accepted.append((start, end))
    accepted.sort()
    replacement = "\u8fd9\u7bc7\u6587\u732e" if re.search(r"[\u4e00-\u9fff]", query) else "this paper"
    text = query
    for start, end in reversed(accepted):
        text = text[:start] + replacement + text[end:]
    return {"text": text, "identity_spans": [
        {"start": a, "end": b, "original": query[a:b], "replacement": replacement}
        for a, b in accepted]}

def balanced_candidates(rows, document_ids, limit=50):
    ordered = sorted(rows, key=lambda r: (-r["rrf_score"], r["citation_id"]))
    if not document_ids or len(document_ids) == 1:
        return ordered[:limit]
    buckets = {doc_id: [] for doc_id in document_ids}
    for row in ordered:
        buckets[row["document_id"]].append(row)
    selected = []
    for rank in range(max((len(items) for items in buckets.values()), default=0)):
        for items in buckets.values():
            if rank < len(items):
                selected.append(items[rank])
                if len(selected) == limit:
                    return selected
    return selected

def select_document_coverage(candidates, document_ids, limit):
    """Coverage cannot bypass field, provenance, or score eligibility."""
    eligible = [r for r in candidates if r["selection_reason"] == "outside_result_limit"]
    selected_ids = set()
    if document_ids and len(document_ids) > 1:
        covered = set()
        for row in eligible:
            if row["document_id"] not in covered and len(selected_ids) < limit:
                selected_ids.add(row["citation_id"])
                covered.add(row["document_id"])
    for row in eligible:
        if len(selected_ids) >= limit:
            break
        selected_ids.add(row["citation_id"])
    selected = []
    for row in candidates:
        if row["citation_id"] in selected_ids:
            row["selection_reason"] = "selected"
            selected.append(row)
    requested = list(document_ids or [])
    matched = sorted({r["document_id"] for r in selected} & set(requested))
    return selected, {
        "status": "not_scoped" if not requested else "complete" if len(matched) == len(requested) else "partial",
        "requested_document_ids": requested, "matched_document_ids": matched,
        "missing_document_ids": [i for i in requested if i not in matched],
    }

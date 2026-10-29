"""Retrieval-time passage preparation; immutable source and vectors stay untouched."""
import re

POLICY = "source-focused-bibliography-v1"
_PREFIXED = {
    "literature-qwen512-source-mapped-refinements-v4",
    "literature-qwen512-chart-source-separation-v5",
}
_CATALOG = re.compile(
    # Author names in a scientific question are not a request for metadata.
    r"\bwho\s+(?:(?:is|are|was|were)\s+(?:the\s+)?(?:authors?|corresponding\s+author)"
    r"|(?:wrote|authored|published)\b)|"
    r"\b(?:list|name|identify|show)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?authors?\b|"
    r"\b(?:what|which|where|list|show|give|provide|identify|find)\b[^?;\n]{0,140}"
    r"\b(?:affiliations?|institutions?|e-?mails?|email\s+addresses?|"
    r"contact\s+(?:details?|information|addresses?)|bibliograph(?:y|ic)|"
    r"publication\s+date|acceptance\s+date|submission\s+date)\b|"
    r"\b(?:affiliations?|e-?mails?|publication\s+date)\s+(?:of|for)\b|"
    r"\bwhich\s+(?:university|universities|institution)\b|"
    r"\bwhen\b[^?;\n]{0,100}\b(?:received|accepted|published|submitted)\b|"
    r"(?:\u4f5c\u8005\u540d\u5355|\u4f5c\u8005\u59d3\u540d|\u4f5c\u8005\u4fe1\u606f|"
    r"\u901a\u8baf\u4f5c\u8005|\u4f5c\u8005\u673a\u6784|\u4f5c\u8005\u5355\u4f4d|"
    r"\u90ae\u7bb1|\u7535\u5b50\u90ae\u4ef6|\u8054\u7cfb\u65b9\u5f0f|"
    r"\u8054\u7cfb\u5730\u5740|\u6536\u7a3f\u65e5\u671f|\u63a5\u53d7\u65e5\u671f|"
    r"\u53d1\u8868\u65e5\u671f|\u4e66\u76ee\u4fe1\u606f)"
    r"[^\u3002\uff1f?\n]{0,30}(?:\u4ec0\u4e48|\u54ea|\u8c01|\u591a\u5c11|\uff1f|\?)|"
    r"(?:\u4f5c\u8005|\u673a\u6784|\u5355\u4f4d)(?:\u662f\u8c01|\u6709\u54ea\u4e9b|"
    r"\u662f\u54ea\u4e9b|\u662f\u54ea|\u53eb\u4ec0\u4e48|\u540d\u5355)|"
    r"(?:\u5217\u51fa|\u663e\u793a|\u63d0\u4f9b|\u67e5\u627e)[^\u3002\uff1f?\n]{0,30}"
    r"(?:\u4f5c\u8005|\u673a\u6784|\u5355\u4f4d|\u90ae\u7bb1|\u8054\u7cfb\u65b9\u5f0f)|"
    r"(?:\u4ec0\u4e48\u65f6\u5019|\u4f55\u65f6)[^\u3002\uff1f?\n]{0,20}"
    r"(?:\u6536\u7a3f|\u63a5\u53d7|\u53d1\u8868)|"
    r"\u54ea\u6240\u5927\u5b66",
    re.I,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_INSTITUTION = re.compile(r"\b(?:Department|Faculty|University|Institute|College|School)\b")
_NAME_WORD = re.compile(r"[^\W\d_]+(?:[-\u2010-\u2015'][^\W\d_]+)*", re.UNICODE)
_ADDRESS_WORDS = {"of", "and", "the", "for", "in", "at", "de", "du", "la", "del"}
_SCIENCE_UNIT = re.compile(
    r"\d\s*(?:%|km\b|m\b|ma\b|mpa\b|g\s*/|kg\b|mg\b|mgal\b|"
    r"degrees?\b|\u00b0)", re.I)


def catalog_requested(query):
    """An explicit metadata question opens, rather than removes, that evidence lane."""
    return bool(_CATALOG.search(query))


def bibliography_role(row):
    """Only recognize unambiguous front-page metadata; unknowns remain evidence."""
    metadata = row.get("metadata") or {}
    if metadata.get("chunker") not in _PREFIXED:
        return None
    pages = [source.get("page") for source in metadata.get("sources", [])]
    if not pages or any(type(page) is not int or page not in (1, 2) for page in pages):
        return None
    source = row.get("text", "")
    text = " ".join(source.replace("\\_", "_").split())
    path = metadata.get("section_path") or []
    if (len(path) == 1 and source.startswith(path[0]) and len(text) < 2000
            and re.search(r"\bReceived\s*:", text)
            and re.search(r"\bAccepted\s*:", text)
            and not re.search(r"\bAbstract\b", text, re.I)):
        # Restrict to title + authors + publication dates + copyright paragraphs.
        paragraphs = [p.strip() for p in source.split("\n\n") if p.strip()]
        if (len(paragraphs) in (3, 4)
                and paragraphs[0] == path[0]
                and all(p.startswith(("Received:", "\u00a9", "Copyright"))
                        for p in paragraphs[2:])
                and not _SCIENCE_UNIT.search(paragraphs[1])):
            names = _NAME_WORD.findall(paragraphs[1])
            if names and all(w[0].isupper() or w.lower() in _ADDRESS_WORDS for w in names):
                return "publication_metadata"
    if metadata.get("kind") != "page_footnote" or len(text) > 600 or _SCIENCE_UNIT.search(text):
        return None
    emails = _EMAIL.findall(text)
    if emails:
        rest = _EMAIL.sub("", text)
        words = _NAME_WORD.findall(rest)
        if (len(words) <= 12 and all(w[0].isupper() or w.lower() in _ADDRESS_WORDS for w in words)
                and not re.search(r"\d", rest)):
            return "author_contact"
        return None
    if _INSTITUTION.search(text) and "," in text:
        words = _NAME_WORD.findall(text)
        if (words and len(words) <= 70
                and all(w[0].isupper() or w.lower() in _ADDRESS_WORDS for w in words)):
            return "author_affiliation"
    return None


def prepare_passage(row, metadata_requested=False):
    """Remove only a known generated prefix; retain repeated table headers/units."""
    metadata = row.get("metadata") or {}
    passage = metadata.get("embedding_text") or row["text"]
    policy = "catalog-context-v1" if metadata_requested else "unchanged-existing-input"
    if not metadata_requested and metadata.get("chunker") in _PREFIXED and metadata.get("embedding_text"):
        prefix = row["title"] + "\n" + " / ".join(metadata.get("section_path") or []) + "\n\n"
        if passage.startswith(prefix):
            passage = passage[len(prefix):]
            policy = POLICY
            # Related-section labels are navigation metadata, not source evidence.
            # Their following caption, table headers and footnotes are retained.
            line, newline, rest = passage.partition("\n")
            related = metadata.get("related_sections") or []
            if (newline and related and line.startswith("Referenced in (not physical ownership): ")
                    and all(" / ".join(path) in line for path in related[:2])):
                passage = rest
    # Never substitute an empty passage or rewrite the source/citation coordinates.
    return {"rerank_input": passage if passage.strip() else row["text"],
            "rerank_input_policy": policy,
            "evidence_role": bibliography_role(row) or "source_content"}


def selection_reason(row, threshold, metadata_requested, selected=False, requested_fields=()):
    if requested_fields and not any(supports_catalog_field(row, field) for field in requested_fields):
        return "requested_metadata_missing"
    if row["evidence_role"] != "source_content" and not metadata_requested:
        return "bibliographic_not_requested"
    if row["rerank_score"] < threshold:
        return "below_threshold"
    return "selected" if selected else "outside_result_limit"


NUMERIC_ORDER_POLICY = {
    "id": "same-document-numeric-caption-tie-v1",
    "max_score_gap": 0.02,
    "calibrated": False,
    "method": "For an explicit value question, a same-document source with a matching-unit value may precede a near-tied caption lacking that value. Scores and eligibility thresholds stay unchanged.",
}
_VALUE_REQUEST = re.compile(
    r"\b(?:what|how\s+(?:much|many|deep|high|long|thick|far))\b|"
    r"\u591a\u5c11|\u51e0|\u6570\u503c|\u4f30\u8ba1\u503c|\u4f30\u7b97\u503c", re.I)
_CONCEPT_REQUEST = re.compile(
    r"\b(?:why|how\s+(?:does|do|can)|definition|meaning|explain|mechanism)\b|"
    r"\u4e3a\u4ec0\u4e48|\u539f\u7406|\u5b9a\u4e49|\u673a\u5236|\u89e3\u91ca", re.I)
_FIGURE_REQUEST = re.compile(r"\b(?:fig(?:ure)?s?\.?)\s*\d+|\u56fe\s*\d+", re.I)
_NUMBER = r"(?<![\w.])[-+]?\d+(?:\.\d+)?\s*"
_QUANTITIES = [
    (re.compile(r"\b(?:depths?|thickness(?:es)?|heights?|elevations?|distances?|lengths?|widths?)\b|\u6df1\u5ea6|\u539a\u5ea6|\u9ad8\u5ea6|\u8ddd\u79bb",re.I),
     re.compile(_NUMBER+r"(?:mm|cm|km|m|kilomet(?:er|re)s?|met(?:er|re)s?)\b|"+_NUMBER+r"(?:\u5343\u7c73|\u7c73|\u5398\u7c73)",re.I)),
    (re.compile(r"\b(?:densit(?:y|ies))\b|\u5bc6\u5ea6",re.I),
     re.compile(_NUMBER+r"(?:g\s*/\s*cm|kg\s*/\s*m|g\s+cm|kg\s+m)",re.I)),
    (re.compile(r"\b(?:porosit(?:y|ies)|percent(?:age)?s?)\b|\u5b54\u9699\u5ea6|\u767e\u5206\u6bd4",re.I),
     re.compile(_NUMBER+r"(?:%|percent\b)",re.I)),
    (re.compile(r"\bpressures?\b|\u538b\u529b",re.I),
     re.compile(_NUMBER+r"(?:[kmg]?pa|bars?|psi)\b",re.I)),
    (re.compile(r"\b(?:age|ages|ma|ga)\b|\u5e74\u4ee3|\u5e74\u9f84",re.I),
     re.compile(_NUMBER+r"(?:[kmg]a|million\s+years?|billion\s+years?)\b",re.I)),
]
_VISUAL_KINDS = {"image","figure","chart","caption","image_caption","figure_caption"}


def prioritize_numeric_evidence(candidates, query, threshold):
    """A narrow, inspectable near-tie rule; never fabricates a score or drops a hit."""
    rows = list(candidates)
    if not _VALUE_REQUEST.search(query) or _CONCEPT_REQUEST.search(query) or _FIGURE_REQUEST.search(query):
        return rows
    units = [unit for terms,unit in _QUANTITIES if terms.search(query)]
    if not units:
        return rows
    def contains_value(row):
        # Only source-derived passage text, not document-title numbers or figure IDs.
        text=(row.get("metadata") or {}).get("retrieval_text") or row["text"]
        return any(unit.search(text) for unit in units)
    for caption in candidates:
        if ((caption.get("metadata") or {}).get("kind") not in _VISUAL_KINDS
                or contains_value(caption) or caption["rerank_score"] < threshold):
            continue
        position=rows.index(caption)
        eligible=[row for row in rows[position+1:]
                  if row["document_id"]==caption["document_id"]
                  and row.get("evidence_role")=="source_content"
                  and (row.get("metadata") or {}).get("kind") not in _VISUAL_KINDS
                  and row["rerank_score"]>=threshold
                  and 0 <= caption["rerank_score"]-row["rerank_score"] <= NUMERIC_ORDER_POLICY["max_score_gap"]
                  and contains_value(row)]
        if eligible:
            best=eligible[0]
            rows.remove(best)
            rows.insert(position,best)
            best["evidence_order_reason"]="numeric_source_before_caption"
            caption["evidence_order_reason"]="supporting_caption"
    return rows


_CATALOG_FIELDS = {
    "affiliation": re.compile(r"\b(?:affiliations?|institutions?|universit(?:y|ies)|departments?)\b|\u673a\u6784|\u5355\u4f4d|\u5927\u5b66",re.I),
    "contact": re.compile(r"\b(?:e-?mails?|contact|correspondence)\b|\u90ae\u7bb1|\u90ae\u4ef6|\u8054\u7cfb\u65b9\u5f0f",re.I),
}
_MIXED_RESEARCH = re.compile(
    r"\b(?:depths?|densit(?:y|ies)|porosit(?:y|ies)|pressures?|models?|methods?|"
    r"results?|findings?|conclusions?|equations?|figures?|tables?|datasets?)\b|"
    r"\u6df1\u5ea6|\u5bc6\u5ea6|\u5b54\u9699|\u538b\u529b|\u6a21\u578b|"
    r"\u65b9\u6cd5|\u7ed3\u679c|\u7ed3\u8bba|\u516c\u5f0f|\u6570\u636e",re.I)


def requested_catalog_fields(query):
    """Conservative field routing. Mixed scientific questions keep both lanes."""
    if not catalog_requested(query) or _MIXED_RESEARCH.search(query):
        return ()
    return tuple(name for name,pattern in _CATALOG_FIELDS.items() if pattern.search(query))


def supports_catalog_field(row, field):
    """Require the requested fact in the source, not merely in a title prefix."""
    text=row["text"].replace("\\_", "_")
    if field=="contact":
        return bool(_EMAIL.search(text))
    if field!="affiliation":
        return False
    if row.get("evidence_role")=="author_affiliation":
        return True
    # Supports a title/authors/affiliation frontmatter chunk without accepting a
    # scientific paragraph that merely mentions a university.
    for paragraph in text.split("\n\n"):
        paragraph=" ".join(paragraph.split())
        if not paragraph or len(paragraph)>600 or _SCIENCE_UNIT.search(paragraph):
            continue
        if _INSTITUTION.search(paragraph) and "," in paragraph:
            words=_NAME_WORD.findall(paragraph)
            if words and all(word[0].isupper() or word.lower() in _ADDRESS_WORDS for word in words):
                return True
    return False

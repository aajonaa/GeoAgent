"""Versioned literature blocks and source-bound Qwen document chunks.

Parser order is preserved, never reconstructed by sorting bounding boxes.
Generated visual descriptions and page furniture are retained but not indexed.
"""
from functools import lru_cache
from hashlib import sha256
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re

VERSION = "literature-blocks-v2"
POLICY = "literature-qwen512-source-bound-table-fragments-v6"
MAX_TOKENS = 512
OVERLAP = 64
EXCLUDED = {"header", "footer", "page_number", "ref_text", "reference", "references"}
HEADINGS = {"doc_title", "paragraph_title", "title", "heading", "section_header"}
SUPPORTED = EXCLUDED | HEADINGS | {"text", "paragraph", "list", "image", "figure", "chart", "table",
    "equation", "formula", "interline_equation", "page_footnote", "footnote", "code", "caption", "aside_text"}


class LiteratureError(ValueError):
    pass


def digest(value):
    return sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "object"}:
            self.depth += 1
        elif not self.depth and tag in {"p", "br", "div", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "iframe", "object"} and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)


def plain(value):
    if not isinstance(value, str):
        return ""
    if re.search(r"<\/?[A-Za-z][^>]*>", value):
        parser = PlainHTML()
        parser.feed(value)
        value = "".join(parser.parts)
    return value.strip()


def table_body(content):
    """Preserve cell merge metadata; ambiguous wide tables require review."""
    if re.match(r"\s*<table(?:\s|>)", content, re.I):
        from ..team.pdf_content import TableParser
        parser = TableParser()
        parser.feed(content)
        parser.close()
        rows = parser.rows
        if not rows:
            raise LiteratureError("Table has no readable cells")
        strings = [" | ".join(cell["text"].strip().replace("\n", " ") for cell in row) for row in rows]
        headers = [strings[i] for i, row in enumerate(rows) if any(cell["header"] for cell in row)]
        # Never invent a header when the parser did not identify one.
        return "\n".join(strings), {"rows": rows, "header": "\n".join(headers),
            "merged_cells": any(cell["rowspan"] > 1 or cell["colspan"] > 1 for row in rows for cell in row)}
    lines = content.strip().splitlines()
    header = ""
    for i, line in enumerate(lines):
        if i and re.fullmatch(r"[\s|:\-]+", line) and "-" in line:
            header = "\n".join(lines[:i+1])
            break
    return content.strip(), {"header": header, "merged_cells": False, "format": "markdown"}


def _parser_document(structured, *, title, original_sha256, raw_sha256, parser=None, page_count=None):
    if not isinstance(structured, dict) or not isinstance(structured.get("pages"), list):
        raise LiteratureError("Structured pages are required; Markdown-only indexing is a separate legacy path")
    pages = structured["pages"]
    if not pages or len(pages) > 10000:
        raise LiteratureError("Invalid structured page count")
    blocks, issues, stack, seen_pages = [], [], [], set()
    for page in pages:
        page_idx = page.get("page_idx") if isinstance(page, dict) else None
        if type(page_idx) is not int or page_idx < 0 or page_idx in seen_pages:
            raise LiteratureError("Missing or duplicate original page index")
        seen_pages.add(page_idx)
        if not isinstance(page.get("blocks"), list):
            raise LiteratureError("Missing structured blocks")
        if not page["blocks"]:
            issues.append({"severity": "warning", "code": "empty_page", "page": page_idx+1})
        for ordinal, source in enumerate(page["blocks"]):
            if not isinstance(source, dict):
                raise LiteratureError("Malformed source block")
            kind = source.get("type", "unknown")
            bid = "p%d-b%d" % (page_idx+1, ordinal+1)
            content = source.get("content", "")
            if not isinstance(content, str):
                raise LiteratureError("Unsupported structured content version at " + bid)
            captions = [plain(v.get("content")) for v in source.get("captions", []) if isinstance(v, dict)]
            notes = [plain(v.get("content")) for v in source.get("footnotes", []) if isinstance(v, dict)]
            captions = [v for v in captions if v]
            notes = [v for v in notes if v]
            bbox = source.get("bbox")
            valid_box = (isinstance(bbox, list) and len(bbox) == 4 and
                         all(type(v) in (int, float) and math.isfinite(v) for v in bbox) and
                         bbox[2] >= bbox[0] and bbox[3] >= bbox[1])
            loc = {"page": page_idx+1, "page_idx": page_idx, "block_id": bid,
                   "bbox": bbox if valid_box else None,
                   "coordinate_space": "normalized_parser" if valid_box and all(0 <= v <= 1 for v in bbox) else "parser_native" if valid_box else None}
            raw = content
            derived, table = None, None
            if kind in {"image", "figure", "chart"}:
                derived = content.strip() or None
                content = "\n".join(captions + notes)
            elif kind == "table":
                content, table = table_body(content)
                content = "\n".join(captions + [content] + notes)
                if table["merged_cells"]:
                    issues.append({"severity": "warning", "code": "merged_table_cells", "block_id": bid})
                if not table["header"]:
                    issues.append({"severity": "warning", "code": "table_header_unidentified", "block_id": bid})
            else:
                content = plain(content)
            if "data:image/" in content or re.search(r"[A-Za-z0-9+/]{500,}={0,2}", content):
                raise LiteratureError("Encoded binary payload in source block " + bid)
            if "\x00" in content:
                raise LiteratureError("NUL in source block " + bid)
            if kind not in SUPPORTED:
                issues.append({"severity": "error", "code": "unsupported_block_type", "block_id": bid, "type": kind})
            if kind in HEADINGS:
                level = source.get("level", 1 if kind == "doc_title" else 2)
                level = level if type(level) is int and 1 <= level <= 12 else 2
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, content))
            exclusion = ("unsupported_block_type" if kind not in SUPPORTED else "page_furniture_or_bibliography" if kind in EXCLUDED or source.get("sub_type") == "ref_text"
                         else "no_extracted_text" if not content.strip() else None)
            blocks.append({"id": bid, "kind": kind, "text": content, "raw_text": raw if kind not in {"image", "figure", "chart"} else "",
                "derived_description": derived, "derived_is_source": False,
                "source": loc, "source_role": "unverified_marginal_text" if kind == "aside_text" else "parser_source", "section_path": [v for _, v in stack], "captions": captions,
                "footnotes": notes, "table": table, "indexable": exclusion is None,
                "excluded_reason": exclusion, "start_char": None, "end_char": None})
    if page_count is not None and (type(page_count) is not int or len(pages) != page_count or seen_pages != set(range(page_count))):
        raise LiteratureError("Structured pages do not cover the original PDF")
    body = ""
    for block in blocks:
        if block["indexable"]:
            block["start_char"] = len(body)
            body += block["text"] + "\n\n"
            block["end_char"] = len(body)
    if not body.strip() and not any(v["severity"] == "error" for v in issues):
        raise LiteratureError("Structured retrieval body must contain source text; original retained")
    issues.append({"severity": "warning", "code": "human_reading_order_and_numeric_review_required"})
    return {"schema": VERSION, "title": title, "body": body, "sha256": digest(body),
        "original_sha256": original_sha256, "raw_sha256": raw_sha256,
        "structure_sha256": digest(json.dumps(structured, sort_keys=True, ensure_ascii=False)),
        "parser": parser or {}, "pages": len(pages), "blocks": blocks, "issues": issues,
        "quality_status": "blocked" if any(v["severity"] == "error" for v in issues) else "manual_review_required",
        "reading_order": "parser_order_preserved_not_independently_verified",
        "policy": POLICY, "automatic_indexing": False}


def document(*args, **kwargs):
    from .refinement import refine_document
    from .literature_segments import attach_segments
    return attach_segments(refine_document(_parser_document(*args, **kwargs)))


@lru_cache(maxsize=1)
def tokenizer():
    from tokenizers import Tokenizer
    path = Path(os.environ["GEOTOOL_KNOWLEDGE_TOKENIZER"])
    raw = path.read_bytes()
    expected = os.environ.get("GEOTOOL_KNOWLEDGE_TOKENIZER_SHA256")
    if not expected or digest(raw) != expected:
        raise LiteratureError("Pinned Qwen tokenizer integrity check failed")
    value = Tokenizer.from_str(raw.decode("utf-8"))
    value.no_truncation()
    value.no_padding()
    return value, expected


def split(doc, tok=None, tokenizer_sha=None):
    from .refinement import split_refined
    from .literature_segments import split_segmented
    if len(doc["body"]) > 120000:
        return split_segmented(doc, split_refined, tok, tokenizer_sha)
    return split_refined(doc, tok, tokenizer_sha)


class LiteratureIndexMixin:
    def ingest_literature(self, package, source):
        from .store import vector, KnowledgeError, LITERATURE_KEY
        from .limits import account_limits
        import uuid
        doc = package["document"]
        title, text, sha = doc["title"], doc["body"], doc["sha256"]
        if not isinstance(title, str) or not title.strip() or len(title) > 160 or not isinstance(source, str) or len(source) > 1000:
            raise ValueError("Invalid literature title or source")
        if doc["quality_status"] == "blocked" or digest(text) != sha:
            raise KnowledgeError("Literature quality or source integrity check failed")
        parts = package["chunks"]
        from .literature_segments import validate_chunk_segments, segment_summary
        manifest = validate_chunk_segments(doc, parts)
        details = {"segmentation": segment_summary(manifest, len(text))} if manifest else {}
        covered = 0
        for part in parts:
            a, b = part["start_char"], part["end_char"]
            m = part["metadata"]
            if (type(a) is not int or type(b) is not int or not 0 <= a < b <= len(text) or a > covered or b <= covered
                    or part["text"] != text[a:b] or m["chunker"] != POLICY or not 0 < m["token_count"] <= MAX_TOKENS
                    or digest(m["embedding_text"]) != m["embedding_input_sha256"]):
                raise KnowledgeError("Literature chunk source or input integrity mismatch")
            covered = b
        if covered != len(text) or not parts or (manifest is None and len(parts) > 1000):
            raise KnowledgeError("Literature chunk coverage is incomplete")
        existing = next((d for d in self.documents() if d["title"] == title.strip() and d["sha256"] == sha and d["embedding_key"] == LITERATURE_KEY and d["chunks"]), None)
        if existing:
            return {**existing, **details, "reused": True}
        values = self.encoder.embed([p["metadata"]["embedding_text"] for p in parts])
        if len(values) != len(parts):
            raise KnowledgeError("Incomplete literature embeddings")
        encoded = [vector(v) for v in values]
        from .store import lexical
        identity = uuid.uuid4().hex
        with self.connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("knowledge:"+self.owner_id,))
            duplicate = conn.execute("SELECT id FROM geotool_knowledge.documents WHERE owner_id=%s AND title=%s AND sha256=%s AND embedding_key=%s", (self.owner_id,title.strip(),sha,LITERATURE_KEY)).fetchone()
            if duplicate:
                identity = duplicate["id"]
                n = conn.execute("SELECT count(*) AS n FROM geotool_knowledge.chunks_qwen3_1024 WHERE owner_id=%s AND document_id=%s", (self.owner_id,identity)).fetchone()["n"]
                if n:
                    return {"id":identity,"chunks":n,"reused":True,"embedding_key":LITERATURE_KEY,**details}
            else:
                n = conn.execute("SELECT count(*) AS n FROM geotool_knowledge.documents WHERE owner_id=%s", (self.owner_id,)).fetchone()["n"]
                capacity = account_limits(self.owner_id)["max_documents"]
                if n >= capacity:
                    raise ValueError(f"Knowledge capacity: {capacity} documents per user")
                conn.execute("INSERT INTO geotool_knowledge.documents (id,owner_id,title,source,sha256,body,embedding_key) VALUES(%s,%s,%s,%s,%s,%s,%s)", (identity,self.owner_id,title.strip(),source,sha,text,LITERATURE_KEY))
            for ordinal, (part, value) in enumerate(zip(parts, encoded), 1):
                conn.execute("""INSERT INTO geotool_knowledge.chunks_qwen3_1024
                    (id,owner_id,document_id,ordinal,start_char,end_char,body,lexical,embedding,metadata)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,to_tsvector('simple',%s),%s::vector,%s::jsonb)""",
                    ("K"+identity+"_"+str(ordinal),self.owner_id,identity,ordinal,part["start_char"],part["end_char"],part["text"],lexical(part["metadata"]["embedding_text"]),value,json.dumps(part["metadata"])))
        return {"id":identity,"title":title.strip(),"sha256":sha,"chunks":len(parts),"reused":False,"embedding_key":LITERATURE_KEY,"chunker":POLICY,**details}

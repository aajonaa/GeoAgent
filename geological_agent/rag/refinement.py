"""Traceable retrieval derivatives. Parser text and PDF locations stay immutable."""
import re

POLICY = "literature-qwen512-source-bound-table-fragments-v6"
MATH = re.compile(r"\$\$[^$]+\$\$|(?<![\\$])\$(?!\$)[^$\n]+(?<!\\)\$|\\\([^\n]+?\\\)|\\\[[\s\S]+?\\\]")
NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?"
NUMERIC = re.compile(r"(?<![\w.])" + NUMBER + r"(?:\s*(?:\u00b1|\+/-|\u2013|\u2014)\s*" + NUMBER + r")?(?:\s*(?:%|ppm\b|ppb\b|wt\s*%|mg/kg\b|g/t\b|km\b|mm\b|cm\b|Ma\b|Ga\b|MPa\b|GPa\b|\u00b0C|seconds\b|s\b|m\b))?")
WORD = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
REF = re.compile(r"\b(Table[s]?|Fig(?:ure)?s?\.?)\s+(S?\d+[A-Za-z]?)(?:\s*(?:,|and|&)\s*(S?\d+[A-Za-z]?))?\b", re.I)


def normalize_math(text):
    """Only explicit math whitespace; never join separated integer digits."""
    changes, warnings = [], []
    for match in MATH.finditer(text):
        raw = match.group()
        # Currency delimiters are not formula evidence.
        if not re.search(r"[=<>]|\\(?:frac|sqrt|sum|times|cdot)\b", raw):
            continue
        ambiguous = bool(re.search(r"\d[ \t]+\d", raw))
        unbalanced = raw.count("(") != raw.count(")") or raw.count("{") != raw.count("}")
        if ambiguous or unbalanced:
            warnings.append({"code": "ambiguous_formula", "start": match.start(), "end": match.end(), "raw": raw})
            continue
        value = re.sub(r"\\(?:,|;|!|quad\b|qquad\b)|~", " ", raw)
        value = re.sub(r"(?<![\d.])(\d+)[ \t]*\.[ \t]*(\d+)(?![\d.])", r"\1.\2", value)
        value = re.sub(r"[ \t]+", " ", value)
        if value != raw:
            changes.append({"start": match.start(), "end": match.end(), "raw": raw,
                            "text": value, "rule": "explicit_math_whitespace"})
    return changes, warnings


def table_grid(rows):
    """Expand explicit row spans; never fill an unmarked empty cell."""
    from .literature import LiteratureError
    grid = [[] for _ in rows]
    for r, row in enumerate(rows):
        col = 0
        for cell_index, cell in enumerate(row):
            while col < len(grid[r]) and grid[r][col] is not None:
                col += 1
            rs, cs = cell.get("rowspan", 1), cell.get("colspan", 1)
            if r + rs > len(rows) or col + cs > 100:
                raise LiteratureError("Table merge geometry exceeds the real row/column bounds")
            for target_row in range(r, r + rs):
                while len(grid[target_row]) < col + cs:
                    grid[target_row].append(None)
                for target_col in range(col, col + cs):
                    if grid[target_row][target_col] is not None:
                        raise LiteratureError("Overlapping table merge geometry")
                    grid[target_row][target_col] = {
                        "text": cell["text"].strip().replace("\n", " ") if target_col == col else "",
                        "origin_row": r, "origin_cell": cell_index,
                        "rowspan": rs, "colspan": cs, "column_offset": target_col - col,
                        "inherited_row": target_row != r, "header": bool(cell.get("header"))}
            col += cs
    width = max((len(row) for row in grid), default=0)
    for row in grid:
        row.extend([None] * (width - len(row)))
    return grid


def apply_changes(text, changes, start=0, end=None):
    end = len(text) if end is None else end
    out, cursor = [], start
    for change in changes:
        a, b = change["start"], change["end"]
        if start <= a < b <= end:
            out.extend([text[cursor:a], change["text"]])
            cursor = b
    out.append(text[cursor:end])
    return "".join(out)


def reference_key(kind, number):
    return ("table" if kind.lower().startswith("table") else "figure", number.lower())


def refine_document(doc):
    """Enrich a newly produced document without replacing its canonical source body."""
    from .literature import LiteratureError, digest
    targets = {}
    for block in doc["blocks"]:
        block["physical_section_path"] = list(block["section_path"])
        block["references_from"] = []
        changes = []
        table = block.get("table")
        if table and table.get("rows"):
            rows = table["rows"]
            grid = table_grid(rows)
            raw_lines = [" | ".join(c["text"].strip().replace("\n", " ") for c in row) for row in rows]
            raw_body = "\n".join(raw_lines)
            if block["text"].count(raw_body) != 1:
                raise LiteratureError("Ambiguous table-to-source mapping at " + block["id"])
            cursor = block["text"].index(raw_body)
            row_maps = []
            for i, (raw, row) in enumerate(zip(raw_lines, grid)):
                expanded = " | ".join(c["text"] if c else "" for c in row)
                entry = {"start": cursor, "end": cursor + len(raw), "raw": raw, "text": expanded,
                         "rule": "explicit_table_spans", "row": i,
                         "origins": [{k: v for k, v in cell.items() if k != "text"} if cell else None for cell in row]}
                row_maps.append(entry)
                if expanded != raw:
                    changes.append(entry)
                cursor += len(raw) + 1
            table.update(grid=grid, row_sources=row_maps,
                         leading_row_context=" | ".join(c["text"] if c else "" for c in grid[0]))
        # Formula edits in a transformed row are incorporated into that row's map.
        formula_changes, warnings = normalize_math(block["text"])
        for change in changes:
            inner, _ = normalize_math(change["text"])
            change["text"] = apply_changes(change["text"], inner)
        changes.extend(c for c in formula_changes if not any(e["start"] <= c["start"] and c["end"] <= e["end"] for e in changes))
        changes.sort(key=lambda c: c["start"])
        block["retrieval_transformations"] = changes
        block["retrieval_text"] = apply_changes(block["text"], changes)
        block["retrieval_is_verbatim"] = not changes
        for warning in warnings:
            doc["issues"].append({**warning, "severity": "warning", "block_id": block["id"]})
        if block["kind"] in {"table", "image", "figure", "chart"}:
            for caption in block["captions"]:
                match = REF.match(caption.lstrip(" *"))
                if match:
                    targets.setdefault(reference_key(match[1], match[2]), []).append(block)
                    block["caption_identity"] = reference_key(match[1], match[2])
                    break
    for block in doc["blocks"]:
        if not block["indexable"] or block["kind"] not in {"text", "paragraph", "list"}:
            continue
        for match in REF.finditer(block["text"]):
            for number in (match[2], match[3]):
                if number is None:
                    continue
                matches = targets.get(reference_key(match[1], number), [])
                if len(matches) != 1:
                    if len(matches) > 1:
                        doc["issues"].append({"severity": "warning", "code": "ambiguous_caption_reference", "block_id": block["id"]})
                    continue
                matches[0]["references_from"].append({"source": block["source"],
                    "section_path": block["section_path"], "start": match.start(), "end": match.end(),
                    "text": match.group(), "context": block["text"][max(0, match.start()-70):match.end()+140]})
    doc["policy"] = POLICY
    doc["refinement"] = {"version": POLICY, "source_body_sha256": digest(doc["body"]),
                         "derived_text_is_execution_proof": False, "formula_policy": "whitespace_only_no_digit_inference"}
    return doc


def protected_spans(text):
    spans = sorted((m.start(), m.end()) for pattern in (MATH, NUMERIC, WORD) for m in pattern.finditer(text))
    merged = []
    for a, b in spans:
        if merged and a < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def safe_boundary(spans, position, *, forward=False):
    for a, b in spans:
        if a < position < b:
            return b if forward else a
        if a >= position:
            break
    return position


def split_refined(doc, tok=None, tokenizer_sha=None):
    from .literature import LiteratureError, tokenizer, digest, MAX_TOKENS, OVERLAP, HEADINGS, VERSION
    if doc["quality_status"] == "blocked":
        raise LiteratureError("Unsupported blocks require review before indexing")
    if tok is None:
        tok, tokenizer_sha = tokenizer()
    def count(value):
        return len(tok.encode(value, add_special_tokens=False).ids)
    groups, pending, narrative = [], [], {"text", "paragraph"}
    for block in doc["blocks"]:
        if not block["indexable"]:
            if pending:
                groups.append(pending)
                pending = []
            continue
        compatible = (pending and block["kind"] in narrative
            and all(b["kind"] in narrative | HEADINGS for b in pending)
            and block["source"]["page"] == pending[-1]["source"]["page"]
            and block["section_path"] == pending[-1]["section_path"]
            and block["start_char"] == pending[-1]["end_char"])
        if not compatible and pending:
            groups.append(pending)
            pending = []
        pending.append(block)
    if pending:
        groups.append(pending)
    parts, text = [], doc["body"]
    spans = protected_spans(text)
    for group in groups:
        block = group[0]
        kind = "text" if len(group) > 1 else block["kind"]
        base = doc["title"] + "\n" + " / ".join(block["section_path"]) + "\n\n"
        related = []
        for ref in block.get("references_from", []):
            if ref["section_path"] not in related:
                related.append(ref["section_path"])
        if related:
            base += "Referenced in (not physical ownership): " + "; ".join(" / ".join(p) for p in related[:2]) + "\n"
        repeated = []
        table = block.get("table")
        if table:
            for value in block["captions"] + [table["header"] or table.get("leading_row_context", "")] + block["footnotes"]:
                value = apply_changes(value, normalize_math(value)[0]).strip()
                if not value or any(value in other for other in repeated):
                    continue
                repeated = [other for other in repeated if other not in value]
                repeated.append(value)
        deferred_context = []
        # Context is a retrieval derivative; its full source remains in the table.
        # Reserve room for source cells instead of repeating an unbounded caption.
        while table and repeated and count(base + "\n".join(repeated)) > MAX_TOKENS // 2:
            deferred_context.append(digest(repeated.pop()))
        if count(base + "\n".join(repeated)) >= MAX_TOKENS - 32:
            raise LiteratureError("Title, section or table header exceeds chunk budget at " + block["id"])
        changes = [{**c, "start": c["start"] + b["start_char"], "end": c["end"] + b["start_char"], "block_id": b["id"]}
                   for b in group for c in b.get("retrieval_transformations", [])]
        def embedding_input(a, b):
            derived = apply_changes(text, changes, a, b)
            extras = [value for value in repeated if value not in derived]
            return base + ("\n".join(extras) + "\n" if extras else "") + derived
        start, finish = group[0]["start_char"], group[-1]["end_char"]
        first, previous_end = start, start
        while start < finish:
            if count(embedding_input(start, finish)) <= MAX_TOKENS:
                end = finish
            elif kind == "table":
                end = start
                for match in re.finditer("\n", text[start:finish]):
                    candidate = start + match.end()
                    if count(embedding_input(start, candidate)) > MAX_TOKENS:
                        break
                    end = candidate
                if end == start:
                    from .table_fragments import fragment_end
                    end = fragment_end(text, start, finish, embedding_input, count, spans, MAX_TOKENS)
            else:
                low, high = start + 1, finish
                while low < high:
                    mid = (low + high + 1) // 2
                    if count(embedding_input(start, mid)) <= MAX_TOKENS:
                        low = mid
                    else:
                        high = mid - 1
                end = safe_boundary(spans, low)
                # Inspect punctuation against the COMPLETE source, never an artificial slice end.
                boundaries = [m.end() for m in re.finditer(r"\n|[.!?\u3002\uff01\uff1f]", text[start + (end-start)//2:end])]
                origin = start + (end-start)//2
                boundaries = [origin + p for p in boundaries]
                boundaries = [p for p in boundaries if safe_boundary(spans, p) == p
                    and (text[p-1] == "\n" or p == len(text) or text[p].isspace() or text[p-1] in "\u3002\uff01\uff1f")]
                if boundaries:
                    end = boundaries[-1]
            embedding_text = embedding_input(start, end)
            if end <= start or end <= previous_end or count(embedding_text) > MAX_TOKENS:
                raise LiteratureError("Chunk cannot progress without splitting a number, formula or table row at " + block["id"])
            source_text = text[start:end]
            contributing = [b for b in group if b["start_char"] < end and b["end_char"] > start]
            used_changes = [c for c in changes if start <= c["start"] < c["end"] <= end]
            retrieval_text = apply_changes(text, used_changes, start, end)
            header = table["header"] if table else ""
            table_details = {}
            if table:
                from .table_fragments import source_fragments
                table_details = source_fragments(block, text, start, end)
                table_details["deferred_table_context_sha256"] = deferred_context
            parts.append({"start_char": start, "end_char": end, "text": source_text,
                "metadata": {"chunker": POLICY, "token_count": count(embedding_text),
                    "source_token_count": count(source_text), "section_path": block["section_path"],
                    "physical_section_path": block["section_path"], "related_sections": related,
                    "references_from": block.get("references_from", []),
                    "kind": kind, "sources": [b["source"] for b in contributing],
                    "block_ids": [b["id"] for b in contributing], "merged_block_count": len(contributing),
                    "continued": start != first,
                    "overlap_tokens": count(text[start:previous_end]) if start < previous_end else 0,
                    "embedding_text": embedding_text, "embedding_input_sha256": digest(embedding_text),
                    "retrieval_text": retrieval_text, "retrieval_is_verbatim": not used_changes,
                    "retrieval_transformations": used_changes, "source_text_sha256": digest(source_text),
                    "tokenizer_sha256": tokenizer_sha, "parser": doc["parser"],
                    "original_sha256": doc["original_sha256"], "structure_sha256": doc["structure_sha256"],
                    "document_schema": VERSION, "quality_status": doc["quality_status"],
                    "table_header_repeated": bool(header and header not in source_text),
                    "table_header_preserved": bool(header and header in embedding_text),
                    **table_details}})
            previous_end = end
            if end == finish:
                break
            if kind in narrative:
                encoded = tok.encode(source_text, add_special_tokens=False)
                offset = encoded.offsets[max(0, len(encoded.ids)-OVERLAP)][0]
                next_start = safe_boundary(spans, start + offset, forward=True)
                start = next_start if start < next_start < end else end
            else:
                start = end
    if not 0 < len(parts) <= 1000:
        raise LiteratureError("Document must produce 1-1000 chunks")
    return parts

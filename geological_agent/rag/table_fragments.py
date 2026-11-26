"""Bounded source-contiguous table fragments with explicit cell provenance.

A fragment is never a complete row claim. Original rows, headers, PDF source
locations and merge origins remain available; numeric/formula spans are atomic.
"""
import re


def fragment_end(text, start, finish, embedding_input, count, spans, maximum):
    from .refinement import safe_boundary
    from .literature import LiteratureError

    newline = text.find("\n", start, finish)
    stop = newline + 1 if newline >= 0 else finish
    low, high = start, stop
    while low < high:
        middle = (low + high + 1) // 2
        if count(embedding_input(start, middle)) <= maximum:
            low = middle
        else:
            high = middle - 1
    end = safe_boundary(spans, low)
    # Prefer cell boundaries. If a single cell is oversized, its text may
    # continue in another fragment, but never through a protected source atom.
    cells = [start + m.end() for m in re.finditer(r"\s*\|\s*", text[start:end])]
    cells = [p for p in cells if p > start and safe_boundary(spans, p) == p]
    if cells:
        end = cells[-1]
    while end > start and count(embedding_input(start, end)) > maximum:
        end = safe_boundary(spans, end - 1)
    if end <= start:
        raise LiteratureError(
            "An indivisible source number, formula or word exceeds the table "
            "fragment budget; original retained, review required")
    return end


def source_fragments(block, body, start, end):
    from .literature import digest

    offset = block["start_char"]
    table = block["table"]
    fragments = []
    rows = table.get("rows", [])
    mappings = table.get("row_sources", [])
    if not mappings:
        cursor = 0
        mappings = []
        for ordinal, line in enumerate(block["text"].splitlines(keepends=True)):
            mappings.append({"row": ordinal, "start": cursor,
                             "end": cursor + len(line.rstrip("\r\n")),
                             "origins": []})
            cursor += len(line)
    for mapping in mappings:
        a, b = offset + mapping["start"], offset + mapping["end"]
        if a >= end or b <= start:
            continue
        ordinal = mapping["row"]
        record = {
            "row": ordinal, "source_start_char": a, "source_end_char": b,
            "row_source_sha256": digest(body[a:b]),
            "fragment_start_char": max(a, start),
            "fragment_end_char": min(b, end),
            "continued_row": start > a or end < b,
            "cells": [], "explicit_merge_origins": mapping.get("origins", []),
        }
        cursor = a
        for cell_index, cell in enumerate(rows[ordinal] if ordinal < len(rows) else []):
            value = cell["text"].strip().replace("\n", " ")
            last = cursor + len(value)
            if body[cursor:last] != value:
                raise ValueError("Table cell does not match its immutable source")
            if cursor < end and last > start:
                positions = [
                    i for i, origin in enumerate(mapping.get("origins", []))
                    if origin and origin["origin_row"] == ordinal
                    and origin["origin_cell"] == cell_index
                    and origin["column_offset"] == 0
                ]
                record["cells"].append({
                    "cell": cell_index,
                    "column": positions[0] if positions else None,
                    "source_start_char": cursor, "source_end_char": last,
                    "source_sha256": digest(value),
                    "fragment_start_char": max(cursor, start),
                    "fragment_end_char": min(last, end),
                    "continued_cell": start > cursor or end < last,
                    "rowspan": cell.get("rowspan", 1),
                    "colspan": cell.get("colspan", 1),
                    "header": bool(cell.get("header")),
                })
            cursor = last + 3  # exact canonical separator: " | "
        fragments.append(record)
    return {
        "table_source_sha256": digest(block["text"]),
        "table_fragment_policy": "source-contiguous-cell-provenance-v1",
        "table_row_fragments": fragments,
        "table_fragment_is_complete_row": (
            bool(fragments) and all(not f["continued_row"] for f in fragments)),
    }

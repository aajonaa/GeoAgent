"""Read-only, evidence-bound presentation; never another model/tool protocol.

Blocks are derived from persisted native receipts and immutable run snapshots.
No generated HTML, code execution, extra model calls or completion decisions.
Preview limits affect display only; downloads retain the original bytes.
"""
import csv
import hashlib
import io
import json
import math
from pathlib import PurePosixPath

from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from .protocol import relative_name


def block(component, identifier, title, props):
    return {"component": component, "version": 1, "id": identifier,
            "title": title, "props": props}


def events_for(store, uid, rid):
    cursor = 0
    while True:
        page = store.events(uid, rid, cursor)
        if not page:
            return
        for row in page:
            yield row["data"]
        cursor = page[-1]["id"]


def receipt_blocks(result):
    if not isinstance(result, dict) or result.get("status") != "ok":
        return []
    # Framework bookkeeping is not a scientific result card.
    if not str(result.get("name", "")).startswith("Geo"):
        return []
    call_id = str(result.get("call_id", ""))
    metrics, tables = [], []

    def walk(value, path):
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, path + [str(key)])
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            if isinstance(value, int) or math.isfinite(value):
                # Text preserves large integers and the original numeric value.
                metrics.append({"label": " / ".join(path), "value": str(value)})
        elif isinstance(value, list) and value and all(isinstance(row, dict) for row in value):
            columns = list(dict.fromkeys(key for row in value for key in row))
            if columns and all(all(item is None or isinstance(item, (str, int, float, bool))
                                   for item in row.values()) for row in value):
                # Missing cells stay distinguishable from an explicit empty string.
                tables.append({"path": " / ".join(path), "columns": columns,
                               "rows": [[display_cell(row.get(key)) for key in columns] for row in value[:100]],
                               "total": len(value), "scope": "receipt_preview"})

    walk(result.get("data", {}), [])
    output = []
    title = str(result.get("name", "Tool result"))
    if metrics:
        output.append(block("metrics", "tool:" + call_id, title, {
            "items": metrics, "call_id": call_id, "cached": bool(result.get("cached")),
            "scope": "Native tool output; not an independent scientific validation."}))
    for index, table in enumerate(tables):
        output.append(block("table", f"tool:{call_id}:table:{index}",
                            title + " / " + table["path"], {**table, "call_id": call_id}))
    return output


def display_cell(value):
    # JSON numbers above the JS safe-integer range would change in JSON.parse.
    # Preserve them as exact decimal text; raw receipts/downloads stay unchanged.
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53 - 1:
        return str(value)
    return value


def collect_receipts(store, uid, rid):
    receipts, sources = {}, {}
    for event in events_for(store, uid, rid):
        if event.get("kind") == "tool_result" and isinstance(event.get("result"), dict):
            result = event["result"]
            receipts[str(result.get("call_id", event.get("id", "")))] = result
        elif event.get("kind") == "knowledge_sources":
            for ref in event.get("references", []):
                if isinstance(ref, dict) and isinstance(ref.get("citation_id"), str):
                    sources[ref["citation_id"]] = {
                        key: ref.get(key, "") for key in
                        ("citation_id", "document_id", "title", "source", "text", "sha256")}
    return receipts, list(sources.values())


def csv_page(raw, name, offset=0, limit=50, sort=-1, descending=False):
    # This is a browser preview budget, never an execution/data validity limit.
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Preview is limited to 2 MiB; download the unchanged source file.")
    text = raw.decode("utf-8-sig", errors="strict")
    reader = csv.reader(io.StringIO(text, newline=""),
                        delimiter="\t" if name.lower().endswith(".tsv") else ",", strict=True)
    columns = next(reader, [])
    if not columns or any(not c.strip() for c in columns) or len(set(columns)) != len(columns):
        raise ValueError("Preview requires unique, nonempty column names; no columns were repaired.")
    if len(columns) > 128:
        raise ValueError("Preview supports up to 128 columns; download the unchanged source file.")
    rows = []
    for line, row in enumerate(reader, 2):
        if len(row) != len(columns):
            raise ValueError(f"CSV record {line} has {len(row)} cells; expected {len(columns)}. No rows were dropped.")
        rows.append(row)
    if sort >= len(columns) or sort < -1:
        raise ValueError("Unknown sort column")
    if sort >= 0:
        from decimal import Decimal, InvalidOperation
        try:
            numbers = [Decimal(row[sort]) for row in rows]
            numeric = all(number.is_finite() for number in numbers)
        except InvalidOperation:
            numeric = False
        if numeric:
            rows = [row for _, row in sorted(zip(numbers, rows), key=lambda item: item[0], reverse=descending)]
        else:
            rows.sort(key=lambda row: row[sort].casefold(), reverse=descending)
    return {"columns": columns, "rows": rows[offset:offset + limit], "total": len(rows),
            "offset": offset, "limit": limit, "sort": sort, "descending": descending,
            "sha256": hashlib.sha256(raw).hexdigest(), "scope": "file_page"}


def install_presentation_routes(app, auth, store):
    def response(value):
        return JSONResponse(value, headers={"Cache-Control": "private, no-store"})

    @app.get("/api/runs/{rid}/presentation")
    def presentation(rid: str, request: Request):
        uid = auth(request)["id"]
        run = store.run(uid, rid)
        receipts, sources = collect_receipts(store, uid, rid)
        blocks = [item for result in receipts.values() for item in receipt_blocks(result)]
        generation = run.get("generation") or ""
        images = []
        if generation:
            # Never substitute the conversation's latest generation for this run.
            with store.lock:
                files = [dict(row) for row in store.db.execute(
                    "SELECT name,length(content) AS bytes,sha256 FROM files WHERE cid=? AND generation=? ORDER BY name",
                    (run["cid"], generation))]
            for file in files:
                suffix = PurePosixPath(file["name"]).suffix.lower()
                if suffix in (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"):
                    images.append(file)
                elif suffix in (".csv", ".tsv"):
                    blocks.append(block("table", "file:" + file["name"], file["name"],
                                        {"file": file, "scope": "file_page"}))
            if images:
                # Pair only when the actual tool result names and hashes agree.
                pairs = []
                by_name = {file["name"]: file for file in images}
                for result in receipts.values():
                    if result.get("status") != "ok":
                        continue
                    data = result.get("data", {})
                    source = data.get("source", {}) if isinstance(data, dict) else {}
                    if not isinstance(source, dict):
                        continue
                    first = by_name.get(source.get("path"))
                    if first is None or first["sha256"] != source.get("sha256"):
                        continue
                    for output in data.get("outputs", []):
                        if not isinstance(output, dict):
                            continue
                        second = by_name.get(output.get("path"))
                        if second and second["sha256"] == output.get("sha256"):
                            pairs.append({"before": first["name"], "after": second["name"],
                                          "call_id": result.get("call_id", "")})
                blocks.append(block("images", "images:" + generation, "Images", {"files": images, "pairs": pairs}))
        if sources:
            blocks.append(block("sources", "knowledge", "Sources", {"items": sources}))
        return response({"version": 1, "run_id": rid, "conversation_id": run["cid"],
                         "generation": generation, "status": run["status"], "blocks": blocks})

    @app.get("/api/runs/{rid}/table")
    def table(rid: str, request: Request, name: str,
              offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
              sort: int = Query(-1, ge=-1), descending: bool = False):
        uid = auth(request)["id"]
        run = store.run(uid, rid)
        name = relative_name(name)
        if not run.get("generation") or PurePosixPath(name).suffix.lower() not in (".csv", ".tsv"):
            raise HTTPException(404, "Committed table not found")
        with store.lock:
            row = store.db.execute("SELECT content FROM files WHERE cid=? AND generation=? AND name=?",
                                   (run["cid"], run["generation"], name)).fetchone()
        if row is None:
            raise HTTPException(404, "Committed table not found")
        try:
            result = csv_page(bytes(row[0]), name, offset, limit, sort, descending)
        except (ValueError, UnicodeError, csv.Error) as exc:
            raise HTTPException(422, str(exc)) from exc
        return response(result)

    @app.get("/api/runs/{rid}/receipts/{call_id}")
    def receipt(rid: str, call_id: str, request: Request):
        uid = auth(request)["id"]
        store.run(uid, rid)
        receipts, _ = collect_receipts(store, uid, rid)
        if call_id not in receipts:
            raise HTTPException(404, "Native receipt not found")
        raw = json.dumps(receipts[call_id], ensure_ascii=False, indent=2, allow_nan=False)
        return Response(raw, media_type="application/json", headers={
            "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
            "Content-Disposition": 'attachment; filename="tool-result.json"'})

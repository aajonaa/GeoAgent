"""Private PDF reading assets and conservative, exact-text page anchors."""
import hashlib
import json
from pathlib import Path
import re

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from geological_agent.team.pdf_content import load_content, content_view, ASSET_NAME, sha, ContentError

WEB = Path(__file__).parent / "web"
MAX_LAYOUT = 100 * 1024 * 1024

def source_summary(job, basis=None):
    result = {k: job.get(k) for k in ("id", "filename", "sha256", "text_sha256", "bytes", "pages")}
    result["text_sha256"] = basis or (job.get("prepared") or {}).get("sha256") or job.get("text_sha256")
    result["raw_text_sha256"] = job.get("text_sha256")
    return result

def document_source(imports, owner, document_id, text_sha256):
    for job in imports.listing(owner):
        if ((job.get("index") or {}).get("id") == document_id
                and (job.get("index_text_sha256") or job.get("text_sha256")) == text_sha256
                and "original" in job.get("artifacts", [])):
            return source_summary(job, text_sha256)
        for previous in job.get("index_history", []):
            if ((previous.get("index") or {}).get("id") == document_id and previous.get("text_sha256") == text_sha256):
                return source_summary(job, text_sha256)
    return None

def exact_page_anchors(text, structured, page_count):
    """Use unique exact substrings, not fuzzy matching or inferred page positions."""
    if not isinstance(structured, dict) or not isinstance(structured.get("pages"), list):
        return []
    candidates = {}
    for page in structured["pages"]:
        if not isinstance(page, dict):
            continue
        number = page.get("page_idx")
        if type(number) is not int or not 0 <= number < page_count:
            continue
        blocks = page.get("blocks", [])
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            content = block.get("content")
            if not isinstance(content, str) or len(content.strip()) < 4:
                continue
            start = text.find(content)
            if start < 0 or text.find(content, start + 1) >= 0:
                continue
            key = (start, start + len(content))
            candidates.setdefault(key, set()).add(number + 1)
    return [{"start_char": start, "end_char": end, "page": next(iter(pages))}
            for (start, end), pages in sorted(candidates.items()) if len(pages) == 1]


def structured_page_anchors(canonical, page_count):
    """Bind normalized blocks to verified canonical spans; never fuzzy-match PDFs."""
    text=canonical.get("body")
    if not isinstance(text,str) or hashlib.sha256(text.encode()).hexdigest()!=canonical.get("sha256"):
        raise ValueError("Canonical text hash mismatch")
    candidates={}
    for block in canonical.get("blocks",[]):
        if not isinstance(block,dict) or not block.get("indexable"):
            continue
        start,end=block.get("start_char"),block.get("end_char")
        source=block.get("source") or {}
        page=source.get("page")
        block_id=block.get("id")
        if (type(start) is not int or type(end) is not int or not 0<=start<end<=len(text)
                or type(page) is not int or not 1<=page<=page_count
                or source.get("page_idx")!=page-1
                or not isinstance(block_id,str) or not block_id
                or source.get("block_id")!=block_id):
            continue
        raw=block.get("text")
        span=text[start:end]
        if not isinstance(raw,str) or not raw or not span.startswith(raw) or span[len(raw):] not in ("","\n","\n\n"):
            continue
        anchor={"start_char":start,"end_char":end,"page":page,"block_id":block_id,
                "mapping":"verified_structured_block","basis_sha256":canonical["sha256"]}
        candidates.setdefault((start,end),[]).append(anchor)
    return [group[0] for _,group in sorted(candidates.items())
            if len({(item["page"],item["block_id"]) for item in group})==1]

def reader_metadata(imports, owner, job_id, basis=None):
    job = imports.get(owner, job_id)
    folder = imports.folder(job_id)
    if "original" not in job.get("artifacts", []) or not (folder / "source.pdf").is_file():
        raise HTTPException(404, "Original PDF not found")
    result = {"source": source_summary(job), "anchors": [], "anchors_limited": False,
              "location_status": "unavailable"}
    pages = job.get("pages")
    layout = folder / "structure.json"
    markdown = folder / "parsed.md"
    if (type(pages) is not int or not 0 < pages <= 10000
            or "structured_content" not in job.get("artifacts", [])
            or not layout.is_file() or not markdown.is_file()
            or layout.stat().st_size > MAX_LAYOUT or markdown.stat().st_size > MAX_LAYOUT):
        return result
    try:
        raw = markdown.read_bytes()
        if hashlib.sha256(raw).hexdigest() != job.get("text_sha256"):
            result["location_status"] = "source_mismatch"
            return result
        text = raw.decode("utf-8")
        if basis != job.get("text_sha256"):
            text, prepared, folder = load_content(folder, job)
            if basis and basis != prepared["sha256"]:
                from .literature import prepare
                canonical = prepare(imports, owner, job_id, with_chunks=False)["document"]
                if basis != canonical["sha256"]:
                    result["location_status"] = "source_mismatch"
                    return result
                anchors=structured_page_anchors(canonical,pages)
                result.update(source=source_summary(job,basis),location_status="structured_blocks",
                    structure_sha256=canonical["structure_sha256"],anchors=anchors[:2000],anchors_limited=len(anchors)>2000)
                return result
            result["source"] = source_summary(job, prepared["sha256"])
        else:
            result["source"] = source_summary(job, basis)
        structured = json.loads(layout.read_text(encoding="utf-8"))
        anchors = exact_page_anchors(text, structured, pages)
        result.update(anchors=anchors[:2000], anchors_limited=len(anchors) > 2000,
                      location_status="exact_text" if anchors else "unavailable")
    except (OSError, UnicodeError, ValueError, TypeError):
        return result
    return result

def reader_asset_path(name, root=None):
    root = Path(root) if root is not None else WEB
    if name == "content.mjs":
        return root / "pdf-content.mjs", "text/javascript"
    if name == "reader.mjs":
        return root / "pdf-reader.mjs", "text/javascript"
    if name in {"pdfjs/build/pdf.mjs", "pdfjs/build/pdf.worker.mjs"}:
        media = "text/javascript"
    elif re.fullmatch(r"pdfjs/cmaps/[A-Za-z0-9_.-]+\.bcmap", name):
        media = "application/octet-stream"
    elif re.fullmatch(r"pdfjs/standard_fonts/[A-Za-z0-9_.-]+\.(pfb|ttf)", name):
        media = "application/octet-stream"
    elif name == "pdfjs/LICENSE":
        media = "text/plain"
    else:
        raise HTTPException(404, "Reader asset not found")
    path = root / "vendor" / name
    if not path.resolve().is_relative_to((root / "vendor" / "pdfjs").resolve()):
        raise HTTPException(404, "Reader asset not found")
    return path, media

def install_reader_routes(app, auth, imports):
    @app.get("/api/knowledge/pdf/reader-assets/{name:path}")
    async def reader_asset(name: str, request: Request):
        auth(request)
        path, media = reader_asset_path(name)
        if not path.is_file():
            raise HTTPException(404, "Reader asset not found")
        return FileResponse(path, media_type=media, headers={
            "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

    @app.get("/api/knowledge/pdf/jobs/{job_id}/reader")
    async def metadata(job_id: str, request: Request, text_sha256: str | None = None):
        return await run_in_threadpool(reader_metadata, imports, auth(request)["id"], job_id, text_sha256)

    async def prepared(request, job_id):
        job = await run_in_threadpool(imports.get, auth(request)["id"], job_id)
        try:
            text, record, folder = await run_in_threadpool(load_content, imports.folder(job_id), job)
        except (OSError, ValueError):
            raise HTTPException(409, "Validated PDF content is not available; originals retained") from None
        return job, text, record, folder

    @app.get("/api/knowledge/pdf/jobs/{job_id}/content")
    async def content(job_id: str, request: Request, text_sha256: str | None = None):
        job = await run_in_threadpool(imports.get, auth(request)["id"], job_id)
        try:
            return await run_in_threadpool(content_view, imports.folder(job_id), job, text_sha256)
        except (OSError, ValueError):
            if text_sha256:
                try:
                    from .literature import prepare
                    from .pdf_content import view_tokens
                    package = await run_in_threadpool(lambda: prepare(imports, auth(request)["id"], job_id, with_chunks=False))
                    doc = package["document"]
                    if doc["sha256"] == text_sha256:
                        return {"sha256":doc["sha256"],"raw_sha256":doc["raw_sha256"],
                            "tokens":view_tokens(doc["body"]),"assets":package["assets"],"derived":[],
                            "quality_status":doc["quality_status"],"characters":len(doc["body"]),
                            "raw_characters":job.get("characters"),"inline_image_characters":0}
                except (OSError,ValueError,KeyError):
                    pass
            raise HTTPException(409, "Content version is unavailable or requires manual review") from None

    @app.get("/api/knowledge/pdf/jobs/{job_id}/content/markdown")
    async def prepared_markdown(job_id: str, request: Request):
        job, text, record, folder = await prepared(request, job_id)
        return FileResponse(folder / "content.md", media_type="text/markdown", filename="content.md",
                            headers={"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff"})

    @app.get("/api/knowledge/pdf/jobs/{job_id}/content/assets/{name}")
    async def image_asset(job_id: str, name: str, request: Request):
        if not ASSET_NAME.fullmatch(name):
            raise HTTPException(404, "Image asset not found")
        job, text, record, folder = await prepared(request, job_id)
        asset = next((value for value in record["assets"] if value["name"] == name), None)
        path = folder / name
        if asset is None or not path.is_file():
            raise HTTPException(404, "Image asset not found")
        if await run_in_threadpool(lambda: sha(path.read_bytes())) != asset["sha256"]:
            raise HTTPException(409, "Image asset hash mismatch")
        return FileResponse(path, media_type=asset["media_type"], headers={
            "Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff"})

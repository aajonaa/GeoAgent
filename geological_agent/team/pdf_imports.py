"""Account-owned PDF imports through a private, asynchronous MinerU service.

The parser runs independently after submission. API polling only refreshes local
status and downloads outputs. No chat model, remote URL source, or HTML execution.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
from threading import Lock
import time
import uuid
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

MAX_PDF = 50 * 1024 * 1024
MAX_OUTPUT = 100 * 1024 * 1024
MAX_PREVIEW = 120000
PARSE_TIER = "advanced"
ARTIFACTS = {
    "original": ("source.pdf", "application/pdf"),
    "markdown": ("parsed.md", "text/markdown"),
    "middle_json": ("layout.json", "application/json"),
    "structured_content": ("structure.json", "application/json"),
    "zip": ("figures.zip", "application/zip"),
}
ACTIVE = {"receiving", "submitting", "queued", "parsing", "fetching", "indexing"}


class ParserError(RuntimeError):
    pass


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value):
        raise ParserError("Invalid parser resource identifier")
    return value


def source_info(value, fallback="", maximum=1000):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid title, filename or source metadata")
    return value.strip() or fallback


class ParserClient:
    def __init__(self, config):
        parts = urlsplit(config["url"])
        if parts.scheme != "http" or parts.hostname != "127.0.0.1" or not parts.port or parts.path not in ("", "/") or parts.username or parts.password or parts.query or parts.fragment:
            raise ParserError("Parser must use an administrator-configured loopback tunnel")
        self.url = config["url"].rstrip("/")
        self.key_file = Path(config["key_file"])

    @contextmanager
    def session(self):
        try:
            if os.name != "nt" and self.key_file.stat().st_mode & 0o077:
                raise ParserError("Parser credential file must be private")
            key = self.key_file.read_text(encoding="ascii").strip()
            if len(key) < 32:
                raise ParserError("Parser credential is unavailable")
        except (OSError, UnicodeError):
            raise ParserError("Parser credential is unavailable") from None
        with httpx.Client(base_url=self.url, headers={"Authorization": "Bearer " + key},
                          follow_redirects=False, trust_env=False,
                          timeout=httpx.Timeout(180, connect=8)) as client:
            yield client

    def json(self, method, path, payload=None):
        try:
            with self.session() as client:
                response = client.request(method, path, json=payload)
                response.raise_for_status()
                if len(response.content) > 2 * 1024 * 1024:
                    raise ParserError("Parser metadata exceeded its size limit")
                return response.json()
        except (httpx.HTTPError, ValueError):
            raise ParserError("Parser request failed; check the private connection or service") from None

    def upload(self, upload_id, path):
        def content():
            with path.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    yield block
        try:
            with self.session() as client:
                response = client.put("/v1/uploads/" + safe_id(upload_id) + "/content",
                                      content=content(), headers={"Content-Type": "application/octet-stream",
                                                                 "Content-Length": str(path.stat().st_size)})
                response.raise_for_status()
        except httpx.HTTPError:
            raise ParserError("PDF transfer failed; original file retained") from None

    def download(self, file_id, target, expected_size):
        if not isinstance(expected_size, int) or isinstance(expected_size, bool) or not 0 <= expected_size <= MAX_OUTPUT:
            raise ParserError("Parser output size is invalid or exceeds 100 MiB")
        temp = target.with_suffix(target.suffix + ".partial")
        try:
            size = 0
            with self.session() as client, client.stream("GET", "/v1/files/" + safe_id(file_id) + "/content") as response:
                response.raise_for_status()
                with temp.open("wb") as stream:
                    for block in response.iter_bytes(1024 * 1024):
                        size += len(block)
                        if size > expected_size or size > MAX_OUTPUT:
                            raise ParserError("Parser output exceeded its declared size")
                        stream.write(block)
            if size != expected_size:
                raise ParserError("Incomplete parser output; not ready for indexing")
            os.replace(temp, target)
        except httpx.HTTPError:
            raise ParserError("Could not download parsed output; try refreshing the task") from None


class PdfImports:
    def __init__(self, root):
        self.root = Path(root) / "knowledge-pdf"
        self.config_path = Path(os.environ.get("GEOTOOL_PDF_PARSER_CONFIG", str(Path(root) / "pdf-parser.json")))
        self._locks = {}
        self._guard = Lock()
        self._ready = False

    def configuration(self):
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            ParserClient(data)
            return data
        except (OSError, ValueError, KeyError, TypeError, ParserError):
            return None

    def capabilities(self):
        return {"enabled": self.configuration() is not None, "max_bytes": MAX_PDF,
                "preview_characters": MAX_PREVIEW, "tier": PARSE_TIER,
                "execution": "private-5060ti", "formats": ["pdf"]}

    def client(self):
        config = self.configuration()
        if config is None:
            raise ParserError("PDF parser connection has not been configured")
        return ParserClient(config)

    def setup(self):
        with self._guard:
            if self._ready:
                return
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            with sqlite3.connect(self.root / "jobs.sqlite3") as db:
                db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, updated REAL NOT NULL, data TEXT NOT NULL)")
                db.execute("CREATE INDEX IF NOT EXISTS pdf_job_owner ON jobs(owner, updated)")
                # This app runs one ASGI worker. On a new worker, recover only
                # local in-flight steps; never resubmit GPU jobs automatically.
                for row in db.execute("SELECT id, data FROM jobs").fetchall():
                    job = json.loads(row[1])
                    state = job.get("state")
                    if state == "receiving":
                        job.update(state="failed", error="Upload was interrupted by a service restart. Retained bytes have not been validated; create a new import to retry.")
                    elif state == "submitting":
                        if job.get("remote_job"):
                            job.update(state="queued", error="Parser job retained after restart; refresh to continue tracking it.")
                        else:
                            job.update(state="submission_unknown", error="Submission was interrupted by a service restart. Original PDF retained; administrator reconciliation is required before another GPU submission.")
                    elif state == "indexing":
                        job.update(state="parsed", error="Indexing was interrupted by a service restart. Parsed output retained; confirm indexing again to reconcile an existing matching document or retry.")
                    else:
                        continue
                    job["recovered_at"] = job["updated_at"] = time.time()
                    db.execute("UPDATE jobs SET data=?, updated=? WHERE id=?",
                               (json.dumps(job, ensure_ascii=False), job["updated_at"], row[0]))
            self._ready = True

    @contextmanager
    def database(self):
        self.setup()
        with sqlite3.connect(self.root / "jobs.sqlite3", timeout=10) as db:
            db.row_factory = sqlite3.Row
            yield db

    def lock(self, job_id):
        with self._guard:
            return self._locks.setdefault(job_id, Lock())

    def folder(self, job_id):
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise ValueError("Invalid import ID")
        return self.root / job_id

    def get(self, owner, job_id):
        self.folder(job_id)
        with self.database() as db:
            row = db.execute("SELECT data FROM jobs WHERE id=? AND owner=?", (job_id, owner)).fetchone()
        if row is None:
            raise HTTPException(404, "PDF import not found")
        return json.loads(row["data"])

    def save(self, job):
        job["updated_at"] = time.time()
        with self.database() as db:
            db.execute("UPDATE jobs SET data=?, updated=? WHERE id=? AND owner=?",
                       (json.dumps(job, ensure_ascii=False), job["updated_at"], job["id"], job["owner"]))

    def listing(self, owner):
        with self.database() as db:
            rows = db.execute("SELECT data FROM jobs WHERE owner=? ORDER BY updated DESC LIMIT 100", (owner,)).fetchall()
        return [self.public(json.loads(row["data"])) for row in rows]

    def public(self, job):
        return {key: value for key, value in job.items()
                if key not in {"owner", "upload_token_hash", "remote_upload", "remote_file", "remote_job"}}

    def create(self, owner, value):
        self.client()
        filename = source_info(value.get("filename"), maximum=180)
        title = source_info(value.get("title"), maximum=160)
        source = source_info(value.get("source", ""), "User-uploaded PDF", maximum=700)
        size = value.get("bytes")
        if not title or not filename.lower().endswith(".pdf") or "/" in filename or "\\" in filename:
            raise ValueError("A PDF filename and title are required")
        if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_PDF:
            raise ValueError("PDF must contain 1 byte to 50 MiB")
        token = secrets.token_urlsafe(32)
        job = {"id": uuid.uuid4().hex, "owner": owner, "filename": filename, "title": title,
               "source": source, "bytes": size, "state": "awaiting_upload", "created_at": time.time(),
               "upload_token_hash": hashlib.sha256(token.encode()).hexdigest(), "error": "",
               "artifacts": [], "index": None}
        job["updated_at"] = job["created_at"]
        with self.database() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT count(*) FROM jobs WHERE owner=?", (owner,)).fetchone()[0] >= 100:
                raise ValueError("PDF pilot quota: 100 imports per account")
            db.execute("INSERT INTO jobs VALUES(?,?,?,?)", (job["id"], owner, job["updated_at"], json.dumps(job)))
        self.folder(job["id"]).mkdir(mode=0o700)
        return {**self.public(job), "upload_token": token}

    def begin_upload(self, owner, job_id, token):
        with self.lock(job_id):
            job = self.get(owner, job_id)
            if not secrets.compare_digest(hashlib.sha256(token.encode()).hexdigest(), job["upload_token_hash"]):
                raise HTTPException(403, "Invalid PDF upload authorization")
            if job["state"] != "awaiting_upload" or time.time() - job["created_at"] > 3600:
                raise HTTPException(409, "PDF upload already consumed or expired")
            job["state"] = "receiving"
            self.save(job)
            return job

    def fail(self, job, error, state="failed"):
        job.update(state=state, error=error)
        self.save(job)

    def submit(self, job):
        with self.lock(job["id"]):
            job.update(state="submitting", error="")
            self.save(job)
            client = self.client()
            try:
                upload = client.json("POST", "/v1/uploads",
                                     {"filename": job["id"] + ".pdf", "bytes": job["bytes"], "mime_type": "application/pdf",
                                      "purpose": "parse", "sha256sum": job["sha256"]})
                job["remote_upload"] = safe_id(upload["id"])
                self.save(job)
                if type(upload.get("bytes")) is not int or upload["bytes"] != job["bytes"] or upload.get("sha256sum") != job["sha256"]:
                    raise ParserError("Upload identity did not match the original PDF")
                if upload.get("status") == "completed":
                    uploaded = upload
                    job["upload_reused"] = True
                elif upload.get("status") == "pending":
                    client.upload(job["remote_upload"], self.folder(job["id"]) / "source.pdf")
                    uploaded = client.json("POST", "/v1/uploads/" + job["remote_upload"] + "/complete",
                                           {"sha256sum": job["sha256"]})
                    job["upload_reused"] = False
                else:
                    raise ParserError("Upload is not usable")
                remote_file = uploaded.get("file")
                if uploaded.get("status") != "completed" or not isinstance(remote_file, dict):
                    raise ParserError("Upload completion was not confirmed")
                for item in (uploaded, remote_file):
                    if type(item.get("bytes")) is not int or item["bytes"] != job["bytes"] or item.get("sha256sum") != job["sha256"]:
                        raise ParserError("Completed file identity did not match the original PDF")
                expires = remote_file.get("expires_at")
                if expires is not None and (type(expires) not in (int, float) or expires <= time.time()):
                    raise ParserError("Completed parser file has expired")
                job["remote_file"] = safe_id(remote_file["id"])
                self.save(job)
                response = client.json("POST", "/v1/parse/jobs", {
                    "files": [{"source": {"type": "file_id", "file_id": job["remote_file"]}}],
                    "tier": PARSE_TIER, "ocr_mode": "auto",
                    "output_formats": ["markdown", "middle_json", "structured_content", "zip"]})
                job.update(remote_job=safe_id(response["job_id"]), state="queued", error="")
                self.save(job)
            except (ParserError, KeyError, TypeError, ValueError):
                self.fail(job, "Parser submission was not confirmed. Original PDF retained. Do not resubmit blindly; ask an administrator to inspect the parser job list.", "submission_unknown")
            return self.public(job)

    def refresh(self, owner, job_id):
        lock = self.lock(job_id)
        if not lock.acquire(blocking=False):
            return self.public(self.get(owner, job_id))
        try:
            job = self.get(owner, job_id)
            if job["state"] not in {"queued", "parsing", "fetching"}:
                return self.public(job)
            client = self.client()
            try:
                result = client.json("GET", "/v1/parse/jobs/" + safe_id(job["remote_job"]))
                status = result["status"]
                job["parser_progress"] = result.get("progress")
                if status in {"queued", "running"}:
                    job.update(state="queued" if status == "queued" else "parsing", error="")
                elif status == "completed":
                    files = result["files"]
                    if len(files) != 1 or files[0].get("status") != "completed":
                        raise ParserError("Parser did not complete the entire PDF")
                    item = files[0]
                    job.update(state="fetching", parser=item.get("parse") or {}, error="")
                    self.save(job)
                    outputs = item.get("output_files") or {}
                    if not outputs.get("markdown") or not outputs.get("middle_json"):
                        raise ParserError("Complete Markdown and layout output are required")
                    available = ["original"]
                    for kind in ("markdown", "middle_json", "structured_content", "zip"):
                        ref = outputs.get(kind)
                        if ref:
                            target = self.folder(job_id) / ARTIFACTS[kind][0]
                            client.download(ref["file_id"], target, ref["bytes"])
                            available.append(kind)
                    text = (self.folder(job_id) / "parsed.md").read_text(encoding="utf-8")
                    layout = json.loads((self.folder(job_id) / "layout.json").read_text(encoding="utf-8"))
                    if not text.strip() or "\x00" in text:
                        raise ParserError("Parsed text is empty or invalid; not indexed")
                    pages = layout.get("pdf_info", layout.get("pages")) if isinstance(layout, dict) else None
                    job.update(state="parsed", artifacts=available, characters=len(text),
                               text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                               pages=len(pages) if isinstance(pages, list) else None,
                               can_index=len(text) <= MAX_PREVIEW,
                               index_note="" if len(text) <= MAX_PREVIEW else "Full parsed text exceeds the current 120,000-character indexing limit. It was retained, not truncated.",
                               error="")
                elif status in {"failed", "partial", "canceled"}:
                    job.update(state="failed", error="PDF parsing did not complete successfully (" + status + "); original file retained.")
                else:
                    raise ParserError("Unknown parser task status")
                self.save(job)
            except (ParserError, OSError, ValueError, KeyError, TypeError):
                job["error"] = "Could not refresh or validate parser output. Original retained; refresh to retry. No indexing has been claimed."
                self.save(job)
            return self.public(job)
        finally:
            lock.release()

    def preview(self, owner, job_id):
        job = self.get(owner, job_id)
        if "markdown" not in job["artifacts"]:
            raise HTTPException(409, "Parsed output is not ready")
        text = (self.folder(job_id) / "parsed.md").read_text(encoding="utf-8")
        return {"job": self.public(job), "text": text[:MAX_PREVIEW],
                "preview_truncated": len(text) > MAX_PREVIEW, "total_characters": len(text)}

    def ingest(self, owner, job_id, factory):
        with self.lock(job_id):
            job = self.get(owner, job_id)
            if job["state"] == "indexed":
                return self.public(job)
            if job["state"] != "parsed" or not job.get("can_index"):
                raise HTTPException(409, "Preview a complete supported document before indexing")
            job.update(state="indexing", error="")
            self.save(job)
            try:
                text = (self.folder(job_id) / "parsed.md").read_text(encoding="utf-8")
                if hashlib.sha256(text.encode()).hexdigest() != job["text_sha256"]:
                    raise ParserError("Parsed source hash changed; indexing refused")
                source = job["source"] + "; PDF SHA256=" + job["sha256"] + "; parsed by MinerU; filename=" + job["filename"]
                if len(source) > 1000:
                    raise ValueError("Source metadata exceeds the current indexing limit")
                result = factory({"id": owner}).ingest(job["title"], text, source)
                if not result.get("chunks"):
                    raise ParserError("Existing document has no chunks; indexing has not completed")
                job.update(state="indexed", index=result, error="")
            except Exception:
                job.update(state="parsed", error="Indexing did not complete. Parser output is preserved; inspect the knowledge service before retrying.")
            self.save(job)
            return self.public(job)

    def unlink_document(self, owner, document_id):
        for public in self.listing(owner):
            if (public.get("index") or {}).get("id") == document_id:
                with self.lock(public["id"]):
                    job = self.get(owner, public["id"])
                    job.update(state="parsed", index=None, error="Knowledge entry deleted; original PDF and parse outputs retained.")
                    self.save(job)


def install_pdf_routes(app, auth, body, index):
    imports = PdfImports(app.state.store.root)
    app.state.pdf_imports = imports

    async def perform(fn, *args):
        try:
            return await run_in_threadpool(fn, *args)
        except ParserError as exc:
            raise HTTPException(503, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.get("/api/knowledge/pdf/jobs")
    async def listing(request: Request):
        user = auth(request)
        return {"service": imports.capabilities(), "jobs": await perform(imports.listing, user["id"])}

    @app.post("/api/knowledge/pdf/jobs")
    async def create(request: Request):
        user = auth(request, mutate=True)
        return await perform(imports.create, user["id"], await body(request))

    @app.put("/api/knowledge/pdf/jobs/{job_id}/file")
    async def upload(job_id: str, request: Request):
        user = auth(request)
        job = await perform(imports.begin_upload, user["id"], job_id, request.headers.get("x-pdf-upload-token", ""))
        target = imports.folder(job_id) / "source.pdf"
        digest = hashlib.sha256()
        total, prefix = 0, b""
        try:
            with target.open("xb") as stream:
                async for block in request.stream():
                    total += len(block)
                    if total > job["bytes"] or total > MAX_PDF:
                        raise ValueError("PDF exceeded its declared size")
                    if len(prefix) < 5:
                        prefix = (prefix + block)[:5]
                    digest.update(block)
                    stream.write(block)
            if total != job["bytes"] or prefix != b"%PDF-":
                raise ValueError("Incomplete upload or invalid PDF header")
            job.update(sha256=digest.hexdigest(), artifacts=["original"])
            imports.save(job)
        except Exception:
            imports.fail(job, "PDF upload failed validation; not submitted to parser.")
            raise HTTPException(400, "PDF upload failed validation; create a new import to retry") from None
        return await perform(imports.submit, job)

    @app.get("/api/knowledge/pdf/jobs/{job_id}")
    async def status(job_id: str, request: Request):
        return await perform(imports.refresh, auth(request)["id"], job_id)

    @app.get("/api/knowledge/pdf/jobs/{job_id}/preview")
    async def preview(job_id: str, request: Request):
        return await perform(imports.preview, auth(request)["id"], job_id)

    @app.post("/api/knowledge/pdf/jobs/{job_id}/ingest")
    async def ingest(job_id: str, request: Request):
        user = auth(request, mutate=True)
        payload = await body(request)
        if payload.get("confirmed") is not True:
            raise HTTPException(400, "Confirm parsed output before indexing")
        return await perform(imports.ingest, user["id"], job_id, index)

    @app.get("/api/knowledge/pdf/jobs/{job_id}/artifacts/{kind}")
    async def artifact(job_id: str, kind: str, request: Request):
        job = await perform(imports.get, auth(request)["id"], job_id)
        if kind not in ARTIFACTS or kind not in job["artifacts"]:
            raise HTTPException(404, "Artifact not found")
        name, media = ARTIFACTS[kind]
        path = imports.folder(job_id) / name
        if not path.is_file():
            raise HTTPException(404, "Artifact not found")
        return FileResponse(path, media_type=media, filename=name, headers={
            "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'"})
    return imports

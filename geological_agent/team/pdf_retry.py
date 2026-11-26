"""Explicit, source-verified retries of confirmed terminal parser failures."""
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

from .pdf_imports import active_coordinator, safe_id


def _identity(value, job):
    if (not isinstance(value, dict) or type(value.get("bytes")) is not int
            or value["bytes"] != job["bytes"]
            or value.get("sha256sum") != job["sha256"]):
        raise ValueError("Parser file identity differs from the retained original")


def _unexpired(value):
    expires = value.get("expires_at")
    return expires is None or (
        type(expires) in (int, float) and expires > time.time())


def retry_failed_import(imports, owner, job_id, *, tier, reason, confirmed=False):
    if confirmed is not True:
        raise ValueError("Explicit confirmation is required for a parser retry")
    if tier not in {"standard", "advanced"} or not isinstance(reason, str) or not 0 < len(reason) <= 400:
        raise ValueError("An explicit supported strategy and retry reason are required")
    with imports.lock(job_id):
        job = imports.get(owner, job_id)
        if job["state"] != "failed" or active_coordinator(job):
            raise ValueError("Only an uncontrolled failed import can be retried")
        folder = imports.folder(job_id)
        source = folder / "source.pdf"
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            prefix = stream.read(5)
            digest.update(prefix)
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if prefix != b"%PDF-" or source.stat().st_size != job["bytes"] or digest.hexdigest() != job["sha256"]:
            raise ValueError("Retained original PDF integrity check failed")
        client = imports.client()
        old = client.json("GET", "/v1/parse/jobs/" + safe_id(job["remote_job"]))
        files = old.get("files") or []
        if (old.get("status") != "failed" or len(files) != 1
                or files[0].get("status") != "failed"
                or files[0].get("file_id") != job["remote_file"]):
            raise ValueError("The previous remote attempt is not a confirmed matching failure")
        error = files[0].get("error") or {}
        if tier == "standard" and (
                error.get("code") != "parse_failed"
                or "truncat" not in str(error.get("message", "")).lower()):
            raise ValueError("Standard recovery is restricted to a confirmed truncated-output failure")
        existing = client.json("GET", "/v1/files/" + safe_id(job["remote_file"]))
        _identity(existing, job)
        attempt = uuid.uuid4().hex
        audit = json.dumps({"previous_job": job, "remote_failure": old,
                            "previous_file": existing, "requested_tier": tier,
                            "reason": reason, "at": time.time()},
                           ensure_ascii=False, sort_keys=True).encode("utf-8")
        audit_path = folder / ("retry-audit-" + attempt + ".json")
        fd = os.open(audit_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(audit)
        job["retry"] = {
            "id": attempt, "tier": tier, "reason": reason,
            "previous_failure_sha256": hashlib.sha256(audit).hexdigest(),
            "started_at": time.time(), "source_sha256": job["sha256"],
        }
        job.update(state="submitting", error="")
        imports.save(job)
        try:
            if not _unexpired(existing):
                uploaded = client.json("POST", "/v1/uploads", {
                    "filename": job_id + ".pdf", "bytes": job["bytes"],
                    "mime_type": "application/pdf", "purpose": "parse",
                    "sha256sum": job["sha256"],
                })
                _identity(uploaded, job)
                job["remote_upload"] = safe_id(uploaded["id"])
                imports.save(job)
                if uploaded.get("status") == "pending":
                    client.upload(job["remote_upload"], source)
                    uploaded = client.json("POST", "/v1/uploads/" + job["remote_upload"] + "/complete",
                                           {"sha256sum": job["sha256"]})
                if uploaded.get("status") != "completed":
                    raise ValueError("Retry upload completion was not confirmed")
                _identity(uploaded, job)
                existing = uploaded.get("file")
                _identity(existing, job)
                if not _unexpired(existing):
                    raise ValueError("The renewed parser file has already expired")
                job["remote_file"] = safe_id(existing["id"])
                imports.save(job)
            response = client.json("POST", "/v1/parse/jobs", {
                "files": [{"source": {"type": "file_id", "file_id": job["remote_file"]}}],
                "tier": tier, "ocr_mode": "auto",
                "output_formats": ["markdown", "middle_json", "structured_content", "zip"],
            })
            job.update(remote_job=safe_id(response["job_id"]), state="queued", error="")
            imports.save(job)
        except Exception:
            # A failed response does not prove that the server rejected a job.
            # Preserve the audit and staged identifiers; never submit again blindly.
            job.update(state="submission_unknown",
                       error="Retry submission was not confirmed; original and prior failure audit retained. Reconcile before another retry.")
            imports.save(job)
            raise
        return imports.public(job)

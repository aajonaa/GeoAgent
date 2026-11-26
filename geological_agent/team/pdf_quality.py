"""Fail-closed source-bound quality holds for recovered PDF pages."""
import hashlib
import json
from pathlib import Path
import re

VERSION = "pdf-page-quality-v1"
HEX = re.compile(r"[a-f0-9]{64}")

class PdfPageQualityError(ValueError):
    pass

def _fail(message):
    raise PdfPageQualityError(message + "; original PDF and prior indexes retained")

def _record(folder, digest):
    if not isinstance(digest,str) or HEX.fullmatch(digest) is None:
        _fail("Invalid page-quality record identity")
    root=Path(folder).resolve()
    path=root/("page-quality-"+digest+".json")
    if path.is_symlink() or not path.is_file() or path.stat().st_size>1024*1024:
        _fail("Page-quality evidence is missing or unsafe")
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=digest:
        _fail("Page-quality evidence hash mismatch")
    try:
        record=json.loads(raw)
    except (ValueError,UnicodeError):
        _fail("Page-quality evidence is invalid")
    if not isinstance(record,dict) or record.get("version")!=VERSION:
        _fail("Unsupported page-quality evidence")
    return record

def _binding(record,job):
    offset=job.get("page_offset",0)
    expected=job.get("pages")
    if expected is None and type(job.get("original_pdf_page_start")) is int and type(job.get("original_pdf_page_end")) is int:
        expected=job["original_pdf_page_end"]-job["original_pdf_page_start"]+1
    if (record.get("job_id")!=job["id"] or record.get("owner")!=job["owner"]
            or record.get("source_sha256")!=job["sha256"]
            or type(record.get("page_count")) is not int or record["page_count"]!=expected
            or type(record.get("original_page_offset")) is not int or record["original_page_offset"]!=offset):
        _fail("Page-quality evidence source, owner or page binding mismatch")

def _issues(record):
    items=record.get("issues")
    if not isinstance(items,list) or not items:
        _fail("Recovered pages require explicit quality-issue evidence")
    numbers=[]
    for item in items:
        if (not isinstance(item,dict) or type(item.get("section_page")) is not int
                or not 1<=item["section_page"]<=record["page_count"]
                or item.get("original_pdf_page")!=record["original_page_offset"]+item["section_page"]
                or not isinstance(item.get("code"),str) or not item["code"]):
            _fail("Invalid page-quality issue location")
        numbers.append(item["section_page"])
    if len(set(numbers))!=len(numbers):
        _fail("Duplicate page-quality issue location")
    return items

def enforce_page_quality(job,folder,*,structure_sha256=None,structured_recovery=False):
    """No legacy behavior changes. Any declared recovery quality hold is mandatory."""
    recovery=job.get("page_recovery")
    pointer=job.get("page_quality")
    if recovery is None and pointer is None and structured_recovery is False:
        return None
    if recovery is not None and not isinstance(recovery,dict):
        _fail("Invalid PDF page-recovery state")
    if isinstance(recovery,dict) and recovery.get("quality_status") in {"blocked","needs_review","rejected"}:
        pages=recovery.get("blocked_original_pdf_pages") or []
        label=", ".join(str(p) for p in pages) or "unresolved pages"
        _fail("Source-quality review required for original PDF page(s) "+label)
    if not isinstance(pointer,dict):
        _fail("Recovered PDF pages lack verified page-quality evidence")
    record=_record(folder,pointer.get("sha256"))
    _binding(record,job)
    issues=_issues(record)
    if record.get("status")=="partial":
        from .pdf_partial import validate_partial_quality
        return validate_partial_quality(job,folder,record,structure_sha256=structure_sha256)
    if record.get("status")!="passed" or any(i.get("status")!="resolved" for i in issues):
        _fail("Recovered PDF page quality has not passed source review")
    artifacts=record.get("artifacts") or {}
    if (not isinstance(artifacts,dict) or not isinstance(artifacts.get("text_sha256"),str)
            or HEX.fullmatch(artifacts["text_sha256"]) is None
            or artifacts["text_sha256"]!=job.get("text_sha256")
            or not isinstance(artifacts.get("structure_sha256"),str)
            or HEX.fullmatch(artifacts["structure_sha256"]) is None
            or (structure_sha256 is not None and artifacts["structure_sha256"]!=structure_sha256)):
        _fail("Page-quality approval does not bind the current parsed artifacts")
    previous=_record(folder,record.get("previous_record_sha256"))
    _binding(previous,job)
    previous_issues=_issues(previous)
    if previous.get("status")!="blocked":
        _fail("Quality recovery must retain its original blocked evidence")
    old={(i["section_page"],i["original_pdf_page"],i["code"]) for i in previous_issues}
    new={(i["section_page"],i["original_pdf_page"],i["code"]) for i in issues}
    if old!=new:
        _fail("An original page-quality issue was dropped or changed")
    for issue in issues:
        resolution=issue.get("resolution") or {}
        if (not isinstance(resolution,dict) or resolution.get("status")!="verified"
                or resolution.get("review_method")!="same-edition-source-page-comparison"
                or resolution.get("original_pdf_page")!=issue["original_pdf_page"]
                or not isinstance(resolution.get("evidence_sha256"),str)
                or HEX.fullmatch(resolution["evidence_sha256"]) is None):
            _fail("Recovered page lacks an explicit same-edition source comparison")
        source=resolution.get("source") or {}
        if (not isinstance(source,dict) or source.get("kind") not in {"publisher_version","author_repository","original_pdf_reparse"}
                or not isinstance(source.get("sha256"),str) or HEX.fullmatch(source["sha256"]) is None):
            _fail("Recovered page source provenance is missing")
        if source["kind"]=="original_pdf_reparse":
            if source["sha256"]!=job["sha256"]:
                _fail("Original-page recovery source hash mismatch")
        else:
            # Only a content-addressed, retained PDF is accepted as supplementary source.
            from urllib.parse import urlsplit
            parts=urlsplit(source.get("url",""))
            if parts.scheme!="https" or not parts.hostname or parts.username or parts.password or parts.fragment:
                _fail("Supplementary page source must be a public HTTPS publication")
            supplement=Path(folder)/("supplement-"+source["sha256"]+".pdf")
            if supplement.is_symlink() or not supplement.is_file() or supplement.stat().st_size>50*1024*1024:
                _fail("Supplementary source PDF is missing or unsafe")
            h=hashlib.sha256()
            with supplement.open("rb") as stream:
                if stream.read(5)!=b"%PDF-":
                    _fail("Supplementary source is not a PDF")
                stream.seek(0)
                for block in iter(lambda:stream.read(1024*1024),b""):h.update(block)
            if h.hexdigest()!=source["sha256"]:
                _fail("Supplementary source PDF hash mismatch")
        evidence=Path(folder)/("page-review-"+resolution["evidence_sha256"]+".json")
        if evidence.is_symlink() or not evidence.is_file() or evidence.stat().st_size>1024*1024:
            _fail("Same-edition page comparison evidence is missing or unsafe")
        raw=evidence.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=resolution["evidence_sha256"]:
            _fail("Same-edition comparison evidence hash mismatch")
        try:proof=json.loads(raw)
        except (ValueError,UnicodeError):_fail("Invalid same-edition comparison evidence")
        if (not isinstance(proof,dict) or proof.get("status")!="verified"
                or proof.get("job_id")!=job["id"] or proof.get("owner")!=job["owner"]
                or proof.get("original_pdf_page")!=issue["original_pdf_page"]
                or proof.get("original_pdf_sha256")!=job["sha256"]
                or proof.get("replacement_source_sha256")!=source["sha256"]
                or proof.get("structure_sha256")!=artifacts["structure_sha256"]
                or proof.get("text_sha256")!=artifacts["text_sha256"]
                or proof.get("same_edition_verified") is not True
                or proof.get("numeric_and_text_comparison_passed") is not True):
            _fail("Same-edition comparison does not bind the current page and artifacts")
    return record


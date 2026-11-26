"""Explicit partial-page publication; unresolved source text never enters retrieval."""
import base64
import hashlib
import json
from pathlib import Path

from .pdf_quality import _record, _binding, _issues, _fail

def validate_partial_quality(job,folder,record,*,structure_sha256=None):
    coverage=record.get("coverage") or {}
    n=record["page_count"];offset=record["original_page_offset"]
    included=coverage.get("included_section_pages")
    excluded=coverage.get("excluded_section_pages")
    if (coverage.get("status")!="partial" or coverage.get("complete") is not False
            or coverage.get("source_pages")!=n or coverage.get("original_page_offset")!=offset
            or coverage.get("original_pdf_retained") is not True
            or not isinstance(included,list) or not isinstance(excluded,list) or not included or not excluded
            or any(type(p) is not int for p in included+excluded)
            or included!=sorted(set(included)) or excluded!=sorted(set(excluded))
            or set(included)&set(excluded) or sorted(included+excluded)!=list(range(1,n+1))
            or coverage.get("excluded_original_pdf_pages")!=[p+offset for p in excluded]):
        _fail("Partial source coverage is incomplete or falsely claims completion")
    previous=_record(folder,record.get("previous_record_sha256"));_binding(previous,job)
    old=_issues(previous);issues=_issues(record)
    if (previous.get("status")!="blocked"
            or {(i["section_page"],i["original_pdf_page"],i["code"]) for i in old}
             !={(i["section_page"],i["original_pdf_page"],i["code"]) for i in issues}
            or sorted(i["section_page"] for i in issues)!=excluded
            or any(i.get("status")!="excluded_pending_review" for i in issues)):
        _fail("Partial publication dropped or falsely resolved a blocked page")
    authorization=_record(folder,record.get("authorization_sha256"));_binding(authorization,job)
    if (authorization.get("purpose")!="partial_publication_authorization"
            or authorization.get("allow_partial_index") is not True
            or authorization.get("claim_complete") is not False
            or authorization.get("excluded_section_pages")!=excluded
            or authorization.get("included_section_pages")!=included
            or authorization.get("retain_original_pdf") is not True):
        _fail("Partial publication lacks explicit source-bound authorization")
    root=Path(folder);path=root/"structure.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size>100*1024*1024:
        _fail("Partial projection structure is missing or unsafe")
    raw=path.read_bytes();h=hashlib.sha256(raw).hexdigest()
    artifacts=record.get("artifacts") or {}
    if (artifacts.get("structure_sha256")!=h
            or (structure_sha256 is not None and structure_sha256!=h)
            or artifacts.get("text_sha256")!=job.get("text_sha256")):
        _fail("Partial approval does not bind the current projection artifacts")
    try:structured=json.loads(raw)
    except (ValueError,UnicodeError):_fail("Invalid partial projection structure")
    pages=structured.get("pages",[]) if isinstance(structured,dict) else []
    if (structured.get("is_full_document") is not False
            or [p.get("page_idx") for p in pages if isinstance(p,dict)]!=list(range(n))
            or structured.get("extensions",{}).get("source_coverage")!=coverage):
        _fail("Partial projection lost source pages or its explicit coverage warning")
    hashes=record.get("included_page_sha256") or {}
    for number in included:
        page=pages[number-1]
        canonical=json.dumps(page,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
        if hashes.get(str(number))!=hashlib.sha256(canonical).hexdigest():
            _fail("An included parser page changed after publication review")
    for number in excluded:
        page=pages[number-1];blocks=page.get("blocks")
        render=_record(folder,(record.get("page_render_records") or {}).get(str(number)))
        _binding(render,job)
        if (render.get("purpose")!="original_page_render"
                or render.get("section_page")!=number
                or render.get("original_pdf_page")!=offset+number):
            _fail("Pending page original-image provenance mismatch")
        if not isinstance(blocks,list) or len(blocks)!=1:
            _fail("Pending page must retain only its original image")
        block=blocks[0]
        if (block.get("type")!="image" or block.get("content")!=""
                or block.get("captions") or block.get("footnotes")
                or not isinstance(block.get("image_source"),str)
                or not block["image_source"].startswith("data:image/png;base64,")):
            _fail("Unreviewed page text or invented captions reached the projection")
        try:image=base64.b64decode(block["image_source"].split(",",1)[1],validate=True)
        except (ValueError,TypeError):_fail("Invalid pending-page image encoding")
        if (not image.startswith(b"\x89PNG\r\n\x1a\n") or len(image)>20*1024*1024
                or hashlib.sha256(image).hexdigest()!=render.get("image_sha256")):
            _fail("Pending page image differs from its retained original render")
    return record

def apply_partial_context(doc,record):
    if not record or record.get("status")!="partial":return None
    coverage=record["coverage"]
    suffix=" [partial "+str(len(coverage["included_section_pages"]))+"/"+str(coverage["source_pages"])+"]"
    title=doc["title"]+suffix
    if len(title)>160:_fail("An explicit shorter title is required for the partial publication")
    doc["title"]=title
    doc["source_coverage"]=coverage
    if doc["quality_status"]!="blocked":doc["quality_status"]="partial"
    doc["issues"].append({"severity":"warning","code":"partial_source_pending_pages",
        "message":"Partial source: original PDF page(s) "+", ".join(map(str,coverage["excluded_original_pdf_pages"]))+
                  " retained as images, with unreviewed text excluded; not a complete publication."})
    return coverage

def annotate_partial_chunks(doc,parts,coverage):
    if not coverage:return
    allowed=set(coverage["included_section_pages"])
    for part in parts:
        sources=part["metadata"].get("sources")
        if not isinstance(sources,list) or not sources or any(s.get("page") not in allowed for s in sources):
            _fail("A retrieval chunk includes an unreviewed or unbound page")
        part["metadata"]["source_coverage"]=coverage
        part["metadata"]["source_completeness"]="partial"
        part["metadata"]["original_pdf_pages"]=sorted({s["page"]+coverage["original_page_offset"] for s in sources})
        part["metadata"]["excluded_original_pdf_pages"]=coverage["excluded_original_pdf_pages"]


"""OpenAlex discovery and source-attributed scientific writing."""

import hashlib
import json
import os
import re
import time

import httpx

from .tools import ToolFailure, ToolOutput, write_file


WORK_ID = r"W[0-9]{1,15}"
OPENALEX_URL = "https://api.openalex.org"
FIELDS = "id,title,publication_year,doi,authorships,open_access,is_retracted"


def _get(route, ctx, **params):
    ctx.check()
    key = os.environ.get("OPENALEX_API_KEY")
    if key:
        params["api_key"] = key
    try:
        timeout = min(8.0, max(0.1, ctx.deadline - time.monotonic()))
        with httpx.Client(base_url=OPENALEX_URL, timeout=timeout, follow_redirects=False) as client:
            response = client.get(route, params={**params, "select": FIELDS})
        if response.status_code == 404:
            return None
        if response.status_code in (401, 403, 429):
            raise ToolFailure("openalex_access", f"OpenAlex returned HTTP {response.status_code}. Check API access or quota.")
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Unexpected response")
        ctx.check()
        return body
    except (httpx.HTTPError, ValueError):
        raise ToolFailure("openalex_unavailable", "OpenAlex could not return valid metadata. Retry or report the source as unavailable.", retryable=True) from None


def _work(row):
    if not isinstance(row, dict):
        return None
    identifier = str(row.get("id") or "").removeprefix("https://openalex.org/")
    if not re.fullmatch(WORK_ID, identifier) or not isinstance(row.get("title"), str):
        return None
    doi = row.get("doi")
    if not isinstance(doi, str) or not doi.startswith("https://doi.org/"):
        doi = None
    authors = [(item.get("author") or {}).get("display_name") for item in row.get("authorships") or []]
    return {
        "id": identifier,
        "url": "https://openalex.org/" + identifier,
        "title": row["title"][:500],
        "doi": doi,
        "year": row.get("publication_year"),
        "authors": [name[:120] for name in authors[:4] if isinstance(name, str)],
        "open_access": bool((row.get("open_access") or {}).get("is_oa")),
        "retracted": row.get("is_retracted") is True,
    }


def openalex_search(args, ctx):
    query = args["query"].strip()
    if not query:
        raise ToolFailure("invalid_query", "Supply search keywords.")
    params = {"search": query, "per-page": args.get("limit", 5)}
    if "since_year" in args:
        params["filter"] = "from_publication_date:" + str(args["since_year"]) + "-01-01"
    body = _get("/works", ctx, **params)
    if body is None or not isinstance(body.get("results"), list):
        raise ToolFailure("openalex_unavailable", "OpenAlex returned no valid search response.", retryable=True)
    return ToolOutput({"query": query, "works": [work for row in body["results"] if (work := _work(row))]})


def _plain(value):
    return " ".join(value.split())


def citation_audit(args, ctx):
    references = {}
    unresolved = {}
    ids = dict.fromkeys(work_id for claim in args["claims"] for work_id in claim["work_ids"])
    if len(ids) > 8:
        raise ToolFailure("too_many_references", "Audit up to eight distinct references per report.", retryable=True)
    for work_id in ids:
        record = _work(_get("/works/" + work_id, ctx))
        if record is None or record["id"] != work_id:
            unresolved[work_id] = "not_found"
        elif record["retracted"]:
            unresolved[work_id] = "retracted"
        else:
            references[work_id] = record
    claims = [{"text": _plain(claim["text"]), "work_ids": claim["work_ids"]} for claim in args["claims"]]
    audit = {
        "schema": 1, "source": "OpenAlex", "title": _plain(args["title"]), "claims": claims,
        "references": references, "unresolved": unresolved,
        "scope": "Bibliographic metadata checked. Claim support requires review of the underlying papers.",
    }
    content = json.dumps(audit, ensure_ascii=False, indent=2) + "\n"
    prefix = "research-citations-" + hashlib.sha256(content.encode()).hexdigest()[:20]
    report = [f"# {audit['title']}", "", audit["scope"], ""]
    report.extend("- " + claim["text"] + " " + " ".join(f"[{key}]" for key in claim["work_ids"]) for claim in claims)
    report.extend(["", "## References", ""])
    report.extend(f"- {key} · {row['title']} ({row['year'] or 'n.d.'}) · {row['doi'] or row['url']}"
                  for key, row in references.items())
    if unresolved:
        report.extend(["", "## References needing attention", ""])
        report.extend(f"- {key} · {reason}" for key, reason in unresolved.items())
    result = write_file({"path": prefix + ".json", "content": content}, ctx)
    writing = write_file({"path": prefix + ".md", "content": "\n".join(report) + "\n"}, ctx)
    receipts = ctx.evidence_state.setdefault("research_citation_audits", {})
    receipts[result.data["path"]] = result.data["sha256"]
    return ToolOutput({"audit_path": result.data["path"], "audit_sha256": result.data["sha256"],
                       "report_path": writing.data["path"], "verified_ids": list(references), "unresolved": unresolved},
                      result.artifacts + writing.artifacts)

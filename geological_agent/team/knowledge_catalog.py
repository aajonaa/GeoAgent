"""Account-owned import catalog; classification is not execution/factual proof."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time

from fastapi import Request
from starlette.concurrency import run_in_threadpool
from ..rag.limits import account_limits

CLASSIFIER_VERSION = "liba-source-keyword-facets-v1"
DEPOSITS = {
    "李坝": r"李坝|\bLiba\b", "寨上": r"寨上|\bZhaishang\b",
    "马坞": r"马坞|\bMawu\b", "鹿儿坝": r"鹿儿坝|\bLu.?erba\b",
    "金山矿区": r"南金山|北金山|\bNanjinshan\b|\bBeijinshan\b",
    "代家庄": r"代家庄|\bDaijiazhuang\b", "锁龙": r"锁龙|\bSuolong\b",
    "雪坪沟": r"雪坪沟|\bXuepinggou\b", "柏家庄／闾井": r"柏家庄|闾井|\bBaijiazhuang\b|\bLujing\b",
}
TOPICS = {
    "年代学与同位素": r"年代学|定年|成矿时代|同位素|U.?Pb|Ar.?Ar|geochronolog|isotop|provenance",
    "成矿流体与包裹体": r"成矿流体|流体包裹体|包裹体|热液|fluid|inclusion|hydrothermal",
    "矿物与元素地球化学": r"黄铁矿|硫化物|石英|矿物学|微量元素|稀土|pyrite|sulfide|mineralog|trace.element|geochem",
    "构造控矿与成矿模式": r"构造|剪切|断裂|褶皱|背斜|成矿模式|控矿|tectonic|structur|metallogen|genetic.mechanism",
    "找矿预测与勘查": r"找矿|勘查|预测|原生晕|化探|异常|prospect|explorat|prediction|geochemical.halo",
    "地球物理与深部结构": r"地球物理|物探|激电|电阻率|电法|深部结构|磁大地|CSAMT|geophys|magnetotelluric|resistivity",
    "遥感与蚀变": r"遥感|蚀变|高光谱|红外|hyperspectral|alteration|remote.sens",
    "区域背景与岩浆岩": r"岩浆|花岗岩|围岩|沉积|岩体|magmat|granit|sediment|metasediment|petrogen",
    "资源利用与环境": r"选矿|选冶|矿石加工|环境|砷的形态|pollution|beneficiation|environment|ore.processing",
}


def classify(structured, title):
    blocks = []
    source_kinds = {"text", "paragraph", "doc_title", "paragraph_title", "title", "heading", "list", "caption"}
    for page in structured.get("pages", []):
        for block in page.get("blocks", []):
            if block.get("type") not in source_kinds or block.get("sub_type") == "ref_text":
                continue
            text = block.get("content")
            if isinstance(text, str) and text.strip():
                blocks.append({"page": page.get("page_idx", 0) + 1, "text": text})
    body = "\n".join(block["text"] for block in blocks)
    evidence = []

    def labels(rules, maximum, threshold):
        ranked = []
        for label, pattern in rules.items():
            rx = re.compile(pattern, re.I)
            hits = sum(min(20, len(rx.findall(block["text"]))) for block in blocks)
            title_hits = len(rx.findall(title))
            weight = title_hits * 12 + min(hits, 30)
            if hits and (title_hits or hits >= threshold):
                ranked.append((weight, label, rx))
        selected = sorted(ranked, key=lambda item: (-item[0], item[1]))[:maximum]
        for _, label, rx in selected:
            for block in blocks:
                match = rx.search(block["text"])
                if match:
                    evidence.append({"label": label, "page": block["page"], "keyword": match.group(),
                        "quote": block["text"][max(0, match.start()-45):match.end()+75]})
                    break
        return [label for _, label, _ in selected]

    deposits = labels(DEPOSITS, 3, 4)
    topics = labels(TOPICS, 3, 5)
    return {"deposits": deposits, "topics": topics, "classification": "automatic_not_expert_verified",
            "classifier": CLASSIFIER_VERSION, "classification_evidence": evidence,
            "classification_source_sha256": hashlib.sha256(body.encode()).hexdigest()}


class KnowledgeCatalog:
    def __init__(self, root):
        self.path = Path(root) / "knowledge-catalog.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS batches(owner TEXT NOT NULL,id TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(owner,id))")
            db.execute("CREATE TABLE IF NOT EXISTS items(owner TEXT NOT NULL,batch_id TEXT NOT NULL,sha TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(owner,batch_id,sha))")
        if os.name != "nt":
            self.path.chmod(0o600)

    @contextmanager
    def connection(self):
        with sqlite3.connect(self.path, timeout=20) as db:
            yield db

    def batch(self, owner, batch_id, **fields):
        with self.connection() as db:
            row = db.execute("SELECT data FROM batches WHERE owner=? AND id=?", (owner, batch_id)).fetchone()
            data = json.loads(row[0]) if row else {"id": batch_id, "created_at": time.time()}
            data.update(fields, updated_at=time.time())
            db.execute("INSERT INTO batches VALUES(?,?,?) ON CONFLICT(owner,id) DO UPDATE SET data=excluded.data",
                       (owner, batch_id, json.dumps(data, ensure_ascii=False)))
        return data

    def item(self, owner, batch_id, sha, **fields):
        if not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise ValueError("Original PDF SHA256 is required")
        with self.connection() as db:
            row = db.execute("SELECT data FROM items WHERE owner=? AND batch_id=? AND sha=?", (owner, batch_id, sha)).fetchone()
            data = json.loads(row[0]) if row else {"sha256": sha, "state": "pending"}
            data.update(fields, updated_at=time.time())
            db.execute("INSERT INTO items VALUES(?,?,?,?) ON CONFLICT(owner,batch_id,sha) DO UPDATE SET data=excluded.data",
                       (owner, batch_id, sha, json.dumps(data, ensure_ascii=False)))
        return data

    def get_item(self, owner, batch_id, sha):
        with self.connection() as db:
            row = db.execute("SELECT data FROM items WHERE owner=? AND batch_id=? AND sha=?", (owner, batch_id, sha)).fetchone()
        return json.loads(row[0]) if row else None

    def listing(self, owner):
        with self.connection() as db:
            batches = [json.loads(row[0]) for row in db.execute("SELECT data FROM batches WHERE owner=?", (owner,))]
            rows = [(row[0], json.loads(row[1])) for row in db.execute("SELECT batch_id,data FROM items WHERE owner=?", (owner,))]
        documents, facets = {}, {"groups": set(), "deposits": set(), "topics": set()}
        summaries = []
        for batch in batches:
            items = [data for identifier, data in rows if identifier == batch["id"]]
            summary = dict(batch)
            summary.update(parsed=sum(item.get("parsed") is True for item in items),
                           indexed=sum(item.get("state") == "indexed" for item in items),
                           partially_indexed=sum(item.get("state") == "partially_indexed" for item in items),
                           pending_pages=sum(len((item.get("coverage") or {}).get("excluded_original_pdf_pages", [])) for item in items),
                           failed=sum(item.get("state") == "failed" for item in items),
                           blocked=sum(item.get("state") in {"needs_review", "submission_unknown"} for item in items))
            summaries.append(summary)
            for item in items:
                for key in facets:
                    facets[key].update(item.get(key, []))
                if item.get("document_id") and item.get("state") in {"indexed", "partially_indexed"}:
                    documents[item["document_id"]] = {key: item[key] for key in
                        ("groups", "deposits", "topics", "aliases", "classification", "classification_evidence", "coverage", "state") if key in item}
                    documents[item["document_id"]].update(collection=batch.get("label", ""), sha256=item["sha256"])
        return {"batches": summaries, "documents": documents,
                "facets": {key: sorted(values) for key, values in facets.items()},
                "limits": account_limits(owner)}


def install_catalog_routes(app, auth):
    catalog = KnowledgeCatalog(app.state.store.root)
    app.state.knowledge_catalog = catalog

    @app.get("/api/knowledge/catalog")
    async def listing(request: Request):
        user = auth(request)
        return await run_in_threadpool(catalog.listing, user["id"])

    return catalog


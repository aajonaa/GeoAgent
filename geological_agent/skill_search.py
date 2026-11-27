"""Hybrid semantic + lexical skill retrieval for OreBOGAO's 191+ geoscience skills.

Combines:
1. BM25-weighted field lexical search (id/name/description/when_to_use/tool_names)
   with English suffix folding, CJK bigrams, and bilingual geoscience concept expansion.
2. Optional dense semantic vector search using the deployment's existing Qwen
   `EncoderClient` (or any injected `embed(texts, query=...)` encoder) with
   fingerprint-keyed in-memory/disk embedding caching.
3. Reciprocal Rank Fusion (RRF) with strict zero-match preservation so unrelated
   queries still return an empty result rather than noise.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
from threading import RLock
from typing import Callable, Iterable

_CJK = re.compile(r"[\u3400-\u9fff]")
_IGNORED = frozenset({
    "the", "and", "or", "for", "with", "from", "to", "of", "in", "on", "by", "at", "as", "is", "are", "be",
})
_SUFFIXES = ("ings", "ing", "ions", "ion", "ies", "es", "ed", "s", "e")

# Bilingual geoscience domain concept groups so Chinese queries can match
# English-authored skill descriptions (and vice versa) even when no dense
# embedding server is configured.
_CONCEPT_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"地震", "震级", "地震波", "震源", "地震能量", "earthquake", "seismic", "magnitude", "seismology"}),
    frozenset({"插值", "克里金", "变异函数", "半变异", "空间插值", "kriging", "variogram", "interpolate", "interpolation"}),
    frozenset({"水文", "径流", "流域", "流量", "水文模型", "降水", "蒸散发", "hydrology", "hydrologic", "runoff", "watershed", "streamflow", "discharge", "hydrograph"}),
    frozenset({"地下水", "含水层", "渗流", "达西", "水位", "抽水", "groundwater", "aquifer", "darcy", "hydraulic", "piezometric"}),
    frozenset({"测井", "岩性", "岩石物理", "孔隙度", "渗透率", "声波", "电阻率", "well", "log", "logging", "lithology", "petrophysics", "porosity", "permeability"}),
    frozenset({"地球化学", "稀土", "主量元素", "微量元素", "花岗岩", "火成岩", "变质岩", "岩石化学", "geochemistry", "geochemical", "ree", "igneous", "petrology"}),
    frozenset({"矿床", "矿产", "成矿", "斑岩", "斑岩铜矿", "品位", "储量", "资源量", "mineral", "deposit", "ore", "porphyry", "commodity", "mining", "grade", "tonnage"}),
    frozenset({"遥感", "影像", "栅格", "高程", "地形", "植被指数", "卫星", "raster", "remote", "sensing", "satellite", "dem", "ndvi", "geotiff"}),
    frozenset({"空间分析", "空间自相关", "莫兰", "热点", "缓冲区", "矢量", "spatial", "moran", "autocorrelation", "gis", "vector", "shapefile", "geojson"}),
    frozenset({"坐标", "投影", "大地测量", "经纬度", "距离", "方位角", "geodesic", "coordinate", "projection", "crs", "epsg", "utm", "wgs84", "azimuth"}),
    frozenset({"地球物理", "重力", "磁异常", "磁法", "电法", "反演", "位场", "geophysics", "geophysical", "gravity", "magnetic", "inversion", "potential", "bouguer"}),
    frozenset({"气候", "古气候", "温度", "情景", "大气", "气象", "climate", "paleoclimate", "weather", "temperature", "ssp", "atmosphere", "meteorology"}),
    frozenset({"海洋", "盐度", "海表", "碳循环", "剖面", "ocean", "oceanography", "salinity", "marine", "carbon", "bathymetry"}),
    frozenset({"构造", "断层", "褶皱", "产状", "赤平投影", "应力", "structural", "fault", "fold", "strike", "dip", "stereonet", "tectonic", "stress"}),
    frozenset({"地层", "沉积", "年代", "同位素", "测年", "化石", "stratigraphy", "sediment", "sedimentary", "chronology", "isotope", "geochronology", "zircon"}),
    frozenset({"图像", "数字化", "曲线提取", "色标", "读图", "识图", "image", "digitization", "digitize", "curve", "plot", "color", "colorbar", "figure"}),
    frozenset({"文献", "论文", "检索", "引用", "综述", "写作", "literature", "paper", "openalex", "citation", "review", "writing", "academic", "bibliography"}),
    frozenset({"幻灯片", "汇报", "演示", "ppt", "表格", "文档", "报告", "slide", "slides", "presentation", "pptx", "docx", "xlsx", "pdf", "table", "report"}),
    frozenset({"能源", "风电", "光伏", "装机", "新能源", "发电", "energy", "renewable", "solar", "wind", "capacity", "power", "facility"}),
    frozenset({"规划", "计划", "进度", "任务拆解", "plan", "planning", "workflow", "progress", "todo"}),
)


def stem_word(word: str) -> str:
    for suffix in _SUFFIXES:
        if not word.endswith(suffix) or len(word) - len(suffix) < 4:
            continue
        if suffix == "s" and word.endswith(("ss", "is", "us")):
            continue
        base = word[:-len(suffix)]
        if suffix == "ies":
            return base + "y"
        if suffix in ("ing", "ings", "ed") and len(base) >= 4 and base[-1] == base[-2] and base[-1] not in "lsz":
            return base[:-1]
        return base
    return word


def tokenize_terms(text: str) -> list[str]:
    """Tokenize into stemmed English tokens and CJK bigrams (preserving multiplicity for BM25)."""
    tokens: list[str] = []
    for run in re.findall(r"[\u3400-\u9fff]+|[^\W\u3400-\u9fff]+", text.casefold()):
        if _CJK.match(run):
            for i in range(len(run) - 1):
                tokens.append(run[i:i + 2])
        elif len(run) > 1 and run not in _IGNORED:
            # Split snake_case / camel-ish identifiers too so `earthquake_energy` matches `earthquake`.
            if "_" in run:
                for part in run.split("_"):
                    if len(part) > 1 and part not in _IGNORED:
                        tokens.append(stem_word(part))
            tokens.append(stem_word(run))
    return tokens


def search_term_set(text: str) -> set[str]:
    return set(tokenize_terms(text))


# Pre-index concept groups by both exact normalized strings and tokenized terms.
_CONCEPT_INDEX: list[tuple[set[str], set[str]]] = []
for _group in _CONCEPT_GROUPS:
    _raw_cjk = {w for w in _group if _CJK.search(w)}
    _terms = set()
    for _w in _group:
        _terms.update(tokenize_terms(_w))
    _CONCEPT_INDEX.append((_raw_cjk, _terms))


def expand_query_concepts(query: str, query_terms: set[str]) -> set[str]:
    """Return bilingual expansion terms triggered by matching domain concepts."""
    q_fold = query.casefold()
    expanded: set[str] = set()
    for raw_cjk, group_terms in _CONCEPT_INDEX:
        matched = bool(query_terms & group_terms)
        if not matched and raw_cjk:
            matched = any(phrase in q_fold for phrase in raw_cjk)
        if matched:
            expanded.update(group_terms)
    return expanded - query_terms


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return list(vec)
    return [float(x) / norm for x in vec]


def _default_encoder():
    """Return configured Qwen EncoderClient if enabled and available, else None."""
    mode = os.environ.get("GEOTOOL_SKILL_SEMANTIC", "auto").strip().lower()
    if mode == "off":
        return None
    if not os.environ.get("GEOTOOL_QWEN_CONFIG_FILE"):
        if mode == "required":
            raise RuntimeError("GEOTOOL_SKILL_SEMANTIC=required but GEOTOOL_QWEN_CONFIG_FILE is not set")
        return None
    try:
        from .rag.store import EncoderClient
        return EncoderClient()
    except Exception:
        if mode == "required":
            raise
        return None


class SkillHybridIndex:
    """Hybrid BM25 + bilingual expansion + optional dense semantic RRF index over skills."""

    def __init__(
        self,
        *,
        encoder=None,
        encoder_factory: Callable[[], object | None] | None = None,
        cache_path: str | Path | None = None,
        semantic_threshold: float = 0.38,
        rrf_k: int = 60,
        bm25_k1: float = 1.5,
        bm25_b: float = 0.75,
    ):
        self._encoder = encoder
        self._encoder_factory = encoder_factory if encoder is None else None
        self._encoder_checked = encoder is not None
        env_cache = os.environ.get("GEOTOOL_SKILL_EMBED_CACHE", "").strip()
        self._cache_path = Path(cache_path) if cache_path else (Path(env_cache) if env_cache else None)
        self.semantic_threshold = float(semantic_threshold)
        self.rrf_k = int(rrf_k)
        self.bm25_k1 = float(bm25_k1)
        self.bm25_b = float(bm25_b)

        self._lock = RLock()
        self._fingerprint: str | None = None
        self._docs: list[dict] = []
        self._idf: dict[str, float] = {}
        self._avg_dl: float = 1.0
        self._vectors: dict[str, list[float]] | None = None
        self._vector_fingerprint: str | None = None
        self.last_search_meta: dict = {}

    @staticmethod
    def _skill_payload(skill) -> dict:
        summary = skill.summary
        tool_names = tuple(getattr(skill, "tool_names", ()))
        return {
            "id": summary.id,
            "name": summary.name,
            "description": summary.description,
            "when_to_use": summary.when_to_use,
            "tool_names": tool_names,
            "summary": summary,
        }

    @staticmethod
    def _compute_fingerprint(skills: Iterable) -> str:
        rows = []
        for skill in skills:
            s = skill.summary
            rows.append([s.id, s.name, s.description, s.when_to_use, list(getattr(skill, "tool_names", ()))])
        rows.sort(key=lambda r: r[0])
        return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]

    def _ensure_lexical_index(self, skills: list) -> str:
        fp = self._compute_fingerprint(skills)
        if fp == self._fingerprint:
            return fp
        docs = []
        df: Counter = Counter()
        total_len = 0.0
        for skill in skills:
            info = self._skill_payload(skill)
            id_tokens = tokenize_terms(info["id"])
            name_tokens = tokenize_terms(info["name"])
            desc_tokens = tokenize_terms(info["description"])
            when_tokens = tokenize_terms(info["when_to_use"])
            tool_tokens = tokenize_terms(" ".join(info["tool_names"]))

            # Weighted term frequencies per field.
            tf: Counter = Counter()
            for t in id_tokens:
                tf[t] += 2.5
            for t in name_tokens:
                tf[t] += 2.2
            for t in desc_tokens:
                tf[t] += 1.4
            for t in when_tokens:
                tf[t] += 1.2
            for t in tool_tokens:
                tf[t] += 1.0

            doc_len = sum(tf.values()) or 1.0
            total_len += doc_len
            for term in tf:
                df[term] += 1

            raw_text = " ".join((
                info["id"], info["name"], info["description"], info["when_to_use"], " ".join(info["tool_names"])
            )).casefold()
            embed_text = (
                f"{info['name']} ({info['id']}): {info['description']} "
                f"When to use: {info['when_to_use']}. "
                f"Tools: {', '.join(info['tool_names'][:12])}."
            )
            docs.append({
                "id": info["id"],
                "summary": info["summary"],
                "tf": tf,
                "doc_len": doc_len,
                "raw_text": raw_text,
                "embed_text": embed_text,
            })

        n_docs = max(len(docs), 1)
        idf = {
            term: math.log(1.0 + (n_docs - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }
        self._docs = docs
        self._idf = idf
        self._avg_dl = (total_len / n_docs) if docs else 1.0
        self._fingerprint = fp
        if self._vector_fingerprint != fp:
            self._vectors = None
            self._vector_fingerprint = None
        return fp

    def _get_encoder(self):
        if self._encoder is not None:
            return self._encoder
        if not self._encoder_checked:
            self._encoder_checked = True
            factory = self._encoder_factory or _default_encoder
            self._encoder = factory()
        return self._encoder

    def _load_disk_cache(self, fp: str) -> dict[str, list[float]] | None:
        if self._cache_path is None or not self._cache_path.is_file():
            return None
        try:
            payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
            if payload.get("fingerprint") != fp:
                return None
            vectors = payload.get("vectors")
            if isinstance(vectors, dict) and len(vectors) == len(self._docs):
                return vectors
        except Exception:
            return None
        return None

    def _save_disk_cache(self, fp: str, vectors: dict[str, list[float]]) -> None:
        if self._cache_path is None:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path.with_suffix(self._cache_path.suffix + ".tmp")
            tmp.write_text(json.dumps({"fingerprint": fp, "vectors": vectors}), encoding="utf-8")
            os.replace(tmp, self._cache_path)
        except Exception:
            pass

    def _ensure_vectors(self, fp: str) -> dict[str, list[float]] | None:
        if self._vectors is not None and self._vector_fingerprint == fp:
            return self._vectors
        encoder = self._get_encoder()
        if encoder is None or not self._docs:
            return None
        cached = self._load_disk_cache(fp)
        if cached is not None:
            self._vectors = cached
            self._vector_fingerprint = fp
            return cached
        try:
            texts = [doc["embed_text"] for doc in self._docs]
            raw_vecs = encoder.embed(texts, query=False)
            if len(raw_vecs) != len(self._docs):
                return None
            vectors = {doc["id"]: _normalize(vec) for doc, vec in zip(self._docs, raw_vecs)}
            self._vectors = vectors
            self._vector_fingerprint = fp
            self._save_disk_cache(fp, vectors)
            return vectors
        except Exception:
            mode = os.environ.get("GEOTOOL_SKILL_SEMANTIC", "auto").strip().lower()
            if mode == "required":
                raise
            return None

    def _lexical_scores(self, query: str) -> dict[str, float]:
        direct_terms = search_term_set(query)
        if not direct_terms:
            return {}
        expanded_terms = expand_query_concepts(query, direct_terms)
        scores: dict[str, float] = {}
        k1, b, avg_dl = self.bm25_k1, self.bm25_b, self._avg_dl
        for doc in self._docs:
            tf = doc["tf"]
            raw_text = doc["raw_text"]
            dl = doc["doc_len"]
            denom_norm = k1 * (1.0 - b + b * (dl / avg_dl))
            score = 0.0
            matched_direct = 0
            for term in direct_terms:
                freq = tf.get(term, 0.0)
                if freq == 0.0 and _CJK.match(term) is not None and term in raw_text:
                    freq = 1.0
                if freq > 0.0:
                    matched_direct += 1
                    idf = self._idf.get(term, 1.0)
                    score += idf * ((freq * (k1 + 1.0)) / (freq + denom_norm))
            if matched_direct:
                # Reward higher coverage of exact user query terms.
                score *= 1.0 + 0.35 * (matched_direct / len(direct_terms))
            # Bilingual concept expansion gets a secondary weight (0.25x) so
            # exact lexical matches always outrank synonym-only matches.
            if expanded_terms:
                exp_score = 0.0
                for term in expanded_terms:
                    freq = tf.get(term, 0.0)
                    if freq == 0.0 and _CJK.match(term) is not None and term in raw_text:
                        freq = 1.0
                    if freq > 0.0:
                        idf = self._idf.get(term, 1.0)
                        exp_score += idf * ((freq * (k1 + 1.0)) / (freq + denom_norm))
                score += 0.25 * exp_score
            if score > 0.0:
                scores[doc["id"]] = score
        return scores

    def _semantic_scores(self, query: str, fp: str) -> dict[str, float]:
        vectors = self._ensure_vectors(fp)
        if not vectors:
            return {}
        encoder = self._get_encoder()
        if encoder is None:
            return {}
        try:
            q_vecs = encoder.embed([query], query=True)
            if not q_vecs:
                return {}
            q_vec = _normalize(q_vecs[0])
        except Exception:
            mode = os.environ.get("GEOTOOL_SKILL_SEMANTIC", "auto").strip().lower()
            if mode == "required":
                raise
            return {}
        scores: dict[str, float] = {}
        for doc in self._docs:
            vec = vectors.get(doc["id"])
            if vec is None:
                continue
            sim = _cosine(q_vec, vec)
            if sim >= self.semantic_threshold:
                scores[doc["id"]] = sim
        return scores

    def search(self, skills: Iterable, query: str, *, limit: int | None = None) -> tuple:
        """Rank skills via lexical BM25 + bilingual expansion + optional dense semantic RRF."""
        skill_list = list(skills)
        if not query or not query.strip():
            summaries = tuple(skill.summary for skill in skill_list)
            return summaries[:limit] if limit is not None else summaries

        with self._lock:
            fp = self._ensure_lexical_index(skill_list)
            lex_scores = self._lexical_scores(query)
            sem_scores = self._semantic_scores(query, fp)

            candidate_ids = set(lex_scores) | set(sem_scores)
            if not candidate_ids:
                self.last_search_meta = {
                    "mode": "hybrid" if self._vectors is not None else "lexical_bm25",
                    "lexical_hits": 0,
                    "semantic_hits": 0,
                    "returned": 0,
                }
                return ()

            lex_rank = {sid: idx + 1 for idx, (sid, _) in enumerate(sorted(lex_scores.items(), key=lambda kv: (-kv[1], kv[0])))}
            sem_rank = {sid: idx + 1 for idx, (sid, _) in enumerate(sorted(sem_scores.items(), key=lambda kv: (-kv[1], kv[0])))}

            k = self.rrf_k
            by_id = {doc["id"]: doc["summary"] for doc in self._docs}
            fused: list[tuple[float, str, object]] = []
            for sid in candidate_ids:
                score = 0.0
                if sid in lex_rank:
                    # Slight lexical preference (1.05x) + raw tiebreak so exact ID/title matches lead.
                    score += 1.05 / (k + lex_rank[sid])
                if sid in sem_rank:
                    score += 1.00 / (k + sem_rank[sid])
                if sid in lex_rank and sid in sem_rank:
                    # Agreement bonus when both lexical and dense semantic channels retrieve the skill.
                    score += 0.35 / k
                fused.append((score, sid, by_id[sid]))

            fused.sort(key=lambda item: (-item[0], item[1]))
            if limit is not None:
                fused = fused[:limit]
            self.last_search_meta = {
                "mode": "hybrid" if self._vectors is not None else "lexical_bm25",
                "lexical_hits": len(lex_scores),
                "semantic_hits": len(sem_scores),
                "returned": len(fused),
            }
            return tuple(item[2] for item in fused)

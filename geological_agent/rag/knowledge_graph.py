"""CPU-only, source-bound literature graph. Mentions are not scientific claims.

Offsets are Unicode code-point offsets in the unmodified indexed document.
The versioned vocabulary is deliberately explicit: no co-occurrence triples,
LLM guessing, title-based document merging, or silent OCR correction.
"""
from __future__ import annotations

import hashlib
import json
import re

TYPES = {
    "deposit": "矿床／矿区", "mineral": "矿物", "rock": "岩石／地层",
    "time": "地质时代", "process": "地质作用", "method": "研究方法", "region": "区域",
}

# Each row defines one concept. Related but distinct deposits stay distinct.
VOCABULARY = {
    "deposit": [
        ["李坝", "李坝金矿", "李坝矿床", "Liba"], ["寨上", "寨上金矿", "Zhaishang"],
        ["马坞", "Mawu"], ["鹿儿坝", "Luerba", "Lu'erba"], ["代家庄", "Daijiazhuang"],
        ["锁龙", "Suolong"], ["雪坪沟", "Xuepinggou"], ["柏家庄", "Baijiazhuang"],
        ["闾井", "Lvjing"], ["南金山", "Nanjinshan"], ["北金山", "Beijinshan"],
        ["夹皮沟", "Jiapigou"], ["阳山", "Yangshan"], ["八卦庙", "Baguamiao"],
        ["双王", "Shuangwang"], ["大水", "大水金矿", "Dashui gold deposit"],
    ],
    "mineral": [
        ["黄铁矿", "pyrite"], ["毒砂", "砷黄铁矿", "arsenopyrite"], ["石英", "quartz"],
        ["黄铜矿", "chalcopyrite"], ["方铅矿", "galena"], ["闪锌矿", "sphalerite"],
        ["方解石", "calcite"], ["白云石", "dolomite"], ["绢云母", "sericite"],
        ["白云母", "muscovite"], ["黑云母", "biotite"], ["绿泥石", "chlorite"],
        ["自然金", "native gold"], ["银金矿", "electrum"], ["磁铁矿", "magnetite"],
        ["赤铁矿", "hematite"], ["金红石", "rutile"], ["锆石", "zircon"],
        ["辉锑矿", "stibnite"], ["磁黄铁矿", "pyrrhotite"], ["碲铋矿", "tetradymite"],
        ["独居石", "monazite"], ["磷灰石", "apatite"],
    ],
    "rock": [
        ["花岗岩", "granite"], ["花岗闪长岩", "granodiorite"], ["闪长岩", "diorite"],
        ["辉长岩", "gabbro"], ["玄武岩", "basalt"], ["流纹岩", "rhyolite"],
        ["砂岩", "sandstone"], ["页岩", "shale"], ["灰岩", "limestone"],
        ["板岩", "slate"], ["千枚岩", "phyllite"], ["片岩", "schist"],
        ["片麻岩", "gneiss"], ["糜棱岩", "mylonite"], ["石英岩", "quartzite"],
        ["西汉水组"], ["大草滩组"], ["舒家坝组"], ["泥盆系"], ["三叠系"],
    ],
    "time": [
        ["太古宙", "Archean"], ["元古宙", "Proterozoic"], ["古生代", "Paleozoic"],
        ["中生代", "Mesozoic"], ["新生代", "Cenozoic"], ["寒武纪", "Cambrian"],
        ["奥陶纪", "Ordovician"], ["志留纪", "Silurian"], ["泥盆纪", "Devonian"],
        ["石炭纪", "Carboniferous"], ["二叠纪", "Permian"], ["三叠纪", "Triassic"],
        ["侏罗纪", "Jurassic"], ["白垩纪", "Cretaceous"], ["第四纪", "Quaternary"],
        ["印支期"], ["燕山期"], ["加里东期"], ["海西期"],
    ],
    "process": [
        ["硅化", "silicification"], ["绢云母化", "sericitization"], ["黄铁矿化", "pyritization"],
        ["碳酸盐化", "carbonatization"], ["绿泥石化", "chloritization"],
        ["热液蚀变", "hydrothermal alteration"], ["流体混合", "fluid mixing"],
        ["流体沸腾", "fluid boiling"], ["韧性剪切", "ductile shear"],
        ["造山型金矿", "orogenic gold"], ["卡林型金矿", "Carlin-type"],
    ],
    "method": [
        ["流体包裹体", "fluid inclusion", "fluid inclusions"], ["硫同位素", "sulfur isotope", "sulphur isotope"],
        ["氢氧同位素"], ["铅同位素", "lead isotope"], ["碳氧同位素"],
        ["锆石 U-Pb 定年", "zircon U-Pb", "锆石U-Pb"], ["LA-ICP-MS", "LA–ICP–MS"],
        ["电子探针", "electron microprobe", "EPMA"], ["扫描电镜", "scanning electron microscope"],
        ["反射光谱", "reflectance spectroscopy"], ["地球化学", "geochemistry"],
    ],
    "region": [["西秦岭", "West Qinling", "Western Qinling"], ["东秦岭", "East Qinling"],
               ["秦岭", "Qinling"], ["吉林省", "Jilin Province"], ["甘肃省", "Gansu Province"],
               ["陕西省", "Shaanxi Province"]],
}


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


VERSION = "literature-mentions-v1-" + digest(json.dumps(VOCABULARY, ensure_ascii=False, sort_keys=True))[:16]


def _lexicon():
    aliases, entities = {}, {}
    for kind, entries in VOCABULARY.items():
        for entry in entries:
            label = entry[0]
            key = digest(kind + "\0" + label)[:24]
            entities[key] = {"id": key, "label": label, "kind": kind, "aliases": entry}
            for alias in entry:
                folded = alias.casefold()
                if folded in aliases and aliases[folded] != key:
                    raise ValueError("Ambiguous graph vocabulary alias")
                aliases[folded] = key
    # Longest first prevents 黄铁矿化 -> 黄铁矿 and 花岗闪长岩 -> 闪长岩.
    alternatives = []
    for alias in sorted(aliases, key=lambda s: (-len(s), s)):
        value = re.escape(alias)
        if alias[0].isascii() and alias[0].isalnum():
            value = r"(?<![a-zA-Z0-9_])" + value
        if alias[-1].isascii() and alias[-1].isalnum():
            value += r"(?![a-zA-Z0-9_])"
        alternatives.append(value)
    return re.compile("|".join(alternatives), re.IGNORECASE), aliases, entities


PATTERN, ALIASES, ENTITIES = _lexicon()


def extract_document(document, chunks):
    """Return exact bounded evidence, including unsupported-source diagnostics.

    Reference sections are excluded from entity mentions, not from source data.
    Invalid chunks are counted and never repaired by approximate matching.
    """
    body = document["body"]
    if not isinstance(body, str) or digest(body) != document["sha256"]:
        raise ValueError("Document body does not match its recorded SHA-256")
    mentions, seen = [], set()
    diagnostics = {"chunks": len(chunks), "invalid_chunks": 0, "reference_chunks": 0,
                   "unlocated_pages": 0, "chunks_without_terms": 0}
    for chunk in chunks:
        start, end = chunk.get("start_char"), chunk.get("end_char")
        text = chunk.get("text", chunk.get("body", ""))
        meta = chunk.get("metadata") or {}
        if (not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int)
                or not isinstance(text, str) or start < 0 or end <= start or end > len(body)
                or body[start:end] != text):
            diagnostics["invalid_chunks"] += 1
            continue
        sections = meta.get("physical_section_path", meta.get("section_path", []))
        if isinstance(sections, str):
            sections = [sections]
        if meta.get("kind") == "ref_text" or any(re.fullmatch(
                r"\s*(?:\d+[.\s]*)?(?:参考文献|references|bibliography)\s*", str(s), re.I) for s in sections):
            diagnostics["reference_chunks"] += 1
            continue
        pages = sorted({p["page"] for p in meta.get("sources", []) if isinstance(p, dict)
                        and isinstance(p.get("page"), int) and not isinstance(p["page"], bool) and p["page"] > 0})
        found = False
        for match in PATTERN.finditer(text):
            entity = ENTITIES[ALIASES[match.group().casefold()]]
            absolute = start + match.start()
            key = (entity["id"], absolute, start + match.end())
            if key in seen:
                continue
            seen.add(key)
            # Quotes retain punctuation, whitespace and negations byte-for-byte.
            left, right = max(0, match.start() - 110), min(len(text), match.end() + 160)
            quote = text[left:right]
            mentions.append({
                "id": digest(document["id"] + "\0" + repr(key) + "\0" + document["sha256"]),
                "entity_id": entity["id"], "label": entity["label"], "kind": entity["kind"],
                "relation": "mentions", "document_id": document["id"],
                "start_char": start + left, "end_char": start + right, "text": quote,
                "mention_start": absolute, "mention_end": start + match.end(),
                "sha256": document["sha256"], "quote_sha256": digest(quote),
                "citation_id": chunk.get("citation_id", chunk.get("id")),
                "pages": pages, "page_scope": "source_chunk" if pages else "unavailable",
                "quality_status": meta.get("quality_status", "not_recorded"),
                "original_sha256": meta.get("original_sha256"),
                "structure_sha256": meta.get("structure_sha256"),
                "block_ids": meta.get("block_ids", []),
            })
            if not pages:
                diagnostics["unlocated_pages"] += 1
            found = True
        if not found:
            diagnostics["chunks_without_terms"] += 1
    return {"id": document["id"], "sha256": document["sha256"], "version": VERSION,
            "mentions": mentions, "diagnostics": diagnostics}

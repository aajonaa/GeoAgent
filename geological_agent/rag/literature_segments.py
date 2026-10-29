"""Bounded page segments, not separate documents or rewritten source text."""

POLICY = "source-bound-page-segments-v1"
MAX_CHARACTERS = 120000
MAX_CHUNKS = 1000
MAX_SEGMENTS = 64


def fail(message):
    from .literature import LiteratureError
    raise LiteratureError(message + "; original retained")


def plan_segments(doc):
    from .literature import digest
    text, entries, covered = doc["body"], [], 0
    for ordinal, block in enumerate(doc["blocks"]):
        if not block["indexable"]:
            continue
        a, b = block["start_char"], block["end_char"]
        if (type(a) is not int or type(b) is not int or a != covered or not a < b <= len(text)
                or text[a:b] != block["text"] + "\n\n"):
            fail("Segment source block coverage mismatch")
        if b - a > MAX_CHARACTERS:
            fail("A source block exceeds the 120000-character segment budget and requires review")
        entries.append((ordinal, block))
        covered = b
    if not entries or covered != len(text):
        fail("Segment source coverage is incomplete")
    pages = []
    for entry in entries:
        if not pages or pages[-1][-1][1]["source"]["page"] != entry[1]["source"]["page"]:
            pages.append([])
        pages[-1].append(entry)
    units = []
    for page in pages:
        if page[-1][1]["end_char"] - page[0][1]["start_char"] > MAX_CHARACTERS:
            units.extend([[entry] for entry in page])
        else:
            units.append(page)
    groups, pending = [], []
    for unit in units:
        if pending and unit[-1][1]["end_char"] - pending[0][1]["start_char"] > MAX_CHARACTERS:
            groups.append(pending)
            pending = []
        pending.extend(unit)
    if pending:
        groups.append(pending)
    if len(groups) > MAX_SEGMENTS:
        fail("Document exceeds the bounded segment count and requires review")
    result = []
    for ordinal, group in enumerate(groups, 1):
        a, b = group[0][1]["start_char"], group[-1][1]["end_char"]
        result.append({"id": "S" + str(ordinal), "start_char": a, "end_char": b,
                       "sha256": digest(text[a:b]), "first_block": group[0][0],
                       "last_block": group[-1][0], "block_ids": [v[1]["id"] for v in group],
                       "pages": list(dict.fromkeys(v[1]["source"]["page"] for v in group))})
    return result


def attach_segments(doc):
    if len(doc["body"]) > MAX_CHARACTERS:
        doc["segmentation"] = {"policy": POLICY, "max_characters": MAX_CHARACTERS,
                               "max_chunks": MAX_CHUNKS, "segments": plan_segments(doc)}
    return doc


def validate_manifest(doc):
    manifest = doc.get("segmentation")
    if len(doc["body"]) <= MAX_CHARACTERS:
        if manifest:
            fail("Unexpected short-document segment manifest")
        return None
    expected = {"policy": POLICY, "max_characters": MAX_CHARACTERS,
                "max_chunks": MAX_CHUNKS, "segments": plan_segments(doc)}
    if manifest != expected:
        fail("Segment manifest does not match the complete canonical source")
    return manifest


def marker(segment):
    return {"policy": POLICY, **{key: segment[key] for key in ("id", "start_char", "end_char", "sha256")}}


def validate_chunk_segments(doc, parts):
    from .literature import digest
    manifest = validate_manifest(doc)
    if manifest is None:
        return None
    segments, blocks = manifest["segments"], {b["id"]: b for b in doc["blocks"]}
    position, covered, count = 0, 0, 0
    for part in parts:
        if position >= len(segments):
            fail("Unexpected chunks after segment coverage completed")
        segment = segments[position]
        a, b = part["start_char"], part["end_char"]
        meta = part["metadata"]
        if (type(a) is not int or type(b) is not int or not segment["start_char"] <= a < b <= segment["end_char"]
                or a > covered or b <= covered or meta.get("segment") != marker(segment)
                or part["text"] != doc["body"][a:b] or meta.get("source_text_sha256") != digest(part["text"])
                or meta.get("original_sha256") != doc["original_sha256"]
                or meta.get("structure_sha256") != doc["structure_sha256"]):
            fail("Segment chunk source or coverage mismatch")
        ids = meta.get("block_ids")
        if (not isinstance(ids, list) or not ids or len(set(ids)) != len(ids)
                or any(bid not in segment["block_ids"] for bid in ids)
                or meta.get("sources") != [blocks[bid]["source"] for bid in ids]
                or any(not blocks[bid]["start_char"] < b or not blocks[bid]["end_char"] > a for bid in ids)):
            fail("Segment chunk page/block binding mismatch")
        covered, count = b, count + 1
        if count > MAX_CHUNKS:
            fail("A segment exceeds the unchanged 1000-chunk budget")
        if covered == segment["end_char"]:
            position += 1
            count = 0
    if position != len(segments) or covered != len(doc["body"]):
        fail("Segment chunk coverage is incomplete")
    return manifest


def split_segmented(doc, splitter, tok, tokenizer_sha):
    manifest = validate_manifest(doc)
    parts = []
    for segment in manifest["segments"]:
        scoped = {**doc, "blocks": doc["blocks"][segment["first_block"]:segment["last_block"] + 1]}
        local = splitter(scoped, tok, tokenizer_sha)
        for part in local:
            part["metadata"]["segment"] = marker(segment)
        parts.extend(local)
    validate_chunk_segments(doc, parts)
    return parts


def segment_summary(manifest, characters):
    return {"policy": POLICY, "segments": len(manifest["segments"]), "characters": characters,
            "max_segment_characters": MAX_CHARACTERS, "max_segment_chunks": MAX_CHUNKS}

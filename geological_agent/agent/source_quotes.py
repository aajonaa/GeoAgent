"""Conservative presentation matching with offsets into untouched source text.

Only whitespace and whole-paragraph Markdown strong wrappers are presentation.
Inline operators, code, headings, links, punctuation and all words stay literal.
There is no fuzzy matching, case folding, dehyphenation or Unicode substitution.
"""
import hashlib
import re


def _view(original):
    removed = set()
    start = 0
    paragraphs = []
    for separator in re.finditer(r"\r?\n[ \t]*\r?\n", original):
        paragraphs.append((start, separator.start()))
        start = separator.end()
    paragraphs.append((start, len(original)))
    for start, end in paragraphs:
        value = original[start:end]
        left = start + len(value) - len(value.lstrip())
        right = end - (len(value) - len(value.rstrip()))
        paragraph = original[left:right]
        for marker in ("**", "__"):
            if not (len(paragraph) > 4 and paragraph.startswith(marker) and paragraph.endswith(marker)):
                continue
            body = paragraph[2:-2]
            if body[0].isspace() or body[-1].isspace() or marker in body or "\\" in body:
                continue
            removed.update((left, left + 1, right - 2, right - 1))
            break
    chars, spans = [], []
    for offset, char in enumerate(original):
        if offset in removed:
            continue
        if char.isspace():
            if chars and chars[-1] == " ":
                spans[-1] = (spans[-1][0], offset + 1)
            elif chars:
                chars.append(" ")
                spans.append((offset, offset + 1))
        else:
            chars.append(char)
            spans.append((offset, offset + 1))
    if chars and chars[-1] == " ":
        chars.pop()
        spans.pop()
    return "".join(chars), spans


def bind_source_quote(original, quote, *, within=None, allow_formatting=True):
    """Return a source-derived binding, or None; bounds use Python code points."""
    if not isinstance(original, str) or not isinstance(quote, str) or not quote.strip():
        return None
    low, high = (0, len(original)) if within is None else within
    if not 0 <= low <= high <= len(original):
        raise ValueError("Invalid original source bounds")
    start = original.find(quote, low, high)
    mode = "exact"
    end = start + len(quote)
    if start < 0:
        # Code and escaped syntax require literal matching. This deliberately
        # rejects unsupported formatting rather than guessing its meaning.
        if (not allow_formatting or any(char in original or char in quote for char in ("`", "\\"))
                or re.search(r"(?m)^[ \t]*~{3,}", original + "\n" + quote)):
            return None
        visible, offsets = _view(original)
        requested, _ = _view(quote)
        if not requested:
            return None
        position = visible.find(requested)
        while position >= 0:
            start, end = offsets[position][0], offsets[position + len(requested) - 1][1]
            if start >= low and end <= high:
                break
            position = visible.find(requested, position + 1)
        if position < 0:
            return None
        mode = "format_normalized"
    return {"start": start, "end": end, "offset_unit": "unicode_codepoints",
            "raw_quote": original[start:end], "match_mode": mode,
            "source_field_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest()}

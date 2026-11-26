"""Create native, editable PowerPoint research slides with PPT Master."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from .research_literature import WORK_ID
from .tools import ToolFailure, ToolOutput, artifact


PPT_MASTER_REVISION = "63a03673d5c3c928e7f52983a2c8ec65bac30002"
DEFAULT_VENDOR = Path(__file__).resolve().parents[2] / "vendor" / ("ppt-master-" + PPT_MASTER_REVISION)
PPT_NS = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
          "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
SVG = "http://www.w3.org/2000/svg"
EXPORT = """
from pathlib import Path
import sys
sys.path[:0] = [sys.argv[1], sys.argv[3]]
from attribution_guard import require_skill_integrity
from svg_to_pptx.pptx_package.builder import create_pptx_with_native_svg

require_skill_integrity()
root = Path(sys.argv[2])
if not create_pptx_with_native_svg(sorted(root.glob('slide-*.svg')), root / 'deck.pptx',
                                  resource_root=root, verbose=False, transition=None,
                                  pptx_structure='flat', workers=1):
    raise SystemExit(1)
"""


def _reference_lines(args, ctx):
    audit_file = ctx.path(args["audit_path"])
    if not audit_file.is_file() or audit_file.stat().st_size > 64000:
        raise ToolFailure("invalid_audit", "Provide the citation audit JSON produced by scientific writing.")
    raw = audit_file.read_bytes()
    recorded = ctx.evidence_state.get("research_citation_audits", {}).get(args["audit_path"])
    if hashlib.sha256(raw).hexdigest() != args["audit_sha256"] or recorded != args["audit_sha256"]:
        raise ToolFailure("invalid_audit", "Re-run the citation audit in this task to verify the current file.", retryable=True)
    try:
        audit = json.loads(raw)
        rows = audit["references"]
        used = list(dict.fromkeys(work_id for slide in args["slides"] for work_id in slide["work_ids"]))
        for work_id in used:
            row = rows[work_id]
            if (audit["schema"] != 1 or audit["source"] != "OpenAlex" or row["id"] != work_id
                    or not re.fullmatch(WORK_ID, work_id) or row["retracted"]):
                raise ValueError("Invalid or retracted reference")
        if not used:
            raise ValueError("A cited slide is required")
        return {
            work_id: f"[{index}] {rows[work_id]['title']} ({rows[work_id]['year'] or 'n.d.'})"
                     f" · {rows[work_id]['doi'] or rows[work_id]['url']}"
            for index, work_id in enumerate(used, 1)
        }
    except (KeyError, ValueError, TypeError, UnicodeError):
        raise ToolFailure("unverified_reference", "Use valid, audited OpenAlex work IDs. Missing and retracted works cannot be cited.", retryable=True) from None


def _wrapped(text, maximum):
    line, units = "", 0
    for char in " ".join(text.split()):
        if unicodedata.category(char) in ("Cc", "Cs") or char in "\ufffe\uffff":
            continue
        width = 2 if unicodedata.east_asian_width(char) in ("F", "W") else 1
        if units + width > maximum:
            split = line.rfind(" ")
            if split > len(line) // 2:
                yield line[:split]
                line = line[split + 1:]
                units = sum(2 if unicodedata.east_asian_width(c) in ("F", "W") else 1 for c in line)
            else:
                yield line
                line, units = "", 0
        line += char
        units += width
    if line:
        yield line.strip()


def _slide(path, title, bullets, footer, *, references=False):
    svg = ET.Element("svg", {"xmlns": SVG, "width": "1280", "height": "720", "viewBox": "0 0 1280 720"})

    def rect(x, y, width, height, fill):
        ET.SubElement(svg, "rect", {"x": str(x), "y": str(y), "width": str(width),
                                    "height": str(height), "fill": fill})

    def line(content, x, y, size, color, *, bold=False):
        shape = ET.SubElement(svg, "text", {"x": str(x), "y": str(y), "fill": color,
                                          "font-family": "Arial, Microsoft YaHei, sans-serif",
                                          "font-size": str(size)})
        if bold:
            shape.set("font-weight", "700")
        shape.text = content

    rect(0, 0, 1280, 720, "#F4F7F6")
    rect(74, 63, 62, 6, "#137B71")
    y = 121
    for piece in _wrapped(title, 43):
        line(piece, 74, y, 43, "#112F3A", bold=True)
        y += 51
    y += 32
    for bullet in bullets:
        for index, piece in enumerate(_wrapped(bullet, 91 if references else 72)):
            if y > 604:
                raise ToolFailure("slide_too_dense", "Shorten the slide title or body, or split it across slides.", retryable=True)
            if index == 0 and not references:
                rect(78, y - 13, 8, 8, "#137B71")
            line(piece, 103, y, 23 if references else 28, "#163C46")
            y += 30 if references else 35
        y += 23
    rect(74, 638, 1132, 1, "#92AEAA")
    line(footer, 74, 673, 17, "#27565C")
    ET.ElementTree(svg).write(path, encoding="utf-8", xml_declaration=True)


def _convert(root, ctx):
    vendor = Path(os.environ.get("ORESAGE_PPT_MASTER_ROOT", str(DEFAULT_VENDOR))).resolve()
    scripts = vendor / "skills/ppt-master/scripts"
    if not (scripts / "svg_to_pptx/pptx_package/builder.py").is_file():
        raise ToolFailure("ppt_master_unavailable", "The pinned PPT Master converter is unavailable.")
    environment = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "LANG") if key in os.environ}
    limit = min(ctx.deadline, time.monotonic() + 25)
    log = root / "converter.log"
    with log.open("wb") as output, subprocess.Popen(
        [sys.executable, "-I", "-B", "-c", EXPORT, str(scripts), str(root), str(vendor / ".deps")],
        cwd=root, env=environment, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
    ) as process:
        try:
            while process.poll() is None:
                ctx.check()
                if time.monotonic() >= limit:
                    raise ToolFailure("ppt_master_timeout", "PPT Master timed out.", retryable=True)
                time.sleep(0.1)
        finally:
            if process.poll() is None:
                process.kill()
        if process.returncode:
            raise ToolFailure("ppt_master_failed", "PPT Master could not export the slides.", retryable=True)


def editable_slide_count(path):
    with ZipFile(path) as deck:
        if deck.testzip() is not None or "ppt/presentation.xml" not in deck.namelist():
            raise ValueError("Invalid PowerPoint package")
        slides = [name for name in deck.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)]
        for name in slides:
            slide = ET.fromstring(deck.read(name))
            if not slide.findall(".//p:sp/p:txBody//a:t", PPT_NS) or slide.findall(".//p:pic", PPT_NS):
                raise ValueError("Expected native PowerPoint text with no flattened slide image")
        return len(slides)


def ppt_master(args, ctx):
    references = _reference_lines(args, ctx)
    numbers = {key: value.split(" ", 1)[0] for key, value in references.items()}
    content = json.dumps(args, ensure_ascii=False, sort_keys=True)
    destination = ctx.path("research-slides-" + hashlib.sha256(content.encode()).hexdigest()[:20] + ".pptx")
    slides = args["slides"]
    reference_groups = [list(references.values())[i:i + 2] for i in range(0, len(references), 2)]
    with tempfile.TemporaryDirectory(prefix=".research-deck-", dir=destination.parent) as temp:
        root = Path(temp)
        for index, slide in enumerate(slides, 1):
            attribution = " ".join(numbers[key] for key in slide["work_ids"])
            footer = f"{index:02d}" + (f"  ·  OpenAlex {attribution}" if attribution else "")
            _slide(root / f"slide-{index:02d}.svg", slide["title"], slide["bullets"], footer)
        for index, group in enumerate(reference_groups, len(slides) + 1):
            _slide(root / f"slide-{index:02d}.svg", "References", group, f"{index:02d}  ·  OpenAlex metadata",
                   references=True)
        _convert(root, ctx)
        deck = root / "deck.pptx"
        count = editable_slide_count(deck)
        if count != len(slides) + len(reference_groups) or deck.stat().st_size > ctx.settings.max_file_bytes:
            raise ToolFailure("invalid_presentation", "Generated deck did not pass structural or size checks.")
        ctx.check()
        os.replace(deck, destination)
    return ToolOutput({"path": destination.name, "slides": count, "editable": True, "engine": "PPT Master"},
                      (artifact(destination, ctx),))

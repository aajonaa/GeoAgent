"""Static SVG image previews. Originals remain separate, immutable downloads."""
import base64
from io import BytesIO
import math
import re
import xml.etree.ElementTree as ET

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException
import tinycss2

from .tools import ToolFailure

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
XML_NS = "http://www.w3.org/XML/1998/namespace"
SVG_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)
TAGS = set("svg g defs title desc style rect circle ellipse line polyline polygon path text tspan textPath linearGradient radialGradient stop clipPath mask marker pattern symbol use image".split())
PROPERTIES = set("fill fill-opacity fill-rule stroke stroke-width stroke-opacity stroke-linecap stroke-linejoin stroke-miterlimit stroke-dasharray stroke-dashoffset opacity color font-family font-size font-style font-weight font-variant font-stretch text-anchor dominant-baseline alignment-baseline baseline-shift letter-spacing word-spacing paint-order vector-effect display visibility clip-path clip-rule mask marker marker-start marker-mid marker-end stop-color stop-opacity transform transform-origin white-space shape-rendering text-rendering image-rendering direction unicode-bidi".split())
ATTRIBUTES = PROPERTIES | set("id class x y x1 y1 x2 y2 cx cy r rx ry dx dy d points width height viewBox preserveAspectRatio version href style type offset gradientUnits gradientTransform spreadMethod fx fy fr clipPathUnits maskUnits maskContentUnits markerUnits markerWidth markerHeight refX refY orient patternUnits patternContentUnits patternTransform textLength lengthAdjust startOffset method spacing role aria-label aria-labelledby aria-describedby focusable".split())
FUNCTIONS = set("rgb rgba hsl hsla hwb color lab lch oklab oklch var calc min max clamp translate translateX translateY scale scaleX scaleY rotate matrix skewX skewY".lower().split())
# Matplotlib emits this inert public declaration. Remove it without resolving it.
PUBLIC_DTD = re.compile(br'<!DOCTYPE\s+svg\s+PUBLIC\s+"-//W3C//DTD SVG 1\.1//EN"\s+"https?://www\.w3\.org/Graphics/SVG/1\.1/DTD/svg11\.dtd"\s*>')
REFERENCE = re.compile(r"#[A-Za-z0-9_.:-]+\Z")

def fail(message):
    raise ToolFailure("svg_preview_blocked", "SVG preview blocked: " + message + ". The original file is still available for download.")

def local_reference(value, references):
    if not REFERENCE.fullmatch(value):
        fail("only document-local fragment references are allowed")
    references.append(value[1:])

def tokens_safe(tokens, references):
    for token in tokens:
        kind = token.type
        if kind in ("error", "at-keyword", "() block", "[] block", "{} block"):
            fail("unsupported CSS syntax")
        if kind == "url":
            local_reference(token.value, references)
        elif kind == "function":
            name = token.lower_name
            if name == "url":
                args = [arg for arg in token.arguments if arg.type not in ("whitespace", "comment")]
                if len(args) != 1 or args[0].type != "string":
                    fail("invalid CSS reference")
                local_reference(args[0].value, references)
            elif name in FUNCTIONS:
                tokens_safe(token.arguments, references)
            else:
                fail("unsupported CSS function")
        elif kind in ("number", "dimension", "percentage") and not math.isfinite(token.value):
            fail("non-finite CSS value")

def declarations(value, references):
    parts = tinycss2.parse_blocks_contents(value, skip_comments=True, skip_whitespace=True)
    for part in parts:
        if part.type != "declaration" or not (part.lower_name in PROPERTIES or re.fullmatch(r"--[A-Za-z0-9_-]+", part.name)):
            fail("unsupported CSS property or rule")
        tokens_safe(part.value, references)
    return tinycss2.serialize(parts)

def stylesheet(value, references):
    rules = tinycss2.parse_stylesheet(value, skip_comments=True, skip_whitespace=True)
    result = []
    for rule in rules:
        if rule.type != "qualified-rule":
            fail("stylesheet imports and at-rules are not allowed")
        tokens_safe(rule.prelude, references)
        result.append(tinycss2.serialize(rule.prelude) + "{" + declarations(rule.content, references) + "}")
    return "".join(result)

def embedded_image(value):
    match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=\s]+)", value)
    if not match:
        fail("embedded images must be PNG, JPEG or WebP data, not external files or SVG")
    try:
        raw = base64.b64decode(re.sub(r"\s", "", match[2]), validate=True)
        from PIL import Image
        with Image.open(BytesIO(raw)) as image:
            if image.format != {"png": "PNG", "jpeg": "JPEG", "webp": "WEBP"}[match[1]] or image.width * image.height > 16000000:
                fail("embedded image exceeds safe image bounds or has the wrong format")
            image.verify()
    except ToolFailure:
        raise
    except (ValueError, OSError) as exc:
        fail("invalid embedded image")
    return "data:image/" + match[1] + ";base64," + base64.b64encode(raw).decode("ascii")

def svg_preview(raw):
    if not raw or len(raw) > 8 * 1024 * 1024:
        fail("SVG must fit the existing 8 MiB upload allowance")
    try:
        root = SafeET.fromstring(PUBLIC_DTD.sub(b"", raw, count=1), forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (ET.ParseError, DefusedXmlException, ValueError):
        fail("invalid XML or a forbidden document/entity declaration")
    ids, edges, count = set(), {}, 0

    def clean(node, depth=0, owner=""):
        nonlocal count
        count += 1
        if count > 50000 or depth > 128:
            fail("SVG structure is too complex for an interactive preview")
        tag = node.tag
        if tag.startswith("{"):
            namespace, tag = tag[1:].split("}", 1)
            if namespace != SVG_NS:
                fail("non-SVG elements are not allowed")
        if tag not in TAGS:
            fail("active or unsupported element " + tag)
        if depth == 0 and tag != "svg":
            fail("the root element must be svg")
        node.tag = "{" + SVG_NS + "}" + tag
        if node.get("id"):
            identifier = node.get("id")
            if not REFERENCE.fullmatch("#" + identifier) or identifier in ids:
                fail("invalid or duplicate element ID")
            ids.add(identifier)
            owner = identifier
        references = []
        for key, value in list(node.attrib.items()):
            local = key
            if key.startswith("{"):
                namespace, local = key[1:].split("}", 1)
                if namespace == XML_NS and local in ("space", "lang"):
                    continue
                if namespace != XLINK_NS or local != "href":
                    fail("unsupported attribute namespace")
            if local.lower().startswith("on") or local not in ATTRIBUTES:
                fail("active or unsupported attribute " + local)
            if local == "href":
                if tag == "image":
                    node.set(key, embedded_image(value))
                elif tag in ("use", "textPath"):
                    local_reference(value, references)
                else:
                    fail("unexpected link attribute")
            elif local == "style":
                node.set(key, declarations(value, references))
            elif local in PROPERTIES:
                tokens_safe(tinycss2.parse_component_value_list(value, skip_comments=True), references)
        if tag == "style":
            if len(node):
                fail("stylesheet must contain only text")
            node.text = stylesheet(node.text or "", references)
        edges.setdefault(owner, []).extend(references)
        for child in list(node):
            # Authoring metadata is not rendered; remove RDF and editor records.
            if child.tag in ("metadata", "{" + SVG_NS + "}metadata"):
                node.remove(child)
            else:
                clean(child, depth + 1, owner)
    clean(root)
    if root.get("viewBox"):
        try:
            box = [float(value) for value in re.split(r"[\s,]+", root.get("viewBox").strip())]
            if len(box) != 4 or not all(math.isfinite(v) for v in box) or box[2] <= 0 or box[3] <= 0:
                fail("invalid viewBox")
        except ValueError:
            fail("invalid viewBox")
        if not root.get("width"):
            root.set("width", str(box[2]))
        if not root.get("height"):
            root.set("height", str(box[3]))
    visiting, done = set(), set()
    def visit(identifier):
        if identifier in visiting:
            fail("cyclic SVG references")
        if identifier in done:
            return
        visiting.add(identifier)
        for reference in edges.get(identifier, []):
            if reference not in ids:
                fail("reference points to a missing element")
            visit(reference)
        visiting.remove(identifier)
        done.add(identifier)
    for identifier in edges:
        visit(identifier)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)

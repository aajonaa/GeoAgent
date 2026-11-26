"""Separate immutable parser output, image assets and retrieval-ready content."""
import base64
import binascii
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import tempfile
import warnings

from PIL import Image
from markdown_it import MarkdownIt

VERSION = "pdf-content-v2-chart-separation"
MAX_RAW = 100 * 1024 * 1024
MAX_IMAGE = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000
DATA_IMAGE = re.compile(r"data:image/(?P<mime>[A-Za-z0-9.+-]+);base64,(?P<data>[A-Za-z0-9+/=\r\n]+)", re.I)
ASSET_NAME = re.compile(r"[a-f0-9]{64}\.(png|jpg|webp|gif)")
FORMATS = {"PNG": ("png","image/png"), "JPEG": ("jpg","image/jpeg"),
           "WEBP": ("webp","image/webp"), "GIF": ("gif","image/gif")}

class ContentError(ValueError):
    pass

def sha(data):
    return hashlib.sha256(data).hexdigest()

def decode_image(match):
    encoded = re.sub(r"\s", "", match.group("data"))
    if len(encoded) > (MAX_IMAGE * 4 // 3 + 8):
        raise ContentError("Embedded image is too large; original parser output retained")
    try:
        data = base64.b64decode(encoded, validate=True)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in FORMATS or image.width * image.height > MAX_PIXELS:
                    raise ContentError("Unsupported or oversized embedded image")
                ext, media = FORMATS[image.format]
                width,height = image.size
                if match.group("mime").lower() not in {media.split("/")[1], "jpg" if ext == "jpg" else ext}:
                    raise ContentError("Embedded image media type does not match its bytes")
                image.verify()
        if not data or len(data) > MAX_IMAGE:
            raise ContentError("Invalid embedded image size")
        digest = sha(data)
        return {"name":digest+"."+ext,"sha256":digest,"media_type":media,
                "bytes":len(data),"width":width,"height":height,"pages":[],"captions":[]}, data
    except (ValueError, OSError, binascii.Error, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ContentError("Embedded image failed validation; original retained") from None

def make_content(raw, structured):
    assets, payloads, changes, derived = {}, {}, [], []
    removed = 0
    def replace(match):
        nonlocal removed
        asset,data = decode_image(match)
        assets.setdefault(asset["name"],asset)
        payloads[asset["name"]] = data
        removed += len(match.group())
        changes.append({"type":"embedded_image","raw_start":match.start(),"raw_end":match.end(),
                        "asset":asset["name"]})
        return "pdf-asset:" + asset["name"]
    text = DATA_IMAGE.sub(replace, raw)
    if re.search(r"data:image/[^ \t\n\"')>]*",text,re.I):
        raise ContentError("Unrecognized embedded image encoding; do not index raw binary payloads")
    pages = structured.get("pages",[]) if isinstance(structured,dict) else []
    for page in pages:
        if not isinstance(page,dict) or type(page.get("page_idx")) is not int:
            continue
        number = page["page_idx"] + 1
        for block in page.get("blocks",[]):
            if not isinstance(block,dict) or block.get("type") not in {"image", "figure", "chart"}:
                continue
            source = block.get("image_source")
            match = DATA_IMAGE.fullmatch(source) if isinstance(source,str) else None
            name = None
            if match:
                info,data = decode_image(match)
                name = info["name"]
                # Also retain a parser crop when Markdown omitted its original image.
                assets.setdefault(name,info)
                payloads[name] = data
                if number not in assets[name]["pages"]:
                    assets[name]["pages"].append(number)
                for caption in block.get("captions",[]):
                    value = caption.get("content") if isinstance(caption,dict) else None
                    if isinstance(value,str) and value not in assets[name]["captions"]:
                        assets[name]["captions"].append(value)
            content = block.get("content")
            if isinstance(content,str) and content.strip():
                entry = {"kind":"parser_visual_transcription","source_type":block.get("type"),"page":number,"asset":name,"text":content,
                         "in_retrieval_text":False}
                if text.count(content) == 1:
                    text = text.replace(content,"",1)
                    derived.append(entry)
                    changes.append({"type":"visual_transcription_separated","page":number,"asset":name})
                elif content not in text:
                    derived.append(entry)
                else:
                    raise ContentError("Ambiguous diagram transcription; manual review required before indexing")
    if len(assets)>500 or sum(len(value) for value in payloads.values())>MAX_RAW:
        raise ContentError("Extracted image assets exceeded the import budget")
    return text, list(assets.values()), payloads, {
        "version":VERSION,"inline_image_characters":removed,"raw_characters":len(raw),
        "characters":len(text),"transformations":changes,"derived":derived,
        "page_count":len(pages),"quality_status":"manual_review_required"}

def load_content(folder, job):
    """Build a content-addressed derivative; never rewrite parser output or vectors."""
    folder = Path(folder)
    raw_bytes = (folder/"parsed.md").read_bytes()
    if len(raw_bytes)>MAX_RAW or sha(raw_bytes)!=job.get("text_sha256"):
        raise ContentError("Parsed source hash or size changed; content preparation refused")
    raw = raw_bytes.decode("utf-8")
    structure_path = folder/"structure.json"
    structure_bytes = structure_path.read_bytes() if structure_path.is_file() else b"{}"
    if len(structure_bytes)>MAX_RAW:
        raise ContentError("Structure output exceeds the supported size")
    structure_sha = sha(structure_bytes)
    key = VERSION+"-"+sha(raw_bytes)[:16]+"-"+structure_sha[:16]
    target = folder/key
    if target.is_dir():
        record = json.loads((target/"manifest.json").read_text(encoding="utf-8"))
        text_bytes = (target/"content.md").read_bytes()
        if (record.get("raw_sha256")!=sha(raw_bytes) or record.get("structure_sha256")!=structure_sha
                or record.get("sha256")!=sha(text_bytes) or record.get("version")!=VERSION):
            raise ContentError("Prepared content failed its provenance check")
        return text_bytes.decode("utf-8"),record,target
    structured = json.loads(structure_bytes)
    text,assets,payloads,record = make_content(raw,structured)
    encoded = text.encode("utf-8")
    record.update(raw_sha256=sha(raw_bytes),structure_sha256=structure_sha,sha256=sha(encoded),
                  assets=assets,key=key)
    temporary = Path(tempfile.mkdtemp(prefix=".pdf-content-",dir=folder))
    try:
        (temporary/"content.md").write_bytes(encoded)
        for name,data in payloads.items():
            (temporary/name).write_bytes(data)
        (temporary/"manifest.json").write_text(json.dumps(record,ensure_ascii=False),encoding="utf-8")
        try:
            temporary.rename(target)
        except OSError:
            if not target.is_dir():
                raise
            # A concurrent request produced the same immutable derivative.
            other = json.loads((target/"manifest.json").read_text(encoding="utf-8"))
            if other.get("sha256")!=record["sha256"]:
                raise ContentError("Concurrent content preparation disagreed")
    finally:
        if temporary.exists():
            for child in temporary.iterdir():
                child.unlink()
            temporary.rmdir()
    return text,record,target

class TableParser(HTMLParser):
    """Read only cell text and merge geometry. Never forward HTML attributes."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows=[];self.row=None;self.cell=None;self.ignore=0;self.caption=[]
    def handle_starttag(self,tag,attrs):
        tag=tag.lower()
        if tag in {"script","style","iframe","object"}:
            self.ignore+=1
        if self.ignore:return
        if tag=="tr":
            self.row=[];self.rows.append(self.row)
        elif tag in {"td","th"}:
            if self.row is None:
                self.row=[];self.rows.append(self.row)
            self.cell={"text":"","header":tag=="th","rowspan":1,"colspan":1}
            for name,value in attrs:
                if name in {"rowspan","colspan"} and value and value.isdigit() and 1<=int(value)<=100:
                    self.cell[name]=int(value)
            self.row.append(self.cell)
        elif tag=="br" and self.cell is not None:
            self.cell["text"]+="\n"
    def handle_endtag(self,tag):
        if tag.lower() in {"script","style","iframe","object"} and self.ignore:
            self.ignore-=1
        if self.ignore:return
        if tag.lower() in {"td","th"}:self.cell=None
        elif tag.lower()=="tr":self.row=None
    def handle_data(self,data):
        if not self.ignore and self.cell is not None:
            self.cell["text"]+=data

def view_tokens(text):
    parser=MarkdownIt("commonmark",{"html":True,"linkify":False,"typographer":False}).enable("table")
    def encode(token):
        result={"type":token.type,"tag":token.tag,"nesting":token.nesting,
                "content":token.content,"attrs":dict(token.attrs or {})}
        if token.children:
            result["children"]=[encode(child) for child in token.children]
        if token.type=="html_block":
            if re.match(r"\s*<table(?:\s|>)",token.content,re.I):
                table=TableParser();table.feed(token.content);table.close()
                result={"type":"safe_table","rows":table.rows}
            else:
                result={"type":"code_block","content":token.content}
        return result
    return [encode(token) for token in parser.parse(text)]

def content_view(folder,job,basis=None):
    text,record,target=load_content(folder,job)
    if basis and basis!=record["sha256"]:
        if basis!=job.get("text_sha256"):
            raise ContentError("The requested content version is not available")
        text=(Path(folder)/"parsed.md").read_text(encoding="utf-8")
        # Never render/index an old payload-contaminated body as if it were normalized.
        if "data:image/" in text:
            raise ContentError("This legacy index contains image payloads; explicit re-indexing is required")
    if len(text)>120000:
        raise ContentError("Prepared body remains above 120,000 characters; split without truncating the original")
    digest=sha(text.encode("utf-8"))
    return {"sha256":digest,"raw_sha256":record["raw_sha256"],"tokens":view_tokens(text),
            "assets":record["assets"],"derived":record["derived"],"quality_status":"manual_review_required",
            "characters":len(text),"raw_characters":record["raw_characters"],
            "inline_image_characters":record["inline_image_characters"]}

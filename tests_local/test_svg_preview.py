"""SVG preview fixtures are synthetic; they are not scientific observations."""
from io import BytesIO
import base64
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from geological_agent.svg_preview import svg_preview, SVG_NS
from geological_agent.tools import ToolFailure
from geological_agent.team.server import create_app

VALID = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 320">
<defs><linearGradient id="rock"><stop offset="0%" stop-color="#cee6dd"/><stop offset="100%" stop-color="#226b58"/></linearGradient>
<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0 L10 5 L0 10Z"/></marker>
<path id="vein" d="M80 250 L300 90"/><clipPath id="frame"><rect width="640" height="320"/></clipPath></defs>
<style>.label { fill: #183e33; font-family: sans-serif; font-size: 20px } rect {stroke-linejoin: round}</style>
<g clip-path="url(#frame)"><rect width="640" height="320" fill="url(#rock)"/>
<use href="#vein" stroke="#cd9945" stroke-width="12" marker-end="url(#arrow)"/>
<text x="25" y="45" class="label">Synthetic vector diagram</text></g></svg>'''

def test_static_svg_remains_vector_with_styles_local_references_and_text():
    original = bytes(VALID)
    result = svg_preview(VALID)
    root = ET.fromstring(result)
    assert root.tag == "{" + SVG_NS + "}svg"
    assert root.get("viewBox") == "0 0 640 320"
    assert root.get("width") == "640.0"
    assert root.find(".//{" + SVG_NS + "}linearGradient") is not None
    assert root.find(".//{" + SVG_NS + "}text").text == "Synthetic vector diagram"
    assert "font-family" in root.find("{" + SVG_NS + "}style").text
    assert VALID == original
    assert b"<svg" in result and b"image/png" not in result

def test_inline_style_variables_quoted_local_urls_and_unicode():
    raw = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><defs><linearGradient id="g"/></defs><style>:root {--ink:#216452} .x {fill:var(--ink)}</style><rect width="20" height="20" style="fill:url(&quot;#g&quot;);stroke:rgb(2,4,6)"/><text>\u77ff\u5316\u793a\u610f</text></svg>'.encode()
    result = svg_preview(raw)
    assert "\u77ff\u5316\u793a\u610f".encode() in result
    assert b"var(--ink)" in result

@pytest.mark.parametrize("body", [
    '<script>alert(1)</script>',
    '<rect onload="alert(1)"/>',
    '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">HTML</div></foreignObject>',
    '<image href="https://evil.example/x.png"/>',
    '<image href="data:image/svg+xml;base64,PHN2Zy8+"/>',
    '<use href="//evil.example/file.svg#x"/>',
    '<use href="javascript:alert(1)"/>',
    '<animate attributeName="href" values="javascript:alert(1)"/>',
    '<style>@import url(https://evil.example/x.css);</style>',
    '<style>.x{fill:url(https://evil.example/x.svg#g)}</style>',
    r'<style>.x{fill:u\72l(https://evil.example/x.svg#g)}</style>',
    '<rect style="fill:expression(alert(1))"/>',
    '<g xml:base="https://evil.example/"><use href="#x"/></g>',
    '<defs><g id="a"><use href="#b"/></g><g id="b"><use href="#a"/></g></defs><use href="#a"/>',
    '<use href="#missing"/>',
    '<rect id="same"/><circle id="same"/>',
])
def test_active_external_and_cyclic_content_is_rejected(body):
    raw = ('<svg xmlns="http://www.w3.org/2000/svg">' + body + '</svg>').encode()
    with pytest.raises(ToolFailure, match="SVG preview blocked"):
        svg_preview(raw)

@pytest.mark.parametrize("raw", [
    b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg>&x;</svg>',
    b'<!DOCTYPE svg SYSTEM "https://evil.example/evil.dtd"><svg/>',
    b'<svg><g></svg>',
    b'<html/>',
    b'<svg viewBox="0 0 -1 50"/>',
])
def test_invalid_xml_entities_and_dimensions_are_rejected(raw):
    with pytest.raises(ToolFailure):
        svg_preview(raw)

def test_inert_matplotlib_header_metadata_and_processing_instructions_are_removed():
    header = b'<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"\n "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n'
    raw = header + b'<?xml-stylesheet href="https://evil.example/a.css"?><svg xmlns="http://www.w3.org/2000/svg" width="72pt" height="72pt" viewBox="0 0 72 72"><metadata><rdf xmlns="urn:ignored">Author data</rdf></metadata><path d="M0 0L72 72" style="fill:none;stroke:#444;stroke-width:1.5"/></svg>'
    result = svg_preview(raw)
    assert b"DOCTYPE" not in result and b"xml-stylesheet" not in result and b"Author data" not in result
    assert ET.fromstring(result).get("width") == "72pt"

def test_embedded_png_and_xlink_references_work_without_network():
    out = BytesIO()
    Image.new("RGB", (2, 2), "#226b58").save(out, format="PNG")
    data = base64.b64encode(out.getvalue()).decode()
    raw = f'<svg xmlns="{SVG_NS}" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 20 20"><image xlink:href="data:image/png;base64,{data}" width="20" height="20"/></svg>'.encode()
    assert data.encode() in svg_preview(raw)

def test_http_svg_is_owner_bound_preserves_original_and_historical_generation(tmp_path):
    class Runner:
        isolated = False
        def stop(self, rid):
            pass
    app = create_app(tmp_path / "accounts", runner=Runner())
    store = app.state.store
    store.create_user("admin", "Synthetic-Admin-Password-2026", role="admin", initial_admin=True)
    store.create_user("alice", "Synthetic-Alice-Password-2026", invite=store.invite())
    store.create_user("bob", "Synthetic-Bob-Password-2026", invite=store.invite())
    with TestClient(app, base_url="http://127.0.0.1") as alice, TestClient(app, base_url="http://127.0.0.1") as bob:
        for client, name in ((alice, "alice"), (bob, "bob")):
            login = client.post("/api/login", json={"username":name, "password":f"Synthetic-{name.title()}-Password-2026"})
            client.headers["X-CSRF-Token"] = login.json()["csrf"]
        cid = alice.post("/api/conversations").json()["id"]
        assert alice.post(f"/api/conversations/{cid}/upload?name=diagram.svg", content=VALID).status_code == 200
        generation = alice.get(f"/api/conversations/{cid}/files").json()["generation"]
        response = alice.get(f"/api/conversations/{cid}/image?name=diagram.svg")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "default-src 'none'" in response.headers["content-security-policy"]
        assert "sandbox" in response.headers["content-security-policy"]
        assert response.headers["x-geoagent-preview"] == "validated-static-svg"
        assert ET.fromstring(response.content).tag == "{" + SVG_NS + "}svg"
        assert alice.get(f"/api/conversations/{cid}/download?name=diagram.svg").content == VALID
        assert bob.get(f"/api/conversations/{cid}/image?name=diagram.svg").status_code == 404
        updated = VALID.replace(b"Synthetic vector diagram", b"New synthetic diagram")
        assert alice.post(f"/api/conversations/{cid}/upload?name=diagram.svg", content=updated).status_code == 200
        old = alice.get(f"/api/conversations/{cid}/image", params={"name":"diagram.svg", "generation":generation})
        assert b"Synthetic vector diagram" in old.content and b"New synthetic diagram" not in old.content
        assert alice.get(f"/api/conversations/{cid}/download", params={"name":"diagram.svg", "generation":generation}).content == VALID
        bad = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>'
        assert alice.post(f"/api/conversations/{cid}/upload?name=bad.svg", content=bad).status_code == 200
        assert alice.get(f"/api/conversations/{cid}/image?name=bad.svg").status_code == 422
        assert alice.get(f"/api/conversations/{cid}/download?name=bad.svg").content == bad
        assert alice.get(f"/api/conversations/{cid}/image?name=../diagram.svg").status_code == 400

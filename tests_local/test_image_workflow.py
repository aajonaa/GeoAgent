"""Synthetic images only; no real scientific observations or third-party data."""
from io import BytesIO
from pathlib import Path
from threading import Event
import base64
import hashlib

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from PIL import Image
from fastapi.testclient import TestClient

from geological_agent.imaging import operate, preview_bytes, OUTPUT_SCHEMA
from geological_agent.bootstrap import build_registry
from geological_agent.contracts import Message, ModelRequest, ModelResponse, ToolCall
from geological_agent.llm import LocalChatClient
from geological_agent.tools import ToolFailure, ToolExecutor, ToolExecutionContext
from geological_agent.settings import Settings
from geological_agent.team.protocol import encode, decode
from geological_agent.team.server import create_app
from jsonschema import validate


@pytest.fixture
def picture(tmp_path):
    pixels = np.zeros((60, 100, 4), dtype="uint8")
    pixels[:, :50] = [220, 20, 20, 255]
    pixels[:, 50:] = [20, 50, 220, 128]
    image = Image.fromarray(pixels)
    image.save(tmp_path / "synthetic.png")
    return tmp_path


def test_transform_real_pixels_original_unchanged_and_manifest(picture):
    original = (picture / "synthetic.png").read_bytes()
    result = operate("GeoImageTransform", {"path": "synthetic.png", "output_path": "out.png",
                     "crop": [0, 0, 50, 60], "rotate": 90, "grayscale": True}, workspace=picture)
    validate(result, OUTPUT_SCHEMA)
    assert (picture / "synthetic.png").read_bytes() == original
    with Image.open(picture / "out.png") as out:
        assert out.size == (60, 50)
        r, g, b, a = out.getpixel((2, 2))
        assert r == g == b and a == 255
    assert result["source"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert (picture / "out.png.image.json").is_file()
    with pytest.raises(ToolFailure):
        operate("GeoImageTransform", {"path": "synthetic.png", "output_path": "out.png"}, workspace=picture)


@pytest.mark.parametrize("extra", [{"crop": [0, 0, 101, 40]}, {"crop": [2, 2, 2, 5]},
                                  {"contrast": float("nan")}, {"rotate": 45}, {"output_path": "../evil.png"}])
def test_bad_arguments_do_not_modify_source(picture, extra):
    before = (picture / "synthetic.png").read_bytes()
    with pytest.raises(ToolFailure):
        operate("GeoImageTransform", {"path": "synthetic.png", "output_path": "bad.png", **extra}, workspace=picture)
    assert (picture / "synthetic.png").read_bytes() == before
    assert not (picture / "bad.png").exists()


def test_alpha_and_resize(picture):
    operate("GeoImageTransform", {"path": "synthetic.png", "output_path": "alpha.png", "grayscale": True, "max_side": 64}, workspace=picture)
    with Image.open(picture / "alpha.png") as image:
        assert image.size == (64, 38)
        assert image.getpixel((60, 20))[3] == 128


def test_broken_and_svg_are_not_images(tmp_path):
    for raw in (b"broken image", b"<svg onload='alert(1)'/>"):
        with pytest.raises(ToolFailure):
            preview_bytes(raw)


def test_raster_preview_nodata_scale_and_original(tmp_path):
    path = tmp_path / "synthetic.tif"
    values = np.array([[1, 2], [3, -9999]], dtype="float32")
    with rasterio.open(path, "w", driver="GTiff", width=2, height=2, count=1, dtype="float32",
                       crs="EPSG:32650", transform=from_origin(0, 2, 1, 1), nodata=-9999) as ds:
        ds.write(values, 1); ds.scales = (2,); ds.offsets = (10,)
    before = path.read_bytes()
    result = operate("GeoRasterPreview", {"path": path.name, "output_path": "raster.png"}, workspace=tmp_path)
    validate(result, OUTPUT_SCHEMA)
    assert result["processing"]["sampled_min"] == 12
    assert result["processing"]["sampled_max"] == 16
    assert result["source"]["crs"] == "EPSG:32650"
    assert path.read_bytes() == before
    with Image.open(tmp_path / "raster.png") as image:
        assert image.getpixel((1, 1))[3] == 0
    with pytest.raises(ToolFailure):
        operate("GeoImageTransform", {"path": path.name, "output_path": "photo.png"}, workspace=tmp_path)


def test_vision_native_wire_has_real_pixels_and_ipc_keeps_them(picture):
    observed = []
    def invoke(request):
        observed.append(request)
        return ModelResponse("Synthetic red and blue regions.", usage={"total_tokens": 42})
    result = operate("GeoImageAnalyze", {"path": "synthetic.png", "question": "Describe the colors."},
                     workspace=picture, vision_invoke=invoke)
    request = decode(encode(observed[0]))
    client = LocalChatClient()
    try:
        body = client._body(request)
    finally:
        client.close()
    content = body["messages"][1]["content"]
    assert content[0]["type"] == "text"
    uri = content[1]["image_url"]["url"]
    assert uri.startswith("data:image/png;base64,")
    with Image.open(BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as image:
        assert image.size == (100, 60)
    assert result["processing"]["usage"]["total_tokens"] == 42
    assert "interpretation" in result


def test_vision_refuses_empty_response(picture):
    with pytest.raises(ToolFailure):
        operate("GeoImageAnalyze", {"path": "synthetic.png", "question": "What is visible?"},
                workspace=picture, vision_invoke=lambda request: ModelResponse(""))


def test_registry_and_executor_return_artifacts(picture):
    registry, skills, _ = build_registry()
    assert "GeoImageTransform" in skills.load("image_workflow").tool_names
    name = "GeoImageTransform"
    ctx = ToolExecutionContext("image-test", picture, (name,), Settings(), Event())
    result = ToolExecutor(registry).execute(ToolCall("image-call", name, {
        "path": "synthetic.png", "output_path": "runtime.png", "rotate": 90}), ctx)
    assert result.status == "ok", result.error
    assert len(result.artifacts) == 2
    assert (picture / result.artifacts[0].path).is_file()


def test_image_http_owner_isolation_and_safe_content(picture, tmp_path):
    class Runner:
        isolated = False
        def stop(self, rid): pass
    app = create_app(tmp_path / "accounts", runner=Runner())
    store = app.state.store
    store.create_user("admin", "Synthetic-Admin-Password-2026", role="admin", initial_admin=True)
    store.create_user("alice", "Synthetic-Alice-Password-2026", invite=store.invite())
    store.create_user("bob", "Synthetic-Bob-Password-2026", invite=store.invite())
    with TestClient(app, base_url="http://127.0.0.1") as alice, TestClient(app, base_url="http://127.0.0.1") as bob:
        for client, name in ((alice, "alice"), (bob, "bob")):
            login = client.post("/api/login", json={"username": name, "password": f"Synthetic-{name.title()}-Password-2026"})
            client.headers["X-CSRF-Token"] = login.json()["csrf"]
        cid = alice.post("/api/conversations").json()["id"]
        raw = (picture / "synthetic.png").read_bytes()
        assert alice.post(f"/api/conversations/{cid}/upload?name=synthetic.png", content=raw).status_code == 200
        response = alice.get(f"/api/conversations/{cid}/image?name=synthetic.png")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert bob.get(f"/api/conversations/{cid}/image?name=synthetic.png").status_code == 404
        assert alice.get(f"/api/conversations/{cid}/download?name=synthetic.png").content == raw
        assert alice.post(f"/api/conversations/{cid}/upload?name=bad.png", content=b"<svg/>").status_code == 200
        assert alice.get(f"/api/conversations/{cid}/image?name=bad.png").status_code == 422

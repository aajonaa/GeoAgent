"""Synthetic contract fixtures and independent numerical/artifact checks."""
from copy import deepcopy
import csv
import hashlib
import importlib
import json
from pathlib import Path
from threading import Event

import numpy as np
import pytest
from geological_agent.bootstrap import build_registry
from geological_agent.contracts import ToolCall
from geological_agent.settings import Settings
from geological_agent.tools import ToolExecutionContext, ToolExecutor
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError
from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("GeoShapelyGeometry", "GeoPandasSpatialJoin", "GeoFionaDatasetInfo", "GeoRasterioWindow",
         "GeoCartopyPointMap", "GeoDatashaderDensity", "HydroAnaFlowTheis", "SeismicObsPyBandpass")


def source(name):
    spec = next(x for x in catalog()["tools"] if x["id"] == name)
    module, method = spec["source_interface"]["entrypoint"]["callable"].split(":")
    return spec, getattr(importlib.import_module(module), method)


def sample(name):
    spec, function = source(name)
    args = deepcopy(spec["example_arguments"])
    for key in spec["source_interface"]["path_fields"]:
        args[key] = str(ROOT / args[key])
    return spec, function, args


def direct(name, path, args=None):
    spec, function, original = sample(name)
    kwargs = {"args": original if args is None else args}
    if spec["source_interface"]["entrypoint"].get("output_directory_parameter"):
        kwargs["output_dir"] = path
    return function(**kwargs)


def semantic(result):
    value = deepcopy(result)
    value.pop("artifacts")
    value["provenance"].pop("output_sha256")
    return value


@pytest.mark.parametrize("name", NAMES)
def test_source_dict_json_and_args_keyword_preserve_semantics(name, tmp_path):
    spec, function, args = sample(name)
    files = bool(spec["source_interface"]["entrypoint"].get("output_directory_parameter"))
    kwargs = {"output_dir": tmp_path / "dict"} if files else {}
    first = function(args=args, **kwargs)
    second = function(json.dumps(args), **({"output_dir": tmp_path / "json"} if files else {}))
    assert semantic(first) == semantic(second)
    assert first["units"]
    assert first["provenance"]["network_used"] is False
    assert first["provenance"]["installed_version"] == spec["metadata"]["upstream"]["version"]
    assert first["provenance"]["runtime_source"] == "pinned_package_release_not_archive_head"
    assert len(first["provenance"]["input_sha256"]) == 64
    json.dumps(first, allow_nan=False)
    for path in map(Path, first["artifacts"]):
        assert path.is_file() and path.stat().st_size > 0
        assert first["provenance"]["output_sha256"][path.name] == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("name", NAMES)
def test_native_execution_and_real_artifact_registration(name, tmp_path):
    spec, _, args = sample(name)
    originals = {}
    for key in spec["source_interface"]["path_fields"]:
        original = Path(args[key])
        target = tmp_path / original.name
        content = original.read_bytes()
        target.write_bytes(content)
        args[key] = target.name
        originals[target] = hashlib.sha256(content).hexdigest()
    registry, _, base = build_registry()
    ctx = ToolExecutionContext("earth-wave1", tmp_path, (name,), Settings(), Event())
    result = ToolExecutor(registry).execute(ToolCall("native", name, args), ctx)
    assert result.status == "ok", result
    assert name not in base
    generates = bool(spec["source_interface"]["entrypoint"].get("output_directory_parameter"))
    assert bool(result.artifacts) == generates
    assert registry.get(name).pure is (not generates and not spec["source_interface"]["path_fields"])
    for path, digest in originals.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("name,changes,code", [
    ("GeoShapelyGeometry", {"crs": "EPSG:4326"}, "invalid_arguments"),
    ("GeoShapelyGeometry", {"geometry": {"type": "Point", "coordinates": [float("nan"), 1]}}, "invalid_arguments"),
    ("GeoShapelyGeometry", {"geometry": {"type": "Point", "coordinates": [True, 1]}}, "invalid_arguments"),
    ("GeoPandasSpatialJoin", {"crs": "not-a-crs"}, "invalid_arguments"),
    ("GeoPandasSpatialJoin", {"predicate": "arbitrary_expression"}, "invalid_arguments"),
    ("GeoFionaDatasetInfo", {"input_path": "absent.geojson"}, "missing_input"),
    ("GeoRasterioWindow", {"bands": [1, 1]}, "invalid_arguments"),
    ("GeoRasterioWindow", {"col_off": 999}, "invalid_arguments"),
    ("GeoRasterioWindow", {"width": 2048, "height": 2048, "bands": [1, 2, 3]}, "resource_limit"),
    ("GeoCartopyPointMap", {"longitude": [116, 117]}, "invalid_arguments"),
    ("GeoCartopyPointMap", {"projection": "mercator", "extent": [115, 118, 39, 89]}, "invalid_arguments"),
    ("GeoDatashaderDensity", {"x": [2, 2, 2]}, "invalid_arguments"),
    ("GeoDatashaderDensity", {"y": [0]}, "invalid_arguments"),
    ("HydroAnaFlowTheis", {"storativity": 0}, "invalid_arguments"),
    ("HydroAnaFlowTheis", {"time_s": [600, 60]}, "invalid_arguments"),
    ("HydroAnaFlowTheis", {"time_s": list(range(1, 130)), "radius_m": list(range(1, 130))}, "resource_limit"),
    ("SeismicObsPyBandpass", {"freqmin_hz": 6}, "invalid_arguments"),
    ("SeismicObsPyBandpass", {"freqmax_hz": 50}, "invalid_arguments"),
])
def test_negative_inputs_return_stable_source_errors(name, changes, code, tmp_path):
    _, _, args = sample(name)
    with pytest.raises(ScientificToolError) as exc:
        direct(name, tmp_path / "out", {**args, **changes})
    assert exc.value.code == code and not exc.value.retryable


def test_geometry_has_independent_square_oracle(tmp_path):
    value = direct("GeoShapelyGeometry", tmp_path)
    assert value["area"] == 100
    assert value["length"] == 40
    assert value["centroid"] == [5, 5]
    assert value["bounds"] == [0, 0, 10, 10]


def test_spatial_join_and_fiona_counts_are_not_fabricated(tmp_path):
    assert direct("GeoPandasSpatialJoin", tmp_path)["matches"] == [[0, 0]]
    value = direct("GeoFionaDatasetInfo", tmp_path)
    assert value["feature_count"] == 2
    assert value["geometry_type"] == "Point"
    assert value["driver"] == "GeoJSON" and value["crs"]


def test_window_values_crs_and_nodata_are_preserved(tmp_path):
    import rasterio
    from PIL import Image
    value = direct("GeoRasterioWindow", tmp_path / "out")
    with rasterio.open(ROOT / "assets/earth-python-wave1/raster.tif") as original, rasterio.open(tmp_path / "out/window.tif") as output:
        assert np.array_equal(original.read(), output.read())
        assert np.array_equal(original.read_masks(), output.read_masks())
        assert original.crs == output.crs and original.transform == output.transform
    assert value["valid_pixels"] == 15
    assert value["statistics"][0]["mean"] == 8
    with Image.open(tmp_path / "out/window-preview.png") as image:
        assert image.size == (4, 4) and image.getpixel((0, 0))[3] == 0


def test_cartopy_outputs_without_any_network_client(tmp_path, monkeypatch):
    import socket
    import urllib.request
    import requests
    def blocked(*args, **kwargs):
        raise AssertionError("Offline map must not contact a service")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
    result = direct("GeoCartopyPointMap", tmp_path / "out")
    assert result["point_count"] == 1
    assert {Path(x).suffix for x in result["artifacts"]} == {".svg", ".png"}
    assert "no coastlines" in result["basemap"]


def test_density_counts_have_exact_conservation(tmp_path):
    result = direct("GeoDatashaderDensity", tmp_path / "out")
    counts = np.load(tmp_path / "out/pixel-counts.npy", allow_pickle=False)
    assert counts.shape == (8, 8) and counts.dtype == np.dtype("uint32")
    assert int(counts.sum()) == result["point_count"] == result["binned_points"] == 3


def test_theis_has_independent_exponential_integral_oracle(tmp_path):
    from scipy.special import exp1
    result = direct("HydroAnaFlowTheis", tmp_path / "out")
    _, _, args = sample("HydroAnaFlowTheis")
    times = np.asarray(args["time_s"])[:, None]
    radii = np.asarray(args["radius_m"])[None, :]
    u = args["storativity"] * radii ** 2 / (4 * args["transmissivity_m2_s"] * times)
    expected = args["pumping_rate_m3_s"] * exp1(u) / (4 * np.pi * args["transmissivity_m2_s"])
    np.testing.assert_allclose(result["drawdown_m"], expected, rtol=1e-9, atol=1e-12)
    rows = list(csv.DictReader((tmp_path / "out/drawdown.csv").open()))
    assert len(rows) == 6 and float(rows[-1]["drawdown_m"]) == result["drawdown_m"][-1][-1]


def test_obspy_filter_rejects_out_of_band_energy_without_changing_timebase(tmp_path):
    from obspy import read
    original = read(str(ROOT / "assets/earth-python-wave1/waveform.mseed"))
    result = direct("SeismicObsPyBandpass", tmp_path / "out")
    filtered = read(str(tmp_path / "out/filtered.mseed"))
    assert len(filtered) == len(original) == 1
    assert filtered[0].stats.npts == original[0].stats.npts == 4000
    assert filtered[0].stats.starttime == original[0].stats.starttime
    assert filtered[0].stats.sampling_rate == original[0].stats.sampling_rate == 100
    freq = np.fft.rfftfreq(4000, 0.01)
    ten_hz = np.argmin(abs(freq - 10))
    assert abs(np.fft.rfft(filtered[0].data)[ten_hz]) < 0.1 * abs(np.fft.rfft(original[0].data)[ten_hz])
    assert result["units"]["amplitude"] == "counts"


def test_files_are_never_overwritten(tmp_path):
    out = tmp_path / "existing"
    out.mkdir()
    (out / "keep.txt").write_text("preserve")
    with pytest.raises(ScientificToolError) as exc:
        direct("GeoCartopyPointMap", out)
    assert exc.value.code == "output_conflict"
    assert (out / "keep.txt").read_text() == "preserve"

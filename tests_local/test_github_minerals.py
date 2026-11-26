"""Independent analytic oracles and native execution for the new scientific tools."""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
from threading import Event

import numpy as np
import pytest
import rasterio
from PIL import Image

from geological_agent.bootstrap import build_registry
from geological_agent.contracts import ToolCall
from geological_agent.settings import Settings
from geological_agent.tools import ToolExecutionContext, ToolExecutor
from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog, definition
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError
from geotool.domain_worker import run as transported

ROOT = Path(__file__).resolve().parents[1]
NAMES = (
    "GeoSpectralAngleMatch", "GeoSpectralContinuumRemoval", "GeoSpectralLinearUnmix", "GeoSpectralAngleMap",
    "GeoGeochemCLR", "GeoGeochemOxideMoles", "GeoGeochemREEPattern", "GeoStereonetAnalysis", "GeoStructuralPlaneIntersection",
)


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def inputs(tmp_path):
    folder = tmp_path / "assets/github-minerals"
    folder.mkdir(parents=True)
    for source in (ROOT / "assets/github-minerals").iterdir():
        if source.is_file():
            (folder / source.name).write_bytes(source.read_bytes())
    return tmp_path


def example(name):
    return deepcopy(definition(name)["example_arguments"])


def direct(name, workspace, args=None, tag="direct", serialized=False):
    spec = definition(name)
    params = example(name) if args is None else deepcopy(args)
    for field in spec["source_interface"]["path_fields"]:
        if field in params:
            params[field] = str(workspace / params[field])
    entry = spec["source_interface"]["entrypoint"]
    mod, fn = entry["callable"].split(":")
    kw = {"args": json.dumps(params) if serialized else params}
    if entry.get("output_directory_parameter"):
        kw["output_dir"] = workspace / tag
    return getattr(importlib.import_module(mod), fn)(**kw)


def oracle(name, value):
    if name == "GeoSpectralAngleMatch":
        a = np.degrees(np.arccos(.75 / np.sqrt(.25 ** 2 + .75 ** 2)))
        np.testing.assert_allclose(value["angles_degrees"], [[0, 90], [90, 0], [90 - a, a]], atol=1e-6)
        assert value["matches"] == ["SYNTHETIC_REF_A", "SYNTHETIC_REF_B", None]
    elif name == "GeoSpectralContinuumRemoval":
        np.testing.assert_allclose(value["continuum"], [[1, 1, 1]])
        np.testing.assert_allclose(value["continuum_removed"], [[1, .5, 1]])
        assert value["maximum_depth"] == [.5] and value["deepest_wavelength_nm"] == [1500]
    elif name == "GeoSpectralLinearUnmix":
        np.testing.assert_allclose(value["coefficients"], [[1, 0], [0, 1], [.25, .75]], atol=1e-12)
        np.testing.assert_allclose(value["rmse_reflectance"], 0, atol=1e-12)
        assert not value["sum_to_one_enforced"] and not value["nonnegative_enforced"]
    elif name == "GeoSpectralAngleMap":
        assert value["matched_pixels"] == [1, 1]
        assert (value["valid_pixels"], value["excluded_pixels"], value["unmatched_pixels"]) == (2, 2, 0)
        assert value["crs"] == "EPSG:32652" and value["affine"] == [10, 0, 500000, 0, -10, 4500000]
    elif name == "GeoGeochemCLR":
        np.testing.assert_allclose(value["clr"], [[-np.log(2), 0, np.log(2)]], atol=1e-12)
    elif name == "GeoGeochemOxideMoles":
        np.testing.assert_allclose(value["moles_per_100g"], [[1, 1]], atol=1e-12)
        np.testing.assert_allclose(value["mol_percent"], [[50, 50]], atol=1e-10)
    elif name == "GeoGeochemREEPattern":
        np.testing.assert_allclose(value["normalized"], [[2, 4, 2]], atol=1e-12)
        np.testing.assert_allclose(value["eu_anomaly"], [2], atol=1e-12)
    elif name == "GeoStereonetAnalysis":
        fit = value["fit_plane"]
        assert fit is not None and fit["dip_degrees"] == pytest.approx(45)
        assert min(fit["strike_degrees"], 360 - fit["strike_degrees"]) < 1e-6
        assert value["eigenvalues"][0] > value["eigenvalues"][1]
    elif name == "GeoStructuralPlaneIntersection":
        assert value["plunge_degrees"] == pytest.approx(90) and value["bearing_degrees"] is None
    else:
        raise AssertionError("Missing independent scientific oracle")


@pytest.mark.parametrize("name", NAMES)
def test_direct_json_native_transport_and_input_integrity(name, inputs):
    before = {p.name: digest(p) for p in (inputs / "assets/github-minerals").iterdir() if p.is_file()}
    for serialized, tag in [(False, "object"), (True, "json")]:
        result = direct(name, inputs, tag=tag, serialized=serialized)
        oracle(name, result)
        for filename, sha in result["provenance"]["output_sha256"].items():
            assert digest(inputs / tag / filename) == sha
        for path in result["artifacts"]:
            if path.endswith(".png"):
                with Image.open(path) as im:
                    assert im.width >= 1000 and im.height >= 700
                    assert len(set(im.convert("RGB").resize((64, 64)).getdata())) > 20
    registry, loader, base = build_registry()
    skill = next(s for s in loader.registry.list() if name in loader.load(s.id).tool_names)
    ctx = ToolExecutionContext("minerals-tests", inputs, base, Settings(), Event())
    executor = ToolExecutor(registry)
    opened = executor.execute(ToolCall("disclose", "skill_load", {"skill_id": skill.id}), ctx)
    assert opened.status == "ok" and name in opened.data["tool_names"]
    ctx.allowed_tool_names = (name,)
    result = executor.execute(ToolCall("native", name, example(name)), ctx)
    assert result.status == "ok", result.error
    oracle(name, result.data)
    for art in result.artifacts:
        p = inputs / art.path
        assert p.is_file() and p.resolve().is_relative_to(inputs.resolve())
        assert digest(p) == result.data["provenance"]["output_sha256"][p.name]
    transported_result = transported({"tool_id": name, "input": example(name), "workspace": str(inputs)})
    assert transported_result["ok"]
    oracle(name, transported_result["result"])
    assert before == {p.name: digest(p) for p in (inputs / "assets/github-minerals").iterdir() if p.is_file()}


def mutate_file(inputs, name, **updates):
    params = example(name)
    file = inputs / params["data_path"]
    data = json.loads(file.read_text())
    data.update(updates)
    file.write_text(json.dumps(data))
    return params


@pytest.mark.parametrize("name,updates", [
    ("GeoSpectralAngleMatch", {"reference_wavelength_nm": [1000, 1501, 2000]}),
    ("GeoSpectralAngleMatch", {"spectra": [[0, 0, 0]] * 3}),
    ("GeoSpectralAngleMatch", {"spectra": [[True, 0, 0]] * 3}),
    ("GeoSpectralContinuumRemoval", {"wavelength_nm": [1000, 1000, 2000]}),
    ("GeoSpectralContinuumRemoval", {"spectra": [[0, 0, 0]]}),
    ("GeoSpectralLinearUnmix", {"reference_spectra": [[1, 0, 0], [1, 0, 0]]}),
    ("GeoGeochemCLR", {"values": [[0, 2, 4]]}),
    ("GeoGeochemCLR", {"unit": "mixed_units"}),
    ("GeoGeochemOxideMoles", {"components": ["FeOT", "MgO"]}),
    ("GeoGeochemOxideMoles", {"values": [[100, 100]]}),
    ("GeoGeochemREEPattern", {"reference_values": [0, 1, 1]}),
    ("GeoGeochemREEPattern", {"components": ["Gd", "Eu", "Sm"]}),
    ("GeoStereonetAnalysis", {"dip_degrees": [91, 45, 45]}),
    ("GeoStereonetAnalysis", {"convention": "dip_direction"}),
])
def test_scientific_invalid_input_is_structured(name, updates, inputs):
    params = mutate_file(inputs, name, **updates)
    with pytest.raises(ScientificToolError) as e:
        direct(name, inputs, params)
    assert e.value.code == "invalid_arguments" and not e.value.retryable


@pytest.mark.parametrize("name", NAMES)
def test_undeclared_argument_rejected_by_both_interfaces(name, inputs):
    params = {**example(name), "command": "untrusted"}
    with pytest.raises(ScientificToolError) as e:
        direct(name, inputs, params)
    assert e.value.code == "invalid_arguments" and not e.value.retryable
    registry, _, _ = build_registry()
    ctx = ToolExecutionContext("invalid", inputs, (name,), Settings(), Event())
    result = ToolExecutor(registry).execute(ToolCall("bad", name, params), ctx)
    assert result.status == "error" and result.error.code == "invalid_arguments" and not result.error.retryable


def test_map_pixels_crs_nodata_and_mask_are_preserved(inputs):
    direct("GeoSpectralAngleMap", inputs)
    with rasterio.open(inputs / "direct/spectral-classes.tif") as src:
        np.testing.assert_array_equal(src.read(1), [[1, 2], [0, 0]])
        assert src.nodata == 0 and str(src.crs) == "EPSG:32652"
        assert list(src.transform)[:6] == [10, 0, 500000, 0, -10, 4500000]
    with rasterio.open(inputs / "direct/spectral-angle-degrees.tif") as src:
        np.testing.assert_allclose(src.read(1), [[0, 0], [-9999, -9999]], atol=1e-6)
        assert src.nodata == -9999


def test_map_explicit_calibration(inputs):
    args = example("GeoSpectralAngleMap")
    path = inputs / args["raster_path"]
    with rasterio.open(path, "r+") as src:
        data = src.read()
        data[data != -9999] *= 10000
        src.write(data)
    args["reflectance_scale"] = .0001
    oracle("GeoSpectralAngleMap", direct("GeoSpectralAngleMap", inputs, args))


def test_map_mask_mismatch_and_unknown_labels_rejected(inputs):
    args = example("GeoSpectralAngleMap")
    with rasterio.open(inputs / args["quality_mask_path"], "r+") as mask:
        mask.crs = "EPSG:32651"
    with pytest.raises(ScientificToolError) as e:
        direct("GeoSpectralAngleMap", inputs)
    assert e.value.code == "invalid_arguments"


def test_parallel_planes_are_not_a_direction(inputs):
    args = {"strike1_degrees": 20, "dip1_degrees": 30, "strike2_degrees": 20, "dip2_degrees": 30}
    with pytest.raises(ScientificToolError) as e:
        direct("GeoStructuralPlaneIntersection", inputs, args)
    assert e.value.code == "unsupported_conditions" and not e.value.retryable


def test_native_input_path_cannot_escape(inputs):
    registry, _, _ = build_registry()
    ctx = ToolExecutionContext("path", inputs, ("GeoGeochemCLR",), Settings(), Event())
    result = ToolExecutor(registry).execute(ToolCall("escape", "GeoGeochemCLR", {"data_path": "../outside.json"}), ctx)
    assert result.status == "error" and result.error.code == "invalid_path"


def test_catalog_is_exact_addition_to_accepted_baseline():
    note = json.loads((ROOT / "catalog/source_delivery/github-minerals/baseline-preservation.json").read_text())
    def canon(v):
        return hashlib.sha256(json.dumps(v, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
    current = catalog()
    assert len(current["tools"]) == 346 and len(current["skills"]) == 70
    assert {t["id"] for t in current["tools"][220:229]} == set(NAMES)
    assert canon(current["tools"][:220]) == note["old_tools_canonical_sha256"]
    assert canon(current["skills"][:47]) == note["old_skills_canonical_sha256"]
    examples = json.loads((ROOT / "catalog/source_delivery/examples.json").read_text())
    assert canon({k: v for k, v in examples.items() if k in {t["id"] for t in current["tools"][:220]}}) == note["old_examples_canonical_sha256"]


def test_missing_dependency_is_explicit(inputs, monkeypatch):
    from geological_agent.geology import collection_contracts
    original = collection_contracts.metadata.version
    def missing(name):
        if name == "spectral":
            raise collection_contracts.metadata.PackageNotFoundError(name)
        return original(name)
    monkeypatch.setattr(collection_contracts.metadata, "version", missing)
    with pytest.raises(ScientificToolError) as e:
        direct("GeoSpectralAngleMatch", inputs)
    assert e.value.code == "missing_dependency" and not e.value.retryable

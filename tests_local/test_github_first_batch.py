"""Acceptance tests for the bounded GitHub first-batch adapters."""
from threading import Event
import copy
import importlib
import json
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from geological_agent.bootstrap import build_registry
from geological_agent.contracts import ToolCall
from geological_agent.geology.github_first_batch import (
    hydro_error_metrics, hydrointerp_grid, metpy_wind_components,
    reference_et0, region_mask, scientific_curve_fit, seismic_reflectivity,
    spatial_moran, verde_grid,
)
from geological_agent.settings import Settings
from geological_agent.tools import ToolExecutionContext, ToolExecutor
from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog, validate_registration_metadata


NAMES = ("GeoVerdeGrid", "GeoRegionMask", "HydroErrorMetrics", "ScientificCurveFit",
         "HydroInterpolationGrid", "MetPyWindComponents", "SeismicReflectivity",
         "SeismicSegySummary", "HydroReferenceET0", "SpatialMoranI")


def test_first_batch_is_registered_with_complete_provenance():
    registry, _, _ = build_registry()
    specs = {item["id"]: item for item in catalog()["tools"]}
    for name in NAMES:
        assert name in registry.names()
        validate_registration_metadata(specs[name])
        assert specs[name]["registration_metadata"]["source_commit"]
        assert specs[name]["registration_metadata"]["provider"]
        assert specs[name]["registration_metadata"]["license"]
        assert specs[name]["registration_metadata"]["asset_version"]
        assert specs[name]["registration_metadata"]["official_protocol_version"] is None


def test_numeric_adapters_return_structured_results():
    assert len(verde_grid({"easting": [0, 1, 0, 1], "northing": [0, 0, 1, 1],
                           "values": [0, 1, 1, 2], "region": [0, 1, 0, 1], "shape": [3, 3]})["grid"]) == 3
    regions = region_mask({"longitude": [-100, 10, 120], "latitude": [40, 50, -25], "region_set": "srex"})
    assert regions["region_ids"] == [4, 12, 25]
    assert hydro_error_metrics({"observed": [1, 2, 3], "simulated": [1, 2, 4], "metrics": ["rmse", "nse"]})["sample_count"] == 3
    assert scientific_curve_fit({"x": [0, 1, 2], "y": [1, 3, 5], "model": "linear"})["parameters"]["slope"] == pytest.approx(2)
    assert hydrointerp_grid({"easting": [0, 1, 0, 1], "northing": [0, 0, 1, 1], "values": [0, 1, 1, 2],
                             "region": [0, 1, 0, 1], "resolution": .5, "method": "linear", "crs": "EPSG:4326"})["shape"] == [2, 2]
    assert metpy_wind_components({"speed": [10], "direction": [0], "speed_unit": "m/s"})["v"][0] == pytest.approx(-10)
    assert seismic_reflectivity({"vp": [2000, 2200], "density": [2, 2.2]})["count"] == 1
    et0 = reference_et0({"tmin_c": 10, "tmax_c": 25, "rh_min": 40, "rh_max": 80, "wind_m_s": 2,
                         "solar_mj_m2": 18, "latitude_deg": 35, "day_of_year": 180})
    assert et0["net_radiation_mj_m2_day"] < 18
    assert et0["net_radiation_mj_m2_day"] == pytest.approx(10.9637, rel=1e-3)
    assert et0["et0_mm_day"] == pytest.approx(4.2287, rel=1e-3)
    assert spatial_moran({"x": [0, 1, 0, 1], "y": [0, 0, 1, 1], "values": [1, 2, 3, 4], "k": 2})["sample_count"] == 4


def test_et0_matches_fao56_reference_case():
    # FAO-56, chapter 4, Example 18 gives Rn=13.28 and ET0=3.88~3.9.
    # https://www.fao.org/4/x0490e/x0490e08.htm
    result = reference_et0({"tmin_c": 12.3, "tmax_c": 21.5, "rh_min": 63,
                            "rh_max": 84, "wind_m_s": 2.078, "solar_mj_m2": 22.07,
                            "latitude_deg": 50.8, "day_of_year": 187, "altitude_m": 100})
    assert result["net_radiation_mj_m2_day"] == pytest.approx(13.2827, rel=1e-3)
    assert result["et0_mm_day"] == pytest.approx(3.8796, rel=1e-3)


def test_grid_metrics_and_moran_match_known_answers():
    points = {"easting": [0, 1, 0, 1], "northing": [0, 0, 1, 1],
              "values": [0, 1, 1, 2], "region": [0, 1, 0, 1]}
    grid = verde_grid({**points, "shape": [3, 2]})
    values = np.asarray(grid["grid"])
    assert grid["shape"] == [3, 2] and values.shape == (2, 3)
    # An undamped interpolating spline must reproduce its four control points.
    np.testing.assert_allclose(values[:, [0, -1]], [[0, 1], [1, 2]], atol=1e-10)
    interpolation = hydrointerp_grid({**points, "resolution": .5,
                                     "method": "linear", "crs": "EPSG:4326"})
    np.testing.assert_allclose(interpolation["x"], [0, .5])
    np.testing.assert_allclose(interpolation["y"], [0, .5])
    # Linear interpolation of z=x+y on the unit square.
    np.testing.assert_allclose(interpolation["grid"], [[0, .5], [.5, 1]])
    errors = hydro_error_metrics({"observed": [1, 2, 3], "simulated": [1, 2, 4],
                                  "metrics": ["rmse", "mae", "nse"]})
    assert errors["metrics"] == pytest.approx({"rmse": 3 ** -.5, "mae": 1 / 3, "nse": .5})
    # No distance ties: directed 1-nearest neighbors are [1, 0, 1, 2].
    # Centered values are [-1.5, -.5, .5, 1.5], so I=(2/5)=0.4.
    moran = spatial_moran({"x": [0, 1, 3, 7], "y": [0, 0, 0, 0],
                           "values": [1, 2, 3, 4], "k": 1})
    assert moran["moran_i"] == pytest.approx(.4)
    assert moran["expected_i"] == pytest.approx(-1 / 3)
    assert moran["p_sim"] is None


@pytest.mark.parametrize("name", NAMES)
def test_first_batch_source_json_transport_and_skill_disclosure(name, tmp_path):
    from geotool.domain_worker import digest, run

    root = Path(__file__).resolve().parents[1]
    specs = {item["id"]: item for item in catalog()["tools"]}
    spec = specs[name]
    examples = json.loads((root / "catalog/source_delivery/examples.json").read_text(encoding="utf-8"))
    args = copy.deepcopy(examples[name])
    for field in spec["source_interface"]["path_fields"]:
        source = root / args[field]
        target = tmp_path / args[field]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    direct_args = copy.deepcopy(args)
    for field in spec["source_interface"]["path_fields"]:
        direct_args[field] = str(tmp_path / args[field])
    module, function = spec["source_interface"]["entrypoint"]["callable"].split(":")
    fn = getattr(importlib.import_module(module), function)
    direct = fn(direct_args)
    serialized = fn(json.dumps(direct_args, allow_nan=False))
    response = run({"tool_id": name, "input": args, "workspace": str(tmp_path)})
    transported = response["result"]
    assert direct == serialized == transported
    for value in (direct, serialized, transported):
        Draft202012Validator(spec["output_schema"]).validate(value)
        json.dumps(value, allow_nan=False)
    if spec["source_interface"]["path_fields"]:
        relative = args["segy_path"]
        assert response["provenance"]["sources"] == [
            {"path": relative, "sha256": digest(tmp_path / relative)}]

    registry, loader, base_tools = build_registry()
    executor = ToolExecutor(registry)
    linked = [skill for skill in loader.registry.list() if name in loader.load(skill.id).tool_names]
    assert linked, f"No existing skill discloses {name}"
    context = ToolExecutionContext("disclosure", tmp_path, base_tools, Settings(), Event())
    loaded = executor.execute(ToolCall("load", "skill_load", {"skill_id": linked[0].id}), context)
    assert loaded.status == "ok" and name in loaded.data["tool_names"]


def test_first_batch_rejects_missing_hydrointerp_crs():
    with pytest.raises(ValueError, match="crs is required"):
        hydrointerp_grid({"easting": [0, 1], "northing": [0, 1], "values": [1, 2],
                          "region": [0, 1, 0, 1], "resolution": 1})


def test_moran_handles_constant_values_and_reproducible_permutations():
    constant = spatial_moran({"x": [0, 1, 0, 1], "y": [0, 0, 1, 1],
                              "values": [1, 1, 1, 1], "k": 2})
    assert constant["moran_i"] is None
    args = {"x": [0, 1, 0, 1, 2], "y": [0, 0, 1, 1, 1],
            "values": [1, 2, 3, 4, 5], "k": 2, "permutations": 25, "random_seed": 42}
    assert spatial_moran(args)["p_sim"] == spatial_moran(args)["p_sim"]


def test_bruges_uses_real_pkg_resources_without_a_shim():
    import sys
    import pkg_resources
    before = pkg_resources
    seismic_reflectivity({"vp": [2000, 2200], "density": [2, 2.2]})
    assert sys.modules["pkg_resources"] is before
    assert Path(pkg_resources.__file__).is_file()
    assert pkg_resources.get_distribution("bruges").version == "0.5.4"


def test_executor_validates_first_batch_contract(tmp_path):
    registry, _, _ = build_registry()
    context = ToolExecutionContext("first-batch", tmp_path, ("HydroErrorMetrics",), Settings(), Event())
    result = ToolExecutor(registry).execute(ToolCall("metrics", "HydroErrorMetrics", {
        "observed": [1, 2, 3], "simulated": [1, 2, 4], "metrics": ["rmse"]}), context)
    assert result.status == "ok"
    assert result.data["metrics"]["rmse"] == pytest.approx(3 ** -.5)
    invalid = ToolExecutor(registry).execute(ToolCall("bad", "HydroErrorMetrics", {
        "observed": [1], "simulated": [1], "metrics": ["not-a-metric"]}), context)
    assert invalid.status == "error"
    assert invalid.error.code == "invalid_arguments"


def test_segyio_summary_reads_a_small_local_file(tmp_path):
    segyio = pytest.importorskip("segyio")
    path = tmp_path / "sample.sgy"
    spec = segyio.spec()
    spec.sorting = segyio.TraceSortingFormat.INLINE_SORTING
    spec.format = 1
    spec.samples = range(4)
    spec.ilines = range(1, 2)
    spec.xlines = range(1, 3)
    with segyio.create(str(path), spec) as handle:
        handle.trace[0] = np.array([1, 2, 3, 4], dtype=np.float32)
        handle.trace[1] = np.array([2, 3, 4, 5], dtype=np.float32)
        handle.bin[segyio.BinField.Interval] = 2000
    from geological_agent.geology.github_first_batch import segy_summary
    result = segy_summary({"segy_path": str(path), "preview_traces": 2})
    assert result["trace_count"] == 2
    assert result["sample_count"] == 4

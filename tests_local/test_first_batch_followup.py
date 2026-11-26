"""Regression cases from the second review; no model or network calls."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from threading import Event

import numpy as np
import pytest

from geological_agent.bootstrap import build_registry
from geological_agent.contracts import ToolCall
from geological_agent.geology.github_first_batch import reference_et0, region_mask, spatial_moran
from geological_agent.settings import Settings
from geological_agent.tools import ToolExecutionContext, ToolExecutor
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError
from legacy.ToolsAgent.ToolsFuns.source_contracts import definition


ET0 = {"tmin_c": 12.3, "tmax_c": 21.5, "rh_min": 63, "rh_max": 84,
       "wind_m_s": 2.078, "solar_mj_m2": 22.07, "latitude_deg": 50.8,
       "day_of_year": 187, "altitude_m": 100}


@pytest.mark.parametrize("region_set", definition("GeoRegionMask")["input_schema"]["properties"]["region_set"]["enum"])
def test_each_declared_region_set_has_a_known_point_answer(region_set):
    expected = {"srex": [4, 12, 25]}
    result = region_mask({"longitude": [-100, 10, 120], "latitude": [40, 50, -25],
                          "region_set": region_set})
    assert result["region_ids"] == expected[region_set]


@pytest.mark.parametrize("region_set", ["natural_earth_v5_1_2", "natural_earth_v5_0_0"])
def test_unimplemented_natural_earth_sets_are_rejected_by_executor(region_set, tmp_path):
    registry, _, _ = build_registry()
    context = ToolExecutionContext("regions", tmp_path, ("GeoRegionMask",), Settings(), Event())
    result = ToolExecutor(registry).execute(ToolCall("mask", "GeoRegionMask", {
        "longitude": [10], "latitude": [50], "region_set": region_set}), context)
    assert result.status == "error" and result.error.code == "invalid_arguments"
    # The executor's shared schema error permits a corrected call. Direct
    # source callers also receive a stable error instead of AttributeError.
    with pytest.raises(ScientificToolError) as caught:
        region_mask({"longitude": [10], "latitude": [50], "region_set": region_set})
    assert caught.value.code == "invalid_arguments" and not caught.value.retryable


@pytest.mark.parametrize("changes,code,fragment", [
    ({"latitude_deg": 80, "day_of_year": 355, "solar_mj_m2": 0}, "unsupported_conditions", "polar night"),
    ({"solar_mj_m2": 100}, "invalid_arguments", "Rs/Rso > 1"),
])
def test_et0_boundaries_have_stable_nonretryable_errors(changes, code, fragment, tmp_path):
    args = {**ET0, **changes}
    for payload in (args, json.dumps(args)):
        with pytest.raises(ScientificToolError, match=fragment) as caught:
            reference_et0(payload)
        assert caught.value.code == code and not caught.value.retryable
    registry, _, _ = build_registry()
    context = ToolExecutionContext("weather", tmp_path, ("HydroReferenceET0",), Settings(), Event())
    result = ToolExecutor(registry).execute(ToolCall("et0", "HydroReferenceET0", args), context)
    assert result.status == "error" and result.error.code == code
    assert not result.error.retryable


def test_worker_rejects_unapproved_entrypoint_before_import(monkeypatch):
    from geotool import domain_worker
    spec = deepcopy(definition("GeoVerdeGrid"))
    spec["source_interface"]["entrypoint"]["callable"] = "os:system"
    monkeypatch.setattr(domain_worker, "definition", lambda _: spec)
    def forbidden(*args, **kwargs):
        pytest.fail("Worker imported a module before checking its allowlist")
    monkeypatch.setattr(domain_worker.importlib, "import_module", forbidden)
    with pytest.raises(ValueError, match="Unexpected GitHub first-batch implementation module"):
        domain_worker.original_call("GeoVerdeGrid", {}, None)


MORAN = {"x": [0, 1, 3, 7, 12, 18, 25, 33], "y": [0] * 8,
         "values": [2, 1, 4, 3, 8, 5, 7, 6], "k": 2, "permutations": 99}


@pytest.mark.parametrize("seed", [0, 42, 91])
def test_local_moran_permutations_agree_with_pinned_esda(seed):
    from esda.moran import Moran
    from libpysal.weights import KNN
    # Reference-only global seeding: this single-threaded test calls the
    # upstream constructor with its documented convention, then restores it.
    weights = KNN.from_array(np.column_stack([MORAN["x"], MORAN["y"]]), k=MORAN["k"])
    state = np.random.get_state()
    try:
        np.random.seed(seed)
        reference = Moran(np.array(MORAN["values"]), weights, permutations=MORAN["permutations"])
    finally:
        np.random.set_state(state)
    actual = spatial_moran({**MORAN, "random_seed": seed})
    assert actual["moran_i"] == pytest.approx(reference.I)
    assert actual["p_sim"] == reference.p_sim


def test_concurrent_moran_uses_local_rng_and_preserves_process_state():
    expected = {seed: spatial_moran({**MORAN, "random_seed": seed}) for seed in (0, 42, 91)}
    before = np.random.get_state()
    seeds = [0, 42, 91] * 8
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda seed: spatial_moran({**MORAN, "random_seed": seed}), seeds))
    assert results == [expected[seed] for seed in seeds]
    after = np.random.get_state()
    assert before[0] == after[0] and before[2:] == after[2:]
    np.testing.assert_array_equal(before[1], after[1])


def test_bruges_first_import_is_concurrent_and_uses_real_dependency():
    code = '''
from concurrent.futures import ThreadPoolExecutor
import sys
from pathlib import Path
from geological_agent.geology.github_first_batch import seismic_reflectivity
assert 'bruges' not in sys.modules
args = {'vp': [2000, 2200], 'density': [2, 2.2]}
with ThreadPoolExecutor(max_workers=6) as pool:
    results = list(pool.map(lambda _: seismic_reflectivity(args), range(18)))
assert all(row == results[0] for row in results)
assert abs(results[0]['coefficients'][0] - 0.09502262443438914) < 1e-12
import pkg_resources
assert Path(pkg_resources.__file__).is_file()
assert pkg_resources.get_distribution('bruges').version == '0.5.4'
print('real-dependency first import passed')
'''
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                               cwd=Path(__file__).resolve().parents[1], timeout=40)
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize("query,host,tool", [
    ("Verde spline scattered point gridding", "scientific_raster_analysis", "GeoVerdeGrid"),
    ("regionmask SREX point membership", "scientific_raster_analysis", "GeoRegionMask"),
    ("Nash-Sutcliffe efficiency streamflow simulation", "geological_table_analysis", "HydroErrorMetrics"),
    ("curve fitting exponential decay", "geological_table_analysis", "ScientificCurveFit"),
    ("hydrointerp station point grid interpolation", "scientific_raster_analysis", "HydroInterpolationGrid"),
    ("wind u v components", "climate_scenario_analysis", "MetPyWindComponents"),
    ("Bruges acoustic impedance reflection coefficients", "earthquake_catalog_analysis", "SeismicReflectivity"),
    ("SEG-Y seismic trace summary", "earthquake_catalog_analysis", "SeismicSegySummary"),
    ("reference evapotranspiration FAO-56 Penman-Monteith", "climate_scenario_analysis", "HydroReferenceET0"),
    ("Moran's I spatial autocorrelation", "geological_table_analysis", "SpatialMoranI"),
])
def test_typical_query_discovers_and_loads_existing_host(query, host, tool, tmp_path):
    registry, _, base = build_registry()
    context = ToolExecutionContext("find", tmp_path, base, Settings(), Event())
    executor = ToolExecutor(registry)
    found = executor.execute(ToolCall("find", "skill_find", {"query": query}), context)
    assert found.status == "ok" and found.data["skills"][0]["id"] == host
    loaded = executor.execute(ToolCall("load", "skill_load", {"skill_id": host}), context)
    assert loaded.status == "ok" and tool in loaded.data["tool_names"]


def test_skill_search_ignores_single_letters_and_preserves_chinese_queries():
    _, loader, _ = build_registry()
    assert not loader.registry.list("I / u v")
    assert not loader.registry.list("zzzzxyq")
    assert not loader.registry.list("nonexistent_litho_operation_xyz")
    assert loader.registry.list("参考蒸散发")[0].id == "climate_scenario_analysis"
    combined = loader.registry.list("Moran's I / wind u v components")
    assert {s.id for s in combined[:2]} == {"geological_table_analysis", "climate_scenario_analysis"}
    assert len(combined) < 34

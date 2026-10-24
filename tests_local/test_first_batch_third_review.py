"""Regression cases from the third first-batch review; no model or network calls."""
from pathlib import Path
from threading import Event

import pytest

from geological_agent.bootstrap import build_registry
from geological_agent.contracts import ToolCall
from geological_agent.geology.github_first_batch import RS_RSO_TOLERANCE, reference_et0
from geological_agent.geology.source_registry import EXISTING_SKILLS
from geological_agent.settings import Settings
from geological_agent.tools import ToolExecutionContext, ToolExecutor
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError
from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog


ROOT = Path(__file__).resolve().parents[1]
# FAO-56 Example 18 inputs; computed clear-sky radiation Rso is about 30.90.
ET0 = {"tmin_c": 12.3, "tmax_c": 21.5, "rh_min": 63, "rh_max": 84,
       "wind_m_s": 2.078, "latitude_deg": 50.8, "day_of_year": 187, "altitude_m": 100}
HOSTS = {"earthquake_catalog_analysis", "climate_scenario_analysis",
         "scientific_raster_analysis", "geological_table_analysis"}


def clear_sky():
    import pyeto
    latitude = pyeto.deg2rad(ET0["latitude_deg"])
    declination = pyeto.sol_dec(ET0["day_of_year"])
    ra = pyeto.et_rad(latitude, declination, pyeto.sunset_hour_angle(latitude, declination),
                      pyeto.inv_rel_dist_earth_sun(ET0["day_of_year"]))
    return pyeto.cs_rad(ET0["altitude_m"], ra)


def test_et0_reference_case_is_not_limited():
    result = reference_et0({**ET0, "solar_mj_m2": 22.07})
    assert result["et0_mm_day"] == pytest.approx(3.8796, rel=1e-3)
    assert result["rs_rso_limited"] is False
    assert result["rs_rso_ratio"] == pytest.approx(22.07 / clear_sky())


def test_et0_limits_small_clear_sky_excess_and_reports_it(tmp_path):
    rso = clear_sky()
    at_limit = reference_et0({**ET0, "solar_mj_m2": rso})
    registry, _, _ = build_registry()
    context = ToolExecutionContext("weather", tmp_path, ("HydroReferenceET0",), Settings(), Event())
    # Executor validation also checks the declared output schema.
    result = ToolExecutor(registry).execute(ToolCall("et0", "HydroReferenceET0", {**ET0, "solar_mj_m2": rso * 1.02}), context)
    assert result.status == "ok", result.error
    assert result.data["rs_rso_limited"] is True
    assert result.data["rs_rso_ratio"] == pytest.approx(1.02)
    # Only the longwave ratio is limited; net shortwave still uses measured Rs.
    assert result.data["net_radiation_mj_m2_day"] > at_limit["net_radiation_mj_m2_day"]
    assert result.data["et0_mm_day"] > at_limit["et0_mm_day"]


def test_et0_rejects_excess_beyond_tolerance():
    with pytest.raises(ScientificToolError, match="Rs/Rso >") as caught:
        reference_et0({**ET0, "solar_mj_m2": clear_sky() * (RS_RSO_TOLERANCE + .01)})
    assert caught.value.code == "invalid_arguments" and not caught.value.retryable


def test_catalog_owns_skill_names_and_descriptions():
    _, loader, _ = build_registry()
    summaries = {summary.id: summary for summary in loader.registry.list()}
    checked = 0
    for spec in catalog()["skills"]:
        skill_id = EXISTING_SKILLS.get(spec["id"], spec["id"].replace("-", "_"))
        text = (ROOT / spec["skill_file"]).read_text(encoding="utf-8").split("---", 2)[1]
        if "\ntools:" in text:
            # Documents declaring tools own their full summary (unchanged behavior).
            continue
        assert summaries[skill_id].name == spec["name"], skill_id
        assert summaries[skill_id].description == spec["description"], skill_id
        checked += 1
    assert checked == 27


def test_host_skill_descriptions_match_catalog():
    _, loader, _ = build_registry()
    summaries = {summary.id: summary for summary in loader.registry.list()}
    catalog_rows = {EXISTING_SKILLS.get(s["id"], s["id"].replace("-", "_")): s for s in catalog()["skills"]}
    for host in HOSTS:
        assert summaries[host].description == catalog_rows[host]["description"]
        assert ";" in summaries[host].description and "," in summaries[host].description


@pytest.mark.parametrize("query,expected", [
    ("statistic", "fractional_zonal_statistics"),
    ("rasters", "scientific_raster_analysis"),
    ("earthquakes", "earthquake_catalog_analysis"),
    ("catalogs", "earthquake_catalog_analysis"),
])
def test_search_folds_plural_and_inflected_forms(query, expected):
    _, loader, _ = build_registry()
    assert expected in {summary.id for summary in loader.registry.list(query)}


@pytest.mark.parametrize("query,expected", [
    ("interpolate rainfall stations to a grid", "scientific_raster_analysis"),
    ("evaluate hydrological model performance", "geological_table_analysis"),
    ("compute ET0 for a weather station", "climate_scenario_analysis"),
    ("convert wind speed and direction", "climate_scenario_analysis"),
    ("read a segy file", "earthquake_catalog_analysis"),
    ("fit an exponential curve", "geological_table_analysis"),
    ("计算参考蒸散发", "climate_scenario_analysis"),
    ("克里金插值", "spatial_kriging_interpolation"),
    ("水文模型评估", "geological_table_analysis"),
])
def test_natural_queries_rank_the_host_first(query, expected):
    _, loader, _ = build_registry()
    found = loader.registry.list(query)
    assert found and found[0].id == expected, [summary.id for summary in found[:3]]


def test_search_still_rejects_noise_queries():
    _, loader, _ = build_registry()
    assert not loader.registry.list("I / u v")
    assert not loader.registry.list("zzzzxyq")
    assert not loader.registry.list("nonexistent_litho_operation_xyz")
    assert not loader.registry.list("的")

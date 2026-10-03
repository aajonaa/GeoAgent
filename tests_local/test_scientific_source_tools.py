"""Synthetic acceptance fixtures only; never research observations or knowledge data."""
import csv
import importlib
import json
from pathlib import Path
from threading import Event

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from geological_agent.bootstrap import build_registry
from geological_agent.contracts import ToolCall
from geological_agent.settings import Settings
from geological_agent.tools import ToolExecutionContext, ToolExecutor
from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog, definition
from legacy.ToolsAgent.ToolsFuns.GeoEval.runtime import dispatch
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import (
    ScientificToolError, mann_kendall, ordinary_kriging_grid, exact_zonal_statistics,
)


@pytest.fixture
def point_args(tmp_path):
    path = tmp_path / "synthetic-points.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["x", "y", "value"])
        writer.writerows([(0, 0, 1), (2, 0, 3), (0, 2, 5), (2, 2, 7)])
    return {
        "points_path": str(path), "crs": "EPSG:32650", "value_unit": "ppm",
        "grid": {"xmin": -0.5, "ymin": -0.5, "xmax": 2.5, "ymax": 2.5, "width": 3, "height": 3},
        "variogram_model": "linear", "variogram_parameters": {"slope": 1, "nugget": 0},
    }


def rectangle(identifier, west, south, east, north):
    return {"type": "Feature", "properties": {"zone_id": identifier},
            "geometry": {"type": "Polygon", "coordinates": [
                [[west, south], [east, south], [east, north], [west, north], [west, south]]
            ]}}


def write_zones(path, features):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")


@pytest.fixture
def zone_args(tmp_path):
    raster_path = tmp_path / "synthetic-values.tif"
    with rasterio.open(raster_path, "w", driver="GTiff", width=2, height=2, count=1,
                       dtype="float64", crs="EPSG:32650", transform=from_origin(0, 2, 1, 1),
                       nodata=-9999) as raster:
        raster.write(np.array([[1., 3.], [5., -9999.]]), 1)
    path = tmp_path / "synthetic-zones.geojson"
    write_zones(path, [rectangle("full", 0, 0, 2, 2), rectangle("half", 0, 0, 0.5, 2),
                      rectangle("outside", 3, 3, 4, 4)])
    return {"raster_path": str(raster_path), "zones_path": str(path),
            "zones_crs": "EPSG:32650", "value_unit": "ppm"}


def test_mk_tie_variance_and_legacy_entry_are_identical():
    args = {"x": [1, 1, 2, 2, 3, 3]}
    direct = mann_kendall(args)
    legacy = dispatch("RemoteSensingMannKendallTest", args)
    assert direct == legacy
    assert direct["s"] == 12
    assert direct["variance_s"] == pytest.approx((510 - 54) / 18)
    assert direct["tau"] == pytest.approx(0.8)
    assert direct["significant"] is True


def test_mk_constant_series():
    result = mann_kendall({"x": [4] * 8})
    assert result["p_value"] == 1
    assert result["z"] == result["s"] == result["variance_s"] == result["slope"] == 0
    assert result["trend"] == "no trend"
    assert result["significant"] is False


def test_mk_time_unit_scaling():
    result = mann_kendall({"x": [1, 3, 5, 7, 9, 11], "sample_interval": 2,
                          "value_unit": "ppm", "time_unit": "year"})
    assert result["slope"] == pytest.approx(1)
    assert result["slope_unit"] == "ppm/year"


def test_mk_seasonal_slope_is_per_time_unit_not_cycle():
    result = mann_kendall({"x": [1, 10, 2, 11, 3, 12, 4, 13],
                          "method": "seasonal", "period": 2,
                          "value_unit": "mm", "time_unit": "month"})
    assert result["slope"] == pytest.approx(0.5)
    assert result["period"] == 2
    assert result["slope_unit"] == "mm/month"


@pytest.mark.parametrize("args", [
    {"x": [1, 2]}, {"x": [1, None, 3]}, {"x": [1, float("nan"), 3]},
    {"x": [True, 2, 3]}, {"x": [1, 2, 3], "alpha": 1},
    {"x": [1, 2, 3], "method": "seasonal"},
    {"x": [1, 2, 3, 4, 5, 6], "method": "original", "period": 2},
    {"x": [1, 2, 3, 4, 5, 6, 7], "method": "seasonal", "period": 2},
    {"x": [1, 2, 3, 4], "method": "seasonal", "period": 2},
])
def test_mk_invalid_inputs(args):
    with pytest.raises(ScientificToolError) as exc:
        mann_kendall(args)
    assert exc.value.code == "invalid_arguments"


def test_kriging_grid_georeferencing_exact_samples_and_no_overwrite(point_args, tmp_path):
    first = ordinary_kriging_grid(point_args, output_dir=tmp_path / "output")
    second = ordinary_kriging_grid(point_args, output_dir=tmp_path / "output")
    assert first["prediction_path"] != second["prediction_path"]
    assert first["variogram_fitted"] is False
    with rasterio.open(first["prediction_path"]) as raster:
        assert raster.shape == (3, 3)
        assert raster.crs.to_epsg() == 32650
        assert raster.xy(0, 0) == (0, 2)
        array = raster.read(1)
        assert array[[0, 0, 2, 2], [0, 2, 0, 2]] == pytest.approx([5, 7, 1, 3])
        assert raster.tags(1)["unit"] == "ppm"
    with rasterio.open(first["variance_path"]) as raster:
        array = raster.read(1)
        assert array.min() >= 0
        assert array[[0, 0, 2, 2], [0, 2, 0, 2]] == pytest.approx([0, 0, 0, 0], abs=1e-9)
    assert first["sample_count"] == 4


@pytest.mark.parametrize("change,code", [
    ({"crs": "EPSG:4326"}, "invalid_crs"),
    ({"variogram_model": "spherical", "variogram_parameters": {"sill": 1, "range": 1, "nugget": 2}}, "invalid_arguments"),
    ({"variogram_parameters": {"nugget": 0}}, "invalid_arguments"),
    ({"x_field": "missing"}, "invalid_data"),
])
def test_kriging_rejects_bad_contract(point_args, tmp_path, change, code):
    point_args.update(change)
    with pytest.raises(ScientificToolError) as exc:
        ordinary_kriging_grid(point_args, output_dir=tmp_path / "output")
    assert exc.value.code == code


def test_kriging_rejects_duplicate_points(point_args, tmp_path):
    with Path(point_args["points_path"]).open("a", encoding="utf-8") as stream:
        stream.write("0,0,10\n")
    with pytest.raises(ScientificToolError, match="Duplicate"):
        ordinary_kriging_grid(point_args, output_dir=tmp_path / "output")


def test_kriging_rejects_reversed_bounds(point_args, tmp_path):
    point_args["grid"]["xmin"] = 10
    with pytest.raises(ScientificToolError) as exc:
        ordinary_kriging_grid(point_args, output_dir=tmp_path / "output")
    assert exc.value.code == "invalid_arguments"


def test_fractional_zonal_nodata_and_empty_zones(zone_args):
    result = exact_zonal_statistics(zone_args)
    full, half, empty = result["zones"]
    assert full["coverage_count"] == 3
    assert full["mean"] == 3
    assert full["coverage_weighted_sum"] == 9
    assert half["coverage_count"] == 1
    assert half["mean"] == 3
    assert half["valid_area_m2"] == 1
    assert half["minimum"] == 1 and half["maximum"] == 5
    assert empty["status"] == "no_valid_cells"
    assert empty["mean"] is None and empty["coverage_weighted_sum"] is None
    assert empty["valid_area_m2"] == 0


def test_zonal_respects_scale_and_offset(zone_args):
    with rasterio.open(zone_args["raster_path"], "r+") as raster:
        raster.scales = (2,)
        raster.offsets = (10,)
    result = exact_zonal_statistics(zone_args)
    assert result["zones"][0]["mean"] == 16
    assert result["raster_scale"] == 2 and result["raster_offset"] == 10


@pytest.mark.parametrize("change,code", [
    ({"zones_crs": "EPSG:4326"}, "invalid_crs"),
    ({"zones_crs": "EPSG:32649"}, "invalid_crs"),
    ({"band": 2}, "invalid_arguments"),
])
def test_zonal_rejects_mismatched_inputs(zone_args, change, code):
    zone_args.update(change)
    with pytest.raises(ScientificToolError) as exc:
        exact_zonal_statistics(zone_args)
    assert exc.value.code == code


def test_zonal_rejects_duplicate_ids(zone_args):
    write_zones(Path(zone_args["zones_path"]), [rectangle(1, 0, 0, 2, 2), rectangle("1", 0, 0, 1, 1)])
    with pytest.raises(ScientificToolError, match="unique"):
        exact_zonal_statistics(zone_args)


def test_zonal_rejects_unclosed_polygon(zone_args):
    feature = rectangle("broken", 0, 0, 1, 1)
    feature["geometry"]["coordinates"][0].pop()
    write_zones(Path(zone_args["zones_path"]), [feature])
    with pytest.raises(ScientificToolError) as exc:
        exact_zonal_statistics(zone_args)
    assert exc.value.code == "invalid_geometry"


def test_zonal_hole_excludes_pixel(zone_args):
    feature = rectangle("hole", 0, 0, 2, 2)
    feature["geometry"]["coordinates"].append([[0, 1], [0, 2], [1, 2], [1, 1], [0, 1]])
    # An interior hole must not touch the exterior: use a centred quarter-cell hole.
    feature["geometry"]["coordinates"][-1] = [[0.25, 1.25], [0.25, 1.75], [0.75, 1.75], [0.75, 1.25], [0.25, 1.25]]
    write_zones(Path(zone_args["zones_path"]), [feature])
    row = exact_zonal_statistics(zone_args)["zones"][0]
    assert row["coverage_count"] == pytest.approx(2.75)
    assert row["coverage_weighted_sum"] == pytest.approx(8.75)


def test_native_registry_and_skills_use_same_contracts():
    registry, skills, _ = build_registry()
    for name in ("GeoOrdinaryKrigingGrid", "GeoExactZonalStatistics", "RemoteSensingMannKendallTest"):
        spec = definition(name)
        native = registry.get(name).definition
        assert native.input_schema == spec["input_schema"] == spec["function_definition"]["function"]["parameters"]
        assert native.result_schema == spec["output_schema"]
        entry = spec["source_interface"]["entrypoint"]
        module, function = entry["callable"].split(":")
        assert callable(getattr(importlib.import_module(module), function))
    assert skills.load("spatial_kriging_interpolation").tool_names == ("GeoOrdinaryKrigingGrid",)
    assert skills.load("fractional_zonal_statistics").tool_names == ("GeoExactZonalStatistics",)
    assert "RemoteSensingMannKendallTest" in skills.load("remote_sensing_trend_distribution").tool_names
    assert "RemoteSensingMannKendallTest" not in [
        row["name"] for row in skills.source_statuses["remote_sensing_trend_distribution"]["unavailable_tools"]
    ]
    assert definition("DeepTimeInterpolateIDW")["source_interface"]["status"] == "blocked"
    assert definition("CCSInterpolateIDW")["source_interface"]["status"] == "blocked"


def test_runtime_chain_uses_real_kriging_artifacts(point_args, tmp_path):
    registry, _, _ = build_registry()
    names = ("GeoOrdinaryKrigingGrid", "GeoExactZonalStatistics")
    ctx = ToolExecutionContext("synthetic-chain", tmp_path, names, Settings(), Event())
    executor = ToolExecutor(registry)
    point_args["points_path"] = Path(point_args["points_path"]).name
    interpolated = executor.execute(ToolCall("call-krige", names[0], point_args), ctx)
    assert interpolated.status == "ok", interpolated.error
    assert len(interpolated.artifacts) == 2
    zones = tmp_path / "runtime-zones.geojson"
    write_zones(zones, [rectangle("whole", -.5, -.5, 2.5, 2.5)])
    aggregated = executor.execute(ToolCall("call-zonal", names[1], {
        "raster_path": interpolated.data["prediction_path"], "zones_path": zones.name,
        "zones_crs": "EPSG:32650", "value_unit": "ppm",
    }), ctx)
    assert aggregated.status == "ok", aggregated.error
    with rasterio.open(tmp_path / interpolated.data["prediction_path"]) as raster:
        expected = raster.read(1).mean()
    assert aggregated.data["zones"][0]["mean"] == pytest.approx(expected)
    assert aggregated.data["zones"][0]["coverage_count"] == 9


def test_runtime_error_retains_source_code(tmp_path):
    registry, _, _ = build_registry()
    name = "RemoteSensingMannKendallTest"
    ctx = ToolExecutionContext("synthetic-error", tmp_path, (name,), Settings(), Event())
    actual = ToolExecutor(registry).execute(ToolCall("bad-season", name, {
        "x": [1, 2, 3, 4, 5, 6], "method": "seasonal",
    }), ctx)
    assert actual.status == "error"
    assert actual.error.code == "invalid_arguments"

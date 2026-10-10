"""Explicit synthetic acceptance inputs. Never registered as real knowledge/data."""
import csv
import hashlib
import math
from pathlib import Path

CSV_FILES = {
    "nodes.csv": "node_index,latitude,longitude,moho_depth_km,lab_depth_km\nn1,0,0,30,100\nn2,0,1,35,110\n",
    "velocity.csv": "latitude,longitude,depth_km,dlnvs_percent\n0,0,100,-1.5\n0,1,100,2\n",
    "events.csv": "id,time,mag,depth,latitude,longitude\ne1,2020-01-01T00:00:00Z,4,10,0,0\ne2,2020-01-02T00:00:00Z,5,20,0,1\n",
    "joins.csv": "event_id,moho_depth_km,lab_depth_km,dlnvs_percent\ne1,30,100,-1.5\n",
    "paleo.csv": "age_kyr_bp,temp_anomaly_C\n0,0\n10,-2\n",
    "annual.csv": "year,temp_anomaly_C\n2020,1\n2022,3\n",
    "ssp.csv": "scenario,horizon_year,estimate_c,lower_c,upper_c\nSSP2-4.5,2050,2,1,3\n",
    "facilities.csv": "id,latitude,longitude,country,energy_source,capacity_mw\nF1,0,0,Synthetic,wind,20\nF2,0,1,Synthetic,coal,30\n",
    "minerals.csv": "id,latitude,longitude\nM1,0,0.5\nM2,0,1.5\n",
    "capacities.csv": "series,year,capacity_mw\nsolar,2020,20\nsolar,2022,30\nzero,2020,0\nzero,2022,10\n",
    "transition.csv": "country,year,renewable_capacity_mw,total_capacity_mw,population\nSynthetic,2022,20,50,1000000\n",
    "monthly.csv": "month,latitude,longitude,carbon\n2020-01,0,0,10\n",
    "profiles.csv": "expocode,station,depth_m,carbon\nC1,S1,0,10\nC1,S1,100,14\n",
    "qc.csv": "cruise,flag\nC1,2\nC1,2\nC1,9\n",
    "stations.csv": "station,latitude,longitude\nS1,0,0\nS2,0,1\n",
    "observations.csv": "time,latitude,longitude,carbon\n2020-01-01,0,0,10\n2020-06-01,0,1,14\n2021-01-01,10,10,90\n",
    "surface.csv": "id,latitude,longitude,carbon\ns1,0,0,10\ns2,10,10,20\n",
    "deep.csv": "id,latitude,longitude,carbon\nd1,0,0,14\n",
    "duplicates.csv": "station,depth_m,carbon\nS1,0,10\nS1,0,11\nS1,100,14\n",
    "points.csv": "latitude,longitude,value\n1.5,0.5,2\n0.5,1.5,8\n",
}

def create(workspace):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    root = Path(workspace) / "assets/recovered-examples"
    root.mkdir(parents=True, exist_ok=True)
    for name, text in CSV_FILES.items():
        (root / name).write_text(text, encoding="utf-8")
    (root / "README.txt").write_text("SYNTHETIC TEST INPUTS ONLY. Not observations or scientific ground truth.\n", encoding="utf-8")
    (root / "graph.ttl").write_text(
        '@prefix geo: <http://www.opengis.net/ont/geosparql#> .\n'
        '<urn:inside> geo:asWKT "POINT(0 0)"^^geo:wktLiteral .\n'
        '<urn:outside> geo:asWKT "POINT(2 2)"^^geo:wktLiteral .\n', encoding="utf-8")
    for name, values, dtype in (
        ("red", [[3, 6], [9, 12]], "float64"),
        ("green", [[1, 2], [3, 4]], "float64"),
        ("qa", [[0, 8], [32, 0]], "uint16"),
    ):
        with rasterio.open(root / (name + ".tif"), "w", driver="GTiff", height=2, width=2,
                           count=1, dtype=dtype, crs="EPSG:4326", transform=from_origin(0, 2, 1, 1)) as dst:
            dst.write(np.asarray(values, dtype=dtype), 1)
            dst.update_tags(acquisition_date="2020-01-01")
    return root

def usgs_fixture(params):
    # Tests explicitly replace the HTTP boundary; no production fallback.
    return {"type": "FeatureCollection", "features": [
        {"id": "test-event", "geometry": {"type": "Point", "coordinates": [1, 0, 10]},
         "properties": {"time": 1577836800000, "mag": 4, "place": "SYNTHETIC TEST EVENT"}}
    ]}

def oracle(name, response, workspace):
    import numpy as np
    import rasterio
    result = response["result"]
    data = result["data"]
    for src in result["sources"]:
        path = Path(workspace) / src["path"]
        assert path.stat().st_size == src["size_bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == src["sha256"]
    expected = {
        "DeepEarthQueryLITHO1": {"node_index": "n1", "value_km": 30, "distance_km": 0},
        "DeepEarthQuerySEMUCB": {"depth_km": 100, "dlnvs_percent": -1.5, "distance_km": 0},
        "DeepEarthSampleEventModels": {"moho_depth_km": 30, "lab_depth_km": 100, "dlnvs_percent": -1.5},
        "DeepEarthQueryUSGSCatalog": {"count": 2, "event_ids": ["e1", "e2"]},
        "GeoBigDataExecuteGeoSPARQL": {"count": 1, "rows": [{"s": "urn:inside"}]},
        "ClimateQueryDeepTime": {"sample_age_kyr_bp": 10, "temp_anomaly_c": -2},
        "ClimateQueryPresentMean": {"mean_temp_anomaly_c": 2, "n": 2, "missing_years": [2021]},
        "ClimateQueryFutureSSP": {"estimate_c": 2, "lower_c": 1, "upper_c": 3},
        "EnergyNearestFacility": {"id": "F1", "distance_km": 0},
        "EnergyNearestMineralSite": {"id": "M1", "distance_km": math.pi*6371.0088/360},
        "EnergyCapacityValue": {"capacity_mw": 30},
        "EnergyCapacityGrowth": {"absolute_growth_mw": 10, "percentage_growth": 50},
        "EnergyCountryRenewableSummary": {"total_capacity_mw": 20, "by_type": [{"energy_source": "wind", "capacity_mw": 20}]},
        "EnergyTransitionMetrics": {"renewable_share_percent": 40, "renewable_w_per_capita": 20},
        "EnergyRegionalOverlaySummary": {"facility_count": 2, "mineral_count": 1, "total_capacity_mw": 50},
        "OceanMonthlyGridValue": {"value": 10},
        "OceanProfileValue": {"value": 14},
        "OceanVerticalProfileDifference": {"surface_value": 10, "deep_value": 14, "deep_minus_surface": 4},
        "OceanCruiseQC": {"total_count": 3, "accepted_count": 2, "rejected_count": 1, "flag_counts": {"2": 2, "9": 1}},
        "OceanAnnualCarbonSummary": {"count": 2, "mean": 12},
        "OceanRegionalMapSummary": {"count": 2, "mean": 12},
        "OceanSurfaceDeepMatch": {"matched_count": 1, "unmatched_count": 1},
        "OceanProfileDeduplication": {"input_count": 3, "unique_count": 2, "duplicate_count": 1},
        "USGS 地震数据获取": {"count": 1, "possibly_limited": False},
        "地震事件地图可视化": {"event_count": 2},
    }
    if name in ("EnergyFacilityDistance", "EnergyMineralSiteDistance", "OceanStationDistance"):
        expected[name] = {"distance_km": math.pi*6371.0088/180}
    if name.endswith("InterpolateIDW"):
        expected[name] = {"shape": [2, 2], "observation_count": 2, "distinct_locations": 2}
    if name.endswith("RasterAlgebra"):
        expected[name] = {"mean": 15, "valid_pixels": 4}
    if name == "RemoteSensingNDTI":
        expected[name] = {"mean": .5, "valid_pixels": 4, "value_unit": "1"}
    if name == "RemoteSensingCloudMask":
        expected[name] = {"mean": 7.5, "valid_pixels": 2}
    for key, wanted in expected.get(name, {}).items():
        if isinstance(wanted, (float, int)) and not isinstance(wanted, bool):
            assert math.isclose(data[key], wanted, rel_tol=1e-9, abs_tol=1e-9), (name, key, data[key], wanted)
        else:
            assert data[key] == wanted, (name, key, data[key], wanted)
    if name == "DeepEarthGetUSGSEvent":
        assert data["event"]["id"] == "e1" and float(data["event"]["mag"]) == 4
    if name == "DeepEarthSampleEventModels":
        assert "not new model sampling" in data["sampling"]
    if name == "OceanSurfaceDeepMatch":
        assert data["matches"] == [{"surface_id": "s1", "deep_id": "d1", "distance_km": 0, "surface_value": 10, "deep_value": 14}]
    if name == "OceanProfileDeduplication":
        with (Path(workspace) / data["output_path"]).open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 2 and rows[0]["carbon"] == "10"
    if name.endswith(("RasterAlgebra", "InterpolateIDW")) or name in ("RemoteSensingNDTI", "RemoteSensingCloudMask"):
        with rasterio.open(Path(workspace) / data["output_path"]) as dst:
            pixels = dst.read(1)
            assert dst.crs.to_epsg() == 4326 and dst.shape == (2, 2)
            if name.endswith("InterpolateIDW"):
                assert pixels[0, 0] == 2 and pixels[1, 1] == 8
                assert np.isfinite(pixels).all() and np.all((pixels >= 2) & (pixels <= 8))
            elif name.endswith("RasterAlgebra"):
                np.testing.assert_allclose(pixels, [[6, 12], [18, 24]])
            elif name == "RemoteSensingNDTI":
                np.testing.assert_allclose(pixels, .5)
            else:
                np.testing.assert_allclose(pixels, [[3, np.nan], [np.nan, 12]], equal_nan=True)
    if name == "地震事件地图可视化":
        page = (Path(workspace) / data["html_path"]).read_text()
        assert "<script>" not in page and "&lt;script&gt;" in page
        assert "default-src 'none'" in page and "src=\"http" not in page
        from PIL import Image
        with Image.open(Path(workspace) / data["png_path"]) as image:
            assert image.width > 300 and image.height > 300
    if name == "USGS 地震数据获取":
        with (Path(workspace) / data["output_path"]).open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert rows[0]["id"] == "test-event" and float(rows[0]["depth"]) == 10
    assert name in expected or name == "DeepEarthGetUSGSEvent", "No scientific oracle for "+name

"""Independent numerical/content references for each spatial operation."""
import math
from pathlib import Path


def check(name, result, args, output_dir):
    import numpy as np

    def raster(relative):
        import rasterio
        with rasterio.open(Path(output_dir) / relative) as source:
            assert source.crs.to_epsg() == 32650
            assert source.transform.a == source.transform.e * -1
            return source.read(1)

    if name == "GeoPyshedsFlowAccumulation":
        values = raster(result["raster"])
        assert result["cell_count"] == 25
        assert values[-1, -1] == 25
        assert values.min() >= 1
    elif name == "GeoPywrWaterAllocation":
        np.testing.assert_allclose(result["allocations"], [5, 2], atol=1e-8)
        np.testing.assert_allclose(result["deficits"], [0, 2], atol=1e-8)
        assert math.isclose(result["supply_used"], 7, abs_tol=1e-8)
        assert math.isclose(result["unused_supply"], 0, abs_tol=1e-8)
    elif name == "GeoHoloViewsLineProfile":
        assert result["sample_count"] == 3
        assert result["statistics"] == {"minimum": 10, "maximum": 14, "mean": 12}
    elif name == "GeoGeoViewsPolygonMap":
        assert result["feature_count"] == 2
        assert result["statistics"] == {"minimum": 2, "maximum": 4, "mean": 3}
    elif name == "GeoHVPlotHexbin":
        assert result["point_count"] == 4 and result["gridsize"] == 5
    elif name == "GeoPanelDataReport":
        document = (Path(output_dir) / result["report"]).read_text(encoding="utf-8")
        assert result["row_count"] == 3 and result["column_count"] == 3
        assert "sample-a" in document and "sample-b" in document
        assert "<script>alert(1)</script>" not in document
        assert "lt;script" in document or "u0026lt;script" in document
        assert result["external_resources"] is False
    elif name == "GeoGeorastersBlockSum":
        np.testing.assert_allclose(raster(result["raster"]), [[14, 22], [46, 54]])
        assert result["source_shape"] == [4, 4] and result["target_shape"] == [2, 2]
    elif name == "GeoPygeoprocessingDistanceTransform":
        rows, columns = np.indices((5, 5))
        expected = np.hypot(rows-2, columns-2) * 10
        np.testing.assert_allclose(raster(result["raster"]), expected, rtol=1e-5, atol=1e-6)
        assert result["region_cell_count"] == 1
    elif name == "GeoLidarMedianFilter":
        assert raster(result["raster"])[2, 2] == 13
        assert result["kernel_size"] == 3
    elif name == "GeoGeemapBoundingPolygon":
        assert result["feature"] == {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[110,31],[110,30],[111,30],[111,31],[110,31]]]}}
    elif name == "GeoCollocatePressureMatch":
        assert result["index"] == 1 and result["pressure_pa"] == 80000 and result["value"] == 20
    elif name == "GeoSalemProjectCoordinates":
        np.testing.assert_allclose(result["x"], [0, 6378137*math.pi/180], rtol=1e-10, atol=1e-8)
        np.testing.assert_allclose(result["y"], [0, 0], atol=1e-8)
        assert result["axis_order"].startswith("x/y")
    else:
        raise AssertionError("No independent spatial reference: " + name)
    if "preview" in result:
        from PIL import Image
        with Image.open(Path(output_dir) / result["preview"]) as picture:
            pixels = np.asarray(picture.convert("RGB"))
            assert pixels.shape[0] >= 100 and pixels.shape[1] >= 100
            assert pixels.std() > 5
    if "vector" in result:
        import xml.etree.ElementTree as ET
        assert ET.parse(Path(output_dir) / result["vector"]).getroot().tag.endswith("svg")

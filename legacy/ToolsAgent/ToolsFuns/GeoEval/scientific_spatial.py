"""Bounded spatial operations with explicit scientific input requirements."""
from __future__ import annotations

import csv
import html
import json
import math
from pathlib import Path
import re


class UnsupportedOperation(ValueError):
    pass


class ScientificResultError(ValueError):
    pass


def _collection(path: Path):
    if path.suffix.casefold() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        features = []
        for row in rows:
            lon = next((row[key] for key in ("lon", "long", "longitude", "longitude_wgs84") if key in row), None)
            lat = next((row[key] for key in ("lat", "latitude", "latitude_wgs84") if key in row), None)
            if lon is None or lat is None:
                raise UnsupportedOperation("Point CSV requires explicit longitude and latitude columns")
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]}, "properties": row})
        value = {"type": "FeatureCollection", "features": features}
    else:
        value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("type") != "FeatureCollection" or not isinstance(value.get("features"), list):
        raise UnsupportedOperation("Expected a GeoJSON FeatureCollection")
    crs = value.get("crs", {}).get("properties", {}).get("name", "EPSG:4326")
    if str(crs).upper() not in {"EPSG:4326", "URN:OGC:DEF:CRS:OGC:1.3:CRS84", "CRS84"}:
        raise UnsupportedOperation("This vector operation requires WGS84 longitude/latitude GeoJSON")
    for feature in value["features"]:
        for lon, lat in _coordinates((feature.get("geometry") or {}).get("coordinates", [])):
            if not math.isfinite(lon) or not math.isfinite(lat) or not -180 <= lon <= 180 or not -90 <= lat <= 90:
                raise ValueError("Invalid longitude/latitude coordinate")
    return value


def _coordinates(value):
    if isinstance(value, (list, tuple)) and len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
        yield float(value[0]), float(value[1])
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _coordinates(child)


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def spherical_buffer(params, paths, output_root):
    if len(paths) != 1:
        raise UnsupportedOperation("Point buffering requires exactly one point layer")
    layer = _collection(paths[0])
    if not layer["features"] or any((row.get("geometry") or {}).get("type") != "Point" for row in layer["features"]):
        raise UnsupportedOperation("Point buffering requires a nonempty Point FeatureCollection")
    distances = params.get("buffer_distances_km") or [params.get("distance_km", params.get("buffer_km", 50))]
    distances = [float(value) for value in distances]
    if any(not math.isfinite(value) or not 0 < value <= 100 for value in distances):
        raise UnsupportedOperation("Spherical buffer radius must be positive and at most 100 km")
    features = []
    for row in layer["features"]:
        lon, lat = row["geometry"]["coordinates"][:2]
        if abs(lat) > 75:
            raise UnsupportedOperation("Spherical buffer contract is limited to abs(latitude)<=75 degrees")
        phi, lam = math.radians(lat), math.radians(lon)
        for distance in distances:
            angular = distance / 6371.0
            ring = []
            for index in range(128):
                theta = index * 2 * math.pi / 128
                phi2 = math.asin(math.sin(phi) * math.cos(angular) + math.cos(phi) * math.sin(angular) * math.cos(theta))
                lam2 = lam + math.atan2(math.sin(theta) * math.sin(angular) * math.cos(phi),
                                       math.cos(angular) - math.sin(phi) * math.sin(phi2))
                point = [math.degrees(lam2), math.degrees(phi2)]
                if not -180 <= point[0] <= 180:
                    raise UnsupportedOperation("Antimeridian-crossing buffers require a topology-aware implementation")
                ring.append(point)
            ring.append(ring[0])
            features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                             "properties": {**(row.get("properties") or {}), "buffer_km": distance}})
    output = output_root / "vector" / (paths[0].stem + "_spherical_buffer.geojson")
    _write_json(output, {"type": "FeatureCollection", "features": features})
    return {"buffer_output": str(output), "buffer_distances_km": distances, "feature_count": len(features),
            "method": "128-segment spherical geodesic circle", "earth_radius_km": 6371.0,
            "implementation_kind": "approximate", "max_relative_chord_sagitta": 1 - math.cos(math.pi / 128)}


def _ring_location(x, y, ring):
    if len(ring) < 4 or ring[0][:2] != ring[-1][:2]:
        raise ValueError("Polygon rings must be closed and contain at least four coordinates")
    inside = False
    for start, end in zip(ring, ring[1:]):
        x1, y1 = start[:2]
        x2, y2 = end[:2]
        if abs(x2 - x1) > 180:
            raise UnsupportedOperation("Antimeridian-crossing polygon rings are unsupported")
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if abs(cross) <= 1e-12 and min(x1, x2) - 1e-12 <= x <= max(x1, x2) + 1e-12 and min(y1, y2) - 1e-12 <= y <= max(y1, y2) + 1e-12:
            return "boundary"
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return "inside" if inside else "outside"


def _polygon_covers(x, y, rings):
    outer = _ring_location(x, y, rings[0])
    if outer == "outside":
        return False
    if outer == "boundary":
        return True
    return not any(_ring_location(x, y, hole) == "inside" for hole in rings[1:])


def point_polygon_overlay(params, paths, output_root):
    if len(paths) != 2:
        raise UnsupportedOperation("Overlay requires exactly one point layer and one polygon layer")
    layers = [_collection(path) for path in paths]
    points = next((layer for layer in layers if layer["features"] and all(row["geometry"]["type"] == "Point" for row in layer["features"])), None)
    polygons = next((layer for layer in layers if layer["features"] and all(row["geometry"]["type"] in {"Polygon", "MultiPolygon"} for row in layer["features"])), None)
    if points is None or polygons is None:
        raise UnsupportedOperation("Only point-in-polygon overlay is implemented; polygon intersection requires a topology engine")
    joined = []
    for point_index, point in enumerate(points["features"]):
        lon, lat = point["geometry"]["coordinates"][:2]
        for zone_index, zone in enumerate(polygons["features"]):
            geometry = zone["geometry"]
            parts = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
            if any(_polygon_covers(lon, lat, part) for part in parts):
                joined.append({"type": "Feature", "geometry": point["geometry"], "properties": {
                    "point_index": point_index, "zone_index": zone_index,
                    "point_properties": point.get("properties") or {}, "zone_properties": zone.get("properties") or {}}})
    output = output_root / "vector" / (paths[0].stem + "_point_polygon_overlay.geojson")
    _write_json(output, {"type": "FeatureCollection", "features": joined})
    return {"overlay_output": str(output), "joined_count": len(joined), "tested_point_count": len(points["features"]),
            "tested_polygon_count": len(polygons["features"]), "boundary_rule": "covers (polygon and hole boundaries included)",
            "method": "point-in-polygon with interior rings; all memberships"}


def zonal_statistics(params, paths, output_root):
    import numpy as np
    operation = str(params.get("operation", params.get("statistic", "mean"))).casefold()
    if operation not in {"mean", "sum", "minimum", "maximum", "count"}:
        raise UnsupportedOperation("Supported zonal operations are mean, sum, minimum, maximum and count")
    raster_paths = [path for path in paths if path.suffix.casefold() in {".npy", ".tif", ".tiff"}]
    if raster_paths:
        if len(raster_paths) != 1 or raster_paths[0].suffix.casefold() == ".npy":
            raise UnsupportedOperation("Zonal raster statistics require one georeferenced GeoTIFF; raw NPY has no spatial transform")
        import rasterio
        from rasterio.features import geometry_mask
        from rasterio.warp import transform_geom
        zone_paths = [path for path in paths if path.suffix.casefold() in {".json", ".geojson"}]
        if len(zone_paths) != 1:
            raise UnsupportedOperation("Zonal statistics require an explicit polygon zone layer; global statistics are not zonal statistics")
        if len(paths) != 2:
            raise UnsupportedOperation("Zonal statistics require exactly one raster and one zone layer; extra sources are ambiguous")
        for key, expected in (("raster_path", raster_paths[0]), ("zones_path", zone_paths[0])):
            if params.get(key) is not None and Path(params[key]).expanduser().resolve() != expected.resolve():
                raise ValueError(f"{key} does not identify the declared input role")
        if params.get("zones_crs") and str(params["zones_crs"]).upper() not in {"EPSG:4326", "CRS84"}:
            raise UnsupportedOperation("zones_crs must agree with WGS84 GeoJSON coordinates")
        zones = _collection(zone_paths[0])["features"]
        if not zones or any(row["geometry"]["type"] not in {"Polygon", "MultiPolygon"} for row in zones):
            raise UnsupportedOperation("Zone layer must contain Polygon/MultiPolygon features")
        zone_field = params.get("zone_field", "zone_id")
        zone_ids = [(zone.get("properties") or {}).get(zone_field) for zone in zones]
        if (any(value is None or isinstance(value, (dict, list, bool)) or str(value).strip() == "" for value in zone_ids)
                or len(set(map(str, zone_ids))) != len(zone_ids)):
            raise ValueError("Every zone requires a unique nonempty identifier in zone_field")
        summaries = []
        with rasterio.open(raster_paths[0]) as dataset:
            if dataset.crs is None:
                raise UnsupportedOperation("Raster CRS is required for zonal statistics")
            if params.get("raster_crs") and rasterio.crs.CRS.from_user_input(params["raster_crs"]) != dataset.crs:
                raise ValueError("raster_crs does not match the selected raster")
            band = params.get("band")
            if band is None:
                if dataset.count != 1:
                    raise UnsupportedOperation("Multiband zonal statistics require an explicit band")
                band = 1
            if isinstance(band, bool) or not isinstance(band, int) or not 1 <= band <= dataset.count:
                raise ValueError("band must identify an existing raster band")
            tags = {**dataset.tags(), **dataset.tags(band)}
            for key in ("variable", "time", "year", "region"):
                if params.get(key) is not None and str(tags.get(key)) != str(params[key]):
                    raise ValueError(f"Selected raster has no matching {key} metadata")
            array = dataset.read(band, masked=True).astype("float64")
            array = array * dataset.scales[band - 1] + dataset.offsets[band - 1]
            for index, zone in enumerate(zones):
                geometry = transform_geom("EPSG:4326", dataset.crs, zone["geometry"])
                mask = geometry_mask([geometry], out_shape=array.shape, transform=dataset.transform, invert=True, all_touched=False)
                values = np.asarray(array.filled(np.nan))[mask & ~np.ma.getmaskarray(array)]
                values = values[np.isfinite(values)]
                if not values.size:
                    raise ValueError(f"Zone {index} has no finite covered raster cells")
                summaries.append({"zone_id": zone_ids[index],
                                  "count": int(values.size), "mean": float(values.mean()), "minimum": float(values.min()),
                                  "maximum": float(values.max()), "sum": float(values.sum())})
            raster_crs = str(dataset.crs)
        for summary in summaries:
            summary["statistic"] = operation
            summary["value"] = summary[operation]
        return {"source": str(raster_paths[0]), "zones_source": str(zone_paths[0]), "zone_statistics": summaries,
                "zone_count": len(summaries), "method": "pixel-center polygon mask", "area_weighted": False,
                "raster_crs": raster_crs, "zones_crs": "EPSG:4326", "band": band,
                "operation": operation, "zone_field": zone_field, "selected_metadata": tags}
    if len(paths) != 1 or paths[0].suffix.casefold() != ".csv" or not params.get("zone_field") or not params.get("value_field"):
        raise UnsupportedOperation("Tabular zonal statistics require one CSV and explicit zone_field/value_field")
    groups = {}
    with paths[0].open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            zone, value = row[params["zone_field"]], float(row[params["value_field"]])
            if not zone or not math.isfinite(value):
                raise ValueError("Zone identifiers and finite measured values are required")
            groups.setdefault(zone, []).append(value)
    if not groups:
        raise ValueError("No observations available for zonal statistics")
    summaries = [{"zone_id": zone, "count": len(values), "mean": sum(values)/len(values),
                  "sum": sum(values), "minimum": min(values), "maximum": max(values)}
                 for zone, values in groups.items()]
    for summary in summaries:
        summary.update(statistic=operation, value=summary[operation])
    return {"zone_statistics": summaries, "zone_count": len(groups), "operation": operation,
            "source": str(paths[0]), "zone_field": params["zone_field"], "value_field": params["value_field"],
            "method": "explicit table group aggregation"}


def render_spatial_map(params, paths, output_root):
    import numpy as np
    from PIL import Image, ImageDraw
    if not paths:
        raise UnsupportedOperation("Map rendering requires actual spatial input")
    if params.get("classification_field"):
        raise UnsupportedOperation("Classified cartographic rendering is not implemented; no placeholder legend will be produced")
    title = str(params.get("title", "Spatial data map"))
    image = Image.new("RGB", (1000, 700), "white")
    draw = ImageDraw.Draw(image)
    rasters = [path for path in paths if path.suffix.casefold() in {".npy", ".tif", ".tiff"}]
    feature_count = 0
    if rasters:
        if len(paths) != 1 or rasters[0].suffix.casefold() == ".npy":
            raise UnsupportedOperation("Raster rendering supports one georeferenced GeoTIFF; NPY or mixed layers need explicit spatial alignment")
        import rasterio
        with rasterio.open(rasters[0]) as dataset:
            if dataset.crs is None:
                raise UnsupportedOperation("A raster map requires an explicit CRS")
            if dataset.transform.b != 0 or dataset.transform.d != 0:
                raise UnsupportedOperation("Rotated raster grids require reprojection before rendering")
            array = dataset.read(1, masked=True).astype("float64")
            array = array * dataset.scales[0] + dataset.offsets[0]
            values = np.asarray(array.filled(np.nan))
            valid = np.isfinite(values)
            if not valid.any():
                raise ValueError("Cannot render a raster with no finite observations")
            low, high = float(values[valid].min()), float(values[valid].max())
            normalized = np.zeros_like(values)
            normalized[valid] = (values[valid] - low) / (high - low) if high != low else 0.5
            rgb = np.full((*values.shape, 3), 255, dtype="uint8")
            rgb[valid, 0] = np.asarray(normalized[valid]*230, dtype="uint8")
            rgb[valid, 1] = 80
            rgb[valid, 2] = np.asarray((1-normalized[valid])*230, dtype="uint8")
            patch = Image.fromarray(rgb)
            patch.thumbnail((880, 530))
            image.paste(patch, (60, 80))
            extent, crs = list(dataset.bounds), str(dataset.crs)
            render_info = {"finite_pixels": int(valid.sum()), "value_range": [low, high]}
    else:
        layers = [_collection(path) for path in paths]
        features = [feature for layer in layers for feature in layer["features"]]
        if any((row.get("geometry") or {}).get("type") not in {"Point", "LineString", "MultiLineString", "Polygon", "MultiPolygon"} for row in features):
            raise UnsupportedOperation("Unsupported geometry type for static rendering")
        coordinates = [point for row in features for point in _coordinates(row["geometry"]["coordinates"])]
        if not coordinates:
            raise ValueError("Cannot render an empty geometry collection")
        xs, ys = zip(*coordinates)
        extent, crs = [min(xs), min(ys), max(xs), max(ys)], "EPSG:4326"
        if extent[2] - extent[0] > 180:
            raise UnsupportedOperation("Antimeridian-spanning maps need projection handling")
        width, height = max(extent[2]-extent[0], 1e-6), max(extent[3]-extent[1], 1e-6)
        scale = min(840/width, 500/height)
        def pixel(point):
            return (80+(point[0]-extent[0])*scale, 600-(point[1]-extent[1])*scale)
        for feature in features:
            geometry = feature["geometry"]
            kind, coords = geometry["type"], geometry["coordinates"]
            if kind == "Point":
                x, y = pixel(coords)
                draw.ellipse((x-4, y-4, x+4, y+4), fill="#b91c1c")
            elif kind in {"LineString", "MultiLineString"}:
                for line in [coords] if kind == "LineString" else coords:
                    draw.line([pixel(point) for point in line], fill="#1d4ed8", width=3)
            else:
                for polygon in [coords] if kind == "Polygon" else coords:
                    for index, ring in enumerate(polygon):
                        draw.polygon([pixel(point) for point in ring], fill="#8bc4e8" if index == 0 else "white", outline="#1e3a5f")
        feature_count = len(features)
        render_info = {"feature_count": feature_count}
    draw.text((60, 20), title, fill="black")
    draw.text((60, 635), f"CRS: {crs}; extent: {extent}", fill="black")
    draw.text((60, 660), str(render_info), fill="black")
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", title).strip("_") or "spatial_map"
    directory = output_root / "maps"
    directory.mkdir(parents=True, exist_ok=True)
    png, webpage = directory/(stem+".png"), directory/(stem+".html")
    image.save(png)
    webpage.write_text(f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title><h1>{html.escape(title)}</h1><img src='{png.name}' alt='Rendered spatial input'><p>{html.escape(str(render_info))}</p>", encoding="utf-8")
    return {"map_png": str(png), "map_html": str(webpage), "title": title, "crs": crs, "extent": extent,
            "sources": list(map(str, paths)), "method": "static spatial data rendering", **render_info}

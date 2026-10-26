"""Contracts shared by the original implementations and the application.

The authoritative definitions live in catalog/registry.json. This module does
not dispatch to, wrap, or import asset_bridge or asset_catalog implementations.
"""

import copy
from functools import lru_cache
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def catalog():
    return json.loads((ROOT / "catalog/registry.json").read_text(encoding="utf-8"))


def definition(name):
    for entry in catalog()["tools"]:
        if entry["id"] == name:
            return entry
    raise ValueError("Unknown source tool: " + name)


def finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Nonfinite numeric values are not supported.")
    if isinstance(value, dict):
        for item in value.values():
            finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            finite(item)


def decode(value):
    """Decode transport JSON only; business functions operate on dictionaries."""
    if not isinstance(value, str):
        return value
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = item
        return result
    result = json.loads(value, object_pairs_hook=pairs)
    finite(result)
    return result


def arguments(name, value):
    spec = definition(name)
    status = spec.get("source_interface", {}).get("status")
    if status != "source_revised_unverified":
        raise NotImplementedError(spec.get("source_interface", {}).get("reason", "No source implementation contract."))
    value = decode(value)
    if not isinstance(value, dict):
        raise ValueError("Tool arguments must be a JSON object, not positional free text.")
    finite(value)
    Draft202012Validator(spec["input_schema"]).validate(value)
    value = copy.deepcopy(value)
    for key, field in spec["input_schema"].get("properties", {}).items():
        if key not in value and "default" in field:
            value[key] = copy.deepcopy(field["default"])
    if name.endswith("DecimalToDMS"):
        axis = value.get("axis", value.get("field"))
        if abs(value["value"]) > (90 if axis == "lat" else 180):
            raise ValueError("Coordinate exceeds the selected axis range.")
    if "bbox" in value:
        west, south, east, north = value["bbox"]
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError("Expected ordered WGS84 bounds without antimeridian crossing.")
    if name == "GeoWGS84BBoxAreaKm2":
        west, south, east, north = (value[k] for k in ("min_lon", "min_lat", "max_lon", "max_lat"))
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError("Expected ordered WGS84 bounds without antimeridian crossing.")
    if name.endswith("Bearing"):
        p1, p2 = math.radians(value["lat1"]), math.radians(value["lat2"])
        delta = math.radians(value["lon2"] - value["lon1"])
        cosine = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(delta)
        if abs(abs(cosine) - 1) < 1e-14:
            raise ValueError("Coincident or antipodal points do not define a unique bearing.")
    if name == "RemoteSensingDivision" and value["b"] == 0:
        raise ValueError("Division by zero.")
    if name == "RemoteSensingPercentageChange" and value["a"] == 0:
        raise ValueError("Percentage change from zero is undefined.")
    if name == "RemoteSensingCoefficientOfVariation" and math.fsum(value["x"]) == 0:
        raise ValueError("Coefficient of variation requires a nonzero mean.")
    if name == "RemoteSensingKurtosis" and len(set(value["x"])) < 2:
        raise ValueError("Kurtosis of a constant sequence is undefined.")
    if name == "RemoteSensingBatchNDSI" and len(value["green_file_list"]) != len(value["swir_file_list"]):
        raise ValueError("Green and SWIR lists must have equal lengths.")
    if name in ("DeepTimeZonalStatistics", "CCSZonalStatistics") and len(value["paths"]) == 1:
        if Path(value["paths"][0]).suffix.lower() != ".csv" or not value.get("value_field"):
            raise ValueError("Single-file zonal mode requires CSV and value_field.")
    return value


def result(name, value):
    value = decode(value)
    finite(value)
    if isinstance(value, dict) and (value.get("status") in ("error", "failed") or value.get("success") is False):
        raise RuntimeError(json.dumps(value, ensure_ascii=False))
    Draft202012Validator(definition(name)["output_schema"]).validate(value)
    if isinstance(value, dict) and value.get("skipped_layers"):
        raise ValueError("The required inputs were only partially processed.")
    return value


def check_files(name, value):
    """Scientific input checks belong to the source entry, not a second adapter."""
    spec = definition(name)
    paths = []
    for key in spec.get("source_interface", {}).get("path_fields", []):
        item = value[key]
        if key != "dir_path":
            paths.extend(item if isinstance(item, list) else [item])
    for path in paths:
        if not Path(path).is_file():
            raise ValueError("Input file does not exist: " + str(path))
    tiffs = [p for p in paths if Path(p).suffix.lower() in (".tif", ".tiff")]
    if name.startswith("RemoteSensing") and name != "RemoteSensingListFiles" and paths and len(tiffs) != len(paths):
        raise ValueError("This source profile requires single-band GeoTIFF input.")
    if tiffs:
        import numpy as np
        import rasterio
        grids = []
        for path in tiffs:
            with rasterio.open(path) as raster:
                if raster.count != 1 or raster.crs is None:
                    raise ValueError("Expected a single-band georeferenced GeoTIFF.")
                cells = raster.read(1, masked=True).compressed()
                if not cells.size or not np.isfinite(cells).all():
                    raise ValueError("No valid raster cells, or nonfinite unmasked cells.")
                if name == "RemoteSensingExtremeSnowLossPercentage" and not np.isin(cells, [0, 1]).all():
                    raise ValueError("Snow-loss input must already be a binary mask.")
                grids.append((raster.crs, raster.transform, raster.width, raster.height))
        if name.startswith("RemoteSensing") and any(grid != grids[0] for grid in grids[1:]):
            raise ValueError("Input raster grids differ; no implicit reprojection.")
    if name.startswith(("CCS", "DeepTime")) and name.endswith(
            ("StandardizeSpatialData", "BatchVector", "ValidateSpatialData", "NearestNeighbor", "Buffer")):
        for path in paths:
            data = decode(Path(path).read_text(encoding="utf-8-sig"))
            features = data.get("features", [])
            if data.get("type") != "FeatureCollection" or not features:
                raise ValueError("Expected a nonempty GeoJSON FeatureCollection.")
            crs = data.get("crs", {}).get("properties", {}).get("name", "EPSG:4326").upper()
            if crs not in ("EPSG:4326", "URN:OGC:DEF:CRS:OGC:1.3:CRS84", "CRS84"):
                raise ValueError("The source vector profile requires WGS84.")
            if name.endswith("NearestNeighbor") and len(features) < 2:
                raise ValueError("Nearest-neighbor calculation needs two or more points.")
            for feature in features:
                geometry = feature.get("geometry") or {}
                xy = geometry.get("coordinates", [])
                if geometry.get("type") != "Point" or len(xy) < 2:
                    raise ValueError("This source profile accepts points only.")
                if not (-180 <= xy[0] <= 180 and -90 <= xy[1] <= 90):
                    raise ValueError("Coordinates are outside WGS84 bounds.")


def validate_registration_metadata(spec):
    """Validate the additive asset metadata envelope without requiring provenance."""
    metadata = spec.get("registration_metadata")
    if not isinstance(metadata, dict):
        raise ValueError("Tool is missing registration_metadata: " + str(spec.get("id")))
    for key in ("provider", "license", "asset_version", "source_commit"):
        if key not in metadata:
            raise ValueError(f"Tool metadata is missing {key}: {spec.get('id')}")
    if metadata.get("metadata_profile") not in ("generic", "scientific"):
        raise ValueError("Invalid tool metadata_profile: " + str(spec.get("id")))
    protocol = metadata.get("official_protocol")
    if not isinstance(protocol, dict):
        raise ValueError("Tool metadata is missing official_protocol: " + str(spec.get("id")))
    applicability = protocol.get("applicability")
    if applicability not in ("applicable", "not_applicable", "unknown"):
        raise ValueError("Invalid official_protocol applicability: " + str(spec.get("id")))
    if applicability == "applicable" and (not protocol.get("name") or not protocol.get("version")):
        raise ValueError("Applicable protocol needs a name and version: " + str(spec.get("id")))
    if applicability != "applicable" and protocol.get("version") is not None:
        raise ValueError("Non-applicable or unknown protocol cannot have a version: " + str(spec.get("id")))
    runtime = metadata.get("runtime")
    if not isinstance(runtime, dict) or any(key not in runtime for key in (
            "python", "dependency_lock", "environment_version")):
        raise ValueError("Tool metadata has an incomplete runtime envelope: " + str(spec.get("id")))
    lifecycle = metadata.get("lifecycle")
    if not isinstance(lifecycle, dict) or any(key not in lifecycle for key in (
            "registration", "contract_validation", "unit_validation",
            "workflow_validation", "platform_validation", "release_status")):
        raise ValueError("Tool metadata has an incomplete lifecycle envelope: " + str(spec.get("id")))

"""Versioned, bounded scientific implementation audit; not an answer scorer."""
from __future__ import annotations

import math
import json
import re
from numbers import Real
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "scientific-tools-v1"

_SPATIAL = {
    "RenderMap": ("real", "GeoJSON geometry or one georeferenced GeoTIFF; static spatial rendering.", "No basemap or cartographic classification; unsupported formats fail."),
    "ZonalStatistics": ("real", "GeoTIFF plus explicit polygon zones with CRS, or table with explicit zone_field/value_field.", "Pixel-center membership; no fractional-cell area weighting. Missing zone definition fails."),
    "Buffer": ("approximate", "WGS84 lon/lat points; spherical radius 6371 km; radius 0-100 km; abs(latitude)<=75; no dateline crossing.", "128-segment spherical circle; chord sagitta <=0.031% radius. Ellipsoid error is not included in this discretization bound."),
    "Overlay": ("real", "WGS84 GeoJSON Point-in-Polygon/MultiPolygon, holes and boundaries; all matching polygon memberships.", "Planar GeoJSON ring semantics; antimeridian/polygon intersection unsupported without a topology engine."),
}
_REMOTE_REAL = {"RemoteSensingBatchImageMean", "RemoteSensingBatchImageSum", "RemoteSensingTiffAverage",
                "RemoteSensingBatchHotspotPercentage", "RemoteSensingCountAboveThreshold",
                "RemoteSensingNDVI", "RemoteSensingNDWI", "RemoteSensingNBR", "RemoteSensingBatchNDSI",
                "RemoteSensingNDTI", "RemoteSensingBatchHotspotRaster",
                "RemoteSensingTiffDifference", "RemoteSensingSubtract", "RemoteSensingFireIncreaseMap"}


def tool_scientific_contract(tool_name: str) -> dict[str, Any]:
    if tool_name in {"DeepTimeDecimalToDMS", "CCSDecimalToDMS"}:
        return {"tool_name": tool_name, "contract_version": CONTRACT_VERSION, "implementation_kind": "real",
                "review_status": "explicit_coordinate_Decimal_reference_audit", "formal_eligible": True,
                "audit_revision": "closure-explicit-dms-v1",
                "conditions": "Explicit finite decimal coordinate in latitude [-90,90] or longitude [-180,180]; axis lat/lon; DMS components normalized and checked against the supplied decimal value within 0.005 arcsecond.",
                "limitations": "Certifies coordinate arithmetic only, not real-world entity location, source-table lookup uniqueness or authenticity. Non-normalized seconds after rounding are rejected by result validation, not silently certified."}
    if tool_name == "RemoteSensingCloudMask":
        return {"tool_name": tool_name, "contract_version": CONTRACT_VERSION, "implementation_kind": "unreviewed",
                "review_status": "known_scientific_contract_gaps", "formal_eligible": None,
                "conditions": "Caller supplies reflectance and QA rasters; implementation uses fixed QA bits 3 and 4.",
                "limitations": "Product-specific QA semantics, QA NoData handling and matching-grid checks require repair and independent validation; execution success is not scientific certification."}
    for suffix, (kind, conditions, limitations) in _SPATIAL.items():
        if tool_name in {"DeepTime" + suffix, "CCS" + suffix}:
            return {"tool_name": tool_name, "contract_version": CONTRACT_VERSION, "implementation_kind": kind,
                    "review_status": "code_and_local_analytic_tests", "formal_eligible": True,
                    "conditions": conditions, "limitations": limitations}
    if tool_name in _REMOTE_REAL:
        return {"tool_name": tool_name, "contract_version": CONTRACT_VERSION, "implementation_kind": "real",
                "review_status": "bounded_raster_contract_audit", "formal_eligible": True,
                "conditions": "Finite raster data; explicit metadata scale/offset/nodata; matching grids for arithmetic.",
                "limitations": "No filename-inferred physical scale; validity does not establish task or reference correctness."}
    return {"tool_name": tool_name, "contract_version": CONTRACT_VERSION, "implementation_kind": "unreviewed",
            "review_status": "not_audited_in_this_batch", "formal_eligible": None,
            "conditions": "Consult the tool contract; this audit does not certify this implementation.", "limitations": "Unreviewed."}


def nonfinite_paths(value: Any, path: str = "$") -> list[str]:
    if isinstance(value, dict):
        return [item for key, child in value.items() for item in nonfinite_paths(child, path + "." + str(key))]
    if isinstance(value, (list, tuple)):
        return [item for index, child in enumerate(value) for item in nonfinite_paths(child, f"{path}[{index}]" )]
    if isinstance(value, Real) and not isinstance(value, bool):
        try:
            return [] if math.isfinite(value) else [path]
        except OverflowError:
            return [path]
    return []


_ARTIFACT_KEYS = {"output_path", "output_file", "raster_output", "average_raster", "buffer_output",
                  "overlay_output", "map_png", "map_html", "clean_output"}


def validate_scientific_result(tool_name: str, payload: Any) -> dict[str, Any]:
    """Validate numeric and explicit artifact evidence, without scoring answers."""
    errors = []
    if payload is None or payload == {} or payload == [] or payload == "":
        errors.append("Empty scientific result")
    errors.extend("Non-finite numeric result at " + path for path in nonfinite_paths(payload))
    if isinstance(payload, dict):
        metadata = payload.get("scientific_contract") or {}
        if metadata.get("implementation_kind") in {"placeholder", "mock"}:
            errors.append("Placeholder/mock output cannot establish scientific completion")
        if str(payload.get("status", "")).casefold() in {"unsupported", "placeholder", "mock", "inspection"}:
            errors.append("Operation did not execute a supported scientific implementation")
        if tool_name in {"CCSRenderMap", "DeepTimeRenderMap"} and not (payload.get("feature_count", 0) > 0 or payload.get("finite_pixels", 0) > 0):
            errors.append("A rendered map must identify the actual feature or pixel evidence")
        if tool_name in {"CCSZonalStatistics", "DeepTimeZonalStatistics"} and not payload.get("zone_statistics"):
            errors.append("Zonal statistics require explicit per-zone summaries")
        if tool_name in {"DeepTimeDecimalToDMS", "CCSDecimalToDMS"}:
            axis, decimal = payload.get("axis"), payload.get("decimal_degrees")
            coordinate_ok = (axis in {"lat", "lon"} and isinstance(decimal, Real) and not isinstance(decimal, bool)
                             and math.isfinite(decimal) and abs(decimal) <= (90 if axis == "lat" else 180))
            match = re.fullmatch(r'''(\d+)°(\d+)'(\d+(?:\.\d+)?)"\s*([NSEW])''', str(payload.get("dms", "")))
            normalized = False
            if match and coordinate_ok:
                degree, minute, second, hemisphere = match.groups()
                expected_hemisphere = ("S" if decimal < 0 else "N") if axis == "lat" else ("W" if decimal < 0 else "E")
                converted = int(degree) + int(minute) / 60 + float(second) / 3600
                normalized = (int(minute) < 60 and float(second) < 60 and hemisphere == expected_hemisphere
                              and abs(converted - abs(decimal)) <= .005 / 3600 + 1e-12)
            if not normalized:
                errors.append("DMS result must have a valid explicit lat/lon coordinate, normalized components and consistent hemisphere/value")

    def inspect(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in _ARTIFACT_KEYS and child is not None:
                    try:
                        path = Path(child)
                        if not path.is_file() or path.stat().st_size == 0:
                            errors.append(f"Missing or empty artifact: {key}={child}")
                        elif path.suffix.casefold() in {".tif", ".tiff"}:
                            import rasterio
                            import numpy as np
                            with rasterio.open(path) as source:
                                if not any(np.isfinite(source.read(1, window=window, masked=True).compressed()).any()
                                           for _, window in source.block_windows(1)):
                                    errors.append(f"Raster artifact has no finite observations: {child}")
                        elif path.suffix.casefold() == ".npy":
                            import numpy as np
                            if not np.isfinite(np.load(path, allow_pickle=False)).any():
                                errors.append(f"Raster artifact has no finite observations: {child}")
                        elif path.suffix.casefold() == ".png":
                            from PIL import Image
                            with Image.open(path) as image:
                                image.verify()
                        elif path.suffix.casefold() in {".json", ".geojson"}:
                            json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
                    except (OSError, ValueError, TypeError):
                        errors.append(f"Invalid artifact path: {key}={child}")
                inspect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                inspect(child)
    inspect(payload)
    return {"valid": not errors, "error_type": "scientific_result_error" if errors else None, "reasons": errors,
            "contract_version": CONTRACT_VERSION, "tool_name": tool_name}

"""Native scientific tools backed by upstream libraries, not delivery adapters.

Inputs and outputs use the shared catalog. These functions do not require an
LLM, LangGraph, a server or a user account. Third-party algorithms are imported,
not copied. See docs/SCIENTIFIC_TOOLS_BATCH1.md for attribution and scope.
"""
from __future__ import annotations

import csv
from functools import wraps
import hashlib
import importlib.metadata
import io
import json
import math
from pathlib import Path
import tempfile
import uuid

from jsonschema import ValidationError
from ..source_contracts import arguments, result, decode, finite


class ScientificToolError(ValueError):
    """Stable error code for direct callers and the native runtime."""

    def __init__(self, code, message, *, retryable=False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _fail(code, message):
    raise ScientificToolError(code, message, retryable=True)


def _source_operation(name):
    def decorate(function):
        @wraps(function)
        def execute(args, **kwargs):
            try:
                params = arguments(name, args)
            except (ValueError, TypeError, ValidationError) as exc:
                _fail("invalid_arguments", str(exc))
            try:
                payload = function(params, **kwargs)
                return result(name, payload)
            except ScientificToolError:
                raise
            except ModuleNotFoundError as exc:
                raise ScientificToolError(
                    "missing_dependency",
                    "Install requirements-source-tools.txt; missing " + str(exc.name),
                ) from exc
            except ValidationError as exc:
                raise ScientificToolError("invalid_result", str(exc)) from exc
            except OSError as exc:
                raise ScientificToolError("file_error", str(exc)) from exc
            except Exception as exc:
                raise ScientificToolError(
                    "scientific_execution_failed", f"{type(exc).__name__}: {exc}"
                ) from exc
        return execute
    return decorate


def _file(value):
    path = Path(value)
    if not path.is_file():
        _fail("missing_input", "Input file does not exist: " + str(path))
    return path


def _hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _versions(*names):
    return {name: importlib.metadata.version(name) for name in names}


def _metric_crs(value):
    from rasterio.crs import CRS
    try:
        crs = CRS.from_user_input(value)
    except Exception as exc:
        _fail("invalid_crs", "Cannot parse CRS: " + str(exc))
    if not crs.is_projected or not math.isclose(crs.linear_units_factor[1], 1.0, rel_tol=1e-12):
        _fail("invalid_crs", "This profile requires a projected CRS in metres; no implicit conversion.")
    return crs


@_source_operation("RemoteSensingMannKendallTest")
def mann_kendall(args):
    """Tie-corrected original or seasonal MK; one-dimensional regular samples."""
    import pymannkendall as mk

    values = args["x"]
    method = args["method"]
    period = args.get("period")
    if method == "original" and period is not None:
        _fail("invalid_arguments", "period is only applicable to method=seasonal.")
    if method == "seasonal":
        if period is None:
            _fail("invalid_arguments", "Seasonal MK requires an explicit period in samples.")
        if len(values) % period or len(values) < 3 * period:
            _fail("invalid_arguments", "Seasonal profile requires complete cycles and at least three cycles.")
        observed = mk.seasonal_test(values, period=period, alpha=args["alpha"])
        slope_interval = args["sample_interval"] * period
        independent_n = len(values) // period
    else:
        observed = mk.original_test(values, alpha=args["alpha"])
        slope_interval = args["sample_interval"]
        independent_n = len(values)
    warnings = [
        "The p-value uses the asymptotic normal approximation with ties and continuity correction.",
        "Serial dependence is not corrected by this profile; a significant trend is not a causal attribution.",
        "A nonsignificant test does not prove absence of a trend.",
    ]
    if independent_n < 10:
        warnings.append("Small sample: the asymptotic p-value may be unreliable; this is not an exact test.")
    return {
        "method": method, "n": len(values), "period": period,
        "alpha": args["alpha"], "trend": str(observed.trend),
        "significant": bool(observed.h), "p_value": float(observed.p),
        "z": float(observed.z), "tau": float(observed.Tau),
        "s": float(observed.s), "variance_s": float(observed.var_s),
        "slope": float(observed.slope) / slope_interval,
        "intercept": float(observed.intercept),
        "value_unit": args["value_unit"], "time_unit": args["time_unit"],
        "sample_interval": args["sample_interval"],
        "slope_unit": args["value_unit"] + "/" + args["time_unit"],
        "versions": _versions("pymannkendall", "numpy", "scipy"),
        "warnings": warnings,
    }


def _point_table(args):
    import numpy as np

    path = _file(args["points_path"])
    raw = path.read_bytes()
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        columns = [args["x_field"], args["y_field"], args["value_field"]]
        if len(set(columns)) != 3:
            _fail("invalid_data", "x_field, y_field and value_field must be different columns.")
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            _fail("invalid_data", "CSV requires unique column names.")
        if any(column not in reader.fieldnames for column in columns):
            _fail("invalid_data", "CSV is missing requested x/y/value columns.")
        rows = []
        for index, row in enumerate(reader, 2):
            try:
                values = [float(row[column]) for column in columns]
            except (ValueError, TypeError, KeyError):
                _fail("invalid_data", f"CSV row {index} has missing or nonnumeric values.")
            if not all(math.isfinite(value) for value in values):
                _fail("invalid_data", f"CSV row {index} contains a nonfinite value.")
            rows.append(values)
    except UnicodeError as exc:
        _fail("invalid_data", "CSV must be UTF-8: " + str(exc))
    if len(rows) < 3:
        _fail("invalid_data", "Two-dimensional interpolation requires at least three sample points.")
    points = np.asarray(rows, dtype=float)
    if len(np.unique(points[:, :2], axis=0)) != len(points):
        _fail("invalid_data", "Duplicate sample coordinates require an explicit scientific aggregation decision.")
    if np.linalg.matrix_rank(points[:, :2] - points[0, :2]) < 2:
        _fail("invalid_data", "Samples are collinear; a two-dimensional interpolation footprint is undefined.")
    return points, hashlib.sha256(raw).hexdigest()


@_source_operation("GeoOrdinaryKrigingGrid")
def ordinary_kriging_grid(args, *, output_dir):
    """Generate two georeferenced rasters using 2-D ordinary kriging."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds
    from pykrige.ok import OrdinaryKriging
    from scipy.spatial import Delaunay

    crs = _metric_crs(args["crs"])
    points, input_hash = _point_table(args)
    grid = args["grid"]
    west, south, east, north = (grid[k] for k in ("xmin", "ymin", "xmax", "ymax"))
    if west >= east or south >= north:
        _fail("invalid_arguments", "Grid bounds must satisfy xmin<xmax and ymin<ymax.")
    width, height = grid["width"], grid["height"]
    model = args["variogram_model"]
    parameters = args.get("variogram_parameters")
    if parameters is not None:
        expected = {"slope", "nugget"} if model == "linear" else {"sill", "range", "nugget"}
        if set(parameters) != expected:
            _fail("invalid_arguments", "Variogram parameters must contain exactly: " + ", ".join(sorted(expected)))
        if model == "linear":
            if parameters["slope"] <= 0:
                _fail("invalid_arguments", "The linear variogram slope must be positive.")
        elif parameters["range"] <= 0 or parameters["sill"] <= parameters["nugget"]:
            _fail("invalid_arguments", "Require range>0 and full sill>nugget>=0.")
    elif np.ptp(points[:, 2]) == 0:
        _fail("invalid_arguments", "A variogram cannot be estimated from constant values; supply justified parameters.")

    kriging = OrdinaryKriging(
        points[:, 0], points[:, 1], points[:, 2],
        variogram_model=model, variogram_parameters=parameters,
        nlags=args["nlags"], coordinates_type="euclidean",
        exact_values=True, pseudo_inv=False, verbose=False, enable_plotting=False,
    )
    dx, dy = (east - west) / width, (north - south) / height
    xs = west + (np.arange(width) + 0.5) * dx
    ys = south + (np.arange(height) + 0.5) * dy
    prediction, variance = kriging.execute("grid", xs, ys, backend="loop")
    prediction, variance = np.asarray(prediction, dtype=float), np.asarray(variance, dtype=float)
    if not np.isfinite(prediction).all() or not np.isfinite(variance).all():
        raise ScientificToolError("invalid_result", "Kriging produced nonfinite predictions or variances.")
    actual = list(map(float, kriging.variogram_model_parameters))
    fitted = ({"slope": actual[0], "nugget": actual[1]} if model == "linear" else
              {"sill": actual[0] + actual[2], "range": actual[1], "nugget": actual[2]})
    scale = max(float(np.var(points[:, 2])), max(map(abs, actual)), np.finfo(float).tiny)
    if np.any(variance < -1e-10 * scale):
        raise ScientificToolError("invalid_result", "Kriging produced materially negative variances.")
    clamped = int(np.count_nonzero(variance < 0))
    variance = np.maximum(variance, 0)
    hull = Delaunay(points[:, :2])
    extrapolated = sum(int(np.count_nonzero(
        hull.find_simplex(np.column_stack((xs, np.full(width, y)))) < 0
    )) for y in ys)
    warnings = [
        "Kriging variance is conditional on the selected variogram, not independently measured prediction error.",
        "This profile is isotropic, uses a planar metric CRS, and does not estimate anisotropy.",
        "Ordinary kriging builds a dense sample matrix; large sample sets can require substantial CPU memory.",
    ]
    if parameters is None:
        warnings.append("Variogram parameters were fitted by PyKrige; inspect the fit before scientific use.")
    if extrapolated:
        warnings.append(f"{extrapolated} grid centres are outside the sample convex hull.")
    if clamped:
        warnings.append(f"{clamped} tiny negative variances were clamped to zero within numerical tolerance.")
    if output_dir is None:
        _fail("invalid_arguments", "A caller-selected output_dir is required.")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / ("kriging-" + uuid.uuid4().hex)
    with tempfile.TemporaryDirectory(prefix=".kriging-", dir=root) as staging:
        profile = dict(driver="GTiff", width=width, height=height, count=1,
                       dtype="float64", crs=crs,
                       transform=from_bounds(west, south, east, north, width, height),
                       compress="deflate")
        for filename, array, quantity, unit in (
            ("prediction.tif", prediction, "prediction", args["value_unit"]),
            ("variance.tif", variance, "conditional_kriging_variance", "(" + args["value_unit"] + ")^2"),
        ):
            with rasterio.open(Path(staging) / filename, "w", **profile) as raster:
                raster.write(np.flipud(array), 1)
                raster.set_band_description(1, quantity)
                raster.update_tags(1, unit=unit)
                raster.update_tags(method="ordinary_kriging", variogram_model=model,
                                   variogram_parameters=json.dumps(fitted), input_sha256=input_hash)
        payload = {
            "method": "ordinary_kriging", "sample_count": len(points),
            "crs": crs.to_string(), "grid": grid,
            "prediction_path": str(destination / "prediction.tif"),
            "variance_path": str(destination / "variance.tif"),
            "value_unit": args["value_unit"], "variance_unit": "(" + args["value_unit"] + ")^2",
            "variogram_model": model, "variogram_parameters": fitted,
            "variogram_fitted": parameters is None, "outside_hull_cells": extrapolated,
            "prediction_min": float(prediction.min()), "prediction_max": float(prediction.max()),
            "variance_min": float(variance.min()), "variance_max": float(variance.max()),
            "input_path": args["points_path"], "input_sha256": input_hash,
            "versions": _versions("PyKrige", "numpy", "scipy", "rasterio"),
            "warnings": warnings,
        }
        # Validate before committing either output. Direct callers keep the same contract.
        result("GeoOrdinaryKrigingGrid", payload)
        Path(staging).rename(destination)
    return payload


def _zones(args, crs):
    from rasterio.crs import CRS
    from shapely.geometry import shape
    from shapely.validation import explain_validity

    path = _file(args["zones_path"])
    raw = path.read_bytes()
    try:
        collection = decode(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        _fail("invalid_data", "Invalid UTF-8 polygon JSON: " + str(exc))
    if not isinstance(collection, dict) or collection.get("type") != "FeatureCollection":
        _fail("invalid_data", "Zones must be a GeoJSON-like FeatureCollection.")
    features = collection.get("features")
    if not isinstance(features, list) or not features:
        _fail("invalid_data", "At least one polygon zone is required.")
    declared = collection.get("crs")
    if declared is not None:
        try:
            declared_crs = CRS.from_user_input(declared["properties"]["name"])
        except (KeyError, TypeError, ValueError):
            _fail("invalid_crs", "Invalid declared zone CRS.")
        if declared_crs != crs:
            _fail("invalid_crs", "zones_crs conflicts with the file's declared CRS.")
    output, identifiers = [], set()
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            _fail("invalid_data", f"Zone {index} is not a Feature.")
        properties = feature.get("properties")
        identifier = properties.get(args["zone_field"]) if isinstance(properties, dict) else None
        if isinstance(identifier, bool) or not isinstance(identifier, (str, int)) or str(identifier) == "":
            _fail("invalid_data", "Every zone needs a nonempty string or integer zone identifier.")
        identifier = str(identifier)
        if identifier in identifiers:
            _fail("invalid_data", "Zone identifiers must be unique after string conversion.")
        identifiers.add(identifier)
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon"):
            _fail("invalid_geometry", "Zones must contain Polygon or MultiPolygon geometry.")
        finite(geometry)
        polygons = [geometry.get("coordinates")] if geometry["type"] == "Polygon" else geometry.get("coordinates")
        if not isinstance(polygons, list) or not polygons:
            _fail("invalid_geometry", "Polygon coordinates are empty.")
        for polygon in polygons:
            if not isinstance(polygon, list) or not polygon:
                _fail("invalid_geometry", "Polygon rings are empty.")
            for ring in polygon:
                if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                    _fail("invalid_geometry", "Polygon rings must be explicitly closed with at least four positions.")
                for coordinate in ring:
                    if not isinstance(coordinate, list) or len(coordinate) != 2 or any(
                        isinstance(v, bool) or not isinstance(v, (int, float)) for v in coordinate
                    ):
                        _fail("invalid_geometry", "This profile requires finite 2-D numeric positions.")
        polygon = shape(geometry)
        if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
            _fail("invalid_geometry", "Invalid polygon; no silent repair: " + explain_validity(polygon))
        output.append({"type": "Feature", "properties": {"zone_id": identifier}, "geometry": geometry})
    return output, hashlib.sha256(raw).hexdigest()


@_source_operation("GeoExactZonalStatistics")
def exact_zonal_statistics(args):
    """Fractional-pixel coverage statistics; read-only, with explicit planar units."""
    import numpy as np
    import rasterio
    from exactextract import exact_extract
    from exactextract.feature import JSONFeatureSource
    from exactextract.operation import Operation
    from exactextract.raster import RasterioRasterSource

    path = _file(args["raster_path"])
    zones_crs = _metric_crs(args["zones_crs"])
    features, zones_hash = _zones(args, zones_crs)

    class CheckedRasterSource(RasterioRasterSource):
        def read_window(self, x0, y0, nx, ny):
            values = super().read_window(x0, y0, nx, ny)
            valid = values.compressed() if np.ma.isMaskedArray(values) else np.asarray(values).ravel()
            if not np.isfinite(valid).all():
                _fail("invalid_data", "Raster has nonfinite, unmasked values in an accessed window.")
            return values

    with rasterio.open(path) as raster:
        if raster.driver != "GTiff":
            _fail("invalid_data", "Only a local GeoTIFF is accepted; virtual/network datasets are not supported.")
        if raster.crs != zones_crs:
            _fail("invalid_crs", "Raster and polygons must share the explicit projected metric CRS.")
        band = args["band"]
        if band > raster.count:
            _fail("invalid_arguments", "band exceeds the raster band count.")
        transform = raster.transform
        if transform.b or transform.d or transform.a <= 0 or transform.e >= 0:
            _fail("invalid_data", "Use an axis-aligned north-up raster with positive pixel width.")
        if not (math.isfinite(raster.scales[band - 1]) and math.isfinite(raster.offsets[band - 1])):
            _fail("invalid_data", "Raster scale and offset must be finite.")
        if not raster.dtypes[band - 1].startswith(("uint", "int", "float")):
            _fail("invalid_data", "The selected raster band must be real-valued.")
        source = CheckedRasterSource(raster, band_idx=band)
        operations = [Operation(stat, field, source) for stat, field in (
            ("count", "coverage_count"), ("mean", "mean"),
            ("sum", "coverage_weighted_sum"), ("min", "minimum"), ("max", "maximum"),
        )]
        extracted = exact_extract(source, JSONFeatureSource(features, srs_wkt=zones_crs.to_wkt()),
                                  operations, include_cols=["zone_id"], output="geojson")
        pixel_area = abs(transform.a * transform.e)
        rows = []
        for feature in extracted:
            values = feature["properties"]
            coverage = float(values["coverage_count"])
            if not math.isfinite(coverage) or coverage < 0:
                raise ScientificToolError("invalid_result", "Invalid pixel coverage count.")
            row = {"zone_id": str(values["zone_id"]), "coverage_count": coverage,
                   "valid_area_m2": coverage * pixel_area,
                   "status": "ok" if coverage > 0 else "no_valid_cells"}
            for field in ("mean", "coverage_weighted_sum", "minimum", "maximum"):
                if coverage == 0:
                    row[field] = None
                else:
                    value = float(values[field])
                    if not math.isfinite(value):
                        raise ScientificToolError("invalid_result", "A populated zone has a nonfinite statistic.")
                    row[field] = value
            rows.append(row)
        if [row["zone_id"] for row in rows] != [f["properties"]["zone_id"] for f in features]:
            raise ScientificToolError("invalid_result", "Zone identities or ordering were not preserved.")
        scale, offset = float(raster.scales[band - 1]), float(raster.offsets[band - 1])
    return {
        "method": "fractional_pixel_coverage", "zone_count": len(rows), "zones": rows,
        "crs": zones_crs.to_string(), "band": args["band"], "value_unit": args["value_unit"],
        "pixel_area_m2": pixel_area, "raster_scale": scale, "raster_offset": offset,
        "raster_path": args["raster_path"], "raster_sha256": _hash(path),
        "zones_path": args["zones_path"], "zones_sha256": zones_hash,
        "versions": _versions("exactextract", "rasterio", "shapely", "numpy"),
        "warnings": [
            "Coverage count is the sum of valid pixel coverage fractions, not an integer pixel count.",
            "Area is measured in the supplied projected coordinate plane, not geodesic surface area.",
            "Coverage-weighted sum is not an area integral or a physical total without a matching quantity definition.",
            "Zones are independent and may overlap; do not add their areas or totals without checking overlap.",
            "NoData and masks are excluded. Zones without valid pixels return null statistics, not invented zeros.",
        ],
    }

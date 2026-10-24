"""Bounded source contracts; upstream algorithms remain in github_first_batch."""
from copy import deepcopy
from functools import wraps
import hashlib
from importlib import metadata
import json
import math
from pathlib import Path

from jsonschema import ValidationError
from legacy.ToolsAgent.ToolsFuns.source_contracts import arguments, definition, finite
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError

MAX_GRID_CELLS = 65536
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_PERMUTATION_WORK = 2_000_000


def _reject(message, code="invalid_arguments"):
    raise ScientificToolError(code, message)


def _validate(name, args, spec):
    keys = spec.get("constraints", {}).get("equal_length_arrays", [])
    if keys and len({len(args[key]) for key in keys}) != 1:
        _reject("Input arrays must have equal lengths")
    if name in {"GeoVerdeGrid", "HydroInterpolationGrid"}:
        xmin, xmax, ymin, ymax = args["region"]
        if not xmin < xmax or not ymin < ymax:
            _reject("region must be ordered xmin,xmax,ymin,ymax")
        points = list(zip(args["easting"], args["northing"]))
        if len(set(points)) != len(points):
            _reject("Duplicate point coordinates require an explicit upstream aggregation policy")
        if name == "GeoVerdeGrid":
            nx, ny = args["shape"]
        else:
            nx = math.ceil((xmax - xmin) / args["resolution"])
            ny = math.ceil((ymax - ymin) / args["resolution"])
        if nx * ny > MAX_GRID_CELLS:
            _reject("Requested grid exceeds 65,536 cells", "resource_limit")
    if name in {"HydroInterpolationGrid", "GeoVerdeGrid", "SpatialMoranI"}:
        crs = args.get("crs", "LOCAL_CARTESIAN")
        if crs != "LOCAL_CARTESIAN":
            from pyproj import CRS
            try:
                parsed = CRS.from_user_input(crs)
            except Exception:
                _reject("crs must identify a valid coordinate reference system")
            if name in {"GeoVerdeGrid", "SpatialMoranI"} and not parsed.is_projected:
                _reject("This Euclidean operation requires planar coordinates; no implicit reprojection")
    if name == "ScientificCurveFit":
        allowed = {"slope", "intercept"} if args["model"] == "linear" else {"amplitude", "decay"}
        if len(set(args["x"])) < 2:
            _reject("Fitting needs at least two distinct x values")
        for key in ("initial", "bounds"):
            if set(args.get(key, {})) - allowed:
                _reject("Unknown parameter for the selected model")
        for key, bounds in args.get("bounds", {}).items():
            if bounds.get("min", -math.inf) >= bounds.get("max", math.inf):
                _reject("Parameter bounds require min < max")
            initial = args.get("initial", {}).get(key)
            if initial is not None and not bounds.get("min", -math.inf) <= initial <= bounds.get("max", math.inf):
                _reject("Initial parameter lies outside its declared bounds")
    if name == "SpatialMoranI":
        count = len(args["values"])
        if args.get("k", 2) >= count:
            _reject("k must be smaller than the number of observations")
        if count * args.get("permutations", 0) > MAX_PERMUTATION_WORK:
            _reject("Requested permutation workload exceeds the bounded operation", "resource_limit")
        if len(set(zip(args["x"], args["y"]))) != count:
            _reject("Duplicate spatial coordinates require an explicit aggregation policy")
    if name == "SeismicSegySummary":
        path = Path(args["segy_path"])
        if not path.is_file():
            _reject("SEG-Y input file is missing", "missing_input")
        if path.stat().st_size > MAX_FILE_BYTES:
            _reject("SEG-Y input exceeds 256 MiB", "resource_limit")


def _units(name, args):
    unspecified = "unspecified; caller must supply units before scientific interpretation"
    value = args.get("value_unit", unspecified)
    if name == "GeoRegionMask":
        return {"longitude": "degree_east", "latitude": "degree_north", "region_ids": "SREX identifiers; not administrative units"}
    if name == "MetPyWindComponents":
        return {"speed": args.get("speed_unit", "m/s"), "direction": "degrees, meteorological from north", "u": "m/s", "v": "m/s"}
    if name == "HydroReferenceET0":
        return {"temperature": "degC", "humidity": "%", "wind": "m/s at 2 m", "radiation": "MJ/m2/day", "et0_mm_day": "mm/day"}
    if name == "SeismicReflectivity":
        return {"vp": "m/s", "density": "g/cm3", "coefficients": "dimensionless"}
    if name == "SeismicSegySummary":
        return {"sample_interval_us": "microsecond", "trace_mean_preview": "file-defined amplitude; not inferred"}
    if name == "HydroErrorMetrics":
        return {"rmse_mae": args.get("series_unit", unspecified), "nse_kge_pearson": "dimensionless"}
    if name == "ScientificCurveFit":
        return {"x": args.get("x_unit", unspecified), "y_rmse": args.get("y_unit", unspecified), "parameters": "derived from declared x/y units and model equation"}
    if name == "SpatialMoranI":
        return {"coordinates": args.get("coordinate_unit", unspecified), "moran_i": "dimensionless", "p_sim": "dimensionless; null means not calculated"}
    return {"coordinates": args.get("coordinate_unit", "CRS-defined for hydrointerp; otherwise unspecified"), "grid": value}


def bounded(name, function):
    """Make direct dict/JSON calls and native execution share the same contract."""
    @wraps(function)
    def call(args):
        payload = args
        try:
            if name == "HydroInterpolationGrid":
                from legacy.ToolsAgent.ToolsFuns.source_contracts import decode
                candidate = decode(payload)
                if isinstance(candidate, dict) and not candidate.get("crs"):
                    _reject("crs is required by hydrointerp; no implicit reprojection")
            args = arguments(name, payload)
            spec = definition(name)
            _validate(name, args, spec)
            output = function(deepcopy(args))
            finite(output)
            if output.get("success") is False:
                _reject("Fitting did not converge; no successful result is available", "non_convergence")
            canonical = deepcopy(args)
            for field in spec["source_interface"].get("path_fields", []):
                canonical[field] = {"sha256": hashlib.sha256(Path(args[field]).read_bytes()).hexdigest()}
            encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            upstream = spec["metadata"]["upstream"]
            versions = {}
            for package in (upstream["package"], "libpysal", "esda") if name == "SpatialMoranI" else (upstream["package"],):
                try:
                    versions[package] = metadata.version(package)
                except metadata.PackageNotFoundError:
                    versions[package] = None
            output["units"] = _units(name, args)
            output["provenance"] = {
                "tool": name,
                "source_url": upstream["url"],
                "declared_source_commit": spec["registration_metadata"]["source_commit"],
                "installed_versions": versions,
                "input_sha256": hashlib.sha256(encoded).hexdigest(),
                "implementation_sha256": hashlib.sha256(Path(function.__code__.co_filename).read_bytes()).hexdigest(),
                "crs": args.get("crs", "EPSG:4326" if name == "GeoRegionMask" else None),
                "reprojection_performed": False,
            }
            from jsonschema import Draft202012Validator
            try:
                Draft202012Validator(spec["output_schema"]).validate(output)
                json.dumps(output, allow_nan=False)
            except (ValidationError, ValueError, TypeError):
                _reject("Upstream output does not satisfy the result contract", "invalid_result")
            return output
        except ScientificToolError:
            raise
        except ModuleNotFoundError as exc:
            _reject("Install the pinned dependency set; missing module: " + str(exc.name), "missing_dependency")
        except FileNotFoundError:
            _reject("A declared input file is missing", "missing_input")
        except PermissionError:
            _reject("Input access denied", "invalid_path")
        except (ValidationError, ValueError, TypeError, KeyError):
            _reject("Arguments must match the declared schema, physical units and operation constraints")
        except MemoryError:
            _reject("Scientific operation exceeded memory availability", "resource_limit")
        except OSError:
            _reject("Scientific file could not be read with the declared format", "invalid_input")
    return call

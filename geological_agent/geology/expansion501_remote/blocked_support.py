"""Unregistered remote support kernels and bounded preflight contracts.

No public Tool entrypoint, process launcher, installation, or network operation.
This directory intentionally has no __init__.py: expansion501_remote.py remains
the entry module. Parent-owned isolated IPC and acceptance are still required.
"""
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET

MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_BUNDLE_BYTES = 512 * 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}")
SAFE = re.compile(
    r"(S1[AB])_IW_(SLC_|GRDH)_1S(SV|SH|DV|DH)_"
    r"(\d{8}T\d{6})_(\d{8}T\d{6})_\d{6}_[0-9A-F]{6}_[0-9A-F]{4}\.SAFE"
)
UNITS_CANOPY = {
    "wavelength": "nm", "pigment": "ug/cm2", "water_thickness": "cm",
    "dry_mass": "g/cm2", "angle": "deg", "reflectance": "dimensionless",
    "leaf_area_index": "m2/m2",
}


class ContractViolation(ValueError):
    """Preflight-only error; a future public adapter must map it through reject."""


def require(condition, message):
    if not condition:
        raise ContractViolation(message)


def closed(value, keys):
    require(isinstance(value, dict) and set(value) == set(keys),
            "Object must contain exactly its declared keys.")


def number(value, lo, hi):
    require(type(value) in (int, float) and math.isfinite(value)
            and lo <= value <= hi, "Expected a finite bounded real, not bool.")
    return value


def utc(value):
    require(isinstance(value, str) and
            re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value),
            "Acquisition time must be explicit UTC with whole-second precision.")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise ContractViolation("Invalid UTC calendar date/time.") from error


def tide_time(value):
    result = utc(value)
    # Reviewed PySolid solid.for declares its leap table expiry as 2025-12-28.
    # The half-open upper bound is conservative; no extrapolation is authorized.
    require(datetime(1972, 1, 1, tzinfo=timezone.utc) <= result <
            datetime(2025, 12, 28, tzinfo=timezone.utc),
            "Time is outside the reviewed PySolid leap-second-table interval.")
    return result


def relative_path(value):
    require(isinstance(value, str) and 1 <= len(value) <= 240 and
            not any(c in value for c in ("\\", ":", "\x00", "?", "#", "%")),
            "Only bounded plain POSIX workspace-relative paths are allowed.")
    path = PurePosixPath(value)
    require(not path.is_absolute() and all(p not in ("", ".", "..") for p in value.split("/")),
            "Absolute paths, traversal, and ambiguous path segments are forbidden.")
    return path


def file_record(value):
    closed(value, ("path", "sha256", "bytes", "role"))
    relative_path(value["path"])
    require(isinstance(value["sha256"], str) and SHA256.fullmatch(value["sha256"]),
            "Expected an explicit lowercase SHA-256.")
    require(type(value["bytes"]) is int and 1 <= value["bytes"] <= MAX_FILE_BYTES,
            "File size is outside the bounded profile.")
    require(value["role"] in {"manifest", "measurement", "annotation", "calibration",
                              "noise", "support", "grib", "timeseries", "geometry",
                              "mask", "stack", "components", "closure"},
            "Unknown scientific file role.")
    return value


def checked_path(root, record):
    file_record(record)
    root = Path(root)
    require(root.is_absolute() and root.is_dir() and not root.is_symlink(),
            "Input root must be an existing non-symlink private directory.")
    current = root
    for part in relative_path(record["path"]).parts:
        current = current / part
        require(not current.is_symlink(), "Symlink input components are forbidden.")
    require(current.is_file() and current.resolve().is_relative_to(root.resolve()),
            "Input is missing or escapes its private snapshot.")
    require(current.stat().st_size == record["bytes"], "Input size differs from manifest.")
    digest = hashlib.sha256()
    with current.open("rb") as handle:
        total = 0
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            total += len(block)
            require(total <= MAX_FILE_BYTES, "Input grew past its byte bound.")
            digest.update(block)
    require(total == record["bytes"] and digest.hexdigest() == record["sha256"],
            "Input content does not match its manifest.")
    return current


def xml_document(data):
    require(isinstance(data, bytes) and 1 <= len(data) <= 8 * 1024 * 1024,
            "XML exceeds the 8 MiB preflight limit.")
    # Reject UTF-16/NUL so declaration screening cannot be bypassed by encoding.
    require(b"\x00" not in data and b"<!DOCTYPE" not in data.upper()
            and b"<!ENTITY" not in data.upper(),
            "DTD/entity declarations and non-UTF8 XML are unsupported.")
    try:
        data.decode("utf-8-sig")
        root = ET.fromstring(data)
    except (ValueError, UnicodeDecodeError, ET.ParseError) as error:
        raise ContractViolation("Malformed UTF-8 XML.") from error
    require(sum(1 for _ in root.iter()) <= 100000, "XML node bound exceeded.")
    return root


def validate_safe_inventory(records, root, *, thermal_noise):
    """Hash/reference completeness preflight, NOT SAFE radiometric certification."""
    require(isinstance(records, list) and 5 <= len(records) <= 256,
            "A bounded original SAFE file inventory is required.")
    for record in records:
        file_record(record)
    names = [r["path"] for r in records]
    require(len(set(names)) == len(names), "Duplicate inventory paths.")
    require(sum(r["bytes"] for r in records) <= MAX_BUNDLE_BYTES,
            "SAFE subset exceeds the bounded snapshot size.")
    first = {PurePosixPath(name).parts[0] for name in names}
    require(len(first) == 1 and SAFE.fullmatch(next(iter(first))),
            "All files must belong to one supported original Sentinel-1 SAFE root.")
    roles = {r["role"] for r in records}
    require({"manifest", "measurement", "annotation", "calibration"} <= roles,
            "SAFE measurement, annotation, calibration, and manifest are required.")
    require(not thermal_noise or "noise" in roles, "Thermal correction requires original noise LUTs.")
    manifests = [r for r in records if r["role"] == "manifest"]
    require(len(manifests) == 1 and manifests[0]["path"].endswith("/manifest.safe"),
            "Exactly one original manifest.safe is required.")
    paths = {r["path"]: checked_path(root, r) for r in records}
    node = xml_document(paths[manifests[0]["path"]].read_bytes())
    base = PurePosixPath(manifests[0]["path"]).parent
    references = []
    for entry in node.iter():
        if entry.tag.rsplit("}", 1)[-1] == "fileLocation":
            href = entry.attrib.get("href", "")
            if href.startswith("./"):
                href = href[2:]
            references.append(str(base / relative_path(href)))
    require(references and len(references) == len(set(references)),
            "Missing or duplicate SAFE fileLocation references.")
    # No dropped sidecars or invented supplemental files.
    require(set(references) == set(names) - {manifests[0]["path"]},
            "Inventory must exactly cover the original manifest references.")
    for record in records:
        if record["role"] in {"annotation", "calibration", "noise"}:
            xml_document(paths[record["path"]].read_bytes())
    return {"file_count": len(records), "bytes": sum(r["bytes"] for r in records),
            "original_manifest_sha256": manifests[0]["sha256"],
            "scope": "hash_and_reference_preflight_only",
            "sensor_metadata_content_acceptance": "pending"}


def acquisitions(values):
    require(isinstance(values, list) and 2 <= len(values) <= 128,
            "Require 2..128 explicitly identified SAR acquisitions.")
    starts, sensors, coreg, polarizations = [], [], set(), set()
    for item in values:
        closed(item, ("product_id", "sensor", "start_utc", "stop_utc",
                      "polarization", "manifest_sha256", "coregistration_reference"))
        match = SAFE.fullmatch(item["product_id"]) if isinstance(item["product_id"], str) else None
        require(match is not None, "Only original Sentinel-1 IW SLC/GRDH product names are supported.")
        start, stop = utc(item["start_utc"]), utc(item["stop_utc"])
        require(0 < (stop - start).total_seconds() <= 600, "Invalid acquisition interval.")
        require(start.strftime("%Y%m%dT%H%M%S") == match[4] and
                stop.strftime("%Y%m%dT%H%M%S") == match[5], "SAFE filename/time mismatch.")
        require(item["sensor"] == match[1], "SAFE sensor identity mismatch.")
        allowed_pols = {"SV": {"VV"}, "SH": {"HH"}, "DV": {"VV", "VH"}, "DH": {"HH", "HV"}}
        require(item["polarization"] in allowed_pols[match[3]], "SAFE polarization mismatch.")
        require(isinstance(item["manifest_sha256"], str) and
                SHA256.fullmatch(item["manifest_sha256"]), "Missing original manifest hash.")
        require(isinstance(item["coregistration_reference"], str) and
                re.fullmatch(r"[A-Za-z0-9_-]{1,80}", item["coregistration_reference"]),
                "Explicit common coregistration reference required.")
        starts.append(start)
        sensors.append(item["sensor"])
        coreg.add(item["coregistration_reference"])
        polarizations.add(item["polarization"])
    require(starts == sorted(starts) and len({x.date() for x in starts}) == len(starts),
            "Require ascending, unique acquisition dates; same-day ambiguity is unsupported.")
    require(len(coreg) == len(polarizations) == 1, "Stack coregistration/polarization mismatch.")
    return starts, sensors


def grid(value):
    closed(value, ("crs", "affine", "shape", "mask", "nodata"))
    require(isinstance(value["crs"], str) and re.fullmatch(r"EPSG:[1-9]\d{3,5}", value["crs"]),
            "Explicit EPSG CRS required; worker must additionally resolve the CRS definition.")
    shape = value["shape"]
    require(isinstance(shape, list) and len(shape) == 2 and
            all(type(n) is int and 1 <= n <= 1024 for n in shape) and
            shape[0] * shape[1] <= 262144, "Raster shape exceeds the bounded profile.")
    affine = value["affine"]
    require(isinstance(affine, list) and len(affine) == 6, "Six affine coefficients required.")
    for item in affine:
        number(item, -1e9, 1e9)
    require(abs(affine[0] * affine[4] - affine[1] * affine[3]) > 1e-15,
            "Singular affine transformation.")
    mask = value["mask"]
    require(isinstance(mask, list) and len(mask) == shape[0] and
            all(isinstance(row, list) and len(row) == shape[1] for row in mask),
            "Mask dimensions must match the grid.")
    require(all(type(x) is bool for row in mask for x in row) and
            any(x for row in mask for x in row), "Require a nonempty boolean valid-data mask.")
    require(value["nodata"] is None, "This JSON contract uses null for NoData, never imputed zero.")
    return [x for row in mask for x in row]


def weather_inventory(records, acquisition_times, scene_bounds):
    """Descriptor preflight only; a future ecCodes stage must inspect actual GRIB."""
    require(isinstance(records, list) and len(records) == len(acquisition_times),
            "Require one explicitly matched weather slice per acquisition.")
    require(isinstance(scene_bounds, list) and len(scene_bounds) == 4, "Require [west,south,east,north].")
    west, south, east, north = scene_bounds
    for x, lo, hi in ((west, -180, 180), (east, -180, 180), (south, -90, 90), (north, -90, 90)):
        number(x, lo, hi)
    require(west < east and south < north, "Dateline crossing/reversed scene bounds unsupported.")
    times = [utc(x) for x in acquisition_times]
    require(times == sorted(set(times)), "Weather matching needs unique ordered acquisitions.")
    for record, instant in zip(records, times):
        closed(record, ("file", "valid_utc", "bounds", "pressure_levels_hpa",
                       "variables", "units", "data_license_url", "provider"))
        file_record(record["file"])
        require(record["file"]["role"] == "grib" and record["provider"] == "ECMWF_ERA5",
                "Only explicitly supplied local ERA5 GRIB is in scope.")
        require(utc(record["valid_utc"]) == instant and instant.minute == instant.second == 0,
                "Exact hourly acquisition/weather match required; no implicit nearest-hour weather.")
        bounds = record["bounds"]
        require(isinstance(bounds, list) and len(bounds) == 4, "Invalid weather bounds.")
        for x, lo, hi in zip(bounds, (-180, -90, -180, -90), (180, 90, 180, 90)):
            number(x, lo, hi)
        require(bounds[0] <= west < east <= bounds[2] and bounds[1] <= south < north <= bounds[3],
                "Weather does not cover the complete scene.")
        levels = record["pressure_levels_hpa"]
        require(isinstance(levels, list) and 3 <= len(levels) <= 137, "Pressure-level coverage missing.")
        for x in levels:
            number(x, 1, 1100)
        require(levels == sorted(set(levels)), "Pressure levels must be strictly ascending.")
        require(record["variables"] == ["geopotential", "specific_humidity", "temperature"] and
                record["units"] == {"geopotential": "m2/s2", "specific_humidity": "kg/kg",
                                     "temperature": "K", "pressure": "hPa"},
                "Weather variable/unit contract mismatch.")
        require(isinstance(record["data_license_url"], str) and
                record["data_license_url"].startswith("https://") and
                len(record["data_license_url"]) <= 500, "External weather data license must be declared.")
    return {"slices": len(records), "network_required": False,
            "grib_content_and_vertical_dem_coverage": "pending"}


def canopy_arguments(args):
    names = ("leaf_structure", "chlorophyll", "carotenoids", "brown_pigment",
             "water_thickness", "dry_mass", "anthocyanins", "leaf_area_index",
             "hotspot", "mean_leaf_angle", "solar_zenith", "view_zenith",
             "relative_azimuth", "diffuse_fraction", "soil_reflectance", "units")
    closed(args, names)
    ranges = {
        "leaf_structure": (1, 4), "chlorophyll": (0, 100), "carotenoids": (0, 30),
        "brown_pigment": (0, 1), "water_thickness": (0.000001, 0.1),
        "dry_mass": (0.000001, 0.05), "anthocyanins": (0, 40),
        "leaf_area_index": (0, 10), "hotspot": (0.000001, 1),
        "mean_leaf_angle": (1, 89), "solar_zenith": (0, 80),
        "view_zenith": (0, 80), "relative_azimuth": (0, 180), "diffuse_fraction": (0, 1),
    }
    for key, (lo, hi) in ranges.items():
        number(args[key], lo, hi)
    require(args["units"] == UNITS_CANOPY, "Explicit canopy physical units mismatch.")
    soil = args["soil_reflectance"]
    require(isinstance(soil, list) and len(soil) == 2101,
            "Require measured or explicitly synthetic soil reflectance at 400..2500 nm, 1 nm step.")
    for value in soil:
        number(value, 0, 1)
    return args


def exact_dependencies(pins):
    """Checks the interpreter actually executing a pending kernel, never the main env by proxy."""
    for package, expected in pins.items():
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError as error:
            raise ContractViolation("Missing private dependency: " + package) from error
        require(actual == expected, "Private dependency version mismatch: " + package)


def pending_canopy_kernel(args):
    """Real upstream composition; not registered, integrated, or scientifically tested.

    Parent must additionally bind the source commit and packaged spectral-library
    files. Version matching alone does not establish that identity.
    """
    canopy_arguments(args)
    exact_dependencies({"numpy": "2.1.3", "scipy": "1.15.3", "radiative-transfer-models": "1.6.2"})
    import numpy as np
    from pypro4sail import prospect, four_sail
    wl, rho, tau = prospect.prospectd(
        args["leaf_structure"], args["chlorophyll"], args["carotenoids"],
        args["brown_pigment"], args["water_thickness"], args["dry_mass"], args["anthocyanins"])
    wl, rho, tau = (np.asarray(x) for x in (wl, rho, tau))
    require(all(x.shape == (2101,) and np.isfinite(x).all() for x in (wl, rho, tau)),
            "Unexpected upstream leaf-spectrum shape or nonfinite result.")
    require(np.array_equal(wl, np.arange(400, 2501)), "Unexpected upstream wavelength axis.")
    require(np.all((rho >= 0) & (rho <= 1) & (tau >= 0) & (tau <= 1) &
                   (rho + tau <= 1 + 1e-7)), "Upstream leaf optics violate passivity.")
    lidf = four_sail.calc_lidf_campbell(args["mean_leaf_angle"], n_elements=18)
    result = four_sail.foursail(
        args["leaf_area_index"], args["hotspot"], lidf, args["solar_zenith"],
        args["view_zenith"], args["relative_azimuth"], rho, tau,
        np.asarray(args["soil_reflectance"], dtype=float))
    require(isinstance(result, (tuple, list)) and len(result) == 21,
            "Unexpected 4SAIL return structure.")
    # Documented pypro4sail.run composition, not a replacement for either kernel.
    direct, diffuse = np.asarray(result[17]), np.asarray(result[14])
    reflectance = diffuse * args["diffuse_fraction"] + direct * (1 - args["diffuse_fraction"])
    require(reflectance.shape == (2101,) and np.isfinite(reflectance).all()
            and (reflectance >= 0).all(), "Invalid upstream canopy spectrum.")
    # Directional reflectance factors are not probabilities; no false <=1 clipping.
    return {"wavelength_nm": wl.tolist(), "directional_reflectance_factor": reflectance.tolist(),
            "units": {"wavelength_nm": "nm", "directional_reflectance_factor": "dimensionless"},
            "source_status": "kernel_source_only_not_integrated",
            "formal_eligible": False}


def pending_s1ab_bias_kernel(args, private_work_dir):
    """Real MintPy pixelwise S1B-minus-S1A offset estimator, not yet a public Tool.

    The future fixed worker must first verify original SAFE metadata, copied
    geolocation/units, and native file contents. No IW subdivision is inferred.
    """
    closed(args, ("acquisitions", "grid", "range_offsets", "units", "representation"))
    dates, sensors = acquisitions(args["acquisitions"])
    mask = grid(args["grid"])
    require(args["units"] == {"range_offsets": "m"} and
            args["representation"] == "coregistered_range_offset_timeseries",
            "Require range offsets in metres, never optical RGB or phase.")
    require(set(sensors) == {"S1A", "S1B"}, "Both platforms are needed.")
    first_b = min(t for t, s in zip(dates, sensors) if s == "S1B")
    for sensor in ("S1A", "S1B"):
        require(sum(t >= first_b and s == sensor for t, s in zip(dates, sensors)) >= 3,
                "At least three acquisitions per platform in the shared fitting interval.")
    values = args["range_offsets"]
    require(isinstance(values, list) and len(values) == len(dates) and
            all(isinstance(row, list) and len(row) == len(mask) for row in values),
            "Range-offset data shape mismatch.")
    for row in values:
        for value, valid in zip(row, mask):
            if valid:
                number(value, -1000, 1000)
            else:
                require(value is None, "Masked values must remain null; no implicit imputation.")
    work = Path(private_work_dir)
    require(work.is_absolute() and work.is_dir() and not work.is_symlink()
            and not any(work.iterdir()), "Require an empty private worker directory.")
    exact_dependencies({"numpy": "2.1.3", "scipy": "1.15.3", "mintpy": "1.6.4"})
    import numpy as np
    from mintpy.utils.s1_utils import estimate_s1ab_bias
    for sensor in ("S1A", "S1B"):
        with (work / (sensor + "_date.txt")).open("x", encoding="ascii", newline="\n") as handle:
            handle.write("".join(t.strftime("%Y%m%d") + "\n" for t, s in zip(dates, sensors) if s == sensor))
    with (work / "SAFE_files.txt").open("x", encoding="ascii", newline="\n") as handle:
        handle.write("".join(a["product_id"] + "\n" for a in args["acquisitions"]))
    array = np.asarray([[x for x, valid in zip(row, mask) if valid] for row in values], dtype=float)
    result = estimate_s1ab_bias(str(work), array, safe_list_file=str(work / "SAFE_files.txt"))
    require(isinstance(result, (list, tuple)) and len(result) == 6 and result[0] is not None,
            "Upstream did not estimate an interplatform bias.")
    bias = np.asarray(result[0])
    require(bias.shape == (sum(mask),) and np.isfinite(bias).all(),
            "Invalid bias; upstream converts exact-zero estimates to NaN, which is unsupported here.")
    stream = iter(bias.tolist())
    full = [next(stream) if valid else None for valid in mask]
    return {"bias_m": full, "grid": args["grid"], "units": {"bias_m": "m"},
            "sign_convention": "S1B_minus_S1A", "source_status": "kernel_source_only_not_integrated",
            "formal_eligible": False}

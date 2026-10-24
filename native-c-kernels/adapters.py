"""Original CPU kernels behind a fixed, bounded JSON/dict interface.

No formulas replacing upstream algorithms, subprocesses, dynamic commands,
user-selected libraries, network, installation or compilation at tool time.
"""
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path

from specs import SPECS, VIC, FFT, HPGL

ROOT = Path(__file__).resolve().parent
POINTER = ctypes.POINTER(ctypes.c_double)


def fail(message, code="invalid_arguments"):
    from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError
    raise ScientificToolError(code, message, retryable=False)


def environment():
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "" or os.environ.get("NVIDIA_VISIBLE_DEVICES") != "none":
        fail("This fixed CPU entrypoint requires all GPU visibility disabled.", "execution_error")
    for key in ("MPLCONFIGDIR", "NUMBA_CACHE_DIR", "XDG_CACHE_HOME"):
        value = os.environ.get(key)
        if not value or not Path(value).resolve().is_relative_to(ROOT):
            fail("Private sidecar cache required: " + key, "execution_error")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parameters(name, value, args, output_dir):
    environment()
    if value is not None and args is not None:
        fail("Supply either the positional argument object or args=, not both.")
    value = args if args is not None else value
    if isinstance(value, str):
        if len(value.encode("utf-8")) > 262144:
            fail("JSON argument object exceeds 256 KiB.")
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            fail("Argument text must be a JSON object.")
    if not isinstance(value, dict):
        fail("Arguments must be a JSON object or dict.")
    if output_dir is not None:
        fail("This bounded kernel returns JSON and does not write artifacts.")
    schema = SPECS[name]["input_schema"]
    unknown = set(value) - set(schema["properties"])
    if unknown:
        fail("Unknown argument fields: " + ", ".join(sorted(map(str, unknown))))
    if set(schema["required"]) - set(value):
        fail("Missing required fields: " + ", ".join(sorted(set(schema["required"]) - set(value))))
    result = dict(value)
    for key, rule in schema["properties"].items():
        if key not in result:
            if "default" in rule:
                result[key] = rule["default"]
            else:
                continue
        item = result[key]
        kind = rule["type"]
        if kind == "array":
            if not isinstance(item, list) or not rule["minItems"] <= len(item) <= rule["maxItems"]:
                fail(key + " must be a bounded JSON array.")
            for element in item:
                finite_number(key, element, rule["items"])
        elif kind in ("number", "integer"):
            finite_number(key, item, rule)
            if kind == "integer" and (not isinstance(item, int) or isinstance(item, bool)):
                fail(key + " must be an integer.")
        elif kind == "string" and (not isinstance(item, str) or item not in rule["enum"]):
            fail(key + " must be an allowed enum value.")
    return result


def finite_number(key, item, rule):
    if isinstance(item, bool) or not isinstance(item, (int, float)):
        fail(key + " must contain finite numbers, not booleans or strings.")
    try:
        valid = math.isfinite(item)
    except (ValueError, OverflowError):
        valid = False
    if not valid or ("minimum" in rule and item < rule["minimum"]) or ("maximum" in rule and item > rule["maximum"]) or ("exclusiveMinimum" in rule and item <= rule["exclusiveMinimum"]):
        fail(key + " lies outside the finite physical/size constraint.")


def library(name):
    environment()
    receipt_path = ROOT / "build" / "build-receipt.json"
    if not receipt_path.is_file():
        fail("Native CPU preparation has not been completed.", "missing_dependency")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if digest(ROOT / "source-lock.json") != receipt["source_lock_sha256"]:
        fail("Source lock differs from prepared build.", "integrity_error")
    for relative, expected in receipt["input_sha256"].items():
        path = ROOT / relative
        if not path.is_file() or path.is_symlink() or digest(path) != expected:
            fail("Prepared native source/bridge integrity mismatch: " + relative, "integrity_error")
    path = ROOT / "build" / SPECS[name]["library"]
    if not path.is_file():
        fail("Fixed native library is missing: " + SPECS[name]["library"], "missing_dependency")
    if path.is_symlink() or digest(path) != receipt["output_sha256"][path.name]:
        fail("Fixed native library integrity mismatch.", "integrity_error")
    try:
        handle = ctypes.CDLL(str(path))
    except OSError as exc:
        fail("Prepared native ABI cannot load: " + str(exc), "missing_dependency")
    function = getattr(handle, SPECS[name]["symbol"])
    function.restype = ctypes.c_int
    return handle, function, receipt


def finish(name, args, result, receipt):
    lock = json.loads((ROOT / "source-lock.json").read_text(encoding="utf-8"))
    source = lock["projects"][str(SPECS[name]["project_id"])]
    result["provenance"] = {
        "tool": name, "source_mode": "original_native_kernel",
        "upstream_url": source["upstream_url"],
        "reviewed_archive_commit": source["reviewed_archive_commit"],
        "original_source_bytes_preserved": True,
        "source_sha256": {p: v["sha256"] for p, v in lock["files"].items() if v["project_id"] == SPECS[name]["project_id"]},
        "binary_sha256": receipt["output_sha256"][SPECS[name]["library"]],
        "build_receipt_sha256": digest(ROOT / "build" / "build-receipt.json"),
        "input_sha256": hashlib.sha256(json.dumps(args, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest(),
        "implementation_sha256": digest(Path(__file__)),
        "precision": SPECS[name]["precision"], "runtime_compile": False,
        "network_required": False, "gpu_required": False,
        "output_sha256": {},
    }
    return result


def check_code(code):
    if code:
        fail("Native kernel rejected input." if code == 1 else "Native kernel allocation/numerical failure: " + str(code), "invalid_arguments" if code == 1 else "execution_error")


def HydroVICPrecipitationPhase(value=None, *, args=None, output_dir=None):
    a = parameters(VIC, value, args, output_dir)
    t, p = a["air_temperature_c"], a["precipitation_mm"]
    n = len(t)
    if len(p) != n or a["max_snow_temperature_c"] <= a["min_rain_temperature_c"]:
        fail("Equal array lengths and max_snow_temperature_c > min_rain_temperature_c are required.")
    handle, fn, receipt = library(VIC)
    fn.argtypes = [ctypes.c_size_t, POINTER, POINTER, ctypes.c_double, ctypes.c_double, POINTER, POINTER]
    buffer = ctypes.c_double * n
    rain, snow = buffer(), buffer()
    check_code(fn(n, buffer(*t), buffer(*p), a["max_snow_temperature_c"], a["min_rain_temperature_c"], rain, snow))
    return finish(VIC, a, {"rain_mm": list(rain), "snow_mm": list(snow), "sample_count": n, "units": dict(SPECS[VIC]["units"])}, receipt)


def SeismicMadagascarFFT(value=None, *, args=None, output_dir=None):
    a = parameters(FFT, value, args, output_dir)
    samples = a["samples"]
    n = len(samples)
    handle, fn, receipt = library(FFT)
    fn.argtypes = [ctypes.c_size_t, POINTER, POINTER, POINTER]
    buffer = ctypes.c_double * n
    real, imaginary = buffer(), buffer()
    check_code(fn(n, buffer(*samples), real, imaginary))
    frequency = [(k if k <= (n-1)//2 else k-n) / (n*a["sampling_interval_s"]) for k in range(n)]
    return finish(FFT, a, {
        "frequency_hz": frequency, "real": list(real), "imaginary": list(imaginary),
        "amplitude_two_sided": [math.hypot(real[k], imaginary[k])/n for k in range(n)],
        "sample_count": n, "normalization": "Forward DFT unscaled; two-sided amplitude is abs(DFT)/N; no window/padding/detrending.",
        "units": {"frequency_hz": "Hz", "real": a["amplitude_unit"], "imaginary": a["amplitude_unit"], "amplitude_two_sided": a["amplitude_unit"]},
    }, receipt)


def GeoHPGLDirectionalSemivariogram(value=None, *, args=None, output_dir=None):
    a = parameters(HPGL, value, args, output_dir)
    n = len(a["values"])
    if any(len(a[k]) != n for k in ("x_m", "y_m", "z_m")) or a["lag_width_m"] > a["lag_separation_m"] or a["first_lag_m"] <= a["lag_width_m"]/2:
        fail("Equal sample lengths, non-overlapping positive lag bins are required.")
    handle, fn, receipt = library(HPGL)
    fn.argtypes = [ctypes.c_size_t, POINTER, POINTER, POINTER, POINTER, ctypes.c_int, ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_int, ctypes.c_double, POINTER]
    buffer = ctypes.c_double * n
    gamma = (ctypes.c_double * a["lag_count"])()
    check_code(fn(n, *(buffer(*a[k]) for k in ("x_m", "y_m", "z_m", "values")), "xyz".index(a["axis"]), a["lag_separation_m"], a["lag_width_m"], a["first_lag_m"], a["lag_count"], a["bandwidth_m"], gamma))
    return finish(HPGL, a, {
        "lag_center_m": [a["first_lag_m"]+k*a["lag_separation_m"] for k in range(a["lag_count"])],
        "semivariance": list(gamma), "sample_count": n,
        "empty_bin_policy": "Unchanged upstream returns 0 for empty bins and for equal-valued pairs; do not infer pair support from zero.",
        "units": {"lag_center_m": "m", "semivariance": "(" + a["value_unit"] + ")^2"},
        "distribution_license_review_required": True,
    }, receipt)


OPERATIONS = {VIC: HydroVICPrecipitationPhase, FFT: SeismicMadagascarFFT, HPGL: GeoHPGLDirectionalSemivariogram}


"""Independent scientific probe oracles. Never imported by a runtime tool."""
import cmath
import ctypes
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def close(values, expected, tolerance=2e-5):
    assert len(values) == len(expected)
    for value, target in zip(values, expected):
        assert math.isfinite(value) and abs(value-target) <= tolerance*max(1.0, abs(target))


def check(name, result, args, output_dir):
    profile = json.loads((ROOT/"geological_agent/geology/native-cpu-profiles.json").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT/"catalog/registry.json").read_text(encoding="utf-8"))
    spec = next(row for row in catalog["tools"] if row["id"] == name)
    normalized = dict(args)
    for key, rule in spec["input_schema"]["properties"].items():
        if key not in normalized and "default" in rule:
            normalized[key] = rule["default"]
    binding = profile["operations"][name]
    assert result.get("artifacts", []) == [] and output_dir is None
    proof = result["provenance"]
    assert proof["tool"] == name and proof["source_mode"] == "original_native_kernel"
    assert proof["binary_sha256"] == binding["binary_sha256"]
    assert proof["build_receipt_sha256"] == binding["build_receipt_sha256"]
    assert proof["input_sha256"] == hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert proof["gpu_used"] is False and proof["runtime_compile"] is False and proof["runtime_install"] is False
    assert proof["original_source_bytes_preserved"] is True
    implementation = ROOT/"geological_agent/geology/native_cpu_kernels.py"
    assert proof["implementation_sha256"] == hashlib.sha256(implementation.read_bytes()).hexdigest()
    lock = json.loads((Path(binding["root"])/"source-lock.json").read_text(encoding="utf-8"))
    project = spec["metadata"]["source_project_id"]
    assert proof["source_sha256"] == {p: v["sha256"] for p,v in lock["files"].items() if v["project_id"] == project}
    if name == "HydroVICPrecipitationPhase":
        t, p = args["air_temperature_c"], args["precipitation_mm"]
        high, low = normalized["max_snow_temperature_c"], normalized["min_rain_temperature_c"]
        expected = [0 if x <= low else y if x >= high else y*(x-low)/(high-low) for x,y in zip(t,p)]
        close(result["rain_mm"], expected, 1e-10)
        close(result["snow_mm"], [y-x for y,x in zip(p,expected)], 1e-10)
        close([r+s for r,s in zip(result["rain_mm"],result["snow_mm"])], p, 1e-10)
        assert result["units"] == {"rain_mm": "mm/time_step", "snow_mm": "mm/time_step", "air_temperature_c": "degree_Celsius"}
    elif name == "SeismicMadagascarFFT":
        samples = [ctypes.c_float(x).value for x in args["samples"]]
        n = len(samples)
        transform = [sum(x*cmath.exp(-2j*math.pi*k*t/n) for t,x in enumerate(samples)) for k in range(n)]
        close(result["real"], [z.real for z in transform])
        close(result["imaginary"], [z.imag for z in transform])
        close(result["amplitude_two_sided"], [abs(z)/n for z in transform])
        close(result["frequency_hz"], [(k if k <= (n-1)//2 else k-n)/(n*args["sampling_interval_s"]) for k in range(n)], 1e-10)
        assert result["units"] == {"frequency_hz": "Hz", "real": normalized["amplitude_unit"], "imaginary": normalized["amplitude_unit"], "amplitude_two_sided": normalized["amplitude_unit"]}
    elif name == "GeoHPGLDirectionalSemivariogram":
        primary = "xyz".index(normalized["axis"])
        points = [[ctypes.c_float(x).value for x in row] for row in zip(args["x_m"],args["y_m"],args["z_m"])]
        values = [ctypes.c_float(x).value for x in args["values"]]
        expected = []
        for lag in range(args["lag_count"]):
            center = args["first_lag_m"]+lag*args["lag_separation_m"]
            squared = []
            for i, first in enumerate(points):
                for j, second in enumerate(points):
                    delta = [first[k]-second[k] for k in range(3)]
                    transverse = math.sqrt(sum(delta[k]**2 for k in range(3) if k != primary))
                    distance = math.sqrt(sum(x*x for x in delta))
                    if delta[primary] >= 0 and transverse <= args["bandwidth_m"] and center-args["lag_width_m"]/2 <= distance < center+args["lag_width_m"]/2:
                        squared.append(ctypes.c_float(values[i]-values[j]).value**2)
            expected.append(sum(squared)/(2*len(squared)) if squared else 0)
        close(result["semivariance"], expected)
        close(result["lag_center_m"], [args["first_lag_m"]+k*args["lag_separation_m"] for k in range(args["lag_count"])], 1e-10)
        assert result["units"] == {"lag_center_m": "m", "semivariance": "("+normalized["value_unit"]+")^2"}
        assert result["distribution_license_review_required"] is True and "empty" in result["empty_bin_policy"]
    else:
        raise AssertionError("Unexpected native CPU probe operation")


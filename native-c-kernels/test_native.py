import copy
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest
import adapters
from checks import dft, directional_semivariogram
from fixtures import examples, harmonic_trace
from specs import SPECS, VIC, FFT, HPGL

ROOT = Path(__file__).resolve().parent


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Offline scientific operation attempted a network connection")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def test_private_cpu_environment():
    adapters.environment()
    assert os.environ["PROJ_NETWORK"] == "OFF"
    for key in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        assert os.environ[key] == "false"
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
        assert os.environ[key] == "1"


def test_original_sources_and_fixed_glue_unchanged():
    lock = json.loads((ROOT/"source-lock.json").read_text(encoding="utf-8"))
    receipt = json.loads((ROOT/"build/build-receipt.json").read_text(encoding="utf-8"))
    assert receipt["source_lock_sha256"] == adapters.digest(ROOT/"source-lock.json")
    assert set(lock["projects"]) == {"39", "86", "131"}
    for relative, item in lock["files"].items():
        assert adapters.digest(ROOT/relative) == item["sha256"]
        assert receipt["input_sha256"][relative] == item["sha256"]
        assert not (ROOT/relative).is_symlink()
    for relative, expected in receipt["input_sha256"].items():
        assert adapters.digest(ROOT/relative) == expected
    for name, expected in receipt["output_sha256"].items():
        assert adapters.digest(ROOT/"build"/name) == expected


@pytest.mark.parametrize("name", list(SPECS))
def test_three_interface_modes_input_immutability(name, monkeypatch):
    args = examples()[name]
    original = copy.deepcopy(args)
    def denied(*a, **kw):
        raise AssertionError("A tool attempted runtime compilation/installation/subprocess")
    monkeypatch.setattr(subprocess, "run", denied)
    operation = adapters.OPERATIONS[name]
    results = [operation(args), operation(json.dumps(args)), operation(args=args)]
    assert results[0] == results[1] == results[2]
    assert args == original
    result = results[0]
    assert result["provenance"]["original_source_bytes_preserved"] is True
    assert result["provenance"]["runtime_compile"] is False
    assert len(result["provenance"]["binary_sha256"]) == 64
    assert result["units"]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("name", list(SPECS))
def test_fixed_executable_matches_direct_call(name):
    args = examples()[name]
    child = subprocess.run([sys.executable, str(ROOT/"runner.py"), name], input=json.dumps(args), text=True, capture_output=True, env=dict(os.environ), timeout=30)
    assert child.returncode == 0, child.stderr + child.stdout
    result = json.loads(child.stdout)
    assert result["status"] == "ok"
    assert result["data"] == adapters.OPERATIONS[name](args)


@pytest.mark.parametrize("name", list(SPECS))
def test_unknown_fields_cannot_inject_commands(name):
    args = examples()[name]
    args["command"] = "touch /tmp/never-execute-this"
    with pytest.raises(Exception) as error:
        adapters.OPERATIONS[name](args)
    assert error.value.code == "invalid_arguments"
    assert error.value.retryable is False


@pytest.mark.parametrize("name", list(SPECS))
@pytest.mark.parametrize("bad", [None, [], "[]", "{broken", {"extra": 1}])
def test_invalid_argument_objects(name, bad):
    with pytest.raises(Exception) as error:
        adapters.OPERATIONS[name](bad)
    assert error.value.code == "invalid_arguments"


def test_fixed_executable_failure_exit_code():
    child = subprocess.run([sys.executable, str(ROOT/"runner.py"), "__import__('os')"], input="{}", text=True, capture_output=True, env=dict(os.environ), timeout=30)
    assert child.returncode == 2
    assert json.loads(child.stdout)["error"]["code"] == "invalid_arguments"


def test_vic_thresholds_and_mass_balance():
    args = examples()[VIC]
    result = adapters.HydroVICPrecipitationPhase(args)
    assert result["rain_mm"] == [0, 0, 5, 10, 10]
    assert result["snow_mm"] == [10, 10, 5, 0, 0]
    for p, rain, snow in zip(args["precipitation_mm"], result["rain_mm"], result["snow_mm"]):
        assert rain+snow == p
        assert 0 <= rain <= p and 0 <= snow <= p


@pytest.mark.parametrize("temp,prec,max_snow,min_rain,rain", [(-5, 12, 3, -1, 0), (1, 12, 3, -1, 6), (3, 12, 3, -1, 12), (0, 0, 2, -2, 0), (-1.999, 100, 2, -2, 0.025), (99, 1, 99, -99, 1)])
def test_vic_independent_numeric_cases(temp, prec, max_snow, min_rain, rain):
    result = adapters.HydroVICPrecipitationPhase({"air_temperature_c": [temp], "precipitation_mm": [prec], "max_snow_temperature_c": max_snow, "min_rain_temperature_c": min_rain})
    assert result["rain_mm"][0] == pytest.approx(rain, abs=1e-10)
    assert result["snow_mm"][0] == pytest.approx(prec-rain, abs=1e-10)


@pytest.mark.parametrize("field,bad", [("air_temperature_c", [float("nan")]), ("air_temperature_c", [True]), ("air_temperature_c", []), ("precipitation_mm", [-1]), ("precipitation_mm", [float("inf")]), ("max_snow_temperature_c", -1), ("min_rain_temperature_c", 1), ("air_temperature_c", [0]*4097), ("precipitation_mm", [1])])
def test_vic_invalid_domains(field, bad):
    args = examples()[VIC]
    args[field] = bad
    with pytest.raises(Exception) as error:
        adapters.HydroVICPrecipitationPhase(args)
    assert error.value.code == "invalid_arguments"


@pytest.mark.parametrize("n", [2, 3, 5, 7, 8, 15, 32, 64])
def test_fft_against_independent_dft_parseval_hermitian(n):
    args = harmonic_trace(n)
    result = adapters.SeismicMadagascarFFT(args)
    # The original engine consumes float32, so the oracle uses the exact
    # representable samples passed through the fixed ABI, not ideal inputs.
    samples = [ctypes.c_float(x).value for x in args["samples"]]
    expected = dft(samples)
    actual = [complex(r, i) for r, i in zip(result["real"], result["imaginary"])]
    assert actual == pytest.approx(expected, rel=2e-5, abs=2e-5)
    assert sum(abs(z)**2 for z in actual)/n == pytest.approx(sum(x*x for x in samples), rel=2e-5, abs=2e-5)
    for k in range(1, n):
        assert actual[k] == pytest.approx(actual[n-k].conjugate(), abs=2e-5)
    assert result["frequency_hz"] == pytest.approx([(k if k <= (n-1)//2 else k-n)/(n*args["sampling_interval_s"]) for k in range(n)])


def test_fft_impulse_and_sinusoidal_amplitudes():
    impulse = adapters.SeismicMadagascarFFT(examples()[FFT])
    assert impulse["real"] == [1]*8
    assert impulse["imaginary"] == [0]*8
    assert impulse["amplitude_two_sided"] == [0.125]*8
    result = adapters.SeismicMadagascarFFT(harmonic_trace())
    assert result["amplitude_two_sided"][0] == pytest.approx(2, abs=2e-6)
    assert result["amplitude_two_sided"][3] == pytest.approx(1.5, abs=2e-6)
    assert result["amplitude_two_sided"][5] == pytest.approx(0.25, abs=2e-6)


@pytest.mark.parametrize("field,bad", [("samples", [1]), ("samples", [1]*4097), ("samples", [True, 2]), ("samples", [1, float("nan")]), ("sampling_interval_s", 0), ("sampling_interval_s", 1e-9), ("amplitude_unit", "unknown")])
def test_fft_invalid_domains(field, bad):
    args = examples()[FFT]
    args[field] = bad
    with pytest.raises(Exception) as error:
        adapters.SeismicMadagascarFFT(args)
    assert error.value.code == "invalid_arguments"


@pytest.mark.parametrize("axis", ["x", "y", "z"])
def test_hpgl_original_variogram_known_profile(axis):
    args = examples()[HPGL]
    args["axis"] = axis
    args["x_m"], args[axis+"_m"] = args[axis+"_m"], args["x_m"]
    result = adapters.GeoHPGLDirectionalSemivariogram(args)
    assert result["semivariance"] == pytest.approx([0.5, 2, 4.5])
    assert result["semivariance"] == pytest.approx(directional_semivariogram(args))
    assert result["units"]["semivariance"] == "(g/t)^2"
    assert result["distribution_license_review_required"] is True


@pytest.mark.parametrize("bandwidth", [0.1, 1, 2])
def test_hpgl_search_geometry_and_empty_bin_policy(bandwidth):
    args = examples()[HPGL]
    args.update(x_m=[0, 1, 2, 3, 4], y_m=[0, 0, 1, 0, 2], z_m=[0]*5, values=[1, 2, 1, 4, 2], bandwidth_m=bandwidth, lag_count=6)
    result = adapters.GeoHPGLDirectionalSemivariogram(args)
    assert result["semivariance"] == pytest.approx(directional_semivariogram(args), rel=2e-6, abs=2e-6)
    assert result["semivariance"][-1] == 0
    assert "empty" in result["empty_bin_policy"]


@pytest.mark.parametrize("field,bad", [("x_m", [0]), ("y_m", [0]*513), ("values", [0, 1, float("inf"), 3]), ("axis", "latlon"), ("lag_count", True), ("lag_count", 65), ("lag_count", 1.5), ("lag_width_m", 2), ("first_lag_m", 0.1), ("bandwidth_m", 0), ("value_unit", "invented")])
def test_hpgl_invalid_domains(field, bad):
    args = examples()[HPGL]
    args[field] = bad
    with pytest.raises(Exception) as error:
        adapters.GeoHPGLDirectionalSemivariogram(args)
    assert error.value.code == "invalid_arguments"


@pytest.mark.parametrize("name", list(SPECS))
def test_no_library_path_or_compile_flag_exposed(name):
    props = SPECS[name]["input_schema"]["properties"]
    assert not {"code", "command", "library", "executable", "compiler", "output_dir"}.intersection(props)
    assert SPECS[name]["runtime_install"] is False
    assert SPECS[name]["runtime_compile"] is False


def test_direct_native_abi_rejects_unsafe_sizes():
    handle, fn, _ = adapters.library(VIC)
    fn.argtypes = [ctypes.c_size_t, adapters.POINTER, adapters.POINTER, ctypes.c_double, ctypes.c_double, adapters.POINTER, adapters.POINTER]
    one = (ctypes.c_double*1)(1)
    assert fn(0, one, one, 1, -1, one, one) == 1
    assert fn(1, one, one, -1, 1, one, one) == 1
    handle, fn, _ = adapters.library(FFT)
    fn.argtypes = [ctypes.c_size_t, adapters.POINTER, adapters.POINTER, adapters.POINTER]
    assert fn(1, one, one, one) == 1


"""Independent original-kernel physics and generic native ToolExecutor tests.

No collection catalog binding, whole Wflow engine or parent acceptance claim.
"""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
for name, suffix in (("MPLCONFIGDIR", "matplotlib"), ("NUMBA_CACHE_DIR", "numba"), ("XDG_CACHE_HOME", "xdg")):
    path = HERE / "cache/acceptance" / suffix
    path.mkdir(parents=True, exist_ok=True)
    os.environ[name] = str(path)
os.environ.update(CUDA_VISIBLE_DEVICES="", NVIDIA_VISIBLE_DEVICES="none", PROJ_NETWORK="OFF",
    LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false", GEOTOOL_LANGSMITH_ENABLED="0",
    OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1",
    NUMBA_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")

import ast
import copy
import hashlib
import importlib.abc
import importlib.metadata
import io
import json
import math
import socket
import subprocess
import sys
import unittest
from dataclasses import asdict
from threading import Event


class NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"torch", "transformers", "openai", "anthropic", "vllm"}:
            raise ImportError("Model imports forbidden during CPU acceptance")


def no_network(*args, **kwargs):
    raise RuntimeError("Network forbidden during CPU acceptance")


sys.meta_path.insert(0, NoModels())
socket.socket.connect = no_network
socket.socket.connect_ex = no_network
socket.create_connection = no_network
sys.path.insert(0, os.environ["WFLOW_HOST_CANDIDATE"])
from jsonschema import Draft202012Validator, ValidationError
from geological_agent.contracts import ToolCall
from geological_agent.tools import ToolExecutionContext
from geological_agent.settings import Settings
from kernel_adapter import NAME, SPEC, digest, get_backend, native_executor, reach_step

KEYS = tuple(SPEC["input_schema"]["required"])
CASES = {
    "zero": (0, 0, 0, 2, .6, 60, 100),
    "steady": (3, 3, 0, 1.5, .6, 600, 250),
    "linear_analytic": (2, 1, .0005, .02, 1, 60, 100),
    "recession": (0, 5, 0, 2, .6, 300, 100),
    "lateral_inflow": (.4, .2, .0001, 1.2, .6, 60, 500),
    "rising_inflow": (50, 1, 0, 2, .6, 600, 1000),
    "small_positive": (1e-6, 2e-6, 0, 1e-5, .6, 1, 10000),
    "large_reach": (1000, 300, .001, 5, .6, 3600, 10000),
}
EVIDENCE = HERE / "evidence"
EVIDENCE.mkdir(exist_ok=True)


def oracle(args):
    qi, qo, q, alpha, beta, dt, dx = (float(args[k]) for k in KEYS)
    if qi + qo + q == 0:
        return 0.0
    if beta == 1:
        return ((dt / dx) * qi + alpha * qo + dt * q) / ((dt / dx) + alpha)
    target = dt / dx * qi + alpha * qo ** beta + dt * q
    lo, hi = 0.0, max(qo, qi + q * dx, 1e-30)
    for _ in range(180):
        mid = (lo + hi) / 2
        if dt / dx * mid + alpha * mid ** beta < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def check(args, result):
    Draft202012Validator(SPEC["output_schema"]).validate(result)
    qi, qo, q, alpha, beta, dt, dx = (float(args[k]) for k in KEYS)
    out = result["outflow_m3_s"]
    reference = oracle(args)
    assert math.isclose(out, reference, rel_tol=1e-9, abs_tol=1e-10), (out, reference)
    residual = dx * alpha * (out ** beta - qo ** beta) + dt * (out - qi - q * dx)
    scale = max(1.0, abs(dx * alpha * qo ** beta) + abs(qi * dt) + abs(q * dx * dt),
                abs(dx * alpha * out ** beta) + abs(out * dt))
    tolerance = max(1e-12 * dx, 1e-10 * scale)
    assert abs(residual) <= tolerance, (residual, tolerance)
    assert math.isclose(result["continuity_tolerance_m3"], tolerance, rel_tol=1e-14)
    assert math.isclose(result["previous_storage_m3"], dx * alpha * qo ** beta, rel_tol=1e-14, abs_tol=1e-20)
    assert math.isclose(result["new_storage_m3"], dx * alpha * out ** beta, rel_tol=1e-14, abs_tol=1e-20)
    assert result["alpha_units"] == "m^(2-3*beta) s^beta" and result["beta_units"] == "1"
    assert result["artifacts"] == [] and result["provenance"]["output_sha256"] == {}
    assert result["provenance"]["source_mode"] == "vendored_source"
    assert result["provenance"]["installed_versions"] == {"numba": "0.68.0", "numpy": "2.1.3"}
    encoded = json.dumps(args, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    assert result["provenance"]["input_sha256"] == hashlib.sha256(encoded).hexdigest()
    assert result["provenance"]["original_files_sha256"] == SPEC["source_receipt"]["files_sha256"]
    assert result["provenance"]["adapter_sha256"] == digest(HERE / "kernel_adapter.py")
    assert result["provenance"]["collection_catalog_binding_accepted"] is False


def native(args, label):
    workspace = HERE / "workspaces" / label
    workspace.mkdir(parents=True, exist_ok=False)
    canary = workspace / "input-canary.txt"
    canary.write_bytes(b"immutable input evidence\n")
    before = digest(canary)
    result = native_executor().execute(ToolCall(label, NAME, args), ToolExecutionContext(
        "wflow-cpu", workspace, (NAME,), Settings(tool_timeout_seconds=0), Event()))
    assert digest(canary) == before
    (EVIDENCE / (label + ".json")).write_text(json.dumps(asdict(result), indent=2, allow_nan=False), encoding="utf-8")
    assert result.call_id == label and result.name == NAME
    return result


class Tests(unittest.TestCase):
    def test_original_ast_source_and_real_cpu_jit(self):
        original = ast.parse((HERE / "vendor/wflow_funcs.py").read_text(encoding="utf-8"))
        kernel = ast.parse((HERE / "vendor/original_kinematic_wave.py").read_text(encoding="utf-8"))
        find = lambda tree: next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "kinematic_wave")
        assert ast.dump(find(original), include_attributes=False) == ast.dump(find(kernel), include_attributes=False)
        for path, sha in SPEC["source_receipt"]["files_sha256"].items():
            assert digest(HERE / path) == sha
        from numba.core.registry import CPUDispatcher
        solver = get_backend()
        solver(3., 3., 0., 1.5, .6, 600., 250.)
        assert isinstance(solver, CPUDispatcher) and solver.nopython_signatures
        assert "torch" not in sys.modules and not any(n.startswith("numba.cuda") for n in sys.modules)
        (EVIDENCE / "jit.json").write_text(json.dumps({"type": type(solver).__name__,
            "nopython_signatures": [str(x) for x in solver.nopython_signatures],
            "original_function_AST_equal_including_decorator": True}), encoding="utf-8")

    def test_fixed_entry_success(self):
        args = dict(zip(KEYS, CASES["linear_analytic"]))
        env = os.environ.copy()
        workspace = HERE / "workspaces/fixed-success"
        workspace.mkdir(parents=True)
        env["WFLOW_WORKSPACE"] = str(workspace)
        proc = subprocess.run([sys.executable, str(HERE / "fixed_entry.py")], input=json.dumps(args),
                              text=True, capture_output=True, env=env)
        (EVIDENCE / "fixed-success.stdout.json").write_text(proc.stdout, encoding="utf-8")
        (EVIDENCE / "fixed-success.stderr.txt").write_text(proc.stderr, encoding="utf-8")
        assert proc.returncode == 0, proc.stderr
        result = json.loads(proc.stdout)
        assert result["status"] == "ok" and result["call_id"] == "wflow-fixed"
        check(args, result["data"])

    def test_fixed_entry_invalid_exit_propagation(self):
        args = dict(zip(KEYS, CASES["steady"]))
        args["reach_length_m"] = 0
        workspace = HERE / "workspaces/fixed-invalid"
        workspace.mkdir(parents=True)
        env = {**os.environ, "WFLOW_WORKSPACE": str(workspace)}
        proc = subprocess.run([sys.executable, str(HERE / "fixed_entry.py")], input=json.dumps(args),
                              text=True, capture_output=True, env=env)
        (EVIDENCE / "fixed-invalid.stdout.json").write_text(proc.stdout, encoding="utf-8")
        (EVIDENCE / "fixed-invalid.stderr.txt").write_text(proc.stderr, encoding="utf-8")
        assert proc.returncode == 1, (proc.returncode, proc.stderr)
        result = json.loads(proc.stdout)
        assert result["status"] == "error" and result["error"]["code"] == "invalid_arguments"

    def test_private_cpu_profile(self):
        packages = {}
        for name in ("numba", "llvmlite", "numpy", "jsonschema", "pydantic", "typing-extensions"):
            dist = importlib.metadata.distribution(name)
            packages[name] = {"version": dist.version, "root": str(dist.locate_file("")),
                              "METADATA_sha256": hashlib.sha256(dist.read_text("METADATA").encode()).hexdigest()}
        assert packages["numba"]["version"] == "0.68.0" and packages["numpy"]["version"] == "2.1.3"
        assert os.environ["CUDA_VISIBLE_DEVICES"] == "" and os.environ["NVIDIA_VISIBLE_DEVICES"] == "none"
        for key in ("MPLCONFIGDIR", "NUMBA_CACHE_DIR", "XDG_CACHE_HOME"):
            assert Path(os.environ[key]).is_relative_to(HERE)
        (EVIDENCE / "runtime-profile.json").write_text(json.dumps({"interpreter": sys.executable,
            "packages": packages, "environment": {k: os.environ[k] for k in (
                "CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES", "PROJ_NETWORK", "MPLCONFIGDIR",
                "NUMBA_CACHE_DIR", "XDG_CACHE_HOME", "NUMBA_NUM_THREADS", "OMP_NUM_THREADS")},
            "worker_bridge_used": False, "runtime_installs": False,
            "parent_latest_interpreter_checked": False}, indent=2), encoding="utf-8")


for label, values in CASES.items():
    for mode in ("dict", "json", "args"):
        def direct(self, values=values, mode=mode):
            args = dict(zip(KEYS, values))
            before = copy.deepcopy(args)
            if mode == "json": result = reach_step(json.dumps(args))
            elif mode == "args": result = reach_step(args=args)
            else: result = reach_step(args)
            assert args == before
            check(args, result)
        setattr(Tests, "test_direct_" + label + "_" + mode, direct)
    for mode in ("dict", "json"):
        def run_native(self, values=values, label=label, mode=mode):
            args = dict(zip(KEYS, values))
            before = copy.deepcopy(args)
            result = native(json.dumps(args) if mode == "json" else args, "native-" + label + "-" + mode)
            assert result.status == "ok", result.error
            assert result.artifacts == () and args == before
            check(args, result.data)
        setattr(Tests, "test_native_" + label + "_" + mode, run_native)

INVALIDS = {
    "negative_inflow": {"upstream_inflow_m3_s": -1},
    "negative_previous": {"previous_outflow_m3_s": -1},
    "negative_lateral": {"lateral_inflow_m2_s": -1},
    "zero_alpha": {"alpha": 0},
    "negative_beta": {"beta": -.5},
    "zero_dt": {"timestep_seconds": 0},
    "zero_dx": {"reach_length_m": 0},
    "boolean_flow": {"upstream_inflow_m3_s": True},
    "nonfinite": {"alpha": float("nan")},
    "unknown_argument": {"code": "not executable"},
    "dry_positive_lateral": {"upstream_inflow_m3_s": 0, "previous_outflow_m3_s": 0,
                             "lateral_inflow_m2_s": .01, "beta": .6},
}
for label, updates in INVALIDS.items():
    for mode in ("direct", "native"):
        def invalid(self, label=label, updates=updates, mode=mode):
            args = {**dict(zip(KEYS, CASES["steady"])), **updates}
            before = json.dumps(args, sort_keys=True)
            if mode == "direct":
                with self.assertRaises((ValueError, TypeError, ValidationError)): reach_step(args=args)
            else:
                result = native(args, "invalid-" + label)
                assert result.status == "error" and result.error.code == "invalid_arguments", result.error
            assert json.dumps(args, sort_keys=True) == before
        setattr(Tests, "test_invalid_" + label + "_" + mode, invalid)


def main():
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    (EVIDENCE / "unittest.log").write_text(stream.getvalue(), encoding="utf-8")
    failures = [{"test": str(test), "traceback": trace} for test, trace in result.failures + result.errors]
    receipt = {"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "skipped": len(result.skipped), "passed": result.wasSuccessful(), "failure_details": failures,
        "GPU_used": False, "models_used": False, "network_used_by_science": False,
        "native_ToolExecutor": True, "native_registration_kind": "explicit_private_prototype",
        "shared_collection_catalog_gate": "pending; no catalog integration acceptance claimed",
        "production_changed": False, "parent_candidate_changed": False,
        "original_project_count_delta": 0, "professional_tool_count_delta": 0,
        "full_engine_claimed": False, "requirements_profile": "R4 current interpreter only"}
    (EVIDENCE / "acceptance.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in receipt.items() if k != "failure_details"}))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

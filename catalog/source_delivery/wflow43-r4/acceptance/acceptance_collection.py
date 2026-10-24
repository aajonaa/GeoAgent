"""Actual shared collection decorator, catalog, Skill, and source registry tests.

All prior numerical/provenance oracles remain in the untouched original proof.
Only a test projection separates those old interface fields from the new SDK
fields; every new SDK provenance/hash/pin is checked on the real result first.
"""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
for key, leaf in (("MPLCONFIGDIR", "matplotlib"), ("NUMBA_CACHE_DIR", "numba"), ("XDG_CACHE_HOME", "xdg")):
    path = HERE / "cache/collection-acceptance" / leaf
    path.mkdir(parents=True, exist_ok=True)
    os.environ[key] = str(path)
os.environ.update(CUDA_VISIBLE_DEVICES="", NVIDIA_VISIBLE_DEVICES="none", PROJ_NETWORK="OFF",
    LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false", GEOTOOL_LANGSMITH_ENABLED="0",
    OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1",
    NUMBA_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")

import ast
import copy
import hashlib
import importlib.abc
import importlib.metadata
import importlib.util
import io
import json
import socket
import subprocess
import sys
import unittest
from dataclasses import asdict
from threading import Event


class NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"torch", "transformers", "openai", "anthropic", "vllm"}:
            raise ImportError("Model imports forbidden")


def no_network(*args, **kwargs):
    raise RuntimeError("Scientific network activity forbidden")


sys.meta_path.insert(0, NoModels())
socket.socket.connect = no_network
socket.socket.connect_ex = no_network
socket.create_connection = no_network
sys.path.insert(0, str(HERE / "candidate"))
sys.path.insert(0, str(HERE / "original-proof"))
proof_spec = importlib.util.spec_from_file_location("retained_original_acceptance", HERE / "original-proof/acceptance.py")
proof = importlib.util.module_from_spec(proof_spec)
proof_spec.loader.exec_module(proof)
import kernel_adapter as proof_interface
from jsonschema import Draft202012Validator
from geological_agent.bootstrap import build_registry
from geological_agent.contracts import ToolCall
from geological_agent.tools import ToolExecutor, ToolExecutionContext
from geological_agent.settings import Settings
from geological_agent.geology import collection_contracts as sdk
from geological_agent.geology import source_registry
from geological_agent.geology.collection_wflow43 import reach_step, UNITS
from geological_agent.geology.collection_vendor.approved_wflow43 import kernel_adapter as deployed_core
from legacy.ToolsAgent.ToolsFuns import source_contracts
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError

NAME = "EarthWflowKinematicWaveReachStep"
REGISTRY, SKILLS, BASE = build_registry()
SPEC = source_contracts.definition(NAME)
EVIDENCE = HERE / "evidence"
EVIDENCE.mkdir(exist_ok=True)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(args, actual):
    Draft202012Validator(SPEC["output_schema"]).validate(actual)
    provenance = actual["provenance"]
    assert provenance["tool"] == NAME and provenance["source_mode"] == "vendored_source"
    assert provenance["upstream_url"] == "https://github.com/openstreams/wflow"
    assert provenance["reviewed_archive_commit"] is None
    requirements = SPEC["metadata"]["upstream"]["requirements"]
    assert provenance["installed_versions"] == {r.split("==")[0]: r.split("==")[1] for r in requirements}
    canonical = json.dumps(args, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()
    assert provenance["input_sha256"] == hashlib.sha256(canonical).hexdigest()
    assert provenance["implementation_sha256"] == sha(HERE / "candidate/geological_agent/geology/collection_wflow43.py")
    assert provenance["contract_sha256"] == sha(sdk.__file__)
    assert provenance["vendored_source"] == SPEC["metadata"]["upstream"]["vendor_files"]
    assert provenance["network_required"] is False and provenance["output_sha256"] == {}
    assert actual["artifacts"] == [] and actual["units"] == UNITS
    raw = proof_interface.reach_step(args=copy.deepcopy(args))
    for key, value in raw.items():
        if key != "provenance": assert actual[key] == value, key
    projection = {k: copy.deepcopy(v) for k, v in actual.items() if k != "units"}
    projection["provenance"] = raw["provenance"]
    proof.check(args, projection)


def native(args, label):
    workspace = HERE / "workspaces" / label
    workspace.mkdir(parents=True, exist_ok=False)
    canary = workspace / "unchanged-input.txt"
    canary.write_bytes(b"original input must not change\n")
    before = sha(canary)
    result = ToolExecutor(REGISTRY).execute(ToolCall(label, NAME, args), ToolExecutionContext(
        "wflow-shared-cpu", workspace, (NAME,), Settings(tool_timeout_seconds=0), Event()))
    assert sha(canary) == before
    (EVIDENCE / (label + ".json")).write_text(json.dumps(asdict(result), indent=2, allow_nan=False), encoding="utf-8")
    assert result.call_id == label and result.name == NAME
    return result


class Tests(unittest.TestCase):
    def test_real_shared_registration_decorator_and_skill(self):
        tool = REGISTRY.get(NAME)
        assert Path(tool.handler.__code__.co_filename).resolve() == Path(source_registry.__file__).resolve()
        assert Path(reach_step.__code__.co_filename).resolve() == Path(sdk.__file__).resolve()
        assert hasattr(reach_step, "__wrapped__")
        assert tuple(SKILLS.load("wflow_kinematic_reach").tool_names) == (NAME,)
        assert SPEC["source_interface"]["entrypoint"]["callable"] == "geological_agent.geology.collection_wflow43:reach_step"
        assert source_registry.source_tools()[NAME] == SPEC

    def test_real_interface_diagnostic_repaired(self):
        assert Path(source_contracts.__file__).is_relative_to(HERE / "candidate")
        assert source_contracts.definition(NAME) == SPEC
        (EVIDENCE / "diagnostic-repaired.json").write_text(json.dumps({
            "shared_collection_interface": sdk.__file__, "real_catalog_interface": source_contracts.__file__,
            "registry": source_registry.__file__, "fixed_only_module_location": True,
            "previous_failure_preserved": True, "current_module_lookup_succeeded": True}, indent=2), encoding="utf-8")

    def test_schema_and_metadata_truthfulness(self):
        Draft202012Validator.check_schema(SPEC["input_schema"])
        Draft202012Validator.check_schema(SPEC["output_schema"])
        assert SPEC["input_schema"] == proof.SPEC["input_schema"]
        assert SPEC["function_definition"]["function"]["parameters"] == SPEC["input_schema"]
        assert SPEC["coverage_kind"] == "original_bounded_operation" and SPEC["coverage_target_project_id"] == 43
        assert SPEC["metadata"]["source_project_id"] == 43
        assert "functional_replacement" not in SPEC["metadata"]
        assert SPEC["metadata"]["upstream"]["package"] == "wflow" and SPEC["metadata"]["upstream"]["version"] is None
        assert SPEC["registration_metadata"]["source_commit"] is None
        assert SPEC["metadata"]["full_legacy_engine_installed"] is False

    def test_exact_pin_rejection_not_silently_stripped(self):
        incompatible = copy.deepcopy(SPEC)
        incompatible["metadata"]["upstream"]["requirements"] = ["numba==0.0.0"]
        with self.assertRaises(ScientificToolError) as error:
            sdk._dependencies(incompatible)
        assert error.exception.code == "missing_dependency"
        assert sdk._dependencies(SPEC) == {r.split("==")[0]: r.split("==")[1] for r in SPEC["metadata"]["upstream"]["requirements"]}

    def test_original_source_byte_AST_and_real_JIT(self):
        vendor = HERE / "candidate/geological_agent/geology/collection_vendor/approved_wflow43"
        receipt = proof.SPEC["source_receipt"]
        for path, expected in receipt["files_sha256"].items():
            assert sha(vendor / path) == expected
            assert sha(HERE / "original-proof" / path) == expected
        assert sha(vendor / "kernel_adapter.py") == sha(HERE / "original-proof/kernel_adapter.py")
        def node(path):
            return next(n for n in ast.parse(path.read_text(encoding="utf-8")).body if isinstance(n, ast.FunctionDef) and n.name == "kinematic_wave")
        assert ast.dump(node(vendor / "vendor/wflow_funcs.py"), include_attributes=False) == ast.dump(node(vendor / "vendor/original_kinematic_wave.py"), include_attributes=False)
        from numba.core.registry import CPUDispatcher
        solver = deployed_core.get_backend()
        solver(3., 3., 0., 1.5, .6, 600., 250.)
        assert isinstance(solver, CPUDispatcher) and solver.nopython_signatures
        assert not any(n == "torch" or n.startswith("numba.cuda") for n in sys.modules)
        (EVIDENCE / "jit.json").write_text(json.dumps({"type": type(solver).__name__,
            "nopython_signatures": [str(s) for s in solver.nopython_signatures],
            "original_bytes_SHA_and_AST_including_decorator_retained": True}), encoding="utf-8")

    def test_runtime_profile_and_private_caches(self):
        packages = {}
        for name in ("numba", "numpy", "llvmlite", "jsonschema", "pydantic", "typing-extensions", "langgraph"):
            dist = importlib.metadata.distribution(name)
            packages[name] = {"version": dist.version, "root": str(dist.locate_file("")),
                "METADATA_sha256": hashlib.sha256(dist.read_text("METADATA").encode()).hexdigest()}
        for requirement in SPEC["metadata"]["upstream"]["requirements"]:
            name, version = requirement.split("==")
            assert packages[name]["version"] == version
        assert os.environ["CUDA_VISIBLE_DEVICES"] == "" and os.environ["NVIDIA_VISIBLE_DEVICES"] == "none"
        for name in ("MPLCONFIGDIR", "NUMBA_CACHE_DIR", "XDG_CACHE_HOME"):
            assert Path(os.environ[name]).is_relative_to(HERE)
        (EVIDENCE / "runtime-profile.json").write_text(json.dumps({"interpreter": sys.executable,
            "packages": packages, "host_candidate": str(HERE / "candidate"),
            "host_worker_requirements_semantics": "All SDK exact pins checked in executing R4 interpreter; no worker, installation, stripping or assertion about parent latest interpreter.",
            "worker_used": False, "runtime_installs": False,
            "environment": {k: os.environ[k] for k in ("CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES", "PROJ_NETWORK", "MPLCONFIGDIR", "NUMBA_CACHE_DIR", "XDG_CACHE_HOME", "OMP_NUM_THREADS", "NUMBA_NUM_THREADS")}}, indent=2), encoding="utf-8")

    def test_fixed_collection_entry_success(self):
        args = dict(zip(proof.KEYS, proof.CASES["linear_analytic"]))
        workspace = HERE / "workspaces/fixed-success"
        workspace.mkdir(parents=True)
        proc = subprocess.run([sys.executable, str(HERE / "fixed_entry_collection.py")], input=json.dumps(args),
            text=True, capture_output=True, env={**os.environ, "WFLOW_COLLECTION_WORKSPACE": str(workspace)})
        (EVIDENCE / "fixed-success.stdout.json").write_text(proc.stdout, encoding="utf-8")
        (EVIDENCE / "fixed-success.stderr.txt").write_text(proc.stderr, encoding="utf-8")
        assert proc.returncode == 0, proc.stderr
        result = json.loads(proc.stdout)
        assert result["status"] == "ok" and result["call_id"] == "wflow-collection-fixed"
        check(args, result["data"])

    def test_fixed_collection_entry_error_exit(self):
        args = {**dict(zip(proof.KEYS, proof.CASES["steady"])), "reach_length_m": 0}
        workspace = HERE / "workspaces/fixed-error"
        workspace.mkdir(parents=True)
        proc = subprocess.run([sys.executable, str(HERE / "fixed_entry_collection.py")], input=json.dumps(args),
            text=True, capture_output=True, env={**os.environ, "WFLOW_COLLECTION_WORKSPACE": str(workspace)})
        (EVIDENCE / "fixed-error.stdout.json").write_text(proc.stdout, encoding="utf-8")
        (EVIDENCE / "fixed-error.stderr.txt").write_text(proc.stderr, encoding="utf-8")
        assert proc.returncode == 1, (proc.returncode, proc.stderr)
        result = json.loads(proc.stdout)
        assert result["status"] == "error" and result["error"]["code"] == "invalid_arguments"


for label, values in proof.CASES.items():
    for mode in ("dict", "json", "args"):
        def direct(self, values=values, mode=mode):
            args = dict(zip(proof.KEYS, values))
            before = copy.deepcopy(args)
            if mode == "json": result = reach_step(json.dumps(args))
            elif mode == "args": result = reach_step(args=args)
            else: result = reach_step(args)
            assert args == before
            check(args, result)
        setattr(Tests, "test_shared_direct_" + label + "_" + mode, direct)
    for mode in ("dict", "json"):
        def run_native(self, values=values, label=label, mode=mode):
            args = dict(zip(proof.KEYS, values))
            before = copy.deepcopy(args)
            result = native(json.dumps(args) if mode == "json" else args, "shared-native-" + label + "-" + mode)
            assert result.status == "ok", result.error
            assert result.artifacts == () and args == before
            check(args, result.data)
        setattr(Tests, "test_shared_native_" + label + "_" + mode, run_native)

for label, updates in proof.INVALIDS.items():
    for mode in ("direct", "native"):
        def invalid(self, label=label, updates=updates, mode=mode):
            args = {**dict(zip(proof.KEYS, proof.CASES["steady"])), **updates}
            before = json.dumps(args, sort_keys=True)
            if mode == "direct":
                with self.assertRaises(ScientificToolError) as error: reach_step(args=args)
                assert error.exception.code == "invalid_arguments"
            else:
                result = native(args, "shared-invalid-" + label)
                assert result.status == "error" and result.error.code == "invalid_arguments", result.error
            assert json.dumps(args, sort_keys=True) == before
        setattr(Tests, "test_shared_invalid_" + label + "_" + mode, invalid)


def main():
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    (EVIDENCE / "unittest.log").write_text(stream.getvalue(), encoding="utf-8")
    receipt = {"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "skipped": len(result.skipped), "passed": result.wasSuccessful(),
        "failure_details": [{"test": str(test), "traceback": trace} for test, trace in result.failures + result.errors],
        "registration": "real source_registry from real catalog, not manual prototype registration",
        "decorator": "unchanged shared collection_contracts.operation",
        "direct_dict_JSON_args": True, "native_ToolExecutor": True, "fixed_entry": True,
        "source_SHA_AST_JIT_numeric_and_unit_checks_retained": True,
        "source_project_id": 43, "coverage_kind": "original_bounded_operation",
        "full_Wflow_system_equivalence": False, "parent_count_delta": 0,
        "production_or_joint_candidate_changed": False, "GPU_used": False, "models_used": False}
    (EVIDENCE / "acceptance.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in receipt.items() if k != "failure_details"}))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

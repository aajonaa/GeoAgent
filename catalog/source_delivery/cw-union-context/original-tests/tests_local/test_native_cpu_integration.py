"""Actual ToolExecutor acceptance of only the three proposed CPU records."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from threading import Event

from jsonschema import Draft202012Validator
import pytest

from geological_agent.bootstrap import build_registry
from geological_agent.contracts import ToolCall
from geological_agent.settings import Settings
from geological_agent.tools import ToolExecutionContext, ToolExecutor
from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog, validate_registration_metadata

ROOT = Path(__file__).resolve().parents[1]
META = json.loads((ROOT/"native-cpu-integration-baseline.json").read_text(encoding="utf-8"))
NAMES = tuple(META["new_tools"])
SPECS = {row["id"]: row for row in catalog()["tools"]}
PROFILE_PATH = ROOT/"geological_agent/geology/native-cpu-profiles.json"
PROFILE = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.loads(json.dumps(value, allow_nan=False))


@pytest.fixture(autouse=True)
def offline_cpu(monkeypatch):
    assert os.environ["CUDA_VISIBLE_DEVICES"] == ""
    assert os.environ["NVIDIA_VISIBLE_DEVICES"] == "none"
    assert os.environ["PROJ_NETWORK"] == "OFF"
    def denied(*args, **kwargs):
        raise AssertionError("Integration scientific call attempted external networking")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def test_all_201_tools_and_42_skills_preserved_exactly():
    current = catalog()
    assert len(current["tools"]) == 204 and len(current["skills"]) == 43
    for kind in ["tools", "skills"]:
        actual = {row["id"]: hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=True).encode()).hexdigest() for row in current[kind]}
        assert all(actual.get(name) == expected for name, expected in META["tool_fingerprints" if kind == "tools" else "skill_fingerprints"].items())
    for name in NAMES:
        validate_registration_metadata(SPECS[name])
        Draft202012Validator.check_schema(SPECS[name]["input_schema"])
        Draft202012Validator.check_schema(SPECS[name]["output_schema"])


def test_allowlist_has_only_one_precise_module_addition():
    from geological_agent.geology.source_registry import ENTRY_MODULES
    assert set(ENTRY_MODULES) == set(META["original_entry_modules"]) | {META["allowed_entry_module_addition"]}
    assert digest(ROOT/"geological_agent/geology/source_registry.py") == META["source_registry_after_sha256"]


def test_all_three_are_discoverable_in_one_skill():
    registry, loader, base_tools = build_registry()
    skill = loader.load(META["new_skill"])
    assert skill.tool_names == NAMES
    assert not loader.source_statuses[META["new_skill"]]["unavailable_tools"]
    assert META["new_skill"] in {item.id for item in loader.registry.list("VIC Madagascar HPGL")}
    assert all(name not in base_tools and registry.get(name) for name in NAMES)


def test_hash_bound_fixed_profile_and_parent_modules():
    assert PROFILE["protocol"] == "fixed-cpu-arguments-json-v1"
    assert set(PROFILE["operations"]) == set(NAMES)
    assert digest(PROFILE_PATH) == META["profile_sha256"]
    assert digest(ROOT/"geological_agent/geology/native_cpu_bridge.py") == META["parent_bridge_sha256"]
    assert digest(ROOT/"geological_agent/geology/native_cpu_kernels.py") == META["parent_kernels_module_sha256"]
    for name in NAMES:
        binding = PROFILE["operations"][name]
        assert binding["entrypoint"] in binding["files_sha256"]
        assert binding["python"] in binding["files_sha256"]
        assert len(binding["files_sha256"]) == 24
        for path, expected in binding["files_sha256"].items():
            assert Path(path).is_absolute() and digest(path) == expected
        assert digest(Path(binding["root"])/"build/build-receipt.json") == binding["build_receipt_sha256"] == META["build_receipt_sha256"]


def native_reference(name, args):
    binding = PROFILE["operations"][name]
    child = subprocess.run([binding["python"], binding["entrypoint"], name], input=json.dumps(args).encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=binding["root"], env=dict(os.environ), timeout=30)
    assert child.returncode == 0, child.stderr.decode(errors="replace")
    response = json.loads(child.stdout)
    assert response["status"] == "ok" and response["tool"] == name
    return response["data"]


@pytest.mark.parametrize("name", NAMES)
def test_real_tool_executor_numeric_units_source_binary_and_input_identity(name, tmp_path):
    args = deepcopy(SPECS[name]["example_arguments"])
    before = deepcopy(args)
    sentinel = tmp_path/"untouched-input.txt"
    sentinel.write_bytes(b"Explicit integration input sentinel; not a scientific observation.\n")
    sentinel_sha = digest(sentinel)
    expected = native_reference(name, args)
    registry, loader, base_tools = build_registry()
    context = ToolExecutionContext("native-cpu-integration", tmp_path, (name,), Settings(), Event())
    call_id = "actual-native-cpu-"+name
    native = ToolExecutor(registry).execute(ToolCall(call_id, name, args), context)
    assert native.status == "ok", asdict(native)
    assert native.call_id == call_id and native.name == name and not native.artifacts
    data = canonical(native.data)
    for key, value in expected.items():
        if key != "provenance":
            assert data[key] == value
    proof, original = data["provenance"], expected["provenance"]
    for key in ["source_sha256", "binary_sha256", "build_receipt_sha256", "input_sha256", "original_source_bytes_preserved", "reviewed_archive_commit"]:
        assert proof[key] == original[key]
    assert proof["upstream_adapter_sha256"] == original["implementation_sha256"]
    assert proof["implementation_sha256"] == META["parent_kernels_module_sha256"]
    assert proof["cpu_bridge_sha256"] == META["parent_bridge_sha256"]
    assert proof["cpu_profile_sha256"] == META["profile_sha256"]
    assert proof["execution_mode"] == "fixed_cpu_dependency_profile" and proof["gpu_used"] is False
    assert proof["runtime_install"] is False and proof["runtime_compile"] is False
    assert data["artifacts"] == []
    assert args == before and digest(sentinel) == sentinel_sha
    Draft202012Validator(SPECS[name]["output_schema"]).validate(data)
    if name == "HydroVICPrecipitationPhase":
        assert data["rain_mm"] == [0, 0, 5, 10, 10]
        assert data["snow_mm"] == [10, 10, 5, 0, 0]
    elif name == "SeismicMadagascarFFT":
        assert data["real"] == [1]*8 and data["imaginary"] == [0]*8
        assert data["amplitude_two_sided"] == [0.125]*8
        assert data["frequency_hz"] == [0, 12.5, 25, 37.5, -50, -37.5, -25, -12.5]
    else:
        assert data["semivariance"] == [0.5, 2, 4.5]
        assert data["units"]["semivariance"] == "(g/t)^2"


@pytest.mark.parametrize("name", NAMES)
def test_parent_bridge_supports_dict_json_args_without_altering_input(name):
    module = importlib.import_module(META["allowed_entry_module_addition"])
    function = getattr(module, name)
    args = deepcopy(SPECS[name]["example_arguments"])
    before = deepcopy(args)
    result = [function(args), function(json.dumps(args)), function(args=args)]
    assert canonical(result[0]) == canonical(result[1]) == canonical(result[2])
    assert args == before


@pytest.mark.parametrize("name", NAMES)
def test_tool_executor_rejects_undeclared_executable_or_code(name, tmp_path):
    registry, loader, base_tools = build_registry()
    args = {**deepcopy(SPECS[name]["example_arguments"]), "command": "must never execute"}
    context = ToolExecutionContext("native-cpu-invalid", tmp_path, (name,), Settings(), Event())
    result = ToolExecutor(registry).execute(ToolCall("invalid-extra-"+name, name, args), context)
    assert result.status == "error"
    assert result.error.code == "invalid_arguments" and result.error.retryable is False
    assert not result.artifacts


@pytest.mark.parametrize("name", NAMES)
def test_native_cross_field_constraints_return_structured_runtime_error(name, tmp_path):
    args = deepcopy(SPECS[name]["example_arguments"])
    if name == "HydroVICPrecipitationPhase":
        args["precipitation_mm"] = [10]
    elif name == "SeismicMadagascarFFT":
        args["sampling_interval_s"] = 0
    else:
        args["first_lag_m"] = 0.1
    registry, loader, base_tools = build_registry()
    context = ToolExecutionContext("native-cpu-domain", tmp_path, (name,), Settings(), Event())
    result = ToolExecutor(registry).execute(ToolCall("invalid-domain-"+name, name, args), context)
    assert result.status == "error" and result.error.code == "invalid_arguments"
    assert result.error.retryable is False and not result.artifacts


def test_license_and_formal_delivery_gates_remain_explicit():
    spec = SPECS["GeoHPGLDirectionalSemivariogram"]
    assert spec["metadata"]["distribution_license_review_required"] is True
    assert "HPGL_README_license_wording_review" in spec["registration_metadata"]["pending_fields"]
    assert META["formal_packaging"] == "not_performed"
    assert META["HPGL_distribution_license_review"] == "pending"
    for name in NAMES:
        assert SPECS[name]["registration_metadata"]["lifecycle"]["workflow_validation"] == "not_run"
        assert SPECS[name]["registration_metadata"]["lifecycle"]["platform_validation"] == "not_run"




def test_original_134_tools_37_skills_and_101_project_accounting():
    initial = json.loads((ROOT/"collection-baseline.json").read_text(encoding="utf-8"))
    for kind in ["tools", "skills"]:
        actual = {row["id"]: hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=True).encode()).hexdigest() for row in catalog()[kind]}
        assert all(actual.get(name) == value for name,value in initial[kind].items())
    assert len(initial["tools"]) == 134 and len(initial["skills"]) == 37
    manifests = json.loads((ROOT/"collection-manifests.json").read_text(encoding="utf-8"))
    acceptance = json.loads((ROOT/"collection-acceptance.json").read_text(encoding="utf-8"))
    rows = [row for group in manifests.values() for row in group["projects"]]
    operations = {op["name"] for group in manifests.values() for op in group["operations"]}
    assert len(rows) == len({row["id"] for row in rows}) == 101
    assert manifests["native_cpu"]["projects"] == []
    assert len(operations) == 78 and len(acceptance["accepted_new_tools"]) == 70 and len(acceptance["inactive_source_adapters"]) == 8
    assert set(acceptance["accepted_new_tools"]) | set(acceptance["inactive_source_adapters"]) == operations
    assert not set(acceptance["accepted_new_tools"]) & set(acceptance["inactive_source_adapters"])
    for row in rows:
        if row["id"] in [39,86,131]:
            assert row["status"] == "implemented" and len(row["operations"]) == 1


@pytest.mark.parametrize("name", NAMES)
def test_proper_wrapped_identity_and_standard_group_probe(name):
    import inspect
    function = getattr(importlib.import_module(META["allowed_entry_module_addition"]), name)
    assert function.__wrapped__ is not function
    original = inspect.unwrap(function)
    assert original is function.__wrapped__ and not hasattr(original,"__wrapped__")
    assert Path(original.__code__.co_filename).resolve() == (ROOT/"geological_agent/geology/native_cpu_kernels.py").resolve()
    args = deepcopy(SPECS[name]["example_arguments"])
    result = function(args=args)
    assert result["provenance"]["implementation_sha256"] == digest(Path(original.__code__.co_filename))
    fixtures = importlib.import_module("collection_acceptance.native_cpu_fixtures").create(ROOT)
    assert fixtures["files"] == [] and set(fixtures["examples"]) == set(NAMES)
    importlib.import_module("collection_acceptance.native_cpu_checks").check(name,result,args,None)

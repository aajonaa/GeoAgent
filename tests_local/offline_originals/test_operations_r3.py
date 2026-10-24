"""CPU-only source interface, oracle, immutable evidence and real runtime gates."""
from copy import deepcopy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import socket
import sys
from threading import Event

import pytest
from jsonschema import Draft202012Validator

PACKAGE = "geological_agent.geology.collection_offline_originals"
adapters = importlib.import_module(PACKAGE + ".adapters")
fixtures = importlib.import_module(PACKAGE + ".fixtures")
checks = importlib.import_module(PACKAGE + ".checks")
from geological_agent.bootstrap import build_registry
from geological_agent.contracts import ToolCall
from geological_agent.settings import Settings
from geological_agent.tools import ToolExecutionContext, ToolExecutor
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError

HERE = Path(__file__).resolve().parent
SOURCE = Path(adapters.__file__).parent
MANIFEST = json.loads((SOURCE / "manifest.json").read_text())
OPERATIONS = MANIFEST["operations"]
NAMES = [row["name"] for row in OPERATIONS]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def offline_policy(monkeypatch):
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "" and os.environ["NVIDIA_VISIBLE_DEVICES"] == "none"
    assert os.environ["PROJ_NETWORK"] == "OFF"
    for name in ["MPLCONFIGDIR", "NUMBA_CACHE_DIR", "XDG_CACHE_HOME"]:
        assert Path(os.environ[name]).resolve().is_relative_to(HERE)
    def deny(*args, **kwargs):
        raise RuntimeError("Network access is forbidden in CPU source acceptance")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture
def inputs(tmp_path):
    fixtures.create(tmp_path)
    return tmp_path


def arguments(spec, workspace):
    args = deepcopy(spec["example_arguments"])
    hashes = {}
    for field in spec["path_fields"]:
        path = workspace / args[field]
        args[field] = str(path)
        hashes[str(path)] = sha(path)
    return args, hashes


def assert_immutable(hashes):
    assert all(sha(path) == digest for path, digest in hashes.items())


@pytest.mark.parametrize("spec", OPERATIONS, ids=NAMES)
def test_schema_and_original_source_evidence(spec):
    Draft202012Validator.check_schema(spec["input_schema"])
    Draft202012Validator.check_schema(spec["output_schema"])
    Draft202012Validator(spec["input_schema"]).validate(spec["example_arguments"])
    assert spec["network_required"] is False and spec["produces_files"] is False
    for original in spec["original_files"] + spec["license_files"] + spec["vendor_files"]:
        assert sha(SOURCE / original["file"]) == original["sha256"]


@pytest.mark.parametrize("mode", ["dict", "json", "keyword"])
@pytest.mark.parametrize("spec", OPERATIONS, ids=NAMES)
def test_direct_numeric_contract_and_immutable_input(spec, mode, inputs):
    args, hashes = arguments(spec, inputs)
    original = deepcopy(args)
    function = getattr(adapters, spec["function"])
    value = function(args=deepcopy(args)) if mode == "keyword" else function(json.dumps(args) if mode == "json" else deepcopy(args))
    checks.check(spec["name"], value, args)
    assert args == original
    Draft202012Validator(spec["output_schema"]).validate(value)
    json.dumps(value, allow_nan=False)
    assert value["artifacts"] == [] and value["provenance"]["output_sha256"] == {}
    assert value["provenance"]["tool"] == spec["name"]
    assert value["provenance"]["implementation_sha256"] == sha(Path(function.__wrapped__.__code__.co_filename))
    assert value["provenance"]["network_required"] is False
    assert_immutable(hashes)


@pytest.mark.parametrize("spec", OPERATIONS, ids=NAMES)
def test_undeclared_argument_does_not_execute(spec, inputs):
    args, hashes = arguments(spec, inputs)
    args["unreviewed_callback"] = "not permitted"
    with pytest.raises(ScientificToolError) as error:
        getattr(adapters, spec["function"])(args)
    assert error.value.code == "invalid_arguments" and error.value.retryable is False
    assert_immutable(hashes)


@pytest.mark.parametrize("spec", OPERATIONS, ids=NAMES)
def test_native_runtime_numeric_units_provenance_and_immutable_inputs(spec, inputs):
    registry, _, base = build_registry()
    context = ToolExecutionContext("offline-originals-r3", inputs, (spec["name"],), Settings(), Event())
    before = {str(path): sha(path) for path in inputs.rglob("*") if path.is_file()}
    result = ToolExecutor(registry).execute(ToolCall("native-" + spec["name"], spec["name"], deepcopy(spec["example_arguments"])), context)
    assert result.status == "ok", result.error
    assert spec["name"] not in base
    assert result.artifacts == ()
    checks.check(spec["name"], result.data, spec["example_arguments"])
    assert result.data["provenance"]["tool"] == spec["name"]
    assert result.data["provenance"]["output_sha256"] == {}
    assert result.data["provenance"]["network_required"] is False
    assert_immutable(before)


@pytest.mark.parametrize("spec", [row for row in OPERATIONS if row["path_fields"]], ids=[row["name"] for row in OPERATIONS if row["path_fields"]])
def test_native_runtime_rejects_workspace_escape(spec, inputs):
    registry, _, _ = build_registry()
    args = deepcopy(spec["example_arguments"])
    args[spec["path_fields"][0]] = "../outside.tif"
    context = ToolExecutionContext("offline-originals-path-r3", inputs, (spec["name"],), Settings(), Event())
    result = ToolExecutor(registry).execute(ToolCall("escape-" + spec["name"], spec["name"], args), context)
    assert result.status == "error"


@pytest.mark.parametrize("spec", [row for row in OPERATIONS if "value_unit" in row["example_arguments"]], ids=[row["name"] for row in OPERATIONS if "value_unit" in row["example_arguments"]])
def test_conflicting_unit_rejected_without_conversion(spec, inputs):
    args, hashes = arguments(spec, inputs)
    args["value_unit"] = "km"
    with pytest.raises(ScientificToolError) as error:
        getattr(adapters, spec["function"])(args)
    assert error.value.code == "invalid_arguments" and error.value.retryable is False
    assert_immutable(hashes)


@pytest.mark.parametrize("spec", [row for row in OPERATIONS if row["path_fields"]], ids=[row["name"] for row in OPERATIONS if row["path_fields"]])
def test_runtime_input_larger_than_two_mib_rejected(spec, inputs):
    args, hashes = arguments(spec, inputs)
    path = Path(args[spec["path_fields"][0]])
    with path.open("ab") as stream:
        stream.write(b"x" * (2 * 1024 * 1024 + 1))
    original = sha(path)
    with pytest.raises(ScientificToolError) as error:
        getattr(adapters, spec["function"])(args)
    assert error.value.code == "resource_limit"
    assert sha(path) == original


@pytest.mark.parametrize("speed", [-1, float("nan"), float("inf"), True])
def test_invalid_wind_measurements_rejected(speed):
    with pytest.raises(ScientificToolError) as error:
        adapters.pyowm_beaufort_wind({"wind_speed_m_s": [speed]})
    assert error.value.code == "invalid_arguments"


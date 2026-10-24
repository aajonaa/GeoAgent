"""Independent hydrological recurrence, metric, evaluator and real runtime tests."""
from copy import deepcopy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import socket
from threading import Event

import pytest
from jsonschema import Draft202012Validator
from geological_agent.bootstrap import build_registry
from geological_agent.contracts import ToolCall
from geological_agent.settings import Settings
from geological_agent.tools import ToolExecutionContext, ToolExecutor
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError

module = importlib.import_module("geological_agent.geology.collection_offline_originals.pyglue_fixed.adapters")
SOURCE = Path(module.__file__).parent
manifest = json.loads((SOURCE / "manifest.json").read_text())
SPEC = manifest["operations"][0]


@pytest.fixture(autouse=True)
def private_cpu_policy(monkeypatch):
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "" and os.environ["NVIDIA_VISIBLE_DEVICES"] == "none"
    assert os.environ["PROJ_NETWORK"] == "OFF"
    for name in ["MPLCONFIGDIR", "NUMBA_CACHE_DIR", "XDG_CACHE_HOME"]:
        assert "earth-python-coverage101-offline-originals-20261022" in os.environ[name]
    def deny(*args, **kwargs):
        raise RuntimeError("No network in fixed PyGLUE CPU acceptance")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def check(result, args):
    assert result["evaluated_count"] == len(args["parameter_sets"])
    accepted = []
    measured = args["observed_runoff_mm"][1:]
    mean = sum(measured) / len(measured)
    for index, (row, params) in enumerate(zip(result["runs"], args["parameter_sets"])):
        storage = args["initial_storage_mm"]
        expected_q, expected_s = [0], [storage]
        for rain in args["precipitation_mm"][1:]:
            expected_q.append((1 - params["a"] - params["b"]) * rain + params["c"] * storage)
            storage = (1 - params["c"]) * storage + params["a"] * rain
            expected_s.append(storage)
        assert row["run_id"] == index
        assert row["runoff_mm"] == pytest.approx(expected_q, abs=1e-12)
        assert row["storage_mm"] == pytest.approx(expected_s, abs=1e-12)
        expected_nse = 1 - sum((obs - sim) ** 2 for obs, sim in zip(measured, expected_q[1:])) / sum((value - mean) ** 2 for value in measured)
        assert row["nse"] == pytest.approx(expected_nse, abs=1e-12)
        assert row["behavioural"] == (expected_nse >= args["minimum_nse"])
        assert abs(row["water_balance_residual_mm"]) < 1e-10
        if row["behavioural"]:
            accepted.append(index)
    assert result["accepted_run_ids"] == accepted
    assert result["behavioural_count"] == len(accepted)
    assert result["units"]["nse"] == "dimensionless" and result["units"]["storage_mm"] == "mm"
    assert result["artifacts"] == [] and result["provenance"]["output_sha256"] == {}
    Draft202012Validator(SPEC["output_schema"]).validate(result)
    json.dumps(result, allow_nan=False)


def test_original_sources_licenses_and_kernels_are_hash_bound():
    for item in SPEC["original_files"] + SPEC["license_files"] + SPEC["vendor_files"]:
        assert hashlib.sha256((SOURCE / item["file"]).read_bytes()).hexdigest() == item["sha256"]
    assert manifest["provenance"]["originals"]["pyglue"]["id"] == 84
    assert len(manifest["provenance"]["originals"]) == 3


@pytest.mark.parametrize("mode", ["dict", "json", "keyword"])
def test_direct_real_fixed_model_and_original_evaluator(mode):
    args = deepcopy(SPEC["example_arguments"])
    original = deepcopy(args)
    value = module.pyglue_abc_ensemble(args=args) if mode == "keyword" else module.pyglue_abc_ensemble(json.dumps(args) if mode == "json" else args)
    check(value, args)
    assert args == original
    assert value["accepted_run_ids"] == [0]
    assert value["runs"][0]["nse"] == pytest.approx(1)


def test_real_registered_native_runtime(tmp_path):
    registry, _, base = build_registry()
    context = ToolExecutionContext("fixed-pyglue-native", tmp_path, (SPEC["name"],), Settings(), Event())
    result = ToolExecutor(registry).execute(ToolCall("fixed-pyglue", SPEC["name"], deepcopy(SPEC["example_arguments"])), context)
    assert result.status == "ok", result.error
    assert SPEC["name"] not in base and result.artifacts == ()
    check(result.data, SPEC["example_arguments"])


@pytest.mark.parametrize("case", ["callback", "nonfinite", "negative_rain", "initial_slot", "mismatched_observation", "constant_observation", "sum_parameters", "duplicate_parameters"])
def test_invalid_physical_or_executable_inputs_rejected(case):
    args = deepcopy(SPEC["example_arguments"])
    if case == "callback":
        args["model_callback"] = "not executable"
    elif case == "nonfinite":
        args["precipitation_mm"][1] = float("nan")
    elif case == "negative_rain":
        args["precipitation_mm"][1] = -1
    elif case == "initial_slot":
        args["precipitation_mm"][0] = 1
    elif case == "mismatched_observation":
        args["observed_runoff_mm"].append(1)
    elif case == "constant_observation":
        args["observed_runoff_mm"] = [0, 1, 1, 1, 1]
    elif case == "sum_parameters":
        args["parameter_sets"][0].update(a=0.8, b=0.5)
    elif case == "duplicate_parameters":
        args["parameter_sets"][1] = deepcopy(args["parameter_sets"][0])
    with pytest.raises(ScientificToolError) as error:
        module.pyglue_abc_ensemble(args)
    assert error.value.code == "invalid_arguments" and error.value.retryable is False


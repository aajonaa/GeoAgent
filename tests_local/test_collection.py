"""No-model CPU regression of accepted source operations and preserved baseline."""
from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
import socket

import pytest

from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = json.loads((ROOT / "collection-acceptance.json").read_text(encoding="utf-8"))
MANIFESTS = json.loads((ROOT / "collection-manifests.json").read_text(encoding="utf-8"))
OPERATIONS = {operation["name"]: {**operation, "group": group} for group, manifest in MANIFESTS.items() for operation in manifest["operations"]}
NAMES = ACCEPTANCE["accepted_new_tools"]
SPECS = {row["id"]: row for row in catalog()["tools"]}


def test_all_original_134_tools_and_37_skills_are_unchanged():
    baseline = json.loads((ROOT / "collection-baseline.json").read_text(encoding="utf-8"))
    for kind in ["tools", "skills"]:
        actual = {row["id"]: hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=True).encode()).hexdigest() for row in catalog()[kind]}
        assert all(actual.get(name) == expected for name, expected in baseline[kind].items())
    assert len(baseline["tools"]) == 134 and len(baseline["skills"]) == 37


def test_source_scope_failure_accounting_and_gpu_prohibition():
    rows = [row for manifest in MANIFESTS.values() for row in manifest["projects"]]
    assert len(rows) == 101 and len({row["id"] for row in rows}) == 101
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "" and os.environ["NVIDIA_VISIBLE_DEVICES"] == "none"
    assert set(NAMES) | set(ACCEPTANCE["inactive_source_adapters"]) == set(OPERATIONS)
    assert not set(NAMES) & set(ACCEPTANCE["inactive_source_adapters"])
    assert all(row["error"] and row["traceback"] for row in ACCEPTANCE["inactive_source_adapters"].values())
    assert not set(ACCEPTANCE["inactive_source_adapters"]) & set(SPECS)
    for row in rows:
        if row["status"] == "blocked":
            assert row["reason"] and row["required_next_step"] and row["evidence"]
            assert row["operations"] == []


@pytest.mark.parametrize("name", NAMES)
def test_real_upstream_results_and_offline_execution(name, tmp_path, monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("Offline operation attempted a network connection")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    spec, operation = SPECS[name], OPERATIONS[name]
    module, entry = spec["source_interface"]["entrypoint"]["callable"].split(":")
    function = getattr(importlib.import_module(module), entry)
    args = deepcopy(spec["example_arguments"])
    originals = {}
    for key in spec["source_interface"].get("path_fields", []):
        values = args[key] if isinstance(args[key], list) else [args[key]]
        originals.update({ROOT / value: hashlib.sha256((ROOT / value).read_bytes()).hexdigest() for value in values})
        args[key] = [str(ROOT / value) for value in values] if isinstance(args[key], list) else str(ROOT / values[0])
    kwargs = {"output_dir": tmp_path / "results"} if operation.get("produces_files") else {}
    result = function(args=args, **kwargs)
    check = importlib.import_module("collection_acceptance." + operation["group"] + "_checks").check
    check(name, result, args, kwargs.get("output_dir"))
    assert result["provenance"]["tool"] == name and result["units"]
    assert result["provenance"]["implementation_sha256"] == hashlib.sha256(Path(function.__wrapped__.__code__.co_filename).read_bytes()).hexdigest()
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == expected for path, expected in originals.items())


@pytest.mark.parametrize("name", NAMES)
def test_undeclared_arguments_fail_before_execution(name, tmp_path):
    spec = SPECS[name]
    module, entry = spec["source_interface"]["entrypoint"]["callable"].split(":")
    function = getattr(importlib.import_module(module), entry)
    args = {**spec["example_arguments"], "__unexpected_acceptance_argument__": True}
    kwargs = {"output_dir": tmp_path / "must-not-exist"} if spec["source_interface"]["entrypoint"].get("output_directory_parameter") else {}
    with pytest.raises(ScientificToolError) as caught:
        function(args=args, **kwargs)
    assert caught.value.code == "invalid_arguments" and caught.value.retryable is False
    assert not (tmp_path / "must-not-exist").exists()

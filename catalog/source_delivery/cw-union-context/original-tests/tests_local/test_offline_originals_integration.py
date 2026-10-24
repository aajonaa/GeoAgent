"""Parent proposal gates: no duplicate project count, preserved originals and real SDK."""
from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
from threading import Event

import pytest
from geological_agent.bootstrap import build_registry
from geological_agent.contracts import ToolCall
from geological_agent.settings import Settings
from geological_agent.tools import ToolExecutionContext, ToolExecutor
from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog, validate_registration_metadata
from collection_acceptance.offline_originals_checks import check
from collection_acceptance.offline_originals_fixtures import create

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = json.loads((ROOT / "offline-originals-integration.json").read_text())
MANIFEST = json.loads((ROOT / "collection-manifests.json").read_text())
OPS = MANIFEST["offline_originals"]["operations"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_101_original_rows_and_exact_seven_delegated_operations():
    assert MANIFEST["offline_originals"]["projects"] == []
    rows = [row for group in MANIFEST.values() for row in group["projects"]]
    assert len(rows) == len({row["id"] for row in rows}) == 101
    assert len(OPS) == 7 and {row["project_id"] for row in OPS} == {10, 26, 31, 84, 100, 124, 126}
    for operation in OPS:
        project = next(row for row in rows if row["id"] == operation["project_id"])
        assert project["status"] == "implemented" and project["operations"] == [operation["name"]]
        assert "reason" not in project and "required_next_step" not in project
    for group, expected in PROPOSAL["original_group_operation_sha256"].items():
        assert hashlib.sha256(json.dumps(MANIFEST[group]["operations"], sort_keys=True, ensure_ascii=True).encode()).hexdigest() == expected


def test_all_201_tool_and_42_skill_definitions_preserved():
    current = catalog()
    for kind, expected in PROPOSAL["baseline_definition_sha256"].items():
        actual = {row["id"]: hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=True).encode()).hexdigest() for row in current[kind]}
        assert all(actual.get(name) == value for name, value in expected.items())
    assert len(current["tools"]) == 210 and len(current["skills"]) == 44
    for item in current["tools"]:
        validate_registration_metadata(item)


def test_handoff_examples_and_new_skill_reach_exact_seven_tools():
    current = catalog()
    examples = json.loads((ROOT / "catalog/source_delivery/examples.json").read_text())
    assert set(examples) == {row["id"] for row in current["tools"] if row["source_interface"]["status"] == "source_revised_unverified"}
    registry, skills, _ = build_registry()
    skill = skills.load("earth_collection_offline_originals")
    assert set(skill.tool_names) == {row["name"] for row in OPS}
    assert set(skill.tool_names) <= set(registry.names())
    for operation in OPS:
        assert examples[operation["name"]] == operation["example_arguments"]


def test_shared_probe_fixture_reuse_is_byte_immutable(tmp_path):
    create(tmp_path)
    files = list((tmp_path / "assets/offline-originals").iterdir())
    before = {str(path): (sha(path), path.stat().st_mtime_ns) for path in files}
    create(tmp_path)
    assert all((sha(Path(path)), Path(path).stat().st_mtime_ns) == expected for path, expected in before.items())


def test_shared_probe_refuses_different_existing_input_without_overwrite(tmp_path):
    create(tmp_path)
    target = tmp_path / "assets/offline-originals/projected.tif"
    with target.open("ab") as stream:
        stream.write(b"deliberate synthetic fixture mutation")
    original = sha(target)
    with pytest.raises(ValueError, match="no file was overwritten"):
        create(tmp_path)
    assert sha(target) == original


@pytest.mark.parametrize("operation", OPS, ids=[row["name"] for row in OPS])
def test_global_group_oracle_and_actual_registered_tool_executor(operation, tmp_path):
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "" and os.environ["NVIDIA_VISIBLE_DEVICES"] == "none"
    create(tmp_path)
    registry, _, base = build_registry()
    name = operation["name"]
    spec = next(row for row in catalog()["tools"] if row["id"] == name)
    module, function = spec["source_interface"]["entrypoint"]["callable"].split(":")
    entry = getattr(importlib.import_module(module), function)
    assert callable(entry.__wrapped__)
    original = {str(path): sha(path) for path in (tmp_path / "assets/offline-originals").iterdir()}
    ctx = ToolExecutionContext("integration-" + name, tmp_path, (name,), Settings(), Event())
    result = ToolExecutor(registry).execute(ToolCall("native-" + name, name, deepcopy(spec["example_arguments"])), ctx)
    assert result.status == "ok", result.error
    assert name not in base and result.artifacts == ()
    check(name, result.data, spec["example_arguments"], None)
    assert result.data["provenance"]["implementation_sha256"] == sha(Path(entry.__wrapped__.__code__.co_filename))
    assert all(sha(Path(path)) == value for path, value in original.items())
    if name == "EarthHydroShareRasterBandRanges":
        assert result.data["native_environment"]["packages"] == {"GDAL": "3.13.3", "numpy": "2.2.6"}
        assert result.data["native_environment"]["runtime_installation"] is False


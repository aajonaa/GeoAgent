"""Metadata/origin gates added without changing any scientific oracle."""
from pathlib import Path
import hashlib
import importlib
from importlib import metadata
import json

import pytest
from geological_agent.bootstrap import build_registry
from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog, validate_registration_metadata

ROOT = Path(__file__).resolve().parents[1]
REPORT = json.loads((ROOT / "replacement-union.json").read_text())
MANIFESTS = json.loads((ROOT / "collection-manifests.json").read_text())
ACCEPTANCE = json.loads((ROOT / "collection-acceptance.json").read_text())
GROUP = "approved_explicit_functional_replacements"
HYDRO_ADDITIONS = frozenset(("EarthCatchmodLinearStoreStep", "HydroModelsHydPyFlowScores", "HydroModelsPyDEMTerrainDerivatives", "HydroModelsPyFloCurveNumberRunoff", "HydroModelsPySTEPSPrecipitationAdvection", "HydroModelsSuperflexUnitHydrograph"))


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_preserved_208_tool_and_43_skill_definitions():
    current = catalog()
    assert len(current["tools"]) == 220 and len(current["skills"]) == 47
    for kind, expected in REPORT["baseline_definition_sha256"].items():
        observed = {row["id"]: canonical(row) for row in current[kind]}
        assert all(observed[name] == digest for name, digest in expected.items())
    for row in current["tools"]:
        validate_registration_metadata(row)


def test_original_101_project_rows_and_original_groups_unchanged():
    rows = [row for group in MANIFESTS.values() for row in group["projects"]]
    assert len(rows) == len({row["id"] for row in rows}) == 101
    assert {str(row["id"]): canonical(row) for row in rows} == REPORT["baseline_project_rows_sha256"]
    assert MANIFESTS[GROUP]["projects"] == []
    for group, digest in REPORT["baseline_group_sha256"].items():
        assert canonical(MANIFESTS[group]) == digest
    for identifier in [72, 82]:
        row = next(row for row in rows if row["id"] == identifier)
        assert row["status"] == "blocked" and row["operations"] == []


def test_separate_original_and_explicit_replacement_accounting():
    assert ACCEPTANCE["accepted_original_collection_operations"] == 84
    assert len(ACCEPTANCE["accepted_original_tools"]) == 84
    assert len(ACCEPTANCE["accepted_functional_replacements"]) == 2
    assert not set(ACCEPTANCE["accepted_original_tools"]).intersection(ACCEPTANCE["accepted_functional_replacements"])
    assert set(ACCEPTANCE["accepted_new_tools"]) == set(ACCEPTANCE["accepted_original_tools"]) | set(ACCEPTANCE["accepted_functional_replacements"])
    assert MANIFESTS[GROUP]["original_implementation_count_delta"] == 0


@pytest.mark.parametrize("name,identifier,package", [("ScipyGroundwaterFrequencyResponse", 72, "scipy"), ("StatsmodelsSeasonalFlowForecast", 82, "statsmodels")])
def test_actual_upstream_and_exact_source_schema_pins(name, identifier, package):
    spec = next(row for row in catalog()["tools"] if row["id"] == name)
    frozen = json.loads((ROOT / "catalog/source_delivery/approved-replacements/catalog-records.json").read_text())
    original = next(row for row in frozen if row["id"] == name)
    for key in ["input_schema", "output_schema", "source_interface", "function_definition", "example_arguments", "limitations", "error_contract"]:
        assert spec[key] == original[key]
    assert spec["metadata"]["upstream"] == original["metadata"]["upstream"]
    assert spec["metadata"]["upstream"]["package"] == package
    assert spec["coverage_kind"] == "explicit_functional_replacement" and spec["coverage_target_project_id"] == identifier
    replacement = spec["metadata"]["functional_replacement"]
    assert replacement["original_code_reused"] is False and replacement["original_implementation_claimed"] is False
    for pin in spec["metadata"]["upstream"]["requirements"]:
        dependency, version = pin.split("==")
        assert metadata.version(dependency) == version
    module, function = spec["source_interface"]["entrypoint"]["callable"].split(":")
    operation = getattr(importlib.import_module(module), function)
    assert callable(operation.__wrapped__)
    assert sha(operation.__wrapped__.__code__.co_filename) == REPORT["contribution_files_sha256"]["source\\geological_agent\\geology\\collection_approved_replacements.py"]


def test_original_examples_preserved_and_new_skill_has_only_two_replacements():
    examples = json.loads((ROOT / "catalog/source_delivery/examples.json").read_text())
    new = set(REPORT["names"])
    assert len(HYDRO_ADDITIONS) == 6 and HYDRO_ADDITIONS <= set(examples)
    assert canonical({name: value for name, value in examples.items() if name not in (new | HYDRO_ADDITIONS)}) == REPORT["baseline_examples_sha256"]
    assert len(examples) == 220
    registry, skills, _ = build_registry()
    skill = skills.load("approved_functional_hydrology_replacements")
    assert set(skill.tool_names) == new and new <= set(registry.names())


def test_inactive_eight_keep_errors_tracebacks_and_are_not_registered():
    inactive = ACCEPTANCE["inactive_source_adapters"]
    assert len(inactive) == 3 and all(row["error"] and row["traceback"] for row in inactive.values())
    registry, _, _ = build_registry()
    assert not set(inactive).intersection(row["id"] for row in catalog()["tools"])
    assert not set(inactive).intersection(registry.names())


def test_frozen_contribution_every_hash_and_test_source_unchanged():
    root = ROOT / "catalog/source_delivery/approved-replacements"
    assert sha(root / "contribution.json") == REPORT["contribution_sha256"]
    for name, digest in REPORT["contribution_files_sha256"].items():
        assert sha(root / name.replace("\\", "/")) == digest
    assert sha(ROOT / "tests_local/approved_replacements/test_replacements_r1.py") == REPORT["contribution_files_sha256"]["acceptance\\test_replacements_r1.py"]

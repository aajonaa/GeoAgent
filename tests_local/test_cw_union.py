"""Additive union checks, without replacing the retained scientific tests."""
from pathlib import Path
from copy import deepcopy
import hashlib
import importlib
import json
from threading import Event

import pytest
from geological_agent.bootstrap import build_registry
from geological_agent.contracts import ToolCall
from geological_agent.settings import Settings
from geological_agent.tools import ToolExecutionContext, ToolExecutor
from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog

ROOT = Path(__file__).resolve().parents[1]
META = json.loads((ROOT / "cw-union.json").read_text())
NAMES = ("HydroVICPrecipitationPhase", "SeismicMadagascarFFT", "GeoHPGLDirectionalSemivariogram", "EarthWflowKinematicWaveReachStep")
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
canonical = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()

# Frozen 214 tools / 46 Skills plus this batch's exact six tools / one Skill.
HYDRO_ADDITIONS = frozenset(("EarthCatchmodLinearStoreStep", "HydroModelsHydPyFlowScores", "HydroModelsPyDEMTerrainDerivatives", "HydroModelsPyFloCurveNumberRunoff", "HydroModelsPySTEPSPrecipitationAdvection", "HydroModelsSuperflexUnitHydrograph"))
HYDRO_INVENTORY_PATCHES = {
    "tests_local/test_intake_contracts.py": [
        [
            "assert len(catalog()['tools'])==214 and len(catalog()['skills'])==46",
            "assert len(catalog()['tools'])==220 and len(catalog()['skills'])==47"
        ]
    ],
    "tests_local/test_professional_catalog.py": [
        [
            "assert len(SPECS) == 214 and len(READY_SPECS) == 214",
            "assert len(SPECS) == 220 and len(READY_SPECS) == 220"
        ],
        [
            "assert len(agent.skills.source_statuses) == len(catalog()[\"skills\"]) == 46",
            "assert len(agent.skills.source_statuses) == len(catalog()[\"skills\"]) == 47"
        ]
    ],
    "tests_local/test_catalog_metadata.py": [
        [
            "assert len(current[\"tools\"]) == 214",
            "assert len(current[\"tools\"]) == 220"
        ]
    ],
    "tests_local/test_unified_skills.py": [
        [
            "assert len(expected) == 46",
            "assert len(expected) == 47"
        ],
        [
            "assert counts[\"professional_tools\"] == 214 and counts[\"runtime_tools\"] == runtime_count",
            "assert counts[\"professional_tools\"] == 220 and counts[\"runtime_tools\"] == runtime_count"
        ],
        [
            "assert len(rows) == 46 and all(row[\"status\"] == \"passed\" for row in rows), rows",
            "assert len(rows) == 47 and all(row[\"status\"] == \"passed\" for row in rows), rows"
        ],
        [
            "assert counts[\"skills\"] == counts[\"catalog_skills\"] == 46",
            "assert counts[\"skills\"] == counts[\"catalog_skills\"] == 47"
        ],
        [
            "assert counts[\"tools\"] == counts[\"registered_tools\"] == len(registry.names()) == 214 + runtime_count",
            "assert counts[\"tools\"] == counts[\"registered_tools\"] == len(registry.names()) == 220 + runtime_count"
        ],
        [
            "assert len(loader.registry.list()) == 46",
            "assert len(loader.registry.list()) == 47"
        ]
    ],
    "tests_local/test_offline_originals_integration.py": [
        [
            "assert len(current[\"tools\"]) == 214 and len(current[\"skills\"]) == 46",
            "assert len(current[\"tools\"]) == 220 and len(current[\"skills\"]) == 47"
        ]
    ],
    "tests_local/test_replacement_union.py": [
        [
            "assert len(current[\"tools\"]) == 214 and len(current[\"skills\"]) == 46",
            "assert len(current[\"tools\"]) == 220 and len(current[\"skills\"]) == 47"
        ],
        [
            "assert ACCEPTANCE[\"accepted_original_collection_operations\"] == 78",
            "assert ACCEPTANCE[\"accepted_original_collection_operations\"] == 84"
        ],
        [
            "assert len(ACCEPTANCE[\"accepted_original_tools\"]) == 78",
            "assert len(ACCEPTANCE[\"accepted_original_tools\"]) == 84"
        ],
        [
            "assert len(examples) == 214",
            "assert len(examples) == 220"
        ],
        [
            "assert len(inactive) == 8 and all(row[\"error\"] and row[\"traceback\"] for row in inactive.values())",
            "assert len(inactive) == 3 and all(row[\"error\"] and row[\"traceback\"] for row in inactive.values())"
        ],
        [
            "GROUP = \"approved_explicit_functional_replacements\"",
            "GROUP = \"approved_explicit_functional_replacements\"\nHYDRO_ADDITIONS = frozenset((\"EarthCatchmodLinearStoreStep\", \"HydroModelsHydPyFlowScores\", \"HydroModelsPyDEMTerrainDerivatives\", \"HydroModelsPyFloCurveNumberRunoff\", \"HydroModelsPySTEPSPrecipitationAdvection\", \"HydroModelsSuperflexUnitHydrograph\"))"
        ],
        [
            "    assert canonical({name: value for name, value in examples.items() if name not in new}) == REPORT[\"baseline_examples_sha256\"]",
            "    assert len(HYDRO_ADDITIONS) == 6 and HYDRO_ADDITIONS <= set(examples)\n    assert canonical({name: value for name, value in examples.items() if name not in (new | HYDRO_ADDITIONS)}) == REPORT[\"baseline_examples_sha256\"]"
        ]
    ],
    "tests_local/test_native_cpu_integration.py": [
        [
            "assert len(current[\"tools\"]) == 214 and len(current[\"skills\"]) == 46",
            "assert len(current[\"tools\"]) == 220 and len(current[\"skills\"]) == 47"
        ],
        [
            "assert set(PROFILE[\"operations\"]) == set(NAMES)",
            "assert set(PROFILE[\"operations\"]) == (set(NAMES) | set(['HydroModelsPyFloCurveNumberRunoff', 'HydroModelsPySTEPSPrecipitationAdvection', 'EarthCatchmodLinearStoreStep', 'HydroModelsSuperflexUnitHydrograph', 'HydroModelsHydPyFlowScores', 'HydroModelsPyDEMTerrainDerivatives']))"
        ],
        [
            "assert len(operations) == 88 and len(acceptance[\"accepted_new_tools\"]) == 80 and len(acceptance[\"inactive_source_adapters\"]) == 8",
            "assert len(operations) == 89 and len(acceptance[\"accepted_new_tools\"]) == 86 and len(acceptance[\"inactive_source_adapters\"]) == 3"
        ]
    ]
}


def test_all_210_definitions_and_44_skills_preserved():
    data = catalog()
    assert len(data["tools"]) == 220 and len(data["skills"]) == 47
    for kind in ["tools", "skills"]:
        actual = {row["id"]: canonical(row) for row in data[kind]}
        assert all(actual[name] == expected for name, expected in META["baseline_definition_sha256"][kind].items())
    assert len(HYDRO_ADDITIONS) == 6 and not HYDRO_ADDITIONS.intersection(NAMES)
    assert {row["id"] for row in data["tools"]} - set(META["baseline_definition_sha256"]["tools"]) == set(NAMES) | HYDRO_ADDITIONS


def test_101_identity_rows_only_four_original_activations():
    manifests = json.loads((ROOT / "collection-manifests.json").read_text())
    rows = {str(row["id"]): row for group in manifests.values() for row in group["projects"]}
    assert len(rows) == 101
    for identifier, original in META["baseline_project_rows"].items():
        expected = deepcopy(original)
        if identifier in META["project_operations"]:
            expected.update(status="implemented", operations=[META["project_operations"][identifier]], active=True,
                implementation_state="original_bounded_operation", acceptance_status="candidate_cpu_validation_pending")
            expected.pop("reason", None)
            expected.pop("required_next_step", None)
        assert rows[identifier] == expected
    for group, expected in META["original_group_operation_sha256"].items():
        assert canonical(manifests[group]["operations"]) == expected
    assert manifests["native_cpu"]["projects"] == manifests["wflow43"]["projects"] == []


def test_all_735_baseline_nodeids_retained_as_required_inputs():
    proof = json.loads((ROOT / "cw-baseline-nodeids.json").read_text())
    assert len(proof["main"]) == 677 and len(proof["replacements58"]) == 58
    assert not set(proof["main"]) & set(proof["replacements58"])
    assert len(set(proof["main"]) | set(proof["replacements58"])) == 735


def test_original_and_replacement_counts_and_inactive_evidence():
    data = json.loads((ROOT / "collection-acceptance.json").read_text())
    assert data["accepted_original_collection_operations"] == len(data["accepted_original_tools"]) == 84
    assert len(data["accepted_functional_replacements"]) == 2
    assert set(data["accepted_new_tools"]) == set(data["accepted_original_tools"]) | set(data["accepted_functional_replacements"])
    assert data["inactive_source_adapters"] == META["inactive_source_adapters"]
    registry, _, _ = build_registry()
    assert len(data["inactive_source_adapters"]) == 3
    assert not set(data["inactive_source_adapters"]) & set(registry.names())
    assert all(row["error"] and row["traceback"] for row in data["inactive_source_adapters"].values())


@pytest.mark.parametrize("name", NAMES)
def test_new_schema_source_pins_and_true_native_execution(name, tmp_path):
    row = next(row for row in catalog()["tools"] if row["id"] == name)
    assert canonical(row) == META["new_tool_definitions_sha256"][name]
    module, entry = row["source_interface"]["entrypoint"]["callable"].split(":")
    function = getattr(importlib.import_module(module), entry)
    args = deepcopy(row["example_arguments"])
    before = deepcopy(args)
    context = ToolExecutionContext("cw-union-cpu", tmp_path, (name,), Settings(tool_timeout_seconds=0), Event())
    registry, _, _ = build_registry()
    result = ToolExecutor(registry).execute(ToolCall("cw-native-" + name, name, args), context)
    assert result.status == "ok", result.error
    assert result.artifacts == () and args == before
    assert result.data["provenance"]["implementation_sha256"] == sha(function.__wrapped__.__code__.co_filename)
    group = "wflow43" if name == "EarthWflowKinematicWaveReachStep" else "native_cpu"
    importlib.import_module("collection_acceptance." + group + "_checks").check(name, result.data, args, None)


def test_skill_document_changes_only_standard_suffix_and_real_state():
    records = {row["id"]: row for row in catalog()["skills"]}
    for record in META["skill_normalizations"]:
        current = records[record["id"]]
        path = ROOT / current["skill_file"]
        original = (ROOT / record["original_path"]).read_bytes()
        assert hashlib.sha256(original).hexdigest() == record["before_sha256"]
        assert path.read_bytes() == original + record["appended_utf8"].encode()
        assert sha(path) == record["after_sha256"]
        assert current["canonical_skill_file"] == current["skill_file"]
        assert current["delivery"]["availability_status"] == "tool_candidates_available_workflow_unverified"
        assert current["delivery"]["workflow_validation"] == current["registration_metadata"]["platform_validation"] == "not_run"
        assert current["registration_metadata"]["lifecycle"]["workflow_validation"] == "not_run"
        assert current["registration_metadata"]["lifecycle"]["platform_validation"] == "not_run"
        assert "Not deployed" in path.read_text() and "Not submitted" in path.read_text()


def test_runtime_patch_is_exact_one_approved_boolean_change():
    original = (ROOT / "catalog/source_delivery/cw-union-context/tools-u8.py").read_bytes()
    old = b'raise ToolFailure("invalid_arguments", str(exc)[:1800], retryable=True) from exc'
    new = old.replace(b"retryable=True", b"retryable=False")
    assert original.count(old) == 1
    assert original.count(b'raise ToolFailure("invalid_path", "Use a workspace-relative path with forward slashes", retryable=True)')==1
    assert original.count(b'raise ToolFailure("invalid_path", "Path escapes the workspace", retryable=True)')==1
    assert (ROOT / "geological_agent/tools.py").read_bytes() == original.replace(old, new, 1).replace(b'raise ToolFailure("invalid_path", "Use a workspace-relative path with forward slashes", retryable=True)',b'raise ToolFailure("invalid_path", "Use a workspace-relative path with forward slashes", retryable=False)',1).replace(b'raise ToolFailure("invalid_path", "Path escapes the workspace", retryable=True)',b'raise ToolFailure("invalid_path", "Path escapes the workspace", retryable=False)',1)


def test_registration_normalization_does_not_change_algorithm_schema_units_or_pins():
    changes = json.loads((ROOT / "cw-registration-normalizations.json").read_text())
    assert changes["frozen_contributions_modified"] is False
    assert sha(ROOT / changes["dependency_lock_path"]) == changes["dependency_lock_sha256"]
    tools = {row["id"]: row for row in catalog()["tools"]}
    original_wflow = json.loads((ROOT / "catalog/source_delivery/wflow43-r4/catalog-records.json").read_text())[0]
    current_wflow = deepcopy(tools["EarthWflowKinematicWaveReachStep"])
    assert original_wflow.pop("registration_metadata") == changes["before"]["EarthWflowKinematicWaveReachStep"]
    assert current_wflow.pop("registration_metadata") == changes["after"]["EarthWflowKinematicWaveReachStep"]
    assert original_wflow == current_wflow
    for name in NAMES:
        registration = tools[name]["registration_metadata"]
        assert registration == changes["after"][name]
        assert registration["source_url"] == tools[name]["metadata"]["upstream"]["url"]
        assert registration["metadata_profile"] == "scientific"
        assert registration["lifecycle"]["workflow_validation"] == registration["lifecycle"]["platform_validation"] == "not_run"


def test_inventory_and_context_patches_preserve_scientific_assertions():
    assert set(HYDRO_INVENTORY_PATCHES) == {row["path"] for row in META["test_inventory_patches"]}
    for row in META["test_inventory_patches"]:
        original = (ROOT / row["original_path"]).read_bytes()
        assert hashlib.sha256(original).hexdigest() == row["before_sha256"]
        changed = original
        for before, after in [*row["replacements"], *HYDRO_INVENTORY_PATCHES[row["path"]]]:
            assert changed.count(before.encode()) == 1
            changed = changed.replace(before.encode(), after.encode(), 1)
        assert (ROOT / row["path"]).read_bytes() == changed


def test_hpgl_is_internal_only_and_reused_87_are_not_new_tests():
    assert META["formal_packaging"] == "not_performed"
    assert META["HPGL_distribution_license_review"] == "pending"
    assert META["C87_evidence_reuse"]["new_test_count"] == 0
    for relative, expected in META["contribution_files_sha256"].items():
        assert sha(ROOT / relative) == expected

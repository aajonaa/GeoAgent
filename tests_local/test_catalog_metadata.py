"""Asset metadata contracts are distinct from executable tool contracts."""
import copy
import json
from pathlib import Path

import pytest

from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog, validate_registration_metadata


def test_all_catalog_tools_have_the_additive_metadata_envelope():
    current = catalog()
    assert current["asset_metadata_version"] == "1.0.0"
    assert len(current["tools"]) == 376
    for spec in current["tools"]:
        validate_registration_metadata(spec)
        assert spec["registration_metadata"]["official_protocol"]["applicability"] in {
            "applicable", "not_applicable", "unknown"
        }


def test_protocol_applicability_does_not_conflate_unknown_and_not_applicable():
    value = copy.deepcopy(catalog()["tools"][0])
    value["registration_metadata"]["official_protocol"] = {
        "applicability": "not_applicable", "name": None, "version": None
    }
    validate_registration_metadata(value)
    value["registration_metadata"]["official_protocol"] = {
        "applicability": "unknown", "name": None, "version": None
    }
    validate_registration_metadata(value)


@pytest.mark.parametrize("protocol", [
    {"applicability": "applicable", "name": None, "version": "1.0"},
    {"applicability": "applicable", "name": "OGC", "version": None},
    {"applicability": "not_applicable", "name": None, "version": "1.0"},
    {"applicability": "other", "name": None, "version": None},
])
def test_invalid_protocol_metadata_is_rejected(protocol):
    value = copy.deepcopy(catalog()["tools"][0])
    value["registration_metadata"]["official_protocol"] = protocol
    with pytest.raises(ValueError):
        validate_registration_metadata(value)


def test_source_commit_and_runtime_environment_are_separate():
    spec = copy.deepcopy(catalog()["tools"][0]["registration_metadata"])
    assert "source_commit" in spec
    assert set(spec["runtime"]) == {"python", "dependency_lock", "environment_version"}
    spec["source_commit"] = "source-sha"
    spec["runtime"]["environment_version"] = "runtime-image"
    assert spec["source_commit"] != spec["runtime"]["environment_version"]


def test_source_delivery_examples_cover_all_revised_tools():
    root = Path(__file__).resolve().parents[1]
    examples = json.loads((root / "catalog/source_delivery/examples.json").read_text(encoding="utf-8"))
    revised = {tool["id"] for tool in catalog()["tools"]
               if tool.get("source_interface", {}).get("status") == "source_revised_unverified"}
    assert set(examples) == revised

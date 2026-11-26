"""Regressions for the approved first-wave corrective changes."""
from copy import deepcopy
from importlib import metadata
from pathlib import Path
from threading import Event

from geological_agent.bootstrap import build_registry
from geological_agent.contracts import ToolCall
from geological_agent.settings import Settings
from geological_agent.tools import ToolExecutionContext, ToolExecutor
from geological_agent.geology.source_registry import source_tools
from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog
from source_asset_checks.run import check_assets


def test_dependency_profile_preserves_pkg_resources_compatibility():
    assert metadata.version("setuptools") == "80.9.0"
    import pkg_resources
    assert Path(pkg_resources.__file__).is_file()


def test_invalid_crs_is_a_native_parameter_error(tmp_path):
    spec = next(x for x in catalog()["tools"] if x["id"] == "GeoPandasSpatialJoin")
    args = {**deepcopy(spec["example_arguments"]), "crs": "not-a-crs"}
    registry, _, _ = build_registry()
    ctx = ToolExecutionContext("crs-regression", tmp_path, (spec["id"],), Settings(), Event())
    result = ToolExecutor(registry).execute(ToolCall("invalid-crs", spec["id"], args), ctx)
    assert result.status == "error" and result.error.code == "invalid_arguments"
    assert result.error.retryable is False


def test_new_file_examples_are_actual_safe_asset_fixtures():
    root = Path(__file__).resolve().parents[1]
    expected = {"GeoFionaDatasetInfo", "GeoRasterioWindow", "SeismicObsPyBandpass"}
    found = set()
    for spec in catalog()["tools"]:
        if spec["id"] not in expected:
            continue
        relative = Path(spec["example_arguments"]["input_path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        assert relative.parts[:2] == ("assets", "earth-python-wave1")
        assert (root / relative).is_file()
        found.add(spec["id"])
    assert found == expected


def test_new_skills_pass_the_unchanged_canonical_asset_checker():
    current = catalog()
    rows = check_assets(current, source_tools())
    selected = [row for row in rows if row["skill"].startswith("earth-python-")]
    assert len(selected) == 3 and all(row["status"] == "passed" for row in selected)
    for skill in current["skills"]:
        if skill["id"].startswith("earth-python-"):
            assert skill["delivery"]["source_candidates"] == skill["tool_references"]
            assert skill["delivery"]["unavailable_references"] == []
            assert skill["delivery"]["workflow_validation"] == "not_run"
            assert skill["registration_metadata"]["platform_validation"] == "not_run"

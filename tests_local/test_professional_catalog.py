from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from threading import Event

import pytest

from geological_agent.bootstrap import create_agent
from geological_agent.contracts import ToolCall
from geological_agent.geology.source_registry import READY, native_name, source_tools
from geological_agent.tools import ToolExecutionContext, ToolFailure
from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog
from source_asset_checks.helpers import oracle
from source_asset_checks.run import populate

ROOT = Path(__file__).resolve().parents[1]
SPECS = source_tools()
READY_SPECS = {name: spec for name, spec in SPECS.items() if spec.get("source_interface", {}).get("status") == READY}


@pytest.fixture(scope="module")
def agent():
    return create_agent(object())


@pytest.fixture(scope="module")
def examples():
    return json.loads((ROOT / "catalog/source_delivery/examples.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def assets(tmp_path_factory, examples):
    directory = tmp_path_factory.mktemp("professional-inputs")
    populate(directory, examples, SPECS)
    return directory


@pytest.mark.parametrize("source_id", sorted(READY_SPECS))
def test_every_ready_source_executes_through_native_runtime(agent, examples, assets, source_id):
    spec = READY_SPECS[source_id]
    name = native_name(spec)
    native = agent.tools.get(name).definition
    assert native.input_schema == spec["input_schema"]
    assert native.result_schema == spec["output_schema"]
    context = ToolExecutionContext("native-acceptance", assets, (name,), agent.settings, Event())
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (assets / "assets").rglob("*") if p.is_file()}
    result = agent.executor.execute(ToolCall("test-" + name, name, examples[source_id]), context)
    assert result.status == "ok", result.error
    # ArtifactRef does not claim a source hash; compute actual file hashes for
    # the source oracle while retaining its pixel/content/size assertions.
    artifacts = [{**asdict(a), "sha256": hashlib.sha256((assets / a.path).read_bytes()).hexdigest()}
                 for a in result.artifacts]
    oracle(source_id, {"ok": True, "result": result.data, "artifacts": artifacts}, assets)
    assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (assets / "assets").rglob("*") if p.is_file()}
    assert all((assets / a.path).is_file() for a in result.artifacts)
    assert not any(key.split(".")[0] in {"asset_catalog", "asset_bridge"} for key in sys.modules)


def test_all_registered_source_tools_are_discoverable(agent):
    assert len(SPECS) == 220 and len(READY_SPECS) == 220
    reachable = {name for summary in agent.skills.registry.list() for name in agent.skills.load(summary.id).tool_names}
    assert {native_name(spec) for spec in READY_SPECS.values()} <= reachable
    assert len(agent.skills.source_statuses) == len(catalog()["skills"]) == 47
    assert len(agent.skills.unavailable_skills) == 0
    from geological_agent.imaging import SCHEMAS as IMAGE_SCHEMAS
    assert set(agent.tools._tools) - set(agent.base_tools) == {native_name(spec) for spec in READY_SPECS.values()} | set(IMAGE_SCHEMAS)
    for spec in SPECS.values():
        if spec.get("source_interface", {}).get("status") != READY:
            # Blocked placeholders may lack a native function definition.
            # Neither their asset ID nor a declared native name may execute.
            with pytest.raises(ToolFailure):
                agent.tools.get(spec["id"])
            name = spec.get("function_definition", {}).get("function", {}).get("name")
            if name:
                with pytest.raises(ToolFailure):
                    agent.tools.get(name)


@pytest.mark.parametrize("path", ["../outside.csv", "/etc/passwd", "C:/secret.csv", "..\\secret.csv"])
def test_source_file_tools_reject_external_paths(agent, tmp_path, path):
    name = "NaturalHazardCountRecords"
    context = ToolExecutionContext("bad-path", tmp_path, (name,), agent.settings, Event())
    result = agent.executor.execute(ToolCall("path", name, {"source": path}), context)
    assert result.status == "error" and result.error.code == "invalid_path"


def test_unavailable_skill_reports_exact_gap_without_exposure(agent, tmp_path, monkeypatch):
    item = {"id": "test_missing_data", "name": "Synthetic blocked skill", "description": "Test", "when_to_use": "Test"}
    monkeypatch.setattr(agent.skills, "unavailable_skills", [item])
    monkeypatch.setitem(agent.skills.source_statuses, item["id"], {"unavailable_tools": [{"name": "test_missing", "reason": "Synthetic missing prerequisite"}]})
    context = ToolExecutionContext("blocked", tmp_path, ("skill_load",), agent.settings, Event())
    result = agent.executor.execute(ToolCall("blocked", "skill_load", {"skill_id": item["id"]}), context)
    assert result.error.code == "skill_unavailable"
    assert result.data["unavailable_tools"]


def test_changed_input_does_not_hit_numeric_pure_cache(agent, assets):
    name = "NaturalHazardCountRecords"
    context = ToolExecutionContext("files", assets, (name,), agent.settings, Event())
    path = assets / "mutable.csv"
    path.write_text("value\n1\n", encoding="utf-8")
    first = agent.executor.execute(ToolCall("first", name, {"source": "mutable.csv"}), context)
    path.write_text("value\n1\n2\n", encoding="utf-8")
    second = agent.executor.execute(ToolCall("second", name, {"source": "mutable.csv"}), context)
    assert first.data["count"] == 1 and second.data["count"] == 2 and not second.cached


@pytest.fixture(autouse=True)
def synthetic_usgs_transport(monkeypatch):
    from legacy.ToolsAgent.ToolsFuns.GeoEval import native_recovery
    from source_asset_checks.recovered_cases import usgs_fixture
    monkeypatch.setattr(native_recovery, "_usgs_response", usgs_fixture)

"""The canonical catalog is the sole registration source; no live model calls."""
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from geological_agent.bootstrap import build_registry
from geological_agent.geology import source_registry
from geological_agent.skills import SkillLoader, SkillRegistry
from geological_agent.team.library import LibraryCatalog
from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog, ROOT
from source_asset_checks.run import check_assets


def skill_id(spec):
    return source_registry.EXISTING_SKILLS.get(spec["id"], spec["id"].replace("-", "_"))


@pytest.mark.parametrize("web_enabled", ["0", "1"])
def test_all_skills_are_catalogued_without_runtime_extras(monkeypatch, web_enabled):
    monkeypatch.setenv("GEOTOOL_WEB_ENABLED", web_enabled)
    registry, loader, _ = build_registry(human_input=True)
    expected = {skill_id(spec) for spec in catalog()["skills"]}
    assert len(expected) == 97
    assert {s.id for s in loader.registry.list()} == expected
    assert set(loader.source_statuses) == expected
    library = LibraryCatalog(human_input=True)
    counts = library.summary()["counts"]
    assert counts["skills"] == counts["catalog_skills"] == 97
    runtime_count = 10 + (2 if web_enabled == "1" else 0)
    assert counts["tools"] == counts["registered_tools"] == len(registry.names()) == 457 + runtime_count
    assert counts["professional_tools"] == 457 and counts["runtime_tools"] == runtime_count
    assert all(row["scope"] != "runtime" for row in library.skills.values())


@pytest.mark.parametrize("identifier,tools", [
    ("geological_table_analysis", ("read_file", "write_file", "execute_python", "HydroErrorMetrics", "ScientificCurveFit", "SpatialMoranI")),
    ("image_workflow", ("GeoImageInspect", "GeoImageTransform", "GeoRasterPreview", "GeoImageAnalyze", "read_file")),
])
def test_former_local_skill_metadata_and_tool_links(identifier, tools):
    registry, loader, _ = build_registry()
    spec = next(s for s in catalog()["skills"] if skill_id(s) == identifier)
    text = (ROOT / spec["skill_file"]).read_text(encoding="utf-8")
    _, front, body = text.split("---", 2)
    metadata = yaml.safe_load(front)
    skill = loader.load(identifier)
    assert skill.instructions == body.strip()
    assert skill.required_inputs == tuple(metadata["required_inputs"])
    assert skill.constraints == tuple(metadata["constraints"])
    assert skill.expected_outputs == tuple(metadata["expected_outputs"])
    assert skill.tool_names == tools == tuple(spec["tool_references"])
    assert loader.registry.list(identifier.split("_")[0])
    library = LibraryCatalog()
    detail = library.detail("skills", identifier)
    assert detail["instructions"] == skill.instructions
    assert detail["tool_count"] == detail["available_tool_count"] == len(tools)
    for tool in detail["tools"]:
        assert registry.get(library.tools[tool["id"]]["native_name"])
        assert any(s["id"] == identifier for s in library.tools[tool["id"]]["skills"])


def test_old_folder_is_not_a_registration_source(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Runtime must not scan the old skill directory")
    monkeypatch.setattr(SkillLoader, "from_directory", forbidden)
    _, loader, _ = build_registry()
    assert len(loader.registry.list()) == 97


def test_removed_catalog_entry_is_not_silently_added_back(monkeypatch):
    original = deepcopy(catalog())
    original["skills"] = [s for s in original["skills"] if s["id"] != "image-workflow"]
    monkeypatch.setattr(source_registry, "catalog", lambda: original)
    _, loader, _ = build_registry()
    assert "image_workflow" not in {s.id for s in loader.registry.list()}


def test_catalog_document_and_dependency_contracts():
    rows = check_assets(catalog(), source_registry.source_tools())
    assert len(rows) == 97 and all(row["status"] == "passed" for row in rows), rows
    root = Path(__file__).resolve().parents[1]
    assert not list((root / "geological_agent/geology/skills").glob("*/SKILL.md"))


def test_missing_runtime_dependency_is_explicit_not_invented(monkeypatch):
    spec = deepcopy(next(s for s in catalog()["skills"] if s["id"] == "image-workflow"))
    monkeypatch.setattr(source_registry, "catalog", lambda: {"tools": [], "skills": [spec]})
    loader = source_registry.load_source_skills(SkillLoader(SkillRegistry()), {})
    assert not loader.registry.list()
    assert loader.unavailable_skills[0]["id"] == "image_workflow"
    assert {t["name"] for t in loader.source_statuses["image_workflow"]["unavailable_tools"]} == set(spec["tool_references"])


def test_document_cannot_escape_catalog(monkeypatch):
    spec = deepcopy(next(s for s in catalog()["skills"] if s["id"] == "image-workflow"))
    spec["skill_file"] = "../outside/SKILL.md"
    monkeypatch.setattr(source_registry, "catalog", lambda: {"tools": [], "skills": [spec]})
    with pytest.raises(ValueError, match="canonical catalog"):
        build_registry()

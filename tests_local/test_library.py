"""Read-only library contracts. No live models or professional algorithms run."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from geological_agent.bootstrap import build_registry, create_agent
from geological_agent.team.library import LibraryCatalog
from geological_agent.team import library as library_module
from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog
from test_model_settings import group, TOKEN


@pytest.fixture(scope="module")
def assets():
    return LibraryCatalog(human_input=True)


def test_library_and_agent_share_the_same_registrations(assets):
    registry, skills, base = build_registry(human_input=True)
    agent = create_agent(None, human_input=True)
    assert registry.names() == agent.tools.names()
    listed = {row["native_name"] for row in assets.tools.values() if row["status"] == "registered"}
    assert listed == set(registry.names())
    assert set(assets.base_tools) == set(base)
    assert {s.id for s in skills.registry.list()} == {
        row["id"] for row in assets.skills.values() if row["status"] != "blocked"
    }


def test_counts_are_derived_and_professional_and_runtime_are_separate(assets):
    source, result = catalog(), assets.summary()
    assert result["counts"]["professional_tools"] == len(source["tools"])
    assert result["counts"]["catalog_skills"] == len(source["skills"])
    assert result["counts"]["tools"] == len(result["tools"])
    assert result["counts"]["skills"] == len(result["skills"])
    assert result["counts"]["registered_tools"] == sum(row["status"] == "registered" for row in result["tools"])
    from geological_agent.imaging import SCHEMAS as IMAGE_SCHEMAS
    runtime_names = {row["native_name"] for row in result["tools"] if row["scope"] == "runtime"}
    assert runtime_names == set(assets.base_tools) | set(IMAGE_SCHEMAS)
    assert result["counts"]["runtime_tools"] == len(runtime_names)
    assert len(assets.revision) == 12


def test_full_schema_is_exactly_the_executable_definition(assets):
    registry, _, _ = build_registry(human_input=True)
    for row in assets.tools.values():
        if row["status"] != "registered":
            continue
        actual = registry.get(row["native_name"]).definition
        assert row["input_schema"] == actual.input_schema
        assert row["output_schema"] == actual.result_schema
        assert row["when_to_use"] == actual.when_to_use


def test_skill_links_are_direct_bidirectional_and_complete(assets):
    for row in assets.skills.values():
        assert row["tool_count"] == len(row["tools"])
        assert row["available_tool_count"] == sum(t["status"] == "registered" for t in row["tools"])
        for tool in row["tools"]:
            assert tool["id"] in assets.tools
            assert any(s["id"] == row["id"] for s in assets.tools[tool["id"]]["skills"])


def test_registered_skill_document_matches_actual_runtime_instructions(assets):
    _, loader, _ = build_registry(human_input=True)
    for summary in loader.registry.list():
        assert assets.detail("skills", summary.id)["instructions"] == loader.load(summary.id).instructions
    assert "GeoMagnitudeToEnergy" in assets.detail("skills", "earthquake_energy")["instructions"]


def test_blocked_tools_and_skills_are_visible_but_have_no_execution_example(assets):
    blocked = [row for row in assets.tools.values() if row["status"] == "blocked"]
    assert blocked
    for row in blocked:
        assert row["reason"]
        assert not row["example_prompt"]
        assert row["example_arguments"] is None
    blocked_skills = [row for row in assets.skills.values() if row["status"] == "blocked"]
    assert blocked_skills
    assert all(row["reason"] and not row["example_prompt"] for row in blocked_skills)


def test_summary_is_lightweight_and_does_not_disclose_server_internals(assets):
    result = assets.summary()
    for row in result["tools"]:
        assert "input_schema" not in row and "output_schema" not in row
        assert "example_arguments" not in row
    for row in result["skills"]:
        assert "instructions" not in row
    text = json.dumps(result)
    assert "entrypoint" not in text and "api_token" not in text
    assert str(library_module.ROOT) not in text


def test_details_are_defensive_copies(assets):
    row = assets.detail("tools", "GeoMagnitudeToEnergy")
    row["input_schema"].clear()
    assert assets.detail("tools", "GeoMagnitudeToEnergy")["input_schema"]


@pytest.mark.parametrize("kind,identifier", [
    ("tools", "not-a-tool"), ("skills", "../team.sqlite3"), ("files", "team.sqlite3"),
])
def test_unknown_ids_are_not_paths(assets, kind, identifier):
    with pytest.raises(KeyError):
        assets.detail(kind, identifier)


def test_document_reader_cannot_escape_canonical_skill_directory(tmp_path):
    secret = tmp_path / "SKILL.md"
    secret.write_text("PRIVATE-CONTENT", encoding="utf-8")
    assert LibraryCatalog._document(str(secret)) == ""
    assert LibraryCatalog._document("../team.sqlite3") == ""


def test_catalog_endpoints_require_login_and_are_read_only(group):
    app, (alice, bob, _), _, calls = group
    with TestClient(app, base_url="http://127.0.0.1") as anonymous:
        assert anonymous.get("/api/library").status_code == 401
        assert anonymous.get("/api/library/tools/GeoMagnitudeToEnergy").status_code == 401
    result = alice.get("/api/library")
    assert result.status_code == 200
    assert bob.get("/api/library").json()["revision"] == result.json()["revision"]
    assert alice.get("/api/library/tools/GeoMagnitudeToEnergy").status_code == 200
    assert alice.get("/api/library/skills/earthquake_energy").status_code == 200
    assert alice.get("/api/library/tools/not-real").status_code == 404
    for method in ("post", "put", "delete"):
        assert getattr(alice, method)("/api/library").status_code == 405
    assert not calls
    assert app.state.store.db.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    assert TOKEN not in result.text


def test_logout_revokes_catalog_access(group):
    _, (alice, _, _), _, _ = group
    assert alice.get("/api/library").status_code == 200
    assert alice.post("/api/logout").status_code == 200
    assert alice.get("/api/library").status_code == 401


def test_frontend_assets_served_and_arbitrary_files_not_exposed(group):
    _, (alice, _, _), _, _ = group
    html = alice.get("/").text
    assert 'id="library-open"' in html and 'id="library-detail"' in html
    for name in ("library.js", "library.css"):
        response = alice.get("/assets/" + name)
        assert response.status_code == 200
    assert alice.get("/assets/model-profiles.key").status_code == 404
    js = alice.get("/assets/library.js").text
    assert ".innerHTML" not in js
    assert "localStorage" not in js and "sessionStorage" not in js


def test_frontend_interaction_regression():
    node = shutil.which("node")
    assert node, "Node is required for the library UI regression; do not silently skip."
    script = Path(__file__).with_name("library-regression.js")
    client = Path(library_module.__file__).parent / "web" / "library.js"
    result = subprocess.run([node, str(script), str(client)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "library UI checks passed" in result.stdout

"""Acceptance gates for the additional >=101-operation intake, never demos.

Run only in its explicitly merged candidate. Individual groups provide the
independent scientific oracles; this file tests additive/runtime boundaries.
"""
import ast
import copy
import hashlib
import json
from pathlib import Path
from threading import Event

import pytest
from jsonschema import Draft202012Validator

from geological_agent.bootstrap import build_registry
from geological_agent.settings import Settings
from geological_agent.tools import ToolCall, ToolExecutionContext, ToolExecutor
from legacy.ToolsAgent.ToolsFuns.source_contracts import ROOT, catalog, validate_registration_metadata

DELIVERY = ROOT / "catalog/source_delivery/github-expansion-20261025"
MERGE = json.loads((DELIVERY / "MERGE.json").read_text(encoding="utf-8"))
NAMES = tuple(MERGE["added_tool_ids"])


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def test_at_least_101_net_new_operations_not_repositories_or_aliases():
    current = catalog()
    assert len(NAMES) == len(set(NAMES)) >= 101
    assert len(current["tools"]) == 229 + len(NAMES) == MERGE["professional_tools_after"]
    assert len(current["skills"]) == MERGE["skills_after"]
    assert {row["id"] for row in current["tools"][229:]} == set(NAMES)
    assert not set(NAMES) & set(MERGE["baseline_tool_ids"])
    assert len({row["capability_key"] for row in MERGE["operations"]}) == len(NAMES)


def test_original_229_tools_50_skills_and_all_examples_are_unchanged():
    current = catalog()
    assert canonical(current["tools"][:229]) == MERGE["old_tools_sha256"]
    assert canonical(current["skills"][:50]) == MERGE["old_skills_sha256"]
    examples = json.loads((ROOT / "catalog/source_delivery/examples.json").read_text(encoding="utf-8"))
    assert canonical({name: value for name, value in examples.items() if name not in NAMES}) == MERGE["old_examples_sha256"]


@pytest.mark.parametrize("name", NAMES)
def test_each_addition_has_closed_scientific_contract_and_real_function(name):
    spec = next(row for row in catalog()["tools"] if row["id"] == name)
    validate_registration_metadata(spec)
    for schema in (spec["input_schema"], spec["output_schema"]):
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False
    for key in ("units", "artifacts", "provenance"):
        assert key in spec["output_schema"]["required"]
    Draft202012Validator(spec["input_schema"]).validate(spec["example_arguments"])
    assert spec["function_definition"]["function"]["parameters"] == spec["input_schema"]
    module, function = spec["source_interface"]["entrypoint"]["callable"].split(":")
    assert module.startswith("geological_agent.geology.github_expansion_")
    assert not spec["source_interface"]["entrypoint"].get("bound_arguments")
    path = ROOT / (module.replace(".", "/") + ".py")
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function]
    assert len(matches) == 1
    decorated = [d for d in matches[0].decorator_list if isinstance(d, ast.Call) and
                 isinstance(d.func, ast.Name) and d.func.id == "operation" and d.args and
                 isinstance(d.args[0], ast.Constant) and d.args[0].value == name]
    assert len(decorated) == 1
    assert not any(isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and
                   isinstance(node.exc.func, ast.Name) and node.exc.func.id == "NotImplementedError"
                   for node in ast.walk(matches[0]))


@pytest.fixture(scope="module")
def registered():
    return build_registry()[0]


@pytest.mark.parametrize("name", NAMES)
def test_every_addition_rejects_undeclared_parameter_without_execution(name, registered, tmp_path):
    spec = next(row for row in catalog()["tools"] if row["id"] == name)
    args = copy.deepcopy(spec["example_arguments"])
    args["_undeclared_command"] = "must_not_run"
    context = ToolExecutionContext("expansion-contract", tmp_path, (name,), Settings(), Event())
    result = ToolExecutor(registered).execute(ToolCall("unknown-arg", name, args), context)
    assert result.status == "error"
    assert result.error.code == "invalid_arguments"
    assert result.error.retryable is False
    assert not result.artifacts


def test_new_skills_are_small_coherent_catalogued_workflows():
    covered = set()
    for skill in catalog()["skills"][50:]:
        names = skill["tool_references"]
        assert 1 <= len(names) <= 12
        assert set(names) <= set(NAMES)
        assert (ROOT / skill["skill_file"]).is_file()
        covered.update(names)
    assert covered == set(NAMES)

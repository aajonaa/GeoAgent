"""Construct a fresh, strictly additive >=101-operation CPU test candidate.

This is a source-staging command, not an acceptance report or service switch.
All four contribution generators must have completed before this command runs.
"""
import argparse
import ast
import copy
import hashlib
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

GROUPS = ("geophysics", "remote", "geology", "spatial")
DELIVERY = Path("catalog/source_delivery/github-expansion-20261025")


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def relative_file(root, name):
    p = Path(name)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("Expected a repository-relative file: " + name)
    result = root / p
    if result.is_symlink() or not result.is_file() or not result.resolve().is_relative_to(root.resolve()):
        raise ValueError("Missing or escaping contribution file: " + name)
    return result


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        raise ValueError("Baseline changed at " + label)
    return text.replace(old, new, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--contributions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--flow-module", required=True, type=Path)
    args = parser.parse_args()
    baseline, contributions, output = (p.resolve() for p in (args.baseline, args.contributions, args.output))
    if output.exists() or output == baseline or output.is_relative_to(baseline) or output.is_relative_to(contributions):
        raise ValueError("Output must be a fresh directory outside source trees")
    module = importlib.util.spec_from_file_location("flowing", args.flow_module)
    flow = importlib.util.module_from_spec(module)
    sys.modules["flowing"] = flow
    module.loader.exec_module(flow)
    task, Flow = flow.task, flow.Flow

    @task
    def collect():
        old = read(baseline / "catalog/registry.json")
        old_examples = read(baseline / "catalog/source_delivery/examples.json")
        if len(old["tools"]) != 229 or len(old["skills"]) != 50:
            raise ValueError("Expected explicit 229-tool / 50-Skill baseline")
        packages = []
        for group in GROUPS:
            root = contributions / DELIVERY / "groups" / group
            additions = read(root / "catalog-additions.json")
            operations = read(root / "candidate-operations.json")
            if operations["group"] != group:
                raise ValueError("Contribution group mismatch")
            packages.append({"group": group, "tools": additions["tools"], "skills": additions["skills"],
                             "examples": read(root / "examples-additions.json"), "operations": operations["operations"]})
        return {"old": old, "old_examples": old_examples, "packages": packages}

    def check(collect):
        seen = {row["id"] for row in collect["old"]["tools"]}
        skills = {row["id"] for row in collect["old"]["skills"]}
        capabilities = set()
        added = 0
        for package in collect["packages"]:
            group = package["group"]
            module_name = "geological_agent.geology.github_expansion_" + group
            module_path = relative_file(contributions, module_name.replace(".", "/") + ".py")
            functions = {node.name for node in ast.parse(module_path.read_text(encoding="utf-8-sig")).body if isinstance(node, ast.FunctionDef)}
            rows = {item["tool_id"]: item for item in package["operations"]}
            names = {item["id"] for item in package["tools"]}
            if len(rows) != len(package["operations"]) or set(rows) != names or set(package["examples"]) != names:
                raise ValueError("Operation/schema/example mismatch in " + group)
            for item in package["tools"]:
                name = item["id"]
                if name in seen:
                    raise ValueError("Duplicate baseline or contribution ID: " + name)
                seen.add(name)
                row = rows[name]
                for key in ("capability_key", "upstream_callable", "scientific_task", "distinct_from_existing", "numeric_oracle"):
                    if not isinstance(row.get(key), str) or not row[key].strip():
                        raise ValueError("Missing scientific admission field " + name + ":" + key)
                if row["capability_key"] in capabilities:
                    raise ValueError("Duplicate declared scientific capability: " + row["capability_key"])
                capabilities.add(row["capability_key"])
                interface = item["source_interface"]
                entry = interface["entrypoint"]
                expected, function = entry["callable"].split(":")
                if interface["kind"] != "github_expansion_" + group or expected != module_name or function not in functions:
                    raise ValueError("Entry must bind a concrete function in its fixed group module: " + name)
                if entry.get("argument_parameter") != "args" or entry.get("bound_arguments", {}):
                    raise ValueError("Parameterized aliases are not additional tools: " + name)
                for key in ("input_schema", "output_schema"):
                    if item[key].get("type") != "object" or item[key].get("additionalProperties") is not False:
                        raise ValueError("Require closed object schema: " + name + ":" + key)
                for key in ("units", "artifacts", "provenance"):
                    if key not in item["output_schema"]["properties"]:
                        raise ValueError("Missing output contract: " + name + ":" + key)
                meta = item["registration_metadata"]
                upstream = item["metadata"]["upstream"]
                if not re.fullmatch(r"[0-9a-f]{40}", meta.get("source_commit", "")):
                    raise ValueError("Missing exact reviewed source commit: " + name)
                if not upstream.get("license") or not upstream.get("url", "").startswith("https://github.com/"):
                    raise ValueError("Missing GitHub origin/license: " + name)
                pins = upstream.get("requirements", [])
                if not pins or any("==" not in pin for pin in pins):
                    raise ValueError("Require pinned scientific dependencies: " + name)
                relative_file(contributions, meta["runtime"]["dependency_lock"])
                for field in interface.get("path_fields", []):
                    value = package["examples"][name].get(field)
                    if value is not None:
                        for path in value if isinstance(value, list) else [value]:
                            relative_file(contributions, path)
                added += 1
            for skill in package["skills"]:
                if skill["id"] in skills:
                    raise ValueError("Duplicate Skill: " + skill["id"])
                skills.add(skill["id"])
                if not set(skill["tool_references"]) <= seen:
                    raise ValueError("Skill references absent operations")
                relative_file(contributions, skill["skill_file"])
        if added < 101:
            raise ValueError(f"Need at least 101 net-new operations, received {added}; no completion/count claim")

    @task(depends_on=[collect], validate=check)
    def materialize(collect):
        shutil.copytree(baseline, output, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "node_modules", ".venv"))
        catalog = copy.deepcopy(collect["old"])
        examples = copy.deepcopy(collect["old_examples"])
        operations = []
        for package in collect["packages"]:
            group = package["group"]
            files = [Path("geological_agent/geology/github_expansion_" + group + ".py"),
                     Path("tests_local/test_github_expansion_" + group + ".py")]
            trees = [DELIVERY / "groups" / group, Path("assets/github-expansion-" + group)]
            for skill in package["skills"]:
                trees.append(Path(skill["skill_file"]).parent)
            for tree in trees:
                files.extend(p.relative_to(contributions) for p in (contributions / tree).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
            for relative in sorted(set(files)):
                source = relative_file(contributions, relative.as_posix())
                destination = output / relative
                if destination.exists():
                    raise ValueError("Contribution would replace baseline file: " + str(relative))
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            catalog["tools"].extend(package["tools"])
            catalog["skills"].extend(package["skills"])
            examples.update(package["examples"])
            operations.extend(package["operations"])
        tools_after, skills_after = len(catalog["tools"]), len(catalog["skills"])
        dump(output / "catalog/registry.json", catalog)
        dump(output / "catalog/source_delivery/examples.json", examples)
        source = output / "geological_agent/geology/source_registry.py"
        old = 'ENTRY_MODULES = {\n'
        new = old + "".join('    "geological_agent.geology.github_expansion_' + group + '",\n' for group in GROUPS)
        source.write_text(replace_once(source.read_text(encoding="utf-8"), old, new, "ENTRY_MODULES"), encoding="utf-8")
        worker = output / "geotool/domain_worker.py"
        text = worker.read_text(encoding="utf-8")
        old = 'if spec["kind"] in {"github_first_batch", "github_minerals"}:'
        new = 'if spec["kind"] in {"github_first_batch", "github_minerals", ' + ', '.join('"github_expansion_' + group + '"' for group in GROUPS) + '}:'
        text = replace_once(text, old, new, "worker kind whitelist")
        old = '"github_minerals": "geological_agent.geology.github_minerals"}[spec["kind"]]'
        new = '"github_minerals": "geological_agent.geology.github_minerals", ' + ', '.join('"github_expansion_' + group + '": "geological_agent.geology.github_expansion_' + group + '"' for group in GROUPS) + '}[spec["kind"]]'
        worker.write_text(replace_once(text, old, new, "worker module whitelist"), encoding="utf-8")
        for filename in ("test_catalog_metadata.py", "test_professional_catalog.py", "test_unified_skills.py"):
            p = output / "tests_local" / filename
            text = p.read_text(encoding="utf-8")
            text = re.sub(r"\b229\b", str(tools_after), text)
            if filename != "test_catalog_metadata.py":
                text = re.sub(r"\b50\b", str(skills_after), text)
            p.write_text(text, encoding="utf-8")
        p = output / "tests_local/test_github_minerals.py"
        text = p.read_text(encoding="utf-8")
        text = replace_once(text, 'assert len(current["tools"]) == 229 and len(current["skills"]) == 50',
                            f'assert len(current["tools"]) == {tools_after} and len(current["skills"]) == {skills_after}', "old mineral count")
        text = replace_once(text, 'current["tools"][220:]', 'current["tools"][220:229]', "old mineral increment")
        text = replace_once(text, 'if k not in NAMES', 'if k in {t["id"] for t in current["tools"][:220]}', "original 220 examples")
        p.write_text(text, encoding="utf-8")
        info = {"state": "merged_source_unverified", "deployed": False, "gpu_used": False,
                "professional_tools_before": 229, "professional_tools_after": tools_after,
                "skills_before": 50, "skills_after": skills_after, "additional_operations": tools_after - 229,
                "old_tools_sha256": canonical(collect["old"]["tools"]),
                "old_skills_sha256": canonical(collect["old"]["skills"]),
                "old_examples_sha256": canonical(collect["old_examples"]),
                "baseline_tool_ids": [row["id"] for row in collect["old"]["tools"]],
                "added_tool_ids": [row["tool_id"] for row in operations], "operations": operations,
                "semantic_review": "requires_review_of_declared_distinctions", "numeric_acceptance": "not_run"}
        dump(output / DELIVERY / "MERGE.json", info)
        return info

    workflow = Flow(materialize, max_workers=1, fail_fast=True)
    results = workflow.run()
    for result in results.values():
        if result.error is not None:
            raise result.error
    result = workflow.value(materialize)
    print(json.dumps({key: result[key] for key in ("state", "additional_operations", "professional_tools_after", "skills_after", "deployed")}))


if __name__ == "__main__":
    main()

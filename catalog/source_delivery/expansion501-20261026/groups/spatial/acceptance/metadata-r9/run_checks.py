"""Actual native registry attempt and metadata fidelity; no scientific calls.

The source registry is copied unchanged, including its existing module allowlist.
A rejected module is reported as blocked, never bypassed or counted as accepted.
"""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import traceback
import unittest

AREA = Path(__file__).resolve().parent
GROUP = AREA.parents[1]
ROOT = GROUP.parents[4]
PYTHON = ROOT / "catalog/source_delivery/expansion501-20261026/groups/geology/acceptance/local-r6-gpr-20261026/venv/Scripts/python.exe"
PYTHON_SHA = "8e11f5c0c4cdea43849e4d800c47c2714e900e27612bf5658b4a87b66a"
# Exact executable binding from the existing reviewed runtime identity.
PYTHON_SHA = "8e11f5c0c4cdea438059feea1b750721929433374b389674c8368ae8bfcbf525"
COPY_FILES = (
    "geological_agent/__init__.py", "geological_agent/contracts.py",
    "geological_agent/settings.py", "geological_agent/tools.py", "geological_agent/skills.py",
    "geological_agent/geology/__init__.py", "geological_agent/geology/source_registry.py",
    "geological_agent/geology/expansion501_spatial.py",
    "legacy/ToolsAgent/__init__.py", "legacy/ToolsAgent/ToolsFuns/__init__.py",
    "legacy/ToolsAgent/ToolsFuns/GeoEval/__init__.py",
    "legacy/ToolsAgent/ToolsFuns/source_contracts.py",
    "legacy/ToolsAgent/ToolsFuns/GeoEval/scientific_tools.py",
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


def configure_cpu():
    os.environ.update({"CUDA_VISIBLE_DEVICES": "", "NVIDIA_VISIBLE_DEVICES": "none",
                       "HIP_VISIBLE_DEVICES": "", "ROCR_VISIBLE_DEVICES": "",
                       "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false",
                       "PYTHONDONTWRITEBYTECODE": "1"})
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS"):
        os.environ[name] = "2"
    for name in ("HOME", "USERPROFILE", "TMP", "TEMP", "TMPDIR", "XDG_CACHE_HOME",
                 "XDG_CONFIG_HOME", "MPLCONFIGDIR", "NUMBA_CACHE_DIR"):
        directory = AREA / "environment" / name.lower()
        directory.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(directory)


def prepare():
    if Path(sys.executable).resolve() != PYTHON.resolve() or sha(PYTHON) != PYTHON_SHA:
        raise RuntimeError("Wrong existing private interpreter; no install is authorized")
    if (AREA / "report.json").exists():
        raise RuntimeError("Preserve prior receipts; use a new revision")
    private = AREA / "private-source"
    private.mkdir(exist_ok=False)
    bindings = {}
    for relative in COPY_FILES:
        original = ROOT / relative
        if original.is_symlink() or not original.is_file():
            raise RuntimeError("Missing ordinary fixed source: " + relative)
        target = private / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        bindings[relative] = sha(target)
    catalog = read_json(GROUP / "catalog-additions.json")
    target = private / "catalog/registry.json"
    target.parent.mkdir(parents=True)
    shutil.copyfile(GROUP / "catalog-additions.json", target)
    for skill in catalog["skills"]:
        target = private / skill["skill_file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / skill["skill_file"], target)
    save(AREA / "private-source-manifest.json", {"files_sha256": bindings,
         "catalog_sha256": sha(private / "catalog/registry.json"),
         "registry_source_modified": False, "module_allowlist_modified": False})
    return {"ready": True, "private": str(private), "source_hashes": bindings}


def contract_checks(preparation):
    sys.path.insert(0, preparation["private"])
    import yaml
    from jsonschema import Draft202012Validator
    from geological_agent.geology import source_registry
    from geological_agent.skills import Skill, SkillSummary, SkillRegistry, SkillLoader
    catalog = read_json(GROUP / "catalog-additions.json")
    original = read_json(AREA / "before-catalog.json")
    documents = read_json(AREA / "before-skills.json")
    hashes = read_json(AREA / "before-hashes.json")
    examples = read_json(GROUP / "examples-additions.json")
    old_tools = {tool["id"]: tool for tool in original["tools"]}
    old_skills = {skill["id"]: skill for skill in original["skills"]}
    source_tree = ast.parse((ROOT / "geological_agent/geology/expansion501_spatial.py").read_text(encoding="utf-8"))
    definitions = {node.name: node for node in source_tree.body if isinstance(node, ast.FunctionDef)}

    class Fidelity(unittest.TestCase):
        pass

    def tool_check(tool):
        def check(self):
            old = old_tools[tool["id"]]
            restored = deepcopy(tool)
            restored.pop("example_arguments")
            restored.pop("function_definition")
            self.assertEqual(restored, old)
            self.assertEqual(tool["example_arguments"], examples[tool["id"]]["input"])
            expected = {"type": "function", "function": {"name": tool["id"],
                        "description": old["description"], "parameters": old["input_schema"]}}
            self.assertEqual(tool["function_definition"], expected)
            self.assertEqual(source_registry.native_name(tool), tool["id"])
            Draft202012Validator.check_schema(tool["input_schema"])
            Draft202012Validator.check_schema(tool["output_schema"])
            Draft202012Validator(tool["input_schema"]).validate(tool["example_arguments"])
            entry = tool["source_interface"]["entrypoint"]
            self.assertEqual(entry["callable"], entry["module"] + ":" + entry["function"])
            function = definitions[entry["function"]]
            declared = [deco.args[0].value for deco in function.decorator_list
                        if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Name)
                        and deco.func.id == "operation" and deco.args and isinstance(deco.args[0], ast.Constant)]
            self.assertEqual(declared, [tool["id"]])
        return check

    def skill_check(skill):
        def check(self):
            normalized = skill["id"].replace("-", "_")
            old = old_skills[skill["id"]]
            restored = deepcopy(skill)
            restored["skill_file"] = old["skill_file"]
            self.assertEqual(restored, old)
            self.assertEqual(skill["skill_file"], "catalog/skills/" + skill["id"] + "/SKILL.md")
            raw = (ROOT / skill["skill_file"]).read_bytes().decode("utf-8")
            self.assertEqual(raw, documents[skill["skill_file"]].replace("id: " + skill["id"] + "\n", "id: " + normalized + "\n", 1))
            front, body = raw.split("---", 2)[1:]
            data = yaml.safe_load(front)
            self.assertEqual(data["id"], normalized)
            self.assertEqual(data["tools"], skill["tool_references"])
            registry = SkillRegistry()
            summary = SkillSummary(*(data[key] for key in ("id", "name", "description", "when_to_use")))
            registry.register(Skill(summary, tuple(data["required_inputs"]), body.strip(),
                tuple(data["constraints"]), tuple(data["tools"]), tuple(data["expected_outputs"])))
            loaded = SkillLoader(registry).load(normalized)
            self.assertEqual(loaded.tool_names, tuple(skill["tool_references"]))
        return check

    for tool in catalog["tools"]:
        setattr(Fidelity, "test_tool_" + tool["id"], tool_check(tool))
    for skill in catalog["skills"]:
        setattr(Fidelity, "test_skill_" + skill["id"].replace("-", "_"), skill_check(skill))

    def protected(self):
        for relative, expected in hashes["protected_sha256"].items():
            self.assertEqual(sha(ROOT / relative), expected, relative)
    Fidelity.test_protected_source_and_main_catalog_unchanged = protected

    def reproducible(self):
        path = GROUP / "build_registry_metadata_r9.py"
        spec = importlib.util.spec_from_file_location("spatial_metadata_generator", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        generated, revised = module.normalize(original, examples, documents)
        self.assertEqual(generated, catalog)
        again, same = module.normalize(generated, examples, revised)
        self.assertEqual(again, generated)
        self.assertEqual(same, revised)
        for relative, text in revised.items():
            self.assertEqual((ROOT / relative).read_bytes().decode("utf-8"), text)
    Fidelity.test_generator_reproduction_and_idempotence = reproducible
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Fidelity)
    if suite.countTestCases() != 34:
        raise RuntimeError("Unexpected bounded test count")
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    (AREA / "tests.log").write_text(stream.getvalue(), encoding="utf-8")
    report = {"tests_run": result.testsRun,
              "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
              "failures": [{"test": str(test), "traceback": trace} for test, trace in result.failures],
              "errors": [{"test": str(test), "traceback": trace} for test, trace in result.errors],
              "skips": [{"test": str(test), "reason": reason} for test, reason in result.skipped],
              "passed_all": result.wasSuccessful(), "scientific_calls": 0}
    save(AREA / "report.json", report)
    return report


def registry_attempt():
    from geological_agent.geology import source_registry
    from geological_agent.tools import ToolRegistry
    from geological_agent.skills import SkillLoader, SkillRegistry
    registry = ToolRegistry()
    try:
        registered = source_registry.register(registry)
        skills = source_registry.load_source_skills(SkillLoader(SkillRegistry()), registered, runtime_registry=registry)
        result = {"status": "registered_not_science_executed", "registered_tools": len(registered),
                  "loaded_skills": len(skills.registry.list())}
    except Exception as error:
        result = {"status": "blocked", "exception_type": type(error).__name__, "message": str(error),
                  "traceback": traceback.format_exc(), "registered_tools": len(registry.names())}
    result.update(source_registry_stubbed=False, allowlist_modified=False, scientific_calls=0,
                  main_catalog_modified=False, formal_eligible=False)
    save(AREA / "native-registry-report.json", result)
    return result


def main():
    configure_cpu()
    sys.path.insert(0, "C:/Users/jona/.codex/skills/flowing/scripts")
    from flowing import Flow, task

    @task
    def identity():
        return prepare()

    def validate_identity(identity):
        if not identity["ready"]:
            raise RuntimeError("Identity preparation failed")

    @task(depends_on=[identity], validate=validate_identity, when=lambda identity: identity["ready"])
    def fields(identity):
        return contract_checks(identity)

    @task(depends_on=[fields], when=lambda fields: fields["passed_all"])
    def native(fields):
        return registry_attempt()

    @task(depends_on=[fields, native])
    def receipt(fields, native):
        result = {"fields": fields, "native_registry": native, "science_acceptance": "not_run",
                  "deployed": False, "submitted": False, "formal_eligible": False}
        save(AREA / "receipt.json", result)
        print(json.dumps(result, indent=2))
        return result

    flow = Flow(receipt, max_workers=1)
    flow.run()
    result = flow.value(receipt)
    return 0 if result["fields"]["passed_all"] and result["native_registry"] and result["native_registry"]["status"] != "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())

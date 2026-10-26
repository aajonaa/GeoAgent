"""Local-only Flow regression. Uses existing private deps; no installs or SSH."""
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest

AREA = Path(__file__).resolve().parent
SHARED = AREA.parent
ROOT = AREA.parents[4]
PYTHON = ROOT / "catalog/source_delivery/expansion501-20261026/groups/geology/acceptance/local-r6-gpr-20261026/venv/Scripts/python.exe"
PYTHON_SHA = "8e11f5c0c4cdea438059feea1b750721929433374b389674c8368ae8bfcbf525"
BASELINE = "25f805cf5531ff8bf1f8894f006dca40c6035efd44967507583c820dcc323fa9"
HOOK = "53e762929334bb3f6c10a40b65dd098684845a38bf9801652f79f063745720a3"
TESTS = "2f629084d67e46c5bd457f4a0d53aec28d15243297fdf07fd1800df6953d3abb"
sys.path.insert(0, "C:/Users/jona/.codex/skills/flowing/scripts")
from flowing import Flow, task

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

@task
def identity():
    if (AREA / "test-report.json").exists():
        raise RuntimeError("Do not overwrite prior evidence.")
    if Path(sys.executable).resolve() != PYTHON.resolve() or sha(PYTHON) != PYTHON_SHA:
        raise RuntimeError("Wrong existing private interpreter.")
    if sys.version_info[:3] != (3, 12, 14) or importlib.metadata.version("jsonschema") != "4.25.1":
        raise RuntimeError("Wrong actual Python/jsonschema version.")
    if sha(ROOT / "geological_agent/geology/collection_contracts.py") != HOOK:
        raise RuntimeError("Common hook changed unexpectedly.")
    if sha(ROOT / "tests/test_isolated_cpu_bridge_v2.py") != TESTS:
        raise RuntimeError("Original 41 tests changed.")
    prior = (SHARED / "source-package-manifest.json").read_bytes()
    with (SHARED / "source-package-manifest-r3.json").open("xb") as out:
        out.write(prior)
    files = ["geological_agent/geology/collection_contracts.py",
             "geological_agent/geology/isolated_cpu_bridge_v2.py",
             "geological_agent/geology/isolated_cpu_worker_v2.py",
             "tests/test_isolated_cpu_bridge_v2.py"]
    return {"ready": True, "python": str(PYTHON), "python_sha256": sha(PYTHON),
            "python_version": sys.version, "jsonschema": "4.25.1",
            "files_sha256": {rel: sha(ROOT / rel) for rel in files}}

def require_identity(identity):
    if identity["ready"] is not True:
        raise RuntimeError("Identity gate failed.")

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

def summary(result):
    return {"run_including_skips": result.testsRun,
            "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
            "failures": [{"test": str(t), "traceback": text} for t, text in result.failures],
            "errors": [{"test": str(t), "traceback": text} for t, text in result.errors],
            "skipped": [{"test": str(t), "reason": reason} for t, reason in result.skipped]}

@task(depends_on=[identity], validate=require_identity, when=lambda identity: identity["ready"])
def execute(identity):
    original = load(ROOT / "tests/test_isolated_cpu_bridge_v2.py", "original_41_local_r5")
    original.AREA = AREA
    extra = load(AREA / "test_gpr_plumbing.py", "gpr_plumbing_local_r5")
    suites = [unittest.defaultTestLoader.loadTestsFromModule(m) for m in (original, extra)]
    if [suite.countTestCases() for suite in suites] != [41, 11]:
        raise RuntimeError("Unexpected test scope.")
    stream = io.StringIO()
    original_result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suites[0])
    extra_result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suites[1])
    with (AREA / "tests.log").open("x", encoding="utf-8") as out:
        out.write(stream.getvalue())
    report = {"scope": "local_Windows_shared_plumbing_not_GPR_science_or_Linux",
              "identity": identity, "original_41": summary(original_result),
              "new_gpr_plumbing_11": summary(extra_result),
              "scientific_tests_executed": 0, "GPR_calls_executed": 0,
              "Linux_tests_executed": 0, "remote_operations": 0,
              "dependency_installs": 0, "group_metadata_modified": False,
              "production_profiles_created": 0,
              "exit_code": 0 if original_result.wasSuccessful() and extra_result.wasSuccessful() else 1}
    with (AREA / "test-report.json").open("x", encoding="utf-8") as out:
        json.dump(report, out, indent=2)
    return report

@task(depends_on=[execute])
def receipt(execute):
    unchanged = all(sha(ROOT / rel) == digest for rel, digest in execute["identity"]["files_sha256"].items())
    binding = {"source_unchanged_after_tests": unchanged,
               "test_report_sha256": sha(AREA / "test-report.json"),
               "tests_log_sha256": sha(AREA / "tests.log"),
               "profile_id_proposed_not_registered": "expansion501-geology-gpr-cpu-v2",
               "formal_eligible": False, "deployed": False, "science_acceptance": "not_run"}
    with (AREA / "receipt.json").open("x", encoding="utf-8") as out:
        json.dump(binding, out, indent=2)
    if not unchanged:
        raise RuntimeError("Source changed during local tests.")
    delivery = json.loads((SHARED / "delivery-files.json").read_text(encoding="utf-8"))["files"]
    rows = []
    for relative in delivery:
        if relative == "catalog/source_delivery/expansion501-20261026/shared-isolation-v2/source-package-manifest.json":
            continue
        path = ROOT / relative
        if not path.is_file():
            raise RuntimeError("Missing explicit delivery file: " + relative)
        rows.append({"path": relative, "sha256": sha(path), "bytes": path.stat().st_size})
    manifest = {"status": "source_authored_local_contract_results_not_science_accepted",
                "baseline_precondition": {"path": "geological_agent/geology/collection_contracts.py",
                                         "sha256_before": BASELINE, "sha256_after": HOOK},
                "files": rows,
                "test_report": "catalog/source_delivery/expansion501-20261026/shared-isolation-v2/local-plumbing-r5/test-report.json",
                "test_exit_code": execute["exit_code"],
                "science_acceptance": "not_run", "real_gpr_cross_interpreter": "not_run",
                "deployed": False, "submitted": False, "manifest_self_hash_excluded": True}
    pending = SHARED / "source-package-manifest-r5.pending.json"
    with pending.open("x", encoding="utf-8") as out:
        json.dump(manifest, out, indent=2)
    os.replace(pending, SHARED / "source-package-manifest.json")
    return {"original_41": execute["original_41"], "new_gpr_plumbing_11": execute["new_gpr_plumbing_11"],
            "exit_code": execute["exit_code"], "files_sha256": execute["identity"]["files_sha256"],
            "manifest_sha256": sha(SHARED / "source-package-manifest.json"),
            "report": str(AREA / "test-report.json")}

if __name__ == "__main__":
    flow = Flow(receipt, max_workers=1)
    results = flow.run()
    value = flow.value(receipt)
    print(json.dumps(value, indent=2))
    raise SystemExit(value["exit_code"])

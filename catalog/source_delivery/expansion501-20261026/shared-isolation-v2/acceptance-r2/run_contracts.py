"""Fresh receipt for unchanged v2 tests in the reviewed private Python. No installs."""
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
ROOT = AREA.parents[4]
PYTHON = ROOT / "catalog/source_delivery/expansion501-20261026/groups/geology/acceptance/local-r6-gpr-20261026/venv/Scripts/python.exe"
PYTHON_SHA = "8e11f5c0c4cdea438059feea1b750721929433374b389674c8368ae8bfcbf525"
HOOK_SHA = "53e762929334bb3f6c10a40b65dd098684845a38bf9801652f79f063745720a3"
sys.path.insert(0, "C:/Users/jona/.codex/skills/flowing/scripts")
from flowing import Flow, task

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

@task
def identity():
    if (AREA / "test-report.json").exists():
        raise RuntimeError("Fresh receipt required; existing evidence will not be overwritten.")
    if Path(sys.executable).resolve() != PYTHON.resolve() or sha(PYTHON) != PYTHON_SHA:
        raise RuntimeError("Interpreter identity differs from Peirce's supplied receipt.")
    if sys.version_info[:3] != (3, 12, 14) or importlib.metadata.version("jsonschema") != "4.25.1":
        raise RuntimeError("Actual interpreter/dependency version mismatch.")
    if sha(ROOT / "geological_agent/geology/collection_contracts.py") != HOOK_SHA:
        raise RuntimeError("Frozen common hook changed; stop rather than test different source.")
    files = ["geological_agent/geology/collection_contracts.py",
             "geological_agent/geology/isolated_cpu_bridge_v2.py",
             "geological_agent/geology/isolated_cpu_worker_v2.py",
             "tests/test_isolated_cpu_bridge_v2.py"]
    return {"ready": True, "python": str(PYTHON), "python_sha256": sha(PYTHON),
            "python_version": sys.version, "jsonschema": importlib.metadata.version("jsonschema"),
            "files_sha256": {rel: sha(ROOT / rel) for rel in files}}

def require_identity(identity):
    if identity["ready"] is not True:
        raise RuntimeError("Reviewed private interpreter is unavailable.")

@task(depends_on=[identity], validate=require_identity, when=lambda identity: identity["ready"])
def execute(identity):
    path = ROOT / "tests/test_isolated_cpu_bridge_v2.py"
    spec = importlib.util.spec_from_file_location("unchanged_v2_contract_tests_r2", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    # Only the evidence/scratch location changes. Test bodies and source files stay unchanged.
    module.AREA = AREA
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    count = suite.countTestCases()
    if count != 41:
        raise RuntimeError("Expected unchanged 41 tests, found " + str(count))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    log = stream.getvalue()
    with (AREA / "tests.log").open("x", encoding="utf-8") as out:
        out.write(log)
    report = {"scope": "Windows_private_Python312_unchanged_v2_synthetic_contract_tests_not_GPR_science",
              "identity": identity, "discovered": count, "tests_run_including_skips": result.testsRun,
              "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
              "failures": [{"test": str(t), "traceback": text} for t, text in result.failures],
              "errors": [{"test": str(t), "traceback": text} for t, text in result.errors],
              "skipped": [{"test": str(t), "reason": reason} for t, reason in result.skipped],
              "scientific_tests_executed": 0, "GPR_scientific_tests_executed": 0,
              "remote_tests_executed": 0, "source_modified": False,
              "prior_reports_reused": False, "environment_modified": False,
              "exit_code": 0 if result.wasSuccessful() else 1}
    with (AREA / "test-report.json").open("x", encoding="utf-8") as out:
        json.dump(report, out, indent=2, ensure_ascii=True)
    return report

@task(depends_on=[execute])
def receipt(execute):
    unchanged = all(sha(ROOT / rel) == digest for rel, digest in execute["identity"]["files_sha256"].items())
    binding = {"source_unchanged_after_tests": unchanged,
               "test_report_sha256": sha(AREA / "test-report.json"),
               "test_log_sha256": sha(AREA / "tests.log"),
               "runner_sha256": sha(Path(__file__)),
               "source_status": "source_frozen_no_repairs_applied",
               "science_acceptance": "not_run", "deployed": False}
    with (AREA / "receipt.json").open("x", encoding="utf-8") as out:
        json.dump(binding, out, indent=2)
    return {**{k: execute[k] for k in ("passed", "failures", "errors", "skipped", "exit_code")},
            "source_unchanged_after_tests": unchanged, "report": str(AREA / "test-report.json")}

if __name__ == "__main__":
    flow = Flow(receipt, max_workers=1)
    results = flow.run()
    value = flow.value(receipt)
    print(json.dumps(value, indent=2))
    raise SystemExit(value["exit_code"] if value["source_unchanged_after_tests"] else 2)

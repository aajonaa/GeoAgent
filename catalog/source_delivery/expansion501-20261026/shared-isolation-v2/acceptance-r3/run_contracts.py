"""Fresh r3 receipt: original 41 tests, approved deadline-boundary repair only."""
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
HOOK_SHA = "53e762929334bb3f6c10a40b65dd098684845a38bf9801652f79f063745720a3"
BASELINE_SHA = "25f805cf5531ff8bf1f8894f006dca40c6035efd44967507583c820dcc323fa9"
sys.path.insert(0, "C:/Users/jona/.codex/skills/flowing/scripts")
from flowing import Flow, task

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

@task
def identity():
    if (AREA / "test-report.json").exists():
        raise RuntimeError("Fresh receipt required; existing r3 evidence will not be overwritten.")
    if Path(sys.executable).resolve() != PYTHON.resolve() or sha(PYTHON) != PYTHON_SHA:
        raise RuntimeError("Interpreter identity differs from Peirce's supplied receipt.")
    if sys.version_info[:3] != (3, 12, 14) or importlib.metadata.version("jsonschema") != "4.25.1":
        raise RuntimeError("Actual interpreter/dependency version mismatch.")
    if sha(ROOT / "geological_agent/geology/collection_contracts.py") != HOOK_SHA:
        raise RuntimeError("Frozen common hook changed.")
    prior = SHARED / "source-package-manifest.json"
    prior_bytes = prior.read_bytes()
    prior_manifest = json.loads(prior_bytes)
    prior_hashes = {row["path"]: row["sha256"] for row in prior_manifest["files"]}
    test_rel = "tests/test_isolated_cpu_bridge_v2.py"
    if sha(ROOT / test_rel) != prior_hashes[test_rel]:
        raise RuntimeError("Original 41 test source changed; stop.")
    with (SHARED / "source-package-manifest-r1.json").open("xb") as out:
        out.write(prior_bytes)
    files = ["geological_agent/geology/collection_contracts.py",
             "geological_agent/geology/isolated_cpu_bridge_v2.py",
             "geological_agent/geology/isolated_cpu_worker_v2.py", test_rel]
    return {"ready": True, "python": str(PYTHON), "python_sha256": sha(PYTHON),
            "python_version": sys.version, "jsonschema": importlib.metadata.version("jsonschema"),
            "original_tests_unchanged": True,
            "prior_manifest_sha256": hashlib.sha256(prior_bytes).hexdigest(),
            "files_sha256": {rel: sha(ROOT / rel) for rel in files}}

def require_identity(identity):
    if identity["ready"] is not True:
        raise RuntimeError("Reviewed private interpreter is unavailable.")

@task(depends_on=[identity], validate=require_identity, when=lambda identity: identity["ready"])
def execute(identity):
    path = ROOT / "tests/test_isolated_cpu_bridge_v2.py"
    spec = importlib.util.spec_from_file_location("unchanged_v2_contract_tests_r3", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.AREA = AREA
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    count = suite.countTestCases()
    if count != 41:
        raise RuntimeError("Expected unchanged 41 tests, found " + str(count))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    with (AREA / "tests.log").open("x", encoding="utf-8") as out:
        out.write(stream.getvalue())
    report = {"scope": "Windows_private_Python312_unchanged_v2_synthetic_contract_tests_not_GPR_science",
              "identity": identity, "discovered": count, "tests_run_including_skips": result.testsRun,
              "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
              "failures": [{"test": str(t), "traceback": text} for t, text in result.failures],
              "errors": [{"test": str(t), "traceback": text} for t, text in result.errors],
              "skipped": [{"test": str(t), "reason": reason} for t, reason in result.skipped],
              "scientific_tests_executed": 0, "GPR_scientific_tests_executed": 0,
              "remote_tests_executed": 0, "source_modified_during_tests": False,
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
               "source_status": "approved_deadline_boundary_repair_no_other_algorithm_changes",
               "science_acceptance": "not_run", "deployed": False}
    with (AREA / "receipt.json").open("x", encoding="utf-8") as out:
        json.dump(binding, out, indent=2)
    if not unchanged:
        raise RuntimeError("Source changed during acceptance; do not publish a composite manifest.")
    delivery = json.loads((SHARED / "delivery-files.json").read_text(encoding="utf-8"))["files"]
    rows = []
    for relative in delivery:
        if relative == "catalog/source_delivery/expansion501-20261026/shared-isolation-v2/source-package-manifest.json":
            continue
        path = ROOT / relative
        if not path.is_file():
            raise RuntimeError("Explicit delivery file missing: " + relative)
        rows.append({"path": relative, "sha256": sha(path), "bytes": path.stat().st_size})
    manifest = {
        "status": "source_authored_local_contract_results_not_science_accepted",
        "baseline_precondition": {"path": "geological_agent/geology/collection_contracts.py",
                                 "sha256_before": BASELINE_SHA, "sha256_after": HOOK_SHA},
        "files": rows,
        "test_report": "catalog/source_delivery/expansion501-20261026/shared-isolation-v2/acceptance-r3/test-report.json",
        "test_exit_code": execute["exit_code"], "science_acceptance": "not_run",
        "real_gpr_cross_interpreter": "not_run", "deployed": False, "submitted": False,
        "manifest_self_hash_excluded": True}
    pending = SHARED / "source-package-manifest-r3.pending.json"
    with pending.open("x", encoding="utf-8") as out:
        json.dump(manifest, out, indent=2)
    os.replace(pending, SHARED / "source-package-manifest.json")
    return {**{k: execute[k] for k in ("passed", "failures", "errors", "skipped", "exit_code")},
            "source_unchanged_after_tests": unchanged,
            "files_sha256": execute["identity"]["files_sha256"],
            "report": str(AREA / "test-report.json"),
            "manifest": str(SHARED / "source-package-manifest.json"),
            "manifest_sha256": sha(SHARED / "source-package-manifest.json")}

if __name__ == "__main__":
    flow = Flow(receipt, max_workers=1)
    results = flow.run()
    value = flow.value(receipt)
    print(json.dumps(value, indent=2))
    raise SystemExit(value["exit_code"])

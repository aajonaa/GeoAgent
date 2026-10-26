"""One-shot local Flow gates. No installation, remote execution or science claims."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

AREA = Path(__file__).resolve().parent
ROOT = AREA.parents[3]
sys.path.insert(0, "C:/Users/jona/.codex/skills/flowing/scripts")
from flowing import Flow, task

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

@task
def prepare():
    report = AREA / "local-test-report-r1.json"
    if report.exists() or (AREA / "source-package-manifest.json").exists():
        raise RuntimeError("Existing evidence must be preserved; this r1 runner is one-shot.")
    spec = importlib.util.spec_from_file_location("isolated_v2_local_runner", ROOT / "geological_agent/geology/isolated_cpu_bridge_v2.py")
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    job = AREA / "runner-private-r1"
    job.mkdir(exist_ok=False)
    env = bridge.private_environment(job)
    return {"ready": True, "environment": env}

def require_ready(prepare):
    if prepare["ready"] is not True:
        raise RuntimeError("CPU local test preparation not ready.")

@task(depends_on=[prepare], validate=require_ready, when=lambda prepare: prepare["ready"])
def execute(prepare):
    with (AREA / "local-tests-r1.stdout.log").open("xb") as stdout, (AREA / "local-tests-r1.stderr.log").open("xb") as stderr:
        result = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "tests/test_isolated_cpu_bridge_v2.py")],
                                cwd=ROOT, env=prepare["environment"], stdout=stdout, stderr=stderr,
                                timeout=120, check=False)
    return {"exit_code": result.returncode}

@task(depends_on=[execute])
def finalize(execute):
    delivery = json.loads((AREA / "delivery-files.json").read_text(encoding="utf-8"))["files"]
    rows = []
    for relative in delivery:
        if relative.endswith("/source-package-manifest.json"):
            continue
        path = ROOT / relative
        if not path.is_file():
            raise RuntimeError("Expected explicit delivery file is missing: " + relative)
        rows.append({"path": relative, "sha256": digest(path), "bytes": path.stat().st_size})
    pre = json.loads((AREA / "baseline-precondition.json").read_text(encoding="utf-8"))
    report = {
        "status": "source_authored_local_contract_results_not_science_accepted",
        "baseline_precondition": {"path": pre["path"], "sha256_before": pre["sha256_before"],
                                 "sha256_after": digest(ROOT / pre["path"])},
        "files": rows,
        "test_report": "catalog/source_delivery/expansion501-20261026/shared-isolation-v2/local-test-report-r1.json",
        "test_exit_code": execute["exit_code"],
        "science_acceptance": "not_run", "real_gpr_cross_interpreter": "not_run",
        "deployed": False, "submitted": False, "manifest_self_hash_excluded": True,
    }
    with (AREA / "source-package-manifest.json").open("x", encoding="utf-8") as out:
        json.dump(report, out, indent=2)
    tests = json.loads((AREA / "local-test-report-r1.json").read_text(encoding="utf-8"))
    return {"exit_code": execute["exit_code"], "baseline_precondition": report["baseline_precondition"],
            "passed": tests["passed"], "failures": tests["failures"], "errors": tests["errors"],
            "skipped": tests["skipped"], "manifest": str(AREA / "source-package-manifest.json")}

if __name__ == "__main__":
    flow = Flow(finalize, max_workers=1)
    results = flow.run()
    value = flow.value(finalize)
    print(json.dumps(value, indent=2))
    raise SystemExit(value["exit_code"])

"""Fresh freeze DAG; failed r2 worker and all native artifacts stay untouched."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/"orchestration"))
from flowing import Flow, task


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2)+chr(10), encoding="utf-8")


@task
def originals():
    lock = json.loads((ROOT/"source-lock.json").read_text(encoding="utf-8"))
    protected = list(lock["files"])+["runner.py", "adapters.py", "specs.py", "test_native.py", "build/build-receipt.json", "build/libvic_phase.so", "build/libmadagascar_fft.so", "build/libhpgl_variogram.so"]
    before = {name: sha(ROOT/name) for name in protected}
    assert before["build/build-receipt.json"] == "6e22c8ceb6efadc9729b7883ceab4822db838ea8b8bca0cd832718acd94b5da5"
    for name, record in lock["files"].items():
        assert before[name] == record["sha256"]
    return before


@task(depends_on=[originals])
def retest(originals):
    assert not (ROOT/"private-pytest-r5").exists(), "Fresh test scope required"
    command = [sys.executable, "-m", "pytest", "test_native.py", "test_failure_exit.py", "-q", "--junitxml=acceptance-r5.xml", "--basetemp=private-pytest-r5"]
    result = subprocess.run(command, cwd=ROOT, env=dict(os.environ), text=True, capture_output=True)
    (ROOT/"acceptance-r5.log").write_text(result.stdout+result.stderr, encoding="utf-8")
    dump(ROOT/"child-result-r5.json", {"command": command, "returncode": result.returncode})
    if result.returncode:
        raise ChildProcessError("Freeze acceptance child failed: "+str(result.returncode))
    tests = list(ET.parse(ROOT/"acceptance-r5.xml").iter("testcase"))
    counts = {"total": len(tests), "failed": sum(t.find("failure") is not None for t in tests), "errors": sum(t.find("error") is not None for t in tests), "skipped": sum(t.find("skipped") is not None for t in tests), "original_scientific": sum(t.get("classname") == "test_native" for t in tests), "failure_specialists": sum(t.get("classname") == "test_failure_exit" for t in tests)}
    assert counts == {"total": 87, "failed": 0, "errors": 0, "skipped": 0, "original_scientific": 80, "failure_specialists": 7}
    return counts


@task(depends_on=[originals, retest])
def freeze(originals, retest):
    after = {name: sha(ROOT/name) for name in originals}
    assert originals == after, "Protected original scientific files changed"
    result = {"complete": True, "exit_code": 0, "tests": retest, "protected_before_sha256": originals, "protected_after_sha256": after, "protected_files_unchanged": True, "build_receipt_sha256": originals["build/build-receipt.json"], "builder_sha256": sha(ROOT/"build_accept.py"), "frozen_worker_sha256": sha(Path(__file__)), "runner_sha256": originals["runner.py"], "compiler_original_exit_propagation_fixed": True, "failed_r2_worker_preserved": True, "gpu_used": False, "production_modified": False, "models_called": False, "deployed": False, "pushed": False, "formal_packaging": "not_performed", "HPGL_distribution_license_review": "pending"}
    dump(ROOT/"freeze-r5.json", result)
    handoff = json.loads((ROOT/"HANDOFF.json").read_text(encoding="utf-8"))
    handoff.update(status="independent_cpu_accepted_frozen_r5", tests=retest, compiler_original_exit_propagation_fixed=True, build_receipt_unchanged=True, build_receipt_sha256=result["build_receipt_sha256"], builder_sha256=result["builder_sha256"], frozen_worker_sha256=result["frozen_worker_sha256"], runner_sha256=result["runner_sha256"], freeze_receipt="freeze-r5.json", formal_packaging="not_performed")
    dump(ROOT/"HANDOFF-r5.json", handoff)
    return result


def main():
    flow = Flow(freeze, max_workers=1, journal_path=str(ROOT/"freeze-r5-flow.jsonl"))
    try:
        flow.run()
        result = flow.value(freeze)
        if not result or not result["complete"]:
            raise RuntimeError("Freeze gate not reached")
        print(json.dumps(result))
        return 0
    except Exception:
        child_path = ROOT/"child-result-r5.json"
        child = json.loads(child_path.read_text(encoding="utf-8")) if child_path.exists() else {}
        code = child.get("returncode") or 1
        result = {"complete": False, "exit_code": code, "child_returncode": child.get("returncode"), "error": traceback.format_exc(), "gpu_used": False, "production_modified": False}
        dump(ROOT/"freeze-r5.json", result)
        print(json.dumps(result))
        return code


if __name__ == "__main__":
    raise SystemExit(main())


"""CPU-only preparation DAG. Not imported or called by scientific tools."""
import os
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import traceback
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/"orchestration"))
from flowing import Flow, task


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=True, indent=2)+"\n", encoding="utf-8")


def run_recorded_child(command, log_path, stage):
    private_root = ROOT.resolve()
    log_path = Path(log_path)
    if not log_path.is_absolute():
        log_path = private_root/log_path
    log_path = log_path.resolve()
    log_path.relative_to(private_root)
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, env=dict(os.environ))
    log_path.write_text(result.stdout+result.stderr, encoding="utf-8")
    record = {"stage": stage, "command": command, "returncode": result.returncode,
              "log": str(log_path.relative_to(private_root))}
    with (ROOT/"process-results-r2.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record)+"\n")
    if stage == "scientific_acceptance":
        dump(ROOT/"child-result.json", {"command": command, "returncode": result.returncode})
    if result.returncode:
        dump(ROOT/"last-child-failure-r2.json", record)
        raise ChildProcessError(stage+" child exited "+str(result.returncode)+"; see "+str(log_path.name))
    return result


@task
def check_sources():
    from adapters import environment
    environment()
    lock = json.loads((ROOT/"source-lock.json").read_text(encoding="utf-8"))
    for path, item in lock["files"].items():
        if sha(ROOT/path) != item["sha256"]:
            raise ValueError("Source hash mismatch: "+path)
    return {"source_lock_sha256": sha(ROOT/"source-lock.json"), "input_sha256": {p: x["sha256"] for p,x in lock["files"].items()}}


@task(depends_on=[check_sources])
def compile_originals(check_sources):
    build = ROOT/"build"
    build.mkdir(exist_ok=False)
    inputs = dict(check_sources["input_sha256"])
    for file in (ROOT/"native").iterdir():
        if file.is_file():
            inputs[file.relative_to(ROOT).as_posix()] = sha(file)
    common = ["-O2", "-fPIC", "-shared", "-fvisibility=hidden", "-Wl,-z,relro,-z,now"]
    commands = [
        ["gcc", "-std=c11", *common, "-Inative", "vendor/vic/calc_rainonly.c", "native/vic_bridge.c", "-lm", "-o", "build/libvic_phase.so"],
        ["gcc", "-std=c11", *common, "-Ivendor/madagascar", "vendor/madagascar/kiss_fft.c", "native/madagascar_bridge.c", "-lm", "-o", "build/libmadagascar_fft.so"],
        ["g++", "-std=c++11", *common, "-Ivendor/hpgl", "vendor/hpgl/variograms.cpp", "native/hpgl_bridge.cpp", "-lm", "-o", "build/libhpgl_variogram.so"],
    ]
    compiler_versions = {}
    for compiler in ("gcc", "g++"):
        p = run_recorded_child([compiler, "--version"], build/(compiler+"-version.log"), "compiler_version:"+compiler)
        compiler_versions[compiler] = p.stdout.splitlines()[0]
    for index, command in enumerate(commands):
        run_recorded_child(command, build/f"compile-{index+1}.log", "compile:"+str(index+1))
    receipt = {**check_sources, "input_sha256": inputs, "commands": commands, "compiler_versions": compiler_versions, "output_sha256": {p.name: sha(p) for p in build.glob("*.so")}, "cpu_only": True, "runtime_compile": False}
    dump(build/"build-receipt.json", receipt)
    return receipt


@task(depends_on=[compile_originals])
def scientific_acceptance(compile_originals):
    command = [sys.executable, "-m", "pytest", "test_native.py", "-q", "--junitxml=acceptance.xml", "--basetemp=private-pytest"]
    run_recorded_child(command, ROOT/"acceptance.log", "scientific_acceptance")
    tests = list(ET.parse(ROOT/"acceptance.xml").iter("testcase"))
    summary = {"total": len(tests), "failed": sum(t.find("failure") is not None for t in tests), "errors": sum(t.find("error") is not None for t in tests), "skipped": sum(t.find("skipped") is not None for t in tests)}
    if not tests or any(summary[k] for k in ("failed", "errors", "skipped")):
        raise AssertionError("Acceptance gate did not pass completely: "+str(summary))
    return summary


@task(depends_on=[scientific_acceptance])
def handoff(scientific_acceptance):
    from specs import SPECS
    payload = {"complete": True, "status": "independent_cpu_accepted", "projects": [39, 131, 86], "accepted_operations": list(SPECS), "tests": scientific_acceptance, "build_receipt_sha256": sha(ROOT/"build/build-receipt.json"), "parent_catalog_modified": False, "production_modified": False, "gpu_used": False, "models_called": False, "deployed": False, "pushed": False, "receiving_lab_approval": "pending", "distribution_license_review": {"HPGL": "README and license.txt wording differ; both preserved for review before distribution.", "Madagascar": "Selected original Kiss FFT BSD notices and project COPYING retained."}, "runtime": {"python": sys.executable, "entrypoint": str(ROOT/"runner.py"), "input": "One fixed tool-name argv plus bounded UTF-8 JSON on stdin", "private_cache_environment_required": True}, "remaining_prerequisites": ["Parent registry integration and whole-project regression are not performed in this disjoint sidecar.", "Existing immutable R4 Python supplies ScientificToolError; gcc/g++ only needed for preparation, never at tool time.", "Final AI Lab receipt/packaging approval and HPGL distribution-license review remain pending."]}
    dump(ROOT/"HANDOFF.json", payload)
    dump(ROOT/"STATUS.json", payload)
    return payload


def main():
    flow = Flow(handoff, max_workers=1, journal_path=str(ROOT/"native-r2-flow.jsonl"))
    try:
        flow.run()
        status = flow.value(handoff)
        if not status or not status.get("complete"):
            raise RuntimeError("Flow did not reach the acceptance handoff gate")
        print(json.dumps(status))
        return 0
    except Exception:
        failure_path = ROOT/"last-child-failure-r2.json"
        child_path = ROOT/"child-result.json"
        child = json.loads(failure_path.read_text(encoding="utf-8")) if failure_path.exists() else (json.loads(child_path.read_text(encoding="utf-8")) if child_path.exists() else {})
        error = {"complete": False, "status": "failed_preserved", "error": traceback.format_exc(), "failure_stage": child.get("stage"), "child_returncode": child.get("returncode"), "gpu_used": False, "production_modified": False}
        dump(ROOT/"STATUS.json", error)
        print(json.dumps(error))
        return child.get("returncode") or 1


if __name__ == "__main__":
    raise SystemExit(main())


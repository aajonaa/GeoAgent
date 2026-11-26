"""Run only local stdlib protocol/reference tests through Flow; never science/SSH."""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPORT = HERE / "local-cpu-r6"
sys.path.insert(0, "C:/Users/jona/.codex/skills/flowing/scripts")
from flowing import task, Flow


@task
def protocol_reference_tests():
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", CUDA_VISIBLE_DEVICES="",
                       NVIDIA_VISIBLE_DEVICES="none", HIP_VISIBLE_DEVICES="",
                       ROCR_VISIBLE_DEVICES="", OMP_NUM_THREADS="2",
                       OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2",
                       LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false")
    environment.pop("EXPANSION501_R6_RUN_SCIENCE", None)
    completed = subprocess.run([sys.executable, str(HERE / "test_pending_two_r6.py")],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=60, env=environment, check=False)
    log = (completed.stdout + completed.stderr).decode("utf-8", errors="replace")
    total = re.search(r"Ran (\d+) tests?", log)
    counts = {}
    for field in ("failures", "errors", "skipped"):
        match = re.search(field + r"=(\d+)", log)
        counts[field] = int(match.group(1)) if match else 0
    counts["total"] = int(total.group(1)) if total else None
    counts["executed"] = counts["total"] - counts["skipped"] if total else None
    counts["passed"] = counts["executed"] - counts["failures"] - counts["errors"] if total else None
    return {"returncode": completed.returncode, "counts": counts, "log": log}


@task(depends_on=[protocol_reference_tests])
def preserve_failure_evidence(protocol_reference_tests):
    record = dict(protocol_reference_tests)
    (REPORT / "tests.log").write_text(record.pop("log"), encoding="utf-8")
    record.update(scope="local stdlib protocol/reference tests only",
                  scientific_tests_executed=0, accepted_operations=0,
                  remote_setup_or_upload=False, installed_packages=False,
                  production_mutation=False, gpu_used=False,
                  known_failure="Superseded v1 diagnostic worker classifies invalid JSON as upstream_failure; not repaired.",
                  source_status="source_revised_unverified",
                  integrated=False, certified=False)
    (REPORT / "result.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


@task(depends_on=[preserve_failure_evidence],
      when=lambda preserve_failure_evidence: preserve_failure_evidence["returncode"] == 0)
def local_gate_passed(preserve_failure_evidence):
    return {"local_gate_passed": True, "scientific_acceptance": "not_run"}


def main():
    REPORT.mkdir(exist_ok=False)
    output = io.StringIO()
    flow = Flow(local_gate_passed, max_workers=1, fail_fast=True)
    with contextlib.redirect_stdout(output):
        flow.run()
        flow.summary()
    (REPORT / "flow.log").write_text(output.getvalue(), encoding="utf-8")
    record = flow.value(preserve_failure_evidence)
    print(output.getvalue())
    print(json.dumps(record, indent=2))
    return record["returncode"]


if __name__ == "__main__":
    raise SystemExit(main())


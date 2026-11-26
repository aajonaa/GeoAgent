"""Local-only Flow gates for the approved unit fix. No remote/install branch."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import time

GROUP = Path(__file__).resolve().parents[1]
ROOT = GROUP.parents[4]
sys.path.insert(0, str(Path.home() / ".codex/skills/flowing/scripts"))
from flowing import Flow, task

RUN = GROUP / "acceptance" / ("local-units-r2-" + str(time.time_ns()))


@task
def local_only_gate():
    RUN.mkdir(parents=True, exist_ok=False)
    return {"local_only":True, "remote":False, "install":False, "native_science":False}


@task(depends_on=[local_only_gate], when=lambda local_only_gate:local_only_gate["local_only"])
def generate_unit_metadata(local_only_gate):
    before = json.loads((GROUP / "pending-contracts.json").read_text(encoding="utf-8"))
    snapshot = {}
    for tool, spec in before.items():
        output = deepcopy(spec["output_schema"])
        output["properties"].pop("units")
        output["required"] = [key for key in output["required"] if key != "units"]
        snapshot[tool] = {"input_schema":spec["input_schema"], "output_without_units":output,
                          "requirements":spec["requirements"], "numeric_oracle":spec["numeric_oracle"]}
    (RUN / "pre-generation-contracts.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    process = subprocess.run([sys.executable, "-B", str(GROUP / "build_resolution.py")], cwd=ROOT,
                             capture_output=True, timeout=30, check=False)
    (RUN / "generator.stdout.log").write_bytes(process.stdout)
    (RUN / "generator.stderr.log").write_bytes(process.stderr)
    if process.returncode:
        raise RuntimeError("Generator failed; evidence retained; no retry")
    return {"exit_code":process.returncode}


@task(depends_on=[generate_unit_metadata], when=lambda generate_unit_metadata:generate_unit_metadata["exit_code"] == 0)
def targeted_unit_regression(generate_unit_metadata):
    env = dict(os.environ)
    for key in ("HOME", "XDG_CACHE_HOME", "MPLCONFIGDIR", "NUMBA_CACHE_DIR", "TMP", "TEMP", "TMPDIR"):
        directory = RUN / key.lower()
        directory.mkdir(exist_ok=False)
        env[key] = str(directory)
    env.update(CUDA_VISIBLE_DEVICES="", NVIDIA_VISIBLE_DEVICES="none", ROCR_VISIBLE_DEVICES="",
               HIP_VISIBLE_DEVICES="", ONEAPI_DEVICE_SELECTOR="*:cpu", OMP_NUM_THREADS="1",
               OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1",
               LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false", PYTHONDONTWRITEBYTECODE="1",
               SPATIAL_UNITFIX_BASELINE=str(RUN / "pre-generation-contracts.json"),
               SPATIAL_UNITFIX_REPORT=str(RUN / "tests.json"))
    process = subprocess.run([sys.executable, "-B", str(GROUP / "acceptance/test_units_r2.py")],
                             cwd=ROOT, env=env, capture_output=True, timeout=30, check=False)
    (RUN / "tests.stdout.log").write_bytes(process.stdout)
    (RUN / "tests.stderr.log").write_bytes(process.stderr)
    print(process.stdout.decode("utf-8", "replace"))
    print(process.stderr.decode("utf-8", "replace"))
    if process.returncode:
        raise RuntimeError("Targeted regression failed; evidence retained; no automatic repair/retry")
    return {"exit_code":process.returncode, "scope":"unit_metadata_regression_only"}


@task(depends_on=[targeted_unit_regression], when=lambda targeted_unit_regression:targeted_unit_regression["exit_code"] == 0)
def freeze_handoff(targeted_unit_regression):
    report = json.loads((RUN / "tests.json").read_text(encoding="utf-8"))
    if report["skipped"] or report["failures"] or report["errors"]:
        raise RuntimeError("A skip/failure cannot be counted as a pass")
    delivery_path = GROUP / "delivery-files.json"
    delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
    evidence = [RUN / name for name in ("pre-generation-contracts.json", "generator.stdout.log",
                "generator.stderr.log", "tests.stdout.log", "tests.stderr.log", "tests.json", "flow-result.json")]
    delivery["files"] = sorted(set(delivery["files"] + [path.relative_to(ROOT).as_posix() for path in evidence]))
    delivery_path.write_text(json.dumps(delivery, indent=2) + "\n", encoding="utf-8")
    return {"source_stable":True, "pending_kernels":11, "incomplete":8, "new_from_remaining_eight":0,
            "new_registered":0, "new_accepted":0, "new_deployed":0, "tests":report}


if __name__ == "__main__":
    results = Flow(freeze_handoff, max_workers=1).run()
    report = {"evidence_path":str(RUN), "steps":{
        name:{"state":result.state.value, "value":result.value, "error":str(result.error) if result.error else None}
        for name,result in results.items()}}
    (RUN / "flow-result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    ok = "freeze_handoff" in results and results["freeze_handoff"].state.value == "succeeded"
    raise SystemExit(0 if ok else 1)

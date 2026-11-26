"""Fixed private CPU acceptance launcher. SOURCE ONLY until parent authorizes transport.

No SSH, installation, venv construction, scientific kernel, GPU probe or service
access. Parent supplies a fresh private revision, private venv and explicit-file
source transport. This launcher only executes its one fixed test file.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import sys
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision-root", required=True)
    parser.add_argument("--source-root", required=True)
    args = parser.parse_args()
    root = Path(args.revision_root).resolve()
    source = Path(args.source_root).resolve()
    if sys.platform != "linux" or not re.fullmatch(
            r"/data/wangjian/expansion501-20261026/geophysics-r[1-9][0-9]*", str(root)):
        raise SystemExit("Private Linux geophysics-rN revision required")
    if not Path(sys.prefix).resolve().is_relative_to(root):
        raise SystemExit("Launch with the revision's private venv, never an accepted base venv")
    if not source.is_relative_to(root):
        raise SystemExit("Source must be transported into this private revision")
    test_file = source / "tests/test_expansion501_geophysics.py"
    adapter_file = source / "geological_agent/geology/expansion501_geophysics.py"
    for path in (test_file, adapter_file):
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
            raise SystemExit("Missing/unsafe explicit source file: " + str(path))
    # Exclusive directory creation is the never-overwrite receipt boundary.
    evidence = root / "geophysics-acceptance-r2"
    evidence.mkdir(exist_ok=False)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.update({
        "E501_CPU_ACCEPTANCE": "1", "E501_GEO_ACCEPTANCE_ROOT": str(root),
        "E501_GEO_RESULTS_JSON": str(evidence / "test-results.json"),
        "CUDA_VISIBLE_DEVICES": "-1", "NVIDIA_VISIBLE_DEVICES": "void",
        "HIP_VISIBLE_DEVICES": "-1", "ROCR_VISIBLE_DEVICES": "-1",
        "JAX_PLATFORMS": "cpu", "JAX_PLATFORM_NAME": "cpu", "NUMBA_DISABLE_CUDA": "1",
        "SYCL_DEVICE_FILTER": "cpu", "ZE_AFFINITY_MASK": "", "MPLBACKEND": "Agg",
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(source),
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PIP_NO_INDEX": "1",
    })
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS", "NUMBA_NUM_THREADS"):
        env[key] = "2"
    for key, relative in {"HOME": "home", "XDG_CACHE_HOME": "cache", "TMPDIR": "tmp",
                          "TEMP": "tmp", "TMP": "tmp", "MPLCONFIGDIR": "cache/matplotlib",
                          "NUMBA_CACHE_DIR": "cache/numba", "JOBLIB_TEMP_FOLDER": "tmp/joblib"}.items():
        directory = evidence / relative
        directory.mkdir(parents=True, exist_ok=True)
        env[key] = str(directory)
    command = [sys.executable, "-B", str(test_file), "-v"]
    started = time.time()
    log_limit = 16 * 1024 * 1024
    wall_limit = 3600
    total = 0
    stop_reason = None
    # Environment selection is not an OS network sandbox. Offline behavior is
    # additionally required of the fixed adapters; no network-disable claim.
    with (evidence / "combined.log").open("xb") as log:
        process = subprocess.Popen(command, cwd=source, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        while selector.get_map():
            if time.time() - started > wall_limit and process.poll() is None:
                stop_reason = "wall_limit_exceeded_3600s"
                process.kill()
            for key, _ in selector.select(timeout=0.25):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                remaining = max(0, log_limit-total)
                log.write(chunk[:remaining])
                total += len(chunk)
                if total > log_limit and process.poll() is None:
                    stop_reason = "combined_output_limit_exceeded_16MiB"
                    process.kill()
        selector.close()
        code = process.wait()
    receipt = {
        "status": "execution_receipt_not_scientific_certification", "command": command,
        "catalog_scope": "versioned_private_geophysics_r2_not_consolidated_parent_r4",
        "formal_registration_acceptance": "pending_parent_r4",
        "actual_exit_status": code, "stop_reason": stop_reason,
        "elapsed_seconds": time.time()-started, "combined_bytes_observed": total,
        "combined_log_complete": total <= log_limit,
        "python_version": sys.version, "private_prefix": sys.prefix,
        "test_sha256": digest(test_file), "adapter_sha256": digest(adapter_file),
        "source_root": str(source), "environment_controls": {k: env[k] for k in (
            "CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES", "HIP_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES",
            "JAX_PLATFORMS", "NUMBA_DISABLE_CUDA", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS", "HOME", "XDG_CACHE_HOME", "TMPDIR")},
        "deployment": "not_run", "push": "not_run", "model": "not_run", "gpu": "not_used",
    }
    with (evidence / "execution-receipt.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(receipt, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"evidence": str(evidence), "actual_exit_status": code, "stop_reason": stop_reason}))
    return 0 if code == 0 and stop_reason is None else 1


if __name__ == "__main__":
    raise SystemExit(main())

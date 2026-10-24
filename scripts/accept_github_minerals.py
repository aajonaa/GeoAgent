"""Isolated CPU acceptance DAG; does not change a running service."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--flow-module", required=True, type=Path)
    parser.add_argument("--extra-deps", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    spec = importlib.util.spec_from_file_location("flowing", args.flow_module)
    flowmod = importlib.util.module_from_spec(spec)
    sys.modules["flowing"] = flowmod
    spec.loader.exec_module(flowmod)
    task, Flow = flowmod.task, flowmod.Flow
    app, deps = root / "app", root / "deps"
    env = dict(os.environ, CUDA_VISIBLE_DEVICES="", NVIDIA_VISIBLE_DEVICES="none", PYTHONNOUSERSITE="1",
               PYTHONDONTWRITEBYTECODE="1", MPLBACKEND="Agg", MPLCONFIGDIR=str(root / "mpl-cache"),
               XDG_CACHE_HOME=str(root / "cache"), NUMBA_CACHE_DIR=str(root / "numba-cache"),
               OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    env["PYTHONPATH"] = os.pathsep.join([str(app), str(deps), *([str(args.extra_deps)] if args.extra_deps else []), "/data/wangjian/geotoolagent-context-postgres/python"])

    def command(argv, log):
        with (root / log).open("w", encoding="utf-8") as out:
            run = subprocess.run(argv, cwd=app if app.exists() else root, env=env, stdout=out, stderr=subprocess.STDOUT)
        if run.returncode:
            raise RuntimeError(f"Command failed with exit code {run.returncode}; see {log}")
        return run.returncode

    @task
    def source_and_packages():
        records = json.loads((root / "downloads.json").read_text())
        for row in records:
            if hashlib.sha256((root / row["file"]).read_bytes()).hexdigest() != row["sha256"]:
                raise ValueError("Downloaded package changed: " + row["package"])
        if app.exists() or deps.exists():
            raise ValueError("This stage requires new app and dependency directories")
        shutil.copytree(args.baseline, app, symlinks=True, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".git"))
        with tarfile.open(root / "minerals-overlay.tar.gz") as archive:
            for member in archive.getmembers():
                target = (app / member.name).resolve()
                if not target.is_relative_to(app.resolve()) or not member.isfile():
                    raise ValueError("Overlay must contain only bounded regular files")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open("wb") as dest:
                    shutil.copyfileobj(source, dest)
        deps.mkdir()
        return records

    @task(depends_on=[source_and_packages])
    def dependencies(source_and_packages):
        command([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps", "--no-build-isolation", "--target", str(deps),
                 *[str(root / row["file"]) for row in source_and_packages]], "install.log")
        command([sys.executable, "-c", "import spectral,pyrolite,mplstereonet; print(spectral.__version__); print(pyrolite.__version__); print(mplstereonet.__version__)"], "import.log")
        command([sys.executable, "scripts/register_github_minerals.py", "--raster-fixtures-only"], "fixtures.log")
        return {"installed": True}

    @task(depends_on=[dependencies])
    def regressions(dependencies):
        files = ["tests_local/test_github_minerals.py", "tests_local/test_catalog_metadata.py", "tests_local/test_unified_skills.py", "tests_local/test_professional_catalog.py"]
        command([sys.executable, "-m", "pytest", "-q", *files, "--junitxml=" + str(root / "acceptance.xml"), "--basetemp=" + str(root / "pytest-work"), "-o", "cache_dir=" + str(root / "pytest-cache")], "tests.log")
        tree = ET.parse(root / "acceptance.xml")
        cases = tree.findall(".//testcase")
        failed = [case.attrib for case in cases if case.find("failure") is not None or case.find("error") is not None or case.find("skipped") is not None]
        if failed or not cases:
            raise ValueError("Acceptance contains failed, skipped or no testcases")
        native = [case.attrib["name"] for case in cases if case.attrib.get("name", "").startswith("test_every_ready_source_executes_through_native_runtime[")]
        if len(native) != 229:
            raise ValueError("Full native acceptance must execute exactly 229 professional tools")
        return {"passed": len(cases), "failed": 0, "skipped": 0, "native_professional_operations": len(native), "cases": [c.attrib for c in cases]}

    @task(depends_on=[regressions])
    def receipt(regressions):
        tracked = [app / "geological_agent/geology/github_minerals.py", app / "catalog/registry.json", app / "requirements-github-minerals.txt"]
        result = {"state": "passed", "scope": "Independent CPU scientific, schema, standalone JSON, native transport and catalog/Skill tests; synthetic fixtures; no live model calls", "deployed": False, "gpu_used": False,
                  "source_sha256": {str(p.relative_to(app)): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}, **regressions}
        (root / "acceptance.json").write_text(json.dumps(result, indent=2) + "\n")
        return result

    flow = Flow(receipt, max_workers=1, fail_fast=True, journal_path=str(root / "journal.jsonl"))
    result = flow.run()
    value = result.get("receipt")
    if not (root / "acceptance.json").exists():
        (root / "failure.json").write_text(json.dumps({"summary": str(flow.summary()), "state": "failed"}, indent=2))
        print(flow.summary(), flush=True)
        raise SystemExit(1)
    r = flow.value(receipt)
    print(json.dumps({k: v for k, v in r.items() if k not in ("cases", "source_sha256")}), flush=True)


if __name__ == "__main__":
    main()

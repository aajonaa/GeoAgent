"""Failure-specialist tests. Fake compilers are test fixtures, never tools."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def private_case(tmp_path):
    for name in ("build_accept.py", "adapters.py", "specs.py", "source-lock.json"):
        shutil.copyfile(ROOT/name, tmp_path/name)
    for name in ("vendor", "licenses", "native", "orchestration"):
        shutil.copytree(ROOT/name, tmp_path/name)
    env = dict(os.environ)
    env.update(MPLCONFIGDIR=str(tmp_path/"cache/matplotlib"), NUMBA_CACHE_DIR=str(tmp_path/"cache/numba"), XDG_CACHE_HOME=str(tmp_path/"cache/xdg"), PYTHONPATH=str(tmp_path)+":/data/wangjian/earth-python-all-20261022-r4/candidate", CUDA_VISIBLE_DEVICES="", NVIDIA_VISIBLE_DEVICES="none", PROJ_NETWORK="OFF", LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false", GEOTOOL_LANGSMITH_ENABLED="0", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMBA_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
    for key in ("MPLCONFIGDIR", "NUMBA_CACHE_DIR", "XDG_CACHE_HOME"):
        Path(env[key]).mkdir(parents=True)
    return env


@pytest.mark.parametrize("code", [17, 23])
@pytest.mark.parametrize("stage", ["compiler_version", "compile"])
def test_original_compiler_exit_reaches_top_level(tmp_path, code, stage):
    env = private_case(tmp_path)
    bin_dir = tmp_path/"fake-compilers"
    bin_dir.mkdir()
    for compiler in ("gcc", "g++"):
        file = bin_dir/compiler
        file.write_text("#!/bin/sh\n"+
            ("if [ \"$1\" = \"--version\" ]; then echo 'explicit failure-test fixture compiler'; exit "+str(code if stage == "compiler_version" and compiler == "gcc" else 0)+"; fi\n")+
            "echo 'explicit synthetic compiler failure fixture' >&2\nexit "+str(code)+"\n", encoding="utf-8")
        file.chmod(0o700)
    env["PATH"] = str(bin_dir)+os.pathsep+env["PATH"]
    before = {p.relative_to(tmp_path).as_posix(): digest(p) for p in (tmp_path/"vendor").rglob("*") if p.is_file()}
    child = subprocess.run([sys.executable, str(tmp_path/"build_accept.py")], cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30)
    (tmp_path/"top-level.log").write_text(child.stdout+child.stderr, encoding="utf-8")
    assert child.returncode == code, child.stdout+child.stderr
    status = json.loads((tmp_path/"STATUS.json").read_text(encoding="utf-8"))
    failure = json.loads((tmp_path/"last-child-failure-r2.json").read_text(encoding="utf-8"))
    assert status["complete"] is False
    assert status["child_returncode"] == failure["returncode"] == code
    assert failure["stage"].startswith(stage)
    assert (tmp_path/failure["log"]).is_file()
    assert "failure-test" in (tmp_path/failure["log"]).read_text(encoding="utf-8") or "failure fixture" in (tmp_path/failure["log"]).read_text(encoding="utf-8")
    assert not (tmp_path/"HANDOFF.json").exists()
    assert not (tmp_path/"build/build-receipt.json").exists()
    for relative, expected in before.items():
        assert digest(tmp_path/relative) == expected


@pytest.mark.parametrize("code", [4, 9])
def test_noncompiler_child_failure_reporting(tmp_path, code):
    env = private_case(tmp_path)
    program = "import pathlib,sys;import build_accept as b;b.run_recorded_child([sys.executable,'-c',\"import sys;print('explicit pytest failure fixture');sys.exit("+str(code)+")\"],pathlib.Path('child.log'),'scientific_acceptance')"
    child = subprocess.run([sys.executable, "-c", program], cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30)
    assert child.returncode != 0
    assert json.loads((tmp_path/"child-result.json").read_text(encoding="utf-8"))["returncode"] == code
    assert json.loads((tmp_path/"last-child-failure-r2.json").read_text(encoding="utf-8"))["returncode"] == code
    assert "explicit pytest failure fixture" in (tmp_path/"child.log").read_text(encoding="utf-8")


def test_child_success_does_not_create_failure_receipt(tmp_path):
    env = private_case(tmp_path)
    program = "import pathlib,sys;import build_accept as b;r=b.run_recorded_child([sys.executable,'-c',\"print('explicit successful control child')\"],pathlib.Path('child.log'),'control_success');assert r.returncode==0"
    child = subprocess.run([sys.executable, "-c", program], cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30)
    assert child.returncode == 0, child.stderr
    assert not (tmp_path/"last-child-failure-r2.json").exists()
    assert "successful control" in (tmp_path/"child.log").read_text(encoding="utf-8")


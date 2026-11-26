"""Local-only Flow; remote policy rejection cannot reach an alternate action."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

GROUP=Path(__file__).resolve().parents[1]; ROOT=GROUP.parents[4]
sys.path.insert(0,str(Path.home()/".codex/skills/flowing/scripts"))
from flowing import Flow,task
RUN=GROUP/"acceptance"/("local-continuation-r7-"+str(time.time_ns()))


@task
def local_policy_gate():
    RUN.mkdir(parents=True,exist_ok=False)
    return {"local_source_only":True,"remote_preparation":False,"native_execution":False}


@task(depends_on=[local_policy_gate],when=lambda local_policy_gate:local_policy_gate["local_source_only"])
def generate(local_policy_gate):
    p=subprocess.run([sys.executable,"-B",str(GROUP/"build_resolution.py")],cwd=ROOT,capture_output=True,timeout=30)
    (RUN/"generator.stdout.log").write_bytes(p.stdout); (RUN/"generator.stderr.log").write_bytes(p.stderr)
    if p.returncode: raise RuntimeError("Generator failed; retain evidence, no retry")
    return {"exit_code":p.returncode}


@task(depends_on=[generate],when=lambda generate:generate["exit_code"]==0)
def local_contract_tests(generate):
    env=dict(os.environ)
    for name in ("HOME","TMP","TEMP","TMPDIR","XDG_CACHE_HOME","MPLCONFIGDIR","NUMBA_CACHE_DIR"):
        path=RUN/name.lower(); path.mkdir(); env[name]=str(path)
    env.update(CUDA_VISIBLE_DEVICES="",NVIDIA_VISIBLE_DEVICES="none",ROCR_VISIBLE_DEVICES="",HIP_VISIBLE_DEVICES="",
               OMP_NUM_THREADS="1",OPENBLAS_NUM_THREADS="1",MKL_NUM_THREADS="1",NUMEXPR_NUM_THREADS="1",
               LANGCHAIN_TRACING_V2="false",LANGSMITH_TRACING="false",PYTHONDONTWRITEBYTECODE="1",
               SPATIAL_R7_LOCAL_REPORT=str(RUN/"tests.json"))
    p=subprocess.run([sys.executable,"-B",str(GROUP/"acceptance/test_continuation_r7.py")],cwd=ROOT,env=env,capture_output=True,timeout=30)
    (RUN/"tests.stdout.log").write_bytes(p.stdout); (RUN/"tests.stderr.log").write_bytes(p.stderr)
    print(p.stdout.decode("utf-8","replace")); print(p.stderr.decode("utf-8","replace"))
    if p.returncode: raise RuntimeError("Local test failed; preserve logs and report before any repair")
    return json.loads((RUN/"tests.json").read_text())


@task(depends_on=[local_contract_tests],when=lambda local_contract_tests:not(local_contract_tests["failures"] or local_contract_tests["errors"] or local_contract_tests["skipped"]))
def source_handoff(local_contract_tests):
    return {"source_stable":True,"concrete_pending":15,"incomplete":4,"integration_blocked":19,
            "native_scientific_tests_run":0,"new_registered":0,"new_accepted":0,"new_deployed":0}


if __name__=="__main__":
    results=Flow(source_handoff,max_workers=1).run()
    report={"evidence_path":str(RUN),"steps":{name:{"state":result.state.value,"value":result.value,
             "error":str(result.error) if result.error else None} for name,result in results.items()}}
    (RUN/"flow-result.json").write_text(json.dumps(report,indent=2)+"\n")
    delivery_path=GROUP/"delivery-files.json"
    delivery=json.loads(delivery_path.read_text())
    names=("generator.stdout.log","generator.stderr.log","tests.stdout.log","tests.stderr.log","tests.json","flow-result.json")
    # Only paths actually emitted by a reached gate are declared, including failures.
    delivery["files"]=sorted(set(delivery["files"]+[p.relative_to(ROOT).as_posix() for p in (RUN/name for name in names) if p.is_file()]))
    delivery_path.write_text(json.dumps(delivery,indent=2)+"\n")
    print(json.dumps(report))
    ok="source_handoff" in results and results["source_handoff"].state.value=="succeeded"
    raise SystemExit(0 if ok else 1)

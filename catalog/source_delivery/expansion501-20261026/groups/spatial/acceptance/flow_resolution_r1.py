"""Flow owns source -> local test -> evidence gates; no remote retry branch."""
import json
from pathlib import Path
import runpy
import subprocess
import sys
import time

GROUP=Path(__file__).resolve().parents[1]
ROOT=GROUP.parents[4]
sys.path.insert(0,str(Path.home()/".codex/skills/flowing/scripts"))
from flowing import Flow,task

RUN=GROUP/"acceptance"/("local-resolution-"+str(time.time_ns()))
RUN.mkdir()


@task
def policy_gate():
    return {"local_source_and_tests":True,"remote_retry_allowed":False,"deployment_allowed":False}


@task(depends_on=[policy_gate],when=lambda policy_gate:policy_gate["local_source_and_tests"])
def materialize(policy_gate):
    runpy.run_path(str(GROUP/"build_resolution.py"),run_name="__main__")
    return {"source_materialized":True}


@task(depends_on=[materialize],when=lambda materialize:materialize["source_materialized"])
def local_tests(materialize):
    import os
    env=os.environ.copy()
    for key in ("CUDA_VISIBLE_DEVICES","ROCR_VISIBLE_DEVICES","HIP_VISIBLE_DEVICES"):
        env[key]=""
    env["NVIDIA_VISIBLE_DEVICES"]="none"
    for key in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS"):
        env[key]="1"
    for key in ("HOME","XDG_CACHE_HOME","MPLCONFIGDIR","NUMBA_CACHE_DIR","TMP","TEMP"):
        private=RUN/key.lower(); private.mkdir(); env[key]=str(private)
    env.update(PYTHONDONTWRITEBYTECODE="1",LANGCHAIN_TRACING_V2="false",LANGSMITH_TRACING="false")
    with (RUN/"stdout.log").open("xb") as stdout,(RUN/"stderr.log").open("xb") as stderr:
        result=subprocess.run([sys.executable,str(GROUP/"acceptance/test_resolution_r1.py")],cwd=ROOT,
                              env=env,stdout=stdout,stderr=stderr,timeout=90,check=False)
    report={"exit_code":result.returncode,"report_directory":str(RUN),"scope":"local source/contract tests; scientific class may skip",
            "native_tests_executed":0,"integrated_runtime_acceptance":False,"remote_work":False}
    (RUN/"result.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    return report


if __name__=="__main__":
    result=Flow(local_tests,max_workers=1).run()
    print(str(RUN))
    print(result)

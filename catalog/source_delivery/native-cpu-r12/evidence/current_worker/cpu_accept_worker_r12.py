"""Fresh CPU-only integration gate; no other candidate is modified."""
import hashlib,json,os,socket,subprocess,sys,traceback
from dataclasses import asdict
from pathlib import Path
from threading import Event
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parent
CANDIDATE=ROOT/"candidate"
ORIGINAL=ROOT.parent
sys.path.insert(0,str(ORIGINAL/"orchestration"))
from flowing import Flow,task
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def dump(name,value):
    with (ROOT/name).open("x",encoding="utf-8") as stream: json.dump(value,stream,indent=2,ensure_ascii=True)
@task
def frozen_originals():
    frozen=json.loads((ORIGINAL/"freeze-r5.json").read_text())
    assert frozen["complete"] and frozen["tests"]=={"total":87,"failed":0,"errors":0,"skipped":0,"original_scientific":80,"failure_specialists":7}
    assert frozen["protected_files_unchanged"]
    for name,expected in frozen["protected_after_sha256"].items(): assert sha(ORIGINAL/name)==expected
    manifest=json.loads((ROOT/"archive-files-sha256.json").read_text())
    for name,expected in manifest.items(): assert sha(ROOT/name)==expected
    return {"freeze_sha256":sha(ORIGINAL/"freeze-r5.json"),"originals":frozen["protected_after_sha256"],"candidate":{name:expected for name,expected in manifest.items() if name.startswith("candidate/")}}
@task(depends_on=[frozen_originals])
def protocol_tests(frozen_originals):
    command=[sys.executable,"-m","pytest",str(CANDIDATE/"tests_local/test_native_cpu_integration.py"),str(CANDIDATE/"tests_local/test_native_cpu_error_policy.py"),"-q","--junitxml="+str(ROOT/"integration.xml"),"--basetemp="+str(ROOT/"pytest-private")]
    run=subprocess.run(command,cwd=CANDIDATE,env=dict(os.environ),capture_output=True,text=True)
    dump("child-result.json",{"command":command,"returncode":run.returncode})
    with (ROOT/"integration.log").open("x",encoding="utf-8") as stream: stream.write(run.stdout+run.stderr)
    if run.returncode: raise ChildProcessError("ToolExecutor acceptance exited "+str(run.returncode))
    cases=list(ET.parse(ROOT/"integration.xml").iter("testcase"))
    summary={"total":len(cases),"failed":sum(c.find("failure") is not None for c in cases),"errors":sum(c.find("error") is not None for c in cases),"skipped":sum(c.find("skipped") is not None for c in cases)}
    assert summary=={"total":29,"failed":0,"errors":0,"skipped":0}
    return summary
@task(depends_on=[protocol_tests])
def real_execution_receipts(protocol_tests):
    def denied(*args,**kwargs): raise AssertionError("Native scientific receipt attempted networking")
    socket.socket.connect=denied
    socket.create_connection=denied
    from geological_agent.bootstrap import build_registry
    from geological_agent.contracts import ToolCall
    from geological_agent.settings import Settings
    from geological_agent.tools import ToolExecutionContext,ToolExecutor
    from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog
    from collection_acceptance.native_cpu_checks import check
    registry,loader,base=build_registry()
    rows={row["id"]:row for row in catalog()["tools"]}
    meta=json.loads((CANDIDATE/"native-cpu-integration-baseline.json").read_text())
    workspace=ROOT/"receipt-workspace"
    workspace.mkdir(exist_ok=False)
    receipts={}
    for name in meta["new_tools"]:
        args=json.loads(json.dumps(rows[name]["example_arguments"]))
        before=json.dumps(args,sort_keys=True,allow_nan=False)
        context=ToolExecutionContext("c-native-receipts-r6",workspace,(name,),Settings(),Event())
        result=ToolExecutor(registry).execute(ToolCall("receipt-r6-"+name,name,args),context)
        assert result.status=="ok",asdict(result)
        assert before==json.dumps(args,sort_keys=True,allow_nan=False)
        check(name,result.data,args,output_dir=None)
        receipts[name]=asdict(result)
    dump("operation-results.json",receipts)
    return {"actual_tool_executor_operations":len(receipts),"tools":len(rows),"skills":len(catalog()["skills"]),"results_sha256":sha(ROOT/"operation-results.json")}
@task(depends_on=[frozen_originals,protocol_tests,real_execution_receipts])
def accepted(frozen_originals,protocol_tests,real_execution_receipts):
    for name,expected in frozen_originals["originals"].items(): assert sha(ORIGINAL/name)==expected
    for name,expected in frozen_originals["candidate"].items(): assert sha(ROOT/name)==expected
    assert real_execution_receipts["tools"]==204 and real_execution_receipts["skills"]==43
    profile=CANDIDATE/"geological_agent/geology/native-cpu-profiles.json"
    result={"complete":True,"status":"independent_frozen_C_and_ToolExecutor_accepted","exit_code":0,"freeze":frozen_originals["freeze_sha256"],"scientific_and_controls":87,"integration_tests":protocol_tests,"real_execution":real_execution_receipts,"profile_sha256":sha(profile),"bridge_sha256":sha(CANDIDATE/"geological_agent/geology/native_cpu_bridge.py"),"kernels_sha256":sha(CANDIDATE/"geological_agent/geology/native_cpu_kernels.py"),"input_archive_sha256":json.loads((ROOT/"source-archive-receipt.json").read_text())["sha256"],"all_candidate_and_original_source_hashes_unchanged":True,"parent_baseline_tools_preserved":201,"parent_baseline_skills_preserved":42,"full_union_regression":"pending_parent","globally_registered":False,"HPGL_distribution_license_review":"pending","formal_packaging":"not_performed","gpu_used":False,"production_modified":False,"other_candidate_modified":False,"deployed":False,"pushed":False}
    dump("integration-result.json",result)
    return result
def main():
    flow=Flow(accepted,max_workers=1,journal_path=str(ROOT/"integration-r12-flow.jsonl"))
    try:
        flow.run()
        result=flow.value(accepted)
        assert result["complete"]
        print(json.dumps(result))
        return 0
    except Exception:
        child=ROOT/"child-result.json"
        code=(json.loads(child.read_text())["returncode"] if child.exists() else 1) or 1
        result={"complete":False,"exit_code":code,"error":traceback.format_exc(),"gpu_used":False,"production_modified":False,"other_candidate_modified":False}
        dump("integration-result.json",result)
        print(json.dumps(result))
        return code
if __name__=="__main__": raise SystemExit(main())

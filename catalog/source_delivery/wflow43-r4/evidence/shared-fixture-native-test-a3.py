
from pathlib import Path
import os
root=Path('/data/wangjian/earth-python-approved-replacements-20261022/wflow43-collection-native-r4')
for key,leaf in (('MPLCONFIGDIR','matplotlib'),('NUMBA_CACHE_DIR','numba'),('XDG_CACHE_HOME','xdg')):
 p=root/'cache/shared-fixture-a3'/leaf;p.mkdir(parents=True,exist_ok=True);os.environ[key]=str(p)
os.environ.update(CUDA_VISIBLE_DEVICES='',NVIDIA_VISIBLE_DEVICES='none',PROJ_NETWORK='OFF',LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false',GEOTOOL_LANGSMITH_ENABLED='0',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1',NUMBA_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1')
import hashlib,importlib.util,json,sys
from dataclasses import asdict
sys.path.insert(0,str(root))
import fixed_entry_collection as entry
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
fixture_path=root/'proposal/acceptance/fixtures.py'
check_path=root/'proposal/acceptance/checks.py'
fixture=load('reviewed_wflow_fixture',fixture_path)
checks=load('reviewed_wflow_checks',check_path)
workspace=root/'workspaces/shared-fixture-a3';workspace.mkdir(parents=True,exist_ok=False)
examples=fixture.prepare(workspace);arguments=examples[entry.NAME]
inputs={str(p.relative_to(workspace)):digest(p) for p in workspace.rglob('*') if p.is_file()}
protected=[fixture_path,check_path,root/'candidate/catalog/registry.json',root/'candidate/geological_agent/geology/collection_contracts.py',root/'candidate/geological_agent/geology/collection_wflow43.py']
before={str(p.relative_to(root)):digest(p) for p in protected}
registry,skills,base=entry.build_registry()
assert tuple(skills.load('wflow_kinematic_reach').tool_names)==(entry.NAME,)
result=entry.ToolExecutor(registry).execute(entry.ToolCall('shared-fixture-a3',entry.NAME,arguments),entry.ToolExecutionContext('fixture-cpu',workspace,(entry.NAME,),entry.Settings(tool_timeout_seconds=0),entry.Event()))
assert result.status=='ok',asdict(result)
checks.check(entry.NAME,result.data,arguments)
assert result.artifacts==() and result.data['artifacts']==[] and result.data['provenance']['output_sha256']=={}
assert inputs=={str(p.relative_to(workspace)):digest(p) for p in workspace.rglob('*') if p.is_file()}
after={str(p.relative_to(root)):digest(p) for p in protected};assert after==before
record={'cases':1,'passed':True,'native_call':asdict(result),'fixture_SHA256':digest(fixture_path),'shared_check_SHA256':digest(check_path),'input_files_SHA256':inputs,'sources_before':before,'sources_after':after,'sources_unchanged':True,'actual_shared_SDK_and_registry_and_Skill':True,'GPU_used':False,'models_used':False,'runtime_installs':False}
(root/'evidence/shared-fixture-native-a3.json').write_text(json.dumps(record,indent=2,allow_nan=False))
print(json.dumps(record,allow_nan=False))

"""Real shared registry and CPU workers; historical sidecar tests are not recounted."""
from copy import deepcopy
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
from threading import Event
import pytest
from geological_agent.bootstrap import build_registry
from geological_agent.contracts import ToolCall
from geological_agent.settings import Settings
from geological_agent.tools import ToolExecutionContext,ToolExecutor
from geological_agent.geology.source_registry import source_tools
from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog,validate_registration_metadata
from source_asset_checks.run import check_assets
from collection_acceptance.hydro_models_checks import check

ROOT=Path(__file__).resolve().parents[1]
CONTRIBUTION=json.loads((ROOT/'geological_agent/geology/collection_hydro_cpu/manifest.json').read_text())
NAMES=list(CONTRIBUTION['operations'])
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def test_exact_extended_counts_and_every_frozen_definition():
    current=catalog();baseline=CONTRIBUTION['baseline_definitions']
    assert len(current['tools'])==220 and len(current['skills'])==47
    for kind in ['tools','skills']:
        actual={row['id']:hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=True).encode()).hexdigest() for row in current[kind]}
        assert all(actual[name]==wanted for name,wanted in baseline[kind].items())
    assert len(baseline['tools'])==214 and len(baseline['skills'])==46
    groups=json.loads((ROOT/'collection-manifests.json').read_text())
    rows=[row for group in groups.values() for row in group['projects']]
    assert len(rows)==101 and len({row['id'] for row in rows})==101
    assert sum(row['id']==55 for row in rows)==1

def test_registry_skill_examples_and_unmodified_asset_checker():
    registry,skills,_=build_registry()
    skill=skills.load('earth_collection_hydro_cpu_profiles')
    assert tuple(skill.tool_names)==tuple(NAMES)
    assert set(NAMES)<=set(registry.names())
    rows=check_assets(catalog(),source_tools())
    assert rows and all(row['status']=='passed' for row in rows),rows
    for name in NAMES:
        spec=source_tools()[name];validate_registration_metadata(spec)
        assert registry.get(name).definition.input_schema==spec['input_schema']
        assert registry.get(name).definition.result_schema==spec['output_schema']
        assert spec['metadata']['cpu_execution']['requirements_scope']=='worker'
        assert spec['metadata']['upstream']['requirements']==CONTRIBUTION['operations'][name]['requirements']
        assert (ROOT/spec['example_arguments']['data_path']).is_file()

@pytest.mark.parametrize('name',NAMES)
@pytest.mark.parametrize('case',['dict','json','unknown_argument','missing_argument','escape_path','invalid_scientific_input'])
def test_real_shared_sdk_native(name,case,tmp_path):
    spec=source_tools()[name];cfg=CONTRIBUTION['operations'][name]
    args=deepcopy(spec['example_arguments']);source=ROOT/args['data_path']
    data=json.loads(source.read_text());target=tmp_path/'input.json';target.write_bytes(source.read_bytes())
    args['data_path']=target.name;before=sha(target)
    if case=='invalid_scientific_input':
        if name=='EarthCatchmodLinearStoreStep':data['initial_outflow_mm_day']=[0.]
        elif name.endswith('HydPyFlowScores'):data['observed_m3_s']=[2.,2.,2.,2.]
        elif name.endswith('PySTEPSPrecipitationAdvection'):data['east_velocity_pixels_step']=[[0.,0.],[0.,0.]]
        elif name.endswith('PyDEMTerrainDerivatives'):data['elevation_m']=[[1.,2.,3.],[2.],[3.,4.,5.]]
        elif name.endswith('PyFloCurveNumberRunoff'):data['rainfall_inches']=[-1.]
        elif name.endswith('SuperflexUnitHydrograph'):data['effective_rainfall_mm_step']=[-1.]
        negative=tmp_path/'negative.json';negative.write_text(json.dumps(data));args['data_path']=negative.name
    arguments=json.dumps(args) if case=='json' else args
    if case=='unknown_argument':arguments={**args,'unreviewed_option':True}
    if case=='missing_argument':arguments={}
    if case=='escape_path':arguments={**args,'data_path':'../outside.json'}
    registry,_,_=build_registry();context=ToolExecutionContext('hydro-shared-sdk',tmp_path,(name,),Settings(),Event())
    call=ToolCall(name+'_'+case,name,arguments)
    result=ToolExecutor(registry).execute(call,context)
    assert result.call_id==call.id and result.name==name
    if case in ['dict','json']:
        assert result.status=='ok',result
        oracle={**args,'data_path':str(target)};check(name,result.data,oracle,None)
        proof=result.data['provenance']
        assert proof['implementation_sha256']==sha(ROOT/'geological_agent/geology/collection_hydro_cpu/adapters.py')
        assert proof['upstream_adapter_sha256']==cfg['implementation_sha256']
        assert proof['binary_sha256']==cfg['kernel_sha256']
        assert proof['build_receipt_sha256']==cfg['build_receipt_sha256']
        assert proof['runtime_install'] is False and proof['runtime_compile'] is False and proof['gpu_used'] is False
        for requirement in cfg['requirements']:
            package,wanted=requirement.split('==');assert proof['installed_versions'][package]==wanted
        assert not result.artifacts and not proof['output_sha256']
    else:
        assert result.status=='error',result
        assert result.error.code==('invalid_path' if case=='escape_path' else 'invalid_arguments'),result
        assert result.error.retryable is False
    assert sha(target)==before

def test_host_dependencies_are_not_worker_claims():
    host=CONTRIBUTION['host_dependency_snapshot']
    for package,wanted in host.items():
        try:actual=metadata.version(package)
        except metadata.PackageNotFoundError:actual=None
        assert actual==wanted
    assert CONTRIBUTION['worker_dependencies_installed_in_host_by_this_integration'] is False


@pytest.mark.parametrize('failure,expected',[('entrypoint','invalid_result'),('bound_file','integrity_error')])
def test_worker_integrity_is_not_generic_upstream(failure,expected,tmp_path):
    """Labelled control fixture: no scientific function is executed."""
    import os,shutil,subprocess
    profiles=json.loads((ROOT/'geological_agent/geology/native-cpu-profiles.json').read_text())
    name='HydroModelsPyFloCurveNumberRunoff';binding=profiles['operations'][name]
    original=Path(binding['entrypoint']);cfg=json.loads((original.parent/'workers.json').read_text())
    local=tmp_path/'fixed-worker';local.mkdir()
    entry=local/'worker.py';shutil.copyfile(original,entry)
    if failure=='entrypoint':cfg['entrypoint_sha256']='0'*64
    else:
        kernel=cfg['operations'][name]['kernel_path']
        cfg['operations'][name]['files_sha256'][kernel]='0'*64
    (local/'workers.json').write_text(json.dumps(cfg))
    env=dict(os.environ,CUDA_VISIBLE_DEVICES='',NVIDIA_VISIBLE_DEVICES='none',PROJ_NETWORK='OFF',
        MPLCONFIGDIR=str(local/'cache/matplotlib'),NUMBA_CACHE_DIR=str(local/'cache/numba'),
        XDG_CACHE_HOME=str(local/'cache/xdg'),LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false',
        PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',
        MKL_NUM_THREADS='2',NUMBA_NUM_THREADS='2')
    cp=subprocess.run([binding['python'],str(entry),name],input=b'{}',stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,env=env,timeout=120)
    assert cp.returncode==3
    value=json.loads(cp.stdout);assert value['status']=='error'
    assert value['error']['code']==expected
    assert value['error']['code'] not in ['upstream_failure','invalid_arguments']
    assert value['error']['retryable'] is False


@pytest.mark.parametrize('name',NAMES)
@pytest.mark.parametrize('serialized',[False,True],ids=['args_dict','args_json'])
def test_actual_source_keyword_args(name,serialized,tmp_path):
    from source_asset_checks.run import invoke_source
    spec=source_tools()[name];args=deepcopy(spec['example_arguments'])
    source=ROOT/args['data_path'];target=tmp_path/args['data_path']
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes())
    before=sha(target);output=tmp_path/'outputs';output.mkdir()
    response=invoke_source(spec,args,tmp_path,output,serialized=serialized)
    assert response['ok'] and response['artifacts']==[]
    absolute={**args,'data_path':str(target)}
    check(name,response['result'],absolute,None)
    proof=response['result']['provenance']
    assert proof['runtime_install'] is False and proof['runtime_compile'] is False and proof['gpu_used'] is False
    assert not proof['output_sha256'] and sha(target)==before

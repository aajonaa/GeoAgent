"""Actual library and ToolExecutor evidence; no synthetic data presented as real."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import importlib
from importlib import metadata
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
from threading import Event

import pytest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'candidate'))
SPECTRAL='ScipyGroundwaterFrequencyResponse'
FORECAST='StatsmodelsSeasonalFlowForecast'
EXAMPLES=json.loads((HERE/'synthetic_examples.json').read_text())['examples']


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def canonical_hash(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=True,allow_nan=False).encode()).hexdigest()


@pytest.fixture(autouse=True)
def cpu_offline(monkeypatch):
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='' and os.environ.get('NVIDIA_VISIBLE_DEVICES')=='none'
    assert os.environ.get('PROJ_NETWORK')=='OFF'
    for name in ['MPLCONFIGDIR','NUMBA_CACHE_DIR','XDG_CACHE_HOME']:
        assert str(HERE) in os.environ.get(name,'')
    def deny(*args,**kwargs):raise AssertionError('Unexpected scientific network call')
    monkeypatch.setattr(socket.socket,'connect',deny)
    monkeypatch.setattr(socket,'create_connection',deny)
    class NoModels:
        def find_spec(self,fullname,path=None,target=None):
            if fullname.split('.')[0] in {'torch','tensorflow','tensorboard','jax'}:
                raise AssertionError('Unexpected model import '+fullname)
    finder=NoModels();sys.meta_path.insert(0,finder)
    yield
    sys.meta_path.remove(finder)
    assert not any(name.split('.')[0] in {'torch','tensorflow','tensorboard','jax'} for name in sys.modules)


def operation(name):
    module=importlib.import_module('geological_agent.geology.collection_approved_replacements')
    return getattr(module,'groundwater_frequency_response' if name==SPECTRAL else 'seasonal_flow_forecast')


def check_spectral(result,args,gain=0.8,phase=-math.pi/6):
    import numpy as np
    f=np.asarray(result['frequency_Hz'])
    expected=1/(32*3600.)
    index=int(np.argmin(np.abs(f-expected)))
    assert math.isclose(f[index],expected,rel_tol=1e-14,abs_tol=1e-18)
    assert result['valid_response'][index]
    assert math.isclose(result['gain_head_per_pressure_head'][index],gain,rel_tol=1e-10,abs_tol=1e-11)
    error=np.angle(np.exp(1j*(result['phase_rad'][index]-phase)))
    assert abs(error)<1e-10
    assert math.isclose(result['coherence'][index],1.,abs_tol=1e-12)
    dt=args['times_seconds'][1]-args['times_seconds'][0]
    length=result['samples_per_segment']
    assert math.isclose(result['pressure_head_psd_m2_per_Hz'][index],length*dt/3,rel_tol=1e-10)
    df=f[1]-f[0]
    assert math.isclose(math.fsum(result['pressure_head_psd_m2_per_Hz'])*df,0.5,rel_tol=1e-10)
    assert len(f)==length//2+1
    for key in ['gain_head_per_pressure_head','phase_rad','coherence','pressure_head_psd_m2_per_Hz','groundwater_head_psd_m2_per_Hz','valid_response']:
        assert len(result[key])==len(f)
    assert not result['valid_response'][0]
    for key in ['gain_head_per_pressure_head','phase_rad','coherence']:
        assert all((value is not None)==valid for value,valid in zip(result[key],result['valid_response']))
    assert result['units']=={'frequency_Hz':'Hz','gain_head_per_pressure_head':'1','phase_rad':'rad','coherence':'1',
        'pressure_head_psd_m2_per_Hz':'m2/Hz','groundwater_head_psd_m2_per_Hz':'m2/Hz','sample_interval_seconds':'s'}


def check_forecast(result,args):
    import numpy as np
    from scipy.stats import t
    def design(phases,predictors):
        angle=2*np.pi*np.asarray(phases)
        return np.column_stack((np.ones(len(phases)),np.sin(angle),np.cos(angle),np.asarray(predictors)))
    x=design(args['training_annual_phase'],args['training_predictors_dimensionless'])
    xf=design(args['forecast_annual_phase'],args['forecast_predictors_dimensionless'])
    y=np.asarray(args['observed_flow_m3_s'])
    coefficients=np.linalg.lstsq(x,y,rcond=None)[0]
    mean=xf@coefficients
    residual=y-x@coefficients
    degrees=len(y)-x.shape[1]
    variance=float(residual@residual/degrees)
    mean_var=variance*np.einsum('ij,jk,ik->i',xf,np.linalg.inv(x.T@x),xf)
    quantile=float(t.ppf((1+args.get('confidence_level',.95))/2,degrees))
    expected={'forecast_mean_m3_s':mean,'mean_ci_lower_m3_s':mean-quantile*np.sqrt(mean_var),
        'mean_ci_upper_m3_s':mean+quantile*np.sqrt(mean_var),
        'prediction_lower_m3_s':mean-quantile*np.sqrt(mean_var+variance),
        'prediction_upper_m3_s':mean+quantile*np.sqrt(mean_var+variance)}
    for name,values in expected.items():
        np.testing.assert_allclose(result[name],values,rtol=1e-10,atol=1e-10)
        assert result['units'][name]=='m3/s'
    np.testing.assert_allclose(result['coefficients_m3_s'],coefficients,rtol=1e-10,atol=1e-10)
    assert result['units']['coefficients_m3_s']=='m3/s'
    assert result['residual_df']==degrees and result['design_rank']==x.shape[1]
    assert result['forecast_samples']==len(xf) and result['training_samples']==len(x)
    assert result['contains_negative_statistical_output']==bool(any(np.any(values<0) for values in expected.values()))


def check_result(name,result,args):
    check_spectral(result,args) if name==SPECTRAL else check_forecast(result,args)
    assert result['artifacts']==[] and result['provenance']['output_sha256']=={}
    assert result['provenance']['input_sha256']==canonical_hash(args)
    assert result['provenance']['tool']==name and result['provenance']['source_mode']=='package_release'
    assert result['provenance']['implementation_sha256']==digest(operation(name).__wrapped__.__code__.co_filename)


@pytest.mark.parametrize('name',[SPECTRAL,FORECAST])
@pytest.mark.parametrize('mode',['dict','json','keyword'])
def test_direct_dict_json_args_actual_libraries(name,mode):
    args=deepcopy(EXAMPLES[name]); original=deepcopy(args)
    fn=operation(name)
    result=fn(args=args) if mode=='keyword' else fn(json.dumps(args) if mode=='json' else args)
    assert args==original
    check_result(name,result,args)


@pytest.mark.parametrize('gain,phase',[(1.,0.),(2.,0.4),(0.25,-0.8)])
def test_spectral_known_gain_and_phase(gain,phase):
    args=deepcopy(EXAMPLES[SPECTRAL])
    args['groundwater_head_m']=[gain*math.cos(2*math.pi*i/32+phase) for i in range(len(args['times_seconds']))]
    result=operation(SPECTRAL)(args)
    check_spectral(result,args,gain,phase)


@pytest.mark.parametrize('confidence',[0.8,0.95,0.99])
def test_actual_prediction_interval_confidence(confidence):
    args=deepcopy(EXAMPLES[FORECAST]);args['confidence_level']=confidence
    check_forecast(operation(FORECAST)(args),args)


def test_negative_statistical_forecast_is_not_fabricated_or_clipped():
    args=deepcopy(EXAMPLES[FORECAST])
    args['forecast_predictors_dimensionless']=[[-100.],[-90.],[-80.]]
    result=operation(FORECAST)(args)
    check_forecast(result,args)
    assert result['contains_negative_statistical_output']
    assert all(value<0 for value in result['forecast_mean_m3_s'])


def invalid_case(name,variant):
    args=deepcopy(EXAMPLES[name])
    if variant=='unknown':args['unreviewed_formula']='user code is not supported'
    elif variant=='nonfinite':args['pressure_head_m' if name==SPECTRAL else 'observed_flow_m3_s'][0]=float('nan')
    elif name==SPECTRAL:
        if variant=='irregular':args['times_seconds'][8]+=30
        elif variant=='constant':args['pressure_head_m']=[2.]*len(args['pressure_head_m'])
        elif variant=='shape':args['groundwater_head_m'].pop()
        elif variant=='segment':args['samples_per_segment']=True
    else:
        if variant=='rank':args['training_predictors_dimensionless']=[[1.] for _ in args['training_predictors_dimensionless']]
        elif variant=='shape':args['forecast_predictors_dimensionless'][0].append(1.)
        elif variant=='confidence':args['confidence_level']=1.
        elif variant=='negative_flow':args['observed_flow_m3_s'][0]=-1.
        elif variant=='insufficient':
            for key in ['observed_flow_m3_s','training_annual_phase','training_predictors_dimensionless']:args[key]=args[key][:8]
            args['training_predictors_dimensionless']=[row+[0.,0.,0.,0.,0.] for row in args['training_predictors_dimensionless']]
            args['forecast_predictors_dimensionless']=[row+[0.,0.,0.,0.,0.] for row in args['forecast_predictors_dimensionless']]
    return args


NEGATIVE=[(SPECTRAL,variant) for variant in ['unknown','nonfinite','irregular','constant','shape','segment']]
NEGATIVE += [(FORECAST,variant) for variant in ['unknown','nonfinite','rank','shape','confidence','negative_flow','insufficient']]


@pytest.mark.parametrize('name,variant',NEGATIVE)
@pytest.mark.parametrize('mode',['dict','json','keyword'])
def test_schema_and_operation_rejections_do_not_execute_delivery(name,variant,mode):
    from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError
    args=invalid_case(name,variant)
    before=json.dumps(args,sort_keys=True)
    fn=operation(name)
    with pytest.raises(ScientificToolError) as caught:
        fn(args=args) if mode=='keyword' else fn(json.dumps(args) if mode=='json' else args)
    assert caught.value.code=='invalid_arguments' and not caught.value.retryable
    assert json.dumps(args,sort_keys=True)==before


@pytest.mark.parametrize('name',[SPECTRAL,FORECAST])
def test_real_native_ToolExecutor_with_input_and_artifact_checks(name,tmp_path):
    from geological_agent.bootstrap import build_registry
    from geological_agent.contracts import ToolCall
    from geological_agent.settings import Settings
    from geological_agent.tools import ToolExecutionContext,ToolExecutor
    args=deepcopy(EXAMPLES[name]);original=deepcopy(args)
    canary=tmp_path/'synthetic-input-preservation-canary.json';canary.write_text(json.dumps(args))
    before=digest(canary)
    registry,_,base=build_registry()
    assert name not in base
    result=ToolExecutor(registry).execute(ToolCall('independent-'+name,name,args),
        ToolExecutionContext('explicit-replacement-acceptance',tmp_path,(name,),Settings(),Event()))
    assert result.status=='ok',result.error
    assert not result.artifacts and digest(canary)==before and args==original
    check_result(name,result.data,args)
    (tmp_path/'native-evidence.json').write_text(json.dumps(asdict(result),indent=2))


@pytest.mark.parametrize('name',[SPECTRAL,FORECAST])
def test_fixed_entry_uses_same_exact_profile_and_real_native_runtime(name,tmp_path):
    source=tmp_path/'arguments.json';source.write_text(json.dumps(EXAMPLES[name]));before=digest(source)
    run=subprocess.run([sys.executable,str(HERE/'fixed_entry_replacements_r1.py'),'--operation',name,
                        '--workspace',str(tmp_path),'--arguments-file',str(source)],env=dict(os.environ),
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
    assert run.returncode==0,run.stderr.decode(errors='replace')
    result=json.loads(run.stdout)
    assert result['status']=='ok' and result['artifacts']==[] and digest(source)==before
    check_result(name,result['data'],EXAMPLES[name])
    (tmp_path/'fixed-entry-evidence.json').write_text(json.dumps(result,indent=2))


def test_fixed_entry_preserves_structured_native_failure_and_exit_code(tmp_path):
    source=tmp_path/'arguments.json';source.write_text(json.dumps(invalid_case(FORECAST,'rank')))
    run=subprocess.run([sys.executable,str(HERE/'fixed_entry_replacements_r1.py'),'--operation',FORECAST,
                        '--workspace',str(tmp_path),'--arguments-file',str(source)],env=dict(os.environ),
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
    assert run.returncode==1
    result=json.loads(run.stdout)
    assert result['status']=='error' and result['error']['code']=='invalid_arguments'
    assert not result['artifacts']
    (tmp_path/'fixed-entry-error-evidence.json').write_text(json.dumps(result,indent=2))


def test_exact_dependency_and_source_provenance_not_worker_impersonation():
    from legacy.ToolsAgent.ToolsFuns.source_contracts import definition
    for name in [SPECTRAL,FORECAST]:
        spec=definition(name)
        upstream=spec['metadata']['upstream']
        assert upstream['source_mode']=='package_release'
        for pin in upstream['requirements']:
            package,version=pin.split('==')
            assert metadata.version(package)==version
        replacement=spec['metadata']['functional_replacement']
        assert replacement['original_project_id']==(72 if name==SPECTRAL else 82)
        assert not replacement['original_implementation_claimed'] and not replacement['original_code_reused']
    record=json.loads((HERE/'runtime-profile.json').read_text())
    for row in record['source_files']:
        assert digest(row['path'])==row['sha256']
    assert record['worker_bridge_used'] is False and record['runtime_installs'] is False


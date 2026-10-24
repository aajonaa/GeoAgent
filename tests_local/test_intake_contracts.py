"""New interface regressions, using synthetic data only and no model/GPU."""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
from threading import Event

import pytest
from geological_agent.bootstrap import build_registry
from geological_agent.contracts import ToolCall
from geological_agent.settings import Settings
from geological_agent.tools import ToolExecutionContext, ToolExecutor
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError
from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog

NAMES=('GeoVerdeGrid','GeoRegionMask','HydroErrorMetrics','ScientificCurveFit',
       'HydroInterpolationGrid','MetPyWindComponents','SeismicReflectivity',
       'SeismicSegySummary','HydroReferenceET0','SpatialMoranI')
ROOT=Path(__file__).resolve().parents[1]


def source(name):
    spec=next(x for x in catalog()['tools'] if x['id']==name)
    module,method=spec['source_interface']['entrypoint']['callable'].split(':')
    return spec,getattr(importlib.import_module(module),method)


@pytest.mark.parametrize('name',NAMES)
def test_native_result_records_units_and_real_provenance(name,tmp_path):
    spec,function=source(name)
    args=deepcopy(spec['example_arguments'])
    for field in spec['source_interface']['path_fields']:
        src=ROOT/args[field]
        target=tmp_path/src.name
        target.write_bytes(src.read_bytes())
        args[field]=str(target)
    first=function(args)
    assert first==function(json.dumps(args))
    assert first==function(args=args)
    assert first['units'] and first['provenance']['tool']==name
    assert len(first['provenance']['input_sha256'])==64
    assert first['provenance']['implementation_sha256']==hashlib.sha256(Path(function.__wrapped__.__code__.co_filename).read_bytes()).hexdigest()
    assert first['provenance']['reprojection_performed'] is False
    json.dumps(first,allow_nan=False)


@pytest.mark.parametrize('name,changes,code',[
    ('GeoRegionMask',{'latitude':[91,0,0]},'invalid_arguments'),
    ('GeoVerdeGrid',{'shape':[257,256]},'invalid_arguments'),
    ('GeoVerdeGrid',{'easting':[0,1,0,0],'northing':[0,0,1,0]},'invalid_arguments'),
    ('HydroInterpolationGrid',{'resolution':1e-10},'resource_limit'),
    ('HydroErrorMetrics',{'observed':[True,2,3]},'invalid_arguments'),
    ('HydroErrorMetrics',{'observed':[float('nan'),2,3]},'invalid_arguments'),
    ('HydroErrorMetrics',{'simulated':[1,2]},'invalid_arguments'),
    ('ScientificCurveFit',{'initial':{'arbitrary_expression':1}},'invalid_arguments'),
    ('ScientificCurveFit',{'bounds':{'slope':{'min':2,'max':1}}},'invalid_arguments'),
    ('MetPyWindComponents',{'speed_unit':'kelvin'},'invalid_arguments'),
    ('MetPyWindComponents',{'direction':[400,0]},'invalid_arguments'),
    ('SpatialMoranI',{'crs':'EPSG:4326'},'invalid_arguments'),
    ('SpatialMoranI',{'crs':'not_a_crs'},'invalid_arguments'),
    ('SeismicReflectivity',{'vp':[0,2200,2200]},'invalid_arguments'),
])
def test_direct_and_runtime_reject_invalid_inputs_identically(name,changes,code,tmp_path):
    spec,function=source(name)
    args={**deepcopy(spec['example_arguments']),**changes}
    with pytest.raises(ScientificToolError) as caught: function(args)
    assert caught.value.code==code and caught.value.retryable is False
    registry,_,_=build_registry()
    context=ToolExecutionContext('intake',tmp_path,(name,),Settings(),Event())
    result=ToolExecutor(registry).execute(ToolCall('invalid',name,args),context)
    assert result.status=='error' and result.error.code==code


def test_original_algorithms_and_all_tools_remain_registered():
    registry,skills,base=build_registry()
    assert len(catalog()['tools'])==220 and len(catalog()['skills'])==47
    mapped={tool for skill in skills.registry.list() for tool in skills.load(skill.id).tool_names}
    for spec in catalog()['tools']:
        native=spec['function_definition']['function']['name']
        assert native in registry.names() and native in mapped
    assert not set(NAMES).intersection(base)


def test_unspecified_units_are_not_invented():
    _,fn=source('HydroErrorMetrics')
    args={'observed':[1,2,3],'simulated':[1,2,4],'metrics':['mae']}
    assert fn(args)['units']['rmse_mae'].startswith('unspecified')
    assert fn({**args,'series_unit':'m3/s'})['units']['rmse_mae']=='m3/s'


def test_permutation_workload_rejected_before_upstream_execution():
    _,fn=source('SpatialMoranI')
    n=256
    with pytest.raises(ScientificToolError) as caught:
        fn({'x':list(range(n)),'y':[0]*n,'values':list(range(n)),'k':2,'permutations':9999})
    assert caught.value.code=='resource_limit'


def test_segy_missing_input_has_stable_error(tmp_path):
    _,fn=source('SeismicSegySummary')
    with pytest.raises(ScientificToolError) as caught: fn({'segy_path':str(tmp_path/'absent.sgy')})
    assert caught.value.code=='missing_input' and not caught.value.retryable

import json,uuid,hashlib,shutil
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from geological_agent.team.case_catalog import CaseCatalog,safe_path
from geological_agent.team.server import create_app,COOKIE

class NoRunner:
    def stop(self,rid):pass

@pytest.fixture(scope='module')
def group(tmp_path_factory):
    app=create_app(tmp_path_factory.mktemp('library-server'),runner=NoRunner());store=app.state.store
    store.create_user('catalogtester','Temporary-Test-Password-2026',role='admin',initial_admin=True)
    token,csrf=store.login('catalogtester','Temporary-Test-Password-2026');uid=store.authenticate(token)['id']
    client=TestClient(app,base_url='http://127.0.0.1');client.cookies.set(COOKIE,token)
    return app,store,client,csrf,uid

def test_all_cases_and_preflight_have_distinct_scope(group):
    app,_,c,csrf,_=group
    report=c.post('/api/cases/preflight',headers={'x-csrf-token':csrf}).json()
    assert report['counts']['total']==44
    assert report['counts']['ready']+report['counts']['blocked']==44
    assert len(report['categories'])==10
    assert len({i['id'] for i in report['items']})==44
    assert report['counts']['prior_agent_records']==1
    for item in report['items']:
        assert item['ready']==(not item['issues'])
        assert 'not scientific or Agent acceptance' in item['checks_scope']
        assert all(k not in item for k in ['operations','input_files','truth','expected','original_replay'])
        assert app.state.case_catalog.files(app.state.case_catalog.get(item['id']))

@pytest.mark.parametrize('name',['../x','/etc/passwd','x/../../x','a\\b','C:/test',''])
def test_safe_path_rejects_escape(tmp_path,name):
    with pytest.raises(ValueError):safe_path(tmp_path,name)

def test_input_tamper_cannot_be_loaded(tmp_path):
    original=CaseCatalog();shutil.copytree(original.root,tmp_path/'library')
    lib=CaseCatalog(tmp_path/'library');item=next(i for i in lib.items.values() if i['skill']=='ore-geodesic')
    name=next(iter(item['input_files']));p=lib.root/'inputs'/item['storage']/name;p.write_bytes(b'changed')
    with pytest.raises(ValueError,match='校验失败'):lib.files(item)

def test_deferred_argument_needs_real_predecessor():
    lib=CaseCatalog();item=next(i for i in lib.items.values() if i['skill']=='ore-obspy')
    assert lib.preflight(item['id'])['ready']
    item['operations'][1]['waveform_from']='nonexistent-result'
    lib.preflight.cache_clear()
    assert '前序操作绑定未成立：nonexistent-result' in lib.preflight(item['id'])['issues']

def test_deferred_argument_does_not_hide_missing_scientific_parameter():
    lib=CaseCatalog();item=next(i for i in lib.items.values() if i['skill']=='ore-obspy')
    del item['operations'][1]['arguments']['freqmin_hz']
    lib.preflight.cache_clear()
    assert any('SeismicObsPyBandpass' in issue for issue in lib.preflight(item['id'])['issues'])

def test_generic_load_original_bytes_and_no_auto_run(group):
    app,store,c,csrf,uid=group;lib=app.state.case_catalog
    item=next(i for i in lib.items.values() if i['skill']=='ore-geodesic')
    assert lib.preflight(item['id'])['ready']
    token=uuid.uuid4().hex;kwargs={'json':{'request_id':token},'headers':{'x-csrf-token':csrf}}
    r=c.post('/api/cases/'+item['id']+'/load',**kwargs);assert r.status_code==200,r.text
    response=r.json();cid=response['conversation_id']
    assert c.post('/api/cases/'+item['id']+'/load',**kwargs).json()==response
    assert store.files(uid,cid)==lib.files(item)
    assert store.runs(uid,cid)==[]
    assert 'truth' not in response['prompt']
    info=c.get('/api/conversations/'+cid+'/case').json()
    assert info['case']==item['id'] and info['check_available'] is False
    assert c.post('/api/conversations/'+cid+'/case/check',headers={'x-csrf-token':csrf}).status_code==409
    assert c.post('/api/cases/curve-linear-v1/load',**kwargs).status_code==409

def test_blocked_load_never_creates_conversation(group):
    app,store,c,csrf,uid=group
    item=next(i for i in app.state.case_catalog.items.values() if i['skill']=='ore-morph')
    before=len(store.conversations(uid))
    r=c.post('/api/cases/'+item['id']+'/load',json={'request_id':uuid.uuid4().hex},headers={'x-csrf-token':csrf})
    assert r.status_code==409
    assert len(store.conversations(uid))==before

def test_preflight_requires_csrf_and_login(group):
    _,_,c,_,_=group
    assert TestClient(group[0],base_url='http://127.0.0.1').post('/api/cases/preflight').status_code==401
    assert c.post('/api/cases/preflight').status_code==403

def test_normalized_parameters_keep_original_numbers(group):
    lib=group[0].state.case_catalog
    for item in lib.items.values():
        files=lib.files(item)
        if item['id']=='curve-linear-v1':continue
        original=json.loads(files['request.original.json']);normalized=json.loads(files['request.json'])
        # Paths and protocol wrappers can change; no scientific scalar may change.
        def numbers(v):
            if isinstance(v,bool):return []
            if isinstance(v,(int,float)):return [v]
            if isinstance(v,list):return sum((numbers(x) for x in v),[])
            if isinstance(v,dict):return sum((numbers(x) for x in v.values()),[])
            return []
        from collections import Counter
        assert not (Counter(numbers(original))-Counter(numbers(normalized))),item['skill']

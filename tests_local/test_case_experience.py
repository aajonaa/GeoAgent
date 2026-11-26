from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from threading import Event
import uuid

import pytest
from fastapi.testclient import TestClient
from geological_agent.team import case_experience as ce
from geological_agent.team.server import create_app, COOKIE
from geological_agent.bootstrap import build_registry
from geological_agent.contracts import ToolCall
from geological_agent.tools import ToolExecutionContext, ToolExecutor
from geological_agent.settings import Settings


class NoRunner:
    def stop(self, rid): pass


@pytest.fixture(scope='module')
def group(tmp_path_factory):
    app=create_app(tmp_path_factory.mktemp('case-server'),runner=NoRunner())
    store=app.state.store
    users=[]
    for n in ['casealice','casebob']:
        store.create_user(n,'Temporary-Test-Password-2026',role='admin' if not users else 'member',
                          initial_admin=not users,invite=store.invite() if users else None)
        token,csrf=store.login(n,'Temporary-Test-Password-2026')
        client=TestClient(app,base_url='http://127.0.0.1')
        client.cookies.set(COOKIE,token)
        users.append((client,csrf,store.authenticate(token)['id']))
    return app,store,users


def load(user):
    client,csrf,_=user
    response=client.post('/api/cases/'+ce.CASE_ID+'/load',json={'request_id':uuid.uuid4().hex},headers={'x-csrf-token':csrf})
    assert response.status_code==200,response.text
    return response.json()['conversation_id']


@pytest.fixture(scope='module')
def actual(tmp_path_factory):
    _,files=ce.fixture()
    work=tmp_path_factory.mktemp('native-curve')
    for name in ['image.png','request.json']:(work/name).write_bytes(files[name])
    q=json.loads(files['request.json'])
    registry,_,_=build_registry()
    context=ToolExecutionContext('test-curve',work,('GeoPlotDigitize',),Settings(),Event())
    call=ToolCall('curve-native-1','GeoPlotDigitize',q['arguments'])
    result=ToolExecutor(registry).execute(call,context)
    assert result.status=='ok',asdict(result)
    events=[{'kind':'tool_start','id':call.id,'name':call.name,'arguments':call.arguments},
            {'kind':'tool_result','id':call.id,'name':call.name,'result':asdict(result)}]
    generated={p.relative_to(work).as_posix():p.read_bytes() for p in work.rglob('*') if p.is_file()}
    return generated,events


def test_native_actual_passes(actual):
    report=ce.compare(*actual)
    assert report['status']=='passed',[c for c in report['checks'] if not c['passed']]


@pytest.mark.parametrize('path',['image.png','request.json','out/curve.csv','out/source.png','out/overlay.png','out/reconstructed.png','out/analysis.geoanalysis.json'])
def test_tampered_or_missing_file_fails(actual,path):
    files,events=actual
    bad=dict(files);bad[path]=b'tampered'
    assert ce.compare(bad,events)['status']=='failed'


@pytest.mark.parametrize('mode',['no-receipts','wrong-parameters','failed-call','wrong-hash'])
def test_execution_binding_fails(actual,mode):
    files,events=actual;events=deepcopy(events)
    if mode=='no-receipts':events=[]
    elif mode=='wrong-parameters':events[0]['arguments']['tolerance']=1
    elif mode=='failed-call':events[1]['result']['status']='error'
    else:events[1]['result']['data']['outputs'][0]['sha256']='0'*64
    assert ce.compare(files,events)['status']=='failed'


def test_pixel_coordinates_remain_exact(actual):
    import csv,io
    files,events=actual;bad=dict(files)
    rows=list(csv.DictReader(io.StringIO(files['out/curve.csv'].decode())))
    rows[0]['pixel_row']=str(float(rows[0]['pixel_row'])+1e-12)
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    bad['out/curve.csv']=stream.getvalue().encode()
    report=ce.compare(bad,events)
    assert any(not c['passed'] and c['name'].endswith('/ pixel_row') for c in report['checks'])


def test_statistics_must_match_frozen_counts(actual):
    files,events=actual;bad=dict(files)
    manifest=json.loads(files['out/analysis.geoanalysis.json'])
    manifest['statistics']['interpolated_points']=1
    bad['out/analysis.geoanalysis.json']=json.dumps(manifest).encode()
    report=ce.compare(bad,events)
    assert any(not c['passed'] and c['name']=='点数、缺失列、歧义列及无插值统计' for c in report['checks'])


def test_auth_and_csrf(group):
    app,store,users=group
    anon=TestClient(app,base_url='http://127.0.0.1')
    assert anon.get('/api/cases').status_code==401
    assert users[0][0].post('/api/cases/'+ce.CASE_ID+'/load',json={'request_id':uuid.uuid4().hex}).status_code==403


def test_catalog_no_truth_or_prompt_answer(group):
    response=group[2][0][0].get('/api/cases');assert response.status_code==200
    items=response.json()['items']
    assert next(i for i in items if i['id']==ce.CASE_ID)['ready'] is True
    assert 'truth' not in response.text
    assert all('operations' not in item and 'input_files' not in item for item in items)
    assert 'reconstructed_points' not in response.text and 'expected_values' not in response.text


def test_load_isolated_idempotent_and_no_run(group):
    app,store,users=group;c,csrf,uid=users[0]
    token=uuid.uuid4().hex
    kwargs={'json':{'request_id':token},'headers':{'x-csrf-token':csrf}}
    a=c.post('/api/cases/'+ce.CASE_ID+'/load',**kwargs).json()
    b=c.post('/api/cases/'+ce.CASE_ID+'/load',**kwargs).json()
    assert a==b
    cid=a['conversation_id'];assert set(store.files(uid,cid))=={'image.png','request.json'}
    assert store.runs(uid,cid)==[]
    assert users[1][0].get('/api/conversations/'+cid+'/case').status_code==404
    assert c.post('/api/conversations/'+cid+'/case/check',headers={'x-csrf-token':csrf}).status_code==409


def test_unknown_case_and_bad_token(group):
    c,csrf,_=group[2][0];headers={'x-csrf-token':csrf}
    assert c.post('/api/cases/no-such-case/load',json={},headers=headers).status_code==404
    assert c.post('/api/cases/'+ce.CASE_ID+'/load',json={'request_id':'../../bad'},headers=headers).status_code==400


def test_busy_rejected(group):
    app,store,users=group;c,csrf,uid=users[0]
    app.state.jobs['fixture-busy']={'uid':uid}
    try:assert c.post('/api/cases/'+ce.CASE_ID+'/load',json={'request_id':uuid.uuid4().hex},headers={'x-csrf-token':csrf}).status_code==409
    finally:app.state.jobs.clear()


def test_finished_run_check_and_stale_invalidation(group,actual):
    app,store,users=group;c,csrf,uid=users[0];cid=load(users[0]);files,events=actual
    rid=store.begin(uid,cid,'case test')
    for event in events:store.event(rid,event)
    generation=store.snapshot(uid,cid,files)
    store.finish(rid,status='completed',generation=generation)
    endpoint='/api/conversations/'+cid+'/case'
    assert c.post(endpoint+'/check',headers={'x-csrf-token':csrf}).json()['status']=='passed'
    assert c.get(endpoint).json()['report']['run_id']==rid
    store.snapshot(uid,cid,{**files,'edited.txt':b'x'})
    assert c.get(endpoint).json()['report'] is None
    assert c.post(endpoint+'/check',headers={'x-csrf-token':csrf}).status_code==409


def test_failed_run_not_passed(group):
    _,store,users=group;c,csrf,uid=users[0];cid=load(users[0])
    rid=store.begin(uid,cid,'failure');store.finish(rid,status='failed')
    assert c.post('/api/conversations/'+cid+'/case/check',headers={'x-csrf-token':csrf}).status_code==409


def test_snapshot_error_rolls_back_new_case(group,monkeypatch):
    _,store,users=group;c,csrf,uid=users[0]
    before=len(store.conversations(uid))
    def fail(*a,**kw):raise ValueError('storage quota test')
    monkeypatch.setattr(store,'snapshot',fail)
    response=c.post('/api/cases/'+ce.CASE_ID+'/load',json={'request_id':uuid.uuid4().hex},headers={'x-csrf-token':csrf})
    assert response.status_code==400
    assert len(store.conversations(uid))==before


def test_post_snapshot_error_removes_generation_audit(group,monkeypatch):
    _,store,users=group;c,csrf,uid=users[0]
    before=len(store.conversations(uid));audit_before=store.db.execute('SELECT count(*) FROM generation_audit').fetchone()[0]
    original=store.snapshot
    def fail_after(*args,**kwargs):
        original(*args,**kwargs)
        raise ValueError('post-snapshot failure test')
    monkeypatch.setattr(store,'snapshot',fail_after)
    response=c.post('/api/cases/'+ce.CASE_ID+'/load',json={'request_id':uuid.uuid4().hex},headers={'x-csrf-token':csrf})
    assert response.status_code==400
    assert len(store.conversations(uid))==before
    assert store.db.execute('SELECT count(*) FROM generation_audit').fetchone()[0]==audit_before


def test_truth_not_served(group):
    c=group[2][0][0]
    assert c.get('/case-assets/truth.json').status_code==404
    assert c.get('/assets/truth.json').status_code==404

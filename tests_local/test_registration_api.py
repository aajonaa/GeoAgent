from contextlib import closing
from dataclasses import replace
from pathlib import Path
import json,os,secrets,sqlite3,time

import pytest
from fastapi.testclient import TestClient
from geological_agent.team import migrations as m
from geological_agent.team.server import COOKIE,create_app
from geological_agent.team.verification_service import VerificationService
from geological_agent.team.verification_policy import Settings,KeyRing
from geological_agent.team.sms_provider import MockProvider
from geological_agent.team.registration_service import RegistrationPolicy

PASSWORD='Synthetic-API-Registration-Password-2026'
PHONE='+8613800138000'

class Clock:
    def __init__(self):self.now=time.time()
    def __call__(self):return self.now

@pytest.fixture
def api(tmp_path):
    root=tmp_path/'api';root.mkdir()
    with closing(sqlite3.connect(root/'team.sqlite3',isolation_level=None)) as c:
        c.execute('PRAGMA foreign_keys=ON');m.migrate(c)
    provider=MockProvider();keys=KeyRing('test',{'test':secrets.token_bytes(32)});clock=Clock()
    class Runner:
        def stop(self,rid):pass
    def factory(store):return VerificationService(store,settings=Settings(mode='mock',environment='test',default_region='CN',edge_limit=100),keys=keys,provider=provider,clock=clock)
    app=create_app(root,runner=Runner(),verification_factory=factory,registration_policy=RegistrationPolicy(mode='invite_sms',environment='test'))
    token=app.state.store.invite()
    with TestClient(app,base_url='http://127.0.0.1') as client:
        sent=client.post('/api/auth/sms/send',json={'invite':token,'phone':PHONE,'request_id':secrets.token_hex(16)})
        assert sent.status_code==202
        vid=sent.json()['verification_id'];code=provider.captured_for_test(vid)[1]
        data={'invite':token,'phone':PHONE,'username':'api-registered','password':PASSWORD,'organization':'Test Organization',
              'verification_id':vid,'code':code,'request_id':secrets.token_hex(16)}
        yield client,app,data,provider,root
    app.state.store.db.close()

def write(name,data):
    if os.environ.get('P22_EVIDENCE'):(Path(os.environ['P22_EVIDENCE'])/name).write_text(json.dumps(data,indent=2))

def test_T09_T36_T40_complete_mock_registration_and_auto_login(api):
    client,app,data,provider,root=api;s=app.state.store;observed=[];original=s.login
    with closing(sqlite3.connect((root/'team.sqlite3').as_uri()+'?mode=ro',uri=True,check_same_thread=False)) as outside:
        def login(username,password):
            assert not s.db.in_transaction
            assert outside.execute('SELECT count(*) FROM users').fetchone()[0]==1
            assert outside.execute("SELECT count(*) FROM business_events WHERE kind='registration_completed'").fetchone()[0]==1
            observed.append(True);return original(username,password)
        s.login=login
        response=client.post('/api/register',json=data)
    assert response.status_code==201 and response.json()['authenticated']
    body=response.json();assert body['user']['role']=='member' and observed
    assert client.cookies.get(COOKIE) and 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=strict' in response.headers['set-cookie']
    assert 'Max-Age=43200' in response.headers['set-cookie'] and response.headers['cache-control']=='no-store'
    me=client.get('/api/me');assert me.status_code==200 and me.json()['id']==body['user']['id']
    client.headers['x-csrf-token']=body['csrf']
    assert client.post('/api/admin/invites').status_code==403
    assert not any(k in body for k in ('password','password_hash','code','code_digest','phone','invite','token'))
    assert provider.call_count_for_test()==1
    counts={t:s.db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('users','user_profiles','invite_uses','business_events','auth')}
    assert all(n==1 for n in counts.values())
    write('api-registration-validation.json',{'registration_http':response.status_code,'authenticated':body['authenticated'],'ordinary_member':True,
      'me_user_matches_registration':True,'login_called_after_independent_connection_sees_commit':True,
      'counts':counts,'cookie_http_only':True,'cookie_same_site':'strict','csrf_compatible':True,
      'public_response_secret_fields':False,'mock_send_calls':provider.call_count_for_test(),'real_sms_calls':0})

def test_T10_real_session_insert_failure_keeps_account_loginable(api):
    client,app,data,provider,root=api;c=app.state.store.db
    def authorizer(operation,arg1,arg2,db,trigger):
        if operation==sqlite3.SQLITE_INSERT and arg1=='auth':return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    c.set_authorizer(authorizer)
    try:response=client.post('/api/register',json=data)
    finally:c.set_authorizer(None)
    assert response.status_code==201 and response.json()=={'ok':True,'registered':True,'authenticated':False,'next':'login'}
    assert not client.cookies and c.execute('SELECT count(*) FROM auth').fetchone()[0]==0
    assert c.execute('SELECT count(*) FROM users').fetchone()[0]==1
    login=client.post('/api/login',json={'username':data['username'],'password':PASSWORD})
    assert login.status_code==200 and client.get('/api/me').status_code==200

def test_committed_response_failure_and_repeat_are_safe(api,monkeypatch):
    client,app,data,provider,root=api
    import geological_agent.team.registration_api as module
    original=module.registration_response
    def fail(*a,**k):raise RuntimeError('controlled response construction failure')
    monkeypatch.setattr(module,'registration_response',fail)
    failed=client.post('/api/register',json=data)
    assert failed.status_code==503 and 'set-cookie' not in failed.headers
    assert app.state.store.db.execute('SELECT count(*) FROM users').fetchone()[0]==1
    monkeypatch.setattr(module,'registration_response',original)
    retried=client.post('/api/register',json=data)
    assert retried.status_code==200 and retried.json()['authenticated']
    for table in ('users','user_profiles','invite_uses','business_events'):
        assert app.state.store.db.execute('SELECT count(*) FROM '+table).fetchone()[0]==1

def test_T38_failed_commit_never_calls_login_or_sets_cookie(api):
    client,app,data,provider,root=api;c=app.state.store.db;called=[];denied=[]
    def login(*args):called.append(True);raise AssertionError('login must not run')
    app.state.store.login=login
    def authorizer(operation,arg1,arg2,db,trigger):
        if operation==sqlite3.SQLITE_TRANSACTION and arg1=='COMMIT' and not denied:
            denied.append(True);return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    c.set_authorizer(authorizer)
    try:response=client.post('/api/register',json=data)
    finally:c.set_authorizer(None)
    assert response.status_code==503 and denied and not called and not client.cookies
    for table in ('users','user_profiles','invite_uses','business_events','auth'):assert c.execute('SELECT count(*) FROM '+table).fetchone()[0]==0
    assert c.execute('SELECT used FROM invites').fetchone()[0]==0
    assert c.execute('SELECT consumed_at FROM sms_verifications').fetchone()[0] is None

@pytest.mark.parametrize('change',[{'role':'admin'},{'password':'short'},{'organization':' '},{'phone':'invalid'},{'code':'bad'},{'request_id':'x'},{'username':'bad name'},{'unknown':'extra'}])
def test_T45_T46_invalid_requests_do_not_create_or_leak(api,change,caplog):
    client,app,data,provider,root=api
    response=client.post('/api/register',json={**data,**change})
    assert response.status_code==400 and not client.cookies
    for value in (data['password'],data['code'],data['phone'],data['invite']):assert value not in response.text and value not in caplog.text
    assert app.state.store.db.execute('SELECT count(*) FROM users').fetchone()[0]==0

def test_T43_T44_no_public_legacy_or_alternate_bypass(api):
    client,app,data,provider,root=api
    old={k:data[k] for k in ('username','password','invite')}
    assert client.post('/api/register',json=old).status_code==400
    for path in ('/api/auth/register','/api/users','/api/signup','/api/admin/users'):
        assert client.post(path,json=data).status_code==404
    assert client.get('/api/register').status_code==405
    routes=[route.path for route in app.routes if getattr(route,'endpoint',None) and getattr(route.endpoint,'__name__','')=='register']
    assert routes==['/api/register'] and app.state.store.db.execute('SELECT count(*) FROM users').fetchone()[0]==0

def test_T51_T52_fail_closed_policy_and_missing_provider(api):
    client,app,data,provider,root=api;reg=app.state.registration_service
    reg.policy=RegistrationPolicy()
    assert client.post('/api/register',json=data).status_code==403
    reg.policy=RegistrationPolicy(mode='invite_sms',environment='production')
    assert client.post('/api/register',json=data).status_code==503
    reg.policy=RegistrationPolicy(mode='invite_sms',environment='test');reg.verification=None
    assert client.post('/api/register',json=data).status_code==503
    assert app.state.store.db.execute('SELECT count(*) FROM users').fetchone()[0]==0

def test_T39_new_user_scope_and_existing_models_remain_isolated(api):
    client,app,data,provider,root=api;s=app.state.store
    old=s.create_user('existing-admin',PASSWORD,role='admin',initial_admin=True)
    private=s.create_conversation(old)
    s.snapshot(old,private['id'],{'secret.txt':b'synthetic private'})
    old_token,_=s.login('existing-admin',PASSWORD)
    client.cookies.set(COOKIE,old_token,domain='127.0.0.1',path='/')
    vault=app.state.model_settings.vault
    vault.put(old,{'format':'connections-v1','active_id':None,'items':[],'private_fixture':'old-user-only'})
    encrypted_before=bytes(s.db.execute('SELECT ciphertext FROM model_profiles WHERE uid=?',(old,)).fetchone()[0])
    response=client.post('/api/register',json=data);assert response.status_code==201
    assert client.cookies.get(COOKIE)!=old_token and client.get('/api/me').json()['role']=='member'
    client.headers['x-csrf-token']=response.json()['csrf']
    for path in [f"/api/conversations/{private['id']}",f"/api/conversations/{private['id']}/download?name=secret.txt"]:
        assert client.get(path).status_code==404
    assert client.get('/api/model-settings').status_code==200
    new_uid=response.json()['user']['id']
    assert vault.get(new_uid) is None and vault.get(old)['private_fixture']=='old-user-only'
    assert bytes(s.db.execute('SELECT ciphertext FROM model_profiles WHERE uid=?',(old,)).fetchone()[0])==encrypted_before
    assert s.authenticate(old_token)['id']==old
    assert client.post('/api/admin/invites').status_code==403

def test_replay_with_wrong_password_never_logs_in_or_changes_password(api):
    client,app,data,provider,root=api
    assert client.post('/api/register',json=data).status_code==201
    client.cookies.clear()
    retry=client.post('/api/register',json={**data,'password':'Another-Synthetic-Password-2026'})
    assert retry.status_code==200 and retry.json()['authenticated'] is False and not client.cookies
    assert app.state.store.db.execute('SELECT count(*) FROM users').fetchone()[0]==1
    assert client.post('/api/login',json={'username':data['username'],'password':PASSWORD}).status_code==200

def test_T50_body_limits_and_rate_limits(api):
    client,app,data,provider,root=api
    assert client.post('/api/register',content=b'x'*5000,headers={'content-type':'application/json'}).status_code==413
    app.state.verification_service.settings=replace(app.state.verification_service.settings,edge_limit=1)
    assert client.post('/api/register',json=data).status_code==429
    assert not client.cookies

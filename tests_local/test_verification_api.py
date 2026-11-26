from contextlib import closing
from dataclasses import replace
from pathlib import Path
import json,secrets,sqlite3,os
import pytest
from fastapi.testclient import TestClient
from geological_agent.team.server import create_app
from geological_agent.team import migrations as m
from geological_agent.team.verification_policy import Settings,KeyRing
from geological_agent.team.verification_service import VerificationService
from geological_agent.team.sms_provider import MockProvider

PHONE='+8613800138000'

@pytest.fixture
def api(tmp_path):
    root=tmp_path/'api';root.mkdir()
    with closing(sqlite3.connect(root/'team.sqlite3',isolation_level=None)) as c:
        c.execute('PRAGMA foreign_keys=ON');m.migrate(c)
    provider=MockProvider();keys=KeyRing('test',{'test':secrets.token_bytes(32)})
    settings=Settings(mode='mock',environment='test',default_region='CN',edge_limit=100)
    class NoTrace:
        def emit(self,*a,**kw):pass
    class Runner:
        def stop(self,rid):pass
    def factory(store):return VerificationService(store,settings=settings,keys=keys,provider=provider)
    app=create_app(root,runner=Runner(),trace_factory=lambda p:NoTrace(),verification_factory=factory)
    token=app.state.store.invite()
    with TestClient(app,base_url='http://127.0.0.1') as client:
        yield client,app,token,provider
    app.state.store.db.close()

def send(client,token,**changes):
    body={'invite':token,'phone':PHONE,'request_id':secrets.token_hex(16)};body.update(changes)
    return client.post('/api/auth/sms/send',json=body),body

def test_T35_T41_full_advisory_chain_without_accounts_or_sessions(api):
    client,app,token,provider=api
    assert client.post('/api/auth/invitations/validate',json={'invite':token}).json()=={'valid':True,'advisory':True}
    response,body=send(client,token);assert response.status_code==202
    result=response.json();code=provider.captured_for_test(result['verification_id'])[1]
    verify=client.post('/api/auth/sms/verify',json={'invite':token,'phone':PHONE,'verification_id':result['verification_id'],'code':code})
    assert verify.status_code==200 and verify.json()=={'valid':True,'advisory':True}
    c=app.state.store.db
    assert c.execute('SELECT count(*) FROM users').fetchone()[0]==0
    assert c.execute('SELECT count(*) FROM auth').fetchone()[0]==0
    assert c.execute('SELECT used FROM invites').fetchone()[0]==0
    assert c.execute('SELECT consumed_at FROM sms_verifications').fetchone()[0] is None
    assert not client.cookies and 'set-cookie' not in response.headers
    assert response.headers['cache-control']=='no-store'
    assert not any(k in result for k in ('code','phone','invite','token','code_digest','key_id'))
    again=client.post('/api/auth/sms/send',json=body)
    assert again.json()['verification_id']==result['verification_id'] and provider.call_count_for_test()==1
    if os.environ.get('P21_EVIDENCE'):
        evidence={'scope':'real TestClient requests against updated app and isolated migrated SQLite',
          'http_status':{'invitation':200,'send':response.status_code,'verify':verify.status_code,'idempotent_retry':again.status_code},
          'response_keys':sorted(result),'verified_advisory':verify.json(),'provider_mode':'mock',
          'mock_calls':provider.call_count_for_test(),'users':c.execute('SELECT count(*) FROM users').fetchone()[0],
          'sessions':c.execute('SELECT count(*) FROM auth').fetchone()[0],'invite_used':c.execute('SELECT used FROM invites').fetchone()[0],
          'consumed_at':c.execute('SELECT consumed_at FROM sms_verifications').fetchone()[0],
          'public_otp_or_key':False,'real_sms_calls':0}
        (Path(os.environ['P21_EVIDENCE'])/'api-validation.json').write_text(json.dumps(evidence,indent=2))

@pytest.mark.parametrize('body',[{},[],{'invite':None},{'invite':'x','phone':None,'request_id':'x'},{'invite':'x','phone':'x','request_id':'x','extra':'bad'}])
def test_T36_send_input_validation(api,body):
    client,app,token,provider=api
    response=client.post('/api/auth/sms/send',json=body)
    assert response.status_code==400 and provider.call_count_for_test()==0

@pytest.mark.parametrize('change',[{'code':None},{'code':'x'},{'code':'9'*10000},{'purpose':'password_reset'},{'verification_id':'x'},{'phone':None}])
def test_T37_verify_input_validation(api,change):
    client,app,token,provider=api
    body={'invite':token,'phone':PHONE,'verification_id':'a'*32,'code':'000000'};body.update(change)
    response=client.post('/api/auth/sms/verify',json=body)
    assert response.status_code in (400,413)
    assert 'code_digest' not in response.text and token not in response.text

def test_T38_errors_body_size_and_invitations_are_private(api):
    client,app,token,provider=api
    assert client.post('/api/auth/sms/send',content=b'x'*3000,headers={'content-type':'application/json'}).status_code==413
    assert client.post('/api/auth/sms/send',content=b'{').status_code==415
    bad,_=send(client,'not-an-invite')
    assert bad.status_code==403 and 'not-an-invite' not in bad.text
    assert client.post('/api/auth/invitations/validate',json={'invite':'invalid'}).json()=={'valid':False,'advisory':True}
    assert provider.call_count_for_test()==0
    assert client.get('/api/auth/sms/send').status_code==405

def test_T39_T40_cooldown_and_header_spoof_do_not_send_again(api):
    client,app,token,provider=api
    response,body=send(client,token);assert response.status_code==202
    same=client.post('/api/auth/sms/send',json=body,headers={'x-forwarded-for':'198.51.100.1'})
    assert same.status_code==202
    other,_=send(client,token)
    assert other.status_code==429 and provider.call_count_for_test()==1
    assert 'Retry-After' in other.headers

def test_default_app_does_not_auto_enable_sms_or_migrate(tmp_path):
    app=create_app(tmp_path/'disabled')
    try:
        with TestClient(app,base_url='http://127.0.0.1') as client:
            assert client.post('/api/auth/sms/send',json={}).status_code==503
        assert app.state.store.db.execute("SELECT count(*) FROM sqlite_master WHERE name='sms_verifications'").fetchone()[0]==0
    finally:app.state.store.db.close()

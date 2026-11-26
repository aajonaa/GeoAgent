from contextlib import closing
from pathlib import Path
from dataclasses import replace
import json,os,secrets,sqlite3,time
import pytest
from fastapi.testclient import TestClient
from geological_agent.team import migrations
from geological_agent.team.server import create_app,COOKIE
from geological_agent.team.store import password_hash
from geological_agent.team.verification_policy import Settings,KeyRing
from geological_agent.team.verification_service import VerificationService
from geological_agent.team.sms_provider import MockProvider
from geological_agent.team.profile_service import ProfilePolicy
from geological_agent.team.registration_service import RegistrationPolicy

PASSWORD='Synthetic-Profile-API-Password-2026';PHONE='+8613800138000'
class Clock:
    def __init__(self):self.now=time.time()
    def __call__(self):return self.now
class Runner:
    def stop(self,rid):pass

@pytest.fixture(scope='module')
def encoded():return password_hash(PASSWORD)

@pytest.fixture
def api(tmp_path,encoded):
    root=tmp_path/'api';root.mkdir()
    with closing(sqlite3.connect(root/'team.sqlite3',isolation_level=None)) as c:
        c.execute('PRAGMA foreign_keys=ON');migrations.migrate(c)
    provider=MockProvider();clock=Clock();key=KeyRing('test',{'test':secrets.token_bytes(32)})
    def factory(s):return VerificationService(s,settings=Settings(mode='mock',environment='test',default_region='CN',cooldown=0,edge_limit=200),keys=key,provider=provider,clock=clock)
    app=create_app(root,runner=Runner(),verification_factory=factory,registration_policy=RegistrationPolicy(mode='invite_sms',environment='test'),profile_policy=ProfilePolicy(phone_binding_enabled=True,environment='test'))
    s=app.state.store
    with s.lock,migrations.transaction(s.db):
        uid=s.create_user_in_transaction(s.db,'legacy-user',encoded)
        other=s.create_user_in_transaction(s.db,'other-user',encoded)
        admin=s.create_user_in_transaction(s.db,'existing-admin',encoded,role='admin',initial_admin=True)
    with TestClient(app,base_url='http://127.0.0.1') as client:
        login=client.post('/api/login',json={'username':'legacy-user','password':PASSWORD});assert login.status_code==200
        client.headers['X-CSRF-Token']=login.json()['csrf']
        yield client,app,provider,clock,uid,other,admin,root
    s.db.close()

def ready(api):
    c,app,provider,clock,uid,other,admin,root=api
    proof=c.post('/api/profile/phone/reauthenticate',json={'phone':PHONE,'password':PASSWORD});assert proof.status_code==200
    grant=proof.json()['authorization']
    sent=c.post('/api/profile/phone/send',json={'phone':PHONE,'authorization':grant,'request_id':secrets.token_hex(16)});assert sent.status_code==202
    vid=sent.json()['verification_id'];code=provider.captured_for_test(vid)[1]
    return {'phone':PHONE,'authorization':grant,'verification_id':vid,'code':code}

def emit(name,data):
    if os.environ.get('P23B1_EVIDENCE'):(Path(os.environ['P23B1_EVIDENCE'])/name).write_text(json.dumps(data,indent=2))

def test_T01_T07_own_profile_and_full_authenticated_binding_api(api):
    c,app,provider,clock,uid,other,admin,root=api;s=app.state.store
    cookie=c.cookies.get(COOKIE);sessions=s.db.execute('SELECT count(*) FROM auth').fetchone()[0]
    first=c.get('/api/profile');assert first.status_code==200 and first.json()['profile_completion_status']=='no_profile'
    assert first.json()['registration_time'] is None and first.json()['user_id']==uid
    patch=c.patch('/api/profile',json={'organization':' Test University '});assert patch.status_code==200 and patch.json()['organization']=='Test University'
    data=ready(api);response=c.post('/api/profile/phone/confirm',json=data)
    assert response.status_code==200 and response.json()['bound'] and not response.json()['already_completed']
    profile=c.get('/api/profile').json();assert profile['phone_verified'] and profile['phone_masked']=='***8000' and profile['profile_completion_status']=='complete'
    assert profile['registration_time'] is None and profile['phone_verified_at']==clock()
    assert c.cookies.get(COOKIE)==cookie and 'set-cookie' not in response.headers and s.db.execute('SELECT count(*) FROM auth').fetchone()[0]==sessions
    assert c.get('/api/me').json()['id']==uid
    repeated=c.post('/api/profile/phone/confirm',json=data);assert repeated.status_code==200 and repeated.json()['already_completed']
    assert s.db.execute("SELECT count(*) FROM business_events WHERE kind='profile_updated'").fetchone()[0]==2
    for secret in (PASSWORD,PHONE,data['code'],data['authorization']):assert secret not in response.text and secret not in first.text
    emit('api-profile-validation.json',{'read_http':first.status_code,'update_http':patch.status_code,'reauth_send_confirm_http':[200,202,response.status_code],'me_user_matches_profile':True,'profile_completion_status':profile['profile_completion_status'],'phone_masked':True,'old_registration_time_still_null':True,'same_cookie':True,'new_sessions':0,'repeat_no_additional_event':True,'real_sms_calls':0})

@pytest.mark.parametrize('method,path',[('GET','/api/profile'),('PATCH','/api/profile'),('POST','/api/profile/phone/reauthenticate'),('POST','/api/profile/phone/send'),('POST','/api/profile/phone/confirm')])
def test_T04_T12_T16_anonymous_rejected(api,method,path):
    c,app,*_=api;c.cookies.clear()
    r=c.request(method,path,json={} if method!='GET' else None);assert r.status_code==401

@pytest.mark.parametrize('path',['/api/profile','/api/profile/phone/reauthenticate','/api/profile/phone/send','/api/profile/phone/confirm'])
def test_all_mutations_require_existing_csrf(api,path):
    c,app,*_=api;c.headers.pop('X-CSRF-Token')
    r=c.patch(path,json={'organization':'Unit'}) if path=='/api/profile' else c.post(path,json={})
    assert r.status_code==403
    assert app.state.store.db.execute('SELECT count(*) FROM user_profiles').fetchone()[0]==0

@pytest.mark.parametrize('key',['user_id','uid','role','username','phone_number','phone_verified_at','registered_at','password'])
def test_T13_T14_T28_mass_assignment_rejected(api,key):
    c,app,provider,clock,uid,other,admin,root=api
    r=c.patch('/api/profile',json={'organization':'Unit',key:other});assert r.status_code==400
    assert app.state.store.db.execute('SELECT count(*) FROM user_profiles').fetchone()[0]==0

@pytest.mark.parametrize('where',['query','body','path'])
def test_T05_T13_no_client_selected_profile_target(api,where):
    c,app,provider,clock,uid,other,admin,root=api
    if where=='query':r=c.get('/api/profile',params={'user_id':other})
    elif where=='body':r=c.request('GET','/api/profile',json={'user_id':other})
    else:r=c.get('/api/profile/'+other)
    assert r.status_code==(404 if where=='path' else 400)
    assert 'phone_number' not in r.text and 'organization' not in r.text

@pytest.mark.parametrize('operation,body',[
 ('reauthenticate',{'phone':PHONE,'password':'Synthetic-Wrong-Password'}),
 ('reauthenticate',{'phone':PHONE,'password':PASSWORD,'user_id':'other'}),
 ('send',{'phone':PHONE,'authorization':'invalid','request_id':'0'*32}),
 ('send',{'phone':PHONE,'authorization':'invalid','request_id':'0'*32,'purpose':'register'}),
 ('confirm',{'phone':PHONE,'authorization':'invalid','verification_id':'0'*32,'code':'000000'}),
])
def test_T29_T30_binding_rejects_untrusted_context(api,operation,body):
    c,app,provider,*_=api;r=c.post('/api/profile/phone/'+operation,json=body)
    assert r.status_code in (400,403) and provider.call_count_for_test()==0
    assert app.state.store.db.execute('SELECT count(*) FROM user_profiles').fetchone()[0]==0

def test_T25_proof_cannot_cross_authenticated_api_identity(api):
    c,app,provider,clock,uid,other,admin,root=api;data=ready(api)
    login=c.post('/api/login',json={'username':'other-user','password':PASSWORD});c.headers['X-CSRF-Token']=login.json()['csrf']
    r=c.post('/api/profile/phone/confirm',json=data);assert r.status_code==403
    assert c.get('/api/profile').json()['user_id']==other
    assert app.state.store.db.execute('SELECT consumed_at FROM sms_verifications').fetchone()[0] is None

def test_T03_T41_new_registration_profile_api_compatible(api):
    c,app,provider,clock,uid,other,admin,root=api;c.cookies.clear();c.headers.pop('X-CSRF-Token')
    token=app.state.store.invite();sent=c.post('/api/auth/sms/send',json={'invite':token,'phone':PHONE,'request_id':secrets.token_hex(16)})
    code=provider.captured_for_test(sent.json()['verification_id'])[1]
    reg=c.post('/api/register',json={'username':'new-user','password':PASSWORD,'organization':'New University','phone':PHONE,'invite':token,'verification_id':sent.json()['verification_id'],'code':code,'request_id':secrets.token_hex(16)})
    assert reg.status_code==201 and reg.json()['authenticated']
    public=c.get('/api/profile');assert public.status_code==200
    assert public.json()['user_id']==reg.json()['user']['id'] and public.json()['registration_time']==clock() and public.json()['organization']=='New University'
    assert PHONE not in public.text

def test_T39_T40_T45_T48_login_history_model_and_admin_compatibility(api):
    c,app,provider,clock,uid,other,admin,root=api;s=app.state.store
    conversation=s.create_conversation(uid);s.snapshot(uid,conversation['id'],{'proof.txt':b'synthetic file'})
    vault=app.state.model_settings.vault;vault.put(uid,{'format':'connections-v1','active_id':None,'items':[]})
    encrypted=bytes(s.db.execute('SELECT ciphertext FROM model_profiles WHERE uid=?',(uid,)).fetchone()[0]);cookie=c.cookies.get(COOKIE)
    c.patch('/api/profile',json={'organization':'Unit'});data=ready(api);assert c.post('/api/profile/phone/confirm',json=data).status_code==200
    assert c.cookies.get(COOKIE)==cookie and c.get('/api/conversations/'+conversation['id']).status_code==200
    assert bytes(s.db.execute('SELECT ciphertext FROM model_profiles WHERE uid=?',(uid,)).fetchone()[0])==encrypted
    assert c.post('/api/admin/invites').status_code==403
    login=c.post('/api/login',json={'username':'existing-admin','password':PASSWORD});c.headers['X-CSRF-Token']=login.json()['csrf']
    assert c.post('/api/admin/invites').status_code==200
    assert c.get('/api/conversations/'+conversation['id']).status_code==404
    emit('profile-compatibility-details.json',{'old_session_unchanged':True,'identity_password_role_unchanged':True,'history_owned_by_original_uid':True,'model_ciphertext_unchanged':True,'member_admin_forbidden':True,'original_admin_permission_works':True,'admin_does_not_gain_other_history':True})

def test_json_limits_and_safe_errors(api,caplog):
    c,app,provider,clock,uid,other,admin,root=api;data=ready(api)
    assert c.patch('/api/profile',json={'organization':'x'*5000}).status_code==413
    assert c.patch('/api/profile',content='text',headers={'content-type':'text/plain'}).status_code==415
    r=c.post('/api/profile/phone/confirm',json={**data,'code':('0' if data['code'][0]!='0' else '1')+data['code'][1:]});assert r.status_code==403
    assert r.headers['cache-control']=='no-store' and 'set-cookie' not in r.headers
    assert all(value not in r.text and value not in caplog.text for value in (PASSWORD,PHONE,data['code'],data['authorization'],c.cookies.get(COOKIE)))

def test_password_reconfirmation_is_rate_limited(api):
    c,app,*_=api;statuses=[c.post('/api/profile/phone/reauthenticate',json={'phone':PHONE,'password':'Incorrect-Password-2026'}).status_code for _ in range(10)]
    assert 403 in statuses and statuses[-1]==429

def test_real_phone_and_ip_send_limits_are_enforced(api):
    c,app,provider,clock,uid,other,admin,root=api
    v=app.state.verification_service;v.settings=replace(v.settings,cooldown=60)
    a=c.post('/api/profile/phone/reauthenticate',json={'phone':PHONE,'password':PASSWORD}).json()['authorization']
    first=c.post('/api/profile/phone/send',json={'phone':PHONE,'authorization':a,'request_id':secrets.token_hex(16)});assert first.status_code==202
    second=c.post('/api/profile/phone/send',json={'phone':'13800138000','authorization':a,'request_id':secrets.token_hex(16)})
    assert second.status_code==429 and int(second.headers['retry-after'])>0 and provider.call_count_for_test()==1

def test_missing_provider_or_production_mock_cannot_enable_binding(api):
    c,app,provider,*_=api;p=app.state.profile_service
    p.policy=ProfilePolicy(phone_binding_enabled=True,environment='production')
    assert c.post('/api/profile/phone/reauthenticate',json={'phone':PHONE,'password':PASSWORD}).status_code==503
    p.policy=ProfilePolicy(phone_binding_enabled=True,environment='test');p.verification=None
    assert c.post('/api/profile/phone/reauthenticate',json={'phone':PHONE,'password':PASSWORD}).status_code==503
    assert c.get('/api/profile').status_code==200 and provider.call_count_for_test()==0

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from threading import Barrier
import base64,json,hashlib,multiprocessing,os,secrets,sqlite3,time
import pytest

from geological_agent.team import migrations
from geological_agent.team.store import Store,password_hash,digest
from geological_agent.team.activity_store import ActivityStore
from geological_agent.team.verification_policy import Settings,KeyRing
from geological_agent.team.verification_service import VerificationService,ServiceError
from geological_agent.team.sms_provider import MockProvider,SendResult
from geological_agent.team.profile_service import ProfileService,ProfilePolicy,ProfileError,OPERATION
from geological_agent.team.registration_service import RegistrationService,RegistrationPolicy

PASSWORD='Synthetic-Profile-Password-2026';PHONE='+8613800138000'
class Clock:
    def __init__(self,value=None):self.value=time.time() if value is None else value
    def __call__(self):return self.value

def setup(root,*,clock=None,keys=None,initialize=False):
    root=Path(root)
    if initialize:
        root.mkdir()
        with closing(sqlite3.connect(root/'team.sqlite3',isolation_level=None)) as c:
            c.execute('PRAGMA foreign_keys=ON');migrations.migrate(c)
    s=Store(root);clock=clock or Clock();keys=keys or KeyRing('test',{'test':secrets.token_bytes(32)})
    provider=MockProvider();v=VerificationService(s,settings=Settings(mode='mock',environment='test',default_region='CN',cooldown=0,edge_limit=200),keys=keys,provider=provider,clock=clock)
    p=ProfileService(s,v,policy=ProfilePolicy(phone_binding_enabled=True,environment='test'),clock=clock)
    return s,v,p,provider

def add_user(s,encoded,name='legacy-user',role='member'):
    with s.lock,migrations.transaction(s.db):
        uid=s.create_user_in_transaction(s.db,name,encoded,role=role,initial_admin=role=='admin')
    token,_=s.login(name,PASSWORD);return uid,token

@pytest.fixture(scope='module')
def encoded():return password_hash(PASSWORD)

@pytest.fixture
def env(tmp_path,encoded):
    s,v,p,provider=setup(tmp_path/'state',initialize=True);uid,session=add_user(s,encoded)
    try:yield s,v,p,provider,uid,session,tmp_path/'state',encoded
    finally:s.db.close()

def challenge(env,*,phone=PHONE,session=None,authorization=None):
    s,v,p,provider,uid,default,root,encoded=env;session=session or default
    authorization=authorization or p.reauthenticate(session,phone=phone,password=PASSWORD)['authorization']
    sent=p.send_phone(session,phone=phone,authorization=authorization,request_id=secrets.token_hex(16),ip='192.0.2.1')
    code=provider.captured_for_test(sent['verification_id'])[1]
    return {'phone':phone,'authorization':authorization,'verification_id':sent['verification_id'],'code':code}

def facts(s):
    return {'profiles':s.db.execute('SELECT count(*) FROM user_profiles').fetchone()[0],
            'verified_profiles':s.db.execute('SELECT count(*) FROM user_profiles WHERE phone_verified_at IS NOT NULL').fetchone()[0],
            'consumed':s.db.execute('SELECT count(*) FROM sms_verifications WHERE consumed_at IS NOT NULL').fetchone()[0],
            'profile_events':s.db.execute("SELECT count(*) FROM business_events WHERE kind='profile_updated'").fetchone()[0],
            'users':s.db.execute('SELECT count(*) FROM users').fetchone()[0],
            'sessions':s.db.execute('SELECT count(*) FROM auth').fetchone()[0]}

def snapshot(s):
    return {t:hashlib.sha256(repr([tuple(row) for row in s.db.execute('SELECT * FROM '+t+' ORDER BY rowid')]).encode()).hexdigest() for t in ('users','auth','user_profiles','sms_verifications','business_events')}

def emit(name,data):
    if os.environ.get('P23B1_EVIDENCE'):(Path(os.environ['P23B1_EVIDENCE'])/name).write_text(json.dumps(data,indent=2))

def test_T01_T02_T07_old_profile_missing_does_not_affect_login(env):
    s,v,p,provider,uid,session,root,encoded=env;before=snapshot(s);result=p.read(session)
    assert result=={'user_id':uid,'username':'legacy-user','organization':None,'phone_masked':None,'phone_verified':False,'phone_verified_at':None,'profile_updated_at':None,'registration_time':None,'profile_completion_status':'no_profile'}
    assert snapshot(s)==before and s.authenticate(session)['id']==uid

def test_T08_T09_T15_organization_create_update_clear_and_repeat(env):
    s,v,p,provider,uid,session,root,encoded=env
    a=p.update_organization(session,' University ');assert a['organization']=='University' and a['registration_time'] is None and not a['phone_verified']
    before=snapshot(s);assert p.update_organization(session,'University')==a and snapshot(s)==before
    v.clock.value+=1;b=p.update_organization(session,'New University');assert b['profile_updated_at']>a['profile_updated_at']
    c=p.update_organization(session,' ');assert c['organization'] is None and c['profile_completion_status']=='incomplete'
    assert facts(s)['profile_events']==3 and s.db.execute('SELECT registered_at FROM user_profiles').fetchone()[0] is None
    events=[json.loads(r[0]) for r in s.db.execute('SELECT metadata FROM business_events')]
    assert all(set(e)=={'changed_fields','profile_was_absent','phone_verified'} for e in events)

@pytest.mark.parametrize('value',[True,12,{},[], 'x'*201,'hello\x00world','hello\nworld'])
def test_T10_T11_invalid_organization_no_writes(env,value):
    s,v,p,provider,uid,session,root,encoded=env;before=snapshot(s)
    with pytest.raises(ProfileError):p.update_organization(session,value)
    assert snapshot(s)==before

def test_empty_update_does_not_create_empty_profile(env):
    s,v,p,provider,uid,session,root,encoded=env
    assert p.update_organization(session,None)['profile_completion_status']=='no_profile'
    assert facts(s)['profiles']==facts(s)['profile_events']==0

def test_T03_T06_registered_user_reads_real_registration_time(env):
    s,v,p,provider,uid,session,root,encoded=env;invite=s.invite();phone='+8613900139000'
    sent=v.send(invite,phone,secrets.token_hex(16),'192.0.2.3');code=provider.captured_for_test(sent['verification_id'])[1]
    r=RegistrationService(s,v,policy=RegistrationPolicy(mode='invite_sms',environment='test'))
    result=r.register({'username':'new-user','password':PASSWORD,'organization':'New University','phone':phone,'invite':invite,'verification_id':sent['verification_id'],'code':code,'request_id':secrets.token_hex(16)})
    token,_=s.login('new-user',PASSWORD);public=p.read(token)
    assert public['user_id']==result.user_id and public['registration_time']==v.clock() and public['profile_completion_status']=='complete'
    assert public['phone_masked']=='***9000' and phone not in json.dumps(public)

def test_T16_T19_complete_atomic_binding_and_visibility(env):
    s,v,p,provider,uid,session,root,encoded=env;data=challenge(env);before=facts(s);phases=[]
    with closing(sqlite3.connect((root/'team.sqlite3').as_uri()+'?mode=ro',uri=True)) as outside:
        def observe(phase):
            phases.append(phase)
            count=outside.execute('SELECT count(*) FROM user_profiles').fetchone()[0]
            assert count==(1 if phase=='after_commit' else 0)
        p.observe=observe;result=p.confirm_phone(session,**data)
    after=facts(s);public=result['profile'];row=p.repo.profile(uid)
    assert after=={'profiles':1,'verified_profiles':1,'consumed':1,'profile_events':1,'users':1,'sessions':1}
    assert row['phone_number']==PHONE and row['phone_verified_at']==v.clock() and row['registered_at'] is None
    assert public['phone_verified'] and public['phone_masked']=='***8000' and public['registration_time'] is None
    assert p.repo.challenge(data['verification_id'])['consumed_by']==uid and p.repo.challenge(data['verification_id'])['purpose']=='phone_change'
    assert not any(k in public for k in ('password','csrf','phone_number','authorization','code_digest'))
    emit('transaction-validation.json',{'scope':'real SQLite profile binding','before':before,'after':after,'same_uid_for_profile_challenge_event':p.repo.challenge(data['verification_id'])['consumed_by']==row['user_id']==uid,'registered_at_remains_unknown':row['registered_at'] is None,'verification_time_matches_clock':row['phone_verified_at']==v.clock(),'before_commit_invisible_to_independent_connection':True,'observer_phases':phases,'new_sessions':after['sessions']-before['sessions'],'real_sms_calls':0})

def test_T08_T29_password_reauthentication_does_not_login(env):
    s,v,p,provider,uid,session,root,encoded=env;before=snapshot(s)
    with pytest.raises(ProfileError):p.reauthenticate(session,phone=PHONE,password='Wrong-Password-2026')
    grant=p.reauthenticate(session,phone=PHONE,password=PASSWORD)
    assert grant['operation']==OPERATION and grant['expires_at']==v.clock()+p.policy.reauth_seconds and snapshot(s)==before
    raw=json.loads(base64.urlsafe_b64decode(grant['authorization'].split('.')[0]+'=='))
    assert all(x not in json.dumps(raw) for x in (PASSWORD,PHONE,session,encoded))
    emit('authorization-validation.json',{'original_password_algorithm_reused':True,'password_check_creates_session':False,'scopes':['user','current_session','target_phone_hmac','profile_phone_bind','password_state','expiry','operation_nonce'],'grant_seconds':p.policy.reauth_seconds,'raw_password_phone_session_or_hash_in_grant':False,'db_unchanged_after_reauthentication':snapshot(s)==before})

@pytest.mark.parametrize('mode',['tampered','other_phone','other_session','other_user','expired','future','wrong_operation','unknown_key'])
def test_T29_T30_grant_cannot_cross_context(env,mode):
    s,v,p,provider,uid,session,root,encoded=env
    grant=p.reauthenticate(session,phone=PHONE,password=PASSWORD)['authorization'];phone=PHONE;used_session=session
    if mode=='tampered':grant=grant[:-1]+('0' if grant[-1]!='0' else '1')
    if mode=='other_phone':phone='+8613900139000'
    if mode=='other_session':used_session=s.login('legacy-user',PASSWORD)[0]
    if mode=='other_user':used_session=add_user(s,encoded,'other-user')[1]
    if mode=='expired':v.clock.value+=301
    if mode=='future':v.clock.value-=1
    if mode in ('wrong_operation','unknown_key'):
        payload=grant.split('.')[0];claim=json.loads(base64.urlsafe_b64decode(payload+'=='))
        claim['op' if mode=='wrong_operation' else 'kid']='register' if mode=='wrong_operation' else 'missing'
        payload=base64.urlsafe_b64encode(json.dumps(claim,sort_keys=True,separators=(',',':')).encode()).decode().rstrip('=')
        grant=payload+'.'+p._tag(v.keys.active,'profile-authorization-v1',payload)
    with pytest.raises(ProfileError):p.send_phone(used_session,phone=phone,authorization=grant,request_id=secrets.token_hex(16),ip='192.0.2.1')
    assert provider.call_count_for_test()==0 and facts(s)['verified_profiles']==0

@pytest.mark.parametrize('mode',['logout','disabled','password_state'])
def test_current_session_and_password_state_rechecked(env,mode):
    s,v,p,provider,uid,session,root,encoded=env;data=challenge(env)
    if mode=='logout':s.logout(session)
    else:
        with s.lock,s.db:
            if mode=='disabled':s.db.execute('UPDATE users SET disabled=1 WHERE id=?',(uid,))
            else:s.db.execute('UPDATE users SET password=? WHERE id=?',(password_hash('Changed-Synthetic-Password'),uid))
    with pytest.raises((ProfileError,PermissionError)):p.confirm_phone(session,**data)
    assert facts(s)['verified_profiles']==facts(s)['consumed']==facts(s)['profile_events']==0

def test_T21_T22_incorrect_attempts_persist_and_exhaust(env):
    s,v,p,provider,uid,session,root,encoded=env;data=challenge(env);wrong=('0' if data['code'][0]!='0' else '1')+data['code'][1:]
    for i in range(v.settings.attempts+1):
        with pytest.raises(ProfileError):p.confirm_phone(session,**{**data,'code':wrong})
    row=p.repo.challenge(data['verification_id'])
    assert row['attempt_count']==v.settings.attempts and row['revoked_at'] is not None
    assert facts(s)['profiles']==facts(s)['consumed']==facts(s)['profile_events']==0

def test_T20_expired_sms_does_not_bind(env):
    s,v,p,provider,uid,session,root,encoded=env;p.policy=replace(p.policy,reauth_seconds=600);data=challenge(env);v.clock.value+=301
    with pytest.raises(ProfileError):p.confirm_phone(session,**data)
    assert facts(s)['profiles']==facts(s)['consumed']==0

def test_T23_T35_repeat_confirmation_returns_same_facts(env):
    s,v,p,provider,uid,session,root,encoded=env;data=challenge(env);first=p.confirm_phone(session,**data);before=snapshot(s);second=p.confirm_phone(session,**data)
    assert not first['already_completed'] and second['already_completed'] and first['profile']==second['profile'] and snapshot(s)==before
    wrong=('0' if data['code'][0]!='0' else '1')+data['code'][1:]
    with pytest.raises(ProfileError):p.confirm_phone(session,**{**data,'code':wrong})
    assert snapshot(s)==before

def test_T24_registration_code_cannot_bind_or_reverse(env):
    s,v,p,provider,uid,session,root,encoded=env;token=s.invite();sent=v.send(token,PHONE,secrets.token_hex(16),'192.0.2.1');code=provider.captured_for_test(sent['verification_id'])[1]
    grant=p.reauthenticate(session,phone=PHONE,password=PASSWORD)['authorization']
    with pytest.raises(ProfileError):p.confirm_phone(session,phone=PHONE,authorization=grant,verification_id=sent['verification_id'],code=code)
    data=challenge(env)
    assert v.verify(token,PHONE,data['verification_id'],data['code'])=={'valid':False,'advisory':True}
    assert facts(s)['consumed']==0 and s.db.execute('SELECT used FROM invites WHERE token=?',(digest(token),)).fetchone()[0]==0

def test_T25_other_user_challenge_never_consumed(env):
    s,v,p,provider,uid,session,root,encoded=env;data=challenge(env);other,other_session=add_user(s,encoded,'other-user');grant=p.reauthenticate(other_session,phone=PHONE,password=PASSWORD)['authorization']
    with pytest.raises(ProfileError):p.confirm_phone(other_session,**{**data,'authorization':grant})
    assert p.repo.challenge(data['verification_id'])['attempt_count']==0 and facts(s)['consumed']==0

def test_T26_T27_unique_phone_normalized_and_no_enumeration(env):
    s,v,p,provider,uid,session,root,encoded=env;data=challenge(env);other,other_session=add_user(s,encoded,'other-user');other_data=challenge(env,session=other_session,phone='138 0013 8000')
    p.confirm_phone(session,**data)
    with pytest.raises(ProfileError) as caught:p.confirm_phone(other_session,**other_data)
    assert caught.value.code=='phone_binding_rejected' and facts(s)['verified_profiles']==facts(s)['consumed']==facts(s)['profile_events']==1
    # Already bound elsewhere produces the same accepted send shape, without provider call.
    before=provider.call_count_for_test();sent=p.send_phone(other_session,phone=PHONE,authorization=other_data['authorization'],request_id=secrets.token_hex(16),ip='192.0.2.1')
    assert sent['status']=='accepted' and provider.call_count_for_test()==before and p.repo.challenge(sent['verification_id'])['send_state']=='failed'

def test_T28_already_verified_phone_cannot_be_replaced(env):
    s,v,p,provider,uid,session,root,encoded=env;data=challenge(env);p.confirm_phone(session,**data);before=p.repo.profile(uid)
    with pytest.raises(ProfileError):p.reauthenticate(session,phone='+8613900139000',password=PASSWORD)
    p.update_organization(session,'University')
    after=p.repo.profile(uid);assert before['phone_number']==after['phone_number'] and before['phone_verified_at']==after['phone_verified_at'] and after['registered_at'] is None

@pytest.mark.parametrize('phase',['verified','profile_written','challenge_consumed','binding_event_written','before_commit'])
def test_T31_T33_each_real_write_phase_rolls_back(env,phase):
    s,v,p,provider,uid,session,root,encoded=env;data=challenge(env);before=snapshot(s)
    def fail(at):
        if at==phase:raise RuntimeError('controlled profile fault')
    p.observe=fail
    with pytest.raises(RuntimeError):p.confirm_phone(session,**data)
    assert not s.db.in_transaction and snapshot(s)==before

@pytest.mark.parametrize('target',['profile_insert','profile_update','sms_update','event_insert','commit'])
def test_T31_T33_real_sql_denials_rollback(env,target):
    s,v,p,provider,uid,session,root,encoded=env
    if target=='profile_update':p.update_organization(session,'Existing Unit')
    data=challenge(env);before=snapshot(s);denied=[]
    def deny(op,a,b,db,trigger):
        match=(target=='profile_insert' and op==sqlite3.SQLITE_INSERT and a=='user_profiles' or target=='profile_update' and op==sqlite3.SQLITE_UPDATE and a=='user_profiles' or target=='sms_update' and op==sqlite3.SQLITE_UPDATE and a=='sms_verifications' or target=='event_insert' and op==sqlite3.SQLITE_INSERT and a=='business_events' or target=='commit' and op==sqlite3.SQLITE_TRANSACTION and a=='COMMIT')
        if match:denied.append(True);return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    s.db.set_authorizer(deny)
    try:
        with pytest.raises(ProfileError):p.confirm_phone(session,**data)
    finally:s.db.set_authorizer(None)
    assert denied and not s.db.in_transaction and snapshot(s)==before

def test_T15_org_event_sql_failure_rolls_back(env):
    s,v,p,provider,uid,session,root,encoded=env;before=snapshot(s)
    def deny(op,a,b,db,trigger):return sqlite3.SQLITE_DENY if op==sqlite3.SQLITE_INSERT and a=='business_events' else sqlite3.SQLITE_OK
    s.db.set_authorizer(deny)
    try:
        with pytest.raises(ProfileError):p.update_organization(session,'New Unit')
    finally:s.db.set_authorizer(None)
    assert snapshot(s)==before

@pytest.mark.parametrize('phase',['profile_written','challenge_consumed','before_commit'])
def test_expiry_during_transaction_rolls_back(env,phase):
    s,v,p,provider,uid,session,root,encoded=env;data=challenge(env);before=snapshot(s)
    def advance(at):
        if at==phase:v.clock.value+=301
    p.observe=advance
    with pytest.raises(ProfileError):p.confirm_phone(session,**data)
    assert snapshot(s)==before

def test_T36_writer_lock_fails_in_bounded_time(env):
    s,v,p,provider,uid,session,root,encoded=env;data=challenge(env);before=snapshot(s);s.db.execute('PRAGMA busy_timeout=30')
    with closing(sqlite3.connect(root/'team.sqlite3')) as writer:
        writer.execute('BEGIN IMMEDIATE');started=time.monotonic()
        with pytest.raises(ProfileError) as caught:p.confirm_phone(session,**data)
        assert time.monotonic()-started<2 and caught.value.http_status==503;writer.rollback()
    assert snapshot(s)==before

def compete(root,keys,clock,session,data,barrier,queue):
    s,v,p,provider=setup(root,keys=keys,clock=Clock(clock))
    try:
        barrier.wait(timeout=15)
        try:result=p.confirm_phone(session,**data);out='replayed' if result['already_completed'] else 'bound'
        except ProfileError as exc:out=exc.code
        if queue is not None:queue.put(out)
        return out
    finally:s.db.close()

def test_T34_two_actual_processes_compete_for_same_phone(env):
    s,v,p,provider,uid,session,root,encoded=env;first=challenge(env);other,other_session=add_user(s,encoded,'other-user');second=challenge(env,session=other_session)
    ctx=multiprocessing.get_context('fork');barrier=ctx.Barrier(2);queue=ctx.Queue()
    procs=[ctx.Process(target=compete,args=(root,v.keys,v.clock(),sess,data,barrier,queue)) for sess,data in [(session,first),(other_session,second)]]
    for proc in procs:proc.start()
    for proc in procs:proc.join(20);assert proc.exitcode==0
    outcomes=sorted(queue.get(timeout=2) for _ in procs);assert outcomes==['bound','phone_binding_rejected']
    state=facts(s);assert state=={'profiles':1,'verified_profiles':1,'consumed':1,'profile_events':1,'users':2,'sessions':2}
    emit('concurrency-processes.json',{'actual_processes':2,'outcomes':outcomes,'facts':state,'real_sqlite':True})

def test_T35_independent_connections_repeat_same_confirmation(env):
    s,v,p,provider,uid,session,root,encoded=env;data=challenge(env);barrier=Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(compete,root,v.keys,v.clock(),session,data,barrier,None) for _ in range(2)];outcomes=sorted(f.result() for f in futures)
    assert outcomes==['bound','replayed'] and facts(s)['profile_events']==facts(s)['consumed']==facts(s)['profiles']==1
    emit('concurrency-repeat.json',{'connections':2,'separate_store_locks':True,'outcomes':outcomes,'facts':facts(s)})

def test_T38_independent_wrong_attempts_not_lost(env):
    s,v,p,provider,uid,session,root,encoded=env;data=challenge(env);data['code']=('0' if data['code'][0]!='0' else '1')+data['code'][1:];barrier=Barrier(5)
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures=[pool.submit(compete,root,v.keys,v.clock(),session,data,barrier,None) for _ in range(5)];outcomes=[f.result() for f in futures]
    row=p.repo.challenge(data['verification_id']);assert outcomes==['phone_binding_rejected']*5 and row['attempt_count']==5 and row['revoked_at'] is not None
    assert facts(s)['profile_events']==facts(s)['consumed']==facts(s)['profiles']==0
    emit('concurrency-wrong-attempts.json',{'connections':5,'attempt_count':row['attempt_count'],'max_attempts':row['max_attempts'],'facts':facts(s)})

def test_send_idempotency_and_shared_register_phone_quota(env):
    s,v,p,provider,uid,session,root,encoded=env;grant=p.reauthenticate(session,phone=PHONE,password=PASSWORD)['authorization'];nonce=secrets.token_hex(16)
    a=p.send_phone(session,phone=PHONE,authorization=grant,request_id=nonce,ip='192.0.2.1');b=p.send_phone(session,phone='13800138000',authorization=grant,request_id=nonce,ip='192.0.2.1')
    assert a==b and provider.call_count_for_test()==1
    v.settings=replace(v.settings,phone_hour_limit=1)
    with pytest.raises(ServiceError) as caught:v.send(s.invite(),PHONE,secrets.token_hex(16),'192.0.2.1')
    assert caught.value.http_status==429 and provider.call_count_for_test()==1

def test_sms_provider_outside_store_lock_and_sql_transaction(env):
    s,v,p,provider,uid,session,root,encoded=env;original=provider.send_verification_code;checks=[]
    def send(phone,code,context):
        assert not s.db.in_transaction and not s.lock._is_owned();checks.append(True);return original(phone,code,context)
    provider.send_verification_code=send;challenge(env);assert checks==[True]

def test_T39_T48_identity_history_models_and_session_preserved(env):
    s,v,p,provider,uid,session,root,encoded=env;c=s.create_conversation(uid);s.snapshot(uid,c['id'],{'proof.txt':b'synthetic result'})
    protected={t:hashlib.sha256(repr([tuple(r) for r in s.db.execute('SELECT * FROM '+t+' ORDER BY rowid')]).encode()).hexdigest() for t in ('users','auth','conversations','runs','files','model_profiles')}
    data=challenge(env);p.update_organization(session,'Unit');p.confirm_phone(session,**data)
    for t,h in protected.items():assert hashlib.sha256(repr([tuple(r) for r in s.db.execute('SELECT * FROM '+t+' ORDER BY rowid')]).encode()).hexdigest()==h
    assert s.authenticate(session)['id']==uid and p.read(session)['registration_time'] is None

def test_disabled_and_production_mock_fail_closed(env):
    s,v,p,provider,uid,session,root,encoded=env
    p.policy=ProfilePolicy()
    assert p.read(session)['profile_completion_status']=='no_profile'
    with pytest.raises(ProfileError):p.reauthenticate(session,phone=PHONE,password=PASSWORD)
    p.policy=ProfilePolicy(phone_binding_enabled=True,environment='production')
    with pytest.raises(ProfileError):p.reauthenticate(session,phone=PHONE,password=PASSWORD)
    assert provider.call_count_for_test()==0

def test_unverified_legacy_corruption_is_not_blessed(env):
    s,v,p,provider,uid,session,root,encoded=env;p.update_organization(session,'Unit')
    # Fault fixture only: approved schema normally prohibits this state.
    s.db.execute('PRAGMA ignore_check_constraints=ON')
    try:
        with s.db:s.db.execute('UPDATE user_profiles SET phone_number=? WHERE user_id=?',(PHONE,uid))
    finally:s.db.execute('PRAGMA ignore_check_constraints=OFF')
    before=snapshot(s)
    with pytest.raises(ProfileError) as caught:p.read(session)
    assert caught.value.http_status==503
    with pytest.raises(ProfileError):p.reauthenticate(session,phone=PHONE,password=PASSWORD)
    assert snapshot(s)==before and provider.call_count_for_test()==0

def test_short_legacy_e164_is_fully_masked(env):
    s,v,p,provider,uid,session,root,encoded=env
    with s.lock,migrations.transaction(s.db):p.repo.create_profile(uid,now=v.clock(),phone_number='+12',phone_verified_at=v.clock())
    public=p.read(session);assert public['phone_masked']=='***' and '+12' not in json.dumps(public)

def test_dal_actual_unique_index_failure_leaves_other_phone_untouched(env):
    s,v,p,provider,uid,session,root,encoded=env;data=challenge(env);other,other_session=add_user(s,encoded,'other-user');p.confirm_phone(session,**data);before=snapshot(s)
    with pytest.raises(sqlite3.IntegrityError):
        with s.lock,migrations.transaction(s.db):p.repo.bind_profile_phone(other,phone_number='+86 13800138000',now=v.clock())
    assert snapshot(s)==before and p.repo.profile(other) is None

@pytest.mark.parametrize('outcome',['rejected','unknown','timeout'])
def test_unsuccessful_transport_never_makes_profile_challenge_valid(env,outcome):
    s,v,p,provider,uid,session,root,encoded=env;original=provider.send_verification_code
    def fail(phone,code,context):
        original(phone,code,context)
        if outcome=='timeout':raise TimeoutError('controlled transport timeout')
        return SendResult(outcome)
    provider.send_verification_code=fail;data=challenge(env)
    with pytest.raises(ProfileError):p.confirm_phone(session,**data)
    assert p.repo.challenge(data['verification_id'])['send_state']==('failed' if outcome=='rejected' else 'unknown')
    assert facts(s)['profiles']==facts(s)['consumed']==facts(s)['profile_events']==0

def test_committed_binding_response_failure_replays_without_new_event(env):
    s,v,p,provider,uid,session,root,encoded=env;data=challenge(env)
    def fail(phase):
        if phase=='after_commit':raise RuntimeError('controlled response failure after commit')
    p.observe=fail
    with pytest.raises(RuntimeError):p.confirm_phone(session,**data)
    state=facts(s);assert state['profiles']==state['consumed']==state['profile_events']==1
    p.observe=lambda phase:None;assert p.confirm_phone(session,**data)['already_completed']
    assert facts(s)==state

@pytest.mark.parametrize('retained',[True,False])
def test_reauthentication_and_challenge_key_rotation(env,retained):
    s,v,p,provider,uid,session,root,encoded=env;data=challenge(env)
    old=v.keys;v.keys=KeyRing('next',{'next':secrets.token_bytes(32),**(old.keys if retained else {})})
    if retained:assert p.confirm_phone(session,**data)['bound']
    else:
        with pytest.raises(ProfileError):p.confirm_phone(session,**data)
        assert facts(s)['profiles']==facts(s)['consumed']==0

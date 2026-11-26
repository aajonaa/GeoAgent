from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from threading import Barrier
import hashlib,json,multiprocessing,os,secrets,sqlite3,time

import pytest
from geological_agent.team import migrations as m
from geological_agent.team.store import Store,password_hash,password_matches,digest
from geological_agent.team.verification_policy import Settings,KeyRing
from geological_agent.team.verification_service import VerificationService
from geological_agent.team.sms_provider import MockProvider
from geological_agent.team.registration_service import RegistrationService,RegistrationPolicy,RegistrationError

PASSWORD='Synthetic-Registration-Password-2026'
PHONE='+8613800138000'

class Clock:
    def __init__(self,value=None):self.value=time.time() if value is None else value
    def __call__(self):return self.value
    def advance(self,seconds):self.value+=seconds

def setup(root,*,keys=None,clock=None,initialize=False):
    root=Path(root)
    if initialize:
        root.mkdir()
        with closing(sqlite3.connect(root/'team.sqlite3',isolation_level=None)) as c:
            c.execute('PRAGMA foreign_keys=ON');m.migrate(c)
    store=Store(root);provider=MockProvider();clock=clock or Clock()
    keys=keys or KeyRing('test-v1',{'test-v1':secrets.token_bytes(32)})
    verification=VerificationService(store,settings=Settings(mode='mock',environment='test',default_region='CN',edge_limit=100),keys=keys,provider=provider,clock=clock)
    registration=RegistrationService(store,verification,policy=RegistrationPolicy(mode='invite_sms',environment='test'))
    return store,verification,registration,provider

@pytest.fixture
def env(tmp_path):
    values=setup(tmp_path/'state',initialize=True)
    try:yield (*values,tmp_path/'state')
    finally:values[0].db.close()

def request(store,v,provider,*,username='registered-user',phone=PHONE,token=None):
    token=token or store.invite()
    sent=v.send(token,phone,secrets.token_hex(16),'192.0.2.1')
    code=provider.captured_for_test(sent['verification_id'])[1]
    return {'username':username,'password':PASSWORD,'organization':' Test University ',
            'phone':phone,'invite':token,'verification_id':sent['verification_id'],'code':code,'request_id':secrets.token_hex(16)}

def facts(store):
    c=store.db
    return {'users':c.execute('SELECT count(*) FROM users').fetchone()[0],
      'profiles':c.execute('SELECT count(*) FROM user_profiles').fetchone()[0],
      'used_invites':c.execute('SELECT count(*) FROM invites WHERE used=1').fetchone()[0],
      'invite_uses':c.execute('SELECT count(*) FROM invite_uses').fetchone()[0],
      'consumed_challenges':c.execute('SELECT count(*) FROM sms_verifications WHERE consumed_at IS NOT NULL').fetchone()[0],
      'registration_events':c.execute("SELECT count(*) FROM business_events WHERE kind='registration_completed'").fetchone()[0],
      'sessions':c.execute('SELECT count(*) FROM auth').fetchone()[0]}

def business_snapshot(store):
    result={}
    for t in ('users','user_profiles','invites','invite_uses','sms_verifications','business_events','auth'):
        rows=[tuple(r) for r in store.db.execute('SELECT * FROM '+t+' ORDER BY rowid')]
        result[t]=hashlib.sha256(repr(rows).encode()).hexdigest()
    return result

def emit(name,value):
    if os.environ.get('P22_EVIDENCE'):(Path(os.environ['P22_EVIDENCE'])/name).write_text(json.dumps(value,indent=2))

def test_T01_T11_T18_T31_T34_complete_atomic_facts(env):
    s,v,r,p,root=env;data=request(s,v,p);checked=[]
    with closing(sqlite3.connect((root/'team.sqlite3').as_uri()+'?mode=ro',uri=True)) as outside:
        def observe(phase):
            checked.append(phase)
            assert s.db.execute('SELECT count(*) FROM auth').fetchone()[0]==0
            assert outside.execute('SELECT count(*) FROM users').fetchone()[0]==(1 if phase=='after_commit' else 0)
        r.observe=observe;result=r.register(data)
    assert result.created and not s.db.in_transaction
    state=facts(s);assert all(value==1 for key,value in state.items() if key!='sessions') and state['sessions']==0
    user=s.user(data['username']);assert user['id']==result.user_id and user['role']=='member'
    assert user['password']!=PASSWORD and password_matches(PASSWORD,user['password'])
    profile=r.repo.profile(result.user_id)
    assert profile['organization']=='Test University' and profile['phone_number']==PHONE
    assert profile['phone_verified_at']==v.clock() and profile['registered_at']==v.clock()
    assert r.repo.invite_use(digest(data['invite']))['user_id']==result.user_id
    assert r.repo.challenge(data['verification_id'])['consumed_by']==result.user_id
    assert 'after_commit' in checked
    emit('transaction-validation.json',{'scope':'real SQLite registration service, session deliberately outside this unit',
      'facts_after_commit':state,'same_database':len([x for x in s.db.execute('PRAGMA database_list') if x[1]!='temp'])==1,
      'observer_phases':checked,'uncommitted_account_invisible_to_other_connection':True,
      'session_before_commit':False,'password_algorithm':'original scrypt','member_role':True,
      'verified_phone_time_matches_clock':True,'invite_usage_and_event_same_uid':True,'real_sms_calls':0})

@pytest.mark.parametrize('phase',['verified','user_created','profile_created','invitation_consumed','invitation_use_created','sms_consumed','event_created','before_commit'])
def test_T02_T08_each_failure_rolls_back_actual_rows(env,phase):
    s,v,r,p,root=env;data=request(s,v,p);before=business_snapshot(s)
    def fail(at):
        if at==phase:raise RuntimeError('controlled failure')
    r.observe=fail
    with pytest.raises(RuntimeError):r.register(data)
    assert not s.db.in_transaction and business_snapshot(s)==before
    assert facts(s)==dict.fromkeys(facts(s),0)

def test_T07_transaction_insert_no_commit_and_legacy_wrapper(env):
    s,v,r,p,root=env;encoded=password_hash(PASSWORD)
    with pytest.raises(RuntimeError):s.create_user_in_transaction(s.db,'new-user',encoded)
    with pytest.raises(RuntimeError),m.transaction(s.db):
        uid=s.create_user_in_transaction(s.db,'new-user',encoded)
        assert s.db.in_transaction and s.user('new-user')['id']==uid
        raise RuntimeError('rollback real account')
    assert s.user('new-user') is None
    admin=s.create_user('old-admin',PASSWORD,role='admin',initial_admin=True)
    member=s.create_user('old-member',PASSWORD,invite=s.invite())
    assert not s.db.in_transaction and s.user('old-admin')['id']==admin
    token,_=s.login('old-member',PASSWORD);assert s.authenticate(token)['id']==member
    with pytest.raises(ValueError):s.create_user('second-admin',PASSWORD,role='admin',initial_admin=True)

def test_real_commit_denial_rolls_back_and_never_authenticates(env):
    s,v,r,p,root=env;data=request(s,v,p);before=business_snapshot(s);denied=[]
    def authorizer(operation,arg1,arg2,db,trigger):
        if operation==sqlite3.SQLITE_TRANSACTION and arg1=='COMMIT' and not denied:
            denied.append(True);return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    s.db.set_authorizer(authorizer)
    try:
        with pytest.raises(RegistrationError) as error:r.register(data)
        assert error.value.http_status==503
    finally:s.db.set_authorizer(None)
    assert denied and business_snapshot(s)==before and not s.db.in_transaction


@pytest.mark.parametrize('operation,table',[(sqlite3.SQLITE_INSERT,'users'),(sqlite3.SQLITE_INSERT,'user_profiles'),
    (sqlite3.SQLITE_UPDATE,'invites'),(sqlite3.SQLITE_INSERT,'invite_uses'),
    (sqlite3.SQLITE_UPDATE,'sms_verifications'),(sqlite3.SQLITE_INSERT,'business_events')])
def test_actual_sql_write_denial_at_each_business_table_rolls_back(env,operation,table):
    s,v,r,p,root=env;data=request(s,v,p);before=business_snapshot(s);denied=[]
    def authorizer(action,arg1,arg2,db,trigger):
        if action==operation and arg1==table:
            denied.append(True);return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    s.db.set_authorizer(authorizer)
    try:
        with pytest.raises(RegistrationError):r.register(data)
    finally:s.db.set_authorizer(None)
    assert denied and business_snapshot(s)==before

@pytest.mark.parametrize('kind',['invite','sms','phone_unique'])
def test_conditional_writes_and_constraint_failures_roll_back(env,kind):
    s,v,r,p,root=env;data=request(s,v,p);before=business_snapshot(s)
    def mutate(phase):
        if kind=='invite' and phase=='profile_created':s.db.execute('UPDATE invites SET used=1 WHERE token=?',(digest(data['invite']),))
        if kind=='sms' and phase=='invitation_use_created':
            uid=s.db.execute('SELECT id FROM users').fetchone()[0]
            s.db.execute('UPDATE sms_verifications SET consumed_at=?,consumed_by=? WHERE verification_id=?',(v.clock(),uid,data['verification_id']))
        if kind=='phone_unique' and phase=='verified':
            s.db.execute("INSERT INTO users(id,username,password,role) VALUES (?,?,?,'member')",('f'*32,'injected-existing','test'))
            r.repo.create_profile('f'*32,now=v.clock(),phone_number=PHONE,phone_verified_at=v.clock())
    r.observe=mutate
    with pytest.raises(RegistrationError):r.register(data)
    assert business_snapshot(s)==before

@pytest.mark.parametrize('state',['invalid','expired','used','revoked'])
def test_T12_T17_invitation_final_checks(env,state):
    s,v,r,p,root=env;data=request(s,v,p)
    if state=='invalid':data['invite']=secrets.token_urlsafe(32)
    elif state=='expired':s.db.execute('UPDATE invites SET expires=?',(v.clock()-1,));s.db.commit()
    elif state=='used':s.db.execute('UPDATE invites SET used=1');s.db.commit()
    else:s.db.execute('UPDATE invites SET revoked_at=?',(v.clock(),));s.db.commit()
    before=business_snapshot(s)
    with pytest.raises(RegistrationError):r.register(data)
    assert business_snapshot(s)==before and facts(s)['users']==0

def test_T19_T20_wrong_attempts_commit_on_registration_rejection(env):
    s,v,r,p,root=env;data=request(s,v,p);data['code']=str((int(data['code'][0])+1)%10)+data['code'][1:]
    for n in range(v.settings.attempts+2):
        with pytest.raises(RegistrationError):r.register(data)
        assert r.repo.challenge(data['verification_id'])['attempt_count']==min(n+1,v.settings.attempts)
        assert facts(s)==dict.fromkeys(facts(s),0)
    assert r.repo.challenge(data['verification_id'])['revoked_at'] is not None

@pytest.mark.parametrize('change',['expired','phone','purpose','invite_context','consumed'])
def test_T21_T26_final_sms_checks_after_advisory(env,change):
    s,v,r,p,root=env;data=request(s,v,p)
    assert v.verify(data['invite'],data['phone'],data['verification_id'],data['code'])['valid']
    if change=='expired':v.clock.advance(v.settings.ttl)
    elif change=='phone':data['phone']='+8613900139000'
    elif change=='purpose':
        s.db.execute("INSERT INTO users(id,username,password,role) VALUES (?,?,?,'member')",('f'*32,'old-user','test'))
        s.db.execute("UPDATE sms_verifications SET purpose='phone_change',bound_user_id=?",('f'*32,));s.db.commit()
    elif change=='invite_context':data['invite']=s.invite()
    else:
        s.db.execute("INSERT INTO users(id,username,password,role) VALUES (?,?,?,'member')",('f'*32,'old-user','test'));s.db.commit()
        with m.transaction(s.db):r.repo.mark_consumed(data['verification_id'],'f'*32,phone_number=PHONE,purpose='register',now=v.clock())
    before=business_snapshot(s)
    with pytest.raises(RegistrationError):r.register(data)
    assert business_snapshot(s)==before

def test_expiry_between_validation_and_consumption_uses_fresh_clock(env):
    s,v,r,p,root=env;data=request(s,v,p);before=business_snapshot(s)
    r.observe=lambda phase:v.clock.advance(v.settings.ttl) if phase=='invitation_use_created' else None
    with pytest.raises(RegistrationError):r.register(data)
    assert business_snapshot(s)==before

def test_T28_T30_conflicts_and_normalized_identity(env):
    s,v,r,p,root=env;data=request(s,v,p)
    s.create_user(data['username'],PASSWORD,invite=s.invite())
    before=business_snapshot(s)
    with pytest.raises(RegistrationError):r.register(data)
    assert business_snapshot(s)==before
    data['username']='another-user';result=r.register(data)
    again={**data,'phone':'+86 (138) 0013-8000','organization':'Test University'}
    replay=r.register(again)
    assert replay.user_id==result.user_id and not replay.created
    assert facts(s)['profiles']==facts(s)['registration_events']==1


def test_phone_bound_after_sms_send_rejects_without_consuming_request(env):
    s,v,r,p,root=env;data=request(s,v,p)
    other=s.create_user('existing-phone-owner',PASSWORD,invite=s.invite())
    with m.transaction(s.db):r.repo.create_profile(other,now=v.clock(),phone_number=PHONE,phone_verified_at=v.clock())
    before=business_snapshot(s)
    with pytest.raises(RegistrationError):r.register({**data,'phone':'+86 138-0013-8000'})
    assert business_snapshot(s)==before and r.repo.challenge(data['verification_id'])['consumed_at'] is None
    assert r.repo.invite_use(digest(data['invite'])) is None

def test_T47_idempotent_retry_never_changes_password_or_facts(env):
    s,v,r,p,root=env;data=request(s,v,p);one=r.register(data);before=business_snapshot(s)
    two=r.register({**data,'password':'Different-Synthetic-Password-2026'})
    assert not two.created and one.user_id==two.user_id and business_snapshot(s)==before
    assert password_matches(PASSWORD,s.user(data['username'])['password'])
    with pytest.raises(RegistrationError):r.register({**data,'organization':'Different'})
    assert business_snapshot(s)==before
    v.clock.advance(r.policy.retry_seconds)
    with pytest.raises(RegistrationError):r.register(data)

def test_T50_real_writer_lock_has_bounded_failure(env):
    s,v,r,p,root=env;data=request(s,v,p);before=business_snapshot(s)
    with closing(sqlite3.connect(root/'team.sqlite3',isolation_level=None)) as blocker:
        blocker.execute('BEGIN IMMEDIATE');s.db.execute('PRAGMA busy_timeout=30')
        started=time.monotonic()
        with pytest.raises(RegistrationError) as error:r.register(data)
        assert error.value.http_status==503 and time.monotonic()-started<3
        blocker.execute('ROLLBACK')
    assert business_snapshot(s)==before

def _attempt(reg,data,barrier):
    barrier.wait()
    try:
        result=reg.register(data);return 'created' if result.created else 'replayed'
    except RegistrationError:return 'rejected'

@pytest.mark.parametrize('kind',['invite','sms_context','phone','username','same_request'])
def test_T16_T27_T48_T49_real_independent_connection_races(env,kind):
    s,v,r,p,root=env;first=request(s,v,p,username='race-first')
    if kind=='username':second=request(s,v,p,username='race-first',phone='+8613900139000')
    elif kind=='phone':
        v.clock.advance(v.settings.cooldown);second=request(s,v,p,username='race-second')
    else:
        second={**first,'username':'race-second','request_id':secrets.token_hex(16)}
        if kind=='sms_context':second['invite']=s.invite()
        if kind=='same_request':second=dict(first)
    s2,v2,r2,p2=setup(root,keys=v.keys,clock=v.clock)
    try:
        barrier=Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            out=[pool.submit(_attempt,reg,data,barrier) for reg,data in [(r,first),(r2,second)]]
            results=[f.result(timeout=15) for f in out]
        assert sorted(results)==(['created','replayed'] if kind=='same_request' else ['created','rejected'])
        state=facts(s)
        assert all(value==1 for key,value in state.items() if key!='sessions') and state['sessions']==0
        emit('concurrency-'+kind+'.json',{'scope':'two actual SQLite connections with independent locks','outcomes':sorted(results),'facts':state})
    finally:s2.db.close()

def _process_register(root,key_values,now,data,queue):
    s,v,r,p=setup(root,keys=KeyRing('test-v1',key_values),clock=Clock(now))
    try:
        try:queue.put('created' if r.register(data).created else 'replayed')
        except RegistrationError:queue.put('rejected')
    finally:s.db.close()

def test_actual_processes_cannot_double_consume(env):
    s,v,r,p,root=env;first=request(s,v,p);second={**first,'username':'process-second','request_id':secrets.token_hex(16)}
    ctx=multiprocessing.get_context('fork');q=ctx.Queue()
    children=[ctx.Process(target=_process_register,args=(str(root),v.keys.keys,v.clock(),d,q)) for d in (first,second)]
    for process in children:process.start()
    for process in children:process.join(15);assert process.exitcode==0
    outcomes=sorted([q.get(timeout=2),q.get(timeout=2)]);assert outcomes==['created','rejected']
    state=facts(s);assert all(value==1 for key,value in state.items() if key!='sessions')
    emit('concurrency-processes.json',{'scope':'two independent processes, same SQLite file','outcomes':outcomes,'facts':state})

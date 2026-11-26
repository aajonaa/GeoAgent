from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
import base64,hmac,json,multiprocessing,os,secrets,sqlite3

import pytest
from geological_agent.team import migrations as m
from geological_agent.team.activity_store import ActivityStore
from geological_agent.team.store import Store,digest
from geological_agent.team.verification_policy import Settings,KeyRing,normalize_phone,client_ip
from geological_agent.team.verification_service import VerificationService,InvitationState,ServiceError
from geological_agent.team.sms_provider import MockProvider,DisabledProvider,UnconfiguredProvider,SendResult

PHONE='+8613800138000'

class Clock:
    def __init__(self):self.value=10000.0
    def __call__(self):return self.value
    def advance(self,seconds):self.value+=seconds

def build(path,*,settings=None,keys=None,provider=None,clock=None,initialize=False):
    c=sqlite3.connect(path,check_same_thread=False,isolation_level=None,timeout=5)
    c.execute('PRAGMA foreign_keys=ON')
    if initialize:m.migrate(c)
    clock=clock or Clock();settings=settings or Settings(mode='mock',environment='test',default_region='CN')
    keys=keys or KeyRing('test-v1',{'test-v1':secrets.token_bytes(32)})
    store=SimpleNamespace(db=c,lock=RLock())
    service=VerificationService(store,settings=settings,keys=keys,provider=provider or MockProvider(),clock=clock)
    return c,service

def invite(c,clock,**changes):
    raw=secrets.token_urlsafe(32)
    c.execute('INSERT INTO invites(token,expires) VALUES (?,?)',(digest(raw),clock()+86400))
    for name,value in changes.items():
        assert name in ('expires','used','revoked_at')
        c.execute('UPDATE invites SET '+name+'=? WHERE token=?',(value,digest(raw)))
    return raw

@pytest.fixture
def env(tmp_path):
    c,s=build(tmp_path/'sms.sqlite3',initialize=True);token=invite(c,s.clock)
    try:yield c,s,token,tmp_path/'sms.sqlite3'
    finally:c.close()

def sent(s,token,phone=PHONE,ip='192.0.2.1'):
    out=s.send(token,phone,secrets.token_hex(16),ip)
    code=s.provider.captured_for_test(out['verification_id'])[1]
    return out,code

def wrong(code):return str((int(code[0])+1)%10)+code[1:]

@pytest.mark.parametrize('changes,state',[({},'valid'),({'expires':9999},'expired'),({'used':1},'already_used'),({'used':1,'revoked_at':9999},'revoked')])
def test_T01_T05_invitation_states_are_readonly(env,changes,state):
    c,s,token,path=env;token=invite(c,s.clock,**changes)
    before=c.execute('SELECT * FROM invites ORDER BY token').fetchall()
    assert s.invitation_state(token).value==state
    assert s.invitation_state('invalid')==InvitationState.INVALID
    assert s.invitation_state(secrets.token_urlsafe(32))==InvitationState.INVALID
    assert c.execute('SELECT * FROM invites ORDER BY token').fetchall()==before
    assert c.execute('SELECT count(*) FROM users').fetchone()[0]==0

def test_T06_old_invite_writer_compatible(tmp_path):
    root=tmp_path/'store';root.mkdir()
    with closing(sqlite3.connect(root/'team.sqlite3',isolation_level=None)) as c:
        c.execute('PRAGMA foreign_keys=ON');m.migrate(c)
    store=Store(root)
    try:
        raw=store.invite()
        service=VerificationService(store,settings=Settings())
        assert service.invitation_state(raw)==InvitationState.VALID
        assert store.db.execute('SELECT used,created_at,created_by,revoked_at FROM invites').fetchone()[0]==0
    finally:store.db.close()

def test_T07_concurrent_invitation_reads(env):
    c,s,token,path=env
    with ThreadPoolExecutor(max_workers=8) as pool:assert all(v==InvitationState.VALID for v in pool.map(s.invitation_state,[token]*32))
    assert c.execute('SELECT used FROM invites').fetchone()[0]==0

@pytest.mark.parametrize('value,expected',[(PHONE,PHONE),('138-0013-8000',PHONE),('+86 (138) 0013-8000',PHONE)])
def test_T08_T10_phone_normalization(env,value,expected):
    assert normalize_phone(value,env[1].settings)==expected

@pytest.mark.parametrize('value',[None,'','+86123','+0013800138000','+8612800138000','+8613800138000x','+86１３８００１３８０００','x'*1000,{},'+8613800138000;DELETE'])
def test_T09_T12_phone_rejection(env,value):
    with pytest.raises(ValueError):normalize_phone(value,env[1].settings)

def test_country_policy_is_explicit(env):
    s=env[1]
    with pytest.raises(ValueError):normalize_phone('+12025550100',s.settings)
    nanp=replace(s.settings,allowed_regions=('NANP',),default_region=None)
    assert normalize_phone('+1 (202) 555-0100',nanp)=='+12025550100'
    with pytest.raises(ValueError):normalize_phone('2025550100',nanp)

def test_T11_bound_phone_does_not_get_sms_or_public_existence_flag(env):
    c,s,token,path=env;uid='a'*32
    c.execute("INSERT INTO users(id,username,password,role) VALUES (?,?,?,'member')",(uid,'existing','synthetic'))
    with m.transaction(c):s.repo.create_profile(uid,now=s.clock(),phone_number=PHONE,phone_verified_at=s.clock())
    result=s.send(token,PHONE,secrets.token_hex(16),'192.0.2.1')
    assert result['status']=='accepted' and 'phone_available' not in result
    assert s.provider.call_count_for_test()==0
    row=s.repo.challenge(result['verification_id']);assert row['send_state']=='failed'
    assert not s.verify(token,PHONE,result['verification_id'],'000000')['valid']

def test_T13_T16_T23_T24_secure_generation_and_no_final_effects(env,monkeypatch):
    c,s,token,path=env;calls=[]
    original=secrets.randbelow
    def secure_rand(limit):calls.append(limit);return original(limit)
    monkeypatch.setattr('geological_agent.team.verification_service.secrets.randbelow',secure_rand)
    before={t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('users','auth','invite_uses')}
    result,code=sent(s,token);row=s.repo.challenge(result['verification_id'])
    assert calls==[10**s.settings.digits]
    assert len(code)==s.settings.digits and code.isdigit()
    assert isinstance(row['code_digest'],bytes) and len(row['code_digest'])==32
    assert code not in result.values() and code.encode() not in row['code_digest']
    # Exact per-record fields contain digests and metadata, not the raw OTP.
    assert all(value!=code for name,value in row.items())
    expected=s._code_digest(row['key_id'],row['verification_id'],token,PHONE,row['send_request_id'],code)
    assert hmac.compare_digest(expected,row['code_digest'])
    for _ in range(2):assert s.verify(token,PHONE,result['verification_id'],code)=={'valid':True,'advisory':True}
    assert {t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in before}==before
    assert c.execute('SELECT used FROM invites WHERE token=?',(digest(token),)).fetchone()[0]==0
    assert s.repo.challenge(result['verification_id'])['consumed_at'] is None

def test_T17_T22_wrong_attempts_commit_and_concurrent_cap(env):
    c,s,token,path=env;result,code=sent(s,token)
    def attempt(_):return s.verify(token,PHONE,result['verification_id'],wrong(code))['valid']
    with ThreadPoolExecutor(max_workers=2) as pool:assert list(pool.map(attempt,range(2)))==[False,False]
    assert s.repo.challenge(result['verification_id'])['attempt_count']==2
    with ThreadPoolExecutor(max_workers=8) as pool:assert not any(pool.map(attempt,range(8)))
    row=s.repo.challenge(result['verification_id']);assert row['attempt_count']==s.settings.attempts
    assert row['revoked_at'] is not None and not s.verify(token,PHONE,result['verification_id'],code)['valid']

def test_T18_expired_and_T20_consumed_rejected(env):
    c,s,token,path=env;result,code=sent(s,token)
    s.clock.advance(s.settings.ttl)
    assert not s.verify(token,PHONE,result['verification_id'],code)['valid']
    s.clock.advance(s.settings.cooldown);result,code=sent(s,token)
    uid='a'*32;c.execute("INSERT INTO users(id,username,password,role) VALUES (?,?,?,'member')",(uid,'synthetic','hash'))
    with m.transaction(c):assert s.repo.mark_consumed(result['verification_id'],uid,phone_number=PHONE,purpose='register',now=s.clock())
    assert not s.verify(token,PHONE,result['verification_id'],code)['valid']

def test_cross_invite_phone_and_purpose_binding(env):
    c,s,token,path=env;result,code=sent(s,token);other=invite(c,s.clock)
    assert not s.verify(other,PHONE,result['verification_id'],code)['valid']
    assert not s.verify(token,'+8613900139000',result['verification_id'],code)['valid']
    with pytest.raises(ServiceError):s.verify(token,PHONE,result['verification_id'],code,purpose='phone_change')
    assert s.repo.challenge(result['verification_id'])['attempt_count']==0
    # Eligibility must be rechecked after an advisory success.
    assert s.verify(token,PHONE,result['verification_id'],code)['valid']
    c.execute('UPDATE invites SET used=1 WHERE token=?',(digest(token),))
    assert not s.verify(token,PHONE,result['verification_id'],code)['valid']

@pytest.mark.parametrize('outcome',['rejected','timeout','unknown','exception'])
def test_T27_T28_T33_T34_provider_failures_never_valid(env,outcome,caplog):
    c,s,token,path=env
    class Failing:
        mode='mock'
        def send_verification_code(self,phone,code,context):
            assert not c.in_transaction
            if outcome=='timeout':raise TimeoutError('private context must be discarded')
            if outcome=='exception':raise RuntimeError(code+s.keys.keys[s.keys.active].hex())
            return SendResult(outcome)
    s.provider=Failing();result=s.send(token,PHONE,secrets.token_hex(16),'192.0.2.1')
    row=s.repo.challenge(result['verification_id'])
    assert row['send_state'] in ('failed','unknown')
    assert not s.verify(token,PHONE,result['verification_id'],'000000')['valid']
    assert not caplog.text

def test_T25_T26_disabled_and_unconfigured_fail_closed(env):
    c,s,token,path=env
    for mode,provider in [('disabled',DisabledProvider()),('provider',UnconfiguredProvider())]:
        other=VerificationService(s.store,settings=replace(s.settings,mode=mode),keys=s.keys,provider=provider,clock=s.clock)
        with pytest.raises(ServiceError) as error:other.send(token,PHONE,secrets.token_hex(16),'192.0.2.1')
        assert error.value.http_status==503
    with pytest.raises(ValueError):Settings(mode='mock',environment='production')
    assert c.execute('SELECT count(*) FROM sms_verifications').fetchone()[0]==0

def test_T29_T30_cooldown_hour_limit_and_restart(env):
    c,s,token,path=env
    for i in range(s.settings.phone_hour_limit):
        sent(s,token)
        with pytest.raises(ServiceError) as e:s.send(token,PHONE,secrets.token_hex(16),'192.0.2.1')
        assert e.value.http_status==429
        s.clock.advance(s.settings.cooldown)
    another=VerificationService(s.store,settings=s.settings,keys=s.keys,provider=MockProvider(),clock=s.clock)
    with pytest.raises(ServiceError):another.send(token,PHONE,secrets.token_hex(16),'192.0.2.99')
    s.clock.advance(s.settings.window)
    assert another.send(token,PHONE,secrets.token_hex(16),'192.0.2.99')['status']=='accepted'

def test_T31_ip_limit_and_rotation_coverage(env):
    c,s,token,path=env;s.settings=replace(s.settings,ip_hour_limit=1,cooldown=0)
    sent(s,token)
    rotated=KeyRing('test-v2',{**s.keys.keys,'test-v2':secrets.token_bytes(32)})
    another=VerificationService(s.store,settings=s.settings,keys=rotated,provider=MockProvider(),clock=s.clock)
    with pytest.raises(ServiceError) as e:another.send(token,'+8613900139000',secrets.token_hex(16),'192.0.2.1')
    assert e.value.http_status==429
    missing=KeyRing('test-v2',{'test-v2':rotated.keys['test-v2']})
    another=VerificationService(s.store,settings=s.settings,keys=missing,provider=MockProvider(),clock=s.clock)
    with pytest.raises(ServiceError) as e:another.send(token,'+8613900139000',secrets.token_hex(16),'192.0.2.2')
    assert e.value.http_status==503

def test_idempotency_and_acknowledgment_failure_do_not_resend(env,monkeypatch):
    c,s,token,path=env;request=secrets.token_hex(16)
    def fail(*a,**kw):raise sqlite3.OperationalError('simulated acknowledgment database failure')
    monkeypatch.setattr(s.repo,'set_send_result',fail)
    first=s.send(token,PHONE,request,'192.0.2.1')
    assert s.repo.challenge(first['verification_id'])['send_state']=='pending'
    second=s.send(token,PHONE,request,'192.0.2.1')
    assert first['verification_id']==second['verification_id'] and s.provider.call_count_for_test()==1
    code=s.provider.captured_for_test(first['verification_id'])[1]
    assert not s.verify(token,PHONE,first['verification_id'],code)['valid']
    with pytest.raises(ServiceError) as e:s.send(token,'+8613900139000',request,'192.0.2.1')
    assert e.value.http_status==409

def test_resend_supersedes_previous_sent_but_failed_does_not(env):
    c,s,token,path=env;old,code=sent(s,token);s.clock.advance(s.settings.cooldown)
    newer,newcode=sent(s,token)
    assert not s.verify(token,PHONE,old['verification_id'],code)['valid']
    assert s.verify(token,PHONE,newer['verification_id'],newcode)['valid']
    class Reject:
        mode='mock'
        def send_verification_code(self,*a):return SendResult('rejected')
    s.clock.advance(s.settings.cooldown);s.provider=Reject();s.send(token,PHONE,secrets.token_hex(16),'192.0.2.1')
    assert s.verify(token,PHONE,newer['verification_id'],newcode)['valid']

def _process_send(path,keydata,token,queue):
    c,s=build(Path(path),keys=KeyRing('test-v1',keydata))
    try:
        try:s.send(token,PHONE,secrets.token_hex(16),'192.0.2.1');queue.put('accepted')
        except ServiceError as e:queue.put(e.code)
    finally:c.close()

def test_T32_two_processes_share_durable_quota(env):
    c,s,token,path=env
    ctx=multiprocessing.get_context('fork');queue=ctx.Queue()
    processes=[ctx.Process(target=_process_send,args=(str(path),s.keys.keys,token,queue)) for _ in range(2)]
    for p in processes:p.start()
    for p in processes:p.join(10);assert p.exitcode==0
    assert sorted([queue.get(timeout=2),queue.get(timeout=2)])==['accepted','rate_limited']
    assert c.execute('SELECT count(*) FROM sms_verifications').fetchone()[0]==1

def test_private_key_file_and_repr(tmp_path):
    p=tmp_path/'private.json';key=secrets.token_bytes(32)
    p.write_text(json.dumps({'active':'test','keys':{'test':base64.b64encode(key).decode()}}));p.chmod(0o600)
    ring=KeyRing.from_file(p);assert ring.active=='test' and key.hex() not in repr(ring)
    p.chmod(0o644)
    with pytest.raises(ValueError):KeyRing.from_file(p)

def test_proxy_boundary_and_edge_guard(env):
    c,s,token,path=env
    assert client_ip('192.0.2.1','198.51.100.1',s.settings)=='192.0.2.1'
    trusted=replace(s.settings,trusted_proxy_cidrs=('127.0.0.1/32',))
    assert client_ip('127.0.0.1','198.51.100.1',trusted)=='198.51.100.1'
    assert client_ip('127.0.0.1','198.51.100.1, 192.0.2.2',trusted)=='unknown'
    s.settings=replace(s.settings,edge_limit=1)
    s.edge_check('192.0.2.1')
    with pytest.raises(ServiceError):s.edge_check('192.0.2.1')


def test_reflected_provider_reference_is_never_persisted(env):
    c,s,token,path=env
    class Reflecting:
        mode='mock'
        def send_verification_code(self,phone,code,context):
            return SendResult('accepted','provider-'+code+'-'+phone.lstrip('+'))
    s.provider=Reflecting();result=s.send(token,PHONE,secrets.token_hex(16),'192.0.2.1')
    assert s.repo.challenge(result['verification_id'])['provider_ref'] is None


def test_wrong_attempts_persist_across_services_and_key_rotation(env):
    c,s,token,path=env;result,code=sent(s,token)
    ring=KeyRing('test-v2',{**s.keys.keys,'test-v2':secrets.token_bytes(32)})
    other_c,other=build(path,keys=ring,clock=s.clock)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(v.verify,token,PHONE,result['verification_id'],wrong(code)) for v in (s,other)]
            assert all(not f.result()['valid'] for f in futures)
        assert s.repo.challenge(result['verification_id'])['attempt_count']==2
        assert other.verify(token,PHONE,result['verification_id'],code)['valid']
    finally:other_c.close()


def test_configuration_factory_requires_explicit_private_key_and_mode(tmp_path):
    from geological_agent.team.verification_config import configured_factory
    config=tmp_path/'settings.json'
    config.write_text(json.dumps({'settings':{'mode':'mock','environment':'production'}}))
    with pytest.raises(ValueError):configured_factory(config)
    config.write_text(json.dumps({'settings':{'mode':'provider','environment':'test'}}))
    with pytest.raises(ValueError):configured_factory(config)
    with pytest.raises(ValueError):Settings(cooldown=3601)


def test_security_validation_artifact(env,caplog):
    c,s,token,path=env;result,code=sent(s,token)
    with pytest.raises(RuntimeError):s.inspect_registration(c,token=token,phone_number=PHONE,verification_id=result['verification_id'],code=code)
    with m.transaction(c):assert s.inspect_registration(c,token=token,phone_number=PHONE,verification_id=result['verification_id'],code=code)
    assert s.verify(token,PHONE,result['verification_id'],code)['valid']
    assert not caplog.text
    row=s.repo.challenge(result['verification_id'])
    assert row['consumed_at'] is None and row['consumed_by'] is None
    assert c.execute('SELECT used FROM invites').fetchone()[0]==0
    if os.environ.get('P21_EVIDENCE'):
        evidence={'hmac_bytes':len(row['code_digest']),'hmac_key_in_database':False,
         'otp_equal_to_any_persisted_field':any(v==code for v in row.values()),
         'application_log_characters':len(caplog.text),'invitation_used':0,'consumed_at':row['consumed_at'],
         'public_response_has_secret':any(k in result for k in ('code','key','phone','invite','code_digest')),
         'explicit_transaction_required':True,'success_is_only_advisory':True,'provider_mode':'mock',
         'cross_process_rate_evidence':'test_T32_two_processes_share_durable_quota',
         'cross_connection_attempt_evidence':'test_wrong_attempts_persist_across_services_and_key_rotation'}
        (Path(os.environ['P21_EVIDENCE'])/'security-validation.json').write_text(json.dumps(evidence,indent=2))

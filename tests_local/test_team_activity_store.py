from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hmac
import json
import os
import secrets
import sqlite3

import pytest
from geological_agent.team.activity_store import ActivityStore, phone
from geological_agent.team.migrations import migrate, transaction

U='a'*32; V='b'*32; NOW=1000.0

@pytest.fixture
def db(tmp_path):
    c=sqlite3.connect(tmp_path/'dal.sqlite3',isolation_level=None,timeout=2)
    c.execute('PRAGMA foreign_keys=ON');migrate(c)
    for uid in (U,V):c.execute("INSERT INTO users(id,username,password,role) VALUES (?,?,?,'member')",(uid,uid,'test-only-hash'))
    try:yield c,ActivityStore(c)
    finally:c.close()


def challenge(a, *, identity='1'*32, number='+12025550100', max_attempts=3, purpose='register', bound=None):
    # Per-test random key, in memory only; no literal HMAC key or plaintext code in DB.
    key=secrets.token_bytes(32)
    value=hmac.digest(key,secrets.token_bytes(24),'sha256')
    a.create_challenge(verification_id=identity,phone_number=number,purpose=purpose,bound_user_id=bound,
                       code_digest=value,key_id='test-key-v1',send_request_id='send:'+identity,
                       request_digest=hmac.digest(key,b'request','sha256'),ip_bucket='f'*64,
                       bucket_key_id='bucket-v1',created_at=NOW,expires_at=NOW+300,max_attempts=max_attempts)
    return value


def test_T06_profile_create_update_null_and_uniqueness(db):
    c,a=db
    assert a.profile(U) is None
    with transaction(c):
        a.create_profile(U,now=NOW,organization=' Unit ',phone_number='+1 (202) 555-0100',phone_verified_at=NOW)
        a.create_profile(V,now=NOW)
    assert a.profile(U)['organization']=='Unit'
    assert a.profile_by_phone('+1 202 555-0100')['user_id']==U
    assert a.profile(V)['registered_at'] is None
    with pytest.raises(sqlite3.IntegrityError),transaction(c):
        a.update_profile(V,now=NOW+1,phone_number='+12025550100',phone_verified_at=NOW+1)
    with pytest.raises(ValueError),transaction(c):a.update_profile(U,now=NOW+1,phone_number='+12025550101')
    with transaction(c):a.update_profile(U,now=NOW+1,organization='Another')
    assert a.profile(U)['created_at']==NOW and a.profile(U)['updated_at']==NOW+1
    with pytest.raises(ValueError),transaction(c):a.create_profile('c'*32,now=NOW,phone_number='+12025550102')
    assert a.profile_by_phone(None) is None
    for number in ['13800138000','+１２３４','+012345','+123;DROP TABLE users']:
        with pytest.raises(ValueError):phone(number)


def test_T05_direct_constraints_and_delete_behavior(db):
    c,a=db
    with pytest.raises(sqlite3.IntegrityError):c.execute('INSERT INTO user_profiles(user_id,created_at,updated_at) VALUES (?,?,?)',('c'*32,NOW,NOW))
    with pytest.raises(sqlite3.IntegrityError):c.execute('INSERT INTO user_profiles(user_id,created_at,updated_at) VALUES (NULL,?,?)',(NOW,NOW))
    with pytest.raises(sqlite3.IntegrityError):c.execute('INSERT INTO user_profiles(user_id,phone_number,created_at,updated_at) VALUES (?,?,?,?)',(U,'+12025550100',NOW,NOW))
    with transaction(c):
        a.create_profile(U,now=NOW)
        a.create_profile(V,now=NOW)
    with pytest.raises(sqlite3.IntegrityError):c.execute('DELETE FROM users WHERE id=?',(U,))
    with pytest.raises(sqlite3.IntegrityError):c.execute('UPDATE users SET id=? WHERE id=?',('c'*32,U))
    assert not c.execute('PRAGMA foreign_key_check').fetchall()


def test_T07_invite_usage_and_sms_set_null(db):
    c,a=db;token='e'*64
    c.execute('INSERT INTO invites(token,expires) VALUES (?,?)',(token,NOW+600))
    with transaction(c):
        challenge(a)
        assert a.mark_invite_used(token,now=NOW)
        a.record_invite_use(token,U,used_at=NOW,registration_request_id='r1',verification_id='1'*32)
    assert a.invite_use(token)['user_id']==U
    assert a.invite_use_by_user(U)['invite_token']==token
    with transaction(c):assert not a.mark_invite_used(token,now=NOW+1)
    with pytest.raises(sqlite3.IntegrityError),transaction(c):a.record_invite_use(token,V,used_at=NOW,registration_request_id='r2')
    with pytest.raises(sqlite3.IntegrityError),transaction(c):a.record_invite_use('d'*64,V,used_at=NOW,registration_request_id='r3')
    c.execute('DELETE FROM sms_verifications WHERE verification_id=?',('1'*32,))
    assert a.invite_use(token)['verification_id'] is None
    with pytest.raises(sqlite3.IntegrityError):c.execute('DELETE FROM invites WHERE token=?',(token,))


def test_T08_sms_storage_attempts_and_one_time_consumption(db):
    c,a=db
    with transaction(c):
        expected=challenge(a)
        assert a.applicable_challenge('+12025550100','register',now=NOW+1) is None
        a.set_send_result('1'*32,state='sent',now=NOW+1)
    assert hmac.compare_digest(a.challenge('1'*32)['code_digest'],expected)
    assert a.applicable_challenge('+12025550100','register',now=NOW+300) is None
    with transaction(c):
        assert a.increment_attempts('1'*32,phone_number='+12025550100',purpose='register',now=NOW+2)
        assert a.mark_consumed('1'*32,U,phone_number='+12025550100',purpose='register',now=NOW+3)
        assert not a.mark_consumed('1'*32,U,phone_number='+12025550100',purpose='register',now=NOW+4)
    assert a.challenge('1'*32)['attempt_count']==1
    assert a.challenge('1'*32)['consumed_by']==U
    assert not ({'code','plaintext_code','hmac_key'} & {r[1] for r in c.execute('PRAGMA table_info(sms_verifications)')})


def test_sms_attempt_limit_and_scope_and_late_ack(db):
    c,a=db
    with transaction(c):
        challenge(a,max_attempts=1)
        a.set_send_result('1'*32,state='sent',now=NOW+1)
        assert not a.mark_consumed('1'*32,U,phone_number='+12025550101',purpose='register',now=NOW+2)
        assert a.increment_attempts('1'*32,phone_number='+12025550100',purpose='register',now=NOW+2)
        assert not a.increment_attempts('1'*32,phone_number='+12025550100',purpose='register',now=NOW+3)
        assert not a.mark_consumed('1'*32,U,phone_number='+12025550100',purpose='register',now=NOW+3)
        challenge(a,identity='2'*32);challenge(a,identity='3'*32)
        a.set_send_result('3'*32,state='sent',now=NOW+3)
        a.set_send_result('2'*32,state='sent',now=NOW+4)
    assert a.applicable_challenge('+12025550100','register',now=NOW+5)['verification_id']=='3'*32
    assert a.challenge('2'*32)['revoked_at'] is not None
    with transaction(c):
        challenge(a,identity='4'*32,purpose='phone_change',bound=U)
        a.set_send_result('4'*32,state='sent',now=NOW+4)
        assert not a.mark_consumed('4'*32,V,phone_number='+12025550100',purpose='phone_change',bound_user_id=U,now=NOW+5)
        assert a.mark_consumed('4'*32,U,phone_number='+12025550100',purpose='phone_change',bound_user_id=U,now=NOW+5)


@pytest.mark.parametrize('assignment,args',[
    ('code_digest=?',('plaintext',)),('expires_at=created_at',()),('max_attempts=0',()),
    ('attempt_count=99',()),('send_state=?',('bogus',)),('consumed_at=?,consumed_by=?',(NOW,U)),
])
def test_sms_db_hard_constraints(db,assignment,args):
    c,a=db
    with transaction(c):challenge(a)
    with pytest.raises(sqlite3.IntegrityError):c.execute('UPDATE sms_verifications SET '+assignment+' WHERE verification_id=?',(*args,'1'*32))


def test_T09_event_queries_idempotency_and_private_input_rejection(db):
    c,a=db
    with transaction(c):
        eid=a.insert_event('registration_completed',user_id=U,object_type='user',object_id=U,occurred_at=NOW,
                           idempotency_key='registration:'+U,metadata={'channel':'invite','profile_present':True})
        assert a.insert_event('registration_completed',user_id=U,object_type='user',object_id=U,occurred_at=NOW+1,
                              idempotency_key='registration:'+U,metadata={'profile_present':True,'channel':'invite'})==eid
        a.insert_event('login_failed',user_id=None,object_type='auth_attempt',object_id='c'*32,occurred_at=NOW+1,metadata={'reason':'invalid_credentials'})
    assert len(a.events(start=NOW,end=NOW+1,user_id=U))==1
    assert len(a.events(start=NOW,end=NOW+2))==2
    assert not a.events(start=NOW,end=NOW+2,user_id=V)
    for key in ('password','code','api_key','phone_number','request_body'):
        with pytest.raises(ValueError),transaction(c):
            a.insert_event('login_failed',user_id=None,object_type='auth_attempt',object_id='c'*32,occurred_at=NOW,metadata={key:'not-allowed'})
    with pytest.raises(ValueError),transaction(c):a.insert_event('run_submitted',user_id=U,object_type='user',object_id=U,occurred_at=NOW)
    with pytest.raises(ValueError),transaction(c):
        a.insert_event('registration_completed',user_id=V,object_type='user',object_id=V,occurred_at=NOW,idempotency_key='registration:'+U,metadata={'channel':'invite','profile_present':True})
    with pytest.raises(ValueError):a.events(start=NOW,end=NOW+1,limit=100000)
    assert not a.events(start=NOW,end=NOW+1,kind="x' OR 1=1 --")


@pytest.mark.parametrize('metadata', ['not-json','[]','{"x":"'+'x'*2050+'"}'])
def test_event_db_json_and_size(db,metadata):
    c,a=db
    with pytest.raises(sqlite3.IntegrityError):c.execute("INSERT INTO business_events(event_id,kind,user_id,object_type,object_id,occurred_at,metadata) VALUES (?,'login_failed',NULL,'auth_attempt',NULL,?,?)",(secrets.token_hex(16),NOW,metadata))


def test_dal_never_commits_caller_transaction(db):
    c,a=db
    with pytest.raises(RuntimeError):a.create_profile(U,now=NOW)
    with pytest.raises(RuntimeError),transaction(c):
        a.create_profile(U,now=NOW)
        challenge(a)
        a.insert_event('profile_updated',user_id=U,object_type='user',object_id=U,occurred_at=NOW,metadata={'changed_fields':['organization']})
        assert c.in_transaction
        raise RuntimeError('roll back all three DAL writes')
    assert a.profile(U) is None
    assert c.execute('SELECT count(*) FROM sms_verifications').fetchone()[0]==0
    assert c.execute('SELECT count(*) FROM business_events').fetchone()[0]==0


@pytest.mark.parametrize('kind', ['phone','invite','sms'])
def test_two_connection_contention_facts(tmp_path,kind):
    path=tmp_path/'race.sqlite3'
    with closing(sqlite3.connect(path,isolation_level=None)) as c:
        c.execute('PRAGMA foreign_keys=ON');migrate(c)
        for uid in (U,V):c.execute("INSERT INTO users(id,username,password,role) VALUES (?,?,?,'member')",(uid,uid,'synthetic'))
        c.execute('INSERT INTO invites(token,expires) VALUES (?,?)',('e'*64,NOW+600))
        with transaction(c):
            challenge(ActivityStore(c));ActivityStore(c).set_send_result('1'*32,state='sent',now=NOW+1)
    def attempt(uid):
        with closing(sqlite3.connect(path,isolation_level=None,timeout=5)) as c:
            c.execute('PRAGMA foreign_keys=ON');a=ActivityStore(c)
            try:
                with transaction(c):
                    if kind=='phone':a.create_profile(uid,now=NOW,phone_number='+12025550100',phone_verified_at=NOW)
                    elif kind=='invite':
                        if not a.mark_invite_used('e'*64,now=NOW):return False
                        a.record_invite_use('e'*64,uid,used_at=NOW,registration_request_id='r:'+uid)
                    else:return a.mark_consumed('1'*32,uid,phone_number='+12025550100',purpose='register',now=NOW+2)
                return True
            except sqlite3.IntegrityError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(attempt,(U,V)))==[False,True]


@pytest.mark.parametrize('kind,object_type,object_id,metadata',[
    ('login_succeeded','auth_attempt','c'*32,{'method':'password','attempt_id':'c'*32}),
    ('file_downloaded','file','d'*64,{'cid':'e'*32,'generation':'f'*32,'content_sha256':'1'*64,'name_hmac':'2'*64,'semantics':'authorized_response_started'}),
    ('stream_started','event_stream','login_succeeded',{'covered_from':NOW,'semantics':'v1','writer_version':'p12-test'}),
    ('retention_advanced','event_stream','login_failed',{'retained_from':NOW,'reason':'retention','semantics':'v1'}),
])
def test_remaining_event_types(db,kind,object_type,object_id,metadata):
    c,a=db
    with transaction(c):a.insert_event(kind,user_id=None if object_type=='event_stream' else U,object_type=object_type,object_id=object_id,occurred_at=NOW,metadata=metadata)
    assert len(a.events(start=NOW,end=NOW+1,kind=kind))==1


def test_invite_user_and_request_unique_and_sms_identity_unique(db):
    c,a=db
    for token in ('a'*64,'b'*64,'c'*64):c.execute('INSERT INTO invites(token,expires) VALUES (?,?)',(token,NOW+600))
    with transaction(c):a.record_invite_use('a'*64,U,used_at=NOW,registration_request_id='r1')
    with pytest.raises(sqlite3.IntegrityError),transaction(c):a.record_invite_use('b'*64,U,used_at=NOW,registration_request_id='r2')
    with pytest.raises(sqlite3.IntegrityError),transaction(c):a.record_invite_use('c'*64,V,used_at=NOW,registration_request_id='r1')
    with transaction(c):challenge(a)
    with pytest.raises(sqlite3.IntegrityError),transaction(c):challenge(a)


def test_finite_times_and_input_whitelists(db):
    c,a=db
    for value in [float('nan'),float('inf'),-1,True,'1000']:
        with pytest.raises(ValueError),transaction(c):a.create_profile(U,now=value)
    with pytest.raises(ValueError),transaction(c):
        a.create_challenge(verification_id='a'*32,phone_number='+12025550100',purpose='register',bound_user_id=None,code_digest=b'bad',key_id='test',send_request_id='send',request_digest=b'x'*32,ip_bucket='f'*64,bucket_key_id='test',created_at=NOW,expires_at=NOW+100,max_attempts=3)
    with transaction(c):a.create_profile(U,now=NOW)
    with pytest.raises(ValueError),transaction(c):a.update_profile(U,now=NOW,**{'organization=?,disabled=1 --':'bad'})
    with pytest.raises(ValueError),transaction(c):
        a.insert_event('login_failed',user_id=None,object_type='auth_attempt',object_id='c'*32,occurred_at=NOW,metadata=[])
    with transaction(c):
        challenge(a);a.set_send_result('1'*32,state='sent',now=NOW+20)
    assert a.applicable_challenge('+12025550100','register',now=NOW+1) is None

"""Own-profile operations on Store.db; no new account or Session mechanism."""
from dataclasses import dataclass
import base64
import hmac
import json
import math
import re
import secrets
import sqlite3
import time

from .activity_store import ActivityStore
from .migrations import transaction
from .store import password_matches
from .verification_policy import normalize_phone
from .verification_service import ServiceError

OPERATION = 'profile_phone_bind'
SMS_PURPOSE = 'phone_change'  # Existing P1.1 enum, limited here to FIRST binding.


@dataclass(frozen=True)
class ProfilePolicy:
    phone_binding_enabled: bool = False
    environment: str = 'production'
    reauth_seconds: int = 300
    body_limit: int = 4096

    def __post_init__(self):
        if type(self.phone_binding_enabled) is not bool or self.environment not in ('production','development','test'):
            raise ValueError('Invalid profile policy')
        if type(self.reauth_seconds) is not int or not 1 <= self.reauth_seconds <= 900 or type(self.body_limit) is not int or self.body_limit <= 0:
            raise ValueError('Invalid profile policy')


class ProfileError(Exception):
    def __init__(self, code, http_status):
        super().__init__(code); self.code=code; self.http_status=http_status


class ProfileService:
    def __init__(self, store, verification=None, *, policy=None, clock=None, observer=None):
        self.store=store; self.db=store.db; self.lock=store.lock
        self.verification=verification; self.policy=policy or ProfilePolicy()
        self.clock=clock or (verification.clock if verification else time.time)
        self.repo=ActivityStore(self.db); self.observe=observer or (lambda phase: None)
        self.email_profiles=bool(self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='email_identities'").fetchone())
        self.registration_details=bool(self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='registration_details'").fetchone())
        if verification is not None and (verification.store is not store or verification.db is not self.db):
            raise ValueError('Profile and verification require the same Store.db')
        databases=[r for r in self.db.execute('PRAGMA database_list') if r[1]!='temp']
        if len(databases)!=1 or databases[0][1]!='main':
            raise ValueError('Profile operations require one SQLite main database')

    def ensure_binding(self):
        v=self.verification
        if not self.policy.phone_binding_enabled or v is None or v.settings.environment!=self.policy.environment:
            raise ProfileError('phone_binding_unavailable',503)
        if self.policy.environment=='production' and v.settings.mode!='provider':
            raise ProfileError('phone_binding_unavailable',503)
        try: v._enabled()
        except ServiceError: raise ProfileError('phone_binding_unavailable',503) from None

    def _session(self, session):
        # Re-read authority from the existing auth/users tables, including expiry/disable.
        if not isinstance(session,str) or not session:
            raise PermissionError('Please sign in')
        user=self.store.authenticate(session)
        encoded=self.db.execute('SELECT password FROM users WHERE id=?',(user['id'],)).fetchone()[0]
        return user,encoded

    def _profile(self, uid):
        row=self.repo.profile(uid)
        if row is not None and ((row['phone_number'] is None)!=(row['phone_verified_at'] is None)):
            # Approved schema forbids unverified numbers here. Never bless corrupt legacy data.
            raise ProfileError('profile_unavailable',503)
        return row

    def _public(self, user, row):
        number=row['phone_number'] if row else None
        verified=bool(number and row['phone_verified_at'] is not None)
        organization=row['organization'] if row else None
        email=self.db.execute('SELECT email,verified_at FROM email_identities WHERE user_id=?',(user['id'],)).fetchone() if self.email_profiles else None
        details=self.db.execute('SELECT research_area,gender,age FROM registration_details WHERE user_id=?',(user['id'],)).fetchone() if self.registration_details else None
        return {'user_id':user['id'],'username':user['username'],'organization':organization,
                'phone_masked':('***'+number[-4:] if len(number)>7 else '***') if verified else None,'phone_verified':verified,
                'phone_verified_at':row['phone_verified_at'] if verified else None,
                'profile_updated_at':row['updated_at'] if row else None,
                'registration_time':row['registered_at'] if row else None,
                'email_masked':email['email'][0]+'***@'+email['email'].split('@')[1] if email else None,
                'email_verified':bool(email),
                'research_area':details['research_area'] if details else None,
                'gender':details['gender'] if details else None,
                'age':details['age'] if details else None,
                'profile_completion_status':'no_profile' if row is None else 'complete' if organization and (verified or email) else 'incomplete'}

    def read(self, session):
        try:
            with self.lock:
                user,_=self._session(session)
                return self._public(user,self._profile(user['id']))
        except sqlite3.Error: raise ProfileError('profile_unavailable',503) from None

    def update_organization(self, session, organization):
        if organization is not None:
            if not isinstance(organization,str): raise ProfileError('invalid_request',400)
            organization=organization.strip() or None
            if organization is not None and (len(organization)>200 or re.search(r'[\x00-\x1f\x7f]',organization)):
                raise ProfileError('invalid_request',400)
        try:
            with self.lock,transaction(self.db):
                user,_=self._session(session);uid=user['id'];row=self._profile(uid)
                if (row['organization'] if row else None)!=organization:
                    now=self.clock()
                    if row is None:self.repo.create_profile(uid,now=now,organization=organization)
                    else:self.repo.update_profile(uid,now=now,organization=organization)
                    self.observe('organization_written')
                    self.repo.insert_event('profile_updated',user_id=uid,object_type='user',object_id=uid,occurred_at=now,
                        metadata={'changed_fields':['organization'],'profile_was_absent':row is None,'phone_verified':bool(row and row['phone_verified_at'] is not None)})
                    self.observe('organization_event_written')
                self._session(session)
                result=self._public(user,self._profile(uid))
            return result
        except sqlite3.Error: raise ProfileError('profile_unavailable',503) from None

    def _phone(self, value):
        try:return normalize_phone(value,self.verification.settings)
        except ValueError:raise ProfileError('invalid_request',400) from None

    def _eligible(self, uid):
        row=self._profile(uid)
        if row and row['phone_verified_at'] is not None:
            raise ProfileError('phone_binding_rejected',403)
        return row

    def _tag(self, kid, domain, *parts):
        return self.verification.keys.digest(kid,domain,*parts).hex()

    def _issue(self, user, encoded, session, phone):
        kid=self.verification.keys.active;now=self.clock()
        claim={'v':1,'kid':kid,'sub':user['id'],'op':OPERATION,'jti':secrets.token_hex(16),'iat':now,'exp':now+self.policy.reauth_seconds,
               'sid':self._tag(kid,'profile-session-v1',session),'phone':self._tag(kid,'profile-phone-v1',phone),
               'pwd':self._tag(kid,'profile-password-state-v1',encoded)}
        payload=base64.urlsafe_b64encode(json.dumps(claim,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).decode().rstrip('=')
        signature=self._tag(kid,'profile-authorization-v1',payload)
        return {'authorization':payload+'.'+signature,'expires_at':claim['exp'],'operation':OPERATION}

    def reauthenticate(self, session, *, phone, password):
        self.ensure_binding();phone=self._phone(phone)
        if not isinstance(password,str) or not 12<=len(password)<=256:raise ProfileError('invalid_request',400)
        try:
            with self.lock:
                user,encoded=self._session(session);self._eligible(user['id'])
            # Original scrypt outside writer lock; does not create a Session.
            if not password_matches(password,encoded):raise ProfileError('reauthentication_required',403)
            with self.lock,transaction(self.db):
                current,current_encoded=self._session(session);self._eligible(current['id'])
                if current['id']!=user['id'] or not hmac.compare_digest(encoded,current_encoded):
                    raise ProfileError('reauthentication_required',403)
                return self._issue(current,current_encoded,session,phone)
        except sqlite3.Error:raise ProfileError('profile_unavailable',503) from None

    def _grant(self, session, phone, authorization):
        user,encoded=self._session(session)
        try:
            if not isinstance(authorization,str) or len(authorization)>2048:raise ValueError()
            payload,signature=authorization.split('.')
            if not re.fullmatch(r'[A-Za-z0-9_-]+',payload) or not re.fullmatch(r'[0-9a-f]{64}',signature):raise ValueError()
            claim=json.loads(base64.urlsafe_b64decode(payload+'='*(-len(payload)%4)))
            if not isinstance(claim,dict) or set(claim)!={'v','kid','sub','op','jti','iat','exp','sid','phone','pwd'}:raise ValueError()
            kid=claim['kid']
            if not isinstance(kid,str) or kid not in self.verification.keys.keys:raise ValueError()
            if not hmac.compare_digest(signature,self._tag(kid,'profile-authorization-v1',payload)):raise ValueError()
            if type(claim['v']) is not int or claim['v']!=1 or claim['sub']!=user['id'] or claim['op']!=OPERATION:raise ValueError()
            if not isinstance(claim['jti'],str) or not re.fullmatch(r'[0-9a-f]{32}',claim['jti']):raise ValueError()
            if any(type(claim[k]) not in (int,float) or not math.isfinite(claim[k]) for k in ('iat','exp')):raise ValueError()
            if not claim['iat']<=self.clock()<claim['exp'] or not 0<claim['exp']-claim['iat']<=self.policy.reauth_seconds:raise ValueError()
            for name,expected in [('sid',self._tag(kid,'profile-session-v1',session)),('phone',self._tag(kid,'profile-phone-v1',phone)),('pwd',self._tag(kid,'profile-password-state-v1',encoded))]:
                if not isinstance(claim[name],str) or not hmac.compare_digest(claim[name],expected):raise ValueError()
            return user,claim
        except (ValueError,TypeError,KeyError,UnicodeError):raise ProfileError('reauthentication_required',403) from None

    def send_phone(self, session, *, phone, authorization, request_id, ip):
        self.ensure_binding();phone=self._phone(phone)
        try:
            with self.lock:
                user,grant=self._grant(session,phone,authorization);self._eligible(user['id'])
            def authorize(now):
                current,latest=self._grant(session,phone,authorization);self._eligible(current['id'])
                if latest['jti']!=grant['jti']:raise ProfileError('reauthentication_required',403)
            return self.verification.send_for_profile(phone,request_id,ip,user_id=user['id'],context_id=grant['jti'],session_tag=grant['sid'],authorize=authorize)
        except sqlite3.Error:raise ProfileError('profile_unavailable',503) from None

    def _matching_code(self, row, uid, phone, grant, code):
        v=self.verification;kid=row['key_id']
        if kid not in v.keys.keys:return False
        expected=v._profile_context_digest(kid,uid,phone,row['send_request_id'],grant['jti'],grant['sid'])
        if not hmac.compare_digest(row['request_digest'],expected):return False
        return hmac.compare_digest(row['code_digest'],v._profile_code_digest(kid,row['verification_id'],uid,phone,row['send_request_id'],grant['jti'],grant['sid'],code))

    def confirm_phone(self, session, *, phone, authorization, verification_id, code):
        self.ensure_binding();phone=self._phone(phone);v=self.verification
        if not isinstance(verification_id,str) or not re.fullmatch(r'[0-9a-f]{32}',verification_id) or not isinstance(code,str) or not re.fullmatch(r'[0-9]{'+str(v.settings.digits)+'}',code):
            raise ProfileError('invalid_request',400)
        rejected=False;replayed=False
        try:
            with self.lock,transaction(self.db):
                user,grant=self._grant(session,phone,authorization);uid=user['id'];now=self.clock()
                row=self.repo.challenge(verification_id)
                if (row is None or row['purpose']!=SMS_PURPOSE or row['bound_user_id']!=uid or row['phone_number']!=phone
                    or row['send_state']!='sent' or row['revoked_at'] is not None or not row['sent_at']<=now<row['expires_at'] or row['attempt_count']>=row['max_attempts']):
                    raise ProfileError('phone_binding_rejected',403)
                # Context must match before wrong attempts can affect this challenge.
                if row['key_id'] not in v.keys.keys or not hmac.compare_digest(row['request_digest'],v._profile_context_digest(row['key_id'],uid,phone,row['send_request_id'],grant['jti'],grant['sid'])):
                    raise ProfileError('phone_binding_rejected',403)
                code_matches=self._matching_code(row,uid,phone,grant,code)
                event_key='profile-phone:'+verification_id
                if row['consumed_at'] is not None:
                    profile=self._profile(uid)
                    event=self.db.execute("SELECT 1 FROM business_events WHERE kind='profile_updated' AND user_id=? AND idempotency_key=?",(uid,event_key)).fetchone()
                    if not (code_matches and row['consumed_by']==uid and profile and profile['phone_number']==phone and event):
                        raise ProfileError('phone_binding_rejected',403)
                    replayed=True
                else:
                    before=self._eligible(uid)
                    applicable=self.repo.applicable_challenge(phone,SMS_PURPOSE,bound_user_id=uid,now=now)
                    if not applicable or applicable['verification_id']!=verification_id or self.repo.profile_by_phone(phone) is not None:
                        raise ProfileError('phone_binding_rejected',403)
                    if not code_matches:
                        self.repo.increment_attempts(verification_id,phone_number=phone,purpose=SMS_PURPOSE,bound_user_id=uid,now=now)
                        rejected=True  # Commit the security counter, then reject outside.
                    else:
                        self.observe('verified')
                        if not self.repo.bind_profile_phone(uid,phone_number=phone,now=now):raise ProfileError('phone_binding_rejected',403)
                        self.observe('profile_written');self._grant(session,phone,authorization)
                        if not self.repo.mark_consumed(verification_id,uid,phone_number=phone,purpose=SMS_PURPOSE,bound_user_id=uid,now=self.clock()):
                            raise ProfileError('phone_binding_rejected',403)
                        self.observe('challenge_consumed')
                        self.repo.insert_event('profile_updated',user_id=uid,object_type='user',object_id=uid,occurred_at=now,idempotency_key=event_key,
                            metadata={'changed_fields':['phone_number'],'profile_was_absent':before is None,'phone_verified':True})
                        self.observe('binding_event_written');self.observe('before_commit')
                if not rejected:
                    self._grant(session,phone,authorization)
                    if self.clock()>=row['expires_at']:raise ProfileError('phone_binding_rejected',403)
                    result={'ok':True,'bound':True,'already_completed':replayed,'profile':self._public(user,self._profile(uid))}
            if rejected:raise ProfileError('phone_binding_rejected',403)
        except sqlite3.IntegrityError:raise ProfileError('phone_binding_rejected',403) from None
        except sqlite3.Error:raise ProfileError('profile_unavailable',503) from None
        self.observe('after_commit')
        return result

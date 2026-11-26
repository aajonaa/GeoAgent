"""Email proof, atomic account facts, and existing Store Sessions."""
from dataclasses import dataclass
import hmac
import re
import secrets
import time
import uuid
from .activity_store import ActivityStore
from .directmail import MailError
from .migrations import transaction
from .registration_service import RegistrationResult
from .store import digest, password_hash


class EmailError(Exception):
    def __init__(self, code, status=400, retry_after=None):
        super().__init__(code)
        self.code, self.status, self.retry_after = code, status, retry_after


def normalize_email(value):
    if not isinstance(value, str):
        raise EmailError('invalid_request')
    value = value.strip().lower()
    if len(value)>254 or not re.fullmatch(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]{1,64}@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+",value):
        raise EmailError('invalid_email')
    local = value.split('@')[0]
    if local.startswith('.') or local.endswith('.') or '..' in local:
        raise EmailError('invalid_email')
    return value  # Explicit case-insensitive identity; no dot/plus alias merging.


@dataclass(frozen=True)
class EmailPolicy:
    environment: str = 'production'
    ttl: int = 300
    cooldown: int = 60
    max_attempts: int = 5
    email_hour_limit: int = 5
    ip_hour_limit: int = 20
    global_hour_limit: int = 500

    def __post_init__(self):
        if self.environment not in ('production','test','development'):
            raise ValueError('Invalid email policy')
        for name in ('ttl','max_attempts','email_hour_limit','ip_hour_limit','global_hour_limit'):
            if type(getattr(self,name)) is not int or getattr(self,name)<=0:
                raise ValueError('Invalid email policy')
        if type(self.cooldown) is not int or self.cooldown<0 or self.ttl>600:
            raise ValueError('Invalid email policy')


class EmailService:
    def __init__(self, store, provider, keys, *, policy=None, clock=None, observer=None):
        self.store, self.db, self.lock = store, store.db, store.lock
        self.provider, self.keys = provider, keys
        self.policy, self.clock = policy or EmailPolicy(), clock or time.time
        self.observe = observer or (lambda phase:None)
        self.repo = ActivityStore(self.db)
        if self.policy.environment=='production' and getattr(provider,'kind',None)!='aliyun_directmail':
            raise ValueError('Production requires the real DirectMail transport')
        from .migrations import status
        if not any(e['version']=='003_invite50_registration_details' for e in status(self.db).get('extensions',[])):
            raise ValueError('Invitation/profile migration must be applied explicitly')

    @staticmethod
    def _opaque(value):
        if not isinstance(value,str) or not re.fullmatch(r'[0-9a-f]{32}',value):
            raise EmailError('invalid_request')
        return value

    def _invite(self, token):
        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):
            raise EmailError('invitation_rejected',403)
        hashed = digest(token)
        row = self.db.execute('SELECT i.expires,i.revoked_at,l.used_count,l.max_uses FROM invites i JOIN invitation_limits l ON l.token=i.token WHERE i.token=?',(hashed,)).fetchone()
        if not row or row['expires']<=self.clock() or row['revoked_at'] is not None:
            raise EmailError('invitation_rejected',403)
        if row['used_count']>=row['max_uses']:raise EmailError('invitation_full',403)
        return hashed

    def invitation(self, token):
        with self.lock:
            try:
                hashed=self._invite(token)
                q=self.db.execute('SELECT max_uses,used_count FROM invitation_limits WHERE token=?',(hashed,)).fetchone()
                return {'valid':True,'max_uses':q['max_uses'],'used_count':q['used_count'],'remaining':q['max_uses']-q['used_count']}
            except EmailError:
                return {'valid':False}

    def _digest(self, kid, identity, email, purpose, invite, code):
        return self.keys.digest(kid,'email-otp-v1',identity,email,purpose,invite,code)

    @staticmethod
    def _public(row):
        return {'accepted':True,'verification_id':row['id'],'expires_at':row['expires_at']}

    def send(self, *, email, purpose, request_id, invite=None, ip='unknown'):
        email=normalize_email(email);self._opaque(request_id)
        if purpose not in ('register','login') or (purpose=='login' and invite is not None):
            raise EmailError('invalid_request')
        code=f'{secrets.randbelow(1000000):06d}';identity=uuid.uuid4().hex;kid=self.keys.active
        ip_tag=self.keys.digest(kid,'email-ip-v1',str(ip)).hex()
        with self.lock, transaction(self.db):
            hashed=self._invite(invite) if purpose=='register' else None
            previous=self.db.execute('SELECT * FROM email_challenges WHERE request_id=?',(request_id,)).fetchone()
            if previous:
                if (previous['email'],previous['purpose'],previous['invite_token'])!=(email,purpose,hashed):
                    raise EmailError('request_conflict',409)
                if previous['state'] in ('sending','sent','suppressed'):
                    return self._public(previous)
                raise EmailError('send_unavailable',503)
            now=self.clock()
            latest=self.db.execute('SELECT MAX(created_at) FROM email_challenges WHERE email=?',(email,)).fetchone()[0]
            if latest is not None and now-latest<self.policy.cooldown:
                raise EmailError('rate_limited',429,max(1,int(self.policy.cooldown-(now-latest))+1))
            checks=[('email=?',(email,),self.policy.email_hour_limit),
                    ('ip_tag=?',(ip_tag,),self.policy.ip_hour_limit),('1=1',(),self.policy.global_hour_limit)]
            for clause,args,limit in checks:
                count=self.db.execute('SELECT COUNT(*) FROM email_challenges WHERE '+clause+' AND created_at>?',(*args,now-3600)).fetchone()[0]
                if count>=limit:
                    raise EmailError('rate_limited',429,3600)
            user=self.db.execute('SELECT u.id FROM email_identities e JOIN users u ON u.id=e.user_id WHERE e.email=? AND u.disabled=0',(email,)).fetchone() if purpose=='login' else None
            suppressed=purpose=='login' and user is None
            self.db.execute("UPDATE email_challenges SET state='revoked' WHERE email=? AND purpose=? AND state IN ('sending','sent')",(email,purpose))
            self.db.execute('INSERT INTO email_challenges(id,email,purpose,invite_token,bound_uid,key_id,code_digest,request_id,ip_tag,state,max_attempts,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (identity,email,purpose,hashed,user['id'] if user else None,kid,self._digest(kid,identity,email,purpose,hashed,code),request_id,ip_tag,'suppressed' if suppressed else 'sending',self.policy.max_attempts,now,now+self.policy.ttl))
        if not suppressed:
            try:
                ack=self.provider.send(email,code,purpose)
                state='sent';ref=ack.get('request_id')
            except MailError as exc:
                state='unknown' if exc.code in ('timeout','unavailable') else 'failed';ref=None
            except Exception:
                state='unknown';ref=None
            with self.lock,transaction(self.db):
                self.db.execute("UPDATE email_challenges SET state=?,provider_ref=? WHERE id=? AND state='sending'",(state,ref,identity))
            if state!='sent':
                raise EmailError('send_unavailable',503)
        return {'accepted':True,'verification_id':identity,'expires_at':now+self.policy.ttl}

    def _proof(self, *, email, purpose, verification_id, code, invite_token=None):
        row=self.db.execute('SELECT * FROM email_challenges WHERE id=?',(verification_id,)).fetchone()
        if not row or (row['email'],row['purpose'],row['invite_token'])!=(email,purpose,invite_token):
            return None
        if row['state']!='sent' or row['expires_at']<=self.clock() or row['attempts']>=row['max_attempts']:
            return None
        valid=row['key_id'] in self.keys.keys and hmac.compare_digest(row['code_digest'],self._digest(row['key_id'],row['id'],email,purpose,invite_token,code))
        if not valid:
            self.db.execute("UPDATE email_challenges SET attempts=attempts+1,state=CASE WHEN attempts+1>=max_attempts THEN 'revoked' ELSE state END WHERE id=?",(row['id'],))
            return None
        return row

    def _consume(self, row, uid):
        now=self.clock()
        if self.db.execute("UPDATE email_challenges SET state='consumed',consumed_at=?,consumed_by=? WHERE id=? AND state='sent' AND expires_at>? AND attempts<max_attempts",(now,uid,row['id'],now)).rowcount!=1:
            raise EmailError('verification_rejected',403)

    def _fields(self, email, verification_id, code):
        email=normalize_email(email);self._opaque(verification_id)
        if not isinstance(code,str) or not re.fullmatch(r'[0-9]{6}',code):
            raise EmailError('invalid_request')
        return email

    def register(self, data):
        required={'username','organization','research_area','gender','age','email','invite','verification_id','code','request_id','password','confirm_password'}
        if not isinstance(data,dict) or set(data)!=required or any(not isinstance(v,str) for k,v in data.items() if k!='age') or type(data['age']) is not int:
            raise EmailError('invalid_request')
        email=self._fields(data['email'],data['verification_id'],data['code']);self._opaque(data['request_id'])
        try:
            self.store.validate_user_identity(data['username'])
        except ValueError:
            raise EmailError('invalid_request') from None
        organization=data['organization'].strip()
        if not 1<=len(organization)<=200 or re.search(r'[\x00-\x1f\x7f]',organization):
            raise EmailError('organization_required')
        research=data['research_area'].strip()
        if not 1<=len(research)<=200 or re.search(r'[\x00-\x1f\x7f]',research):raise EmailError('research_area_required')
        if data['gender'] not in ('male','female'):raise EmailError('gender_required')
        if not 1<=data['age']<=120:raise EmailError('invalid_age')
        encoded=self._password(data['password'],data['confirm_password']);result=None
        with self.lock,transaction(self.db):
            identity_digest=self.keys.digest(self.keys.active,'email-registration-password-v1',email,data['username'],organization,research,data['gender'],data['age'],digest(data['invite']),data['verification_id'],data['password'])
            previous=self.db.execute('SELECT * FROM invite_redemptions WHERE registration_request_id=?',(data['request_id'],)).fetchone()
            if previous:
                comparison=identity_digest
                if previous['identity_format']!=2:raise EmailError('registration_conflict',409)
                if previous['email_challenge_id'] is None or previous['identity_digest'] is None or not hmac.compare_digest(previous['identity_digest'],comparison):
                    raise EmailError('registration_conflict',409)
                # Idempotent business retry never reuses an OTP to issue a new Session.
                return {'result':RegistrationResult(previous['user_id'],data['username'],False),'session':None}
            hashed=self._invite(data['invite'])
            row=self._proof(email=email,purpose='register',verification_id=data['verification_id'],code=data['code'],invite_token=hashed)
            if row:
                if self.db.execute('SELECT 1 FROM users WHERE username=?',(data['username'],)).fetchone() or self.db.execute('SELECT 1 FROM email_identities WHERE email=?',(email,)).fetchone():
                    raise EmailError('registration_conflict',409)
                now=self.clock();uid=self.store.create_user_in_transaction(self.db,data['username'],encoded)
                self.repo.create_profile(uid,organization=organization,registered_at=now,now=now)
                self.db.execute('INSERT INTO registration_details VALUES (?,?,?,?,?)',(uid,research,data['gender'],data['age'],now))
                self.db.execute('INSERT INTO email_identities VALUES (?,?,?,?)',(uid,email,now,now))
                self.observe('identity_created')
                if not self.repo.mark_invite_used(hashed,now=now):
                    raise EmailError('invitation_rejected',403)
                self.repo.record_invite_use(hashed,uid,used_at=now,registration_request_id=data['request_id'],email_challenge_id=row['id'],request_digest=identity_digest,request_key_id=self.keys.active,identity_format=2)
                self._consume(row,uid)
                self.repo.insert_event('registration_completed',user_id=uid,object_type='user',object_id=uid,occurred_at=now,idempotency_key='registration:'+uid,metadata={'channel':'invite','profile_present':True})
                self.observe('before_commit');result=RegistrationResult(uid,data['username'],True)
        if result is None:
            raise EmailError('verification_rejected',403)  # Wrong-code counter already committed.
        try:
            session=self.store.create_session(result.user_id,password_snapshot=encoded)
        except Exception:
            session=None  # Account exists; recover with a NEW email-login challenge.
        return {'result':result,'session':session}

    def login(self, *, email, verification_id, code):
        email=self._fields(email,verification_id,code);session=None
        with self.lock,transaction(self.db):
            row=self._proof(email=email,purpose='login',verification_id=verification_id,code=code)
            if row:
                user=self.db.execute('SELECT u.id FROM email_identities e JOIN users u ON u.id=e.user_id WHERE e.email=? AND u.id=? AND u.disabled=0',(email,row['bound_uid'])).fetchone()
                if user:
                    self._consume(row,user['id'])
                    session=self.store.create_session_in_transaction(self.db,user['id'])
                    self.repo.insert_event('login_succeeded',user_id=user['id'],object_type='auth_attempt',object_id=row['id'],occurred_at=self.clock(),idempotency_key='email-login:'+row['id'],metadata={'method':'email_otp','attempt_id':row['id']})
                    self.observe('before_commit')
        if session is None:
            raise EmailError('verification_rejected',403)
        return session

    @staticmethod
    def _password(password, confirm_password):
        if not isinstance(password,str) or not 12<=len(password)<=256:
            raise EmailError('invalid_password')
        if not isinstance(confirm_password,str) or not hmac.compare_digest(password.encode(),confirm_password.encode()):
            raise EmailError('password_mismatch')
        return password_hash(password)

    def reset_password(self, *, email, verification_id, code, password, confirm_password, expected_uid=None):
        email=self._fields(email,verification_id,code)
        encoded=self._password(password,confirm_password);uid=None
        with self.lock,transaction(self.db):
            row=self._proof(email=email,purpose='login',verification_id=verification_id,code=code)
            if row:
                user=self.db.execute('SELECT u.id FROM email_identities e JOIN users u ON u.id=e.user_id WHERE e.email=? AND u.id=? AND u.disabled=0',(email,row['bound_uid'])).fetchone()
                if user:
                    if expected_uid is not None and expected_uid!=user['id']:
                        raise EmailError('account_changed',409)
                    uid=user['id'];self._consume(row,uid)
                    self.db.execute('UPDATE users SET password=? WHERE id=? AND disabled=0',(encoded,uid))
                    self.db.execute('DELETE FROM auth WHERE uid=?',(uid,))
                    self.db.execute("UPDATE email_challenges SET state='revoked' WHERE email=? AND purpose='login' AND state IN ('sending','sent')",(email,))
                    self.observe('password_updated')
                    self.observe('before_commit')
        if uid is None:raise EmailError('verification_rejected',403)
        return uid

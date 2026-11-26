"""Advisory invitation/OTP prechecks. Final consumption belongs ONLY to P2.2.

Invitation validation is advisory; final invitation eligibility and consumption
must be checked atomically during P2.2 registration.
"""
from collections import Counter
from enum import Enum
from threading import Lock
import hmac
import re
import secrets
import sqlite3
import time
import uuid

from .activity_store import ActivityStore
from .migrations import status, transaction
from .store import digest
from .verification_policy import Settings, normalize_phone
from .sms_provider import DisabledProvider, UnconfiguredProvider, SendContext


class InvitationState(str,Enum):
    VALID='valid'
    INVALID='invalid'
    EXPIRED='expired'
    ALREADY_USED='already_used'
    REVOKED='revoked'


class ServiceError(Exception):
    def __init__(self,code,http_status,retry_after=None):
        super().__init__(code)
        self.code,self.http_status,self.retry_after=code,http_status,retry_after


class VerificationService:
    def __init__(self,store,*,settings=None,keys=None,provider=None,clock=time.time):
        self.store=store;self.db=store.db;self.lock=store.lock
        self.settings=settings or Settings();self.keys=keys;self.clock=clock
        self.provider=provider or (DisabledProvider() if self.settings.mode=='disabled' else UnconfiguredProvider())
        if self.provider.mode!=self.settings.mode:
            raise ValueError('Provider and verification mode do not match')
        if self.settings.mode!='disabled' and keys is None:
            raise ValueError('A private verification key ring is required')
        if self.settings.mode!='disabled':
            with self.lock:
                if status(self.db)['state']!='applied':raise ValueError('Explicit P1.2 migration is required')
        self.repo=ActivityStore(self.db)
        self._edge_lock=Lock();self._edge={};self._health=Counter()

    def __repr__(self):
        return 'VerificationService(<private configuration>)'

    def invitation_state(self,token,*,connection=None,now=None):
        """Pure read. No validated state is persisted, no invitation is reserved."""
        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):
            return InvitationState.INVALID
        db=connection or self.db;now=self.clock() if now is None else now
        with self.lock:
            # Old non-migrated app exposes new endpoints only as disabled (503).
            row=db.execute('SELECT expires,used,revoked_at FROM invites WHERE token=?',(digest(token),)).fetchone()
        if not row:return InvitationState.INVALID
        if row[2] is not None:return InvitationState.REVOKED
        if row[1]:return InvitationState.ALREADY_USED
        if row[0] is None or now>=row[0]:return InvitationState.EXPIRED
        return InvitationState.VALID

    def edge_check(self,ip):
        """Extra single-broker abuse guard, not the durable SMS send quota."""
        now=time.monotonic();key=ip
        with self._edge_lock:
            self._edge={k:[t for t in v if now-t<self.settings.edge_window] for k,v in self._edge.items() if v and now-v[-1]<self.settings.edge_window}
            if len(self._edge)>=self.settings.edge_buckets or len(self._edge.get(key,[]))>=self.settings.edge_limit:
                raise ServiceError('rate_limited',429,self.settings.edge_window)
            self._edge.setdefault(key,[]).append(now)

    def _enabled(self):
        if self.settings.mode=='disabled' or isinstance(self.provider,UnconfiguredProvider):
            raise ServiceError('sms_unavailable',503)

    def _normalize(self,value):
        try:return normalize_phone(value,self.settings)
        except ValueError:raise ServiceError('invalid_request',400) from None

    def _context_digest(self,key_id,token,phone,request_id):
        return self.keys.digest(key_id,'sms-request-v1',digest(token),phone,'register',request_id)

    def _code_digest(self,key_id,verification_id,token,phone,request_id,code):
        return self.keys.digest(key_id,'sms-code-v1',verification_id,phone,'register',None,digest(token),request_id,code)

    def _key_coverage(self,now):
        recent={r[0] for r in self.db.execute('SELECT DISTINCT bucket_key_id FROM sms_verifications WHERE created_at>=?',(now-self.settings.window,))}
        if recent-set(self.keys.keys):raise ServiceError('sms_unavailable',503)

    def _response(self,row):
        # Same response for bound phone/provider failure; never claim SMS delivery.
        return {'status':'accepted','verification_id':row['verification_id'],'expires_at':row['expires_at'], 'advisory':True}

    def send(self,token,phone_number,request_id,ip):
        def authorize(now):
            if self.invitation_state(token,now=now)!=InvitationState.VALID:
                raise ServiceError('verification_unavailable',403)
        return self._send_challenge(phone_number,request_id,ip,purpose='register',bound_user_id=None,authorize=authorize,
            request_digest=lambda kid,phone,request:self._context_digest(kid,token,phone,request),
            code_digest=lambda kid,vid,phone,request,code:self._code_digest(kid,vid,token,phone,request,code))

    def _profile_context_digest(self,key_id,user_id,phone,request_id,context_id,session_tag):
        return self.keys.digest(key_id,'profile-sms-request-v1',user_id,phone,'phone_change',request_id,context_id,session_tag)

    def _profile_code_digest(self,key_id,verification_id,user_id,phone,request_id,context_id,session_tag,code):
        return self.keys.digest(key_id,'profile-sms-code-v1',verification_id,user_id,phone,'phone_change',request_id,context_id,session_tag,code)

    def send_for_profile(self,phone_number,request_id,ip,*,user_id,context_id,session_tag,authorize):
        # Trusted authenticated caller supplies authorization; no anonymous route uses this.
        return self._send_challenge(phone_number,request_id,ip,purpose='phone_change',bound_user_id=user_id,authorize=authorize,
            request_digest=lambda kid,phone,request:self._profile_context_digest(kid,user_id,phone,request,context_id,session_tag),
            code_digest=lambda kid,vid,phone,request,code:self._profile_code_digest(kid,vid,user_id,phone,request,context_id,session_tag,code))

    def _send_challenge(self,phone_number,request_id,ip,*,purpose,bound_user_id,authorize,request_digest,code_digest):
        self._enabled();phone=self._normalize(phone_number)
        if not isinstance(request_id,str) or not re.fullmatch(r'[0-9a-f]{32}',request_id):
            raise ServiceError('invalid_request',400)
        try:
            with self.lock,transaction(self.db):
                now=self.clock()
                authorize(now)
                self._key_coverage(now)
                old=self.repo._one('SELECT * FROM sms_verifications WHERE send_request_id=?',(request_id,))
                if old:
                    if old['key_id'] not in self.keys.keys or not hmac.compare_digest(old['request_digest'],request_digest(old['key_id'],phone,request_id)):
                        raise ServiceError('request_conflict',409)
                    return self._response(old)
                recent=self.repo._one('SELECT MAX(created_at) AS last,COUNT(*) AS total FROM sms_verifications WHERE phone_number=? AND created_at>=?',(phone,now-self.settings.window))
                if recent['last'] is not None and now-recent['last']<self.settings.cooldown:
                    raise ServiceError('rate_limited',429,self.settings.cooldown)
                buckets=[self.keys.digest(k,'sms-ip-v1',ip).hex() for k in self.keys.keys]
                count=self.db.execute('SELECT COUNT(*) FROM sms_verifications WHERE ip_bucket IN ('+','.join('?' for _ in buckets)+') AND created_at>=?',(*buckets,now-self.settings.window)).fetchone()[0]
                if recent['total']>=self.settings.phone_hour_limit or count>=self.settings.ip_hour_limit:
                    raise ServiceError('rate_limited',429,self.settings.window)
                verification_id=uuid.uuid4().hex
                code=str(secrets.randbelow(10**self.settings.digits)).zfill(self.settings.digits)
                key_id=self.keys.active
                self.repo.create_challenge(verification_id=verification_id,phone_number=phone,purpose=purpose,bound_user_id=bound_user_id,
                    code_digest=code_digest(key_id,verification_id,phone,request_id,code),key_id=key_id,send_request_id=request_id,
                    request_digest=request_digest(key_id,phone,request_id),ip_bucket=self.keys.digest(key_id,'sms-ip-v1',ip).hex(),bucket_key_id=key_id,
                    created_at=now,expires_at=now+self.settings.ttl,max_attempts=self.settings.attempts)
                suppressed=self.repo.profile_by_phone(phone) is not None
                row=self.repo.challenge(verification_id)
        except sqlite3.Error:
            raise ServiceError('sms_unavailable',503) from None
        # No lock or SQLite transaction across this external boundary.
        state='failed';failure='unavailable';provider_ref=None
        if not suppressed:
            try:
                result=self.provider.send_verification_code(phone,code,SendContext(verification_id,request_id,self.settings.provider_timeout))
                state={'accepted':'sent','rejected':'failed','unknown':'unknown'}.get(result.state,'unknown')
                failure=None if state=='sent' else ('rejected' if state=='failed' else 'unknown')
                provider_ref=result.provider_ref
                # Do not persist a provider's reflected OTP, phone or arbitrary text.
                if provider_ref is not None and (not isinstance(provider_ref,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',provider_ref) or code in provider_ref or phone.lstrip('+') in provider_ref):
                    provider_ref=None
            except TimeoutError:
                state='unknown';failure='timeout'
            except Exception:
                # Intentionally discard external exception text/traceback/locals.
                state='unknown';failure='unknown'
        try:
            with self.lock,transaction(self.db):
                self.repo.set_send_result(verification_id,state=state,now=self.clock(),provider_ref=provider_ref,failure_code=failure)
        except Exception:
            # Durable pending is ineligible. Same request never re-sends after this failure.
            self._health['acknowledgment_failed']+=1
        finally:
            code=None
        return self._response(row)

    def inspect_registration(self,connection,*,token,phone_number,verification_id,code):
        """Caller-owned transaction precheck for P2.2; does not consume or commit.

        False after a wrong code can update attempt_count. Caller must commit that
        failure counter separately from any rolled-back account creation work.
        A prior True or public advisory response is never a registration credential.
        """
        if connection is not self.db or not connection.in_transaction:
            raise RuntimeError('Explicit transaction on the service connection is required')
        if not isinstance(verification_id,str) or not re.fullmatch(r'[0-9a-f]{32}',verification_id) or not isinstance(code,str) or not re.fullmatch(r'[0-9]{'+str(self.settings.digits)+'}',code):
            raise ServiceError('invalid_request',400)
        phone=self._normalize(phone_number);now=self.clock()
        if self.invitation_state(token,connection=connection,now=now)!=InvitationState.VALID:return False
        row=self.repo.applicable_challenge(phone,'register',now=now)
        if row is None or row['verification_id']!=verification_id or row['key_id'] not in self.keys.keys:return False
        if not hmac.compare_digest(row['request_digest'],self._context_digest(row['key_id'],token,phone,row['send_request_id'])):return False
        if self.repo.profile_by_phone(phone) is not None:return False
        expected=self._code_digest(row['key_id'],verification_id,token,phone,row['send_request_id'],code)
        if hmac.compare_digest(row['code_digest'],expected):return True
        self.repo.increment_attempts(verification_id,phone_number=phone,purpose='register',now=now)
        return False

    def verify(self,token,phone_number,verification_id,code,*,purpose='register'):
        self._enabled()
        if purpose!='register' or not isinstance(verification_id,str) or not re.fullmatch(r'[0-9a-f]{32}',verification_id) or not isinstance(code,str) or not re.fullmatch(r'[0-9]{'+str(self.settings.digits)+'}',code):
            raise ServiceError('invalid_request',400)
        try:
            with self.lock,transaction(self.db):
                valid=self.inspect_registration(self.db,token=token,phone_number=phone_number,verification_id=verification_id,code=code)
                # Return normally so a wrong attempt counter COMMITs, not rollbacks.
            return {'valid':valid,'advisory':True}
        except sqlite3.Error:
            raise ServiceError('verification_unavailable',503) from None

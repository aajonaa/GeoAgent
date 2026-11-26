"""Single-database registration unit of work; authentication begins AFTER commit."""
from dataclasses import dataclass
from pathlib import Path
import hmac
import json
import re
import sqlite3

from .activity_store import ActivityStore
from .migrations import transaction
from .store import digest, password_hash
from .verification_policy import normalize_phone
from .verification_service import InvitationState, ServiceError


@dataclass(frozen=True)
class RegistrationPolicy:
    mode: str = 'disabled'
    environment: str = 'production'
    retry_seconds: int = 86400
    body_limit: int = 4096

    def __post_init__(self):
        if self.mode not in ('disabled','invite_sms') or self.environment not in ('production','development','test'):
            raise ValueError('Invalid registration policy')
        if type(self.retry_seconds) is not int or self.retry_seconds<=0 or type(self.body_limit) is not int or self.body_limit<=0:
            raise ValueError('Invalid registration policy')

    @classmethod
    def from_file(cls,path):
        try:return cls(**json.loads(Path(path).read_text(encoding='utf-8')))
        except Exception:raise ValueError('Invalid registration policy file') from None


class RegistrationError(Exception):
    def __init__(self,code,http_status):
        super().__init__(code);self.code=code;self.http_status=http_status


@dataclass(frozen=True)
class RegistrationResult:
    user_id: str
    username: str
    created: bool


class RegistrationService:
    def __init__(self,store,verification,*,policy=None,observer=None):
        self.store=store;self.db=store.db;self.lock=store.lock
        self.verification=verification;self.policy=policy or RegistrationPolicy()
        self.repo=ActivityStore(self.db);self.observe=observer or (lambda phase:None)
        if verification is not None and (verification.store is not store or verification.db is not self.db):
            raise ValueError('Registration and verification must share Store.db')
        databases=[r for r in self.db.execute('PRAGMA database_list') if r[1]!='temp']
        if len(databases)!=1 or databases[0][1]!='main':
            raise ValueError('Registration requires one SQLite main database')

    def ensure_enabled(self):
        if self.policy.mode=='disabled':raise RegistrationError('registration_disabled',403)
        v=self.verification
        if v is None or v.settings.environment!=self.policy.environment:
            raise RegistrationError('registration_unavailable',503)
        if self.policy.environment=='production' and v.settings.mode!='provider':
            raise RegistrationError('registration_unavailable',503)
        try:v._enabled()
        except ServiceError:raise RegistrationError('registration_unavailable',503) from None

    def validate(self,data):
        required={'username','password','organization','phone','invite','verification_id','code','request_id'}
        if not isinstance(data,dict) or set(data)!=required or any(not isinstance(v,str) for v in data.values()):
            raise RegistrationError('invalid_request',400)
        try:
            self.store.validate_user_identity(data['username'])
            if not 12<=len(data['password'])<=256:raise ValueError()
            organization=data['organization'].strip()
            if not 1<=len(organization)<=200 or re.search(r'[\x00-\x1f\x7f]',organization):raise ValueError()
            phone=normalize_phone(data['phone'],self.verification.settings)
            if not re.fullmatch(r'[A-Za-z0-9_-]{43}',data['invite']):raise ValueError()
            if not re.fullmatch(r'[0-9a-f]{32}',data['verification_id']) or not re.fullmatch(r'[0-9a-f]{32}',data['request_id']):raise ValueError()
            if not re.fullmatch(r'[0-9]{'+str(self.verification.settings.digits)+'}',data['code']):raise ValueError()
        except ValueError:raise RegistrationError('invalid_request',400) from None
        return {**data,'organization':organization,'phone':phone}

    def _identity_digest(self,key_id,data):
        # Noncredential identity only. Replays never replace a password; login verifies it.
        return self.verification.keys.digest(key_id,'registration-identity-v1',digest(data['invite']),data['username'],data['organization'],data['phone'],data['verification_id'],data['request_id'])

    def _replay(self,data,now):
        row=self.repo._one('SELECT * FROM invite_uses WHERE registration_request_id=?',(data['request_id'],))
        if row is None:return None
        if (row['invite_token']!=digest(data['invite']) or row['verification_id']!=data['verification_id']
            or row['retry_expires_at'] is None or now>=row['retry_expires_at']
            or row['request_key_id'] not in self.verification.keys.keys or row['request_digest'] is None
            or not hmac.compare_digest(row['request_digest'],self._identity_digest(row['request_key_id'],data))):
            raise RegistrationError('registration_conflict',409)
        user=self.db.execute('SELECT username FROM users WHERE id=?',(row['user_id'],)).fetchone()
        if user is None or user[0]!=data['username']:raise RegistrationError('registration_conflict',409)
        return RegistrationResult(row['user_id'],user[0],False)

    def register(self,data):
        """Creates facts, not a Session. Wrong-code counter has a normal commit path."""
        self.ensure_enabled();data=self.validate(data)
        # CPU work outside Store.lock and the SQLite writer transaction.
        encoded=password_hash(data['password'])
        result=None;rejected=False
        try:
            with self.lock,transaction(self.db):
                now=self.verification.clock()
                result=self._replay(data,now)
                if result is None:
                    valid=self.verification.inspect_registration(self.db,token=data['invite'],phone_number=data['phone'],verification_id=data['verification_id'],code=data['code'])
                    if not valid:
                        # Do not raise within this context: wrong attempts must survive.
                        rejected=True
                    else:
                        if self.db.execute('SELECT 1 FROM users WHERE username=?',(data['username'],)).fetchone() or self.repo.profile_by_phone(data['phone']) is not None:
                            raise RegistrationError('registration_conflict',409)
                        now=self.verification.clock()
                        self.observe('verified')
                        uid=self.store.create_user_in_transaction(self.db,data['username'],encoded)
                        self.observe('user_created')
                        self.repo.create_profile(uid,now=now,organization=data['organization'],phone_number=data['phone'],phone_verified_at=now,registered_at=now)
                        self.observe('profile_created')
                        # CAS invitation consumption, no unconditional legacy UPDATE.
                        if not self.repo.mark_invite_used(digest(data['invite']),now=self.verification.clock()):
                            raise RegistrationError('registration_rejected',403)
                        self.observe('invitation_consumed')
                        key_id=self.verification.keys.active
                        self.repo.record_invite_use(digest(data['invite']),uid,used_at=now,registration_request_id=data['request_id'],verification_id=data['verification_id'],request_digest=self._identity_digest(key_id,data),request_key_id=key_id,retry_expires_at=now+self.policy.retry_seconds)
                        self.observe('invitation_use_created')
                        if not self.repo.mark_consumed(data['verification_id'],uid,phone_number=data['phone'],purpose='register',now=self.verification.clock()):
                            raise RegistrationError('registration_rejected',403)
                        self.observe('sms_consumed')
                        self.repo.insert_event('registration_completed',user_id=uid,object_type='user',object_id=uid,occurred_at=now,idempotency_key='registration:'+uid,metadata={'channel':'invite','profile_present':True})
                        self.observe('event_created')
                        # FK/UNIQUE constraints, CAS rowcounts and same-connection writes
                        # protect all six facts; no network/files/model work in this block.
                        result=RegistrationResult(uid,data['username'],True)
                        self.observe('before_commit')
            if rejected:raise RegistrationError('registration_rejected',403)
        except sqlite3.IntegrityError:
            raise RegistrationError('registration_conflict',409) from None
        except sqlite3.Error:
            raise RegistrationError('registration_unavailable',503) from None
        except ServiceError:
            raise RegistrationError('registration_rejected',403) from None
        self.observe('after_commit')
        return result

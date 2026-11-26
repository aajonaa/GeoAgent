"""Small trusted persistence adapter, not an HTTP/authentication/business service.

Pass Store.db while holding Store.lock, or an explicitly owned test connection.
Caller owns transaction, authentication, HMAC verification, send limits and policy.
No method commits, creates a connection or automatically migrates the database.
"""
import json
import math
import re
import uuid


def timestamp(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError('A finite UTC Unix timestamp is required')
    return float(value)


def phone(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r'\+[0-9 ()-]+', value):
        raise ValueError('Explicit international phone format is required')
    value = re.sub(r'[ ()-]', '', value)
    if not re.fullmatch(r'\+[1-9][0-9]{1,14}', value):
        raise ValueError('Invalid international phone shape')
    return value


def digest_bytes(value):
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError('A 32-byte keyed digest is required')
    return value


def opaque(value, *, hex_length=None):
    pattern = r'[0-9a-f]{' + str(hex_length) + '}' if hex_length else r'[A-Za-z0-9_.:-]{1,200}'
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError('Invalid opaque identifier')
    return value


class ActivityStore:
    def __init__(self, connection):
        if connection.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
            raise ValueError('Foreign key enforcement is required')
        self.db = connection
        self.multi_invite = bool(connection.execute("SELECT 1 FROM sqlite_master WHERE name='invitation_limits' AND type='table'").fetchone())

    def _write(self):
        if not self.db.in_transaction:
            raise RuntimeError('Caller must own an explicit transaction')
        if self.db.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
            raise RuntimeError('Foreign key enforcement is required')

    def _one(self, sql, args):
        cursor = self.db.execute(sql, args)
        row = cursor.fetchone()
        return dict(zip((c[0] for c in cursor.description), row)) if row is not None else None

    def profile(self, user_id):
        return self._one('SELECT * FROM user_profiles WHERE user_id=?', (user_id,))

    def profile_by_phone(self, value):
        value = phone(value)
        if value is None:
            return None
        return self._one('SELECT * FROM user_profiles WHERE phone_number=? AND phone_verified_at IS NOT NULL', (value,))

    @staticmethod
    def _profile_values(organization, phone_number, phone_verified_at):
        if organization is not None:
            if not isinstance(organization, str) or len(organization) > 200:
                raise ValueError('Invalid organization')
            organization = organization.strip() or None
        number = phone(phone_number)
        verified = timestamp(phone_verified_at) if phone_verified_at is not None else None
        if (number is None) != (verified is None):
            raise ValueError('Only verified phone numbers belong in a profile')
        return organization, number, verified

    def create_profile(self, user_id, *, now, organization=None, phone_number=None,
                       phone_verified_at=None, registered_at=None):
        self._write()
        organization, number, verified = self._profile_values(organization, phone_number, phone_verified_at)
        now = timestamp(now)
        registered = timestamp(registered_at) if registered_at is not None else None
        self.db.execute('INSERT INTO user_profiles(user_id,organization,phone_number,phone_verified_at,'
                        'registered_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
                        (user_id, organization, number, verified, registered, now, now))

    def update_profile(self, user_id, *, now, **changes):
        self._write()
        if not changes or set(changes) - {'organization', 'phone_number', 'phone_verified_at'}:
            raise ValueError('Unsupported profile fields')
        current = self.profile(user_id)
        if current is None:
            raise KeyError('Profile not found')
        current.update(changes)
        organization, number, verified = self._profile_values(current['organization'], current['phone_number'], current['phone_verified_at'])
        # Replacing a number must explicitly provide its own verification timestamp.
        if 'phone_number' in changes and number != self.profile(user_id)['phone_number'] and 'phone_verified_at' not in changes:
            raise ValueError('New phone verification evidence is required')
        self.db.execute('UPDATE user_profiles SET organization=?,phone_number=?,phone_verified_at=?,updated_at=? WHERE user_id=?',
                        (organization, number, verified, timestamp(now), user_id))

    def bind_profile_phone(self, user_id, *, phone_number, now):
        """First verified number only. Caller owns writer transaction and HMAC checks."""
        self._write()
        number = phone(phone_number)
        if number is None:
            raise ValueError('A verified phone is required')
        when = timestamp(now)
        if self.profile(user_id) is None:
            self.create_profile(user_id, now=when, phone_number=number, phone_verified_at=when)
            return True
        return self.db.execute('UPDATE user_profiles SET phone_number=?,phone_verified_at=?,updated_at=? '
                               'WHERE user_id=? AND phone_number IS NULL AND phone_verified_at IS NULL',
                               (number, when, when, user_id)).rowcount == 1

    def mark_invite_used(self, invite_token, *, now):
        self._write()
        if self.multi_invite:
            changed=self.db.execute('UPDATE invitation_limits SET used_count=used_count+1 WHERE token=? AND used_count<max_uses AND EXISTS (SELECT 1 FROM invites i WHERE i.token=invitation_limits.token AND i.expires>? AND i.revoked_at IS NULL)',(invite_token,timestamp(now))).rowcount==1
            if changed:
                self.db.execute('UPDATE invites SET used=(SELECT used_count>=max_uses FROM invitation_limits WHERE token=?) WHERE token=?',(invite_token,invite_token))
            return changed
        return self.db.execute('UPDATE invites SET used=1 WHERE token=? AND used=0 '
                               'AND expires>? AND revoked_at IS NULL', (invite_token, timestamp(now))).rowcount == 1

    def record_invite_use(self, invite_token, user_id, *, used_at, registration_request_id,
                          verification_id=None, request_digest=None, request_key_id=None, retry_expires_at=None,
                          email_challenge_id=None, identity_format=0):
        self._write()
        if request_digest is not None:
            digest_bytes(request_digest)
        if self.multi_invite:
            self.db.execute('INSERT INTO invite_redemptions(registration_request_id,invite_token,user_id,used_at,verification_id,identity_digest,request_key_id,retry_expires_at,email_challenge_id,identity_format) VALUES (?,?,?,?,?,?,?,?,?,?)',
                (opaque(registration_request_id),invite_token,user_id,timestamp(used_at),verification_id,request_digest,request_key_id,retry_expires_at,email_challenge_id,identity_format))
            return
        self.db.execute('INSERT INTO invite_uses(invite_token,user_id,used_at,registration_request_id,'
                        'verification_id,request_digest,request_key_id,retry_expires_at) VALUES (?,?,?,?,?,?,?,?)',
                        (invite_token, user_id, timestamp(used_at), opaque(registration_request_id), verification_id,
                         request_digest, request_key_id, timestamp(retry_expires_at) if retry_expires_at is not None else None))

    def invite_use(self, invite_token):
        if self.multi_invite:
            return self._one('SELECT *,identity_digest AS request_digest FROM invite_redemptions WHERE invite_token=? ORDER BY used_at LIMIT 1',(invite_token,))
        return self._one('SELECT * FROM invite_uses WHERE invite_token=?', (invite_token,))

    def invite_use_by_user(self, user_id):
        if self.multi_invite:
            return self._one('SELECT *,identity_digest AS request_digest FROM invite_redemptions WHERE user_id=?',(user_id,))
        return self._one('SELECT * FROM invite_uses WHERE user_id=?', (user_id,))

    def create_challenge(self, *, verification_id, phone_number, purpose, bound_user_id,
                         code_digest, key_id, send_request_id, request_digest, ip_bucket,
                         bucket_key_id, created_at, expires_at, max_attempts):
        self._write()
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts <= 0:
            raise ValueError('Invalid attempt budget')
        self.db.execute('INSERT INTO sms_verifications(verification_id,phone_number,purpose,bound_user_id,'
                        'code_digest,key_id,send_request_id,request_digest,ip_bucket,bucket_key_id,send_state,'
                        'created_at,expires_at,max_attempts) VALUES (?,?,?,?,?,?,?,?,?,?,\'pending\',?,?,?)',
                        (opaque(verification_id, hex_length=32), phone(phone_number), purpose, bound_user_id,
                         digest_bytes(code_digest), opaque(key_id), opaque(send_request_id), digest_bytes(request_digest),
                         opaque(ip_bucket, hex_length=64), opaque(bucket_key_id), timestamp(created_at), timestamp(expires_at), max_attempts))

    def challenge(self, verification_id):
        # Trusted internal return includes HMAC, never expose this dict via an API.
        return self._one('SELECT * FROM sms_verifications WHERE verification_id=?', (verification_id,))

    def set_send_result(self, verification_id, *, state, now, provider_ref=None, failure_code=None):
        """Storage-only acknowledgment; never invokes or retries a provider."""
        self._write()
        if state not in ('sent', 'failed', 'unknown'):
            raise ValueError('Invalid send outcome')
        if provider_ref is not None:
            opaque(provider_ref)
        if failure_code is not None and failure_code not in ('rejected', 'timeout', 'unavailable', 'unknown'):
            raise ValueError('Only classified provider failures may be stored')
        now = timestamp(now)
        changed = self.db.execute('UPDATE sms_verifications SET send_state=?,sent_at=?,provider_ref=?,failure_code=? '
                               "WHERE verification_id=? AND send_state IN ('pending','unknown') AND consumed_at IS NULL",
                               (state, now if state == 'sent' else None, provider_ref, failure_code, verification_id)).rowcount == 1
        if changed and state == 'sent':
            row = self.challenge(verification_id)
            newest = self._one("SELECT MAX(seq) AS seq FROM sms_verifications WHERE phone_number=? AND purpose=? "
                               "AND bound_user_id IS ? AND send_state='sent'", (row['phone_number'], row['purpose'], row['bound_user_id']))['seq']
            self.db.execute('UPDATE sms_verifications SET revoked_at=? WHERE phone_number=? AND purpose=? '
                            'AND bound_user_id IS ? AND seq<? AND consumed_at IS NULL AND revoked_at IS NULL',
                            (now, row['phone_number'], row['purpose'], row['bound_user_id'], newest))
        return changed

    def applicable_challenge(self, phone_number, purpose, *, bound_user_id=None, now):
        # Select latest successful send first; never fall back to an older consumed/revoked code.
        row = self._one("SELECT * FROM sms_verifications WHERE phone_number=? AND purpose=? "
                        "AND bound_user_id IS ? AND send_state='sent' ORDER BY seq DESC LIMIT 1",
                        (phone(phone_number), purpose, bound_user_id))
        if row and row['revoked_at'] is None and row['consumed_at'] is None and row['attempt_count'] < row['max_attempts'] and row['sent_at'] <= timestamp(now) < row['expires_at']:
            return row
        return None

    def _applicable_id(self, verification_id, phone_number, purpose, bound_user_id, now):
        row = self.applicable_challenge(phone_number, purpose, bound_user_id=bound_user_id, now=now)
        return row is not None and row['verification_id'] == verification_id

    def increment_attempts(self, verification_id, *, phone_number, purpose, bound_user_id=None, now):
        self._write()
        if not self._applicable_id(verification_id, phone_number, purpose, bound_user_id, now):
            return False
        return self.db.execute('UPDATE sms_verifications SET attempt_count=attempt_count+1,'
                               'revoked_at=CASE WHEN attempt_count+1>=max_attempts THEN ? ELSE revoked_at END '
                               'WHERE verification_id=? AND consumed_at IS NULL AND revoked_at IS NULL AND attempt_count<max_attempts',
                               (timestamp(now), verification_id)).rowcount == 1

    def mark_consumed(self, verification_id, user_id, *, phone_number, purpose, bound_user_id=None, now):
        """Caller must verify the HMAC before requesting this transition (P2)."""
        self._write()
        if purpose == 'phone_change' and bound_user_id != user_id:
            return False
        if not self._applicable_id(verification_id, phone_number, purpose, bound_user_id, now):
            return False
        return self.db.execute("UPDATE sms_verifications SET consumed_at=?,consumed_by=? WHERE verification_id=? "
                               "AND consumed_at IS NULL AND revoked_at IS NULL AND send_state='sent' "
                               'AND expires_at>? AND attempt_count<max_attempts',
                               (timestamp(now), user_id, verification_id, timestamp(now))).rowcount == 1

    @staticmethod
    def _metadata(kind, metadata):
        shapes = {
            'registration_completed': {'channel': str, 'profile_present': bool},
            'login_succeeded': {'method': str, 'attempt_id': str},
            'login_failed': {'reason': str},
            'profile_updated': {'changed_fields': list, 'profile_was_absent': bool, 'phone_verified': bool},
            'file_downloaded': {'cid': str, 'generation': str, 'content_sha256': str, 'name_hmac': str, 'semantics': str},
            'stream_started': {'covered_from': float, 'semantics': str, 'writer_version': str},
            'retention_advanced': {'retained_from': float, 'reason': str, 'semantics': str},
        }
        if kind not in shapes or not isinstance(metadata, dict) or set(metadata) - set(shapes[kind]):
            raise ValueError('Unsupported event metadata')
        for key, value in metadata.items():
            expected = shapes[kind][key]
            if expected is float:
                timestamp(value)
            elif type(value) is not expected:
                raise ValueError('Invalid event metadata type')
            if key in ('cid', 'generation', 'attempt_id'):
                opaque(value, hex_length=32)
            elif key in ('content_sha256', 'name_hmac'):
                opaque(value, hex_length=64)
            elif key == 'changed_fields':
                if any(x not in ('organization', 'phone_number') for x in value):
                    raise ValueError('Invalid changed fields')
            elif expected is str:
                opaque(value)
        enums = {'channel': ('invite', 'local_admin'), 'method': ('password', 'email_otp'),
                 'reason': ('invalid_credentials', 'retention'), 'semantics': ('authorized_response_started', 'v1')}
        for key, values in enums.items():
            if key in metadata and metadata[key] not in values:
                raise ValueError('Unsupported metadata value')
        encoded = json.dumps(metadata, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        if len(encoded.encode()) > 2048:
            raise ValueError('Event metadata is too large')
        return encoded

    def insert_event(self, kind, *, user_id, object_type, object_id, occurred_at,
                     metadata=None, idempotency_key=None, event_id=None):
        self._write()
        objects = {'registration_completed': 'user', 'profile_updated': 'user',
                   'login_succeeded': 'auth_attempt', 'login_failed': 'auth_attempt',
                   'file_downloaded': 'file', 'stream_started': 'event_stream', 'retention_advanced': 'event_stream'}
        if objects.get(kind) != object_type:
            raise ValueError('Unsupported event object')
        if object_type == 'user' and object_id != user_id:
            raise ValueError('Event object does not match its subject')
        if object_type == 'event_stream':
            if object_id not in objects or user_id is not None:
                raise ValueError('Invalid coverage stream')
        elif object_id is not None:
            opaque(object_id, hex_length=64 if object_type == 'file' else 32)
        encoded = self._metadata(kind, metadata if metadata is not None else {})
        when = timestamp(occurred_at)
        key = opaque(idempotency_key) if idempotency_key is not None else None
        if key:
            previous = self._one('SELECT * FROM business_events WHERE kind=? AND idempotency_key=?', (kind, key))
            if previous:
                if (previous['user_id'], previous['object_type'], previous['object_id'], json.loads(previous['metadata'])) != (user_id, object_type, object_id, json.loads(encoded)):
                    raise ValueError('Idempotency key conflicts with a different event')
                return previous['event_id']
        identity = opaque(event_id, hex_length=32) if event_id else uuid.uuid4().hex
        self.db.execute('INSERT INTO business_events(event_id,kind,user_id,object_type,object_id,'
                        'occurred_at,idempotency_key,metadata_version,metadata) VALUES (?,?,?,?,?,?,?,1,?)',
                        (identity, kind, user_id, object_type, object_id, when, key, encoded))
        return identity

    def events(self, *, start, end, user_id=None, kind=None, limit=100):
        start, end = timestamp(start), timestamp(end)
        if end <= start or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('Invalid event query bounds')
        clauses, args = ['occurred_at>=?', 'occurred_at<?'], [start, end]
        if user_id is not None:
            clauses.append('user_id=?'); args.append(user_id)
        if kind is not None:
            clauses.append('kind=?'); args.append(kind)
        cursor = self.db.execute('SELECT * FROM business_events WHERE ' + ' AND '.join(clauses) + ' ORDER BY occurred_at,event_id LIMIT ?', [*args, limit])
        return [dict(zip((c[0] for c in cursor.description), row)) for row in cursor]

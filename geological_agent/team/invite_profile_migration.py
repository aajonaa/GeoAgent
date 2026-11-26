"""Additive 50-seat invitation and registration-details expansion."""
import hashlib
import sqlite3
import time
from .migrations import MigrationError, schema, statements, transaction

VERSION='003_invite50_registration_details'
SQL="""
CREATE TABLE invitation_limits(
 token TEXT PRIMARY KEY REFERENCES invites(token) ON DELETE RESTRICT,
 max_uses INTEGER NOT NULL DEFAULT 50 CHECK(max_uses BETWEEN 1 AND 50),
 used_count INTEGER NOT NULL DEFAULT 0 CHECK(used_count BETWEEN 0 AND max_uses),
 legacy_used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE invite_redemptions(
 registration_request_id TEXT PRIMARY KEY,
 invite_token TEXT NOT NULL REFERENCES invites(token) ON DELETE RESTRICT,
 user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE RESTRICT,
 used_at REAL NOT NULL CHECK(used_at>=0),
 email_challenge_id TEXT UNIQUE REFERENCES email_challenges(id),
 verification_id TEXT REFERENCES sms_verifications(verification_id),
 identity_digest BLOB CHECK(identity_digest IS NULL OR (typeof(identity_digest)='blob' AND length(identity_digest)=32)),
 request_key_id TEXT,
 retry_expires_at REAL,
 identity_format INTEGER NOT NULL DEFAULT 0 CHECK(identity_format IN (0,1,2))
);
CREATE INDEX invite_redemptions_token ON invite_redemptions(invite_token,used_at);
CREATE TABLE registration_details(
 user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
 research_area TEXT NOT NULL CHECK(length(trim(research_area)) BETWEEN 1 AND 200),
 gender TEXT NOT NULL CHECK(gender IN ('male','female','other')),
 age INTEGER NOT NULL CHECK(typeof(age)='integer' AND age BETWEEN 1 AND 120),
 created_at REAL NOT NULL
);
"""
CHECKSUM=hashlib.sha256(SQL.encode()+b'\nbackfill-union-v1-active-invites-50').hexdigest()
NAMES={'invitation_limits','invite_redemptions','invite_redemptions_token','registration_details'}


def extension_schema():
    with sqlite3.connect(':memory:') as db:
        for sql in statements(SQL):db.execute(sql)
        return schema(db)


def inspect_extensions(connection,base):
    from . import email_migration as email
    expected={**base,**email.extension_schema(),**extension_schema()}
    if schema(connection)!=expected:raise MigrationError('Unknown invitation/profile schema')
    expected_rows={email.VERSION:email.CHECKSUM,VERSION:CHECKSUM}
    rows=dict(connection.execute('SELECT version,checksum FROM schema_migrations WHERE version!=?',('001_identity_activity_expand',)))
    if rows!=expected_rows:raise MigrationError('Invitation/profile migration checksum conflict')
    return [{'version':v,'checksum':c,'state':'applied'} for v,c in expected_rows.items()]


def migrate(connection,*,observer=None):
    from .migrations import status,contracts
    observe=observer or (lambda phase:None)
    with transaction(connection):
        old=status(connection)
        if any(e['version']==VERSION for e in old.get('extensions',[])):
            return {'version':VERSION,'checksum':CHECKSUM,'result':'already_applied','state':'applied'}
        if not any(e['version']=='002_email_otp' for e in old.get('extensions',[])):
            raise MigrationError('Apply email migration first')
        for sql in statements(SQL):connection.execute(sql)
        connection.execute('INSERT INTO invite_redemptions(registration_request_id,invite_token,user_id,used_at,verification_id,identity_digest,request_key_id,retry_expires_at) SELECT registration_request_id,invite_token,user_id,used_at,verification_id,request_digest,request_key_id,retry_expires_at FROM invite_uses')
        for row in connection.execute('SELECT request_id,user_id,challenge_id,invite_token,identity_digest,created_at FROM email_registrations').fetchall():
            req,uid,challenge,token,identity,created=row
            prior=connection.execute('SELECT user_id,invite_token FROM invite_redemptions WHERE registration_request_id=?',(req,)).fetchone()
            if prior:
                if tuple(prior)!=(uid,token):raise MigrationError('Conflicting legacy registration facts')
                connection.execute('UPDATE invite_redemptions SET email_challenge_id=?,identity_digest=?,identity_format=1 WHERE registration_request_id=?',(challenge,identity,req))
            else:
                connection.execute('INSERT INTO invite_redemptions(registration_request_id,invite_token,user_id,used_at,email_challenge_id,identity_digest,identity_format) VALUES (?,?,?,?,?,?,1)',(req,token,uid,created,challenge,identity))
        now=time.time()
        for token,used,expires,revoked in connection.execute('SELECT token,used,expires,revoked_at FROM invites').fetchall():
            count=connection.execute('SELECT COUNT(*) FROM invite_redemptions WHERE invite_token=?',(token,)).fetchone()[0]
            count=max(count,int(bool(used)))
            if count>50:raise MigrationError('Historical invitation exceeds target capacity')
            connection.execute('INSERT INTO invitation_limits VALUES (?,50,?,?)',(token,count,used))
            if expires is not None and expires>now and revoked is None:
                connection.execute('UPDATE invites SET used=? WHERE token=?',(int(count>=50),token))
        observe('after_backfill')
        connection.execute('INSERT INTO schema_migrations VALUES (?,?,?)',(VERSION,CHECKSUM,now))
        inspect_extensions(connection,contracts()[1])
        if connection.execute('PRAGMA foreign_key_check').fetchone():raise MigrationError('Foreign key violations')
        observe('before_commit')
    return {'version':VERSION,'checksum':CHECKSUM,'result':'applied','state':'applied'}

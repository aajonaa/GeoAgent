"""Explicit additive email migration; never called by application startup."""
import hashlib
import sqlite3
import time
from .migrations import MigrationError, schema, statements, transaction

VERSION = '002_email_otp'
SQL = """
CREATE TABLE email_identities(
 user_id TEXT PRIMARY KEY REFERENCES users(id),
 email TEXT NOT NULL UNIQUE COLLATE NOCASE,
 verified_at REAL NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE email_challenges(
 id TEXT PRIMARY KEY,
 email TEXT NOT NULL COLLATE NOCASE,
 purpose TEXT NOT NULL CHECK(purpose IN ('register','login')),
 invite_token TEXT REFERENCES invites(token),
 bound_uid TEXT REFERENCES users(id),
 key_id TEXT NOT NULL, code_digest BLOB NOT NULL CHECK(length(code_digest)=32),
 request_id TEXT NOT NULL UNIQUE,
 ip_tag TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('sending','sent','failed','unknown','suppressed','revoked','consumed')),
 attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts>=0),
 max_attempts INTEGER NOT NULL DEFAULT 5 CHECK(max_attempts>0),
 created_at REAL NOT NULL, expires_at REAL NOT NULL,
 consumed_at REAL, consumed_by TEXT REFERENCES users(id),
 provider_ref TEXT,
 CHECK((purpose='register' AND invite_token IS NOT NULL) OR (purpose='login' AND invite_token IS NULL))
);
CREATE UNIQUE INDEX email_one_active ON email_challenges(email,purpose)
 WHERE state IN ('sending','sent');
CREATE INDEX email_send_window ON email_challenges(email,created_at);
CREATE INDEX email_ip_window ON email_challenges(ip_tag,created_at);
CREATE TABLE email_registrations(
 request_id TEXT PRIMARY KEY,
 user_id TEXT NOT NULL UNIQUE REFERENCES users(id),
 challenge_id TEXT NOT NULL UNIQUE REFERENCES email_challenges(id),
 invite_token TEXT NOT NULL UNIQUE REFERENCES invites(token),
 identity_digest BLOB NOT NULL CHECK(length(identity_digest)=32),
 created_at REAL NOT NULL
);
"""
CHECKSUM = hashlib.sha256(SQL.encode()).hexdigest()
NAMES = {'email_identities','email_challenges','email_registrations',
         'email_one_active','email_send_window','email_ip_window'}


def extension_schema():
    with sqlite3.connect(':memory:') as db:
        for statement in statements(SQL):
            db.execute(statement)
        return schema(db)


def inspect_extension(connection, base):
    actual = schema(connection)
    if {k:v for k,v in actual.items() if k not in NAMES} != base:
        raise MigrationError('Unknown base schema')
    if {k:v for k,v in actual.items() if k in NAMES} != extension_schema():
        raise MigrationError('Email schema differs from the approved contract')
    rows = connection.execute('SELECT version,checksum FROM schema_migrations WHERE version!=?',
                              ('001_identity_activity_expand',)).fetchall()
    if len(rows)!=1 or tuple(rows[0])!=(VERSION,CHECKSUM):
        raise MigrationError('Email migration checksum conflict')
    return {'version':VERSION,'checksum':CHECKSUM,'state':'applied'}


def migrate(connection, *, observer=None):
    from .migrations import status, contracts
    observe = observer or (lambda phase: None)
    with transaction(connection):
        baseline = status(connection)
        if baseline['state']!='applied':
            raise MigrationError('Apply migration 001 explicitly first')
        if baseline.get('extensions'):
            return {**baseline['extensions'][0], 'result':'already_applied'}
        for statement in statements(SQL):
            connection.execute(statement)
        observe('after_ddl')
        connection.execute('INSERT INTO schema_migrations(version,checksum,applied_at) VALUES (?,?,?)',
                           (VERSION,CHECKSUM,time.time()))
        inspect_extension(connection,contracts()[1])
        if connection.execute('PRAGMA foreign_key_check').fetchone():
            raise MigrationError('Foreign key violations')
        observe('before_commit')
    return {'version':VERSION,'checksum':CHECKSUM,'state':'applied','result':'applied'}

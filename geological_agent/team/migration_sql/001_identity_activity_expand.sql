-- DESIGN DRAFT ONLY. P1.1 did not execute this SQL, including against empty databases.
-- P1.2 must manage BEGIN IMMEDIATE / COMMIT explicitly, using individual execute calls.
CREATE TABLE schema_migrations (
  version TEXT NOT NULL PRIMARY KEY,
  checksum TEXT NOT NULL CHECK(length(checksum)=64),
  applied_at REAL NOT NULL CHECK(applied_at>=0)
);

ALTER TABLE invites ADD COLUMN created_at REAL;
ALTER TABLE invites ADD COLUMN created_by TEXT REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE invites ADD COLUMN revoked_at REAL;

CREATE TABLE user_profiles (
  user_id TEXT NOT NULL PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
  organization TEXT CHECK(organization IS NULL OR length(organization)<=200),
  phone_number TEXT CHECK(phone_number IS NULL OR (
    length(phone_number) BETWEEN 3 AND 16 AND substr(phone_number,1,1)='+'
    AND substr(phone_number,2,1) BETWEEN '1' AND '9'
    AND substr(phone_number,2) NOT GLOB '*[^0-9]*')),
  phone_verified_at REAL CHECK(phone_verified_at IS NULL OR phone_verified_at>=0),
  registered_at REAL CHECK(registered_at IS NULL OR registered_at>=0),
  created_at REAL NOT NULL CHECK(created_at>=0),
  updated_at REAL NOT NULL CHECK(updated_at>=created_at),
  CHECK((phone_number IS NULL AND phone_verified_at IS NULL) OR
        (phone_number IS NOT NULL AND phone_verified_at IS NOT NULL))
);

CREATE TABLE sms_verifications (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  verification_id TEXT NOT NULL UNIQUE CHECK(length(verification_id)=32),
  phone_number TEXT NOT NULL CHECK(
    length(phone_number) BETWEEN 3 AND 16 AND substr(phone_number,1,1)='+'
    AND substr(phone_number,2,1) BETWEEN '1' AND '9'
    AND substr(phone_number,2) NOT GLOB '*[^0-9]*'),
  purpose TEXT NOT NULL CHECK(purpose IN ('register','phone_change')),
  bound_user_id TEXT REFERENCES users(id) ON DELETE RESTRICT,
  code_digest BLOB NOT NULL CHECK(typeof(code_digest)='blob' AND length(code_digest)=32),
  key_id TEXT NOT NULL,
  send_request_id TEXT NOT NULL UNIQUE,
  request_digest BLOB NOT NULL CHECK(typeof(request_digest)='blob' AND length(request_digest)=32),
  ip_bucket TEXT NOT NULL CHECK(length(ip_bucket)=64),
  bucket_key_id TEXT NOT NULL,
  send_state TEXT NOT NULL CHECK(send_state IN ('pending','sent','failed','unknown')),
  provider_ref TEXT CHECK(provider_ref IS NULL OR length(provider_ref)<=128),
  failure_code TEXT CHECK(failure_code IS NULL OR length(failure_code)<=64),
  created_at REAL NOT NULL CHECK(created_at>=0),
  expires_at REAL NOT NULL CHECK(expires_at>created_at),
  sent_at REAL,
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0 AND attempt_count<=max_attempts),
  max_attempts INTEGER NOT NULL CHECK(max_attempts>0),
  consumed_at REAL,
  consumed_by TEXT REFERENCES users(id) ON DELETE RESTRICT,
  revoked_at REAL,
  CHECK((purpose='register' AND bound_user_id IS NULL) OR
        (purpose='phone_change' AND bound_user_id IS NOT NULL)),
  CHECK((send_state='sent' AND sent_at IS NOT NULL AND sent_at>=created_at) OR
        (send_state!='sent' AND sent_at IS NULL)),
  CHECK((consumed_at IS NULL AND consumed_by IS NULL) OR
        (consumed_at IS NOT NULL AND consumed_by IS NOT NULL AND send_state='sent'
         AND consumed_at>=sent_at AND consumed_at<expires_at)),
  CHECK(revoked_at IS NULL OR revoked_at>=created_at)
);

CREATE TABLE invite_uses (
  invite_token TEXT NOT NULL PRIMARY KEY REFERENCES invites(token) ON DELETE RESTRICT,
  user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE RESTRICT,
  used_at REAL NOT NULL CHECK(used_at>=0),
  registration_request_id TEXT NOT NULL UNIQUE,
  verification_id TEXT REFERENCES sms_verifications(verification_id) ON DELETE SET NULL,
  request_digest BLOB CHECK(request_digest IS NULL OR
    (typeof(request_digest)='blob' AND length(request_digest)=32)),
  request_key_id TEXT,
  retry_expires_at REAL,
  CHECK((request_digest IS NULL AND request_key_id IS NULL AND retry_expires_at IS NULL) OR
        (request_digest IS NOT NULL AND request_key_id IS NOT NULL
         AND retry_expires_at IS NOT NULL AND retry_expires_at>=used_at))
);

CREATE TABLE business_events (
  event_id TEXT NOT NULL PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN ('registration_completed','login_succeeded',
    'login_failed','profile_updated','file_downloaded','stream_started','retention_advanced')),
  user_id TEXT REFERENCES users(id) ON DELETE RESTRICT,
  object_type TEXT NOT NULL CHECK(object_type IN ('user','auth_attempt','file','event_stream')),
  object_id TEXT,
  occurred_at REAL NOT NULL CHECK(occurred_at>=0),
  idempotency_key TEXT,
  metadata_version INTEGER NOT NULL DEFAULT 1 CHECK(metadata_version=1),
  metadata TEXT NOT NULL DEFAULT '{}' CHECK(
    CASE WHEN json_valid(metadata) THEN json_type(metadata)='object' ELSE 0 END),
  CHECK(length(CAST(metadata AS BLOB))<=2048),
  UNIQUE(kind,idempotency_key),
  CHECK(kind IN ('login_failed','stream_started','retention_advanced') OR user_id IS NOT NULL)
);

CREATE UNIQUE INDEX profile_verified_phone ON user_profiles(phone_number) WHERE phone_number IS NOT NULL;
CREATE INDEX profile_registration ON user_profiles(registered_at,user_id) WHERE registered_at IS NOT NULL;
CREATE INDEX profile_organization ON user_profiles(organization,user_id);
CREATE INDEX sms_phone_window ON sms_verifications(phone_number,created_at);
CREATE INDEX sms_ip_window ON sms_verifications(ip_bucket,created_at);
CREATE INDEX sms_current ON sms_verifications(phone_number,purpose,bound_user_id,send_state,seq DESC);
CREATE INDEX sms_expiry ON sms_verifications(expires_at);
CREATE INDEX invite_availability ON invites(used,expires);
CREATE INDEX invite_use_time ON invite_uses(used_at,invite_token);
CREATE INDEX business_event_time ON business_events(occurred_at,event_id);
CREATE INDEX business_event_kind_time ON business_events(kind,occurred_at,event_id);
CREATE INDEX business_event_user_kind_time ON business_events(user_id,kind,occurred_at,event_id);

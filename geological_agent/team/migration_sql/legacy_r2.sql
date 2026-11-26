CREATE TABLE auth(token TEXT PRIMARY KEY, uid TEXT REFERENCES users(id), csrf TEXT, expires REAL);

CREATE TABLE conversations(id TEXT PRIMARY KEY, uid TEXT REFERENCES users(id), title TEXT,
          generation TEXT NOT NULL, created REAL, updated REAL);

CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT, rid TEXT REFERENCES runs(id), data TEXT);

CREATE TABLE file_origins(cid TEXT, generation TEXT, name TEXT,
          sha256 TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(cid,generation,name));

CREATE TABLE files(cid TEXT REFERENCES conversations(id), generation TEXT, name TEXT,
          content BLOB NOT NULL, sha256 TEXT, PRIMARY KEY(cid,generation,name));

CREATE TABLE input_requests(id TEXT PRIMARY KEY, cid TEXT REFERENCES conversations(id),
          origin_rid TEXT REFERENCES runs(id), core_id TEXT NOT NULL, job_id TEXT NOT NULL, payload TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'pending', reply_rid TEXT UNIQUE REFERENCES runs(id), created REAL NOT NULL);

CREATE TABLE invites(token TEXT PRIMARY KEY, expires REAL, used INTEGER NOT NULL DEFAULT 0);

CREATE TABLE memorax_approvals(
              uid TEXT NOT NULL REFERENCES users(id), project_id TEXT NOT NULL, approval_id TEXT NOT NULL,
              fingerprint TEXT NOT NULL, receipt TEXT NOT NULL, created REAL NOT NULL,
              PRIMARY KEY(uid,project_id,approval_id));

CREATE TABLE memorax_auto_dedup(
              uid TEXT NOT NULL, project TEXT NOT NULL, content_sha TEXT NOT NULL,
              rid TEXT NOT NULL, PRIMARY KEY(uid,project,content_sha));

CREATE TABLE memorax_auto_jobs(
              rid TEXT PRIMARY KEY REFERENCES runs(id), uid TEXT NOT NULL,
              cid TEXT NOT NULL, epoch TEXT NOT NULL, project TEXT NOT NULL,
              scope TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL,
              source_sha TEXT NOT NULL DEFAULT '', applied INTEGER NOT NULL DEFAULT 0,
              receipt TEXT NOT NULL DEFAULT '{}');

CREATE TABLE memorax_automatic(
              uid TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
              enabled INTEGER NOT NULL, since REAL NOT NULL, epoch TEXT NOT NULL);

CREATE TABLE memorax_bindings(
              cid TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
              uid TEXT NOT NULL REFERENCES users(id), project_id TEXT NOT NULL);

CREATE TABLE memorax_namespace(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);

CREATE TABLE memorax_settings(
              uid TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
              enabled INTEGER NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL);

CREATE TABLE memorax_summaries(
              cid TEXT NOT NULL, epoch TEXT NOT NULL, summary TEXT NOT NULL,
              chain_sha TEXT NOT NULL, updated REAL NOT NULL,
              PRIMARY KEY(cid,epoch));

CREATE TABLE model_profiles (uid TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,ciphertext BLOB NOT NULL, updated REAL NOT NULL);

CREATE TABLE run_activity(rid TEXT PRIMARY KEY REFERENCES runs(id), data TEXT NOT NULL);

CREATE TABLE runs(id TEXT PRIMARY KEY, cid TEXT REFERENCES conversations(id), query TEXT,
          status TEXT, answer TEXT DEFAULT '', reason TEXT DEFAULT '', generation TEXT DEFAULT '', created REAL, turns INTEGER DEFAULT 0, finished_at REAL);

CREATE TABLE users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
          password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','member')), disabled INTEGER NOT NULL DEFAULT 0);

CREATE INDEX conversation_owner ON conversations(uid,updated);

CREATE INDEX event_run ON events(rid,seq);

CREATE UNIQUE INDEX one_pending_input ON input_requests(cid) WHERE state IN ('pending','resuming');

CREATE INDEX run_conversation ON runs(cid,created);

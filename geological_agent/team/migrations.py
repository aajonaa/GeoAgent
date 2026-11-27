"""Explicit, opt-in SQLite expansion. Importing this module never changes a DB."""
from contextlib import contextmanager, closing
from pathlib import Path
import argparse
import hashlib
import json
import re
import sqlite3
import time

SQL_ROOT = Path(__file__).with_name('migration_sql')
VERSION = '001_identity_activity_expand'
DESCRIPTION = 'Add optional profiles, SMS storage, invitation usage and account events'
NEW_TABLES = {'schema_migrations', 'user_profiles', 'sms_verifications', 'invite_uses', 'business_events'}
RUNTIME_TABLES = {'generation_audit', 'file_cas_index'}
GENERATION_AUDIT_SQL = """
CREATE TABLE IF NOT EXISTS generation_audit(
 cid TEXT REFERENCES conversations(id),
 generation TEXT,
 action TEXT NOT NULL,
 source_generation TEXT,
 created REAL NOT NULL,
 PRIMARY KEY(cid,generation)
);
"""
FILE_CAS_INDEX_SQL = """
CREATE TABLE IF NOT EXISTS file_cas_index(
 cid TEXT,
 generation TEXT,
 name TEXT,
 sha256 TEXT NOT NULL,
 byte_size INTEGER NOT NULL,
 PRIMARY KEY(cid,generation,name)
);
"""


class MigrationError(RuntimeError):
    pass


def statements(text):
    """Use SQLite's statement boundary scanner, never executescript (implicit commits)."""
    buffer = ''
    for line in text.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            yield buffer
            buffer = ''
    if buffer.strip():
        raise MigrationError('Incomplete migration SQL')


def canonical(sql):
    # Preserve quoted literal case and whitespace; normalize SQL tokens only.
    return ' '.join(x if x.startswith(("'", '"')) else x.lower() for x in
                    re.findall(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|[A-Za-z_][A-Za-z_0-9]*|\d+|[^\s]", sql or ''))


def schema(connection, *, include_runtime=False):
    # Runtime tables remain outside the explicit migration contract.
    return {row[0]: {'type': row[1], 'table': row[2], 'sql': canonical(row[3])}
            for row in connection.execute("SELECT name,type,tbl_name,sql FROM sqlite_master "
                                          "WHERE name NOT LIKE 'sqlite_%' ORDER BY name")
            if include_runtime or row[0] not in RUNTIME_TABLES}


def validate_runtime_schema(connection):
    with closing(sqlite3.connect(':memory:')) as reference:
        reference.execute(GENERATION_AUDIT_SQL)
        reference.execute(FILE_CAS_INDEX_SQL)
        expected = schema(reference, include_runtime=True)
    actual = {name: value for name, value in schema(connection, include_runtime=True).items()
              if name in RUNTIME_TABLES}
    if any(name not in expected or value != expected[name] for name, value in actual.items()):
        raise MigrationError('Unknown runtime schema')


def definition():
    legacy = (SQL_ROOT / 'legacy_r2.sql').read_text(encoding='utf-8')
    expanded = (SQL_ROOT / (VERSION + '.sql')).read_text(encoding='utf-8')
    checksum = hashlib.sha256((legacy + '\n-- expansion --\n' + expanded).encode()).hexdigest()
    return legacy, expanded, checksum


def contracts():
    legacy, expanded, _ = definition()
    with closing(sqlite3.connect(':memory:', isolation_level=None)) as reference:
        reference.execute('PRAGMA foreign_keys=ON')
        for sql in statements(legacy):
            reference.execute(sql)
        before = schema(reference)
        for sql in statements(expanded):
            reference.execute(sql)
        return before, schema(reference)


def _foreign_keys(connection):
    if connection.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        raise MigrationError('Foreign keys must be enabled before starting a transaction')


@contextmanager
def transaction(connection):
    """The caller owns exactly one top-level transaction; never nest legacy Store calls."""
    if connection.in_transaction:
        raise MigrationError('An existing transaction is already active')
    _foreign_keys(connection)
    connection.execute('BEGIN IMMEDIATE')
    try:
        yield connection
        connection.execute('COMMIT')
    except BaseException:
        if connection.in_transaction:
            connection.execute('ROLLBACK')
        raise


def status(connection):
    """Read-only status; description lives in code, not an unapproved ledger column."""
    validate_runtime_schema(connection)
    _, expected = contracts()
    _, _, checksum = definition()
    if 'schema_migrations' not in schema(connection):
        return {'version': VERSION, 'description': DESCRIPTION, 'state': 'not_applied', 'checksum': checksum}
    extensions = []
    if schema(connection) != expected:
        if 'invitation_limits' in schema(connection):
            from .invite_profile_migration import inspect_extensions
            extensions = inspect_extensions(connection, expected)
        else:
            from .email_migration import inspect_extension
            extensions.append(inspect_extension(connection, expected))
    rows = connection.execute('SELECT version,checksum,applied_at FROM schema_migrations ORDER BY version').fetchall()
    original = [row for row in rows if row[0] == VERSION]
    if len(rows) != 1 + len(extensions) or len(original) != 1 or original[0][1] != checksum:
        raise MigrationError('Unknown migration version or checksum conflict')
    return {'version': VERSION, 'description': DESCRIPTION, 'state': 'applied',
            'checksum': checksum, 'applied_at': original[0][2], **({'extensions': extensions} if extensions else {})}


def migrate(connection, *, observer=None):
    """Migrate only the supplied connection; callback is for isolated fault tests.

    Never called by Store/create_app/startup. No credentials, HTTP or PostgreSQL.
    Database-level BEGIN IMMEDIATE serializes independent processes, not just threads.
    """
    legacy, expanded, checksum = definition()
    before, after = contracts()
    observe = observer or (lambda phase: None)
    with transaction(connection):
        actual = schema(connection)
        if 'schema_migrations' in actual:
            result = status(connection)
            return {**result, 'result': 'already_applied'}
        if actual and actual != before:
            raise MigrationError('Unsupported legacy schema or partially created objects')
        if not actual:
            for sql in statements(legacy):
                connection.execute(sql)
            observe('legacy_bootstrap')
        if connection.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise MigrationError('Legacy foreign key violations')
        for number, sql in enumerate(statements(expanded), 1):
            connection.execute(sql)
            observe('ddl:' + str(number))
        if schema(connection) != after:
            raise MigrationError('Expansion schema does not match its contract')
        if connection.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise MigrationError('Expansion foreign key violations')
        observe('before_ledger')
        applied = time.time()
        connection.execute('INSERT INTO schema_migrations(version,checksum,applied_at) VALUES (?,?,?)',
                           (VERSION, checksum, applied))
        observe('before_commit')
    observe('after_commit')
    return {'version': VERSION, 'description': DESCRIPTION, 'state': 'applied',
            'result': 'applied', 'checksum': checksum, 'applied_at': applied}


def guarded_database(database, workspace):
    """CLI restricts disk writes to this independent checkout's test-data tree."""
    workspace = Path(workspace).absolute()
    own = Path(__file__).resolve().parents[3]
    if workspace.resolve() != own or not (workspace / 'P1-02-workspace.json').is_file():
        raise MigrationError('An independent P1.2 workspace is required')
    test_root = workspace / 'test-data'
    database = Path(database).absolute()
    if not database.resolve().is_relative_to(test_root.resolve()) or database.suffix != '.sqlite3':
        raise MigrationError('Database must be a P1.2 test-data SQLite file')
    # Reject aliases even when they resolve back inside the allowed tree.
    for p in (database, *database.parents):
        if p.is_symlink():
            raise MigrationError('Symlink database paths are not supported')
        if p == workspace:
            break
    if database.exists() and database.stat().st_nlink != 1:
        raise MigrationError('Hard-linked databases are not supported')
    if not database.parent.is_dir():
        raise MigrationError('Database parent must already exist')
    return database


def main(argv=None):
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--database', required=True)
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args(argv)
    try:
        database = guarded_database(args.database, args.workspace)
        uri = database.as_uri() + ('?mode=ro' if args.status else '?mode=rwc')
        with closing(sqlite3.connect(uri, uri=True, timeout=5, isolation_level=None)) as connection:
            connection.execute('PRAGMA foreign_keys=ON')
            if args.status:
                connection.execute('PRAGMA query_only=ON')
            result = status(connection) if args.status else migrate(connection)
        print(json.dumps(result))
        return 0
    except (MigrationError, sqlite3.Error):
        # Do not echo SQL arguments, phone numbers or secrets on errors.
        print(json.dumps({'error': 'Migration rejected or failed; inspect schema and isolated test evidence'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

"""P1.2 real SQLite tests: no network, model, provider or production state."""
from contextlib import closing
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

import pytest
from geological_agent.team import migrations as m


def connect(path):
    connection = sqlite3.connect(path, isolation_level=None, timeout=2)
    connection.execute('PRAGMA foreign_keys=ON')
    return connection


def signature(db, tables=None):
    names = tables or [x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    result = {}
    for name in names:
        columns = [r[1] for r in db.execute('PRAGMA table_info("' + name + '")')]
        if name == 'invites': columns = [c for c in columns if c not in ('created_at', 'created_by', 'revoked_at')]
        rows = db.execute('SELECT ' + ','.join('"'+x+'"' for x in columns) + ' FROM "'+name+'" ORDER BY rowid').fetchall()
        # Contains only aggregates and hashes; no real user credentials in report.
        result[name] = {'rows': len(rows), 'sha256': hashlib.sha256(repr([tuple(row) for row in rows]).encode()).hexdigest()}
    return result


def legacy(db):
    for sql in m.statements(m.definition()[0]): db.execute(sql)


def test_T01_blank_database(tmp_path):
    with closing(connect(tmp_path/'fresh.sqlite3')) as c:
        assert m.migrate(c)['result']=='applied'
        assert len([v for v in m.schema(c).values() if v['type']=='table'])==24
        assert m.schema(c)==m.contracts()[1]
        for name in m.NEW_TABLES-{'schema_migrations'}: assert c.execute('SELECT count(*) FROM '+name).fetchone()[0]==0


def test_T02_T03_T11_legacy_snapshot_three_runs(tmp_path):
    source=Path(os.environ['P12_LEGACY_DB'])
    target=tmp_path/'legacy.sqlite3'
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as a, closing(connect(target)) as b: a.backup(b)
    with closing(connect(target)) as c:
        old_names=[x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        before=signature(c,old_names); missing=c.execute('SELECT count(*) FROM runs WHERE finished_at IS NULL').fetchone()[0]
        results=[]
        for _ in range(3):
            results.append(m.migrate(c)['result'])
            assert signature(c,old_names)==before
            assert c.execute('SELECT count(*) FROM runs WHERE finished_at IS NULL').fetchone()[0]==missing
        assert results==['applied','already_applied','already_applied']
        assert c.execute('SELECT count(*) FROM schema_migrations').fetchone()[0]==1
        assert c.execute('SELECT count(*) FROM invites WHERE created_at IS NOT NULL OR created_by IS NOT NULL OR revoked_at IS NOT NULL').fetchone()[0]==0


@pytest.mark.parametrize('failure_point', list(range(1,21))+['before_ledger','before_commit'])
def test_T04_every_expansion_statement_rolls_back(tmp_path, failure_point):
    # Five CREATE TABLE + three ALTER + twelve INDEX = 20 statements.
    with closing(connect(tmp_path/'failure.sqlite3')) as c:
        legacy(c); before=m.schema(c); data=signature(c)
        wanted='ddl:'+str(failure_point) if isinstance(failure_point,int) else failure_point
        def fail(phase):
            if phase==wanted: raise RuntimeError('injected isolated failure')
        with pytest.raises(RuntimeError):m.migrate(c,observer=fail)
        assert not c.in_transaction and m.schema(c)==before and signature(c)==data
        assert 'schema_migrations' not in m.schema(c)
        assert m.migrate(c)['result']=='applied'


def test_T04_bootstrap_failure_and_real_unique_index_failure(tmp_path):
    with closing(connect(tmp_path/'bootstrap.sqlite3')) as c:
        def fail(phase):
            if phase=='legacy_bootstrap': raise RuntimeError('injected')
        with pytest.raises(RuntimeError):m.migrate(c,observer=fail)
        assert not m.schema(c)
        legacy(c); before=m.schema(c)
        def duplicates(phase):
            if phase=='ddl:8':
                for uid in ('a'*32,'b'*32):
                    c.execute("INSERT INTO users(id,username,password,role) VALUES (?,?,?,'member')",(uid,uid,'synthetic-hash'))
                    c.execute('INSERT INTO user_profiles(user_id,phone_number,phone_verified_at,created_at,updated_at) VALUES (?,?,?,?,?)',(uid,'+12025550100',1,1,1))
        with pytest.raises(sqlite3.IntegrityError):m.migrate(c,observer=duplicates)
        assert m.schema(c)==before and c.execute('SELECT count(*) FROM users').fetchone()[0]==0


@pytest.mark.parametrize('point,applied', [('before_commit',False),('after_commit',True)])
def test_T04_process_exit_before_after_commit(tmp_path,point,applied):
    path=tmp_path/'crash.sqlite3'
    with closing(connect(path)) as c:legacy(c)
    code="from geological_agent.team import migrations as m; import sqlite3,os; c=sqlite3.connect(os.environ['CRASH_DB'],isolation_level=None); c.execute('PRAGMA foreign_keys=ON'); m.migrate(c,observer=lambda phase: os._exit(71) if phase==os.environ['CRASH_POINT'] else None)"
    p=subprocess.run([sys.executable,'-B','-c',code],env={**os.environ,'CRASH_DB':str(path),'CRASH_POINT':point},capture_output=True,timeout=15)
    assert p.returncode==71
    with closing(connect(path)) as c:
        assert ('schema_migrations' in m.schema(c))==applied
        assert m.migrate(c)['result']==('already_applied' if applied else 'applied')
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


def test_runtime_generation_audit_restart_contract(tmp_path):
    from geological_agent.team import email_migration as email
    from geological_agent.team import invite_profile_migration as invite
    from geological_agent.team.store import Store

    store=Store(tmp_path/'runtime-store')
    try:
        assert store.db.execute("SELECT 1 FROM sqlite_master WHERE name='generation_audit'").fetchone()
        m.validate_runtime_schema(store.db)
    finally:store.db.close()
    with closing(connect(tmp_path/'runtime-restart.sqlite3')) as c:
        legacy(c)
        c.execute(m.GENERATION_AUDIT_SQL)
        assert m.migrate(c)['result']=='applied'
        email.migrate(c)
        invite.migrate(c)
        state=m.status(c)
        assert {row['version'] for row in state['extensions']}=={email.VERSION,invite.VERSION}
        assert m.migrate(c)['result']=='already_applied'
        c.execute('ALTER TABLE generation_audit ADD COLUMN unexpected TEXT')
        with pytest.raises(m.MigrationError):m.status(c)
        with pytest.raises(m.MigrationError):m.migrate(c)


def test_version_checksum_and_structure_drift(tmp_path):
    with closing(connect(tmp_path/'drift.sqlite3')) as c:
        m.migrate(c)
        c.execute("UPDATE schema_migrations SET checksum=?",('0'*64,))
        before=m.schema(c)
        with pytest.raises(m.MigrationError):m.migrate(c)
        assert m.schema(c)==before
        c.execute('UPDATE schema_migrations SET checksum=?',(m.definition()[2],))
        c.execute('DROP INDEX sms_expiry')
        with pytest.raises(m.MigrationError):m.migrate(c)
    with closing(connect(tmp_path/'partial.sqlite3')) as c:
        legacy(c);c.execute('CREATE TABLE user_profiles(wrong TEXT)');before=m.schema(c)
        with pytest.raises(m.MigrationError):m.migrate(c)
        assert m.schema(c)==before


def test_foreign_keys_transaction_ownership_and_busy(tmp_path):
    path=tmp_path/'lock.sqlite3'
    with closing(connect(path)) as a,closing(connect(path)) as b:
        legacy(a);a.execute('BEGIN IMMEDIATE'); b.execute('PRAGMA busy_timeout=20')
        with pytest.raises(sqlite3.OperationalError):m.migrate(b)
        assert not b.in_transaction
        a.execute('ROLLBACK');b.execute('PRAGMA foreign_keys=OFF')
        with pytest.raises(m.MigrationError):m.migrate(b)
        b.execute('PRAGMA foreign_keys=ON');b.execute('BEGIN')
        with pytest.raises(m.MigrationError):m.migrate(b)
        assert b.in_transaction;b.execute('ROLLBACK')


def test_T13_two_process_migration_entries(tmp_path):
    W=Path(os.environ['P12_WORKSPACE']); path=tmp_path/'race.sqlite3'
    command=[sys.executable,'-B','-m','geological_agent.team.migrations','--workspace',str(W),'--database',str(path)]
    first=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    second=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    results=[]
    for p in (first,second):
        out,err=p.communicate(timeout=15);assert p.returncode==0,err
        results.append(json.loads(out)['result'])
    assert sorted(results)==['already_applied','applied']
    with closing(connect(path)) as c:assert m.schema(c)==m.contracts()[1]


def test_T14_cli_target_guard_and_no_auto_migration(tmp_path):
    W=Path(os.environ['P12_WORKSPACE']); allowed=tmp_path/'allowed.sqlite3';allowed.touch()
    assert m.guarded_database(allowed,W)==allowed
    forbidden=['/data/wangjian/geotoolagent-hitl-state-20260930-r1/team.sqlite3',str(W.parent/'state/team.sqlite3')]
    for p in forbidden:
        with pytest.raises(m.MigrationError):m.guarded_database(p,W)
    link=tmp_path/'alias.sqlite3';link.symlink_to(allowed)
    with pytest.raises(m.MigrationError):m.guarded_database(link,W)
    hard=tmp_path/'hard.sqlite3';os.link(allowed,hard)
    with pytest.raises(m.MigrationError):m.guarded_database(hard,W)
    from geological_agent.team.store import Store
    store=Store(tmp_path/'legacy-store')
    try:assert 'schema_migrations' not in m.schema(store.db)
    finally:store.db.close()


def test_T10_legacy_accounts_session_history_and_invites(tmp_path):
    from geological_agent.team.store import Store
    (tmp_path/'old').mkdir()
    with closing(connect(tmp_path/'old/team.sqlite3')) as c:legacy(c)
    s=Store(tmp_path/'old')
    try:
        uid=s.create_user('legacy-admin','Synthetic-Only-Password-123',role='admin',initial_admin=True)
        invite=s.invite(); member=s.create_user('legacy-member','Synthetic-Only-Password-123',invite=invite)
        token,csrf=s.login('legacy-member','Synthetic-Only-Password-123')
        conv=s.create_conversation(member);rid=s.begin(member,conv['id'],'synthetic task');s.finish(rid,status='completed')
        before=signature(s.db)
        m.migrate(s.db)
        assert signature(s.db,list(before))==before
        assert s.authenticate(token)['id']==member
        assert s.history(member,rid)['run_id']==rid
        assert s.run(member,rid)['status']=='completed'
        assert s.db.execute('SELECT count(*) FROM user_profiles').fetchone()[0]==0
        with pytest.raises(PermissionError):s.login('legacy-member','wrong-password')
        with pytest.raises(ValueError):s.create_user('duplicate-use','Synthetic-Only-Password-123',invite=invite)
        s.change_password(member,'Synthetic-Only-Password-123','Synthetic-Only-Password-456')
        with pytest.raises(PermissionError):s.authenticate(token)
        s.login('legacy-member','Synthetic-Only-Password-456')
        s.disable('legacy-member')
        with pytest.raises(PermissionError):s.login('legacy-member','Synthetic-Only-Password-456')
    finally:s.db.close()

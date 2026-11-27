import json
import sqlite3
from threading import RLock
from types import SimpleNamespace

import pytest

from geological_agent.team import recovery as recovery_module
from geological_agent.team.recovery import Recovery


def recovery_with_run(tmp_path, monkeypatch, *, events, phase='settled', terminal_status='stopped',
                      process_coverage=None):
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE runs (id TEXT PRIMARY KEY, cid TEXT, status TEXT)')
    db.execute('CREATE TABLE conversations (id TEXT PRIMARY KEY, uid TEXT)')
    db.execute('CREATE TABLE events (rid TEXT, seq INTEGER, data TEXT)')
    rid = 'a' * 32
    db.execute('INSERT INTO runs VALUES (?, ?, ?)', (rid, 'c', 'stopped'))
    db.execute('INSERT INTO conversations VALUES (?, ?)', ('c', 'u'))
    for seq, event in enumerate(events):
        db.execute('INSERT INTO events VALUES (?, ?, ?)', (rid, seq, json.dumps(event)))
    store = SimpleNamespace(root=tmp_path, lock=RLock(), db=db)
    recovery = Recovery(store)
    evidence = {'rid': rid, 'uid': 'u', 'cid': 'c', 'owner': {'pid': 1},
                'scope': 'external_unknown', 'phase': phase, 'execution_authorized': True,
                'terminal_status': terminal_status}
    if process_coverage:
        evidence['process_coverage'] = process_coverage
    monkeypatch.setattr(recovery, '_load', lambda run_id: evidence)
    monkeypatch.setattr(recovery_module, 'owner_dead', lambda owner: True)
    return recovery, rid, db


def test_settled_terminal_without_process_reconciles_when_all_tools_returned(tmp_path, monkeypatch):
    recovery, rid, db = recovery_with_run(tmp_path, monkeypatch, events=[
        {'kind': 'tool_start', 'id': 'one', 'name': 'web_search'},
        {'kind': 'tool_result', 'id': 'one', 'name': 'web_search'},
    ])
    try:
        recovery._inspect(rid, lambda record: None)
        assert recovery.notes[rid]['state'] == 'reconciled'
        assert recovery.notes[rid]['resource_unverified'] is False
    finally:
        db.close()


def test_settled_terminal_without_process_stays_quarantined_for_unfinished_tool(tmp_path, monkeypatch):
    recovery, rid, db = recovery_with_run(tmp_path, monkeypatch, events=[
        {'kind': 'tool_start', 'id': 'one', 'name': 'web_search'},
    ])
    try:
        recovery._inspect(rid, lambda record: None)
        assert recovery.notes[rid]['state'] == 'quarantined'
        assert recovery.notes[rid]['resource_unverified'] is True
    finally:
        db.close()


@pytest.mark.parametrize('phase,terminal_status,process_coverage', [
    ('outcome', 'stopped', None),
    ('settled', 'completed', None),
    ('settled', 'stopped', 'trusted_worker_only'),
])
def test_terminal_without_process_requires_settled_matching_uncovered_evidence(
        tmp_path, monkeypatch, phase, terminal_status, process_coverage):
    recovery, rid, db = recovery_with_run(
        tmp_path, monkeypatch, events=[], phase=phase,
        terminal_status=terminal_status, process_coverage=process_coverage)
    try:
        recovery._inspect(rid, lambda record: None)
        assert recovery.notes[rid]['state'] == 'quarantined'
        assert recovery.notes[rid]['resource_unverified'] is True
    finally:
        db.close()

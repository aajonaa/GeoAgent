"""Display contracts use synthetic receipts, not model/scientific evidence."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from geological_agent.team.presentation import csv_page, display_cell, receipt_blocks
from test_team import group


def test_large_integer_cells_and_metrics_are_lossless():
    value = 10 ** 350 + 19
    assert display_cell(value) == str(value)
    assert display_cell(42) == 42
    assert display_cell(True) is True
    blocks = receipt_blocks({'status': 'ok', 'name': 'GeoSynthetic', 'call_id': 'precise',
                             'data': {'count': value, 'rows': [{'sample': value}]}})
    raw = json.dumps(blocks, allow_nan=False)
    assert raw.count('"' + str(value) + '"') == 2
    assert receipt_blocks({'status': 'error', 'name': 'GeoSynthetic', 'data': {'value': 1}}) == []


def test_csv_keeps_original_cells_and_sorts_whole_file():
    raw = ('sample,value\n001,9007199254740993\n002,3.548e14\n003,2\n').encode()
    page = csv_page(raw, 'table.csv', offset=1, limit=1, sort=1)
    assert page['total'] == 3
    assert page['rows'] == [['002', '3.548e14']]
    assert page['sha256'] == hashlib.sha256(raw).hexdigest()
    assert csv_page(raw, 'table.csv')['rows'][0] == ['001', '9007199254740993']
    assert csv_page(b'x\ty\n1\t2\n', 'data.tsv')['rows'] == [['1', '2']]


@pytest.mark.parametrize('raw', [b'x,x\n1,2\n', b'x,y\n1\n', b'x,y\n1,2,3\n', b'\xff'])
def test_invalid_csv_is_not_silently_repaired(raw):
    with pytest.raises(ValueError):
        csv_page(raw, 'bad.csv')


def test_display_routes_are_bound_to_owner_run_and_generation(group):
    app, clients = group
    alice = clients['alice']
    store = app.state.store
    uid = store.user('alice')['id']
    cid = alice.post('/api/conversations').json()['id']
    original = b'x,y\n1,2\n'
    generation = store.snapshot(uid, cid, {'values.csv': original})
    rid = store.begin(uid, cid, 'Synthetic presentation contract test')
    receipt = {'call_id': 'call-1', 'name': 'GeoSynthetic', 'status': 'ok',
               'data': {'distance_km': 12.5}, 'artifacts': []}
    store.event(rid, {'kind': 'tool_result', 'result': receipt})
    store.finish(rid, status='completed', generation=generation)
    # A later upload must not relabel history or replace the result's old CSV.
    store.snapshot(uid, cid, {'values.csv': b'x,y\n99,100\n'})
    response = alice.get(f'/api/runs/{rid}/presentation')
    assert response.status_code == 200
    data = response.json()
    assert data['generation'] == generation
    assert data['files'] == [{'name': 'values.csv', 'bytes': len(original), 'sha256': hashlib.sha256(original).hexdigest()}]
    assert '12.5' in json.dumps(data)
    assert hashlib.sha256(original).hexdigest() in json.dumps(data)
    page = alice.get(f'/api/runs/{rid}/table', params={'name': 'values.csv'})
    assert page.status_code == 200 and page.json()['rows'] == [['1', '2']]
    download = alice.get(f'/api/runs/{rid}/receipts/call-1')
    assert download.status_code == 200 and download.json() == receipt
    assert 'attachment' in download.headers['content-disposition']
    paths = [f'/api/runs/{rid}/presentation', f'/api/runs/{rid}/table?name=values.csv',
             f'/api/runs/{rid}/receipts/call-1']
    for other in ('bob', 'admin'):
        for path in paths:
            assert clients[other].get(path).status_code == 404
    with TestClient(app, base_url='http://127.0.0.1') as anonymous:
        for path in paths:
            assert anonymous.get(path).status_code == 401


def test_no_latest_file_fallback_before_run_commit(group):
    app, clients = group
    alice, store = clients['alice'], app.state.store
    uid = store.user('alice')['id']
    cid = alice.post('/api/conversations').json()['id']
    store.snapshot(uid, cid, {'uncommitted.csv': b'x\n1\n'})
    rid = store.begin(uid, cid, 'Synthetic not committed')
    try:
        response = alice.get(f'/api/runs/{rid}/table?name=uncommitted.csv')
        assert response.status_code == 404
        assert 'uncommitted.csv' not in json.dumps(alice.get(f'/api/runs/{rid}/presentation').json())
        assert alice.get(f'/api/runs/{rid}/presentation').json()['files'] == []
    finally:
        store.finish(rid, status='stopped')


def test_presentation_javascript_syntax_and_latest_request_contract():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is not installed')
    root = Path(__file__).resolve().parents[1]
    for name in ('presentation-state.js', 'presentation.js', 'app.js'):
        subprocess.run([node, '--check', str(root / 'geological_agent/team/web' / name)], check=True)
    subprocess.run([node, str(Path(__file__).with_name('presentation-regression.js'))], check=True)
    subprocess.run([node, str(Path(__file__).with_name('answer-images-regression.js'))], check=True)

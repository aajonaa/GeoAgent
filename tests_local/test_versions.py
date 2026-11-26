"""Generation history, comparison, restore and evidence remain owner/context bound."""
import hashlib
import json
import struct
import zlib

from fastapi.testclient import TestClient

from geological_agent.team.server import COOKIE
from test_team import group


def png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00\xff\x00')) + chunk(b'IEND', b''))


def test_generation_list_compare_restore_and_permissions(group):
    app, clients = group
    alice, store = clients['alice'], app.state.store
    uid = store.user('alice')['id']
    cid = alice.post('/api/conversations').json()['id']
    other_cid = alice.post('/api/conversations').json()['id']
    image = png()
    first = store.snapshot(uid, cid, {'figure.png': image, 'notes.txt': b'first'},
                           origins={'figure.png': {'origin': 'tool', 'sha256': hashlib.sha256(image).hexdigest(),
                                                   'source': 'GeoImageTransform'}})
    second = store.snapshot(uid, cid, {'figure.png': image, 'notes.txt': b'second', 'new.csv': b'x\n1\n'})
    listing = alice.get(f'/api/conversations/{cid}/generations')
    assert listing.status_code == 200
    generations = listing.json()['items']
    assert [item['generation'] for item in generations[:2]] == [second, first]
    assert generations[0]['current'] and generations[0]['action'] == 'snapshot'
    assert generations[0]['file_count'] == 3 and generations[1]['file_count'] == 2
    detail = alice.get(f'/api/conversations/{cid}/generation', params={'id': first}).json()
    assert detail['figures'][0]['width'] == 2
    assert detail['figures'][0]['source'] == 'tool'
    assert detail['figures'][0]['cartographic_scale'] is None
    assert detail['figures'][0]['coordinate_reference'] is None
    comparison = alice.get(f'/api/conversations/{cid}/generation-compare', params={'left': first, 'right': second}).json()
    assert comparison['counts'] == {'added': 1, 'removed': 0, 'modified': 1, 'unchanged': 1}
    assert {item['name']: item['status'] for item in comparison['changes']} == {
        'figure.png': 'unchanged', 'notes.txt': 'modified', 'new.csv': 'added'}

    restored_response = alice.post(f'/api/conversations/{cid}/generation-restore', params={'generation': first})
    assert restored_response.status_code == 200
    restored = restored_response.json()['generation']
    assert restored not in (first, second)
    assert store.conversation(uid, cid)['generation'] == restored
    assert store.files(uid, cid, restored) == store.files(uid, cid, first)
    assert store.files(uid, cid, second)['notes.txt'] == b'second'
    download = alice.get(f'/api/conversations/{cid}/download', params={'name': 'notes.txt', 'generation': first})
    assert download.status_code == 200 and download.content == b'first'
    origin = store.file_origins(uid, cid, restored)['figure.png']
    assert origin['restored_from'] == first and origin['origin'] == 'tool'
    assert next(item for item in alice.get(f'/api/conversations/{cid}/generations').json()['items']
                if item['generation'] == restored)['action'] == 'restore'
    for user in ('bob', 'admin'):
        for path in (f'/api/conversations/{cid}/generations',
                     f'/api/conversations/{cid}/generation?id={first}',
                     f'/api/conversations/{cid}/generation-compare?left={first}&right={second}'):
            assert clients[user].get(path).status_code == 404
        assert clients[user].post(f'/api/conversations/{cid}/generation-restore', params={'generation': first}).status_code == 404
        assert clients[user].get(f'/api/conversations/{cid}/download', params={'name': 'notes.txt', 'generation': first}).status_code == 404
    assert alice.get(f'/api/conversations/{other_cid}/generation', params={'id': first}).status_code == 404
    assert alice.post(f'/api/conversations/{other_cid}/generation-restore', params={'generation': first}).status_code == 404
    assert alice.get(f'/api/conversations/{other_cid}/download', params={'name': 'notes.txt', 'generation': first}).status_code == 404
    assert alice.get(f'/api/conversations/{cid}/generation', params={'id': '../bad'}).status_code == 422
    with TestClient(app, base_url='http://127.0.0.1') as anonymous:
        assert anonymous.get(f'/api/conversations/{cid}/generations').status_code == 401
        assert anonymous.post(f'/api/conversations/{cid}/generation-restore', params={'generation': first}).status_code == 401


def test_empty_generation_remains_listed_and_restorable(group):
    app, clients = group
    alice, store = clients['alice'], app.state.store
    uid = store.user('alice')['id']
    cid = alice.post('/api/conversations').json()['id']
    empty = store.snapshot(uid, cid, {})
    populated = store.snapshot(uid, cid, {'notes.txt': b'notes'})
    items = alice.get(f'/api/conversations/{cid}/generations').json()['items']
    assert [item['generation'] for item in items[:2]] == [populated, empty]
    empty_row = next(item for item in items if item['generation'] == empty)
    assert empty_row['file_count'] == 0 and empty_row['bytes'] == 0
    assert not empty_row['current'] and empty_row['created_known']
    detail = alice.get(f'/api/conversations/{cid}/generation', params={'id': empty}).json()
    assert detail['files'] == [] and detail['figures'] == [] and detail['file_count'] == 0
    restored = alice.post(f'/api/conversations/{cid}/generation-restore', params={'generation': empty}).json()['generation']
    assert restored != empty and store.conversation(uid, cid)['generation'] == restored
    assert store.files(uid, cid, restored) == {}
    comparison = alice.get(f'/api/conversations/{cid}/generation-compare', params={'left': empty, 'right': restored}).json()
    assert comparison['changes'] == [] and comparison['counts']['unchanged'] == 0


def test_legacy_run_only_generation_remains_visible_and_restorable(group):
    app, clients = group
    alice, store = clients['alice'], app.state.store
    uid = store.user('alice')['id']
    cid = alice.post('/api/conversations').json()['id']
    other_cid = alice.post('/api/conversations').json()['id']
    legacy = 'f' * 32
    rid = store.begin(uid, cid, 'legacy empty result')
    store.finish(rid, status='completed', answer='历史空成果', generation=legacy)
    assert store.files(uid, cid, legacy) == {}
    assert store.db.execute('SELECT 1 FROM generation_audit WHERE cid=? AND generation=?', (cid, legacy)).fetchone() is None
    row = next(item for item in alice.get(f'/api/conversations/{cid}/generations').json()['items']
               if item['generation'] == legacy)
    assert row['file_count'] == 0 and row['bytes'] == 0 and row['created_known'] and row['run_id'] == rid
    detail = alice.get(f'/api/conversations/{cid}/generation', params={'id': legacy})
    assert detail.status_code == 200 and detail.json()['files'] == []
    assert alice.get(f'/api/conversations/{cid}/generation-compare', params={'left': legacy, 'right': legacy}).json()['changes'] == []
    restored = alice.post(f'/api/conversations/{cid}/generation-restore', params={'generation': legacy}).json()['generation']
    assert restored != legacy and store.files(uid, cid, restored) == {}
    assert alice.get(f'/api/conversations/{other_cid}/generation', params={'id': legacy}).status_code == 404
    assert clients['bob'].get(f'/api/conversations/{cid}/generation', params={'id': legacy}).status_code == 404


def test_processing_preview_keeps_source_and_output_crs_separate(group):
    app, clients = group
    alice, store = clients['alice'], app.state.store
    uid = store.user('alice')['id']
    cid = alice.post('/api/conversations').json()['id']
    image = png()
    manifest = {'schema_version': 1, 'source': {'path': 'source.tif', 'crs': 'EPSG:4326'},
                'outputs': [{'path': 'preview.png', 'sha256': hashlib.sha256(image).hexdigest()}],
                'processing': {'coordinate_reference': 'pixel-preview', 'width': 2, 'height': 1}}
    generation = store.snapshot(uid, cid, {'preview.png': image, 'preview.png.image.json': json.dumps(manifest).encode()})
    detail = alice.get(f'/api/conversations/{cid}/generation', params={'id': generation}).json()
    figure = next(item for item in detail['figures'] if item['name'] == 'preview.png')
    assert figure['coordinate_reference'] == 'pixel-preview'
    assert figure['source_coordinate_reference'] == 'EPSG:4326'


def test_geotiff_uses_raster_metadata_before_image_dimensions(group):
    import numpy as np
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin

    app, clients = group
    alice, store = clients['alice'], app.state.store
    uid = store.user('alice')['id']
    cid = alice.post('/api/conversations').json()['id']
    with MemoryFile() as memory:
        with memory.open(driver='GTiff', width=2, height=1, count=2, dtype='uint8',
                         crs='EPSG:32750', transform=from_origin(100, 200, 1, 1)) as dataset:
            dataset.write(np.array([[[1, 2]], [[3, 4]]], dtype='uint8'), [1, 2])
            dataset.set_band_unit(1, 'm')
            dataset.set_band_unit(2, 's')
        image = memory.read()
    generation = store.snapshot(uid, cid, {'raster.tif': image})
    detail = alice.get(f'/api/conversations/{cid}/generation', params={'id': generation}).json()
    figure = detail['figures'][0]
    assert figure['coordinate_reference'] == 'EPSG:32750'
    assert figure['transform'] == [100, 1, 0, 200, 0, -1]
    assert figure['width'] == 2 and figure['height'] == 1
    assert figure['units'] is None and figure['band_units'] == ['m', 's']


def test_restore_refuses_active_run_and_missing_csrf(group):
    app, clients = group
    alice, store = clients['alice'], app.state.store
    uid = store.user('alice')['id']
    cid = alice.post('/api/conversations').json()['id']
    generation = store.snapshot(uid, cid, {'a.txt': b'a'})
    response = alice.post(f'/api/conversations/{cid}/generation-restore', params={'generation': generation})
    assert response.status_code == 200
    rid = store.begin(uid, cid, 'active task')
    try:
        assert alice.post(f'/api/conversations/{cid}/generation-restore', params={'generation': generation}).status_code == 409
    finally:
        store.finish(rid, status='stopped')
    with TestClient(app, base_url='http://127.0.0.1') as missing_csrf:
        token, csrf = store.create_session(uid)
        missing_csrf.cookies.set(COOKIE, token)
        assert missing_csrf.post(f'/api/conversations/{cid}/generation-restore', params={'generation': generation}).status_code == 403


def test_evidence_uses_only_saved_citations_and_recorded_manifest(group):
    app, clients = group
    alice, store = clients['alice'], app.state.store
    uid = store.user('alice')['id']
    cid = alice.post('/api/conversations').json()['id']
    image = png()
    manifest = {'schema_version': 1, 'source': {'path': 'source.png', 'crs': None},
                'outputs': [{'path': 'figure.png', 'sha256': hashlib.sha256(image).hexdigest()}],
                'processing': {'width': 2, 'height': 1}}
    generation = store.snapshot(uid, cid, {'figure.png': image, 'figure.png.image.json': json.dumps(manifest).encode()})
    rid = store.begin(uid, cid, 'evidence contract')
    citation = 'K' + 'a' * 16 + '_1'
    answer = '结论原文 [K' + 'a' * 16 + '_1]'
    store.event(rid, {'kind': 'knowledge_sources', 'references': [
        {'citation_id': citation, 'document_id': 'doc-1', 'title': 'Saved source', 'text': 'Exact excerpt',
         'sha256': 'b' * 64, 'metadata': {'sources': [{'page': 3}]}}]})
    store.finish(rid, status='completed', answer=answer, generation=generation)
    detail = alice.get(f'/api/conversations/{cid}/generation', params={'id': generation}).json()
    figure = next(item for item in detail['figures'] if item['name'] == 'figure.png')
    assert figure['manifest'] == 'figure.png.image.json' and figure['width'] == 2
    assert figure['units'] is None and figure['cartographic_scale'] is None
    evidence = alice.get(f'/api/conversations/{cid}/generation-evidence', params={'generation': generation}).json()
    assert evidence['items'][0]['answer'] == answer
    assert evidence['items'][0]['items'][0]['text'] == 'Exact excerpt'
    assert evidence['items'][0]['items'][0]['pages'] == [3]
    assert evidence['items'][0]['relation'] == 'saved_citation_only'
    assert '支持或反驳关系未自动判定' in evidence['note']

import base64
import json
from pathlib import Path
from threading import Event
import time

from fastapi.testclient import TestClient
import pytest

from geological_agent.contracts import Message, ModelRequest, ToolCall
from geological_agent.team.isolation import Cancelled, SandboxRunner
from geological_agent.team.protocol import decode, encode, file_packet, relative_name, scrub, unpack_files
from geological_agent.team.server import COOKIE, create_app


class NoTrace:
    def emit(self, *args, **kwargs):
        pass


class FakeRunner:
    def stop(self, rid):
        pass

    def run(self, rid, query, files, cancel, model_call, on_trace, **kwargs):
        if 'WAIT_FOR_STOP' in query:
            if not cancel.wait(5):
                raise RuntimeError('Expected cancellation')
            raise Cancelled('Stopped in acceptance fixture')
        return {'status': 'completed', 'answer': 'Saved result.txt', 'reason': '', 'turns': 0,
                'files': {**files, 'result.txt': b'private test result'}}


@pytest.fixture(scope='module')
def group(tmp_path_factory):
    app = create_app(tmp_path_factory.mktemp('team'), runner=FakeRunner(), trace_factory=lambda path: NoTrace())
    store = app.state.store
    credentials = {'admin': 'Admin-Test-Password-2026', 'alice': 'Alice-Test-Password-2026', 'bob': 'Bob-Test-Password-2026'}
    store.create_user('admin', credentials['admin'], role='admin', initial_admin=True)
    for name in ('alice','bob'):
        store.create_user(name, credentials[name], invite=store.invite())
    clients = {}
    with TestClient(app, base_url='http://127.0.0.1') as lifecycle:
        for name, password in credentials.items():
            client = TestClient(app, base_url='http://127.0.0.1')
            response = client.post('/api/login', json={'username':name, 'password':password})
            assert response.status_code == 200
            client.headers['x-csrf-token'] = response.json()['csrf']
            clients[name] = client
        yield app, clients
    for client in clients.values():
        client.close()


def test_native_roundtrip_keeps_json_arrays():
    request = ModelRequest((Message('assistant', '', (ToolCall('c1','x',{'values':[1,2,3]}),)),), ())
    restored = decode(json.loads(json.dumps(encode(request))))
    assert restored.messages[0].tool_calls[0].arguments['values'] == [1,2,3]
    assert isinstance(restored.messages[0].tool_calls[0].arguments['values'], list)


@pytest.mark.parametrize('name', ['../x','/etc/passwd','a/../../b','a\\b','C:/x','.agent/key','a//b','a\x00b'])
def test_path_rejection(name):
    with pytest.raises(ValueError):
        relative_name(name)


def test_file_transfer_hash_and_duplicates():
    item = file_packet('nested/data.csv', b'x,y\n1,2\n')
    assert unpack_files([item])['nested/data.csv'].startswith(b'x,y')
    with pytest.raises(ValueError):
        unpack_files([item,item])
    item['data'] = base64.b64encode(b'changed').decode()
    with pytest.raises(ValueError):
        unpack_files([item])


def test_credentials_only_redaction_and_no_24k_cut():
    text = 'A' * 50000 + ' private-secret'
    result = scrub({'text':text,'password':'abc'}, ('private-secret',))
    assert result['text'] == 'A'*50000 + ' [REDACTED]'
    assert result['password'] == '[REDACTED]'


def test_auth_cookie_and_no_key(group):
    app, clients = group
    me = clients['alice'].get('/api/me')
    assert me.json()['role'] == 'member'
    assert 'token' not in me.json()
    assert clients['alice'].cookies.get(COOKIE)
    anonymous = TestClient(app, base_url='http://127.0.0.1')
    assert anonymous.get('/api/conversations').status_code == 401
    assert anonymous.post('/api/conversations').status_code == 401


def test_owner_checks_cover_files_history_download_and_run(group):
    app, clients = group
    alice, bob = clients['alice'], clients['bob']
    cid = alice.post('/api/conversations').json()['id']
    assert alice.post(f'/api/conversations/{cid}/upload?name=secret.txt', content=b'alice-private').status_code == 200
    for path in [f'/api/conversations/{cid}', f'/api/conversations/{cid}/files', f'/api/conversations/{cid}/download?name=secret.txt']:
        assert bob.get(path).status_code == 404
    assert bob.post(f'/api/conversations/{cid}/upload?name=changed.txt', content=b'bad').status_code == 404
    assert bob.post(f'/api/conversations/{cid}/runs', json={'query':'read secret.txt'}).status_code == 404
    assert cid not in [c['id'] for c in bob.get('/api/conversations').json()]
    rid = alice.post(f'/api/conversations/{cid}/runs', json={'query':'save a result'}).json()['id']
    for _ in range(60):
        run = alice.get(f'/api/runs/{rid}').json()
        if run['status'] != 'running':
            break
        time.sleep(.05)
    assert run['status'] == 'completed'
    assert bob.get(f'/api/runs/{rid}').status_code == 404
    assert bob.get(f'/api/runs/{rid}/events').status_code == 404
    assert bob.post(f'/api/runs/{rid}/stop').status_code == 404
    assert alice.get(f'/api/conversations/{cid}/download?name=result.txt').content == b'private test result'
    # Even the administrator's HTTP session does not bypass conversation ownership.
    assert clients['admin'].get(f'/api/conversations/{cid}').status_code == 404


def test_csrf_and_cross_origin(group):
    app, clients = group
    alice = clients['alice']
    assert alice.post('/api/conversations', headers={'x-csrf-token':'wrong'}).status_code == 403
    assert alice.post('/api/conversations', headers={'origin':'https://evil.example'}).status_code == 403
    assert alice.get('/api/me', headers={'host':'evil.example'}).status_code == 403
    assert alice.post('/api/admin/invites').status_code == 403


def test_member_invitation_cannot_grant_admin(group):
    app, clients = group
    invite = clients['admin'].post('/api/admin/invites').json()['token']
    anonymous = TestClient(app, base_url='http://127.0.0.1')
    data = {'username':'invited', 'password':'Invited-User-Password-2026','invite':invite,'role':'admin'}
    assert anonymous.post('/api/register', json=data).status_code == 200
    assert app.state.store.user('invited')['role'] == 'member'
    assert anonymous.post('/api/register', json={**data,'username':'reused'}).status_code == 400


def test_cancel_preserves_committed_files(group):
    app, clients = group
    alice = clients['alice']
    cid = alice.post('/api/conversations').json()['id']
    assert alice.post(f'/api/conversations/{cid}/upload?name=retained.txt',content=b'retain').status_code==200
    rid = alice.post(f'/api/conversations/{cid}/runs',json={'query':'WAIT_FOR_STOP'}).json()['id']
    assert alice.post(f'/api/runs/{rid}/stop').status_code == 200
    for _ in range(60):
        run = alice.get(f'/api/runs/{rid}').json()
        if run['status'] != 'running':
            break
        time.sleep(.05)
    assert run['status'] == 'stopped'
    assert alice.get(f'/api/conversations/{cid}/download?name=retained.txt').content == b'retain'


def test_logout_revokes_cookie(group):
    app, clients = group
    client = TestClient(app, base_url='http://127.0.0.1')
    login = client.post('/api/login',json={'username':'bob','password':'Bob-Test-Password-2026'})
    cookie = client.cookies.get(COOKIE)
    assert 'httponly' in login.headers['set-cookie'].lower()
    assert 'samesite=strict' in login.headers['set-cookie'].lower()
    assert client.post('/api/logout',headers={'x-csrf-token':login.json()['csrf']}).status_code==200
    client.cookies.set(COOKIE,cookie)
    assert client.get('/api/me').status_code==401


def test_no_nonlinux_execution_fallback(monkeypatch):
    monkeypatch.setattr('geological_agent.team.isolation.sys.platform','win32')
    with pytest.raises(RuntimeError,match='requires Linux'):
        SandboxRunner().command('a'*32)

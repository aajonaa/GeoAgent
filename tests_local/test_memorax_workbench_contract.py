"""Memory transport preservation checks; all HTTP calls use MockTransport."""
import json
import uuid
import httpx
import pytest
from geological_agent.memorax import MemoraXClient, MemoryUnavailable

KEY = 'synthetic-workbench-contract-key'


def client(handler):
    return MemoraXClient(KEY, http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_workbench_host_is_not_substituted_for_authenticated_api():
    calls = []
    def reply(request):
        assert request.url.host == 'preview-text.memorax.net'
        assert request.url.scheme == 'https'
        assert request.headers['authorization'] == 'Token ' + KEY
        assert request.headers['x-platform'] == 'memory'
        uuid.UUID(request.headers['x-request-id'])
        body = json.loads(request.content)
        calls.append(request.url.path)
        if request.url.path == '/v1/memories/add':
            assert set(body) == {'user_id', 'messages'}
            assert set(body['messages'][0]) == {'role', 'content'}
            return httpx.Response(200, json={'success':True,'data':{'status':'completed','task_id':'synthetic-task'}})
        assert request.url.path == '/v1/memories/search'
        assert body == {'user_id':'synthetic-user','query':'Synthetic map preference?'}
        return httpx.Response(200, json={'success':True,'data':[{'id':'synthetic-note','content':'Synthetic Chinese map labels.'}]})
    api = client(reply)
    assert api.add('synthetic-user', 'Synthetic preference.', kind='preference').status == 'completed'
    result = api.search('synthetic-user', 'Synthetic map preference?')
    assert len(result) == 1 and result[0].text == 'Synthetic Chinese map labels.'
    assert calls == ['/v1/memories/add','/v1/memories/search']


@pytest.mark.parametrize('status', [301,302,401,403,422,500,503])
def test_auth_redirects_and_errors_remain_fail_closed(status):
    calls = []
    def reply(request):
        calls.append(request)
        return httpx.Response(status, headers={'location':'https://untrusted.invalid/'}, text=KEY)
    with pytest.raises(MemoryUnavailable) as caught:
        client(reply).search('synthetic-user', 'Synthetic query')
    assert caught.value.code == 'http_' + str(status)
    assert KEY not in str(caught.value)
    assert len(calls) == 1


@pytest.mark.parametrize('payload', [[],{'success':False},{'success':True,'data':{}},
    {'success':True,'data':[{'id':'x','memory':'wrong field'}]},
    {'success':True,'data':[{'id':'x','content':'x'*4001}]}])
def test_changed_search_payload_does_not_become_fabricated_success(payload):
    with pytest.raises(MemoryUnavailable):
        client(lambda request: httpx.Response(200, json=payload)).search('synthetic-user','Synthetic query')


def test_pending_write_does_not_become_completed_or_retry():
    calls = []
    def reply(request):
        calls.append(request)
        return httpx.Response(202, json={'success':True,'data':{'task_id':'synthetic-pending','status':'accepted'}})
    assert client(reply).add('synthetic-user','Synthetic note',kind='preference').status == 'pending'
    assert len(calls) == 1


def test_timeout_keeps_unknown_outcome_and_hides_key():
    def reply(request):
        raise httpx.ReadTimeout(KEY,request=request)
    with pytest.raises(MemoryUnavailable) as caught:
        client(reply).add('synthetic-user','Synthetic note',kind='preference')
    assert caught.value.outcome_unknown is True
    assert KEY not in str(caught.value)

"""Transport controls use labelled protocol fixtures, never fake science."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from geological_agent.geology import native_cpu_bridge as bridge
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError

NAME = 'ProtocolFixtureOnly'


@pytest.fixture
def protocol(tmp_path, monkeypatch):
    root = tmp_path / 'profile'
    root.mkdir()
    worker = root / 'never-executed-protocol-fixture.py'
    worker.write_text('# Labelled protocol fixture, not a scientific implementation.\n')
    profile = root / 'profiles.json'
    binding = {'root': str(root), 'python': sys.executable, 'entrypoint': str(worker), 'files_sha256': {str(worker): bridge.digest(worker), sys.executable: bridge.digest(sys.executable)}, 'binary_sha256': 'f' * 64, 'build_receipt_sha256': 'a' * 64, 'timeout_seconds': None}
    profile.write_text(json.dumps({'protocol': 'fixed-cpu-arguments-json-v1', 'operations': {NAME: binding}}))
    spec = {'input_schema': {'type': 'object', 'required': ['x'], 'properties': {'x': {'type': 'number', 'minimum': 0, 'maximum': 10}}, 'additionalProperties': False}, 'output_schema': {'type': 'object', 'required': ['x', 'units', 'provenance', 'artifacts'], 'properties': {'x': {'type': 'number'}, 'units': {'type': 'object'}, 'provenance': {'type': 'object'}, 'artifacts': {'type': 'array', 'maxItems': 0}}, 'additionalProperties': False}, 'error_contract': {'codes': ['invalid_arguments', 'missing_dependency', 'integrity_error', 'execution_error', 'invalid_result', 'resource_limit']}}
    reply = {'status': 'ok', 'tool': NAME, 'data': {'x': 1, 'units': {'x': 'm'}, 'provenance': {'tool': NAME, 'binary_sha256': binding['binary_sha256'], 'build_receipt_sha256': binding['build_receipt_sha256'], 'implementation_sha256': 'c' * 64, 'output_sha256': {}}}}
    calls = []
    def process(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(reply).encode(), stderr=b'')
    monkeypatch.setattr(bridge, 'PROFILE_FILE', profile)
    monkeypatch.setattr(bridge, 'specification', lambda name: copy.deepcopy(spec))
    monkeypatch.setattr(bridge.subprocess, 'run', process)
    return SimpleNamespace(root=root, worker=worker, profile=profile, binding=binding, reply=reply, calls=calls, process=process)


@pytest.mark.parametrize('mode', ['dict', 'json', 'args'])
def test_fixed_argv_schema_cpu_caches_and_secret_nonforwarding(protocol, monkeypatch, mode):
    monkeypatch.setenv('OPENAI_API_KEY', 'labelled-test-secret-not-a-credential')
    monkeypatch.setenv('LANGSMITH_API_KEY', 'labelled-test-secret-not-a-credential')
    result = bridge.invoke(NAME, args={'x': 1}) if mode == 'args' else bridge.invoke(NAME, json.dumps({'x': 1}) if mode == 'json' else {'x': 1})
    assert result['x'] == 1 and result['artifacts'] == []
    assert result['provenance']['binary_sha256'] == protocol.binding['binary_sha256']
    assert result['provenance']['runtime_install'] is False and result['provenance']['gpu_used'] is False
    argv, kwargs = protocol.calls[0]
    assert argv == [sys.executable, str(protocol.worker), NAME]
    assert json.loads(kwargs['input']) == {'x': 1} and kwargs['timeout'] is None
    env = kwargs['env']
    assert env['CUDA_VISIBLE_DEVICES'] == '' and env['NVIDIA_VISIBLE_DEVICES'] == 'none'
    assert 'OPENAI_API_KEY' not in env and 'LANGSMITH_API_KEY' not in env
    for key in ['MPLCONFIGDIR', 'NUMBA_CACHE_DIR', 'XDG_CACHE_HOME', 'HOME', 'TMPDIR']:
        assert Path(env[key]).is_relative_to(protocol.root / 'runtime-private-cache')
    assert not Path(env['TMPDIR']).exists()


@pytest.mark.parametrize('value', [[], None, {'x': True}, {'x': -1}, {'x': 11}, {'x': '1'}, {'x': 1, 'command': 'must-not-execute'}, {'x': float('nan')}, {'x': float('inf')}, '{"x":1,"x":2}', '{"x":NaN}', '[1]', '{invalid'])
def test_invalid_input_never_spawns(protocol, value):
    with pytest.raises(ScientificToolError) as error:
        bridge.invoke(NAME, value)
    assert error.value.code == 'invalid_arguments' and error.value.retryable is False
    assert protocol.calls == []


def test_output_directory_and_double_arguments_never_spawn(protocol):
    for kwargs in [{'output_dir': protocol.root / 'output'}, {'args': {'x': 2}}]:
        with pytest.raises(ScientificToolError) as error:
            bridge.invoke(NAME, {'x': 1}, **kwargs)
        assert error.value.code == 'invalid_arguments'
    assert protocol.calls == []


def test_input_bound_never_spawns(protocol):
    with pytest.raises(ScientificToolError) as error:
        bridge.invoke(NAME, '{"x":1,"oversized":"' + 'x' * 262145 + '"}')
    assert error.value.code == 'resource_limit' and protocol.calls == []


@pytest.mark.parametrize('raw,code,expected', [(b'{invalid', 0, 'invalid_result'), (b'[]', 0, 'invalid_result'), (b'{"status":"ok","status":"ok"}', 0, 'invalid_result'), (b'{"status":"ok","tool":"WrongTool","data":{}}', 0, 'invalid_result'), (b'{"status":"ok","tool":"ProtocolFixtureOnly","data":{}}', 2, 'invalid_result'), (b'{"status":"error","error":{"code":"invalid_arguments","message":"original child error","retryable":false}}', 2, 'invalid_arguments'), (b'{"status":"error","error":{"code":"undeclared_error","message":"bad","retryable":false}}', 2, 'invalid_result'), (b'{"status":"error","error":{"code":"invalid_arguments","message":"bad","retryable":true}}', 2, 'invalid_result'), (b'{"status":"error","error":{"code":"invalid_arguments","message":"bad","retryable":false}}', 0, 'invalid_result'), (b'\xff', 0, 'invalid_result')])
def test_child_protocol_and_failure_contract(protocol, monkeypatch, raw, code, expected):
    monkeypatch.setattr(bridge.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=code, stdout=raw, stderr=b''))
    with pytest.raises(ScientificToolError) as error:
        bridge.invoke(NAME, {'x': 1})
    assert error.value.code == expected and error.value.retryable is False
    if expected == 'invalid_arguments':
        assert str(error.value) == 'original child error'


@pytest.mark.parametrize('field', ['binary_sha256', 'build_receipt_sha256', 'tool'])
def test_false_execution_binding_rejected(protocol, field):
    protocol.reply['data']['provenance'][field] = 'not-the-reviewed-build'
    with pytest.raises(ScientificToolError) as error:
        bridge.invoke(NAME, {'x': 1})
    assert error.value.code == 'integrity_error'


def test_no_fabricated_artifacts(protocol):
    protocol.reply['data']['provenance']['output_sha256'] = {'fake.png': 'f' * 64}
    with pytest.raises(ScientificToolError) as error:
        bridge.invoke(NAME, {'x': 1})
    assert error.value.code == 'invalid_result'


def test_output_schema_not_relaxed(protocol):
    protocol.reply['data']['x'] = 'not-a-number'
    with pytest.raises(ScientificToolError) as error:
        bridge.invoke(NAME, {'x': 1})
    assert error.value.code == 'invalid_result'


def test_source_integrity_prevents_execution(protocol):
    protocol.worker.write_text('# labelled tampered test fixture, not a science source\n')
    with pytest.raises(ScientificToolError) as error:
        bridge.invoke(NAME, {'x': 1})
    assert error.value.code == 'integrity_error' and protocol.calls == []


def test_missing_profile_is_structured(protocol):
    protocol.profile.unlink()
    with pytest.raises(ScientificToolError) as error:
        bridge.invoke(NAME, {'x': 1})
    assert error.value.code == 'missing_dependency' and protocol.calls == []


def test_missing_fixed_profile_directory_is_structured(protocol):
    profile = json.loads(protocol.profile.read_text())
    profile['operations'][NAME]['root'] = str(protocol.root / 'does-not-exist')
    protocol.profile.write_text(json.dumps(profile))
    with pytest.raises(ScientificToolError) as error:
        bridge.invoke(NAME, {'x': 1})
    assert error.value.code == 'missing_dependency' and protocol.calls == []


def test_output_bound(protocol, monkeypatch):
    monkeypatch.setattr(bridge.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=b' ' * 2097153, stderr=b''))
    with pytest.raises(ScientificToolError) as error:
        bridge.invoke(NAME, {'x': 1})
    assert error.value.code == 'resource_limit'

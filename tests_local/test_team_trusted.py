from pathlib import Path
from threading import Event
from types import SimpleNamespace
import pytest

from geological_agent.team.trusted import TrustedLocalRunner
from geological_agent.team.server import create_app
from geological_agent.team.isolation import Cancelled


def test_trusted_run_uses_native_core_and_preserves_files(tmp_path, monkeypatch):
    events = []
    def builder(model, settings, trace_factory):
        class Agent:
            def run(self, query, workspace, cancel_event):
                assert query == 'calculate'
                assert (workspace / 'input.txt').read_bytes() == b'input'
                (workspace / 'answer.txt').write_text('5', encoding='utf-8')
                trace_factory('run', workspace).emit('checked', result=model.invoke('request'))
                return SimpleNamespace(status='completed', answer='5', reason=None, model_turns=1)
        return Agent()
    monkeypatch.setattr('geological_agent.team.trusted.create_agent', builder)
    runner = TrustedLocalRunner(tmp_path / 'jobs')
    result = runner.run('a'*32, 'calculate', {'input.txt':b'input'}, Event(), lambda request,cancel:'native', lambda kind,fields:events.append((kind,fields)))
    assert runner.isolated is False
    assert result['files'] == {'input.txt':b'input', 'answer.txt':b'5'}
    assert events == [('checked', {'result':'native'})]


def test_trusted_run_honors_pre_start_cancel(tmp_path):
    cancel = Event()
    cancel.set()
    with pytest.raises(Cancelled):
        TrustedLocalRunner(tmp_path).run('b'*32,'query',{},cancel,None,None)


def test_trusted_mode_requires_explicit_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv('GEOTOOL_TEAM_EXECUTION', raising=False)
    assert create_app(tmp_path / 'default').state.runner.isolated is True
    monkeypatch.setenv('GEOTOOL_TEAM_EXECUTION', 'trusted')
    assert create_app(tmp_path / 'trusted').state.runner.isolated is False
    monkeypatch.setenv('GEOTOOL_TEAM_EXECUTION', 'typo')
    with pytest.raises(ValueError, match='automatic fallback'):
        create_app(tmp_path / 'bad')

"""Business outcomes and fault labels do not authorize execution or approval."""
from copy import deepcopy
import json

import pytest

from geological_agent.run_status import issue_for_event, task_outcome
from geological_agent.team.streaming import RunProgress
from test_langsmith_tracing import sink


EVIDENCE = 'Invalid source review blocks: ' + json.dumps({
    'b1': 'Compared term needs its exact quoted source evidence: private source text',
})


def paused(error=EVIDENCE):
    return {'status': 'needs_input', 'error': error, 'model_turns': 2,
            'metadata': {'pending_input': {'reason_type': 'model_protocol',
                'recovery_origin': 'runtime', 'recovery_phase': 'knowledge_semantics',
                'reason': error}}}


@pytest.mark.parametrize('event,fields,expected', [
    ('completion_review_protocol_error', {'error': EVIDENCE}, 'review_evidence'),
    ('completion_review_protocol_error', {'error': 'Invalid source review blocks: {"b1":"Missing requested block"}'}, 'review_format'),
    ('completion_review_protocol_error', {'error': 'Invalid source review blocks: broken'}, 'review_format'),
    ('completion_review_protocol_error', {'error': 'Model provider error: unavailable'}, 'model_service'),
    ('model_protocol_error', {'error': 'Native tool call absent'}, 'model_protocol'),
    ('model_failed', {'error': 'private exception'}, 'model_service'),
    ('completion_rejected', {'feedback': 'Unsupported claim'}, 'answer_validation'),
    ('knowledge_semantic_checked', {'passed': False}, 'answer_validation'),
    ('completion_check_error', {'error': 'Internal checker failure'}, 'verification_error'),
])
def test_fault_categories_come_from_events_and_do_not_export_private_text(event, fields, expected):
    original = deepcopy(fields)
    issue = issue_for_event(event, fields)
    assert issue['category'] == expected and fields == original
    assert 'private' not in json.dumps(issue)


def test_unrelated_events_and_successful_reviews_are_not_errors():
    assert issue_for_event('model_responded', {'content': EVIDENCE}) is None
    assert issue_for_event('knowledge_semantic_checked', {'passed': True}) is None


def test_runtime_recovery_is_not_a_request_for_research_information():
    outcome = task_outcome(paused())
    assert outcome['business_state'] == 'review_blocked'
    assert outcome['failure_category'] == 'review_evidence'
    assert outcome['recovery_required'] and not outcome['task_completed']
    normal = task_outcome({'status': 'needs_input', 'metadata': {
        'pending_input': {'question': 'Which area?', 'reason_type': 'missing_user_input'}}},
        {'category': 'review_evidence'})
    assert normal['business_state'] == 'awaiting_user' and not normal['recovery_required']
    assert normal['failure_category'] is None


def test_intent_pause_snapshot_without_current_error_is_not_a_review_failure():
    fields = paused('The model service did not honor native tool_choice=required')
    fields['metadata']['pending_input']['recovery_phase'] = 'intent'
    before = deepcopy(fields)
    outcome = task_outcome(fields)
    assert outcome['business_state'] == 'model_blocked'
    assert outcome['failure_category'] == 'model_protocol'
    assert outcome['recovery_required'] and not outcome['task_completed']
    assert fields == before


@pytest.mark.parametrize('status', ['completed', 'failed', 'stopped', 'budget_exhausted', 'incomplete'])
def test_outcome_never_infers_success_from_an_ended_run(status):
    result = task_outcome({'status': status}, {'category': 'model_service'})
    assert result['task_completed'] is (status == 'completed')
    assert result['business_state'] == status
    if status == 'completed':
        assert result['failure_category'] is None


def test_progress_publishes_distinct_issue_and_outcome_without_mutating_evidence():
    events = []
    progress = RunProgress(events.append)
    fields = {'phase': 'knowledge_semantics', 'turn': 2, 'error': EVIDENCE}
    before = deepcopy(fields)
    progress.observe('completion_review_protocol_error', fields)
    progress.observe('run_finished', paused())
    assert fields == before
    assert events[0]['kind'] == 'diagnostic' and events[0]['category'] == 'review_evidence'
    assert events[1]['kind'] == 'run_outcome' and events[1]['business_state'] == 'review_blocked'
    assert not any('private' in json.dumps(event) for event in events)
    progress.close()
    count = len(events)
    progress.observe('model_protocol_error', {'error': 'late'})
    assert len(events) == count


@pytest.mark.parametrize('capture', [False, True])
def test_langsmith_marks_blocked_review_without_claiming_task_success(tmp_path, capture):
    trace, client = sink(tmp_path, capture=capture)
    trace.emit('run_started', run_id='synthetic-status', task='Synthetic status acceptance')
    trace.emit('completion_review_protocol_error', phase='knowledge_semantics', turn=2, error=EVIDENCE)
    trace.emit('run_finished', **paused())
    assert not trace.failed
    final = client.updated[-1]
    assert final['error']
    assert final['outputs']['task_outcome']['business_state'] == 'review_blocked'
    assert not final['outputs']['task_outcome']['task_completed']
    assert trace.root.extra['metadata']['business_state'] == 'review_blocked'
    assert 'task_state:review_blocked' in trace.root.tags
    if not capture:
        assert 'private' not in json.dumps([client.created, client.updated], default=str)


def test_completed_run_preserves_recovered_failure_but_is_business_success(tmp_path):
    trace, client = sink(tmp_path)
    trace.emit('run_started', run_id='synthetic-recovered', task='Synthetic recovery')
    trace.emit('completion_review_protocol_error', phase='knowledge_semantics', turn=1, error=EVIDENCE)
    trace.emit('knowledge_semantic_checked', passed=True, turn=2)
    trace.emit('run_finished', status='completed', model_turns=2)
    assert not trace.failed and not client.updated[-1].get('error')
    assert client.updated[-1]['outputs']['task_outcome']['task_completed']
    assert any(item.get('error') == 'completion_review_protocol_error' for item in client.updated)


def test_actual_human_question_remains_nonfailure_and_not_completed(tmp_path):
    trace, client = sink(tmp_path)
    trace.emit('run_started', run_id='synthetic-human', task='Synthetic clarification')
    trace.emit('run_finished', status='needs_input', metadata={
        'pending_input': {'question': 'Which region?', 'reason_type': 'missing_user_input'}})
    result = client.updated[-1]
    assert not trace.failed and not result.get('error')
    assert result['outputs']['task_outcome']['business_state'] == 'awaiting_user'
    assert not result['outputs']['task_outcome']['task_completed']

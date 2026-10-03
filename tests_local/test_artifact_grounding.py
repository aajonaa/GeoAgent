import importlib.util
import json
from pathlib import Path

import pytest

from geological_agent.agent.completion import quoted_artifact_issues
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import ModelResponse, ToolCall


_spec = importlib.util.spec_from_file_location("grounding_oracles", Path(__file__).resolve().parents[1] / "scripts/local_agent_oracles.py")
_oracles = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_oracles)


def contents(text, path="summary.json", truncated=False):
    return {path: {"content": text, "truncated": truncated}}


@pytest.mark.parametrize("quote", ['{"value":42000}', '{"value":true}', '{"value":42, "invented":1}', '{"value":'])
def test_named_json_quotation_must_match_actual_file(quote):
    issues = quoted_artifact_issues("### summary.json\n```json\n" + quote + "\n```", contents('{"value":42}'))
    assert issues and not issues[0].needs_action
    assert "actual file" in issues[0].message


def test_json_formatting_and_equivalent_numbers_are_accepted():
    assert not quoted_artifact_issues('summary.json\n```json\n{ "value": 42.0 }\n```', contents('{"value":42}'))


def test_every_quote_is_checked_and_other_files_are_not_conflated():
    actual = {**contents('{"value":42}'), **contents("Total: 42\n", "report.md")}
    answer = 'summary.json\n```json\n{"value":42}\n```\nreport.md\n```text\nTotal: 42000\n```'
    issues = quoted_artifact_issues(answer, actual)
    assert len(issues) == 1 and "report.md" in issues[0].message


def test_truncated_evidence_cannot_approve_full_file_quote():
    issues = quoted_artifact_issues('summary.json\n```json\n{"value":42}\n```', contents('{"value":42}', truncated=True))
    assert issues and issues[0].needs_action


def test_unattributed_hypothetical_code_is_not_a_file_claim():
    assert not quoted_artifact_issues('Example code:\n```python\nprint(100)\n```', contents('{"value":42}'))


class Model:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        return next(self.responses)


def test_bad_file_quote_is_revised_without_reexecuting_the_tool(tmp_path):
    good = 'summary.json\n```json\n{"value":42}\n```'
    bad = 'summary.json\n```json\n{"value":42000}\n```'
    model = Model(
        ModelResponse(tool_calls=(ToolCall("w1", "write_file", {"path": "summary.json", "content": '{"value":42}'}),), finish_reason="tool_calls"),
        ModelResponse("Created summary.json."),
        ModelResponse(tool_calls=(ToolCall("readiness", "assess_completion", {
            "verdict": "complete", "feedback": "The file was created", "required_outputs": ["summary.json"],
            "requires_python_execution": False, "evidence_call_ids": ["w1"]}),), finish_reason="tool_calls"),
        ModelResponse(bad), ModelResponse(good),
        ModelResponse(tool_calls=(ToolCall("assessment", "assess_completion", {
            "verdict": "complete", "feedback": "Actual file agrees with answer", "required_outputs": ["summary.json"],
            "requires_python_execution": False, "evidence_call_ids": ["w1"]}),), finish_reason="tool_calls"))
    result = create_agent(model).run("Create summary.json containing value 42 and report its content", workspace=tmp_path)
    assert result.status == "completed" and result.answer == good
    assert result.model_turns == 6
    assert len([m for m in result.state["messages"] if m.role == "tool"]) == 1
    assert model.requests[4].tool_choice == "none"
    assert not any(m.content == bad for m in model.requests[4].messages)
    assert "actual file" in result.state["metadata"]["rejected_answers"][0]["feedback"]
    review_payload = json.loads(model.requests[5].messages[1].content)
    assert review_payload["observed_artifact_contents"]["summary.json"]["content"] == '{"value":42}'


def test_independent_oracle_rejects_the_observed_false_pass():
    bad = 'summary.json and report.md\n```json\n{"total_ore_tonnes":430.0,"total_metal_tonnes":7.8,"weighted_grade_pct":1.813953488372093}\n```'
    with pytest.raises(AssertionError):
        _oracles.assert_table_answer(bad)


def test_independent_oracle_checks_prose_even_beside_correct_json():
    good = 'summary.json and report.md\n```json\n{"total_ore_tonnes":380.0,"total_metal_tonnes":4.4,"weighted_grade_pct":1.1578947368421053}\n```'
    _oracles.assert_table_answer(good)
    with pytest.raises(AssertionError):
        _oracles.assert_table_answer(good + "\nThere are 430 tonnes of ore.")


def test_independent_oracle_accepts_labelled_rounding():
    _oracles.assert_table_answer("summary.json and report.md\nTotal ore (t): 380\nTheoretical metal (t): 4.4\nWeighted grade (%): 1.16")

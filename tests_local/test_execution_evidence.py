import hashlib
import importlib.util
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from geological_agent.agent.completion import review_evidence_issues
from geological_agent.contracts import ToolResult
from geological_agent.settings import Settings
from geological_agent.tools import ToolExecutionContext, ToolFailure, execute_python


_spec = importlib.util.spec_from_file_location("execution_oracles", Path(__file__).resolve().parents[1] / "scripts/local_agent_oracles.py")
_oracles = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_oracles)


def events(output, workspace):
    return [json.loads(line) for line in (workspace / output.data["execution_trace_path"]).read_text().splitlines()]


def context(tmp_path):
    return ToolExecutionContext("evidence-test", tmp_path, {"execute_python"}, Settings(), Event())


def test_redefined_function_does_not_count_as_executing_saved_file(tmp_path):
    (tmp_path / "calc.py").write_text("def f():\n    return 3\n")
    result = execute_python({"code": "def f():\n    return 3\n\nassert f() == 3\n"}, context(tmp_path))
    assert result.data["return_code"] == 0
    assert result.data["execution_record_complete"]
    assert result.data["executed_files"] == []


def test_actual_saved_file_execution_records_its_hash(tmp_path):
    path = tmp_path / "calc.py"
    path.write_text("def f():\n    return 3\n")
    result = execute_python({"code": "import runpy\nf = runpy.run_path('calc.py')['f']\nassert f() == 3\nprint(f())\n"}, context(tmp_path))
    assert result.data["stdout"].strip() == "3"
    assert result.data["executed_files"] == [{"path": "calc.py", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]


def test_completion_rejects_execution_of_previous_file_version(tmp_path):
    path = tmp_path / "calc.py"
    path.write_text("def f():\n    return 3\n")
    ctx = context(tmp_path)
    output = execute_python({"code": "import runpy\nassert runpy.run_path('calc.py')['f']() == 3\n"}, ctx)
    state = {"answer": "Repaired calc.py", "artifacts": [SimpleNamespace(path="calc.py")],
             "messages": [ToolResult("p1", "execute_python", "ok", output.data).message()]}
    review = {"required_outputs": ["calc.py"], "requires_python_execution": True, "evidence_call_ids": ["p1"]}
    assert not review_evidence_issues(review, state, ctx)
    path.write_text("def f():\n    return 300\n")
    assert any("current saved version" in issue.message for issue in review_evidence_issues(review, state, ctx))


def test_completion_rejects_copy_only_execution(tmp_path):
    (tmp_path / "calc.py").write_text("def f():\n    return 3\n")
    ctx = context(tmp_path)
    output = execute_python({"code": "assert 3 == 3\n"}, ctx)
    state = {"answer": "Repaired calc.py", "artifacts": [SimpleNamespace(path="calc.py")],
             "messages": [ToolResult("p1", "execute_python", "ok", output.data).message()]}
    review = {"required_outputs": ["calc.py"], "requires_python_execution": True, "evidence_call_ids": ["p1"]}
    issues = review_evidence_issues(review, state, ctx)
    assert any(issue.needs_action and "current saved version" in issue.message for issue in issues)


SOURCE = "def contained_metal(ore_tonnes, grade_pct):\n    return ore_tonnes * grade_pct / 100\n\nif __name__ == '__main__':\n    assert abs(contained_metal(200, 1.5) - 3) < 1e-9\n    assert abs(contained_metal(100, 1.2) - 1.2) < 1e-9\n"
CASES = [({"ore_tonnes": 200, "grade_pct": 1.5}, 3), ({"ore_tonnes": 100, "grade_pct": 1.2}, 1.2)]


def check_cases(output, tmp_path):
    _oracles.assert_executed_cases([{"name": "execute_python", "status": "ok", "data": output.data}], tmp_path, "calc.py", "contained_metal", CASES)


def test_loaded_module_is_not_function_or_test_execution(tmp_path):
    (tmp_path / "calc.py").write_text(SOURCE)
    ctx = context(tmp_path)
    output = execute_python({"code": "import runpy\nrunpy.run_path('calc.py')\n"}, ctx)
    assert output.data["executed_files"]
    assert not any(event["event"] == "assertion" for event in events(output, tmp_path))
    state = {"answer": "Tests passed", "artifacts": [SimpleNamespace(path="calc.py")],
             "messages": [ToolResult("p1", "execute_python", "ok", output.data).message()]}
    review = {"required_outputs": ["calc.py"], "requires_python_execution": True, "evidence_call_ids": ["p1"]}
    assert any(issue.needs_action and "only loaded" in issue.message for issue in review_evidence_issues(review, state, ctx))
    with pytest.raises(AssertionError, match="checked cases"):
        check_cases(output, tmp_path)


@pytest.mark.parametrize("code", [
    "import runpy\nrunpy.run_path('calc.py', run_name='__main__')\n",
    "import runpy, math\nf=runpy.run_path('calc.py')['contained_metal']\nassert math.isclose(f(200,1.5),3)\nassert math.isclose(f(100,1.2),1.2)\n",
    "import sys\nsys.path.insert(0,'.')\nfrom calc import contained_metal as f\nassert abs(f(200,1.5)-3)<1e-9\nassert abs(f(100,1.2)-1.2)<1e-9\n",
])
def test_actual_checked_calls_prove_both_cases(tmp_path, code):
    (tmp_path / "calc.py").write_text(SOURCE)
    output = execute_python({"code": code}, context(tmp_path))
    check_cases(output, tmp_path)


@pytest.mark.parametrize("code", [
    "import runpy\nf=runpy.run_path('calc.py')['contained_metal']\nf(200,1.5)\nf(100,1.2)\nprint('All tests passed')\n",
    "import runpy\nf=runpy.run_path('calc.py')['contained_metal']\nassert f(200,1.5)==3\n",
    "import runpy\nf=runpy.run_path('calc.py')['contained_metal']\ndef test_cases():\n    assert f(200,1.5)==3\n    assert f(100,1.2)==1.2\n",
    "import runpy\nf=runpy.run_path('calc.py')['contained_metal']\nf(200,1.5)\nf(100,1.2)\nassert 3==3\n",
    "import runpy\nf=runpy.run_path('calc.py')['contained_metal']\ntry:\n    assert f(200,1.5)==300\nexcept AssertionError:\n    pass\nassert f(100,1.2)==1.2\n",
])
def test_incomplete_or_unrelated_checks_do_not_pass_oracle(tmp_path, code):
    (tmp_path / "calc.py").write_text(SOURCE)
    output = execute_python({"code": code}, context(tmp_path))
    with pytest.raises(AssertionError, match="checked cases"):
        check_cases(output, tmp_path)


@pytest.mark.parametrize("assertion", ["assert f(200,1.5)==300\n", "assert (\n    f(200,1.5)\n    == 300\n)\n"])
def test_failed_assertion_is_recorded_not_passed(tmp_path, assertion):
    (tmp_path / "calc.py").write_text(SOURCE)
    with pytest.raises(ToolFailure) as caught:
        execute_python({"code": "import runpy\nf=runpy.run_path('calc.py')['contained_metal']\n" + assertion}, context(tmp_path))
    checks = [event for event in events(caught.value, tmp_path) if event["event"] == "assertion"]
    assert checks and checks[-1]["status"] == "raised"


@pytest.mark.parametrize("assertion", [
    "assert (\n    f(200,1.5)\n    == 3\n)\n",
    "assert abs(\n    f(200,1.5) - 3\n) < 1e-9\n",
    "assert math.isclose(\n    f(200,1.5),\n    3\n)\n",
])
def test_multiline_assertion_is_observed(tmp_path, assertion):
    (tmp_path / "calc.py").write_text(SOURCE)
    code = "import runpy, math\nf=runpy.run_path('calc.py')['contained_metal']\n" + assertion + "assert f(100,1.2)==1.2\n"
    output = execute_python({"code": code}, context(tmp_path))
    check_cases(output, tmp_path)


def test_trace_preview_is_bounded_without_discarding_raw_evidence(tmp_path):
    (tmp_path / "calc.py").write_text(SOURCE)
    ctx = context(tmp_path)
    ctx.settings = Settings(max_tool_output_chars=800)
    output = execute_python({"code": "import runpy\nrunpy.run_path('calc.py', run_name='__main__')\n"}, ctx)
    assert output.data["execution_events_truncated"]
    check_cases(output, tmp_path)


def test_disabled_trace_is_not_complete(tmp_path):
    output = execute_python({"code": "import sys\nsys.settrace(None)\n"}, context(tmp_path))
    assert not output.data["execution_record_complete"]


def test_trace_tampering_or_stale_source_does_not_pass_oracle(tmp_path):
    path = tmp_path / "calc.py"
    path.write_text(SOURCE)
    output = execute_python({"code": "import runpy\nrunpy.run_path('calc.py', run_name='__main__')\n"}, context(tmp_path))
    path.write_text(SOURCE + "\n# changed after testing\n")
    with pytest.raises(AssertionError, match="checked cases"):
        check_cases(output, tmp_path)
    trace = tmp_path / output.data["execution_trace_path"]
    trace.write_text("[]\n")
    with pytest.raises(AssertionError, match="hash mismatch"):
        check_cases(output, tmp_path)

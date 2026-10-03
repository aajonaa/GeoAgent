import hashlib

from geological_agent.bootstrap import create_agent
from geological_agent.contracts import ModelResponse, ToolCall


def call(name, args, identity):
    return ModelResponse(tool_calls=(ToolCall(identity, name, args),), finish_reason="tool_calls")


def review(outputs=(), evidence=()):
    return call("assess_completion", {"verdict": "complete", "feedback": "Observed results satisfy the task",
        "required_outputs": list(outputs), "requires_python_execution": False,
        "evidence_call_ids": list(evidence)}, "assessment")


class Model:
    def __init__(self, *responses):
        self.responses, self.requests = iter(responses), []

    def invoke(self, request):
        self.requests.append(request)
        return next(self.responses)


def test_empty_or_unauthorized_answer_revision_does_not_reopen_tools(tmp_path):
    good = 'summary.json\n```json\n{"value":42}\n```'
    model = Model(call("write_file", {"path": "summary.json", "content": '{"value":42}'}, "w1"),
        ModelResponse("Created summary.json."), review(("summary.json",), ("w1",)),
        ModelResponse('summary.json\n```json\n{"value":42000}\n```'), ModelResponse(""),
        call("write_file", {"path": "unexpected.txt", "content": "must not execute"}, "forbidden"),
        ModelResponse(good), review(("summary.json",), ("w1",)))
    result = create_agent(model).run("Create summary.json with value 42", workspace=tmp_path)
    assert result.status == "completed" and result.answer == good
    assert all(request.tool_choice == "none" and not request.tools for request in model.requests[4:7])
    assert not (tmp_path / "unexpected.txt").exists()
    assert len([m for m in result.state["messages"] if m.role == "tool"]) == 1


def test_identical_observation_produces_progress_feedback(tmp_path):
    (tmp_path / "input.txt").write_text("42")
    model = Model(call("read_file", {"path": "input.txt"}, "r1"),
        call("read_file", {"path": "input.txt"}, "r2"), ModelResponse("The file contains 42."), review(evidence=("r2",)),
        ModelResponse("The file contains 42."), review(evidence=("r2",)))
    result = create_agent(model).run("Read input.txt", workspace=tmp_path)
    assert result.status == "completed"
    assert any("added no new evidence" in message.content for message in model.requests[2].messages)
    assert len([m for m in result.state["messages"] if m.role == "tool"]) == 2


def test_rereading_changed_file_is_not_flagged_as_repeated_evidence(tmp_path):
    path = tmp_path / "input.txt"
    path.write_text("42")
    model = Model(call("read_file", {"path": "input.txt"}, "r1"),
        call("write_file", {"path": "input.txt", "content": "43", "expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}, "w1"),
        call("read_file", {"path": "input.txt"}, "r2"), ModelResponse("The updated file contains 43."), review(("input.txt",), ("w1", "r2")),
        ModelResponse("The updated file contains 43."), review(("input.txt",), ("w1", "r2")))
    result = create_agent(model).run("Change input.txt to 43 and read it back", workspace=tmp_path)
    assert result.status == "completed"
    assert not any("added no new evidence" in message.content for message in model.requests[3].messages)


def test_failed_invalid_arguments_do_not_break_subsequent_success(tmp_path):
    model = Model(call("write_file", "{", "bad"),
        call("write_file", {"path": "result.txt", "content": "42"}, "good"),
        ModelResponse("Created result.txt containing 42."), review(("result.txt",), ("good",)),
        ModelResponse("Created result.txt containing 42."), review(("result.txt",), ("good",)))
    result = create_agent(model).run("Create result.txt containing 42", workspace=tmp_path)
    assert result.status == "completed"
    assert (tmp_path / "result.txt").read_text() == "42"

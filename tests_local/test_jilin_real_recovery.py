"""Real-data lineage and isolated scientific execution regressions."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from threading import Event
import zipfile

import pytest

from geological_agent.contracts import ToolCall, ToolResult
from geological_agent.settings import Settings
from geological_agent.tool_evidence import EvidenceLedger, reference_gaps
from geological_agent.tools import (
    Tool, ToolDefinition, ToolExecutionContext, ToolExecutor, ToolOutput,
    ToolRegistry, object_schema, register_file_tools, execute_python, ToolFailure,
)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def setup(work):
    tools = ToolRegistry()
    register_file_tools(tools)
    tools.register(Tool(ToolDefinition(
        "lookup", "Read caller records", "Inspect source data",
        object_schema({"path": {"type": "string"}}, ["path"]),
        object_schema({"body": {"type": "string"}}, ["body"])),
        lambda args, ctx: ToolOutput({"body": ctx.path(args["path"]).read_text()}),
        input_paths=("path",), reference_paths=("path",)))
    ctx = ToolExecutionContext("fixture", work, tools.names(), Settings(), Event())
    EvidenceLedger(ctx)
    return tools, ctx, ToolExecutor(tools)

def supplied(ctx, name, data):
    ctx.path(name).write_bytes(data)
    ctx.evidence_state["files"][name] = {
        "origin": "user_supplied", "sha256": sha(data),
        "scope": "Caller upload, not independent scientific verification"}

def query(executor, ctx, path, call_id="lookup"):
    return executor.execute(ToolCall(call_id, "lookup", {"path": path}), ctx)

def state(ctx, result):
    return {"messages": [result.message()],
            "metadata": {"tool_evidence": ctx.evidence_state}}

def test_exact_uploaded_copy_is_caller_data_not_external_certification(tmp_path):
    _, ctx, executor = setup(tmp_path)
    supplied(ctx, "original.csv", b"id,value\n1,2\n")
    result = executor.execute(ToolCall("copy", "write_file", {
        "path": "copy.csv", "content": "id,value\n1,2\n"}), ctx)
    assert result.status == "ok"
    result = query(executor, ctx, "copy.csv")
    assert result.evidence["input_files"][0]["origin"] == "user_supplied"
    assert not reference_gaps(state(ctx, result))
    changed = executor.execute(ToolCall("change", "write_file", {
        "path": "changed.csv", "content": "id,value\n1,200\n"}), ctx)
    assert changed.status == "ok"
    assert reference_gaps(state(ctx, query(executor, ctx, "changed.csv")))

def test_zip_member_inherits_exact_hash_and_archive_identity(tmp_path):
    _, ctx, executor = setup(tmp_path)
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("data.csv", "id,value\n1,2\n")
    supplied(ctx, "source.zip", archive.read_bytes())
    result = executor.execute(ToolCall("extract", "execute_python", {
        "code": "from zipfile import ZipFile\nwith ZipFile('source.zip') as z:\n z.extractall('unpacked')\n"}), ctx)
    assert result.status == "ok", result.error
    row = ctx.evidence_state["files"]["unpacked/data.csv"]
    assert row["origin"] == "user_supplied"
    assert row["sha256"] == sha(b"id,value\n1,2\n")
    assert row["lineage"] == {
        "kind": "exact_archive_member", "parent_path": "source.zip",
        "parent_sha256": sha(archive.read_bytes()), "member_path": "data.csv"}
    assert not reference_gaps(state(ctx, query(executor, ctx, "unpacked/data.csv")))

def test_resume_resolves_old_unknown_observation_without_rewriting_it(tmp_path):
    _, ctx, executor = setup(tmp_path)
    (tmp_path / "unpacked").mkdir()
    (tmp_path / "unpacked/data.csv").write_bytes(b"id,value\n1,2\n")
    previous = query(executor, ctx, "unpacked/data.csv")
    old_message = deepcopy(previous.message())
    assert reference_gaps(state(ctx, previous))
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("data.csv", "id,value\n1,2\n")
    supplied(ctx, "source.zip", archive.read_bytes())
    # The historical path may not have an artifact-origin entry.
    ctx.evidence_state["files"]["unpacked/data.csv"] = {
        "origin": "derived_unverified", "sha256": sha(b"id,value\n1,2\n")}
    EvidenceLedger(ctx).reconcile()
    assert previous.message() == old_message
    assert not reference_gaps(state(ctx, previous))
    (tmp_path / "unpacked/data.csv").write_bytes(b"id,value\n1,999\n")
    latest = query(executor, ctx, "unpacked/data.csv", "new-hash")
    assert reference_gaps(state(ctx, latest))
    assert previous.message() == old_message

@pytest.mark.parametrize("bad_name", ["../escape.csv", "/absolute.csv", "C:drive.csv", "bad\\name.csv"])
def test_unsafe_archive_cannot_create_a_trusted_member(tmp_path, bad_name):
    _, ctx, executor = setup(tmp_path)
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(bad_name, "bad")
        z.writestr("data.csv", "id,value\n1,2\n")
    supplied(ctx, "source.zip", archive.read_bytes())
    (tmp_path / "data.csv").write_bytes(b"id,value\n1,2\n")
    assert reference_gaps(state(ctx, query(executor, ctx, "data.csv")))

def test_tampered_archive_and_model_authored_archive_remain_unverified(tmp_path):
    _, ctx, executor = setup(tmp_path)
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("data.csv", "original")
    supplied(ctx, "source.zip", archive.read_bytes())
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("data.csv", "tampered")
    (tmp_path / "data.csv").write_text("tampered")
    assert reference_gaps(state(ctx, query(executor, ctx, "data.csv")))
    ctx.evidence_state["files"]["source.zip"] = {
        "origin": "model_authored", "sha256": sha(archive.read_bytes())}
    assert reference_gaps(state(ctx, query(executor, ctx, "data.csv", "model-archive")))

def test_duplicate_archive_members_are_not_promoted(tmp_path):
    _, ctx, executor = setup(tmp_path)
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("data.csv", "first")
        with pytest.warns(UserWarning):
            z.writestr("data.csv", "second")
    supplied(ctx, "source.zip", archive.read_bytes())
    (tmp_path / "data.csv").write_text("second")
    assert reference_gaps(state(ctx, query(executor, ctx, "data.csv")))

def test_configured_dependencies_preserve_isolated_mode_and_assertion_trace(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    deps = tmp_path / "dependencies"
    deps.mkdir()
    (deps / "approved_fixture.py").write_text("value=7\n")
    (work / "approved_fixture.py").write_text("value=999\n")
    monkeypatch.setenv("GEOTOOL_PYTHON_PACKAGES", str(deps))
    monkeypatch.setenv("PYTHONPATH", str(work))
    _, ctx, _ = setup(work)
    output = execute_python({"code": "import sys,approved_fixture\nassert sys.flags.isolated == 1\nassert approved_fixture.value == 7\nprint('approved')\n"}, ctx)
    assert output.data["return_code"] == 0
    assert output.data["stdout"].strip() == "approved"
    assert output.data["execution_record_complete"]
    assert any(e["event"] == "assertion" and e["status"] == "completed_without_exception"
               for e in output.data["execution_events"])

def test_workspace_dependency_path_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_PYTHON_PACKAGES", str(tmp_path))
    _, ctx, _ = setup(tmp_path)
    with pytest.raises(ToolFailure, match="dependency directory"):
        execute_python({"code": "print('must not execute')"}, ctx)

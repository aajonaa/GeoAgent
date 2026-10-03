"""Regression coverage for the real missing-file / fabricated-source incident."""
from dataclasses import replace
import hashlib
import json
from threading import Event

import pytest

from geological_agent.agent.compaction import fit_request, request_size, unpack_data
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import Message, ModelRequest, ModelResponse, ToolCall, ToolResult
from geological_agent.settings import Settings
from geological_agent.team.store import Store
from geological_agent.tool_evidence import EvidenceLedger, reference_gaps
from geological_agent.tools import (Tool, ToolDefinition, ToolExecutionContext,
    ToolExecutor, ToolFailure, ToolOutput, ToolRegistry, object_schema, register_file_tools)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def context(tmp_path, registry):
    ctx = ToolExecutionContext("test", tmp_path, registry.names(), Settings(), Event())
    EvidenceLedger(ctx)
    return ctx


def registry():
    calls = []
    tools = ToolRegistry()
    register_file_tools(tools)
    schema = object_schema({"dataset_path": {"type": "string"}, "limit": {"type": "integer"}},
                           ["dataset_path"])
    def query(args, ctx):
        calls.append(args)
        path = ctx.path(args["dataset_path"])
        if not path.is_file():
            raise ToolFailure("missing_input", "Input file not found: " + args["dataset_path"], retryable=True)
        return ToolOutput({"content": path.read_text(encoding="utf-8")})
    tools.register(Tool(ToolDefinition("records", "Query source records", "Lookup", schema,
                                      object_schema({"content": {"type": "string"}}, ["content"])),
                        query, input_paths=("dataset_path",), reference_paths=("dataset_path",)))
    return tools, calls


def run(executor, ctx, name, args, identity):
    return executor.execute(ToolCall(identity, name, args), ctx)


def test_missing_file_is_not_reexecuted_when_only_limit_changes(tmp_path):
    tools, called = registry()
    executor, ctx = ToolExecutor(tools), context(tmp_path, tools)
    results = [run(executor, ctx, "records", {"dataset_path": "absent.csv", "limit": n}, str(n))
               for n in (1, 2, 3)]
    assert len(called) == 1
    assert results[0].error.code == "missing_input"
    assert all(r.error.code == "unchanged_failure" for r in results[1:])
    assert results[-1].evidence["suppressed_attempts"] == 2
    assert EvidenceLedger(ctx).pending_missing()


def test_actual_file_change_reenables_execution(tmp_path):
    tools, called = registry()
    executor, ctx = ToolExecutor(tools), context(tmp_path, tools)
    for i in range(3):
        run(executor, ctx, "records", {"dataset_path": "real.csv"}, str(i))
    (tmp_path / "real.csv").write_bytes(b"actual caller input")
    ctx.evidence_state["files"]["real.csv"] = {"origin": "user_supplied", "sha256": sha(b"actual caller input")}
    result = run(executor, ctx, "records", {"dataset_path": "real.csv"}, "new")
    assert result.status == "ok" and len(called) == 2
    assert not EvidenceLedger(ctx).pending_missing()
    assert not reference_gaps({"messages": [result.message()]})


@pytest.mark.parametrize("origin", ["unknown", "model_authored", "derived_unverified"])
def test_unverified_input_cannot_be_reference_evidence(tmp_path, origin):
    tools, _ = registry()
    executor, ctx = ToolExecutor(tools), context(tmp_path, tools)
    data = b"dep_id,source_url\n10134066,https://mrdata.usgs.gov/mrds/show-mrds.php?dep_id=10134066\n"
    (tmp_path / "records.csv").write_bytes(data)
    ctx.evidence_state["files"]["records.csv"] = {"origin": origin, "sha256": sha(data)}
    result = run(executor, ctx, "records", {"dataset_path": "records.csv"}, "lookup")
    assert result.status == "ok"  # Native tool computation remains usable.
    gaps = reference_gaps({"messages": [result.message()]})
    assert len(gaps) == 1 and gaps[0]["origin"] == origin


def test_hash_change_invalidates_old_source_origin(tmp_path):
    tools, _ = registry()
    ctx = context(tmp_path, tools)
    (tmp_path / "data.csv").write_bytes(b"new model content")
    ctx.evidence_state["files"]["data.csv"] = {"origin": "user_supplied", "sha256": sha(b"original")}
    result = run(ToolExecutor(tools), ctx, "records", {"dataset_path": "data.csv"}, "new")
    assert reference_gaps({"messages": [result.message()]})[0]["origin"] == "unknown"


def test_model_written_url_does_not_create_source_provenance(tmp_path):
    tools, _ = registry()
    executor, ctx = ToolExecutor(tools), context(tmp_path, tools)
    run(executor, ctx, "write_file", {"path": "data.csv", "content": "source_url\nhttps://usgs.gov\n"}, "write")
    result = run(executor, ctx, "records", {"dataset_path": "data.csv"}, "lookup")
    assert reference_gaps({"messages": [result.message()]})[0]["origin"] == "model_authored"


def test_exact_observed_source_copy_is_distinct_from_model_transformation(tmp_path):
    tools, _ = registry()
    body = "id,country\n1,Exampleland\n"
    tools.register(Tool(ToolDefinition("web_fetch", "Fetch", "Source", object_schema({}), object_schema({
        "content": {"type": "string"}, "url": {"type": "string"}})),
        lambda args, ctx: ToolOutput({"content": body, "url": "https://example.org/source.csv"})))
    executor, ctx = ToolExecutor(tools), context(tmp_path, tools)
    run(executor, ctx, "web_fetch", {}, "fetch")
    run(executor, ctx, "write_file", {"path": "copy.csv", "content": body}, "copy")
    result = run(executor, ctx, "records", {"dataset_path": "copy.csv"}, "lookup")
    assert not reference_gaps({"messages": [result.message()]})
    run(executor, ctx, "write_file", {"path": "changed.csv", "content": body.replace("1,", "99,")}, "change")
    result = run(executor, ctx, "records", {"dataset_path": "changed.csv"}, "lookup2")
    assert reference_gaps({"messages": [result.message()]})


def test_corrected_query_supersedes_bad_version_without_deleting_history(tmp_path):
    tools, _ = registry()
    executor, ctx = ToolExecutor(tools), context(tmp_path, tools)
    (tmp_path / "records.csv").write_bytes(b"unverified")
    first = run(executor, ctx, "records", {"dataset_path": "records.csv"}, "first")
    (tmp_path / "actual.csv").write_bytes(b"caller")
    ctx.evidence_state["files"]["actual.csv"] = {"origin": "user_supplied", "sha256": sha(b"caller")}
    second = run(executor, ctx, "records", {"dataset_path": "actual.csv"}, "second")
    messages = [first.message(), second.message()]
    assert reference_gaps({"messages": [first.message()]})
    assert not reference_gaps({"messages": messages})
    assert len(messages) == 2


def test_generated_nonreference_files_remain_usable(tmp_path):
    tools, _ = registry()
    original = tools.get("records")
    tools._tools["records"] = replace(original, reference_paths=())
    executor, ctx = ToolExecutor(tools), context(tmp_path, tools)
    run(executor, ctx, "write_file", {"path": "simulation.csv", "content": "value\n5\n"}, "create")
    result = run(executor, ctx, "records", {"dataset_path": "simulation.csv"}, "compute")
    assert result.status == "ok" and not reference_gaps({"messages": [result.message()]})


def test_transient_failure_is_not_cached_as_deterministic(tmp_path):
    tools, called = registry()
    def transient(args, ctx):
        called.append(args)
        raise ToolFailure("network_error", "temporary", retryable=True)
    tools._tools["records"] = replace(tools.get("records"), handler=transient)
    executor, ctx = ToolExecutor(tools), context(tmp_path, tools)
    for i in range(2):
        result = run(executor, ctx, "records", {"dataset_path": "absent.csv"}, str(i))
        assert result.error.code == "network_error"
    assert len(called) == 2


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path)
    with result.db:
        result.db.executemany("INSERT INTO users VALUES (?,?,?,?,?)",
                             [("alice", "alice", "unused", "member", 0), ("bob", "bob", "unused", "member", 0)])
    yield result
    result.db.close()


def test_origins_persist_by_owner_generation_and_hash(store):
    cid = store.create_conversation("alice")["id"]
    origin = {"origin": "model_authored", "sha256": sha(b"fake")}
    generation = store.snapshot("alice", cid, {"data.csv": b"fake"}, origins={"data.csv": origin})
    store.snapshot("alice", cid, {"data.csv": b"fake", "note.txt": b"hello"})
    assert store.file_origins("alice", cid)["data.csv"] == origin
    assert store.file_origins("alice", cid, generation)["data.csv"] == origin
    assert store.file_origins("alice", cid)["note.txt"]["origin"] == "unknown"
    with pytest.raises(KeyError):
        store.file_origins("bob", cid)
    store.snapshot("alice", cid, {"data.csv": b"new"})
    assert store.file_origins("alice", cid)["data.csv"]["origin"] == "unknown"
    assert store.files("alice", cid, generation)["data.csv"] == b"fake"


def test_legacy_file_is_unknown_not_promoted_to_user_source(store):
    cid = store.create_conversation("alice")["id"]
    generation = store.snapshot("alice", cid, {"data.csv": b"legacy"})
    with store.db:
        store.db.execute("DELETE FROM file_origins WHERE cid=?", (cid,))
    assert store.file_origins("alice", cid, generation)["data.csv"]["origin"] == "unknown"


class Scripted:
    def __init__(self, responses):
        self.responses = iter(responses)
    def invoke(self, request):
        return next(self.responses)


def reply(name, args, i):
    return ModelResponse(tool_calls=(ToolCall(i, name, args),), finish_reason="tool_calls")


def test_real_mineral_incident_cannot_publish_completed(tmp_path, monkeypatch):
    for name in ("GEOTOOL_INTENT_REVIEW", "GEOTOOL_REQUIREMENT_COVERAGE", "GEOTOOL_COMBINED_COMPLETION_REVIEW"):
        monkeypatch.delenv(name, raising=False)
    agent = create_agent(object(), settings=Settings(verify_completion=False, max_model_turns=12))
    sid = next(s.id for s in agent.skills.registry.list()
               if "MineralResourcesSearchDeposits" in agent.skills.load(s.id).tool_names)
    csv = "dep_id,country,commod1,latitude,longitude\n10134066,China,Nickel,38.99825,102.49969\n"
    lookup = {"dataset_path": "mrds_china.csv", "country": "China", "commodity": "Nickel", "limit": 1}
    agent.model = Scripted([
        reply("write_file", {"path": "mrds_china.csv", "content": csv}, "write"),
        reply("MineralResourcesSearchDeposits", lookup, "lookup1"),
        ModelResponse("A verified external catalog contains this mine."),
        reply("MineralResourcesSearchDeposits", lookup, "lookup2"),
        ModelResponse("A verified external catalog contains this mine."),
    ])
    outcome = agent.run("Find a real nickel mine in China from an actual source.", workspace=tmp_path, skill_id=sid)
    assert outcome.status == "incomplete", outcome.reason
    assert "provenance" in outcome.reason
    assert (tmp_path / "mrds_china.csv").read_text() == csv
    assert outcome.state["metadata"]["tool_evidence"]["files"]["mrds_china.csv"]["origin"] == "model_authored"


class Archive:
    def __init__(self):
        self.rows = {}
    def put(self, run_id, kind, key, payload, label=""):
        self.rows[key] = payload
        return {"evidence_id": "ev_" + key, "sha256": key, "source_run_id": run_id,
                "kind": kind, "total_chars": len(json.dumps(payload))}


def test_archive_index_fits_actual_budget_without_evicting_fitting_evidence():
    messages = [Message("user", "Keep exact user requirements.")]
    for i in range(15):
        call = ToolCall(str(i), "lookup", {"part": i})
        messages += [Message("assistant", "old working prose " * 12, (call,)),
                     ToolResult(str(i), "lookup", "error", {"details": str(i) * 2500}).message()]
    state = {"run_id": "a"*32, "task": messages[0].content, "messages": messages, "metadata": {}}
    request = ModelRequest((Message("system", "protected schema/policy " * 1200), *messages), ())
    archive, summaries = Archive(), []
    def summarize(source, target):
        summaries.append((source, target))
        return "Earlier failed inspections; source still needed."
    fitted = fit_request(request, state, Settings(max_context_chars=48000), archive=archive, summarize=summarize)
    assert request_size(fitted) <= 48000
    assert fitted.messages[0] == request.messages[0] and fitted.messages[-2:] == request.messages[-2:]
    originals = {m.tool_call_id: m.content for m in messages if m.role == "tool"}
    retained = {m.tool_call_id: m.content for m in fitted.messages if m.role == "tool"}
    assert {"13", "14"} <= set(retained)
    assert all(unpack_data(json.loads(content)) == json.loads(originals[identity])
               for identity, content in retained.items())
    assert len(archive.rows) == 14
    assert state["messages"] == messages
    assert state["metadata"]["context_compactions"][-1]["headroom_chars"] == 48000 - request_size(fitted)

def test_reference_guidance_is_loaded_only_with_reference_tools(tmp_path):
    agent = create_agent(object(), settings=Settings(verify_completion=False))
    state = {"task": "Inspect input", "messages": [Message("user", "Inspect input")],
             "selected_skill_ids": [], "exposed_tool_names": ["read_file"], "metadata": {}}
    plain = agent.context.build(state)
    assert "Reference-data provenance:" not in plain.messages[0].content
    state["exposed_tool_names"].append("MineralResourcesSearchDeposits")
    sourced = agent.context.build(state)
    assert "Reference-data provenance:" in sourced.messages[0].content
    assert "Model-authored or unknown-origin rows" in sourced.messages[0].content


def test_short_assistant_drafts_can_be_compacted_when_they_cause_overflow():
    call1, call2 = ToolCall("one", "inspect", {}), ToolCall("two", "inspect", {})
    messages = [Message("user", "exact task"), Message("assistant", "a" * 2975, (call1,)),
                ToolResult("one", "inspect", "ok", {"source": "b" * 2000}).message(),
                Message("assistant", tool_calls=(call2,)), ToolResult("two", "inspect", "ok", {"n": 2}).message()]
    state = {"run_id": "b"*32, "task": "exact task", "messages": messages, "metadata": {}}
    request = ModelRequest((Message("system", "p" * 7000), *messages), ())
    summaries = []
    def summarize(source, target):
        summaries.append(target)
        return "Prior inspection, original source archived."
    fitted = fit_request(request, state, Settings(max_context_chars=10000), archive=Archive(), summarize=summarize)
    assert request_size(fitted) <= 10000 and summaries
    assert state["messages"] == messages

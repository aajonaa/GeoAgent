"""Resource availability and acquisition recovery without paid APIs or live data."""
import hashlib
import json
from pathlib import Path

import pytest

from geological_agent.agent.resource_policy import resource_request, workspace_files
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import ModelResponse, ToolCall
from geological_agent.settings import Settings
from geological_agent.tools import Tool, ToolDefinition, ToolFailure, ToolOutput, object_schema


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    for key in ("GEOTOOL_INTENT_REVIEW", "GEOTOOL_REQUIREMENT_COVERAGE",
                "GEOTOOL_COMBINED_COMPLETION_REVIEW", "GEOTOOL_OPTIMIZE_ROUND_TRIPS",
                "GEOTOOL_COMPACT_REVIEW", "GEOTOOL_COMPACT_DISCOVERY",
                "GEOTOOL_REVIEW_REFERENCE_SETS", "GEOTOOL_WEB_ENABLED"):
        monkeypatch.delenv(key, raising=False)


class Scripted:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        response = next(self.responses)
        return response(request) if callable(response) else response


def native(name, args, identity):
    return ModelResponse(tool_calls=(ToolCall(identity, name, args),), finish_reason="tool_calls")


def make_agent(model, *, human=False, web=True):
    agent = create_agent(model, settings=Settings(verify_completion=False, max_model_turns=12),
                         human_input=human)
    calls = []
    def query(args, ctx):
        calls.append(args)
        path = ctx.path(args["dataset_path"])
        if not path.is_file():
            raise ToolFailure("missing_input", "Input file not found: " + args["dataset_path"], retryable=True)
        return ToolOutput({"content": path.read_text(encoding="utf-8")})
    agent.tools.register(Tool(ToolDefinition("catalog_lookup", "Read reference records", "Existing source table",
        object_schema({"dataset_path": {"type": "string"}}, ["dataset_path"]),
        object_schema({"content": {"type": "string"}}, ["content"])), query,
        input_paths=("dataset_path",), reference_paths=("dataset_path",)))
    names = ["catalog_lookup"]
    if web:
        agent.tools.register(Tool(ToolDefinition("web_search", "Search public sources", "Public source discovery",
            object_schema({"query": {"type": "string"}}, ["query"]),
            object_schema({"results": {"type": "array", "items": {"type": "object"}}}, ["results"])),
            lambda args, ctx: ToolOutput({"results": [{"url": "https://example.org/record/42",
                "title": "Synthetic acceptance source", "snippet": "Test-only record 42"}]})))
        agent.tools.register(Tool(ToolDefinition("web_fetch", "Read public source", "Inspect an observed source URL",
            object_schema({"url": {"type": "string"}}, ["url"]),
            object_schema({"url": {"type": "string"}, "content": {"type": "string"}}, ["url", "content"])),
            lambda args, ctx: ToolOutput({"url": args["url"], "content": "dep_id,country\n42,Exampleland\n"})))
        names += ["web_search", "web_fetch"]
    agent.base_tools = (*agent.base_tools, *names)
    return agent, calls


def records(outcome):
    return [json.loads(message.content) for message in outcome.state["messages"] if message.role == "tool"]


def tool_names(request):
    return {tool.name for tool in request.tools}


def test_empty_workspace_hides_file_query_without_changing_registry(tmp_path):
    def choose(request):
        assert "catalog_lookup" not in tool_names(request)
        assert {"web_search", "web_fetch"} <= tool_names(request)
        assert '"files": []' in request.messages[-1].content
        return native("web_search", {"query": "Public catalog record"}, "search")
    model = Scripted(choose, native("web_fetch", {"url": "https://example.org/record/42"}, "fetch"),
                     ModelResponse("The synthetic observed record has dep_id 42, country Exampleland."))
    agent, calls = make_agent(model)
    result = agent.run("Find a public source record.", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert [row["name"] for row in records(result)] == ["web_search", "web_fetch"]
    assert not calls and not result.artifacts
    assert agent.tools.get("catalog_lookup").definition.input_schema["required"] == ["dataset_path"]


def test_unavailable_native_call_is_never_executed_and_can_recover(tmp_path):
    model = Scripted(native("catalog_lookup", {"dataset_path": "invented.csv"}, "invalid"),
        native("web_search", {"query": "Public record"}, "search"),
        native("web_fetch", {"url": "https://example.org/record/42"}, "fetch"),
        ModelResponse("Observed test record 42."))
    agent, calls = make_agent(model)
    result = agent.run("Find a public source record.", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert not calls
    assert len(result.state["metadata"]["protocol_failures"]) == 1
    assert model.requests[1].tool_choice == "required"
    assert [row["name"] for row in records(result)] == ["web_search", "web_fetch"]


def test_repeated_unavailable_native_calls_pause_without_execution(tmp_path):
    model = Scripted(native("catalog_lookup", {"dataset_path": "invented.csv"}, "one"),
                     native("catalog_lookup", {"dataset_path": "different.csv"}, "two"))
    agent, calls = make_agent(model, human=True)
    result = agent.run("Find a record.", workspace=tmp_path/"work", checkpoint_path=tmp_path/"cp.sqlite3")
    assert result.status == "needs_input"
    assert result.state["metadata"]["pending_input"]["reason_type"] == "model_protocol"
    assert not calls and not records(result) and not result.artifacts


def test_real_new_file_reenables_native_query_with_observed_source_origin(tmp_path):
    body = "dep_id,country\n42,Exampleland\n"
    def lookup(request):
        assert "catalog_lookup" in tool_names(request)
        return native("catalog_lookup", {"dataset_path": "source.csv"}, "lookup")
    model = Scripted(native("web_fetch", {"url": "https://example.org/record/42"}, "fetch"),
                     native("write_file", {"path": "source.csv", "content": body}, "save"),
                     lookup, ModelResponse("Observed record 42 in Exampleland."))
    agent, calls = make_agent(model)
    result = agent.run("Use the supplied source URL https://example.org/record/42.", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert len(calls) == 1 and len(records(result)) == 3
    assert records(result)[-1]["evidence"]["input_files"][0]["origin"] == "retrieved"
    assert (tmp_path/"source.csv").read_text() == body


def test_existing_user_file_keeps_local_query_usable(tmp_path):
    data = b"dep_id,country\n42,Exampleland\n"
    (tmp_path/"given.csv").write_bytes(data)
    model = Scripted(native("catalog_lookup", {"dataset_path": "given.csv"}, "read"),
                     ModelResponse("The supplied record is 42."))
    agent, calls = make_agent(model)
    result = agent.run("Query my supplied table, do not browse.", workspace=tmp_path,
        input_origins={"given.csv": {"origin": "user_supplied", "sha256": hashlib.sha256(data).hexdigest()}})
    assert result.status == "completed", result.reason
    assert len(calls) == 1 and [row["name"] for row in records(result)] == ["catalog_lookup"]
    assert "catalog_lookup" in tool_names(model.requests[0])


def test_missing_input_gets_actionable_correction_on_first_error(tmp_path):
    (tmp_path/"existing.txt").write_text("Unrelated caller file")
    def repair(request):
        assert request.tool_choice == "required"
        assert any("Runtime resource correction:" in msg.content for msg in request.messages)
        assert any("existing.txt" in msg.content for msg in request.messages)
        return native("web_search", {"query": "Public record"}, "search")
    model = Scripted(native("catalog_lookup", {"dataset_path": "missing.csv"}, "missing"), repair,
                     native("web_fetch", {"url": "https://example.org/record/42"}, "fetch"),
                     ModelResponse("Observed public test record 42."))
    agent, calls = make_agent(model)
    result = agent.run("Find a public source record.", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert len(calls) == 1
    assert [row["name"] for row in records(result)] == ["catalog_lookup", "web_search", "web_fetch"]
    assert records(result)[0]["error"]["code"] == "missing_input"


def test_plain_local_runtime_preserves_error_observations(tmp_path):
    agent, calls = make_agent(Scripted(native("catalog_lookup", {"dataset_path": "missing.csv"}, "missing"),
                                      ModelResponse("The requested local input is missing.")), web=False)
    result = agent.run("Inspect a local record.", workspace=tmp_path)
    assert len(calls) == 1
    assert records(result)[0]["error"]["code"] == "missing_input"
    assert result.state["metadata"].get("resource_availability") is None


def test_internal_web_cache_is_not_a_reference_input(tmp_path):
    cache = tmp_path/".agent"/"web"
    cache.mkdir(parents=True)
    (cache/"source.json").write_text('{"content":"Cached excerpt"}')
    assert workspace_files(tmp_path) == []
    folder = tmp_path/"user-data"
    folder.mkdir()
    (folder/"given.csv").write_text("id\n42\n")
    assert workspace_files(tmp_path) == ["user-data/given.csv"]


def test_external_symlink_is_not_advertised_as_input(tmp_path):
    outside = tmp_path/"outside"
    outside.mkdir()
    (outside/"source.csv").write_text("id\n42\n")
    work = tmp_path/"work"
    work.mkdir()
    try:
        (work/"linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires a Windows privilege; exercised on A100")
    assert workspace_files(work) == []


def test_optional_reference_path_does_not_disable_independent_operations(tmp_path):
    from dataclasses import replace
    agent, _ = make_agent(object())
    tool = agent.tools.get("catalog_lookup")
    definition = replace(tool.definition, input_schema=object_schema({"dataset_path": {"type": "string"}}))
    agent.tools._tools["catalog_lookup"] = replace(tool, definition=definition)
    from geological_agent.contracts import ModelRequest
    request = ModelRequest((), agent.tools.definitions(agent.base_tools))
    filtered, _ = resource_request(request, agent.tools, tmp_path)
    assert "catalog_lookup" in tool_names(filtered)


def test_generated_file_availability_is_not_source_authentication(tmp_path):
    body = "dep_id,country\n42,Exampleland\n"
    model = Scripted(native("write_file", {"path": "guessed.csv", "content": body}, "write"),
        native("catalog_lookup", {"dataset_path": "guessed.csv"}, "lookup1"),
        ModelResponse("The external catalog has record 42."),
        native("catalog_lookup", {"dataset_path": "guessed.csv"}, "lookup2"),
        ModelResponse("The external catalog has record 42."))
    agent, calls = make_agent(model)
    result = agent.run("Find a real external record.", workspace=tmp_path)
    assert result.status == "incomplete", result.reason
    assert "provenance" in result.reason and len(calls) == 2
    assert result.state["metadata"]["tool_evidence"]["files"]["guessed.csv"]["origin"] == "model_authored"


def test_real_provider_failure_can_pause_for_missing_input(tmp_path):
    from dataclasses import replace
    model = Scripted(native("web_search", {"query": "Public source"}, "search"),
        native("request_user_input", {"question": "Please supply the source; the provider is not configured.",
            "reason": "Observed web_not_configured response.", "missing": ["source"], "options": []}, "ask"))
    agent, _ = make_agent(model, human=True)
    def unavailable(args, ctx):
        raise ToolFailure("web_not_configured", "Provider is not configured")
    agent.tools._tools["web_search"] = replace(agent.tools.get("web_search"), handler=unavailable)
    result = agent.run("Find a public record.", workspace=tmp_path/"work", checkpoint_path=tmp_path/"cp.sqlite3")
    assert result.status == "needs_input", result.reason
    assert records(result)[0]["error"]["code"] == "web_not_configured"
    assert result.state["metadata"]["pending_input"]["missing"] == ["source"]


def test_skill_supports_source_reading_without_fabricated_csv():
    agent = create_agent(object())
    skill = agent.skills.load("mineral_deposit_search")
    assert "Public source route" in skill.instructions
    assert "web_search" in skill.instructions and "web_fetch" in skill.instructions
    assert "NOT required" in skill.instructions
    assert "{'capability':" not in skill.instructions
    assert set(skill.tool_names) == {"MineralResourcesSearchDeposits", "MineralResourcesGetDeposit"}

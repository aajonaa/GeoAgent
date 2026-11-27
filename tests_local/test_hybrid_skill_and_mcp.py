"""P1-3 tests: Hybrid semantic+lexical skill retrieval and standard MCP client/adapter."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from threading import Event, Thread

import pytest

from geological_agent.bootstrap import build_registry, create_agent
from geological_agent.contracts import ToolCall
from geological_agent.mcp_client import (
    McpServerConfig,
    McpToolManager,
    load_mcp_configs,
    native_mcp_tool_name,
    register_mcp_tools,
)
from geological_agent.settings import Settings
from geological_agent.skill_search import SkillHybridIndex
from geological_agent.skills import Skill, SkillRegistry, SkillSummary
from geological_agent.tools import ToolExecutionContext, ToolExecutor, ToolRegistry


def _ctx(workspace: Path, allowed: tuple[str, ...]) -> ToolExecutionContext:
    return ToolExecutionContext("run-p1-3", workspace, allowed, Settings(), Event())


def test_bilingual_geoscience_skill_search_on_real_catalog(tmp_path):
    registry, skills, _ = build_registry()
    assert len(skills.registry.list()) >= 180

    # Chinese natural-language queries should retrieve English-authored geoscience skills.
    quake_hits = [s.id for s in skills.registry.list("计算地震震级对应的地震能量", limit=5)]
    assert "earthquake_energy" in quake_hits

    raster_hits = [s.id for s in skills.registry.list("栅格影像高程分析", limit=10)]
    assert any("raster" in sid or "dem" in sid or "remote" in sid or "image" in sid for sid in raster_hits), raster_hits

    hydro_hits = [s.id for s in skills.registry.list("流域水文径流模拟", limit=10)]
    assert any("hydro" in sid or "water" in sid or "runoff" in sid or "wflow" in sid for sid in hydro_hits), hydro_hits

    # Unrelated nonsense query must still return empty, never unrelated noise.
    assert skills.registry.list("zxqv_nonexistent_banana_999") == ()

    # skill_find tool honors optional `limit` and validates against strict schemas.
    executor = ToolExecutor(registry)
    res = executor.execute(
        ToolCall("c-find", "skill_find", {"query": "earthquake magnitude", "limit": 3}),
        _ctx(tmp_path, ("skill_find",)),
    )
    assert res.status == "ok", res
    assert 1 <= len(res.data["skills"]) <= 3
    assert res.data["skills"][0]["id"] == "earthquake_energy"


def test_hybrid_semantic_rrf_fusion_and_disk_cache(tmp_path):
    cache_file = tmp_path / "skill_embeds.json"

    class FakeEncoder:
        def __init__(self):
            self.doc_calls = 0
            self.query_calls = 0

        def embed(self, texts, *, query=False):
            if query:
                self.query_calls += 1
            else:
                self.doc_calls += 1
            out = []
            for t in texts:
                low = t.lower()
                if "porphyry" in low or "copper" in low or "斑岩" in low or "成矿斑岩体" in low:
                    out.append([1.0, 0.0, 0.0])
                elif "aquifer" in low or "darcy" in low or "地下含水层" in low:
                    out.append([0.0, 1.0, 0.0])
                elif "seismogram" in low or "wave" in low:
                    out.append([0.0, 0.0, 1.0])
                else:
                    # Orthogonal noise vector -> cosine 0.0 against all skills.
                    out.append([0.0, 0.0, 0.0])
            return out

    enc1 = FakeEncoder()
    idx1 = SkillHybridIndex(encoder=enc1, cache_path=cache_file, semantic_threshold=0.5)
    reg = SkillRegistry(hybrid_index=idx1)
    reg.register(Skill(
        SkillSummary("porphyry_model", "Porphyry Copper Assessment", "Assess copper porphyry systems", "Use for copper deposits"),
        (), "Use porphyry tools.", (), ("read_file",), (),
    ))
    reg.register(Skill(
        SkillSummary("aquifer_flow", "Aquifer Darcy Solver", "Compute Darcy hydraulic flux", "Use for aquifer flow"),
        (), "Use aquifer tools.", (), ("read_file",), (),
    ))
    reg.register(Skill(
        SkillSummary("wave_picker", "Seismogram Phase Picker", "Pick P and S waves", "Use for seismograms"),
        (), "Use seismic tools.", (), ("read_file",), (),
    ))

    # Query with zero direct English overlap with `porphyry_model` text, matched via dense embedding!
    hits = reg.list("成矿斑岩体远景评价")
    assert hits and hits[0].id == "porphyry_model"
    assert enc1.doc_calls == 1
    assert enc1.query_calls == 1
    assert idx1.last_search_meta["mode"] == "hybrid"
    assert cache_file.is_file()

    # Noise query below semantic_threshold and without lexical hits returns empty.
    assert reg.list("totally_unrelated_xyz_query") == ()

    # Second index instance loads embeddings from disk cache with ZERO document re-embedding!
    enc2 = FakeEncoder()
    idx2 = SkillHybridIndex(encoder=enc2, cache_path=cache_file, semantic_threshold=0.5)
    reg2 = SkillRegistry(hybrid_index=idx2)
    for skill in reg._skills.values():
        reg2.register(skill)
    hits2 = reg2.list("地下含水层渗透计算")
    assert hits2 and hits2[0].id == "aquifer_flow"
    assert enc2.doc_calls == 0
    assert enc2.query_calls == 1


_FAKE_STDIO_MCP_SERVER = r'''
import json, os, sys

for raw in sys.stdin:
    line = raw.strip()
    if not line:
        continue
    msg = json.loads(line)
    req_id = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}
    if req_id is None:
        continue
    if method == "initialize":
        resp = {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-geo-stdio", "version": "1.0"},
            },
        }
    elif method == "tools/list":
        cursor = params.get("cursor")
        if not cursor:
            resp = {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "calc_grade",
                            "description": "Compute contained metal tonnage from ore tonnage and grade pct.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "ore_tonnes": {"type": "number"},
                                    "grade_pct": {"type": "number"},
                                },
                                "required": ["ore_tonnes", "grade_pct"],
                            },
                            "annotations": {"readOnlyHint": True},
                        },
                        {
                            "name": "secret_denied",
                            "description": "Should be filtered out by deny_tools.",
                            "inputSchema": {"type": "object", "properties": {}},
                        },
                    ],
                    "nextCursor": "page-2",
                },
            }
        else:
            resp = {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "inspect_env",
                            "description": "Report allowed env var and secret non-leakage.",
                            "inputSchema": {"type": "object", "properties": {}},
                        },
                        {
                            "name": "fail_tool",
                            "description": "Always returns MCP isError=true.",
                            "inputSchema": {"type": "object", "properties": {}},
                        },
                    ],
                },
            }
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "calc_grade":
            metal = float(args["ore_tonnes"]) * float(args["grade_pct"]) / 100.0
            resp = {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"contained_metal={metal:.2f}"}],
                    "structuredContent": {"contained_metal_tonnes": metal},
                    "isError": False,
                },
            }
        elif name == "inspect_env":
            payload = {
                "allowed": os.environ.get("MCP_CUSTOM_FLAG"),
                "openai_leaked": "OPENAI_API_KEY" in os.environ,
                "secret_leaked": "TEAM_SECRET_TOKEN" in os.environ,
            }
            resp = {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(payload)}],
                    "structuredContent": payload,
                    "isError": False,
                },
            }
        elif name == "fail_tool":
            resp = {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": "simulated remote tool failure"}],
                    "isError": True,
                },
            }
        else:
            resp = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "unknown tool"}}
    else:
        resp = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "unknown method"}}
    sys.stdout.write(json.dumps(resp) + "\n")
    sys.stdout.flush()
'''


def test_stdio_mcp_server_discovery_execution_and_secret_hygiene(tmp_path, monkeypatch):
    server_script = tmp_path / "fake_mcp_server.py"
    server_script.write_text(_FAKE_STDIO_MCP_SERVER, encoding="utf-8")

    monkeypatch.setenv("OPENAI_API_KEY", "labelled-test-key-must-not-leak")
    monkeypatch.setenv("TEAM_SECRET_TOKEN", "labelled-test-token-must-not-leak")

    cfg = McpServerConfig(
        name="geo_stdio",
        transport="stdio",
        command=(sys.executable, "-u", str(server_script)),
        env={"MCP_CUSTOM_FLAG": "geo-enabled"},
        deny_tools=("secret_denied",),
        timeout_seconds=10.0,
    )
    registry = ToolRegistry()
    names, manager = register_mcp_tools(registry, configs=[cfg], fail_fast=True)
    assert manager is not None
    try:
        assert set(names) == {
            "mcp__geo_stdio__calc_grade",
            "mcp__geo_stdio__inspect_env",
            "mcp__geo_stdio__fail_tool",
        }
        assert "mcp__geo_stdio__secret_denied" not in names
        assert registry.get("mcp__geo_stdio__calc_grade").pure is True
        assert registry.get("mcp__geo_stdio__inspect_env").pure is False

        executor = ToolExecutor(registry)
        ctx = _ctx(tmp_path, names)

        # 1. Paginated tool invocation + structured content
        r_calc = executor.execute(
            ToolCall("c1", "mcp__geo_stdio__calc_grade", {"ore_tonnes": 500, "grade_pct": 1.6}),
            ctx,
        )
        assert r_calc.status == "ok", r_calc
        assert r_calc.data["text"] == "contained_metal=8.00"
        assert r_calc.data["structured_content"] == {"contained_metal_tonnes": 8.0}

        # 2. Secret hygiene check in spawned MCP subprocess
        r_env = executor.execute(ToolCall("c2", "mcp__geo_stdio__inspect_env", {}), ctx)
        assert r_env.status == "ok", r_env
        assert r_env.data["structured_content"] == {
            "allowed": "geo-enabled",
            "openai_leaked": False,
            "secret_leaked": False,
        }

        # 3. MCP isError=true maps cleanly to retryable ToolFailure
        r_fail = executor.execute(ToolCall("c3", "mcp__geo_stdio__fail_tool", {}), ctx)
        assert r_fail.status == "error"
        assert r_fail.error is not None and r_fail.error.code == "mcp_tool_error"
        assert "simulated remote tool failure" in r_fail.error.message
    finally:
        manager.close()


def test_http_mcp_server_json_and_sse_roundtrip(tmp_path):
    token_file = tmp_path / "mcp_token.txt"
    token_file.write_text("labelled-bearer-token-2026", encoding="utf-8")
    seen_sessions = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.headers.get("Authorization") != "Bearer labelled-bearer-token-2026":
                self.send_response(401)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            msg = json.loads(self.rfile.read(length).decode("utf-8"))
            req_id = msg.get("id")
            method = msg.get("method")
            if self.headers.get("Mcp-Session-Id"):
                seen_sessions.append(self.headers.get("Mcp-Session-Id"))
            if req_id is None:
                self.send_response(202)
                self.end_headers()
                return
            if method == "initialize":
                body = json.dumps({
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}},
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Mcp-Session-Id", "sess-geo-001")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif method == "tools/list":
                body = json.dumps({
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {
                        "tools": [{
                            "name": "lookup_mineral",
                            "description": "Lookup mineral formula via HTTP MCP.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"mineral": {"type": "string"}},
                                "required": ["mineral"],
                            },
                        }],
                    },
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif method == "tools/call":
                mineral = msg["params"]["arguments"]["mineral"]
                payload = json.dumps({
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"{mineral}: CuFeS2"}],
                        "structuredContent": {"mineral": mineral, "formula": "CuFeS2"},
                        "isError": False,
                    },
                })
                sse = f"event: message\ndata: {payload}\n\n".encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(sse)))
                self.end_headers()
                self.wfile.write(sse)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config_file = tmp_path / "mcp_servers.json"
        config_file.write_text(json.dumps({
            "mcpServers": {
                "mineral_http": {
                    "url": f"http://127.0.0.1:{port}/mcp",
                    "bearer_token_file": str(token_file),
                    "read_only": True,
                }
            }
        }), encoding="utf-8")
        configs = load_mcp_configs(config_file=config_file)
        assert len(configs) == 1 and configs[0].transport == "http" and configs[0].read_only is True

        registry = ToolRegistry()
        names, manager = register_mcp_tools(registry, configs=configs, fail_fast=True)
        try:
            assert names == ("mcp__mineral_http__lookup_mineral",)
            executor = ToolExecutor(registry)
            res = executor.execute(
                ToolCall("c-http", "mcp__mineral_http__lookup_mineral", {"mineral": "chalcopyrite"}),
                _ctx(tmp_path, names),
            )
            assert res.status == "ok", res
            assert res.data["text"] == "chalcopyrite: CuFeS2"
            assert res.data["structured_content"]["formula"] == "CuFeS2"
            assert "sess-geo-001" in seen_sessions
        finally:
            manager.close()
    finally:
        server.shutdown()
        server.server_close()


def test_mcp_bootstrap_and_read_only_mode_gating(tmp_path, monkeypatch):
    monkeypatch.delenv("GEOTOOL_MCP_CONFIG_FILE", raising=False)
    monkeypatch.delenv("GEOTOOL_MCP_SERVERS", raising=False)
    # Zero-impact default
    names_empty, mgr_empty = register_mcp_tools(ToolRegistry())
    assert names_empty == () and mgr_empty is None

    server_script = tmp_path / "fake_mcp_server.py"
    server_script.write_text(_FAKE_STDIO_MCP_SERVER, encoding="utf-8")
    ro_cfg = McpServerConfig(
        name="ro_srv",
        command=(sys.executable, "-u", str(server_script)),
        allow_tools=("calc_grade",),
        read_only=True,
    )
    rw_cfg = McpServerConfig(
        name="rw_srv",
        command=(sys.executable, "-u", str(server_script)),
        allow_tools=("inspect_env",),
        read_only=False,
    )

    agent_full = create_agent(None, mcp_servers=[ro_cfg, rw_cfg], read_only=False)
    try:
        assert "mcp__ro_srv__calc_grade" in agent_full.base_tools
        assert "mcp__rw_srv__inspect_env" in agent_full.base_tools
    finally:
        agent_full.tools.mcp_manager.close()

    agent_ask = create_agent(None, mcp_servers=[ro_cfg, rw_cfg], read_only=True)
    try:
        assert "mcp__ro_srv__calc_grade" in agent_ask.base_tools
        assert "mcp__rw_srv__inspect_env" not in agent_ask.base_tools
        assert "mcp__ro_srv__calc_grade" in agent_ask.tools.names()
        assert "mcp__rw_srv__inspect_env" not in agent_ask.tools.names()
    finally:
        agent_ask.tools.mcp_manager.close()

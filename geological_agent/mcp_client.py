"""Standard Model Context Protocol (MCP) JSON-RPC 2.0 client and native Tool adapter.

Supports:
- Local `stdio` MCP servers (newline-delimited JSON-RPC 2.0 over stdin/stdout)
- Remote/local Streamable HTTP MCP servers (JSON or SSE single-response over HTTP/S)
- Declarative `mcpServers` JSON configuration (`GEOTOOL_MCP_CONFIG_FILE` / `GEOTOOL_MCP_SERVERS`)
- Namespaced native Tool registration (`mcp__<server>__<tool>`) with Draft 2020-12
  schema normalization, allowlist/denylist, read_only classification, and secret hygiene.

Zero-impact default: when no MCP servers are configured, registers 0 tools.
"""
from __future__ import annotations

import atexit
from copy import deepcopy
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import RLock
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .tools import Tool, ToolDefinition, ToolFailure, ToolOutput, object_schema

MCP_PROTOCOL_VERSION = "2025-03-26"
MAX_MCP_MESSAGE_BYTES = 4 * 1024 * 1024
_SENSITIVE_ENV_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "DSN", "AUTHORIZATION", "COOKIE")
_SERVER_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,47}$")


class McpError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class McpServerConfig:
    """Declarative configuration for one MCP server (stdio or HTTP)."""
    name: str
    transport: str = "stdio"  # "stdio" | "http"
    command: tuple[str, ...] = ()
    args: tuple[str, ...] = ()
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    env_passthrough: tuple[str, ...] = ()
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    read_only: bool = False
    allow_tools: tuple[str, ...] = ()
    deny_tools: tuple[str, ...] = ()
    timeout_seconds: float = 30.0
    enabled: bool = True

    def __post_init__(self):
        if not _SERVER_ID_RE.fullmatch(self.name):
            raise ValueError(f"Invalid MCP server name: {self.name!r}")
        if self.transport not in ("stdio", "http"):
            raise ValueError(f"Unsupported MCP transport {self.transport!r} for server {self.name!r}")
        if self.transport == "stdio" and not self.command:
            raise ValueError(f"MCP stdio server {self.name!r} requires a non-empty command")
        if self.transport == "http":
            if not self.url:
                raise ValueError(f"MCP http server {self.name!r} requires a url")
            parsed = urlsplit(self.url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError(f"MCP http server {self.name!r} requires an HTTP(S) URL without embedded credentials")
        if self.timeout_seconds <= 0:
            raise ValueError("MCP timeout_seconds must be positive")


def _sanitize_tool_segment(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip()).strip("_")
    if not cleaned:
        raise ValueError(f"Invalid MCP tool name: {name!r}")
    return cleaned


def native_mcp_tool_name(server_name: str, remote_tool_name: str) -> str:
    """Build deterministic namespaced native tool name: `mcp__<server>__<tool>`."""
    return f"mcp__{_sanitize_tool_segment(server_name)}__{_sanitize_tool_segment(remote_tool_name)}"


def normalize_mcp_input_schema(raw_schema: dict | None) -> dict:
    """Normalize an MCP tool inputSchema into a valid Draft 2020-12 object schema."""
    if not isinstance(raw_schema, dict):
        return object_schema({})
    schema = deepcopy(raw_schema)
    schema["type"] = "object"
    if not isinstance(schema.get("properties"), dict):
        schema["properties"] = {}
    if "required" in schema and not isinstance(schema["required"], list):
        schema["required"] = list(schema["required"])
    schema.setdefault("additionalProperties", False)
    return schema


def _mcp_result_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "server": {"type": "string"},
            "tool": {"type": "string"},
            "text": {"type": "string"},
            "content": {"type": "array", "items": {"type": "object"}},
            "structured_content": {"type": ["object", "null"]},
            "is_error": {"type": "boolean"},
        },
        "required": ["server", "tool", "text", "content", "is_error"],
        "additionalProperties": False,
    }


def _redact_secrets(text: str, secrets: tuple[str, ...]) -> str:
    out = text
    for secret in secrets:
        if secret and len(secret) >= 4:
            out = out.replace(secret, "[REDACTED]")
    return out


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class StdioMcpClient:
    """Thread-safe JSON-RPC 2.0 MCP client over local stdio subprocess."""

    def __init__(self, config: McpServerConfig):
        self.config = config
        self._lock = RLock()
        self._proc: subprocess.Popen | None = None
        self._next_id = 0
        self._initialized = False
        self.server_info: dict = {}

    def _build_env(self) -> dict[str, str]:
        env = {
            k: v for k, v in os.environ.items()
            if not any(word in k.upper() for word in _SENSITIVE_ENV_WORDS)
        }
        for key in self.config.env_passthrough:
            if key in os.environ:
                env[key] = os.environ[key]
        env.update(self.config.env)
        env.setdefault("PYTHONUNBUFFERED", "1")
        return env

    def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        argv = [*self.config.command, *self.config.args]
        options = {}
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.config.cwd,
            env=self._build_env(),
            **options,
        )
        self._initialized = False

    def _write_message(self, message: dict) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        raw = (json.dumps(message, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        if len(raw) > MAX_MCP_MESSAGE_BYTES:
            raise McpError("mcp_payload_too_large", "MCP request exceeds maximum message size")
        try:
            self._proc.stdin.write(raw)
            self._proc.stdin.flush()
        except OSError as exc:
            raise McpError("mcp_transport_error", f"Failed writing to MCP server {self.config.name}: {exc}", retryable=True) from exc

    def _read_message(self, timeout: float) -> dict:
        assert self._proc is not None and self._proc.stdout is not None
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpError("mcp_timeout", f"MCP server {self.config.name} timed out", retryable=True)
            # On POSIX use select for non-blocking deadline enforcement; on Windows readline directly.
            if os.name != "nt":
                import select
                ready, _, _ = select.select([self._proc.stdout], [], [], min(remaining, 0.2))
                if not ready:
                    if self._proc.poll() is not None:
                        raise McpError("mcp_process_exited", f"MCP server {self.config.name} exited unexpectedly", retryable=True)
                    continue
            line = self._proc.stdout.readline(MAX_MCP_MESSAGE_BYTES + 1)
            if not line:
                stderr_hint = ""
                if self._proc.stderr is not None and self._proc.poll() is not None:
                    try:
                        stderr_hint = self._proc.stderr.read(512).decode("utf-8", errors="replace").strip()
                    except Exception:
                        pass
                msg = f"MCP server {self.config.name} closed stdout"
                if stderr_hint:
                    msg += f": {stderr_hint}"
                raise McpError("mcp_process_exited", msg, retryable=True)
            if len(line) > MAX_MCP_MESSAGE_BYTES:
                raise McpError("mcp_payload_too_large", "MCP response exceeds maximum message size")
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise McpError("mcp_invalid_json", f"Invalid JSON from MCP server {self.config.name}: {exc}") from exc
            if isinstance(parsed, dict):
                return parsed

    def _request(self, method: str, params: dict | None = None, *, timeout: float | None = None) -> dict:
        self._next_id += 1
        req_id = self._next_id
        payload: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._write_message(payload)
        eff_timeout = timeout if timeout is not None else self.config.timeout_seconds
        deadline = time.monotonic() + eff_timeout
        while True:
            rem = max(0.05, deadline - time.monotonic())
            msg = self._read_message(rem)
            # Ignore server-initiated notifications while awaiting our response ID.
            if "id" not in msg:
                continue
            if msg.get("id") != req_id:
                continue
            if "error" in msg and msg["error"] is not None:
                err = msg["error"]
                detail = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                raise McpError("mcp_rpc_error", f"MCP {self.config.name} {method} failed: {detail}", retryable=True)
            result = msg.get("result")
            if not isinstance(result, dict):
                raise McpError("mcp_invalid_response", f"MCP {self.config.name} returned non-object result")
            return result

    def initialize(self) -> dict:
        with self._lock:
            self._ensure_started()
            if self._initialized:
                return self.server_info
            res = self._request(
                "initialize",
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "orebogao", "version": "0.31"},
                },
            )
            self._write_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
            self._initialized = True
            self.server_info = res
            return res

    def list_tools(self) -> list[dict]:
        with self._lock:
            self.initialize()
            tools: list[dict] = []
            cursor: str | None = None
            for _ in range(32):
                params = {"cursor": cursor} if cursor else {}
                res = self._request("tools/list", params)
                batch = res.get("tools", [])
                if not isinstance(batch, list):
                    raise McpError("mcp_invalid_response", "MCP tools/list did not return a tools array")
                tools.extend(t for t in batch if isinstance(t, dict) and isinstance(t.get("name"), str))
                cursor = res.get("nextCursor")
                if not cursor:
                    break
            return tools

    def call_tool(self, tool_name: str, arguments: dict, *, timeout: float | None = None) -> dict:
        with self._lock:
            self.initialize()
            return self._request(
                "tools/call",
                {"name": tool_name, "arguments": arguments},
                timeout=timeout,
            )

    def close(self) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None
            self._initialized = False
            if proc is None:
                return
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
            for pipe in (proc.stdout, proc.stderr):
                try:
                    if pipe:
                        pipe.close()
                except Exception:
                    pass


class HttpMcpClient:
    """Standard Streamable HTTP JSON-RPC 2.0 MCP client (JSON & SSE responses)."""

    def __init__(self, config: McpServerConfig):
        self.config = config
        self._lock = RLock()
        self._next_id = 0
        self._initialized = False
        self._session_id: str | None = None
        self.server_info: dict = {}

    def _secret_values(self) -> tuple[str, ...]:
        return tuple(v for v in self.config.headers.values() if v)

    def _post(self, payload: dict, *, timeout: float | None = None, expect_response: bool = True) -> dict | None:
        assert self.config.url is not None
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self.config.headers,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        req = Request(self.config.url, data=raw, headers=headers, method="POST")
        eff_timeout = timeout if timeout is not None else self.config.timeout_seconds
        opener = build_opener(_NoRedirect())
        try:
            with opener.open(req, timeout=eff_timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self._session_id = sid
                if not expect_response or resp.status == 202:
                    return None
                content_type = (resp.headers.get("Content-Type") or "").lower()
                body = resp.read(MAX_MCP_MESSAGE_BYTES + 1)
                if len(body) > MAX_MCP_MESSAGE_BYTES:
                    raise McpError("mcp_payload_too_large", "MCP HTTP response exceeds maximum size")
                text = body.decode("utf-8", errors="replace")
                if "text/event-stream" in content_type:
                    return self._parse_sse_jsonrpc(text, payload.get("id"))
                return json.loads(text)
        except HTTPError as exc:
            detail = _redact_secrets(f"HTTP {exc.code}: {exc.reason}", self._secret_values())
            raise McpError("mcp_http_error", f"MCP server {self.config.name} error ({detail})", retryable=exc.code >= 500 or exc.code == 429) from None
        except (URLError, TimeoutError, OSError) as exc:
            detail = _redact_secrets(str(exc), self._secret_values())
            raise McpError("mcp_transport_error", f"MCP server {self.config.name} unreachable: {detail}", retryable=True) from None
        except json.JSONDecodeError as exc:
            raise McpError("mcp_invalid_json", f"Invalid JSON from MCP HTTP server {self.config.name}: {exc}") from None

    @staticmethod
    def _parse_sse_jsonrpc(text: str, req_id) -> dict:
        last_obj = None
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if not chunk or chunk == "[DONE]":
                continue
            try:
                obj = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                last_obj = obj
                if req_id is not None and obj.get("id") == req_id:
                    return obj
        if last_obj is None:
            raise McpError("mcp_invalid_response", "MCP SSE stream contained no JSON-RPC payload")
        return last_obj

    def _request(self, method: str, params: dict | None = None, *, timeout: float | None = None) -> dict:
        self._next_id += 1
        req_id = self._next_id
        payload: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            payload["params"] = params
        msg = self._post(payload, timeout=timeout, expect_response=True)
        if not isinstance(msg, dict):
            raise McpError("mcp_invalid_response", f"MCP {self.config.name} returned empty response")
        if "error" in msg and msg["error"] is not None:
            err = msg["error"]
            detail = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise McpError("mcp_rpc_error", f"MCP {self.config.name} {method} failed: {detail}", retryable=True)
        result = msg.get("result")
        if not isinstance(result, dict):
            raise McpError("mcp_invalid_response", f"MCP {self.config.name} returned non-object result")
        return result

    def initialize(self) -> dict:
        with self._lock:
            if self._initialized:
                return self.server_info
            res = self._request(
                "initialize",
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "orebogao", "version": "0.31"},
                },
            )
            try:
                self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_response=False)
            except McpError:
                pass
            self._initialized = True
            self.server_info = res
            return res

    def list_tools(self) -> list[dict]:
        with self._lock:
            self.initialize()
            tools: list[dict] = []
            cursor: str | None = None
            for _ in range(32):
                params = {"cursor": cursor} if cursor else {}
                res = self._request("tools/list", params)
                batch = res.get("tools", [])
                if not isinstance(batch, list):
                    raise McpError("mcp_invalid_response", "MCP tools/list did not return a tools array")
                tools.extend(t for t in batch if isinstance(t, dict) and isinstance(t.get("name"), str))
                cursor = res.get("nextCursor")
                if not cursor:
                    break
            return tools

    def call_tool(self, tool_name: str, arguments: dict, *, timeout: float | None = None) -> dict:
        with self._lock:
            self.initialize()
            return self._request("tools/call", {"name": tool_name, "arguments": arguments}, timeout=timeout)

    def close(self) -> None:
        with self._lock:
            self._initialized = False
            self._session_id = None


def load_mcp_configs(
    *,
    config_file: str | Path | None = None,
    raw_json: str | None = None,
) -> list[McpServerConfig]:
    """Load declarative MCP server configurations from file or env JSON."""
    payload = None
    file_path = config_file or os.environ.get("GEOTOOL_MCP_CONFIG_FILE", "").strip()
    env_json = raw_json if raw_json is not None else os.environ.get("GEOTOOL_MCP_SERVERS", "").strip()
    if file_path:
        path = Path(file_path)
        if not path.is_file():
            raise ValueError(f"Configured MCP config file does not exist: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
    elif env_json:
        payload = json.loads(env_json)
    else:
        return []

    if not isinstance(payload, dict):
        raise ValueError("MCP configuration must be a JSON object")
    servers = payload.get("mcpServers", payload)
    if not isinstance(servers, dict):
        raise ValueError("MCP configuration 'mcpServers' must be a JSON object")

    configs: list[McpServerConfig] = []
    for name, spec in servers.items():
        if not isinstance(spec, dict):
            raise ValueError(f"Invalid MCP server definition for {name!r}")
        if spec.get("enabled", True) is False:
            continue
        transport = spec.get("transport") or ("http" if "url" in spec else "stdio")
        cmd = spec.get("command")
        if isinstance(cmd, str):
            cmd_tuple = (cmd,)
        elif isinstance(cmd, (list, tuple)):
            cmd_tuple = tuple(str(x) for x in cmd)
        else:
            cmd_tuple = ()
        args_tuple = tuple(str(x) for x in spec.get("args", ()))
        headers = dict(spec.get("headers") or {})
        if spec.get("bearer_token_file"):
            tok_path = Path(spec["bearer_token_file"])
            headers["Authorization"] = "Bearer " + tok_path.read_text(encoding="utf-8").strip()
        configs.append(
            McpServerConfig(
                name=str(name),
                transport=str(transport),
                command=cmd_tuple,
                args=args_tuple,
                cwd=spec.get("cwd"),
                env={str(k): str(v) for k, v in (spec.get("env") or {}).items()},
                env_passthrough=tuple(str(x) for x in spec.get("env_passthrough", ())),
                url=spec.get("url"),
                headers={str(k): str(v) for k, v in headers.items()},
                read_only=bool(spec.get("read_only", False)),
                allow_tools=tuple(str(x) for x in spec.get("allow_tools", ())),
                deny_tools=tuple(str(x) for x in spec.get("deny_tools", ())),
                timeout_seconds=float(spec.get("timeout_seconds", 30.0)),
                enabled=True,
            )
        )
    return configs


def _format_mcp_content(content: list) -> tuple[str, list[dict]]:
    parts: list[str] = []
    normalized: list[dict] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        normalized.append(item)
        kind = item.get("type")
        if kind == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
        elif kind == "resource" and isinstance(item.get("resource"), dict):
            res = item["resource"]
            if isinstance(res.get("text"), str):
                parts.append(res["text"])
            elif isinstance(res.get("uri"), str):
                parts.append(f"[resource: {res['uri']}]")
        elif kind == "image":
            parts.append(f"[image: {item.get('mimeType', 'image')}]")
    return "\n".join(parts), normalized


class McpToolManager:
    """Manages connected MCP clients and registers their tools as native OreBOGAO Tools."""

    def __init__(self, configs: list[McpServerConfig] | tuple[McpServerConfig, ...]):
        self.configs = tuple(configs)
        self._clients: dict[str, StdioMcpClient | HttpMcpClient] = {}
        self.registered_tools: list[str] = []
        self.read_only_tools: set[str] = set()
        self.errors: dict[str, str] = {}
        atexit.register(self.close)

    def _client_for(self, config: McpServerConfig) -> StdioMcpClient | HttpMcpClient:
        if config.name not in self._clients:
            self._clients[config.name] = (
                StdioMcpClient(config) if config.transport == "stdio" else HttpMcpClient(config)
            )
        return self._clients[config.name]

    def register_into(self, registry, *, fail_fast: bool = False) -> tuple[str, ...]:
        """Discover tools from configured MCP servers and register them into `registry`."""
        newly_registered: list[str] = []
        result_schema = _mcp_result_schema()
        for config in self.configs:
            if not config.enabled:
                continue
            try:
                client = self._client_for(config)
                remote_tools = client.list_tools()
            except Exception as exc:
                self.errors[config.name] = str(exc)
                if fail_fast:
                    raise
                continue

            allow = set(config.allow_tools)
            deny = set(config.deny_tools)
            for spec in remote_tools:
                remote_name = spec["name"]
                if allow and remote_name not in allow:
                    continue
                if remote_name in deny:
                    continue
                native_name = native_mcp_tool_name(config.name, remote_name)
                if native_name in registry.names():
                    if fail_fast:
                        raise ValueError(f"MCP tool name collision: {native_name}")
                    continue

                description = str(spec.get("description") or f"MCP tool {remote_name} from server {config.name}").strip()
                when_to_use = f"External MCP tool ({config.name}:{remote_name}). Invoke when its declared parameters match the task."
                input_schema = normalize_mcp_input_schema(spec.get("inputSchema"))
                annotations = spec.get("annotations") if isinstance(spec.get("annotations"), dict) else {}
                is_read_only = bool(config.read_only or annotations.get("readOnlyHint") is True)

                def _make_handler(cli, srv_name, rem_name, cfg_timeout):
                    def _handler(args, ctx):
                        ctx.check()
                        remaining = ctx.deadline - time.monotonic()
                        if remaining <= 0:
                            ctx.check()
                        eff_timeout = min(cfg_timeout, remaining) if remaining < float("inf") else cfg_timeout
                        try:
                            raw_res = cli.call_tool(rem_name, dict(args), timeout=eff_timeout)
                        except McpError as exc:
                            raise ToolFailure(exc.code, exc.message, retryable=exc.retryable) from None
                        content_raw = raw_res.get("content", [])
                        if not isinstance(content_raw, list):
                            content_raw = []
                        text, normalized_content = _format_mcp_content(content_raw)
                        structured = raw_res.get("structuredContent")
                        if structured is not None and not isinstance(structured, dict):
                            structured = None
                        is_error = bool(raw_res.get("isError", False))
                        data = {
                            "server": srv_name,
                            "tool": rem_name,
                            "text": text[:ctx.settings.max_tool_output_chars],
                            "content": normalized_content,
                            "structured_content": structured,
                            "is_error": is_error,
                        }
                        if is_error:
                            raise ToolFailure(
                                "mcp_tool_error",
                                text or f"MCP tool {srv_name}:{rem_name} reported an error",
                                retryable=True,
                                data=data,
                            )
                        return ToolOutput(data)
                    return _handler

                registry.register(
                    Tool(
                        ToolDefinition(native_name, description, when_to_use, input_schema, deepcopy(result_schema)),
                        _make_handler(client, config.name, remote_name, config.timeout_seconds),
                        pure=is_read_only,
                    )
                )
                newly_registered.append(native_name)
                self.registered_tools.append(native_name)
                if is_read_only:
                    self.read_only_tools.add(native_name)
        return tuple(newly_registered)

    def close(self) -> None:
        for client in list(self._clients.values()):
            try:
                client.close()
            except Exception:
                pass
        self._clients.clear()


def register_mcp_tools(
    registry,
    *,
    configs: list[McpServerConfig] | tuple[McpServerConfig, ...] | None = None,
    fail_fast: bool = False,
) -> tuple[tuple[str, ...], McpToolManager | None]:
    """Load configured MCP servers and register their tools into `registry`.

    Returns `(registered_tool_names, manager_or_none)`. When no MCP servers are
    configured, returns `((), None)` with zero runtime side effects.
    """
    resolved = list(configs) if configs is not None else load_mcp_configs()
    if not resolved:
        return (), None
    manager = McpToolManager(resolved)
    names = manager.register_into(registry, fail_fast=fail_fast)
    return names, manager

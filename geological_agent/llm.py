import json
import re
from typing import Iterator, Protocol
import httpx
from .contracts import Message, ModelEvent, ModelRequest, ModelResponse, ToolCall, strict_json
from .model_context import native_context


class ModelProtocolError(ValueError):
    def __init__(self, message, *, diagnostic=None):
        super().__init__(message)
        self.diagnostic = diagnostic or {}


def native_response_diagnostic(response, tool_choice="required"):
    """Distinguish provider-reported hosted work from caller-owned function calls."""
    metadata = getattr(response, "provider_metadata", {}) or {}
    usage = metadata.get("server_side_tool_usage")
    hosted = isinstance(usage, dict) and any(
        isinstance(count, (int, float)) and not isinstance(count, bool) and count > 0
        for count in usage.values())
    calls = getattr(response, "tool_calls", ()) or ()
    kind = ("provider_hosted_tools_without_native_calls" if hosted and not calls else
            "missing_native_tool_calls" if response is not None and not calls else
            "invalid_native_tool_response")
    return {"kind": kind, "requested_tool_choice": tool_choice,
            "native_tool_call_count": len(calls),
            "provider_reported_tool_usage": usage if isinstance(usage, dict) else {},
            "provider_response_id": metadata.get("id"),
            "provider_execution_verified": False}


def missing_native_tool_message(response):
    if native_response_diagnostic(response)["kind"] == "provider_hosted_tools_without_native_calls":
        return ("The provider reports server-side tool use but returned no native tool_calls "
                "for the supplied functions despite tool_choice=required. No client-side tool "
                "was executed. Provider usage/citations are diagnostics, not verified local "
                "execution. Check this API route's custom-function configuration or use a "
                "compatible model route.")
    return "The model service did not honor native tool_choice=required; no tool from this response was executed"


class LLMClient(Protocol):
    def invoke(self, request: ModelRequest) -> ModelResponse: ...
    def stream(self, request: ModelRequest) -> Iterator[ModelEvent]: ...


class LocalChatClient:
    """Client for an EXISTING local model endpoint. Starts no HTTP service.

    Only this adapter knows the OpenAI-compatible wire format. The runtime does
    not import HTTP/SDK types. An in-process local model can implement LLMClient
    instead, without changing the graph or domain components.
    """

    def __init__(self, base_url="http://127.0.0.1:8000/v1", model="GeoGPT-Research-Project/Qwen2.5-72B-GeoGPT",
                 api_key="", timeout=180.0, transport=None, max_tokens=4096, thinking_enabled=True, required_streaming=False):
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.client = httpx.Client(base_url=base_url.rstrip("/") + "/", headers=headers, timeout=timeout,
                                   trust_env=False, transport=transport)
        self.model = model
        self.max_tokens = max_tokens
        self.deepseek = (self.client.base_url.host.lower().rstrip(".") == "api.deepseek.com")
        self.thinking_enabled = thinking_enabled
        self.required_streaming = required_streaming
        self._diagnostic_secrets = (api_key,) if api_key else ()

    def close(self):
        self.client.close()

    def _body(self, request, stream=False):
        if request.transport not in ("auto", "full_response"):
            raise ValueError("Unsupported model transport preference")
        if request.tool_choice not in ("auto", "required", "none"):
            raise ValueError("Unsupported native tool_choice")
        if request.tool_choice == "required" and not request.tools:
            raise ValueError("Native required tool choice needs exposed tools")
        body = {"model": self.model, "temperature": 0, "max_tokens": self.max_tokens,
                "stream": stream, **native_context(request)}
        if self.deepseek:
            # Official Chat Completions rejects required/named tool choices in
            # thinking mode. Keep the native requirement, not a text-JSON fallback.
            enabled = self.thinking_enabled and request.tool_choice != "required"
            body["thinking"] = {"type": "enabled" if enabled else "disabled"}
            if enabled:
                body.pop("temperature", None)
            for message in body["messages"]:
                if message["role"] == "assistant":
                    # Non-thinking turns legitimately have no reasoning. Actual
                    # thinking text is preserved exactly, never synthesized.
                    message.setdefault("reasoning_content", "")
        return body

    @staticmethod
    def _provider_metadata(data):
        # Retain known response metadata, not HTTP headers or credentials.
        # Values remain provider claims and never enter native tool dispatch.
        return {key: data[key] for key in (
            "id", "model", "object", "created", "system_fingerprint",
            "citations", "server_side_tool_usage") if key in data}

    @staticmethod
    def _response(message, finish_reason, usage=None, provider_metadata=None):
        calls = []
        for raw in message.get("tool_calls") or []:
            fn = raw.get("function", {})
            if not isinstance(raw.get("id"), str) or not raw["id"] or not isinstance(fn.get("name"), str):
                raise ModelProtocolError("Tool calls need a nonempty ID and function name")
            calls.append(ToolCall(raw["id"], fn["name"], fn.get("arguments", "")))
        content = message.get("content") or ""
        if not isinstance(content, str):
            raise ModelProtocolError("Assistant content must be text")
        reasoning = message.get("reasoning_content")
        if reasoning is not None and not isinstance(reasoning, str):
            raise ModelProtocolError("Assistant reasoning_content must be text or null")
        return ModelResponse(content, tuple(calls), finish_reason or "", usage or {},
                             provider_metadata or {}, reasoning_content=reasoning)

    def _safe_diagnostic(self, value):
        if isinstance(value, dict):
            return {k: "[REDACTED]" if str(k).lower() in {
                "api_key", "api_token", "access_token", "refresh_token", "session_token",
                "authorization", "password", "cookie", "set-cookie", "secret"
            } else self._safe_diagnostic(v) for k, v in value.items()}
        if isinstance(value, (tuple, list)):
            return [self._safe_diagnostic(v) for v in value]
        if isinstance(value, str):
            for secret in self._diagnostic_secrets:
                value = value.replace(secret, "[REDACTED]")
            value = re.sub(r"(?i)Bearer\s+[A-Za-z0-9_.~+/=-]+", "Bearer [REDACTED]", value)
            value = re.sub(r"lsv2_[A-Za-z0-9_]+", "[REDACTED]", value)
            value = re.sub(
                r'(?i)("(?:api_key|api_token|access_token|password|authorization|secret)"\s*:\s*)"(?:\\.|[^"\\])*"',
                r'\1"[REDACTED]"', value)
        return value

    def _failure(self, kind, message, response, **details):
        diagnostic = self._safe_diagnostic({
            "kind": kind, "http_status": response.status_code,
            "content_type": response.headers.get("content-type"),
            "provider_request_id": response.headers.get("x-request-id") or response.headers.get("request-id"),
            "model": self.model, **details})
        return ModelProtocolError(self._safe_diagnostic(message), diagnostic=diagnostic)

    def _check_http(self, response):
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            response.read()
            try:
                body = strict_json(response.text)
            except (ValueError, TypeError):
                body = response.text
            exc.diagnostic = self._failure(
                "http_error", str(exc), response, body=body).diagnostic
            raise

    def invoke(self, request):
        response = self.client.post("chat/completions", json=self._body(request))
        self._check_http(response)
        data = None
        try:
            data = strict_json(response.text)
            if not isinstance(data, dict):
                raise ValueError("Response must be a JSON object")
            if data.get("error") is not None:
                raise self._failure("provider_error", "Model provider error: " +
                                    json.dumps(data["error"], ensure_ascii=False), response, body=data)
            choice = data["choices"][0]
            if not choice.get("finish_reason"):
                raise ValueError("Model response has no finish reason; no tool was dispatched")
            return self._response(choice["message"], choice["finish_reason"], data.get("usage"),
                                  self._provider_metadata(data))
        except ModelProtocolError as exc:
            if not exc.diagnostic:
                exc.diagnostic = self._failure("invalid_response", str(exc), response, body=data).diagnostic
            raise
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise self._failure("invalid_response", f"Invalid model response: {exc}", response,
                                body=data if data is not None else response.text) from exc

    def stream(self, request):
        if request.transport == "full_response" or (request.tool_choice == "required" and not self.required_streaming):
            # The deployed vLLM required-tool SSE path can emit [DONE] without
            # a finish_reason. Request a complete native response up front;
            # do not dispatch partial calls or replay an ambiguous stream.
            completed = self.invoke(request)
            if not completed.finish_reason:
                raise ModelProtocolError("Model response has no finish reason; no tool was dispatched")
            yield ModelEvent("response", response=completed)
            return
        text, calls, reason, usage = [], {}, None, {}
        reasoning, reasoning_seen = [], False
        provider_metadata, provider_events = {}, []
        frames, non_data_lines, done_seen = [], [], False
        with self.client.stream("POST", "chat/completions", json=self._body(request, True)) as response:
            self._check_http(response)
            if "application/json" in response.headers.get("content-type", "").lower():
                response.read()
                try:
                    body = strict_json(response.text)
                except ValueError:
                    body = response.text
                error = body.get("error") if isinstance(body, dict) else None
                raise self._failure(
                    "provider_error" if error is not None else "unexpected_content_type",
                    "Model provider error: " + json.dumps(error, ensure_ascii=False) if error is not None
                    else "Expected an SSE stream but received a JSON body; no tool was dispatched",
                    response, body=body)

            def packets():
                # SSE permits multiple data lines per event and comments between them.
                event_name, data_lines = "", []
                for line in response.iter_lines():
                    if line == "":
                        if data_lines:
                            yield event_name, "\n".join(data_lines)
                        event_name, data_lines = "", []
                    elif line.startswith("data:"):
                        value = line[5:]
                        data_lines.append(value[1:] if value.startswith(" ") else value)
                    elif line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line and not line.startswith(":"):
                        non_data_lines.append(line)
                if data_lines:
                    yield event_name, "\n".join(data_lines)

            for event_name, payload in packets():
                payload = payload.strip()
                if payload == "[DONE]":
                    done_seen = True
                    break
                try:
                    data = strict_json(payload)
                    frames.append({"event": event_name, "data": data})
                    if not isinstance(data, dict):
                        raise ValueError("Stream packet must be a JSON object")
                    if event_name == "error" or data.get("error") is not None or data.get("type") == "error":
                        error = data.get("error", data)
                        raise self._failure("provider_error", "Model provider error: " +
                                            json.dumps(error, ensure_ascii=False), response,
                                            frames=frames, non_data_lines=non_data_lines, done_seen=done_seen)
                    usage = data.get("usage") or usage
                    extra = self._provider_metadata(data)
                    provider_metadata.update(extra)
                    extensions = {key: extra[key] for key in ("citations", "server_side_tool_usage")
                                  if key in extra}
                    if extensions:
                        # Preserve metadata-only frames too. Counts may be cumulative,
                        # so keep original frames instead of summing them.
                        provider_events.append(extensions)
                    if not data.get("choices"):
                        continue
                    choice = data["choices"][0]
                    reason = choice.get("finish_reason") or reason
                    delta = choice.get("delta", {})
                    if delta.get("reasoning_content") is not None:
                        fragment = delta["reasoning_content"]
                        if not isinstance(fragment, str):
                            raise ModelProtocolError("Stream reasoning_content must be text or null")
                        reasoning_seen = True
                        reasoning.append(fragment)
                        yield ModelEvent("reasoning_delta", fragment)
                    if delta.get("content"):
                        if not isinstance(delta["content"], str):
                            raise ModelProtocolError("Stream content must be text")
                        text.append(delta["content"])
                        yield ModelEvent("text_delta", delta["content"])
                    for part in delta.get("tool_calls") or []:
                        slot = calls.setdefault(part["index"], {"id": "", "function": {"name": "", "arguments": ""}})
                        if part.get("id"):
                            slot["id"] = part["id"]
                        for key in ("name", "arguments"):
                            slot["function"][key] += part.get("function", {}).get(key, "") or ""
                except ModelProtocolError as exc:
                    if not exc.diagnostic:
                        exc.diagnostic = self._failure("invalid_stream", str(exc), response,
                            frames=frames, non_data_lines=non_data_lines, done_seen=done_seen).diagnostic
                    raise
                except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
                    raise self._failure("invalid_stream", f"Invalid model stream: {exc}", response,
                                        frames=frames, failed_payload=payload,
                                        non_data_lines=non_data_lines, done_seen=done_seen) from exc
        if reason is None:
            raise self._failure("stream_incomplete",
                "Model stream ended without a finish reason; no tool was dispatched", response,
                frames=frames, non_data_lines=non_data_lines, done_seen=done_seen,
                partial_tool_calls=len(calls), content_chars=sum(map(len, text)))
        if provider_events:
            provider_metadata["stream_events"] = provider_events
        completed = self._response({"content": "".join(text), "tool_calls": [calls[k] for k in sorted(calls)],
                                   "reasoning_content": "".join(reasoning) if reasoning_seen else None},
                                   reason, usage, provider_metadata)
        yield ModelEvent("response", response=completed)

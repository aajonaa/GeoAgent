import json
from typing import Iterator, Protocol
import httpx
from .contracts import Message, ModelEvent, ModelRequest, ModelResponse, ToolCall, strict_json
from .model_context import native_context


class ModelProtocolError(ValueError):
    pass


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
                 api_key="", timeout=180.0, transport=None, max_tokens=4096):
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.client = httpx.Client(base_url=base_url.rstrip("/") + "/", headers=headers, timeout=timeout,
                                   trust_env=False, transport=transport)
        self.model = model
        self.max_tokens = max_tokens

    def close(self):
        self.client.close()

    def _body(self, request, stream=False):
        if request.tool_choice not in ("auto", "required", "none"):
            raise ValueError("Unsupported native tool_choice")
        if request.tool_choice == "required" and not request.tools:
            raise ValueError("Native required tool choice needs exposed tools")
        return {"model": self.model, "temperature": 0, "max_tokens": self.max_tokens,
                "stream": stream, **native_context(request)}

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
        for raw in message.get("tool_calls", []):
            fn = raw.get("function", {})
            if not isinstance(raw.get("id"), str) or not raw["id"] or not isinstance(fn.get("name"), str):
                raise ModelProtocolError("Tool calls need a nonempty ID and function name")
            calls.append(ToolCall(raw["id"], fn["name"], fn.get("arguments", "")))
        content = message.get("content") or ""
        if not isinstance(content, str):
            raise ModelProtocolError("Assistant content must be text")
        return ModelResponse(content, tuple(calls), finish_reason or "", usage or {},
                             provider_metadata or {})

    def invoke(self, request):
        response = self.client.post("chat/completions", json=self._body(request))
        response.raise_for_status()
        try:
            data = strict_json(response.text)
            choice = data["choices"][0]
            return self._response(choice["message"], choice["finish_reason"], data.get("usage"),
                                  self._provider_metadata(data))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelProtocolError(f"Invalid model response: {exc}") from exc

    def stream(self, request):
        if request.tool_choice == "required":
            # The deployed vLLM required-tool SSE path can emit [DONE] without
            # a finish_reason. Request a complete native response up front;
            # do not dispatch partial calls or replay an ambiguous stream.
            completed = self.invoke(request)
            if not completed.finish_reason:
                raise ModelProtocolError("Model response has no finish reason; no tool was dispatched")
            yield ModelEvent("response", response=completed)
            return
        text, calls, reason, usage = [], {}, None, {}
        provider_metadata, provider_events = {}, []
        with self.client.stream("POST", "chat/completions", json=self._body(request, True)) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    data = strict_json(payload)
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
                    if delta.get("content"):
                        text.append(delta["content"])
                        yield ModelEvent("text_delta", delta["content"])
                    for part in delta.get("tool_calls", []):
                        slot = calls.setdefault(part["index"], {"id": "", "function": {"name": "", "arguments": ""}})
                        if part.get("id"):
                            slot["id"] = part["id"]
                        for key in ("name", "arguments"):
                            slot["function"][key] += part.get("function", {}).get(key, "") or ""
                except (KeyError, TypeError, ValueError) as exc:
                    raise ModelProtocolError(f"Invalid model stream: {exc}") from exc
        if reason is None:
            raise ModelProtocolError("Model stream ended without a finish reason; no tool was dispatched")
        if provider_events:
            provider_metadata["stream_events"] = provider_events
        completed = self._response({"content": "".join(text), "tool_calls": [calls[k] for k in sorted(calls)]},
                                   reason, usage, provider_metadata)
        yield ModelEvent("response", response=completed)

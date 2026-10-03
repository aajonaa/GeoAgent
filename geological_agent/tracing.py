from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from contextlib import nullcontext
import json
import os
import re
from pathlib import Path
from typing import Protocol


class TraceSink(Protocol):
    def emit(self, event: str, **fields) -> None: ...


class NullTrace:
    def emit(self, event, **fields):
        pass


class JsonlTrace:
    def __init__(self, path: Path, secrets=()):
        self.path = path
        self.secrets = tuple(s for s in secrets if s)
        path.parent.mkdir(parents=True, exist_ok=True)

    def _safe(self, value):
        """Redact credentials without truncating recorded content."""
        if is_dataclass(value):
            value = asdict(value)
        if isinstance(value, dict):
            safe = {}
            for key, item in value.items():
                if key.lower() in {"api_key", "api_token", "authorization", "password", "access_token",
                                   "session_token", "refresh_token", "cookie", "set-cookie"}:
                    safe[key] = "[REDACTED]"
                elif key == "tool_choice" and isinstance(item, str) and item in ("auto", "required", "none"):
                    # These are public protocol enums, even when a local model
                    # uses an identical word as its dummy API credential.
                    safe[key] = item
                else:
                    safe[key] = self._safe(item)
            return safe
        if isinstance(value, (tuple, list)):
            return [self._safe(v) for v in value]
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[REDACTED]")
            value = re.sub(r"(?i)Bearer\s+[A-Za-z0-9_.~+/=-]+", "Bearer [REDACTED]", value)
            value = re.sub(r"lsv2_[A-Za-z0-9_]+", "[REDACTED]", value)
            return value
        return value

    def emit(self, event, **fields):
        record = self._safe({"time": datetime.now(timezone.utc).isoformat(), "event": event, **fields})
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str, allow_nan=False) + "\n")

    def execution_context(self):
        # Our explicit exporter owns what leaves this process. Do not also send
        # entire LangGraph states through an ambient automatic tracer.
        try:
            from langsmith import tracing_context
        except ImportError:
            return nullcontext()
        return tracing_context(enabled=False)


def configured_trace(path, secrets=()):
    """Local logs always; external tracing requires an explicit opt-in."""
    key = os.environ.get("LANGSMITH_API_KEY", "")
    local = JsonlTrace(path, secrets=(*secrets, key))
    if os.environ.get("GEOTOOL_LANGSMITH_ENABLED", "").lower() != "true":
        return local
    if not key:
        local.emit("langsmith_unavailable", reason="LANGSMITH_API_KEY is not configured; local logging remains active")
        return local
    try:
        from langsmith import Client
        from .langsmith_tracing import LangSmithTrace
        def export_error(exc):
            # Exception text can include private request data or credentials.
            local.emit("langsmith_export_failed", error_type=type(exc).__name__)
        client = Client(api_key=key, api_url=os.environ.get("LANGSMITH_ENDPOINT") or None,
                        timeout_ms=5000, auto_batch_tracing=True, omit_traced_runtime_info=True,
                        tracing_error_callback=export_error)
        return LangSmithTrace(local, client,
            project=os.environ.get("LANGSMITH_PROJECT", "geotoolagent-acceptance"),
            capture_content=os.environ.get("GEOTOOL_LANGSMITH_CAPTURE_CONTENT", "").lower() == "true",
            model=os.environ.get("GEOTOOL_MODEL", "GeoGPT-Research-Project/Qwen2.5-72B-GeoGPT"),
            release=os.environ.get("GEOTOOL_RELEASE", "local-cli"))
    except Exception as exc:
        local.emit("langsmith_unavailable", error_type=type(exc).__name__)
        return local

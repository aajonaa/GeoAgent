"""Small, explicit IPC protocol. No pickle, eval, or arbitrary class loading."""
import base64
from dataclasses import asdict, fields, is_dataclass
import hashlib
import json
from pathlib import PurePosixPath
import re

from ..contracts import ArtifactRef, ErrorInfo, Message, ModelRequest, ModelResponse, ToolCall, ToolResult
from ..tools import ToolDefinition

MAX_PACKET = 128 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
MAX_FILES_TOTAL = 64 * 1024 * 1024
TYPES = {c.__name__: c for c in (ArtifactRef, ErrorInfo, Message, ModelRequest, ModelResponse, ToolCall, ToolResult, ToolDefinition)}


def encode(value):
    if is_dataclass(value):
        return {"_type": type(value).__name__, "fields": {f.name: encode(getattr(value, f.name)) for f in fields(value)}}
    if isinstance(value, (list, tuple)):
        return [encode(item) for item in value]
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def decode(value):
    if isinstance(value, list):
        return [decode(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"_type", "fields"}:
            cls = TYPES.get(value["_type"])
            if cls is None or not isinstance(value["fields"], dict):
                raise ValueError("Unsupported IPC type")
            return cls(**{k: decode(v) for k, v in value["fields"].items()})
        return {k: decode(v) for k, v in value.items()}
    return value


def dumps(value):
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(raw) > MAX_PACKET:
        raise ValueError("IPC packet exceeds the explicit 128 MiB transport limit; nothing was truncated")
    return raw


def relative_name(name):
    if not isinstance(name, str) or not name or len(name) > 240:
        raise ValueError("Invalid relative filename")
    parts = name.split("/")
    if name.startswith("/") or "\\" in name or ":" in name or any(ord(c) < 32 for c in name):
        raise ValueError("Invalid relative filename")
    if any(p in ("", ".", "..", ".agent") or len(p) > 100 for p in parts):
        raise ValueError("Invalid relative filename")
    return str(PurePosixPath(name))


def file_packet(name, data):
    if len(data) > MAX_FILE:
        raise ValueError("A file exceeds the explicit 8 MiB transfer limit")
    return {"name": relative_name(name), "data": base64.b64encode(data).decode("ascii"),
            "sha256": hashlib.sha256(data).hexdigest()}


def unpack_files(items):
    if not isinstance(items, list) or len(items) > 1024:
        raise ValueError("Invalid file collection")
    result, total = {}, 0
    for item in items:
        name = relative_name(item["name"])
        if name in result or len(item["data"]) > (MAX_FILE + 2) // 3 * 4:
            raise ValueError("Duplicate or oversized file")
        raw = base64.b64decode(item["data"], validate=True)
        total += len(raw)
        if len(raw) > MAX_FILE or total > MAX_FILES_TOTAL:
            raise ValueError("File transfer quota exceeded; no partial snapshot is committed")
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("File digest mismatch")
        result[name] = raw
    return result


def scrub(value, secrets=()):
    """Preserve full content, masking credentials only."""
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {k: "[REDACTED]" if str(k).lower() in {
            "password", "api_key", "api_token", "authorization", "access_token",
            "session_token", "refresh_token", "cookie"
        } else scrub(v, secrets) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [scrub(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)Bearer\s+[A-Za-z0-9_.~+/=-]+", "Bearer [REDACTED]", value)
        value = re.sub(r"lsv2_[A-Za-z0-9_]+", "[REDACTED]", value)
    return value

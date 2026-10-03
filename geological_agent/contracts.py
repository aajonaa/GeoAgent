from dataclasses import asdict, dataclass, field
import json
from typing import Any


def strict_json(text: str) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"Non-finite JSON number: {value}")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict | str


@dataclass(frozen=True)
class Message:
    role: str
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    # Ephemeral visual requests only; encoded pixels are not appended to text history.
    image_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtifactRef:
    path: str
    media_type: str
    produced_by: str


@dataclass(frozen=True)
class ErrorInfo:
    code: str
    message: str
    retryable: bool = False
    outcome_unknown: bool = False


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str
    status: str
    data: dict = field(default_factory=dict)
    artifacts: tuple[ArtifactRef, ...] = ()
    error: ErrorInfo | None = None
    cached: bool = False
    evidence: dict = field(default_factory=dict)

    def message(self) -> Message:
        return Message("tool", json.dumps(asdict(self), ensure_ascii=False, allow_nan=False), tool_call_id=self.call_id)


@dataclass(frozen=True)
class ModelRequest:
    messages: tuple[Message, ...]
    tools: tuple[Any, ...]
    tool_choice: str = "auto"


@dataclass(frozen=True)
class ModelResponse:
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str = "stop"
    usage: dict = field(default_factory=dict)
    # Provider-reported diagnostics, never ToolResult or execution evidence.
    provider_metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ModelEvent:
    kind: str
    text: str = ""
    response: ModelResponse | None = None


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: str
    answer: str
    artifacts: tuple[ArtifactRef, ...]
    reason: str | None
    model_turns: int
    state: dict

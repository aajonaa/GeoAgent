from dataclasses import dataclass
import math


# Framework presets, not claims about a provider's supported capacity.
DEFAULT_CONTEXT_WINDOW_TOKENS = 1000000
DEFAULT_MAX_OUTPUT_TOKENS = 128000


@dataclass(frozen=True)
class Settings:
    max_model_turns: int | None = 32
    tool_timeout_seconds: float = 0.0  # Zero disables the execution deadline.
    max_context_chars: int = 750000  # Legacy config field; not the context budget.
    max_tool_output_chars: int = 12000
    max_file_bytes: int = 2 * 1024 * 1024
    memory_enabled: bool = False
    knowledge_enabled: bool = False
    verify_completion: bool = True
    context_window_tokens: int | None = DEFAULT_CONTEXT_WINDOW_TOKENS
    context_model: str = ""
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS

    def __post_init__(self):
        # Missing/null windows in old configurations inherit the token preset.
        if self.context_window_tokens is None:
            object.__setattr__(self, "context_window_tokens", DEFAULT_CONTEXT_WINDOW_TOKENS)
        if not isinstance(self.context_model, str) or len(self.context_model) > 256:
            raise ValueError("context_model must be a model ID of at most 256 characters")
        if type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= 9007199254740991:
            raise ValueError("max_output_tokens must be a positive safe integer")
        if self.context_window_tokens is not None:
            window = self.context_window_tokens
            if type(window) is not int or not 1 <= window <= 9007199254740991:
                raise ValueError("Context window must be a positive whole number of tokens")
            reserve = self.max_output_tokens + max(1024, (window + 19) // 20)
            if window <= reserve:
                raise ValueError("Context window must exceed the output and safety reserves")
        if self.max_model_turns is not None and self.max_model_turns < 1:
            raise ValueError("max_model_turns must be positive or None")
        if (type(self.tool_timeout_seconds) not in (int, float)
                or not math.isfinite(self.tool_timeout_seconds)
                or self.tool_timeout_seconds < 0):
            raise ValueError("tool_timeout_seconds must be finite and nonnegative; zero disables the deadline")
        for name in ("max_context_chars", "max_tool_output_chars", "max_file_bytes"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")

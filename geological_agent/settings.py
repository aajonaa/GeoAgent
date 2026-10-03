from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    max_model_turns: int | None = 32
    tool_timeout_seconds: float = 60.0
    max_context_chars: int = 48000
    max_tool_output_chars: int = 12000
    max_file_bytes: int = 2 * 1024 * 1024
    memory_enabled: bool = False
    knowledge_enabled: bool = False
    verify_completion: bool = True

    def __post_init__(self):
        if self.max_model_turns is not None and self.max_model_turns < 1:
            raise ValueError("max_model_turns must be positive or None")
        for name in ("tool_timeout_seconds", "max_context_chars", "max_tool_output_chars", "max_file_bytes"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")

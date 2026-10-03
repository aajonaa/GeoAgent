from typing import TypedDict
from ..contracts import ArtifactRef, Message, ToolCall


class AgentState(TypedDict):
    run_id: str
    task: str
    messages: list[Message]
    selected_skill_ids: list[str]
    exposed_tool_names: list[str]
    pending_tool_calls: list[ToolCall]
    artifacts: list[ArtifactRef]
    status: str
    model_turns: int
    last_error: str | None
    answer: str
    metadata: dict

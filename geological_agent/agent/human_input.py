"""Native human-input control, with durable LangGraph checkpoints."""
from contextlib import contextmanager
from pathlib import Path
import os
import sqlite3

from ..tools import Tool, ToolDefinition, ToolOutput, object_schema


def register_human_input(registry):
    text = {"type": "string", "minLength": 1}
    schema = object_schema({
        "question": {**text, "description": "A specific question in the user's language. Ask for missing information or an authorized decision, not a generic request for help."},
        "reason": {**text, "description": "What is blocked and what actual attempts or observations establish the gap. Do not claim a resource does not exist merely because a search missed it."},
        "missing": {"type": "array", "items": text, "description": "The concrete data, access, parameter, or decision needed."},
        "options": {"type": "array", "items": text, "description": "Optional suggested answers. Free text is always allowed; no option is pre-approved."},
        "reason_type": {"type": "string", "enum": ["missing_objective", "missing_input", "unavailable_resource", "approval"], "description": "Classify the actual blocker. Ordinary requested calculations are already authorized. Discover skills before claiming unavailable resources."},
        "supporting_call_ids": {"type": "array", "items": text, "description": "Actual prior call IDs establishing a resource gap. Empty for genuinely missing user inputs or objectives."},
        "approval_tool_names": {"type": "array", "items": text, "description": "Exact exposed tool names for the consequential operation needing approval. Pure calculations do not need renewed permission."},
    }, ["question", "reason", "missing", "options"])
    registry.register(Tool(ToolDefinition(
        "request_user_input", "Pause the task for a human response, retaining files and execution state.",
        "Essential information or an approval must come from the user, and no grounded autonomous next step is available. Call alone unless the runtime explicitly permits an ordered batch ending with this request. Never schedule an action that needs the missing input before receiving it. Do not ask the user to debug the runtime.",
        schema, schema), lambda args, context: ToolOutput(args)))


@contextmanager
def durable_checkpoint(path):
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # These are the only application-defined classes stored in AgentState.
    allowed = [("geological_agent.contracts", name) for name in ("Message", "ToolCall", "ArtifactRef")]
    serde = JsonPlusSerializer(pickle_fallback=False, allowed_msgpack_modules=allowed, allowed_json_modules=allowed)
    connection = sqlite3.connect(path, check_same_thread=False)
    try:
        if os.name != "nt":
            path.chmod(0o600)
        yield SqliteSaver(connection, serde=serde)
    finally:
        connection.close()

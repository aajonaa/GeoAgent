"""Native human-input control, with durable LangGraph checkpoints."""
from contextlib import contextmanager
from pathlib import Path
import os
import sqlite3

from ..contracts import Message
from ..tools import Tool, ToolDefinition, ToolOutput, object_schema


def apply_human_reply(state, reply):
    """Keep runtime recovery controls out of research messages and retrieval."""
    import json

    pending = state["metadata"]["pending_input"]
    if (not isinstance(reply, dict) or reply.get("request_id") != pending["id"]
            or not isinstance(reply.get("text"), str) or not reply["text"].strip()):
        raise ValueError("The response must address the current input request")
    metadata = dict(state["metadata"])
    recovery = metadata.get("protocol_recovery")
    control = (pending.get("reason_type") == "model_protocol"
               and pending.get("recovery_origin") == "runtime")
    if control and (not isinstance(recovery, dict) or not recovery.get("phase")
                    or recovery["phase"] != pending.get("recovery_phase")):
        raise ValueError("The recovery response must address the saved runtime phase")
    for name in ("pending_input", "execution_ready", "final_answer_composed", "next_tool_choice",
                 "native_tool_recovery_pending", "protocol_recovery", "runtime_control_resume",
                 "resume_review_candidate", "resume_review_phase"):
        metadata.pop(name, None)
    messages = list(state["messages"])
    if control:
        phase = recovery["phase"]
        metadata["runtime_control_resume"] = phase
        # Files are the current workspace inventory, not new execution evidence.
        # Keep the whole reply for diagnostics, never as research clarification.
        metadata["runtime_control_responses"] = metadata.get("runtime_control_responses", []) + [
            {**reply, "phase": phase}]
        if phase.startswith("review:") or phase == "knowledge_semantics":
            metadata["resume_review_candidate"] = recovery
            progress = metadata.get("semantic_review_progress")
            if progress is not None:
                metadata["semantic_review_progress"] = {**progress, "failure_signatures": []}
        elif phase == "intent":
            metadata["protocol_recovery"] = {**recovery, "failures": 0}
            metadata.pop("objective_checked", None)
        else:
            metadata["next_tool_choice"] = recovery["tool_choice"]
            metadata["native_tool_recovery_pending"] = True
    else:
        metadata["human_responses"] = metadata.get("human_responses", []) + [reply]
        messages.append(Message("user", reply["text"] +
            "\nCurrent supplied file names (data, not execution evidence):\n" +
            json.dumps(reply.get("files", []), ensure_ascii=False)))
    return {"messages": messages, "metadata": metadata,
            "status": "running", "answer": "", "last_error": None}


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

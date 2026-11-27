"""Dynamic task checklist (todo) tool and KV-cache-friendly tail recitation.

Persists a readable checklist under `.agent/todo.md` (never polluting user
deliverables) and appends a compact progress snapshot at the tail of execution
requests so long-horizon runs stay aligned with remaining steps.
"""
import hashlib
import re

from ..contracts import Message
from ..tools import Tool, ToolDefinition, ToolFailure, ToolOutput, object_schema

_MARKERS = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]", "blocked": "[!]"}
_STATUS_VALUES = ("pending", "in_progress", "done", "blocked")


def _clean_line(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _render_markdown(objective: str, items: list[dict]) -> str:
    lines = ["# Task Todo", ""]
    if objective:
        lines.extend([f"**Objective**: {objective}", ""])
    for item in items:
        marker = _MARKERS[item["status"]]
        line = f"- {marker} `{item['id']}`: {item['task']}"
        if item.get("evidence"):
            line += f" (evidence: {item['evidence']})"
        lines.append(line)
    return "\n".join(lines) + "\n"


def update_todo(args, ctx):
    ctx.check()
    raw_items = args.get("items") or []
    if not raw_items:
        raise ToolFailure("empty_todo", "Provide at least one todo item.", retryable=True)
    seen_ids = set()
    items = []
    for raw in raw_items:
        item_id = _clean_line(raw["id"])
        task_text = _clean_line(raw["task"])
        status = raw["status"]
        if not item_id or not task_text:
            raise ToolFailure("invalid_todo_item", "Each todo item needs a nonempty id and task.", retryable=True)
        if item_id in seen_ids:
            raise ToolFailure("duplicate_todo_id", f"Duplicate todo item id: {item_id}", retryable=True)
        seen_ids.add(item_id)
        entry = {"id": item_id, "task": task_text, "status": status}
        if raw.get("evidence"):
            entry["evidence"] = _clean_line(raw["evidence"])[:240]
        items.append(entry)
    objective = _clean_line(args.get("objective", ""))[:400]
    markdown = _render_markdown(objective, items)
    raw_bytes = markdown.encode("utf-8")
    if len(raw_bytes) > 16384:
        raise ToolFailure("todo_too_large", "Keep the todo checklist concise (<= 16 KB).", retryable=True)
    target = ctx.path(".agent/todo.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw_bytes)
    counts = {status: sum(1 for item in items if item["status"] == status) for status in _STATUS_VALUES}
    counts["total"] = len(items)
    digest = hashlib.sha256(raw_bytes).hexdigest()
    # Stored under .agent/ so it is internal working state, not a user deliverable artifact.
    return ToolOutput({
        "objective": objective,
        "items": items,
        "counts": counts,
        "markdown_path": ".agent/todo.md",
        "sha256": digest,
    })


def register_todo_tool(registry):
    text = {"type": "string"}
    item_schema = object_schema({
        "id": {**text, "minLength": 1, "maxLength": 32, "description": "Short stable step ID (e.g. s1, s2)."},
        "task": {**text, "minLength": 1, "maxLength": 200, "description": "Concrete step description."},
        "status": {**text, "enum": list(_STATUS_VALUES), "description": "Current step status."},
        "evidence": {**text, "maxLength": 240, "description": "Optional observed file path, citation ID, or metric proving completion."},
    }, ["id", "task", "status"])
    in_schema = object_schema({
        "objective": {**text, "maxLength": 400, "description": "Concise overall research objective."},
        "items": {"type": "array", "items": item_schema, "minItems": 1, "maxItems": 15,
                  "description": "Ordered full list of task steps and their current status."},
    }, ["items"])
    out_schema = object_schema({
        "objective": text,
        "items": {"type": "array", "items": {"type": "object"}},
        "counts": {"type": "object"},
        "markdown_path": text,
        "sha256": text,
    }, ["objective", "items", "counts", "markdown_path", "sha256"])
    registry.register(Tool(
        ToolDefinition(
            "update_todo",
            "Create or update the run's live execution checklist (.agent/todo.md) to track progress across multi-step tasks.",
            "Use for multi-step research, analysis, or multi-deliverable tasks to stay aligned and avoid repeating completed steps.",
            in_schema,
            out_schema,
        ),
        update_todo,
    ))
    return ("update_todo",)


def recite_progress_message(state) -> Message | None:
    """Build a compact tail-only progress recitation from todo_list or research_plan.

    Placed at the tail of messages so earlier turns remain byte-identical for KV-cache.
    """
    if len(state.get("messages", ())) <= 1:
        return None
    metadata = state.get("metadata") or {}
    todo = metadata.get("todo_list")
    if isinstance(todo, dict) and todo.get("items"):
        lines = [
            "Current task progress (todo recitation — focus on remaining pending/in_progress items; "
            "do not repeat completed work; this checklist is working state, not execution proof):"
        ]
        if todo.get("objective"):
            lines.append("Objective: " + str(todo["objective"])[:300])
        for item in todo["items"][:15]:
            marker = _MARKERS.get(item.get("status"), "[ ]")
            entry = f"- {marker} {item.get('id', '')}: {item.get('task', '')}"
            if item.get("evidence"):
                entry += f" [evidence: {item['evidence']}]"
            lines.append(entry)
        counts = todo.get("counts") or {}
        lines.append(
            f"Summary: {counts.get('done', 0)}/{counts.get('total', len(todo['items']))} done, "
            f"{counts.get('in_progress', 0)} in_progress, {counts.get('pending', 0)} pending, "
            f"{counts.get('blocked', 0)} blocked."
        )
        return Message("user", "\n".join(lines)[:2000])

    plan = metadata.get("research_plan")
    if isinstance(plan, dict) and isinstance(plan.get("content"), str) and plan["content"].strip():
        snippet = plan["content"].strip()[:1600]
        return Message(
            "user",
            "Current research plan recitation (working state, not execution proof — stay aligned with unfinished steps):\n"
            + snippet,
        )
    return None

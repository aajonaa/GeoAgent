"""Workspace research plans and their LangGraph checkpoint representation."""

import hashlib
import re

from .tools import ToolFailure, ToolOutput, write_file


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _path(ctx):
    return "research-plan-" + hashlib.sha256(ctx.run_id.encode()).hexdigest()[:24] + ".md"


def _current(ctx):
    path = ctx.path(_path(ctx))
    if not path.exists():
        return None
    if path.stat().st_size > 10000:
        raise ToolFailure("invalid_research_plan", "The research plan exceeds 10 KB.")
    return path.read_bytes().decode("utf-8")


def _line(value):
    return re.sub(r"\s+", " ", value).strip()


def research_plan(args, ctx):
    current = _current(ctx)
    path = _path(ctx)
    if "steps" not in args:
        if current is None:
            return ToolOutput({"path": path, "sha256": None, "content": None})
        return ToolOutput({"path": path, "sha256": _digest(current), "content": current})

    sha = _digest(current) if current is not None else None
    markers = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]", "blocked": "[!]"}
    steps = "\n".join(f"- {markers[step['status']]} {_line(step['task'])}" for step in args["steps"])
    evidence = "\n".join("- " + _line(item) for item in args.get("evidence", ()))
    content = f"# Research plan\n\n## Objective\n{_line(args['objective'])}\n\n## Steps\n{steps}\n"
    if evidence:
        content += "\n## Evidence and decisions\n" + evidence + "\n"
    if len(content.encode("utf-8")) > 10000:
        raise ToolFailure("invalid_research_plan", "Shorten the research plan to 10 KB.", retryable=True)
    if content != current and args.get("expected_sha256") != sha:
        raise ToolFailure("research_plan_changed", "Read the plan and use its current sha256 before updating.", retryable=True)
    output = write_file({"path": path, "content": content, "expected_sha256": sha}, ctx)
    return ToolOutput({"path": path, "sha256": output.data["sha256"], "content": content}, output.artifacts)


def restore_research_plan(record, ctx):
    """Recreate a missing scratch file after validating its checkpoint provenance."""
    if not record:
        return
    if record["path"] != _path(ctx) or _digest(record["content"]) != record["sha256"]:
        raise ValueError("Invalid research plan checkpoint")
    current = _current(ctx)
    if current is None:
        write_file({"path": record["path"], "content": record["content"]}, ctx)
    # An existing workspace file is authoritative for the next read, including edits
    # saved after the checkpoint. Restoration never overwrites such edits.

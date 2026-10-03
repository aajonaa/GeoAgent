"""State-based availability for reference-file tools; never a scientific planner."""
from dataclasses import replace
import json
import os
from pathlib import Path

from ..contracts import Message


SOURCE_TOOLS = frozenset({"web_search", "web_fetch"})


def workspace_files(workspace):
    """Inspect names only. Internal cache files and external symlinks are not inputs."""
    root = Path(workspace).resolve()
    found = []
    for directory, folders, names in os.walk(root, followlinks=False):
        folders[:] = [name for name in folders if name != ".agent"
                      and not (Path(directory) / name).is_symlink()]
        for name in names:
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                continue
            found.append(path.relative_to(root).as_posix())
    return sorted(found)


def source_tools_available(names):
    return sorted(SOURCE_TOOLS.intersection(names))


def resource_request(request, registry, workspace):
    """Temporarily hide impossible file queries, without changing the registry/schema.

    A file existing is only an availability fact, never proof of its provenance.
    Normal direct/local execution remains available when web acquisition is absent.
    """
    sources = source_tools_available(tool.name for tool in request.tools)
    if not sources:
        return request, None
    references = [tool for tool in request.tools
                  if set(registry.get(tool.name).reference_paths).intersection(
                      tool.input_schema.get("required", []))]
    if not references:
        return request, None
    files = workspace_files(workspace)
    blocked = sorted(tool.name for tool in references) if not files else []
    facts = {"files": files, "blocked_tools": blocked, "source_tools": sources}
    notice = (
        "Current runtime resource availability (filesystem observation, not a model claim):\n" +
        json.dumps(facts, ensure_ascii=False) +
        "\nThe listed blocked tools require an existing reference-data file; registration and "
        "a skill's example procedure do not supply that file. They are not callable in this "
        "request, and automatically return after an input file really exists. "
        "Do not invent a filename or fabricate rows to unlock a tool. "
        "Use exposed acquisition tools for authorized PUBLIC sources, inspect the retrieved "
        "record, or ask for genuinely private/missing user input. Do not send private file "
        "contents, credentials or conversation history to a search provider. "
        "A public-source question can be answered directly from observed source text if it "
        "satisfies the user's goal; creating a CSV and running a local lookup is not mandatory. "
        "Existing files remain subject to source/provenance checks. "
        "Narration about a search, read or write is not an observation; return each native "
        "tool call and wait for its actual result before using it."
    )
    return replace(request, tools=tuple(tool for tool in request.tools if tool.name not in blocked),
                   messages=(*request.messages, Message("user", notice))), facts


def missing_reference_paths(result):
    if not result.error or (result.error.code != "missing_input" and
                            result.evidence.get("original_error") != "missing_input"):
        return []
    return sorted({row["path"] for row in result.evidence.get("input_files", [])
                   if row.get("reference_data") and not row.get("exists")})


def source_attempted(messages):
    for message in messages:
        if message.role == "tool":
            result = json.loads(message.content)
            if result.get("name") in SOURCE_TOOLS:
                return True
    return False


def repair_guidance(paths, source_tools):
    return (
        "Runtime resource correction: the reference input does not exist: " +
        ", ".join(paths) + ". The failed call did not read any deposit records. "
        "A different limit, an absolute path, or repeating the same filename cannot repair "
        "a missing dataset. Consult the observed file inventory and use a real supplied "
        "input if appropriate. Otherwise use an exposed acquisition tool (" +
        ", ".join(source_tools) + ") for the user's authorized public-source query, inspect "
        "the returned source before reporting facts, or request the actual private input. "
        "Do not manufacture a factual dataset from memory. Public source text may satisfy "
        "the task directly without an intermediate table. Preserve prior successful work "
        "and every user constraint. The next response must contain an actual native action, "
        "not a narration claiming that these actions already happened."
    )

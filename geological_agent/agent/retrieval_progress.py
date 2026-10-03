"""Detect unchanged retrieval evidence without treating timestamps as progress."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

from ..contracts import Message

SEARCH_TOOLS = frozenset(("web_search", "context_search", "skill_find"))
SUPPORTING_TOOLS = SEARCH_TOOLS | {"skill_load", "web_fetch", "context_read"}
_VOLATILE = frozenset(("retrieved_at", "cache_hit", "duration_ms", "elapsed_seconds"))


def observation_key(name, data):
    if name not in SUPPORTING_TOOLS or not isinstance(data, dict):
        return None
    value = {key: deepcopy(item) for key, item in data.items() if key not in _VOLATILE}
    if name in SEARCH_TOOLS:
        value.pop("query", None)
        for field in ("results", "matches", "skills"):
            if isinstance(value.get(field), list):
                value[field] = sorted(value[field], key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
    return hashlib.sha256(json.dumps([name, value], sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode("utf-8")).hexdigest()


def unchanged(name, arguments, data, old_name, old_arguments, old_data):
    if old_name != name:
        return False
    key = observation_key(name, data)
    return key == observation_key(old_name, old_data) if key is not None else (
        arguments == old_arguments and data == old_data)


def redirect_request(request, stalled_names):
    """One decision chooses another strategy, not a permanent search ban."""
    stalled = set(stalled_names) & SEARCH_TOOLS
    if not stalled:
        return request
    alternatives = tuple(tool for tool in request.tools if tool.name not in stalled)
    if not alternatives:
        return request
    guidance = (
        "Retrieval strategy correction: previous searches returned already observed evidence, not new facts. "
        "For this decision the repeated search tools are not disclosed: " + ", ".join(sorted(stalled)) + ". "
        "Inspect an observed source or archived record, use an available professional tool with real inputs, "
        "or deliver from existing evidence. If essential data remains unobtainable, describe the actual gap; "
        "ask for genuinely missing user input rather than inventing a dataset. Successful work must not be rerun. "
        "Search becomes available again on the next decision if a materially different search is justified."
    )
    return replace(request, tools=alternatives, messages=(*request.messages, Message("user", guidance)))

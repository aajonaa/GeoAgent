"""Budget native skill disclosure without rewriting schemas or execution evidence."""
from copy import deepcopy

from .compaction import ContextOverflow, fit_request, request_size
from ..context_budget import input_allowance, request_budget_size, budget_description


def fit_skill_scope(state, *, build_request, base_tool_names, skills, settings, archive=None):
    """Return an active scope; deferred skills remain discoverable and reloadable.

    Selection follows the model's relevance order, with explicit skill_load
    requests first. The 90% target is the existing compaction headroom, not a
    skill-count limit. Probes use exact compaction only, never model summaries.
    Original messages, artifacts, tool results and canonical schemas are untouched.
    """
    if state.get("pending_tool_calls"):
        raise ValueError("Cannot change skill scope while native calls are pending")
    metadata = state.get("metadata", {})
    focus = list(dict.fromkeys(metadata.get("skill_scope_focus", [])))
    candidates = list(dict.fromkeys([*focus, *state["selected_skill_ids"]]))
    previous_deferred = list(metadata.get("deferred_skill_ids", []))
    if not candidates:
        return state, None
    known = list(dict.fromkeys([*candidates, *previous_deferred]))
    loaded = {sid: skills.load(sid) for sid in known}
    skill_tools = {name for skill in loaded.values() for name in skill.tool_names}
    base = list(dict.fromkeys([*base_tool_names, *(
        name for name in state["exposed_tool_names"] if name not in skill_tools)]))

    def scoped(active):
        pending = [sid for sid in known if sid not in active]
        names = list(dict.fromkeys([*base, *(
            name for sid in active for name in loaded[sid].tool_names)]))
        return {**state, "selected_skill_ids": list(active), "exposed_tool_names": names,
                "metadata": {**metadata, "deferred_skill_ids": pending, "skill_scope_focus": []}}

    measurements = {}

    def measure(active):
        trial = scoped(active)
        # Compaction may write immutable originals to the archive, but trial
        # summaries/diagnostics must not mutate the authoritative checkpoint.
        probe = {**trial, "metadata": deepcopy(trial["metadata"])}
        request = build_request(probe)
        try:
            fitted = fit_request(request, probe, settings, phase="execution", archive=archive)
            measurements[tuple(active)] = request_size(fitted)
            return request_budget_size(fitted, settings)
        except ContextOverflow:
            return None

    target = int(input_allowance(settings) * .9)
    full_size = measure(candidates)
    active = list(candidates)
    if full_size is None or full_size > target:
        active = []
        for sid in candidates:
            size = measure([*active, sid])
            # Headroom is soft: a single useful skill that fits the real
            # allowance must not be made unavailable by a reserve percentage.
            if size is not None and (size <= target or not active):
                active.append(sid)
    result = scoped(active)
    final_size = measure(active)
    if final_size is None:
        raise ContextOverflow(
            "The base tools, current user instructions and protected evidence exceed "
            "the context allowance even with specialized skills deferred. Originals retained.")
    announced = metadata.get("active_skill_ids", [])
    deferred = result["metadata"]["deferred_skill_ids"]
    changed = active != announced or deferred != previous_deferred
    result["metadata"]["active_skill_ids"] = list(active)
    info = {"active_skill_ids": list(active), "deferred_skill_ids": deferred,
            "activated_skill_ids": [sid for sid in active if sid not in announced],
            "exposed_tool_names": result["exposed_tool_names"],
            "request_chars": measurements[tuple(active)],
            "allowance_chars": settings.max_context_chars if settings.context_window_tokens is None else None,
            "request_estimated_tokens": final_size if settings.context_window_tokens is not None else None,
            **budget_description(settings),
            "source": "explicit_skill_load" if focus else metadata.get("skill_scope_source", "runtime"),
            "schemas_unchanged": True, "execution_evidence_preserved": True}
    result["metadata"].pop("skill_scope_source", None)
    return result, info if changed else None

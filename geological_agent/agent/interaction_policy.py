"""Ground human pauses in actual observations, without blocking missing inputs."""
from dataclasses import asdict, replace
import json
import math

from ..contracts import Message, strict_json
from .compaction import fit_request


def human_input_issue(call, state, registry):
    if call.name != "request_user_input":
        return None
    try:
        args = strict_json(call.arguments) if isinstance(call.arguments, str) else call.arguments
    except (ValueError, TypeError):
        return None  # The normal tool-schema validator reports malformed arguments.
    if not isinstance(args, dict):
        return None
    kind = args.get("reason_type")
    if kind not in {"missing_objective", "missing_input", "unavailable_resource", "approval"}:
        return "Classify the real blocker using reason_type. Requested calculations are already authorized; first discover/load the relevant skill, not ask permission to calculate."
    records = {}
    calls = {c.id: c for m in state["messages"] for c in m.tool_calls}
    for message in state["messages"]:
        if message.role == "tool":
            records[message.tool_call_id] = strict_json(message.content)
    ids = args.get("supporting_call_ids", [])
    if not isinstance(ids, list) or any(not isinstance(i, str) or i not in records for i in ids):
        return "supporting_call_ids must reference real prior tool observations. Do not invent evidence."
    if kind == "unavailable_resource":
        grounded = False
        for identity in ids:
            result, prior = records[identity], calls.get(identity)
            if prior is None:
                continue
            if result["status"] != "ok" and prior.name != "request_user_input":
                grounded = True
            if prior.name == "skill_load" and result.get("data", {}).get("unavailable_tools"):
                grounded = True
            if prior.name == "skill_find" and result["status"] == "ok":
                arguments = strict_json(prior.arguments) if isinstance(prior.arguments, str) else prior.arguments
                # A keyword miss alone is not proof that the resource is absent.
                grounded = grounded or not arguments.get("query", "").strip()
        if not grounded:
            return "Resource absence is not established. Inspect skill_find/skill_load; after a keyword miss, list the registry with an empty query. Cite actual missing-resource observations before pausing."
    if kind == "approval":
        names = args.get("approval_tool_names", [])
        if not isinstance(names, list) or not names or any(not isinstance(n, str) or n not in state["exposed_tool_names"] for n in names):
            return "Specify the actual exposed consequential operation in approval_tool_names. Discover/load tools first. Do not ask permission for ordinary calculations already requested by the user."
        if all(registry.get(name).pure for name in names):
            return "These are pure calculation tools. The user already requested the calculation; execute with the supplied inputs instead of asking permission again."
    return None


def enrich_request(request, state, settings, *, defer_compaction=False):
    tools = []
    for definition in request.tools:
        if definition.name == "request_user_input":
            schema = {**definition.input_schema, "required": list(dict.fromkeys(
                [*definition.input_schema["required"], "reason_type", "supporting_call_ids", "approval_tool_names"]))}
            definition = replace(definition, input_schema=schema)
        tools.append(definition)
    representations = []
    for message in state["messages"]:
        if message.role != "tool":
            continue
        result = strict_json(message.content)
        if result.get("status") != "ok" or not isinstance(result.get("data"), dict):
            continue
        for key, value in result["data"].items():
            if type(value) in (int, float) and math.isfinite(value) and (abs(value) >= 1e6 or 0 < abs(value) < 1e-3):
                representations.append({"call_id": message.tool_call_id, "field": key,
                                        "observed": value, "scientific_notation": format(value, ".15e")})
    guidance = ("Runtime delivery reminder: preserve every original requested output, notation, precision, assumption and exclusion, including during answer-only repair. "
                "Do not request renewed permission for ordinary calculations. A resource not yet discovered is not an unavailable resource. "
                "Observed-number formatting hints below are representations of tool output, NOT independent scientific validation:\n" +
                json.dumps(representations, ensure_ascii=False, allow_nan=False))
    messages = (*request.messages, Message("user", guidance))
    enriched = replace(request, messages=messages, tools=tuple(tools))
    return enriched if defer_compaction else fit_request(enriched, state, settings,
        phase="final_answer" if request.tool_choice == "none" else "execution")

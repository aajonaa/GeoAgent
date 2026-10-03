"""Native completion assessment with references into immutable observed evidence.

Short labels change the internal review contract, not professional tool schemas.
All labels are generated and resolved by the runtime, never trusted as facts.
"""
from copy import deepcopy
from dataclasses import replace
import json
import re
from jsonschema import Draft202012Validator, ValidationError

from ..contracts import Message, strict_json
from ..llm import ModelProtocolError
from ..tools import object_schema
from .completion import review_request, successful_evidence_ids
from .execution_contract import obligations
from .compaction import fit_request


def indexes(state):
    task = state["task"].rsplit("Current user request:\n", 1)[-1]
    replies = [r["text"] for r in state["metadata"].get("human_responses", [])]
    parts = re.split(r"[\u3002\uff01\uff1f\uff1b;\n!?]+|\.(?!\d)\s*", "\n".join([task, *replies]))
    requirements = {f"r{i + 1}": text.strip() for i, text in enumerate(p for p in parts if p.strip())}
    answers = {f"a{i + 1}": text for i, text in enumerate(p for p in state["answer"].splitlines() if p.strip())}
    successful = set(successful_evidence_ids(state["messages"]))
    ordered = list(dict.fromkeys(m.tool_call_id for m in state["messages"]
                                if m.role == "tool" and m.tool_call_id in successful))
    tools = {f"t{i + 1}": identity for i, identity in enumerate(ordered)}
    return requirements, answers, tools


def schema_for(base, requirements, answers=None, tools=None):
    schema = deepcopy(base)
    check = object_schema({
        "ok": {"type": "boolean", "description": "Entire requirement satisfied, including its constraints."},
        "a": {"type": "array", "items": {"type": "string"}, "description": "Relevant actual answer-line IDs, not quotations or user-input IDs."},
        "t": {"type": "array", "items": {"type": "string"}, "description": "Relevant successful tool-result IDs."},
    }, ["ok", "a", "t"])
    schema["properties"]["requirement_checks"] = object_schema(
        {key: {**deepcopy(check), "description": text} for key, text in requirements.items()}, requirements)
    schema["required"] = list(dict.fromkeys([*schema["required"], "requirement_checks"]))
    schema["properties"]["evidence_call_ids"] = {
        "type": "array", "items": {"type": "string"},
        "description": "Short successful tool-result IDs t1, t2, etc. Do not repeat provider call IDs."}
    # Enumerate current references when building a live request.
    for field, table in (("a", answers), ("t", tools)):
        for item in schema["properties"]["requirement_checks"]["properties"].values():
            if table:
                item["properties"][field]["items"]["enum"] = list(table)
            elif table is not None:
                item["properties"][field]["maxItems"] = 0
    if tools:
        schema["properties"]["evidence_call_ids"]["items"]["enum"] = list(tools)
    elif tools is not None:
        schema["properties"]["evidence_call_ids"]["maxItems"] = 0
    schema["properties"]["feedback"] = {"type": "string", "description": "One concise correction when needed. Empty on success."}
    return schema


GUIDANCE = """Assess both executed work AND the candidate answer against EVERY numbered requirement.
Check requested operations, numerical values, units, precision, notation, assumptions, exclusions, and deliverables.
Observations are evidence; a draft, a claimed test, or a user assertion is not independent execution evidence.
For each requirement return ok plus relevant answer-line IDs (a) and successful tool-result IDs (t).
Use the supplied IDs, never copy answer text or long provider call IDs. A line ID only locates text: judge whether it actually satisfies the requirement.
An exclusion or input-only requirement can have empty references. Do not invent answer lines repeating input coordinates.
If a requested result or assumption is missing, mark its requirement false and revise_answer; do not approve merely because a tool succeeded.
Use continue for missing execution, clarify only for genuinely missing user intent/input, and complete only when everything is covered.
No code, files, or Python are required unless the task actually requires them. Preserve all existing execution/evidence checks.
A request_user_input result proves only a question was asked; skill_find/skill_load prove only discovery. None proves a calculation happened.
For requested professional calculations, check EACH requested operation independently against the observed tool name, input and result.
A professional result for one quantity does not prove another calculation. Generic Python/file tools do not satisfy a request for professional computation.
Cite the relevant professional results for ALL operations in that requirement, not just one successful call. If any operation lacks such evidence, use continue and explain the gap.
Do not approve a line-count constraint by citing only the desired result lines while ignoring extra introductory or concluding lines.
Use the smallest sufficient set of relevant line IDs, not every line in the answer. Check the whole answer regardless.
Keep feedback empty on success and concise on failure. Return only the native assessment call."""

def reference_set_schema(base, requirements, answers, tools):
    """Same requirement-by-requirement audit, without repeated status/role fields."""
    schema = schema_for(base, requirements, answers, tools)
    references = [*answers, *tools]
    evidence = {"type": "array", "items": {"type": "string"},
                "description": "Minimal relevant a/t evidence IDs. Empty is valid only when no positive reference is needed (e.g. exclusions or input-only clauses)."}
    if references:
        evidence["items"]["enum"] = references
    else:
        evidence["maxItems"] = 0
    schema["properties"]["requirement_checks"] = object_schema(
        {key: {**deepcopy(evidence), "description": text} for key, text in requirements.items()}, requirements)
    unmet = {"type": "array", "items": {"type": "string"},
             "description": "Every requirement not fully satisfied, including missing values, constraints or operations. Empty only when ALL requirements passed."}
    if requirements:
        unmet["items"]["enum"] = list(requirements)
    else:
        unmet["maxItems"] = 0
    schema["properties"]["unmet_requirement_ids"] = unmet
    del schema["properties"]["evidence_call_ids"]
    schema["required"] = [key for key in schema["required"] if key != "evidence_call_ids"]
    schema["required"].append("unmet_requirement_ids")
    return schema


REFERENCE_SET_GUIDANCE = GUIDANCE.replace(
    "For each requirement return ok plus relevant answer-line IDs (a) and successful tool-result IDs (t).",
    "Return EVERY requirement key in requirement_checks, mapped to its minimal supporting a/t ID array. "
    "List EVERY not-fully-satisfied requirement in unmet_requirement_ids. Never omit a requirement key. "
    "A requirement absent from unmet_requirement_ids is an explicit assertion that ALL its constraints passed. "
    "Keep unrelated or duplicate references out; exclusions can use []. "
    "The runtime derives the global successful-tool evidence set from these per-requirement references."
)


def compact_review_request(state, context, settings, *, protocol_feedback=None):
    base = review_request(state, context, settings, phase="answer", protocol_feedback=protocol_feedback, defer_compaction=True)
    requirements, answers, tools = indexes(state)
    reference_sets = state["metadata"].get("review_reference_sets", False)
    schema_builder = reference_set_schema if reference_sets else schema_for
    definition = replace(base.tools[0], input_schema=schema_builder(base.tools[0].input_schema, requirements, answers, tools))
    evidence = json.loads(base.messages[1].content)
    aliases = {identity: alias for alias, identity in tools.items()}
    # One namespace in this request. Original records remain in the trace;
    # no observation payload is shortened.
    for index, record in enumerate(evidence["observed_actions"]):
        identity = record["result"]["call_id"]
        alias = aliases.get(identity, f"failed_{index + 1}")
        record["result"]["call_id"] = alias
        if record["call"] is not None:
            record["call"]["id"] = alias
    evidence.pop("candidate_answer", None)  # Same text is indexed once below.
    evidence["requirement_ids"] = requirements
    evidence["answer_line_ids"] = answers
    evidence["successful_evidence_call_ids"] = list(tools)
    evidence["successful_result_ids"] = list(tools)
    professional_names = set(state["metadata"].get("professional_tool_names", []))
    if professional_names:
        evidence["professional_result_ids"] = [aliases[m.tool_call_id] for m in state["messages"]
            if m.role == "tool" and m.tool_call_id in aliases and strict_json(m.content)["name"] in professional_names]
    guidance = REFERENCE_SET_GUIDANCE if reference_sets else GUIDANCE
    messages = (replace(base.messages[0], content=base.messages[0].content + "\n" + guidance),
                Message("user", json.dumps(evidence, ensure_ascii=False, allow_nan=False)))
    return fit_request(replace(base, messages=messages, tools=(definition,)), state, settings, phase="review")


def parse_compact_review(response, state, request):
    if response.finish_reason not in ("stop", "tool_calls") or len(response.tool_calls) != 1:
        raise ModelProtocolError("Completion review requires one complete native assessment call")
    call = response.tool_calls[0]
    if call.name != request.tools[0].name:
        raise ModelProtocolError("Unexpected completion assessment function")
    try:
        args = strict_json(call.arguments) if isinstance(call.arguments, str) else deepcopy(call.arguments)
        Draft202012Validator(request.tools[0].input_schema).validate(args)
    except (ValueError, TypeError, ValidationError) as exc:
        raise ModelProtocolError("Invalid compact completion assessment: " + str(exc)) from exc
    requirements, answers, tools = indexes(state)
    def resolve(values, table, kind):
        unknown = [key for key in values if key not in table]
        if unknown:
            raise ModelProtocolError(f"Unknown {kind} reference(s): {unknown}; valid IDs: {list(table)}")
        return [table[key] for key in dict.fromkeys(values)]
    checks = {}
    if "unmet_requirement_ids" in request.tools[0].input_schema["properties"]:
        unmet_ids = set(args.pop("unmet_requirement_ids"))
        for key in requirements:
            references = args["requirement_checks"][key]
            resolve(references, {**answers, **tools}, "evidence")
            checks[key] = {"satisfied": key not in unmet_ids,
                           "answer_quotes": resolve([ref for ref in references if ref in answers], answers, "answer line"),
                           "call_ids": resolve([ref for ref in references if ref in tools], tools, "successful tool")}
        args["evidence_call_ids"] = list(dict.fromkeys(
            identity for check in checks.values() for identity in check["call_ids"]))
    else:
        args["evidence_call_ids"] = resolve(args["evidence_call_ids"], tools, "successful tool")
        for key in requirements:
            check = args["requirement_checks"][key]
            checks[key] = {"satisfied": check["ok"],
                           "answer_quotes": resolve(check["a"], answers, "answer line"),
                           "call_ids": resolve(check["t"], tools, "successful tool")}
    args["requirement_checks"] = checks
    unmet = [key for key, check in checks.items() if not check["satisfied"]]
    if unmet and args["verdict"] == "complete":
        args["verdict"] = "revise_answer"
        args["feedback"] = "Unmet requirements: " + ", ".join(unmet) + ". " + args["feedback"]
    professional_names = set(state["metadata"].get("professional_tool_names", []))
    if professional_names:
        professional_ids = {m.tool_call_id for m in state["messages"] if m.role == "tool"
                            and strict_json(m.content).get("status") == "ok"
                            and strict_json(m.content)["name"] in professional_names}
        unsupported = []
        for key, text in requirements.items():
            requires_professional = obligations({"task": text, "metadata": {}}, professional_names)[0]
            cited = set(checks[key]["call_ids"])
            if requires_professional and (not cited or not cited <= professional_ids):
                checks[key]["satisfied"] = False
                unsupported.append(key)
        if unsupported and args["verdict"] in ("complete", "revise_answer"):
            args["verdict"] = "continue"
            args["feedback"] = ("Professional execution evidence is missing or cites generic/discovery tools for " +
                                ", ".join(unsupported) + ". Check EACH requested calculation and invoke its applicable "
                                "professional tool. Preserve already successful results. " + args["feedback"])
    args["evidence_index"] = {"answer_lines": answers, "tool_results": tools, "requirements": requirements}
    return args

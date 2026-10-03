"""Explicit requirement coverage plus narrow, deterministic presentation checks.

The checklist is model-assisted, not a proof of semantic completeness. Literal
evidence and supported formatting rules are checked separately by the runtime.
"""
from copy import deepcopy
from dataclasses import replace
import json
import re

from jsonschema import Draft202012Validator, ValidationError
from ..contracts import strict_json
from ..llm import ModelProtocolError
from ..tools import object_schema
from .completion import CompletionIssue, parse_review


CHECK_SCHEMA = object_schema({
    "satisfied": {"type": "boolean"},
    "answer_quotes": {"type": "array", "items": {"type": "string"}, "description": "Short, separate real answer excerpts. Use one excerpt per location, not a concatenation. Empty for execution-only or exclusion checks."},
    "call_ids": {"type": "array", "items": {"type": "string"}, "description": "Actual successful calls supporting this requirement; empty for presentation-only requirements."},
}, ["satisfied", "answer_quotes", "call_ids"])


def task_text(state):
    return state["task"].rsplit("Current user request:\n", 1)[-1]


def requirement_segments(state):
    # Keep decimal coordinates and magnitudes intact. Segmentation is not
    # semantic planning: all constraints within each segment still need review.
    parts = re.split(r"[。！？；;\n]+|(?<!\d)[.!?](?!\d)\s*", task_text(state))
    return {"r" + str(i + 1): text.strip() for i, text in enumerate(p for p in parts if p.strip())}


def coverage_schema(state):
    segments = requirement_segments(state)
    return object_schema({identity: {**deepcopy(CHECK_SCHEMA), "description": text} for identity, text in segments.items()}, segments)


def normalized_quote(text):
    # Whitespace and Markdown emphasis are presentation, not scientific data.
    # Preserve digits, signs, units and punctuation to reject changed values.
    return re.sub(r"\s+", "", text.replace("**", "").replace("__", "").replace("`", ""))


def covered_request(request, state):
    tool = request.tools[0]
    schema = deepcopy(tool.input_schema)
    schema["properties"]["requirement_checks"] = coverage_schema(state)
    schema["required"].append("requirement_checks")
    system = request.messages[0].content + (
        "\nAccount for ALL constraints in EACH program-supplied requirement segment r1, r2, etc. "
        "Return every segment ID as a key in requirement_checks; do not rewrite the task or invent IDs. "
        "Use short answer_quotes, one real excerpt per location, for presentation requirements. "
        "A correct decimal value does not satisfy requested scientific notation. Correct values without requested assumptions are incomplete. "
        "Absence of a prohibited operation can be checked from the full action log, with empty answer_quotes and call_ids. "
        "Do not turn implementation suggestions or hypothetical examples into mandatory outputs.")
    system += "\nRequired segments: " + json.dumps(requirement_segments(state), ensure_ascii=False)
    return replace(request, messages=(replace(request.messages[0], content=system), *request.messages[1:]),
                   tools=(replace(tool, input_schema=schema),))


def parse_covered_review(response, state, allowed_ids):
    if len(response.tool_calls) != 1:
        raise ModelProtocolError("One native completion assessment is required")
    call = response.tool_calls[0]
    try:
        args = strict_json(call.arguments) if isinstance(call.arguments, str) else call.arguments
        args = dict(args)
        checks = args.pop("requirement_checks")
        Draft202012Validator(coverage_schema(state)).validate(checks)
    except (ValueError, TypeError, KeyError, ValidationError) as exc:
        raise ModelProtocolError("Invalid requirement coverage: " + str(exc)) from exc
    review = parse_review(replace(response, tool_calls=(replace(call, arguments=args),)), allowed_evidence_ids=allowed_ids)
    allowed = set(allowed_ids or ())
    answer = normalized_quote(state.get("answer", ""))
    missing = []
    for identity, check in checks.items():
        if any(not normalized_quote(quote) or normalized_quote(quote) not in answer for quote in check["answer_quotes"]):
            raise ModelProtocolError("Use separate short excerpts actually present in the answer; do not combine nonadjacent passages or invent evidence (" + identity + ")")
        if any(identity not in allowed for identity in check["call_ids"]):
            raise ModelProtocolError("Requirement cites an unknown or unsuccessful tool call")
        if not check["satisfied"]:
            missing.append(identity + ": " + requirement_segments(state)[identity])
    if missing and review["verdict"] == "complete":
        review["verdict"] = "revise_answer"
        review["feedback"] = "Unmet requirements: " + "; ".join(missing) + ". " + review["feedback"]
    review["requirement_checks"] = checks
    return review


def delivery_issues(state):
    task, answer = task_text(state), state.get("answer", "")
    issues = []
    expected_lines = line_count_requirement(state)
    if expected_lines is not None:
        actual_lines = sum(bool(line.strip()) for line in answer.splitlines())
        if actual_lines != expected_lines:
            issues.append(CompletionIssue(
                f"The user requested exactly {expected_lines} nonempty answer lines in total; the draft has {actual_lines}. "
                "Remove unsolicited introduction/conclusion or restore missing result lines. Preserve all requested values, units and notes. "
                "Use existing observations; do not repeat successful tools."))
    requested_scientific = re.search(r"scientific notation|科学计数法", task, re.I)
    forbidden_scientific = re.search(r"(?:do not|don't|without|no)\s+(?:use\s+)?scientific notation|(?:不用|不要|不使用|无需)科学计数法", task, re.I)
    scientific_value = re.search(r"[+-]?\d+(?:\.\d+)?\s*(?:[eE][+-]?\d+|(?:x|×|\\times|\\cdot)\s*10\s*(?:\^\s*\{?[+-]?\d+|[⁺⁻]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+))", answer)
    if requested_scientific and not forbidden_scientific and not scientific_value:
        issues.append(CompletionIssue("The user explicitly requested scientific notation, but the answer omits it. Preserve the observed value and use its scientific representation; do not repeat the calculation."))
    requested_assumptions = re.search(r"(?:state|report|include|explain|list)[^.!?\n]{0,70}\bassumptions\b|(?:报告|说明|列出|交代|注明)[^。！？\n]{0,50}假设", task, re.I)
    assumption_text = re.search(r"(?:assumptions?|assuming|假设|采用|视为|近似|经验关系)[^\n]{8,}", answer, re.I)
    if requested_assumptions and not assumption_text:
        issues.append(CompletionIssue("The user requested the calculation assumptions. State the actual method assumptions from the loaded skills/tool definitions; do not invent them or omit them during numerical correction."))
    return issues


def line_count_requirement(state):
    """Recognize explicit logical-line counts, not inferred brevity preferences.

    Blank lines are ignored. A separately requested one-sentence note adds one
    logical line. Ambiguous/multiple line-count requests remain model-reviewed.
    """
    task = re.sub(r"\x60{3}[\s\S]*?\x60{3}", "", task_text(state))
    numbers = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
               "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
               "\u4e00": 1, "\u4e8c": 2, "\u4e24": 2, "\u4e09": 3,
               "\u56db": 4, "\u4e94": 5, "\u516d": 6, "\u4e03": 7,
               "\u516b": 8, "\u4e5d": 9, "\u5341": 10}
    numeral = r"\d+|one|two|three|four|five|six|seven|eight|nine|ten|[\u4e00\u4e8c\u4e24\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]"
    pattern = (r"(?:\b(?:only|exactly|just)\s+|(?:\u53ea|\u4ec5)(?:\u7ed9|\u8f93\u51fa|\u8fd4\u56de|\u5199|\u4fdd\u7559)(?:\u51fa)?\s*)("
               + numeral + r")\s*(?:\u884c|\blines?\b)")
    matches = [m for m in re.finditer(pattern, task, re.I)
               if not re.search(r"(?:\bnot|\bdon't|\bdo not|\u4e0d\u8981|\u4e0d\u5fc5|\u4e0d\u7528|\u65e0\u9700)\s*(?:(?:return|give|write|output|use)\s+)?$",
                                task[:m.start()], re.I)]
    if len(matches) != 1:
        return None
    token = matches[0][1].lower()
    count = int(token) if token.isdigit() else numbers[token]
    if count <= 0:
        return None
    extra_note = re.search(
        r"(?:\u5e76|\u53e6(?:\u5916)?|\u518d)\s*(?:\u7528|\u8865|\u52a0|\u9644\u52a0|\u8865\u5145)?\s*(?:\u4e00|1)\s*\u53e5(?:\u8bdd)?"
        r"|(?:plus|and add|and include)\s+(?:a[ -]sentence|(?:a\s+)?(?:one|1)[ -]sentence)",
        task[matches[0].end():], re.I)
    return count + bool(extra_note)

"""Ground explicit tool-use instructions in real successful observations.

A narrow bilingual execution check, not a semantic planner or proof of science.
It does not select tools or infer mandatory actions from a number alone.
Normal model-assisted coverage and domain validators still run.
"""
import re
from ..contracts import strict_json
from .completion import CompletionIssue

CONTROL_TOOLS = frozenset(("skill_find", "skill_load", "request_user_input"))
_ACTION = re.compile(r"\b(?:use|using|invoke|call|run|execute)\b|使用|调用|运行|(?<!使|调|作|利|采|引)用", re.I)
_TOOL = re.compile(r"\btools?\b|工具", re.I)
_PROFESSIONAL = re.compile(r"\b(?:professional|speciali[sz]ed|domain[- ]specific)\b|专业", re.I)
_NEGATED = re.compile(r"(?:do not|don't|must not|need not|no need to|without)\s+(?:\w+\s+){0,2}$|(?:不要|不用|不必|无需|禁止|不需要|不|别)(?:再|去)?$", re.I)
_EXPLANATION = re.compile(r"(?:how to|how do I|example of|examples of)\s*$|(?:如何|怎样|怎么)(?:才能)?$", re.I)


def obligations(state, professional_names):
    names = set(professional_names)
    required_names, professional, any_execution = set(), False, False
    task = state["task"].rsplit("Current user request:\n", 1)[-1]
    texts = [task, *(reply["text"] for reply in state.get("metadata", {}).get("human_responses", []))]
    for text in texts:
        text = re.sub(r"\x60{3}[\s\S]*?\x60{3}", "", text)
        for clause in re.split(r"[,，;；。！？\n]|\.(?!\d)|\bbut\b", text, flags=re.I):
            for action in _ACTION.finditer(clause):
                prefix, tail = clause[:action.start()], clause[action.end():]
                if _EXPLANATION.search(prefix):
                    continue
                negative = bool(_NEGATED.search(prefix))
                matched = {name for name in names if re.search(
                    r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", tail)}
                if matched:
                    required_names.difference_update(matched) if negative else required_names.update(matched)
                if not _TOOL.search(tail):
                    continue
                if _PROFESSIONAL.search(tail):
                    professional = not negative
                elif not any(name in tail for name in CONTROL_TOOLS):
                    any_execution = not negative
                    if negative:
                        professional = False
                        required_names.clear()
    return professional, any_execution, required_names


def requested_execution_issues(state, professional_names):
    professional, any_execution, names = obligations(state, professional_names)
    if not (professional or any_execution or names):
        return []
    successful = set()
    for message in state["messages"]:
        if message.role == "tool":
            result = strict_json(message.content)
            if result.get("status") == "ok":
                successful.add(result["name"])
    issues = []
    missing = sorted(names - successful)
    if missing:
        issues.append(CompletionIssue("Explicitly requested tools have no successful execution: " +
                                      ", ".join(missing) + ". Load the relevant skill if needed, then execute with confirmed inputs.", True))
    if professional and not successful.intersection(professional_names):
        issues.append(CompletionIssue(
            "The user explicitly requested a professional tool calculation, but no successful professional execution exists. "
            "A question, skill search, skill load, or an answer calculated from memory is not execution evidence. "
            "Load the relevant available skill and invoke its native tool with confirmed inputs; ask only for genuinely missing inputs.", True))
    if any_execution and not successful.difference(CONTROL_TOOLS):
        issues.append(CompletionIssue(
            "The requested tool operation has not executed. Human-input and discovery calls do not perform the requested work. "
            "Use a relevant executable tool; do not publish an unexecuted draft as a result.", True))
    return issues

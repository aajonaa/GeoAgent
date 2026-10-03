"""Execution guidance and a single, evidence-grounded completion assessment."""
from dataclasses import asdict, replace
import json


EXECUTION_GUIDANCE = """Choose operations from the user's actual objective, not just from available inputs.
Coordinates, a series, or a file without an analysis objective are insufficient to choose an arbitrary task: ask what result is wanted.
For specialized calculations, first discover or load the relevant available skill and prefer its native professional tools over a Python reimplementation.
Python examples in a skill are explanations, not a requirement to execute Python. Only use custom code when needed and permitted by the user.
When multiple exposed tools have independent, fully known inputs, call them in one native tool-call response. Never guess outputs of earlier calls.
After successful observations, deliver the requested values and units in the user's language. Avoid extra progress-only drafts, repeated calculations, and unrequested files.
If no suitable tool or required data exists, identify the actual gap and ask for help; do not invent a result.
The user's request authorizes ordinary calculations. Never ask permission again merely to discover or run a calculation tool. No tool being loaded yet is NOT evidence of a missing tool; use skill_find or a known skill_load first.
Preserve ALL original deliverable constraints during corrections, including scientific notation, precision, assumptions, exclusions and language. Never remove a requested representation merely to pass a numerical check.
If Python or file creation is explicitly forbidden, do not use it as a fallback after a professional tool fails. Describe the observed limitation instead.
"""

COMBINED_REVIEW_GUIDANCE = """This is the single combined execution-and-answer assessment, not a preliminary readiness check.
Independently check BOTH that every user-requested operation actually happened AND that the candidate answer correctly reports the observed results.
Use complete only when both conditions hold. Check values, units, requested precision, requested output files, language and exclusions.
Successful native professional tools constitute real calculation evidence. Do not demand execute_python, a new file or a duplicate calculation unless the user actually requested that operation.
Set requires_python_execution only for an explicit Python execution or program-testing requirement, never merely for a numeric task.
If a requested operation is missing or failed, choose continue. If observations already suffice but wording, numbers or language are wrong, choose revise_answer, not continue.
Do not accept a progress announcement or promise as the final answer, even when the operations are complete.
If the user supplied inputs but no objective, choose clarify rather than approving an invented task.
These instructions do not establish scientific validity by themselves. Preserve every underlying evidence, artifact and numerical check.
Keep feedback concise and cite actual successful call IDs.
"""


def combined_review_request(state, context, settings, *, protocol_feedback=None, defer_compaction=False):
    # Local imports avoid a cycle through completion -> context -> this module.
    from .completion import review_request
    from .compaction import fit_request

    request = review_request(state, context, settings, phase="answer", protocol_feedback=protocol_feedback, defer_compaction=True)
    if state["metadata"].get("requirement_coverage"):
        from .delivery_contract import covered_request
        request = covered_request(request, state)
    messages = (replace(request.messages[0], content=request.messages[0].content + "\n" + COMBINED_REVIEW_GUIDANCE), *request.messages[1:])
    request = replace(request, messages=messages)
    return request if defer_compaction else fit_request(request, state, settings, phase="review")

"""Explicit answer-length constraints and bounded, non-evidentiary repair hints."""
from dataclasses import replace
import hashlib
import json
import re

from ..contracts import Message
from .delivery_contract import task_text


_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
_RANGE = re.compile(
    r"(?:\u7528|\u4ee5|\u5199(?:\u6210)?|\u63a7\u5236(?:\u5728|\u4e3a)|"
    r"\u9650\u5236(?:\u5728|\u4e3a)|\u5b57\u6570(?:\u63a7\u5236)?(?:\u5728|\u4e3a)?)\s*"
    rf"(?P<minimum>{_NUMBER})\s*[-\u2013\u2014~\uff5e\u81f3\u5230]\s*"
    rf"(?P<maximum>{_NUMBER})\s*(?:\u4e2a)?\u5b57(?:\u7b26)?(?!\u6bcd)"
)
_NEGATED = re.compile(r"\u4e0d\u8981|\u4e0d\u5fc5|\u65e0\u9700|\u4e0d\u7528|\u4e0d\u8981\u6c42|\u53d6\u6d88|\u4e0d\u518d|\u4e0d\u6309|\u4e0d\s*$")
_GUIDANCE = (
    "Final-answer constraints below apply to the delivered answer, not to tool arguments. "
    "The current user's instructions remain authoritative. Satisfy all still-applicable "
    "requirements together; repairing a citation must not undo a length or content repair. "
    "An explicit character range is inclusive. Count all non-whitespace characters, "
    "including punctuation, document titles, page numbers and Markdown delimiters; only "
    "registered internal citation markers are excluded. Aim near the middle of the range. "
    "Rewrite concisely; do not truncate, hide text, drop required evidence, or fabricate facts. "
    "Prior repair feedback is a hint about rejected drafts, NOT source evidence, execution "
    "proof, approval, or a current source binding. Recheck it against the current answer "
    "and original bound sources. Keep claim-local citations. When the user permits "
    "insufficient evidence, distinguish a source's classification from independent proof, "
    "and precisely identify what the retrieved excerpts do not establish. Do not claim "
    "the entire library lacks evidence unless that has actually been established."
)


def answer_length_requirement(state):
    """Recognize only explicit, unambiguous Chinese character ranges, not token budgets."""
    text = task_text(state)
    text = re.sub(r"```.*?```|~~~.*?~~~|`[^`\n]*`", "", text, flags=re.S)
    text = re.sub(r"(?m)^\s*>[^\n]*", "", text)
    ranges = set()
    for match in _RANGE.finditer(text):
        prefix = re.split(r"[\u3002\uff01\uff1f\uff1b\n]", text[:match.start()])[-1]
        if _NEGATED.search(prefix[-24:]):
            continue
        low = int(match['minimum'].replace(',', ''))
        high = int(match['maximum'].replace(',', ''))
        if not 0 < low <= high <= 1_000_000:
            return None
        ranges.add((low, high))
    return next(iter(ranges)) if len(ranges) == 1 else None


def answer_character_count(answer, state):
    """Exclude only actual registered citation IDs; never remove arbitrary brackets."""
    refs = state.get('metadata', {}).get('knowledge', {}).get('references', {})
    if isinstance(refs, dict):
        ids = refs.keys()
    elif isinstance(refs, list):
        ids = [item.get('citation_id') for item in refs if isinstance(item, dict)]
    else:
        ids = ()
    text = answer
    for citation_id in ids:
        if isinstance(citation_id, str) and citation_id:
            text = text.replace('[' + citation_id + ']', '')
    return sum(not char.isspace() for char in text)


def answer_length_issues(state):
    from .completion import CompletionIssue
    requirement = answer_length_requirement(state)
    answer = state.get('answer', '')
    if requirement is None or not answer.strip():
        return []
    low, high = requirement
    actual = answer_character_count(answer, state)
    if low <= actual <= high:
        return []
    return [CompletionIssue(
        message=(f"Answer length requirement: {actual} non-whitespace characters; "
                 f"required {low}-{high} inclusive. Registered internal citation markers "
                 "are excluded; punctuation, titles, page numbers and Markdown delimiters "
                 "count. Rewrite the answer within the range while retaining the required "
                 "content, accurate source bindings and explicit evidence limitations."),
        needs_action=False)]


def constrain_answer_request(request, state):
    requirement = answer_length_requirement(state)
    rejected = state.get('metadata', {}).get('rejected_answers', [])[-3:]
    if requirement is None and not rejected:
        return request
    data = {'repair_hints_are_evidence': False}
    if requirement is not None:
        low, high = requirement
        data['answer_character_range'] = {'minimum': low, 'maximum': high,
                                         'suggested_target': (low + high) // 2}
    if rejected:
        data['prior_repair_hints'] = [{
            'rejected_draft_sha256': hashlib.sha256(item['answer'].encode('utf-8')).hexdigest(),
            'feedback': item['feedback'],
            'character_count': answer_character_count(item['answer'], state),
        } for item in rejected]
    supplement = Message('user', json.dumps({
        'answer_delivery_constraints': data, 'constraint_guidance': _GUIDANCE,
    }, ensure_ascii=False))
    return replace(request, messages=(*request.messages, supplement))

"""Recognize regional literature comparisons and their default deliverables."""

import re


_REGIONAL = re.compile(
    r"(?:区域|地区|成矿带|省份|矿集区).{0,18}(?:适用性|对比|比较|差异|迁移)"
    r"|(?:跨区|跨区域|各区域|不同地区|不同成矿带)"
    r"|(?:对比|比较).{0,40}(?:地区|区域|省|成矿带|矿集区)"
    r"|\b(?:regional applicability|cross.regional|compar\w+ (?:across|between) (?:regions|provinces|belts|districts))\b",
    re.I,
)
_RESEARCH = re.compile(
    r"文献|调研|综述|研究|检索|汇总|\b(?:research|literature|survey|review|synthesis)\b", re.I,
)
_OUTPUT_OVERRIDE = re.compile(
    r"(?:不要|不用|无需|不需要|不必|不生成|请勿|禁止).{0,8}(?:图件?|报告|文件)"
    r"|(?:只|仅)(?:需|要|用|输出|给出|提供|保存).{0,8}(?:文字|文本|表格|CSV|对话内|摘要|报告)"
    r"|(?:no|without|do not |don't ).{0,12}(?:figures?|charts?|reports?|files?)"
    r"|\b(?:text|csv|table|report)[- ]only\b", re.I,
)


def regional_research(question):
    return bool(_REGIONAL.search(question) and _RESEARCH.search(question))


def regional_deliverables(state):
    from .runtime_knowledge import confirmed_plan, knowledge_query

    metadata = state.get("metadata", {})
    if metadata.get("read_only") or metadata.get("is_subagent"):
        return False
    task = state.get("task", "")
    question = knowledge_query(task)
    plan = confirmed_plan(task)
    return regional_research(question) and not _OUTPUT_OVERRIDE.search(
        question + "\n" + str(plan.get("deliverables") or ""))


DELIVERY_GUIDANCE = (
    "For this regional research comparison, save both a standalone Markdown report and a comparative figure "
    "in previewable SVG or PNG. Use the same regions, comparison criteria and evidence in both. "
    "A Markdown or CSV table alone does not fulfill the figure deliverable. Prefer self-contained SVG with "
    "plain text labels and no external assets. Embed the saved figure in the Markdown using an image link "
    "relative to the report's own directory. When using knowledge-base evidence, include the current "
    "receipt's exact citation IDs near the claims in the report and relevant labels or legend of the figure. "
    "A bibliography-only excerpt is a lead, not a finding. Finish the files before delivering the final links."
)

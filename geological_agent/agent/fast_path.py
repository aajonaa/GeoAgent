"""Deterministic fast-path guards to slim redundant synchronous LLM review stages.

These predicates are strictly conservative: any task involving tools, artifacts,
file/code obligations, ambiguous bare data, or unfinished-work promises falls
through to the full LLM review pipeline unchanged.
"""
import re

_GREETING_OR_IDENTITY = re.compile(
    r"^(?:"
    r"(?:你好|您好|嗨|哈喽|早上好|下午好|晚上好|谢谢|感谢|在吗|hi|hello|hey|thanks|thank you)[!！。.~～?？\s]*"
    r"|(?:请问)?(?:你|您|这个(?:系统|平台|产品|助手|智能体))(?:是|叫)(?:谁|什么(?:名字|产品|系统|助手|智能体)?)[?？。\s]*"
    r"|(?:请问)?(?:介绍一下(?:你|您)?自己|你(?:能|可以)做什么|你有什么功能)[?？。\s]*"
    r"|(?:请问)?(?:你|当前|现在|目前)(?:用的|使用(?:的)?|运行(?:的)?|背后(?:的)?|底层(?:的)?)?(?:是)?(?:什么|哪个|哪款)(?:大)?模型[?？。\s]*"
    r"|(?:who\s+are\s+you|what\s+are\s+you|what\s+(?:model|llm)\s+(?:are\s+you|is\s+running)|introduce\s+yourself)[?.!\s]*"
    r")$",
    re.I,
)

_BARE_COORDS_OR_DATA = re.compile(
    r"^[\s,;:，；：()（）\[\]\-\+\d\.°′″NSEWnsew/\\]+$"
)

_VAGUE_STUB = re.compile(
    r"^(?:这个|那个|它|帮我|请)?(?:智能体|工具|模型|文件|附件|数据|结果|问题|查一下|看一下|帮我看下|看看|分析一下|处理一下|怎么弄|怎么样)[?？。\s]*$",
    re.I,
)

_CLEAR_INTENT_SIGNAL = re.compile(
    r"(?:什么|为什么|为何|如何|怎么|怎样|哪些|多少|是否|能否|区别|对比|比较|解释|说明|介绍|概括|总结|列举|分析|计算|求解|推导|证明|绘制|生成|编写|写一个|查询|检索|查找|评估|预测)"
    r"|\b(?:what|why|how|which|where|when|compare|explain|describe|summarize|list|analyze|calculate|compute|solve|plot|generate|write|create|find|search|evaluate|predict)\b",
    re.I,
)

_UNFINISHED_PROMISE = re.compile(
    r"(?:^|\n)\s*(?:接下来我(?:将|会|先)|下一步我(?:将|会)|稍后我(?:将|会)|我现在(?:将|去|先)(?:读取|检查|计算|执行|调用|查看)"
    r"|next[, ]+i\s+will\b|i\s+will\s+(?:now\s+)?(?:calculate|compute|run|execute|inspect|read|check|create|write|generate|verify)\b)",
    re.I,
)


def extract_current_request(task: str) -> str:
    _, marker, current = (task or "").rpartition("\nCurrent user request:\n")
    return (current if marker else (task or "")).strip()


def is_direct_conversational_query(task: str) -> bool:
    """True only for unmistakable greetings or direct product/model identity questions."""
    current = extract_current_request(task)
    if not current or len(current) > 120 or "\n" in current:
        return False
    return bool(_GREETING_OR_IDENTITY.fullmatch(current))


def has_clear_objective(task: str, human_replies=()) -> bool:
    """Conservative deterministic check for an explicit user objective (GEOTOOL_SLIM_INTENT=1).

    Returns False on any bare coordinates/numbers, vague stubs, or unclear fragments
    so those still route to LLM assess_task_intent for clarification.
    """
    if human_replies:
        return False
    current = extract_current_request(task)
    if not current:
        return False
    if is_direct_conversational_query(current):
        return True
    if _BARE_COORDS_OR_DATA.fullmatch(current) or _VAGUE_STUB.fullmatch(current):
        return False
    # Bare labeled coordinates/numbers like "Beijing: 39.9, 116.4; Shanghai: 31.2, 121.4"
    alpha_or_cjk = re.findall(r"[A-Za-z]+|[\u3400-\u9fff]+", current)
    if not alpha_or_cjk:
        return False
    if len(current) < 6:
        return False
    if not _CLEAR_INTENT_SIGNAL.search(current):
        return False
    # Require either a question mark or enough substance beyond a lone verb.
    if "?" in current or "？" in current:
        return True
    return len("".join(alpha_or_cjk)) >= 6


def promises_unfinished_work(answer: str) -> bool:
    if not isinstance(answer, str) or not answer.strip():
        return True
    return bool(_UNFINISHED_PROMISE.search(answer))


def can_skip_completion_review(state: dict, *, read_only: bool) -> str | None:
    """Return fast-path reason if LLM completion review is redundant, else None.

    Called ONLY AFTER all deterministic checks (requested_execution_issues,
    reference_gaps, artifact_issues, answer_length_issues, delivery_issues,
    and completion_checks including citation_issues) have already passed.
    """
    answer = state.get("answer", "")
    if not answer.strip() or promises_unfinished_work(answer):
        return None
    if state.get("artifacts"):
        return None
    if state.get("metadata", {}).get("rejected_answers"):
        # Once a draft was rejected, keep the full LLM auditor in the loop.
        return None
    if read_only:
        # Ask mode cannot execute code, write files, or call professional tools.
        # Deterministic checks + (if knowledge refs exist) quote-bound semantic
        # verification in publish() cover all read-only invariants directly.
        return "read_only_fast_path"
    has_tools = any(m.role == "tool" for m in state.get("messages", ()))
    has_refs = bool(state.get("metadata", {}).get("knowledge", {}).get("references"))
    if not has_tools and not has_refs and is_direct_conversational_query(state.get("task", "")):
        return "direct_conversational_fast_path"
    return None

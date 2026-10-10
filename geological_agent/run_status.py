"""Presentation-only classification of recorded failures and task outcomes."""
import json


_EVIDENCE_ERRORS = (
    "Compared term needs its exact quoted source evidence",
    "Quoted text is absent from the exact source field",
    "Supported block needs exact evidence for all its cited sources",
    "Cross-language source claim omitted its technical-term comparison",
)


def issue_for_event(event, fields):
    """Classify actual events, never infer execution or change recovery control."""
    review = event in ("completion_review_protocol_error", "completion_review_recovery")
    if event == "knowledge_semantic_checked" and fields.get("passed") is True:
        return None
    if event not in {
        "completion_review_protocol_error", "completion_review_recovery",
        "model_protocol_error", "model_protocol_recovery", "model_failed",
        "completion_rejected", "completion_check_error", "knowledge_semantic_checked",
    }:
        return None
    error = fields.get("error", "")
    error = error if isinstance(error, str) else ""
    category = "review_format" if review else "model_protocol"
    if event in ("completion_rejected", "knowledge_semantic_checked"):
        category = "answer_validation"
    elif event == "completion_check_error":
        category = "verification_error"
    elif event == "model_failed" or error.startswith((
        "Model provider error:", "HTTPStatusError:", "ReadTimeout:", "ConnectError:",
    )) or fields.get("error_type") in {
        "HTTPStatusError", "ReadTimeout", "ConnectTimeout", "ConnectError", "PoolTimeout",
    }:
        category = "model_service"
    elif review and error.startswith("Invalid source review blocks: "):
        try:
            errors = json.loads(error[len("Invalid source review blocks: "):])
        except (ValueError, TypeError):
            errors = None
        if isinstance(errors, dict) and errors and all(
            isinstance(value, str) and value.startswith(_EVIDENCE_ERRORS)
            for value in errors.values()
        ):
            category = "review_evidence"
    return {
        "category": category, "event": event, "phase": fields.get("phase"),
        "turn": fields.get("turn"),
        "blocking": event.endswith("_recovery") and fields.get("action") == "pause_assessment",
    }


def task_outcome(fields, last_issue=None):
    """Task success is not the same as a transport/span ending normally."""
    status = fields.get("status", "unknown")
    pending = fields.get("metadata", {}).get("pending_input") or {}
    runtime_pause = status == "needs_input" and (
        pending.get("recovery_origin") == "runtime" or pending.get("reason_type") == "model_protocol"
    )
    category = None
    if status == "completed":
        business = "completed"
    elif status == "needs_input":
        if runtime_pause:
            phase = pending.get("recovery_phase")
            issue = issue_for_event("model_protocol_recovery" if phase == "intent" else "completion_review_recovery", {
                "phase": phase, "error": pending.get("reason") or fields.get("error", ""),
            })
            category = (last_issue or issue or {}).get("category")
            business = "review_blocked" if (
                phase == "knowledge_semantics" or category in {
                    "review_evidence", "review_format", "answer_validation", "verification_error",
                }
            ) else "model_blocked"
        else:
            business = "awaiting_user" if pending else "awaiting_input"
    else:
        business = status if status in ("failed", "stopped", "budget_exhausted", "incomplete") else "not_completed"
        category = (last_issue or {}).get("category")
    return {
        "task_status": status, "business_state": business, "task_completed": status == "completed",
        "failure_category": category, "requires_user_action": status == "needs_input",
        "recovery_required": runtime_pause,
    }

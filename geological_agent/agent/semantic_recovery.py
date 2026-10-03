"""Incremental source audits, with durable protocol-cycle recovery."""
import json

from .completion import CompletionIssue
from .knowledge_semantics import (
    fingerprint, material, semantic_request, parse_semantic_review, SemanticReviewProtocolError)
from ..llm import ModelProtocolError
from ..tool_evidence import identity


def review_sources(state, *, settings, model, cancel, record, trace, activity, pause):
    if not settings.verify_completion or not state["metadata"].get("knowledge", {}).get("references"):
        return state, []
    stamp = fingerprint(state)
    previous = state["metadata"].get("knowledge_semantic_reviews", [])
    if previous and previous[-1]["fingerprint"] == stamp and previous[-1].get("complete_coverage", True):
        return state, [CompletionIssue(message) for message in previous[-1]["issues"]]
    saved = state["metadata"].get("semantic_review_progress", {})
    progress = ({"fingerprint": stamp, "checks": {}, "issues": [], "failure_signatures": []}
                if saved.get("fingerprint") != stamp else
                {**saved, "checks": dict(saved["checks"]), "issues": list(saved["issues"]),
                 "failure_signatures": list(saved.get("failure_signatures", []))})
    state = {**state, "metadata": {**state["metadata"], "semantic_review_progress": progress,
             "semantic_pending_draft": {"answer": state["answer"], "fingerprint": stamp,
                                        "trust": "unverified candidate, not evidence"}}}
    blocks = material(state)["answer_blocks"]
    feedback, attempt = None, 0
    while True:
        if cancel.is_set():
            return {**state, "status": "stopped", "answer": "", "last_error": "Stopped by user"}, []
        if settings.max_model_turns is not None and state["model_turns"] >= settings.max_model_turns:
            return {**state, "status": "budget_exhausted", "answer": "",
                    "last_error": "Model-turn budget exhausted before source semantic review; draft not published"}, []
        pending = [key for key in blocks if key not in progress["checks"]]
        if not pending:
            verdict = {"passed": not progress["issues"], "checks": progress["checks"],
                       "issues": progress["issues"], "complete_coverage": True,
                       "scope": "Exact quote/coverage checks plus model-assisted semantics; not scientific certification."}
            audit = {**verdict, "fingerprint": stamp, "turn": state["model_turns"]}
            state["metadata"]["knowledge_semantic_reviews"] = previous + [audit]
            state["metadata"].pop("semantic_review_progress", None)
            if verdict["passed"]:
                state["metadata"].pop("semantic_pending_draft", None)
            trace.emit("knowledge_semantic_checked", run_id=state["run_id"], **audit)
            record(state, state)
            return state, [CompletionIssue(message) for message in verdict["issues"]]
        request = semantic_request(state, settings, protocol_feedback=feedback, block_ids=pending)
        attempt += 1
        turn = state["model_turns"] + 1
        state = {**state, "model_turns": turn}
        record(state, state)
        trace.emit("completion_review_requested", run_id=state["run_id"], turn=turn, request=request,
                   phase="knowledge_semantics", attempt=attempt)
        activity("completion_review", turn=turn, phase="knowledge_semantics", attempt=attempt)
        response = None
        try:
            response = model.invoke(request)
            state = {**state, "metadata": {**state["metadata"],
                     "usage": state["metadata"]["usage"] + [response.usage]}}
            trace.emit("completion_review_responded", run_id=state["run_id"], turn=turn, response=response,
                       phase="knowledge_semantics", attempt=attempt)
            verdict = parse_semantic_review(response, request)
        except ModelProtocolError as exc:
            error = str(exc)
            if isinstance(exc, SemanticReviewProtocolError):
                progress["checks"].update(exc.checks)
                progress["issues"].extend(exc.issues)
            pending = [key for key in blocks if key not in progress["checks"]]
            failure = {"turn": turn, "attempt": attempt, "error": error, "pending_blocks": pending}
            state["metadata"]["knowledge_semantic_protocol_errors"] = (
                state["metadata"].get("knowledge_semantic_protocol_errors", []) + [failure])
            state["metadata"]["semantic_review_progress"] = progress
            trace.emit("completion_review_protocol_error", run_id=state["run_id"],
                       phase="knowledge_semantics", **failure)
            record(state, state)
            if progress["issues"]:
                # Valid negative findings permit revision, NEVER approval.
                audit = {"passed": False, "checks": progress["checks"],
                         "issues": progress["issues"], "complete_coverage": False,
                         "invalid_blocks": getattr(exc, "block_errors", {}),
                         "fingerprint": stamp, "turn": turn}
                state["metadata"]["knowledge_semantic_reviews"] = previous + [audit]
                trace.emit("knowledge_semantic_checked", run_id=state["run_id"], **audit)
                record(state, state)
                return state, [CompletionIssue(message) for message in progress["issues"]]
            signature = identity([stamp, pending, error])
            repeated_failure = signature in progress["failure_signatures"]
            progress["failure_signatures"].append(signature)
            if repeated_failure:
                return pause(state, "knowledge_semantics", error), []
            rejected = []
            if response is not None:
                for call in response.tool_calls:
                    if call.name == "assess_knowledge_semantics":
                        try:
                            value = json.loads(call.arguments) if isinstance(call.arguments, str) else call.arguments
                            if isinstance(value, dict) and isinstance(value.get("checks"), dict):
                                rejected.append({key: value["checks"].get(key) for key in pending})
                        except (ValueError, TypeError):
                            pass
            feedback = {"error": error, "pending_blocks": pending, "rejected_checks": rejected,
                        "instruction": "Correct only pending blocks; malformed blocks authorize no approval or task action."}
            continue
        progress["checks"].update(verdict["checks"])
        progress["issues"].extend(verdict["issues"])
        state["metadata"]["semantic_review_progress"] = progress

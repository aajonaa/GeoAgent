"""Incremental source audits, with durable protocol-cycle recovery."""
from concurrent.futures import ThreadPoolExecutor
import json
import math
import re
from dataclasses import replace
import time

from .completion import CompletionIssue
from .compaction import ContextOverflow
from .knowledge_semantics import (
    fingerprint, material, semantic_request, parse_semantic_review, SemanticReviewProtocolError)
from ..llm import ModelProtocolError
from ..tool_evidence import identity
from ..contracts import strict_json


def observed_numeric_result(receipt, tool_names):
    """Render finite numeric outputs from a successful registered tool receipt."""
    if (not isinstance(receipt, dict) or receipt.get("status") != "ok"
            or receipt.get("name") not in tool_names or not isinstance(receipt.get("data"), dict)):
        return None
    values = []
    for key, value in receipt["data"].items():
        if (re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key)
                and not re.search(r"(?:^|_)(?:id|port|token|key|credential|password|secret)(?:_|$)", key, re.I)
                and type(value) in (int, float) and (type(value) is int or math.isfinite(value))):
            values.append(f"`{key}` = {value}")
        if len(values) == 8:
            break
    return f"`{receipt['name']}` · " + "，".join(values) if values else None


def numeric_results_from_receipts(receipts, task):
    from .execution_contract import obligations
    names = {receipt["name"] for receipt in receipts
             if isinstance(receipt, dict) and isinstance(receipt.get("name"), str)}
    requested = obligations({"task": task}, names)[2]
    results = [observed_numeric_result(receipt, requested) for receipt in receipts]
    return list(dict.fromkeys(item for item in results if item))[-3:]


def partial_delivery(state):
    metadata = state["metadata"]
    registry = set(metadata.get("professional_tool_names", []))
    calls = {call.id: call.name for message in state["messages"] if message.role == "assistant"
             for call in message.tool_calls}
    results = list(reversed(metadata.get("partial_numeric_results", [])[-3:]))
    for message in reversed(state["messages"]):
        if len(results) == 3:
            break
        if message.role != "tool":
            continue
        try:
            receipt = strict_json(message.content)
        except (ValueError, TypeError):
            continue
        if (not isinstance(receipt, dict) or receipt.get("call_id") != message.tool_call_id
                or calls.get(message.tool_call_id) != receipt.get("name")):
            continue
        result = observed_numeric_result(receipt, registry)
        if result and result not in results:
            results.append(result)
    if not results:
        return partial_source_answer(state)
    sources = partial_source_answer(state)
    prefix = "## 已取得的工具结果\n\n" + "\n".join("- " + item for item in reversed(results))
    return prefix + "\n\n" + (sources or "**仍待核实**：以上为本轮工具的原始输出。文献解释和其余交付尚未完成核验。")


def partial_source_answer(state):
    """Return audited prose; raw search excerpts remain in the reference panel."""
    metadata = state["metadata"]
    audits = [metadata.get("semantic_review_progress", {}),
              *reversed(metadata.get("knowledge_semantic_reviews", []))]
    drafts = [state["answer"], metadata.get("semantic_pending_draft", {}).get("answer", ""),
              *(row["answer"] for row in reversed(metadata.get("rejected_answers", [])))]
    for draft in dict.fromkeys(drafts):
        if not draft.strip():
            continue
        candidate = {**state, "answer": draft}
        stamp = fingerprint(candidate)
        blocks = material(candidate)["answer_blocks"]
        # Keep the original audit numbering but select only prose outside fences.
        prose = re.sub(r"(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?(?:^\s*\1[ \t]*$|\Z)", "", draft)
        prose_blocks = set(material({**candidate, "answer": prose})["answer_blocks"].values())
        for audit in audits:
            if audit.get("fingerprint") != stamp:
                continue
            rejected = {match[1] for issue in audit["issues"]
                        if (match := re.match(r"Source semantics (b\d+):", issue))}
            verified = []
            for key, block in blocks.items():
                check = audit["checks"].get(key, {})
                if (key not in rejected and check.get("verdict") == "supported"
                        and check.get("evidence_bindings", {}).get("quotes")
                        and block in prose_blocks and not block.startswith(("#", "|"))):
                    verified.append(block)
            if verified:
                return ("## 已核验的部分\n\n" + "\n\n".join(dict.fromkeys(verified)) +
                        "\n\n**仍待核实**：其余论断或交付项尚未得到充分支持。")

    return ""


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
    feedback, attempt, stagnant_attempts = None, 0, 0
    while True:
        if cancel.is_set():
            return {**state, "status": "stopped", "answer": "", "last_error": "Stopped by user"}, []
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
        if settings.max_model_turns is not None and state["model_turns"] >= settings.max_model_turns - 1:
            return {**state, "status": "budget_exhausted", "answer": "",
                    "last_error": "Model-turn budget exhausted before source semantic review; draft not published"}, []
        # Parallelize independent 4-block library_first batches on clean passes
        # to cut multi-paragraph citation audit latency by 2-3x without relaxing checks.
        if state["metadata"].get("library_first") and len(pending) > 4 and feedback is None:
            remaining_budget = (
                max(0, (settings.max_model_turns - 1) - state["model_turns"])
                if settings.max_model_turns is not None else 3
            )
            max_parallel = min(3, remaining_budget)
            chunks = [pending[i:i + 4] for i in range(0, len(pending), 4)][:max_parallel]
            if len(chunks) >= 2:
                try:
                    chunk_requests = [
                        (chunk, replace(semantic_request(state, settings, block_ids=chunk),
                                        transport=progress.get("response_transport", "auto")))
                        for chunk in chunks
                    ]
                except ContextOverflow as exc:
                    trace.emit("completion_check_error", run_id=state["run_id"], error=str(exc), phase="knowledge_semantics")
                    return pause(state, "knowledge_semantics", str(exc)), []
                chunk_meta = []
                for chunk, req in chunk_requests:
                    attempt += 1
                    turn = state["model_turns"] + 1
                    state = {**state, "model_turns": turn}
                    chunk_meta.append((chunk, req, turn, attempt))
                    trace.emit("completion_review_requested", run_id=state["run_id"], turn=turn, request=req,
                               phase="knowledge_semantics", attempt=attempt)
                    activity("completion_review", turn=turn, phase="knowledge_semantics", attempt=attempt)
                record(state, state)
                batch_t0 = time.monotonic()

                def _invoke_chunk(req):
                    try:
                        return model.invoke(req), None
                    except Exception as exc:
                        return None, exc

                with ThreadPoolExecutor(max_workers=len(chunk_meta)) as pool:
                    futures = [pool.submit(_invoke_chunk, req) for _, req, _, _ in chunk_meta]
                    outcomes = [f.result() for f in futures]
                elapsed_ms = round((time.monotonic() - batch_t0) * 1000, 1)
                state["metadata"]["semantic_parallel_batches"] = state["metadata"].get("semantic_parallel_batches", 0) + 1
                trace.emit("semantic_review_parallel_batch", run_id=state["run_id"],
                           chunks=len(chunk_meta), blocks=sum(len(c) for c, _, _, _ in chunk_meta),
                           elapsed_ms=elapsed_ms)
                transient_error = None
                for (chunk, req, turn, att), (resp, exc) in zip(chunk_meta, outcomes):
                    if exc is not None:
                        if isinstance(exc, (RuntimeError, TimeoutError, ConnectionError)) and (
                            isinstance(exc, (TimeoutError, ConnectionError)) or re.search(
                                r"\b(?:502|503|504|524)\b|timed? ?out|connection (?:reset|broken)", str(exc), re.I)
                        ):
                            transient_error = exc
                            continue
                        if not isinstance(exc, ModelProtocolError):
                            raise exc
                        failure = {"turn": turn, "attempt": att, "error": str(exc), "pending_blocks": chunk}
                        state["metadata"]["knowledge_semantic_protocol_errors"] = (
                            state["metadata"].get("knowledge_semantic_protocol_errors", []) + [failure])
                        trace.emit("completion_review_protocol_error", run_id=state["run_id"],
                                   phase="knowledge_semantics", **failure)
                        continue
                    state = {**state, "metadata": {**state["metadata"],
                             "usage": state["metadata"]["usage"] + [resp.usage]}}
                    trace.emit("completion_review_responded", run_id=state["run_id"], turn=turn, response=resp,
                               phase="knowledge_semantics", attempt=att)
                    try:
                        verdict = parse_semantic_review(resp, req)
                    except ModelProtocolError as parse_exc:
                        if isinstance(parse_exc, SemanticReviewProtocolError):
                            progress["checks"].update(parse_exc.checks)
                            progress["issues"].extend(parse_exc.issues)
                        failure = {"turn": turn, "attempt": att, "error": str(parse_exc), "pending_blocks": chunk}
                        state["metadata"]["knowledge_semantic_protocol_errors"] = (
                            state["metadata"].get("knowledge_semantic_protocol_errors", []) + [failure])
                        trace.emit("completion_review_protocol_error", run_id=state["run_id"],
                                   phase="knowledge_semantics", **failure)
                        continue
                    progress["checks"].update(verdict["checks"])
                    progress["issues"].extend(verdict["issues"])
                state["metadata"]["semantic_review_progress"] = progress
                record(state, state)
                if transient_error is not None:
                    state["metadata"]["source_review_unavailable"] = True
                    record(state, state)
                    return pause(state, "knowledge_semantics", "Source verification service temporarily unavailable"), []
                stagnant_attempts = 0
                feedback = None
                continue
        try:
            batch = pending[:4] if state["metadata"].get("library_first") else pending
            request = semantic_request(state, settings, protocol_feedback=feedback, block_ids=batch)
        except ContextOverflow as exc:
            trace.emit("completion_check_error", run_id=state["run_id"], error=str(exc), phase="knowledge_semantics")
            return pause(state, "knowledge_semantics", str(exc)), []
        request = replace(request, transport=progress.get("response_transport", "auto"))
        attempt += 1
        turn = state["model_turns"] + 1
        state = {**state, "model_turns": turn}
        record(state, state)
        trace.emit("completion_review_requested", run_id=state["run_id"], turn=turn, request=request,
                   phase="knowledge_semantics", attempt=attempt)
        activity("completion_review", turn=turn, phase="knowledge_semantics", attempt=attempt)
        response = None
        accepted_before = len(progress["checks"])
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
            diagnostic = getattr(exc, "diagnostic", {})
            if diagnostic:
                failure["diagnostic"] = diagnostic
                failure["transport"] = request.transport
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
            transport_kind = diagnostic.get("kind")
            if (request.transport == "auto" and transport_kind in
                    ("stream_incomplete", "invalid_stream", "unexpected_content_type")):
                # The NEXT existing-budget turn changes transport, never the schema,
                # source evidence or semantic checks. No hidden HTTP retry.
                progress["response_transport"] = "full_response"
                trace.emit("completion_review_recovery", run_id=state["run_id"],
                           phase="knowledge_semantics", action="retry_full_response",
                           from_transport="auto", to_transport="full_response",
                           error=error, diagnostic=diagnostic)
                record(state, state)
                continue
            if transport_kind:
                # Explicit provider rejection or a failed fallback needs attention,
                # not a loop over the same invalid request.
                return pause(state, "knowledge_semantics", error), []
            signature = identity([stamp, pending, error])
            repeated_failure = signature in progress["failure_signatures"]
            progress["failure_signatures"].append(signature)
            stagnant_attempts = 0 if len(progress["checks"]) > accepted_before else stagnant_attempts + 1
            if repeated_failure or stagnant_attempts >= 3:
                trace.emit("completion_review_recovery", run_id=state["run_id"],
                           phase="knowledge_semantics", action="pause_no_progress",
                           attempts=attempt, stagnant_attempts=stagnant_attempts,
                           pending_blocks=pending, error=error)
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
        except (RuntimeError, TimeoutError, ConnectionError) as exc:
            transient = isinstance(exc, (TimeoutError, ConnectionError)) or re.search(
                r"\b(?:502|503|504|524)\b|timed? ?out|connection (?:reset|broken)", str(exc), re.I)
            if not transient:
                raise
            # Preserve the actual checkpoint and any completed checks. The parent
            # may deliver an explicitly provisional, ordinarily reviewed answer.
            state["metadata"]["source_review_unavailable"] = True
            record(state, state)
            return pause(state, "knowledge_semantics", "Source verification service temporarily unavailable"), []
        progress["checks"].update(verdict["checks"])
        feedback = None
        progress["issues"].extend(verdict["issues"])
        stagnant_attempts = 0
        state["metadata"]["semantic_review_progress"] = progress

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from contextlib import nullcontext
from pathlib import Path
from threading import Event, Lock
import json
import os
import re
import time
import uuid
from ..contracts import ErrorInfo, Message, ModelRequest, RunResult, ToolCall, ToolResult
from ..context_budget import input_allowance, request_budget_size
from ..llm import ModelProtocolError, extract_cache_usage, missing_native_tool_message, native_response_diagnostic
from ..tools import ToolExecutionContext, ToolExecutor, ToolFailure
from ..tracing import NullTrace
from .context import ContextManager
from .skill_scope import fit_skill_scope
from .resource_policy import resource_request, source_tools_available, missing_reference_paths, source_attempted, repair_guidance
from ..tool_evidence import EvidenceLedger, identity, reference_gaps, reference_gap_message
from .compaction import ContextOverflow, fingerprint, fit_request, request_size
from .retrieval_progress import SEARCH_TOOLS, unchanged, redirect_request
from .interaction_policy import human_input_issue, enrich_request
from .human_review import human_review_request, parse_human_review
from .intent_review import intent_request, parse_intent
from .compact_review import compact_review_request, parse_compact_review
from .delivery_contract import parse_covered_review, delivery_issues
from .answer_constraints import answer_length_issues, constrain_answer_request
from .execution_contract import requested_execution_issues
from .graph import build_graph
from .fast_path import can_skip_completion_review, has_clear_objective, is_direct_conversational_query
from .review_policy import combined_review_request
from .completion import CompletionIssue, artifact_issues, final_answer_request, resolve_final_answer, parse_review, review_evidence_issues, review_request, successful_evidence_ids
from .runtime_knowledge import (
    knowledge_receipt_feedback,
    _NON_LIBRARY_SCOPE,
    bounded_json_call,
    knowledge_query,
    missing_attachment as _missing_attachment_check,
    requested_library,
    run_knowledge_retrieval,
    source_context,
    theory_library_query,
)
from .runtime_recovery import (
    build_rejected_final_update,
    compose_source_partial,
    pause_review_protocol_state,
    prepare_compacted_request,
    recover_model_protocol_step,
)


class AgentRuntime:
    def __init__(self, model, settings, tools, skills, memory, knowledge, base_tools, trace_factory=None, completion_checks=(), context_store=None, *, read_only=False, is_subagent=False):
        self.model, self.settings, self.tools, self.skills = model, settings, tools, skills
        self.base_tools = tuple(base_tools)
        self.professional_tool_names = frozenset(
            name for summary in skills.registry.list() for name in skills.load(summary.id).tool_names
            if name not in self.base_tools)
        self.executor = ToolExecutor(tools)
        self.context = ContextManager(settings, tools, skills, memory, knowledge)
        self.trace_factory = trace_factory or (lambda run_id, workspace: NullTrace())
        self.completion_checks = tuple(completion_checks)
        self.context_store = context_store
        self.read_only = read_only
        self.is_subagent = is_subagent

    def run(self, query, *, workspace: Path, skill_id=None, cancel_event=None, on_text=None, on_event=None,
            checkpoint_path=None, resume=None, input_origins=None):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("A nonempty task is required")
        workspace = Path(workspace).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        if resume is not None and ((checkpoint_path is None and self.context_store is None) or not isinstance(resume, dict) or
                                   not re.fullmatch(r"[a-f0-9]{32}", str(resume.get("run_id", "")))):
            raise ValueError("A valid saved run and checkpoint are required to resume")
        if "request_user_input" in self.base_tools and checkpoint_path is None and self.context_store is None:
            raise ValueError("Human input requires a durable checkpoint")
        run_id = resume["run_id"] if resume is not None else uuid.uuid4().hex
        cancel = cancel_event if cancel_event is not None else Event()
        trace = self.trace_factory(run_id, workspace)
        started = time.monotonic()
        selected = [skill_id] if skill_id else []
        exposed = list(self.base_tools)
        for sid in selected:
            for name in self.skills.load(sid).tool_names:
                self.tools.get(name)
                if name not in exposed:
                    exposed.append(name)
        initial = {"run_id": run_id, "task": query, "messages": [Message("user", query)], "selected_skill_ids": selected,
                   "exposed_tool_names": exposed, "pending_tool_calls": [], "artifacts": [], "status": "running",
                   "model_turns": 0, "last_error": None, "answer": "", "metadata": {"usage": [], "workspace": str(workspace),
                   "optimize_round_trips": os.environ.get("GEOTOOL_OPTIMIZE_ROUND_TRIPS") == "1",
                   "combined_completion_review": os.environ.get("GEOTOOL_COMBINED_COMPLETION_REVIEW") == "1",
                   "requirement_coverage": os.environ.get("GEOTOOL_REQUIREMENT_COVERAGE") == "1",
                   "read_only": self.read_only,
                   "is_subagent": self.is_subagent,
                   "intent_review": False if self.is_subagent else (self.read_only or os.environ.get("GEOTOOL_INTENT_REVIEW") == "1"),
                   "slim_intent": os.environ.get("GEOTOOL_SLIM_INTENT") == "1",
                   "compact_review": os.environ.get("GEOTOOL_COMPACT_REVIEW") == "1",
                   "compact_discovery": os.environ.get("GEOTOOL_COMPACT_DISCOVERY") == "1",
                   "review_reference_sets": os.environ.get("GEOTOOL_REVIEW_REFERENCE_SETS") == "1",
                   "professional_tool_names": sorted(self.professional_tool_names)}}
        execution = ToolExecutionContext(run_id, workspace, tuple(exposed), self.settings, cancel)
        latest = initial
        pending_delivery = None
        prev_exec_prefix = None
        from ..team.case_catalog import default_case_operations, fixed_case_arguments, next_fixed_operation
        case_operations = default_case_operations(query, input_origins, workspace)
        origins_pending = True
        trace.emit("run_started", run_id=run_id, task=query, selected_skills=selected)

        def record_cache_metrics(metadata, request, response, phase):
            nonlocal prev_exec_prefix
            cache = extract_cache_usage(getattr(response, "usage", None))
            metrics = dict(metadata.get("prompt_cache_metrics") or {
                "execution_turns": 0,
                "system_prefix_stable_turns": 0,
                "append_only_prefix_turns": 0,
                "provider_reported_turns": 0,
                "total_prompt_tokens": 0,
                "total_cached_tokens": 0,
                "total_cache_creation_tokens": 0,
                "cache_hit_ratio": None,
                "system_prefix_sha256": None,
            })
            if cache["prompt_tokens"] is not None:
                metrics["total_prompt_tokens"] += cache["prompt_tokens"]
            if cache["cached_tokens"] is not None:
                metrics["provider_reported_turns"] += 1
                metrics["total_cached_tokens"] += cache["cached_tokens"]
            if cache["cache_creation_tokens"] is not None:
                metrics["total_cache_creation_tokens"] += cache["cache_creation_tokens"]
            if metrics["provider_reported_turns"] and metrics["total_prompt_tokens"] > 0:
                metrics["cache_hit_ratio"] = round(
                    min(1.0, metrics["total_cached_tokens"] / metrics["total_prompt_tokens"]), 4)
            if phase == "execution" and request.messages:
                msg_hashes = [fingerprint(asdict(m)) for m in request.messages]
                sys_hash = msg_hashes[0]
                metrics["execution_turns"] += 1
                if metrics["system_prefix_sha256"] == sys_hash:
                    metrics["system_prefix_stable_turns"] += 1
                metrics["system_prefix_sha256"] = sys_hash
                if prev_exec_prefix is not None and len(msg_hashes) >= len(prev_exec_prefix):
                    if msg_hashes[:len(prev_exec_prefix)] == prev_exec_prefix:
                        metrics["append_only_prefix_turns"] += 1
                prev_exec_prefix = msg_hashes
            metadata["prompt_cache_metrics"] = metrics
            return cache

        def record_cascade_skip(metadata, kind, *, saved_turns=1):
            metrics = dict(metadata.get("review_cascade_metrics") or {
                "source_selection_skipped": 0,
                "intent_review_skipped": 0,
                "completion_review_skipped": 0,
                "saved_model_turns": 0,
            })
            metrics[kind] = metrics.get(kind, 0) + 1
            metrics["saved_model_turns"] = metrics.get("saved_model_turns", 0) + saved_turns
            metadata["review_cascade_metrics"] = metrics

        def activity(kind, **data):
            if on_event is not None:
                on_event({"kind": kind, **data})

        def record(update, state):
            nonlocal latest
            latest = {**state, **update}
            if self.context_store is not None:
                self.context_store.sync_state(latest)
                update = {**update, "metadata": latest["metadata"]}
            return update


        def prepare_request(request, state, phase):
            return prepare_compacted_request(
                request, state, phase,
                settings=self.settings, model=self.model, cancel=cancel,
                run_id=run_id, record=record, trace=trace, activity=activity,
                archive=self.context_store,
            )

        def recover_model_protocol(state, error, response, *, tool_choice, phase="execution"):
            return recover_model_protocol_step(
                state, error, response, tool_choice=tool_choice, phase=phase,
                settings=self.settings, cancel=cancel, run_id=run_id,
                checkpoint_path=checkpoint_path, context_store=self.context_store,
                record=record, trace=trace, ask_human=ask_human,
            )

        def pause_review_protocol(state, phase, error):
            return pause_review_protocol_state(
                state, phase, error, settings=self.settings, cancel=cancel, run_id=run_id, trace=trace,
            )

        def bounded_json(state, phase, instruction, data):
            return bounded_json_call(
                state, phase, instruction, data,
                settings=self.settings, model=self.model, cancel=cancel,
                run_id=run_id, record=record, trace=trace, activity=activity,
            )

        def retrieve_knowledge(state):
            return run_knowledge_retrieval(
                state, retriever=self.context.knowledge, workspace=workspace,
                case_operations=case_operations, bounded_json=bounded_json,
                cancel=cancel, run_id=run_id, record=record, trace=trace, activity=activity,
                record_cascade_skip=record_cascade_skip,
            )

        def missing_attachment(state):
            return _missing_attachment_check(state, workspace)

        def model_turn(state):
            metadata = dict(state["metadata"])
            metadata.pop("runtime_control_resume", None)
            state = {**state, "metadata": metadata}

            def commit_model(update, current):
                # The graph commits returned updates, not the local state copy.
                return record({"selected_skill_ids": current["selected_skill_ids"],
                               "exposed_tool_names": current["exposed_tool_names"],
                               **update}, current)

            if cancel.is_set():
                return commit_model({"status": "stopped", "last_error": "Stopped by user"}, state)
            if missing_attachment(state):
                answer = (
                    "这项总结还缺原始附件。请上传需要概括的文件，或直接粘贴正文。\n\n"
                    "材料到齐前，可以先按三个字段整理：主要结论、对应证据、页码或图表位置。"
                    if re.search(r"[\u3400-\u9fff]", knowledge_query(state["task"])) else
                    "Please attach the document to summarize, or paste its text. While the file is missing, prepare three fields for each conclusion: the finding, the evidence, and the page or figure."
                )
                return publish({**state, "answer": answer}, "incomplete", "缺少原始附件")
            if self.settings.max_model_turns is not None and state["model_turns"] >= self.settings.max_model_turns:
                if state["metadata"].get("semantic_pending_draft"):
                    return publish_source_partial(state)
                return commit_model({"status": "budget_exhausted", "last_error": "Configured model-turn budget exhausted; files are retained"}, state)
            if state["metadata"].get("resume_review_candidate"):
                metadata = dict(state["metadata"])
                saved = metadata.pop("resume_review_candidate")
                metadata["resume_review_phase"] = saved["phase"]
                metadata["final_answer_composed"] = saved["final_answer_composed"]
                metadata["execution_ready"] = saved["execution_ready"]
                if saved["phase"] == "review:answer_revision":
                    # An explicit recovery retries composition, not execution or
                    # the already rejected candidate's assessment.
                    metadata.pop("resume_review_phase", None)
                    metadata.pop("answer_repair_progress", None)
                    metadata.pop("final_answer_composed", None)
                    metadata["next_tool_choice"] = "none"
                    state = {**state, "metadata": metadata, "answer": "",
                             "pending_tool_calls": [], "last_error": None}
                else:
                    return commit_model({"metadata": metadata, "answer": saved["candidate"],
                                         "pending_tool_calls": [], "last_error": None}, state)
            if state["metadata"].get("intent_review") and not state["metadata"].get("objective_checked"):
                if (state["metadata"].get("slim_intent")
                        and not state["metadata"].get("compact_discovery")
                        and has_clear_objective(state["task"], state["metadata"].get("human_responses", ()))):
                    metadata = dict(state["metadata"])
                    metadata["objective_checked"] = True
                    metadata["intent_fast_path"] = True
                    record_cascade_skip(metadata, "intent_review_skipped")
                    state = {**state, "metadata": metadata}
                    trace.emit("intent_review_skipped", run_id=run_id, reason="clear_objective_fast_path")
                    record(state, state)
                else:
                    turn = state["model_turns"] + 1
                    state = {**state, "model_turns": turn}
                    record(state, state)
                    response = None
                    intent_requested = intent_responded = False
                    try:
                        summaries = self.skills.registry.list() if state["metadata"].get("compact_discovery") else None
                        catalog = ({summary.id: [
                            {"name": name, "purpose": self.tools.peek(name).definition.description}
                            for name in self.skills.load(summary.id).tool_names if name in self.professional_tool_names]
                            for summary in summaries} if summaries is not None else None)
                        request = intent_request(state, self.settings, skill_summaries=summaries, skill_tools=catalog)
                        request = prepare_request(request, state, "intent")
                        trace.emit("model_requested", run_id=run_id, turn=turn, messages=request.messages,
                                   tools=[t.name for t in request.tools], tool_definitions=request.tools,
                                   tool_choice="required", phase="intent")
                        intent_requested = True
                        activity("model_requested", turn=turn, tool_choice="required", phase="intent")
                        response = self.model.invoke(request)
                        trace.emit("model_responded", run_id=run_id, turn=turn, response=response, phase="intent")
                        intent_responded = True
                        metadata = {**state["metadata"], "usage": state["metadata"]["usage"] + [response.usage]}
                        state = {**state, "metadata": metadata}
                        decision = parse_intent(response, skill_summaries=summaries)
                        if metadata.get("protocol_recovery", {}).get("phase") == "intent":
                            metadata.pop("protocol_recovery", None)
                            state = {**state, "metadata": metadata, "last_error": None}
                        if len(response.tool_calls) > 1:
                            coalesced = {"turn": turn, "call_ids": [call.id for call in response.tool_calls],
                                         "count": len(response.tool_calls), "assessment": decision}
                            metadata = {**metadata, "intent_assessment_coalesces":
                                        metadata.get("intent_assessment_coalesces", []) + [coalesced]}
                            state = {**state, "metadata": metadata}
                            trace.emit("intent_assessment_coalesced", run_id=run_id, **coalesced)
                        if cancel.is_set():
                            return commit_model({**state, "status": "stopped", "last_error": "Stopped by user"}, state)
                        if not decision["objective_present"]:
                            question = decision["question"].strip()
                            if checkpoint_path is not None or self.context_store is not None:
                                return ask_human(state, {"question": question, "reason": "Missing task objective",
                                                         "missing": ["task objective"], "options": []})
                            return publish({**state, "answer": question}, "needs_input", "Missing task objective")
                        candidates = list(dict.fromkeys(decision.get("skill_ids", [])))
                        state = {**state, "selected_skill_ids": list(dict.fromkeys(
                                    [*state["selected_skill_ids"], *candidates])),
                                 "metadata": {**metadata, "objective_checked": True,
                                              "intent_selected_skill_ids": candidates,
                                              "skill_scope_source": "intent_selection"}}
                        record(state, state)
                    except ModelProtocolError as exc:
                        if intent_requested and not intent_responded:
                            trace.emit("model_failed", run_id=run_id, turn=turn,
                                       error=f"{type(exc).__name__}: {exc}", phase="intent")
                        trace.emit("model_protocol_error", run_id=run_id, turn=turn, error=str(exc), phase="intent")
                        return recover_model_protocol(state, exc, response, tool_choice="required", phase="intent")
                    except Exception as exc:
                        event = "model_failed" if intent_requested and not intent_responded else "intent_assessment_error"
                        trace.emit(event, run_id=run_id, turn=turn, error=f"{type(exc).__name__}: {exc}", phase="intent")
                        return commit_model({**state, "status": "failed", "answer": "",
                                       "last_error": f"Intent assessment failed: {type(exc).__name__}: {exc}"}, state)
                    if self.settings.max_model_turns is not None and state["model_turns"] >= self.settings.max_model_turns:
                        return commit_model({**state, "status": "budget_exhausted", "last_error": "Model-turn budget exhausted after intent assessment"}, state)
            turns = state["model_turns"] + 1
            metadata = dict(state["metadata"])
            tool_choice = metadata.pop("next_tool_choice", "auto")
            if self.read_only and metadata.get("read_only_retrieval_exhausted"):
                tool_choice = "none"
            stalled_retrieval = metadata.pop("retrieval_route_once", [])
            pending_execution = requested_execution_issues(state, self.professional_tool_names)
            if tool_choice == "auto" and pending_execution:
                tool_choice = "required"
            response = None
            try:
                answer_only = tool_choice == "none" and self.settings.verify_completion
                def assemble(current):
                    built = (final_answer_request(current, self.context, self.settings, defer_compaction=True)
                             if answer_only else replace(self.context.build(current, defer_compaction=True), tool_choice=tool_choice))
                    if current["metadata"].get("library_first"):
                        built = replace(built, messages=(*built.messages, Message("user",
                            "Use the relevant shared-library passages already retrieved first. Cite each local finding with its exact "
                            "[K...] ID at the claim. Distinguish deposit observations, regional inferences and testable hypotheses. "
                            "Use public primary sources only to fill a specific gap if permitted; cite the URL actually read alongside "
                            "the added claim. If the library evidence is sufficient, proceed to the requested deliverable.")))
                    built = constrain_answer_request(built, current)
                    if tool_choice == "none" and not answer_only:
                        built = replace(built, tools=())
                    if current["metadata"].get("requirement_coverage"):
                        built = enrich_request(built, current, self.settings, defer_compaction=True)
                    if pending_execution and tool_choice != "none":
                        built = replace(built, messages=(*built.messages, Message(
                            "user", "Unfulfilled execution requirement: " +
                            "\n".join(issue.message for issue in pending_execution))))
                    if not answer_only and tool_choice != "none":
                        built = redirect_request(built, stalled_retrieval)
                        return resource_request(built, self.tools, execution.workspace)
                    return built, None

                state = {**state, "metadata": metadata}
                if not answer_only and tool_choice != "none":
                    state, scope = fit_skill_scope(state, build_request=lambda current: assemble(current)[0],
                        base_tool_names=self.base_tools, skills=self.skills, settings=self.settings,
                        archive=self.context_store)
                    metadata = dict(state["metadata"])
                    if scope is not None:
                        trace.emit("skill_scope_updated", run_id=run_id, **scope)
                        activity("skill_scope_updated", **scope)
                        for sid in scope["activated_skill_ids"]:
                            trace.emit("skill_loaded", run_id=run_id, skill_id=sid,
                                       skill_name=self.skills.load(sid).summary.name,
                                       exposed_tools=scope["exposed_tool_names"], source=scope["source"])
                            activity("skill_loaded", skill_id=sid, source=scope["source"])
                    if "prompt_prefix_anchor" not in metadata:
                        metadata["prompt_prefix_anchor"] = {
                            "skill_ids": list(state["selected_skill_ids"]),
                            "deferred_skill_ids": list(metadata.get("deferred_skill_ids", ())),
                            "has_reference_tools": any(self.tools.peek(n).reference_paths for n in state["exposed_tool_names"]),
                            "web_names": [n for n in ("web_search", "web_fetch") if n in state["exposed_tool_names"]],
                            "has_context_read": "context_read" in state["exposed_tool_names"],
                            "has_update_todo": "update_todo" in state["exposed_tool_names"],
                            "has_delegate_subagent": "delegate_subagent" in state["exposed_tool_names"],
                            "has_run_codeact": "run_codeact" in state["exposed_tool_names"],
                        }
                        if self.settings.memory_enabled and "prefix_memory_snapshot" not in metadata:
                            metadata["prefix_memory_snapshot"] = [
                                {"kind": "memory", **asdict(m)} for m in self.context.memory.search(state["task"], limit=3)
                            ]
                        state = {**state, "metadata": metadata}
                request, availability = assemble(state)
                if not answer_only and tool_choice != "none":
                    if availability != metadata.get("resource_availability"):
                        trace.emit("resource_availability", run_id=run_id, availability=availability)
                    metadata["resource_availability"] = availability
                state = {**state, "metadata": metadata}
                request = prepare_request(request, state, "final_answer" if answer_only else "execution")
                metadata = state["metadata"]
                if not answer_only and tool_choice != "none":
                    metadata["execution_available_tool_names"] = [tool.name for tool in request.tools]
                if cancel.is_set():
                    return commit_model({**state, "status": "stopped", "last_error": "Stopped by user"}, state)
                if self.settings.max_model_turns is not None and state["model_turns"] >= self.settings.max_model_turns:
                    return commit_model({**state, "status": "budget_exhausted", "answer": "",
                                         "last_error": "Model-turn budget exhausted after context compaction"}, state)
                if case_operations and not self.read_only and not answer_only and tool_choice != "none":
                    scheduled = metadata.get("scheduled_case_operations", [])
                    op = next_fixed_operation(case_operations, scheduled, metadata["execution_available_tool_names"])
                    if op is not None:
                        call = ToolCall(uuid.uuid4().hex, op["tool"], op["arguments"])
                        metadata["scheduled_case_operations"] = [*scheduled, op["operation_id"]]
                        trace.emit("case_operation_scheduled", run_id=run_id, operation_id=op["operation_id"],
                                   tool=call.name, call_id=call.id)
                        return commit_model({"messages": [*state["messages"], Message("assistant", "", (call,))],
                                             "pending_tool_calls": [call], "answer": "", "last_error": None,
                                             "metadata": metadata}, state)
                turns = state["model_turns"] + 1
                phase_name = "final_answer" if answer_only else "execution"
                trace.emit("model_requested", run_id=run_id, turn=turns, messages=request.messages,
                           tools=[t.name for t in request.tools], tool_definitions=request.tools, tool_choice=request.tool_choice,
                           phase=phase_name)
                activity("model_requested", turn=turns, tool_choice=request.tool_choice, phase=phase_name)
                if on_text is None:
                    response = self.model.invoke(request)
                else:
                    response = None
                    for event in self.model.stream(request):
                        if event.kind == "response":
                            response = event.response
                    if response is None:
                        raise ModelProtocolError("Stream did not produce a complete model response")
                cache_usage = record_cache_metrics(metadata, request, response, phase_name)
                trace.emit("model_responded", run_id=run_id, turn=turns, response=response, cache_usage=cache_usage)
                metadata["usage"] = metadata["usage"] + [response.usage]
                if answer_only:
                    response = resolve_final_answer(response, request)
                if response.finish_reason not in ("stop", "tool_calls"):
                    raise ModelProtocolError(f"Incomplete response ({response.finish_reason}); produce a complete call or concise final answer")
                if tool_choice == "none" and response.tool_calls:
                    raise ModelProtocolError("This request is answer-only; no tool call was authorized. Use the verified observations to deliver the corrected final answer")
                if tool_choice == "required" and not response.tool_calls:
                    raise ModelProtocolError(missing_native_tool_message(response))
                if not response.tool_calls and not response.content.strip():
                    if tool_choice == "none":
                        raise ModelProtocolError("The answer-only response was empty. Deliver the concrete results from verified observations, not a plan or a promise to inspect them")
                    if request.tools:
                        metadata["next_tool_choice"] = "required"
                        metadata["native_tool_recovery_pending"] = True
                        raise ModelProtocolError("Empty response; the next request requires a native tool call. Select a currently exposed tool using its schema. Automatic choice resumes after the tool result")
                    raise ModelProtocolError("Empty response; use a tool or provide a response")
                blocked = set((metadata.get("resource_availability") or {}).get("blocked_tools", []))
                unavailable = blocked.intersection(call.name for call in response.tool_calls)
                if unavailable:
                    raise ModelProtocolError("Tool input prerequisites are unmet; these functions were not exposed in this request: " +
                                             ", ".join(sorted(unavailable)) +
                                             ". Use an actually exposed acquisition or clarification tool; no action from this response was executed")
                previous_ids = {call.id for msg in state["messages"] for call in msg.tool_calls}
                ids = [call.id for call in response.tool_calls]
                if any(not i for i in ids) or len(ids) != len(set(ids)) or previous_ids.intersection(ids):
                    raise ModelProtocolError("Each tool call must have a fresh unique ID")
                if case_operations and response.tool_calls:
                    bound_calls = []
                    for call in response.tool_calls:
                        args = fixed_case_arguments(case_operations, call.name)
                        if args is not None and call.name in metadata.get("execution_available_tool_names", ()):
                            call = replace(call, arguments=args)
                        bound_calls.append(call)
                    response = replace(response, tool_calls=tuple(bound_calls))
                # Delivery candidates are not working instructions for later tools.
                messages = list(state["messages"]) if answer_only else state["messages"] + [Message(
                    "assistant", response.content, response.tool_calls, reasoning_content=response.reasoning_content)]
                if not answer_only:
                    metadata.pop("execution_ready", None)
                metadata.pop("protocol_recovery", None)
                metadata.pop("answer_protocol_failures", None)
                if response.tool_calls:
                    metadata.pop("execution_repair_draft", None)
                metadata["final_answer_composed"] = answer_only and not response.tool_calls
                return commit_model({"messages": messages, "model_turns": turns, "pending_tool_calls": list(response.tool_calls),
                               "answer": "" if response.tool_calls else response.content, "metadata": metadata, "last_error": None}, state)
            except ModelProtocolError as exc:
                if tool_choice != "none":
                    trace.emit("model_protocol_error", run_id=run_id, error=str(exc),
                               diagnostic=native_response_diagnostic(response, tool_choice))
                    return recover_model_protocol(
                        {**state, "model_turns": turns, "metadata": metadata}, exc, response,
                        tool_choice=tool_choice)
                trace.emit("model_protocol_error", run_id=run_id, error=str(exc))
                failures = metadata.get("answer_protocol_failures", 0) + 1
                metadata["answer_protocol_failures"] = failures
                if failures >= 2:
                    return publish_source_partial({**state, "metadata": metadata, "model_turns": turns})
                metadata["next_tool_choice"] = "none"
                return commit_model({"model_turns": turns, "last_error": str(exc), "metadata": metadata, "messages": state["messages"] +
                               [Message("user", "Runtime feedback: " + str(exc) + ". No tool from that invalid response was executed.")]}, state)
            except Exception as exc:
                trace.emit("model_failed", run_id=run_id, error=f"{type(exc).__name__}: {exc}")
                status = ("stopped" if cancel.is_set() else "budget_exhausted"
                          if self.settings.max_model_turns is not None and state["model_turns"] >= self.settings.max_model_turns else "failed")
                return commit_model({"status": status, "model_turns": state["model_turns"] if status != "failed" else max(turns, state["model_turns"]),
                                     "metadata": state["metadata"], "last_error": f"{type(exc).__name__}: {exc}"}, state)

        def review_human_pause(state, call):
            metadata = dict(state["metadata"])
            if cancel.is_set() or (self.settings.max_model_turns is not None and state["model_turns"] >= self.settings.max_model_turns):
                metadata["human_review_stop"] = "stopped" if cancel.is_set() else "budget_exhausted"
                return {**state, "metadata": metadata}, "Human-input assessment could not run within the remaining budget; no question was published."
            turn = state["model_turns"] + 1
            state = {**state, "model_turns": turn, "metadata": metadata}
            record(state, state)
            try:
                request = human_review_request(state, call, self.context, self.skills, self.settings)
                request = prepare_request(request, state, "human_review")
                trace.emit("completion_review_requested", run_id=run_id, turn=turn, request=request, phase="human_input", attempt=1)
                activity("completion_review", turn=turn, phase="human_input", attempt=1)
                response = self.model.invoke(request)
                metadata["usage"] = metadata["usage"] + [response.usage]
                trace.emit("completion_review_responded", run_id=run_id, turn=turn, response=response, phase="human_input", attempt=1)
                assessment = parse_human_review(response)
                metadata["human_input_reviews"] = metadata.get("human_input_reviews", []) + [assessment]
                state = {**state, "metadata": metadata}
                if assessment["decision"] == "continue":
                    return state, "Do not pause: " + assessment["feedback"]
                return state, None
            except Exception as exc:
                trace.emit("completion_review_protocol_error", run_id=run_id, phase="human_input", turn=turn, attempt=1, error=str(exc))
                return {**state, "metadata": metadata}, "Human-input assessment failed; the question was not published: " + str(exc)

        def execute_tools(state):
            from .semantic_recovery import observed_numeric_result
            nonlocal origins_pending
            messages = list(state["messages"])
            metadata = dict(state["metadata"])
            prior_calls = {c.id: c for message in messages for c in message.tool_calls}
            repeated = []
            artifacts = {a.path: a for a in state["artifacts"]}
            selected, exposed = list(state["selected_skill_ids"]), list(state["exposed_tool_names"])
            # A call must have been disclosed in the request that produced it.
            evidence_state = metadata.setdefault("tool_evidence", {})
            if origins_pending:
                evidence_state.setdefault("files", {}).update(input_origins or {})
                origins_pending = False
            def invoke_vision(request):
                nonlocal state, metadata
                if cancel.is_set():
                    raise RuntimeError("Visual request cancelled before submission")
                if self.settings.max_model_turns is not None and state["model_turns"] >= self.settings.max_model_turns:
                    raise RuntimeError("Model-turn budget exhausted before image interpretation")
                if ((request_budget_size(request, self.settings) > input_allowance(self.settings))
                        if self.settings.context_window_tokens is not None else
                        (sum(len(m.content) for m in request.messages) > self.settings.max_context_chars)):
                    raise ContextOverflow("Visual question exceeds the configured text allowance")
                turn = state["model_turns"] + 1
                state = {**state, "model_turns": turn, "metadata": metadata}
                record(state, state)
                trace.emit("model_requested", run_id=run_id, turn=turn, messages=request.messages,
                           tools=[], tool_definitions=(), tool_choice="none", phase="vision")
                activity("model_requested", turn=turn, tool_choice="none", phase="vision")
                try:
                    response = self.model.invoke(request)
                    trace.emit("model_responded", run_id=run_id, turn=turn, response=response, phase="vision")
                    metadata = {**metadata, "usage": metadata.get("usage", []) + [response.usage]}
                    return response
                except Exception as exc:
                    trace.emit("model_failed", run_id=run_id, turn=turn, error=str(exc), phase="vision")
                    raise
            disclosed = metadata.get("execution_available_tool_names", exposed)
            subagent_runner = None
            if not self.is_subagent and any(n in disclosed for n in ("delegate_subagent", "run_subagents_parallel")):
                from .subagent import SubagentCoordinator
                subagent_runner = SubagentCoordinator(
                    parent_runtime=self,
                    parent_run_id=run_id,
                    workspace=execution.workspace,
                    cancel=cancel,
                    parent_metadata=metadata,
                    metadata_lock=Lock(),
                    trace=trace,
                    activity=activity,
                    remaining_budget_fn=lambda: (
                        None if self.settings.max_model_turns is None
                        else max(0, self.settings.max_model_turns - state["model_turns"])
                    ),
                )
            codeact_bridge = None
            if not self.is_subagent and "run_codeact" in disclosed:
                from .codeact import CodeActBridge
                codeact_bridge = CodeActBridge(
                    executor=self.executor,
                    allowed_tools=tuple(disclosed),
                    trace=trace,
                    parent_run_id=run_id,
                    activity=activity,
                )
            ctx = replace(execution, allowed_tool_names=tuple(disclosed), evidence_state=evidence_state,
                          vision_invoke=invoke_vision, subagent_runner=subagent_runner, codeact_bridge=codeact_bridge)
            last_error = None
            missing_resources = set()
            batch = state["pending_tool_calls"]
            human_positions = [i for i, c in enumerate(batch) if c.name == "request_user_input"]
            ordered_pause = (state["metadata"].get("optimize_round_trips") and
                             human_positions == [len(batch) - 1])
            mixed_human_request = len(batch) != 1 and bool(human_positions) and not ordered_pause
            earlier_failed = False
            searching = any(c.name == "skill_find" for c in batch)

            parallel_read_only = frozenset({
                "read_file", "web_search", "web_fetch",
                "context_search", "context_read", "skill_find", "GeoOpenAlexSearch",
            })
            serial_only = frozenset({
                "request_user_input", "skill_load", "write_file", "execute_python",
                "update_todo", "delegate_subagent", "run_subagents_parallel", "run_codeact",
            })

            def _is_parallel_safe(call):
                if (mixed_human_request or case_operations
                        or self.executor.execution_adapter is not None
                        or call.name in serial_only
                        or call.name not in disclosed):
                    return False
                if call.name in parallel_read_only:
                    return True
                try:
                    tool = self.tools.peek(call.name)
                except ToolFailure:
                    return False
                return bool(tool.pure and not tool.input_paths)

            groups = []
            current_run = []
            for call in batch:
                if _is_parallel_safe(call):
                    current_run.append(call)
                else:
                    if current_run:
                        groups.append(("parallel" if len(current_run) >= 2 else "serial", current_run))
                        current_run = []
                    groups.append(("serial", [call]))
            if current_run:
                groups.append(("parallel" if len(current_run) >= 2 else "serial", current_run))

            def _commit_tool_outcome(call, result):
                nonlocal last_error, earlier_failed
                if result.status == "ok":
                    arguments = json.loads(call.arguments) if isinstance(call.arguments, str) else call.arguments
                    if call.name == "GeoResearchPlan" and "steps" in arguments:
                        metadata["research_plan"] = result.data
                    if call.name == "update_todo":
                        metadata["todo_list"] = result.data
                        trace.emit("todo_updated", run_id=run_id, counts=result.data.get("counts"),
                                   items=result.data.get("items"))
                        activity("todo_updated", counts=result.data.get("counts"),
                                 items=result.data.get("items"))
                    count = 0
                    for message in messages:
                        if message.role != "tool" or message.tool_call_id not in prior_calls:
                            continue
                        previous = json.loads(message.content)
                        if previous["status"] != "ok":
                            continue
                        old_call = prior_calls[message.tool_call_id]
                        old_args = json.loads(old_call.arguments) if isinstance(old_call.arguments, str) else old_call.arguments
                        if unchanged(call.name, arguments, result.data, old_call.name, old_args, previous["data"]):
                            count += 1
                    if count:
                        repeated.append(f"{call.name} has returned unchanged successful evidence {count + 1} times. This call added no new evidence. Query wording, cache flags and timestamps do not establish new facts. Reuse the observations and change strategy rather than repeating successful work.")
                        if call.name in SEARCH_TOOLS:
                            metadata["retrieval_route_once"] = list(dict.fromkeys([
                                *metadata.get("retrieval_route_once", []), call.name]))
                        if self.read_only and call.name in ("context_search", "context_read"):
                            progress = metadata.setdefault("read_only_retrieval_progress", {})
                            progress[call.name] = progress.get(call.name, 0) + 1
                            if progress[call.name] >= 1:
                                metadata["read_only_retrieval_exhausted"] = True
                                trace.emit("read_only_retrieval_exhausted", run_id=run_id,
                                           tool=call.name, unchanged_returns=count + 1)
                messages.append(result.message())
                trace.emit("tool_completed" if result.status == "ok" else "tool_failed", run_id=run_id, result=result)
                if result.status == "ok" and call.name in self.professional_tool_names:
                    observed = observed_numeric_result(asdict(result), self.professional_tool_names)
                    if observed:
                        metadata["partial_numeric_results"] = list(dict.fromkeys([
                            *metadata.get("partial_numeric_results", []), observed]))[-3:]
                activity("tool_result", name=call.name, status=result.status)
                earlier_failed = earlier_failed or result.status != "ok"
                if result.status == "ok" and call.name not in ("skill_find", "skill_load"):
                    metadata.pop("native_tool_recovery_pending", None)
                artifacts.update({a.path: a for a in result.artifacts})
                if result.error:
                    last_error = result.error.message
                    missing_resources.update(missing_reference_paths(result))
                if (result.error and not result.error.retryable and
                        fixed_case_arguments(case_operations, call.name) is not None):
                    reason = f"{call.name} 按案例参数执行失败（{result.error.code}）：{result.error.message}"
                    updated = {**state, "messages": messages, "metadata": metadata,
                               "pending_tool_calls": [], "artifacts": list(artifacts.values())}
                    return publish(
                        {**updated, "answer": reason}, "incomplete", reason)
                if result.status == "ok" and call.name == "request_user_input":
                    updated = {**state, "messages": messages, "pending_tool_calls": [], "artifacts": list(artifacts.values()),
                               "selected_skill_ids": selected, "exposed_tool_names": exposed, "last_error": None,
                               "metadata": metadata}
                    return ask_human(updated, result.data)
                if result.status == "ok" and call.name == "skill_load":
                    sid = result.data["skill_id"]
                    skill = self.skills.load(sid)
                    if sid not in selected:
                        selected.append(sid)
                    for name in skill.tool_names:
                        self.tools.get(name)
                        if name not in exposed:
                            exposed.append(name)
                    metadata["skill_scope_focus"] = list(dict.fromkeys([
                        *metadata.get("skill_scope_focus", []), sid]))
                return None

            for mode, group in groups:
                if mode == "parallel" and not cancel.is_set():
                    for call in group:
                        trace.emit("tool_requested", run_id=run_id, call=call)
                        activity("tool_requested", name=call.name)
                    batch_t0 = time.monotonic()
                    with ThreadPoolExecutor(max_workers=min(4, len(group))) as pool:
                        futures = [pool.submit(self.executor.execute, call, ctx) for call in group]
                        results = [future.result() for future in futures]
                    elapsed_ms = round((time.monotonic() - batch_t0) * 1000, 1)
                    batch_info = {"count": len(group), "tools": [c.name for c in group], "elapsed_ms": elapsed_ms}
                    metadata["parallel_tool_batches"] = metadata.get("parallel_tool_batches", []) + [batch_info]
                    trace.emit("parallel_tool_batch", run_id=run_id, **batch_info)
                    for call, result in zip(group, results):
                        early = _commit_tool_outcome(call, result)
                        if early is not None:
                            return early
                    continue
                for call in group:
                    trace.emit("tool_requested", run_id=run_id, call=call)
                    activity("tool_requested", name=call.name)
                    if mixed_human_request:
                        result = ToolResult(call.id, call.name, "error", error=ErrorInfo(
                            "input_request_must_be_alone", "No action from this batch was executed. Request human input alone, or, when ordered pauses are enabled, place exactly one request last after independent actions. Never execute actions after a request for missing input.", True))
                    elif call.name == "request_user_input" and (earlier_failed or cancel.is_set()):
                        result = ToolResult(call.id, call.name, "error", error=ErrorInfo(
                            "prior_action_failed", "The pause was not accepted because a preceding action failed or cancellation was requested. Successful prior work is retained; inspect the real outcome before asking again.", True))
                    elif searching and call.name == "skill_load":
                        result = ToolResult(call.id, call.name, "error", error=ErrorInfo(
                            "discovery_order", "Inspect the skill_find results before choosing a real skill ID in the next model turn. This load was not executed.", True))
                    else:
                        issue = human_input_issue(call, {**state, "messages": messages}, self.tools,
                                                  check_requirements=bool(metadata.get("requirement_coverage")))
                        if not issue and call.name == "request_user_input" and metadata.get("requirement_coverage"):
                            state, issue = review_human_pause({**state, "messages": messages, "metadata": metadata}, call)
                            metadata = dict(state["metadata"])
                        result = (ToolResult(call.id, call.name, "error", error=ErrorInfo("ungrounded_human_request", issue, True))
                                  if issue else self.executor.execute(call, ctx))
                    early = _commit_tool_outcome(call, result)
                    if early is not None:
                        return early
            source_tools = source_tools_available(exposed)
            if missing_resources and source_tools and not cancel.is_set():
                feedback = repair_guidance(sorted(missing_resources), source_tools)
                messages.append(Message("user", feedback))
                metadata["next_tool_choice"] = "required"
                metadata["native_tool_recovery_pending"] = True
                trace.emit("resource_recovery_scheduled", run_id=run_id,
                           missing_paths=sorted(missing_resources), source_tools=source_tools)
            unresolved = EvidenceLedger(ctx).pending_missing()
            # A stale missing-file record must not pause a successful alternative
            # source read. Missing local data is not evidence that public sources
            # are unavailable, so allow an actual acquisition attempt first.
            if source_tools and (not missing_resources or not source_attempted(messages)):
                unresolved = []
            if unresolved and not cancel.is_set():
                paths = sorted({dep["path"] for row in unresolved for dep in row["dependencies"]})
                reason = "Repeated attempts require the same missing input: " + ", ".join(paths)
                trace.emit("recovery_requires_input", run_id=run_id, paths=paths, reason=reason)
                updated = {**state, "messages": messages, "metadata": metadata, "pending_tool_calls": [],
                           "artifacts": list(artifacts.values()), "selected_skill_ids": selected,
                           "exposed_tool_names": exposed}
                if checkpoint_path is not None or self.context_store is not None:
                    chinese = bool(re.search(r"[\u3400-\u9fff]", state["task"]))
                    question = (("查询工具需要真实的数据文件或可访问来源：" + ", ".join(paths) +
                                 "。当前输入仍缺失，已有文件和结果已保留；这不代表公开数据一定不存在。")
                                if chinese else
                                "Please supply the actual missing data file(s), or an accessible source: " +
                                ", ".join(paths) + ". Existing files and results are retained; this does not prove public data is unavailable.")
                    return ask_human(updated, {"question": question,
                                               "reason": reason, "missing": paths, "options": []})
                return publish({**updated, "answer": reason}, "incomplete", reason)
            if repeated:
                feedback = "Runtime progress feedback:\n" + "\n".join(repeated)
                messages.append(Message("user", feedback))
                trace.emit("repeated_observation", run_id=run_id, feedback=feedback)
            if metadata.get("read_only_retrieval_exhausted"):
                messages.append(Message("user",
                    "Read-only historical retrieval has stopped after repeated unchanged evidence. "
                    "Use the observations already available to answer now, or ask one concise clarification. "
                    "Do not request another search or read."))
            if metadata.get("native_tool_recovery_pending"):
                # Discovery is not yet the requested operation. Preserve native
                # recovery across it, then restore auto after an actual result.
                metadata["next_tool_choice"] = "required"
            return record({"messages": messages, "artifacts": list(artifacts.values()), "selected_skill_ids": selected,
                           "exposed_tool_names": exposed, "pending_tool_calls": [], "last_error": last_error,
                           "metadata": metadata,
                            "model_turns": state["model_turns"],
                            "status": metadata.pop("human_review_stop", "stopped" if cancel.is_set() else "running")}, state)

        def ask_human(state, payload):
            question = {"id": uuid.uuid4().hex, **payload}
            metadata = {**state["metadata"], "pending_input": question}
            return record({**state, "status": "needs_input", "answer": question["question"],
                           "last_error": question["reason"], "metadata": metadata}, state)

        def wait_for_human(state):
            from langgraph.types import interrupt
            from .human_input import apply_human_reply
            pending = state["metadata"]["pending_input"]
            # No side effect before interrupt: this node is replayed on resume.
            reply = interrupt(pending)
            update = apply_human_reply(state, reply)
            update["metadata"].pop("read_only_retrieval_exhausted", None)
            update["metadata"].pop("read_only_retrieval_progress", None)
            control = update["metadata"].get("runtime_control_resume")
            trace.emit("human_input_received", run_id=run_id, request_id=pending["id"],
                       input_kind="runtime_control" if control else "clarification",
                       recovery_phase=control)
            return record(update, state)

        def source_partial(state):
            return compose_source_partial(state, execution=execution, bounded_json=bounded_json)

        def publish_source_partial(state):
            reason = "本轮已交付可核验的信息，其余内容未能确认。"
            return publish(source_partial(state), "incomplete", reason)

        def finish_review(state):
            if (state["status"] == "budget_exhausted"
                    and state["metadata"].get("knowledge", {}).get("references")):
                return publish_source_partial(state)
            return record(state, state)

        def reject_final(state, issues):
            return build_rejected_final_update(
                state, issues, run_id=run_id, record=record, trace=trace, activity=activity,
                publish_source_partial=publish_source_partial, pause_review_protocol=pause_review_protocol,
            )

        def check_knowledge_semantics(state):
            from .semantic_recovery import review_sources
            def end_source_review(candidate, _phase, error):
                return {**candidate, "status": "incomplete", "last_error": error}
            return review_sources(state, settings=self.settings, model=self.model, cancel=cancel,
                                  record=record, trace=trace, activity=activity, pause=end_source_review)

        def publish(state, status="completed", reason=None):
            nonlocal pending_delivery
            if cancel.is_set():
                return record({"status": "stopped", "answer": "", "last_error": "Stopped by user",
                               "model_turns": state["model_turns"], "metadata": state["metadata"]}, state)
            if status == "completed":
                state, semantic_issues = check_knowledge_semantics(state)
                if state["status"] in ("budget_exhausted", "incomplete"):
                    metadata = state["metadata"]
                    reviews = metadata.get("completion_reviews", [])
                    if (metadata.get("source_review_unavailable") and metadata.get("library_first")
                            and state["answer"].strip() and reviews and reviews[-1].get("verdict") == "complete"
                            and not metadata.get("semantic_review_progress", {}).get("issues")
                            and not metadata.get("rejected_answers")):
                        note = ("逐条来源复核因服务超时或连接中断未完成。以下为暂定回答，引用和具体结论仍需对照原文。"
                                if re.search(r"[\u3400-\u9fff]", knowledge_query(state["task"])) else
                                "Source verification was interrupted. This answer is provisional; check citations and conclusions against the originals.")
                        return publish({**state, "answer": note + "\n\n" + state["answer"]}, "incomplete", note)
                    return publish_source_partial(state)
                if state["status"] != "running":
                    return record(state, state)
                if semantic_issues:
                    return reject_final(state, semantic_issues)
                if cancel.is_set():
                    return record({"status": "stopped", "answer": "", "last_error": "Stopped by user",
                                   "model_turns": state["model_turns"], "metadata": state["metadata"]}, state)
            messages = list(state["messages"])
            if not messages or messages[-1].role != "assistant" or messages[-1].tool_calls or messages[-1].content != state["answer"]:
                messages.append(Message("assistant", state["answer"]))
            update = record({"status": status, "last_error": reason, "metadata": state["metadata"],
                             "model_turns": state["model_turns"], "answer": state["answer"],
                             "messages": messages}, state)
            pending_delivery = (status, state["answer"])
            return update

        def finalize(state):
            metadata = dict(state["metadata"])
            resume_phase = metadata.pop("resume_review_phase", None)
            state = {**state, "metadata": metadata}
            if cancel.is_set():
                return record({"status": "stopped", "answer": "", "last_error": "Stopped by user"}, state)

            def assess(phase):
                nonlocal state
                feedback, attempt = None, 0
                failure_signatures = set()
                while True:
                    if cancel.is_set():
                        state = {**state, "status": "stopped", "answer": "", "last_error": "Stopped by user"}
                        return None
                    if self.settings.max_model_turns is not None and state["model_turns"] >= self.settings.max_model_turns:
                        label = "execution assessment" if phase == "execution" else "completion review"
                        state = {**state, "status": "budget_exhausted", "answer": "",
                                 "last_error": f"Model-turn budget exhausted before {label}; the draft was not published"}
                        return None
                    # Recompute against the current workspace, using the same
                    # policy as execution. A previous tool may have acquired a file.
                    available, availability = resource_request(
                        ModelRequest((), self.tools.definitions(state["exposed_tool_names"])),
                        self.tools, execution.workspace)
                    state = {**state, "metadata": {**state["metadata"],
                             "execution_available_tool_names": [tool.name for tool in available.tools],
                             "resource_availability": availability}}
                    compact = phase == "combined" and state["metadata"].get("compact_review")
                    request = (compact_review_request(state, self.context, self.settings, protocol_feedback=feedback, defer_compaction=True)
                               if compact else combined_review_request(state, self.context, self.settings, protocol_feedback=feedback, defer_compaction=True)
                               if phase == "combined" else
                               review_request(state, self.context, self.settings, phase=phase, protocol_feedback=feedback, defer_compaction=True))
                    if phase in ("combined", "answer"):
                        request = replace(request, messages=(*request.messages, Message("user",
                            "Check the actual deliverables against the current user question. For a plan verify the requested "
                            "locations, methods and decision criteria; for a diagram verify an actual artifact or inline figure "
                            "and any requested predictions. Confirm that linked outputs exist in the workspace or observed results. "
                            "A list of search excerpts alone does not fulfill a request for a design, diagram or explanation. "
                            "Conditional hypotheses and proposed tests must be labeled but do not require proof that they already occurred.")))
                    request = prepare_request(request, state, "review")
                    attempt += 1
                    turn = state["model_turns"] + 1
                    state = {**state, "model_turns": turn}
                    record(state, state)
                    trace.emit("completion_review_requested", run_id=run_id, turn=turn, request=request,
                               phase=phase, attempt=attempt)
                    activity("completion_review", turn=turn, phase=phase, attempt=attempt)
                    response = None
                    try:
                        response = self.model.invoke(request)
                        state = {**state, "metadata": {**state["metadata"],
                                 "usage": state["metadata"]["usage"] + [response.usage]}}
                        record(state, state)
                        trace.emit("completion_review_responded", run_id=run_id, turn=turn, response=response,
                                   phase=phase, attempt=attempt)
                        allowed_ids = successful_evidence_ids(state["messages"]) if state["metadata"].get("optimize_round_trips") else None
                        review = (parse_compact_review(response, state, request) if compact else
                                  parse_covered_review(response, state, allowed_ids)
                                  if phase == "combined" and state["metadata"].get("requirement_coverage")
                                  else parse_review(response, allowed_evidence_ids=allowed_ids))
                    except ModelProtocolError as exc:
                        # Retry only this internal assessment. Invalid native calls
                        # never become actions, evidence, or execution messages.
                        feedback = str(exc)
                        failure = {"phase": phase, "turn": turn, "attempt": attempt, "error": feedback}
                        state = {**state, "last_error": feedback, "metadata": {**state["metadata"],
                                 "review_protocol_errors": state["metadata"].get("review_protocol_errors", []) + [failure]}}
                        record(state, state)
                        trace.emit("completion_review_protocol_error", run_id=run_id, **failure)
                        activity("completion_review_retry", turn=turn, phase=phase, attempt=attempt)
                        signature = identity([phase, state["answer"], feedback])
                        if signature in failure_signatures or attempt >= 3:
                            trace.emit("completion_review_recovery", run_id=run_id,
                                       phase=phase, action="pause_no_progress",
                                       attempts=attempt, error=feedback)
                            state = pause_review_protocol(state, "review:" + phase, feedback)
                            return None
                        failure_signatures.add(signature)
                        feedback = {"error": feedback,
                                    "rejected_native_calls": [asdict(call) for call in response.tool_calls] if response is not None else [],
                                    "instruction": "Repair this assessment against the same observed work. No workspace action or approval was accepted."}
                        continue
                    if cancel.is_set():
                        state = {**state, "status": "stopped", "answer": "", "last_error": "Stopped by user"}
                        return None
                    state = {**state, "last_error": None}
                    return review

            try:
                missing_execution = requested_execution_issues(state, self.professional_tool_names)
                if missing_execution:
                    return reject_final(state, missing_execution)
                gaps = reference_gaps(state)
                if gaps:
                    feedback = reference_gap_message(gaps)
                    signature = identity([{k: v for k, v in gap.items() if k != "call_id"} for gap in gaps])
                    trace.emit("reference_evidence_rejected", run_id=run_id, gaps=gaps, reason=feedback)
                    if state["metadata"].get("reference_recovery_signature") == signature:
                        if checkpoint_path is not None or self.context_store is not None:
                            return ask_human(state, {
                                "question": "Please provide the actual source dataset or a directly accessible source. "
                                            "The current lookup used unverified generated or unknown-origin records; "
                                            "I cannot present them as verified facts.",
                                "reason": feedback, "missing": sorted({gap["path"] for gap in gaps}), "options": []})
                        return publish({**state, "answer": feedback}, "incomplete", feedback)
                    state["metadata"]["reference_recovery_signature"] = signature
                    return reject_final(state, [CompletionIssue(feedback, True)])
                state["metadata"].pop("reference_recovery_signature", None)
                combined = self.settings.verify_completion and state["metadata"].get("combined_completion_review")
                checking_answer = combined or state["metadata"].get("final_answer_composed") or not self.settings.verify_completion
                issues = artifact_issues(state if checking_answer else {**state, "answer": ""}, execution)
                if checking_answer:
                    issues.extend(answer_length_issues(state))
                    if state["metadata"].get("requirement_coverage"):
                        issues.extend(delivery_issues(state))
                    for check in self.completion_checks:
                        issues.extend(check(state))
                if issues:
                    return reject_final(state, issues)
                if not self.settings.verify_completion:
                    return publish(state)
                fast_reason = can_skip_completion_review(state, read_only=self.read_only)
                if fast_reason is not None:
                    fast_issues = []
                    if not checking_answer:
                        fast_issues.extend(answer_length_issues(state))
                        if state["metadata"].get("requirement_coverage"):
                            fast_issues.extend(delivery_issues(state))
                        for check in self.completion_checks:
                            fast_issues.extend(check(state))
                    if fast_issues:
                        return reject_final(state, fast_issues)
                    metadata = dict(state["metadata"])
                    record_cascade_skip(metadata, "completion_review_skipped")
                    metadata.update(execution_ready=True, final_answer_composed=True,
                                    answer_source=fast_reason)
                    trace.emit("completion_review_skipped", run_id=run_id, reason=fast_reason)
                    return publish({**state, "metadata": metadata})
                if (resume_phase == "knowledge_semantics"
                        and state["metadata"].get("execution_ready")
                        and state["metadata"].get("final_answer_composed")):
                    # The same candidate already passed ordinary completion review.
                    # Deterministic checks above still run; publish performs the
                    # pending source audit, never an unconditional approval.
                    return publish(state)

                if combined:
                    review = assess("combined")
                    if review is None:
                        return finish_review(state)
                    metadata = dict(state["metadata"])
                    metadata["completion_reviews"] = metadata.get("completion_reviews", []) + [review]
                    state = {**state, "metadata": metadata}
                    if review["verdict"] in ("clarify", "cannot_complete"):
                        receipt_issue = knowledge_receipt_feedback(state, review["feedback"])
                        if receipt_issue:
                            return reject_final(state, [CompletionIssue(receipt_issue, False)])
                        if review["verdict"] == "clarify" and checkpoint_path is not None:
                            return ask_human(state, {"question": review["feedback"], "reason": review["feedback"], "missing": [], "options": []})
                        return publish({**state, "answer": review["feedback"]},
                                       "needs_input" if review["verdict"] == "clarify" else "incomplete", review["feedback"])
                    issues = review_evidence_issues(review, state, execution)
                    if review["verdict"] != "complete":
                        issues.append(CompletionIssue(review["feedback"] or "The candidate does not cover the task",
                                                      review["verdict"] == "continue"))
                    if issues:
                        return reject_final(state, issues)
                    state = {**state, "metadata": {**metadata, "execution_ready": True, "final_answer_composed": True,
                                                  "answer_source": "combined_reviewed_candidate"}}
                    return publish(state)
                if not state["metadata"].get("execution_ready"):
                    readiness = assess("execution")
                    if readiness is None:
                        return finish_review(state)
                    metadata = dict(state["metadata"])
                    metadata["execution_reviews"] = metadata.get("execution_reviews", []) + [readiness]
                    state = {**state, "metadata": metadata}
                    if readiness["verdict"] in ("clarify", "cannot_complete"):
                        receipt_issue = knowledge_receipt_feedback(state, readiness["feedback"])
                        if receipt_issue:
                            return reject_final(state, [CompletionIssue(receipt_issue, True)])
                        if readiness["verdict"] == "clarify" and checkpoint_path is not None:
                            return ask_human(state, {"question": readiness["feedback"], "reason": readiness["feedback"], "missing": [], "options": []})
                        return publish(state, "needs_input" if readiness["verdict"] == "clarify" else "incomplete", readiness["feedback"])
                    issues = review_evidence_issues(readiness, {**state, "answer": ""}, execution)
                    if readiness["verdict"] == "continue":
                        issues.append(CompletionIssue(readiness["feedback"] or "Requested operations remain unfinished", True))
                    if issues:
                        # Readiness cannot be repaired by rewriting the answer.
                        return reject_final(state, [CompletionIssue(issue.message, True) for issue in issues])
                    state = {**state, "metadata": {**metadata, "execution_ready": True,
                                                  "reuse_candidate_answer": readiness["verdict"] == "complete"}}
                    if cancel.is_set():
                        return record({"status": "stopped", "answer": "", "last_error": "Stopped by user",
                                       "model_turns": state["model_turns"], "metadata": state["metadata"]}, state)
                if (state["metadata"].get("optimize_round_trips") and state["metadata"].get("reuse_candidate_answer")
                        and not state["metadata"].get("final_answer_composed") and state["answer"].strip()):
                    # Reuse only the text, never its claims as evidence. The same
                    # deterministic checks and independent answer audit still run.
                    state = {**state, "metadata": {**state["metadata"], "final_answer_composed": True,
                                                  "answer_source": "execution_candidate"}}
                    issues = artifact_issues(state, execution)
                    for check in self.completion_checks:
                        issues.extend(check(state))
                    if issues:
                        return reject_final(state, issues)
                    trace.emit("final_answer_reused", run_id=run_id, answer=state["answer"])
                    activity("final_answer_reused")
                if not state["metadata"].get("final_answer_composed"):
                    if self.settings.max_model_turns is not None and state["model_turns"] >= self.settings.max_model_turns:
                        return finish_review({**state, "status": "budget_exhausted", "answer": "",
                                              "last_error": "Model-turn budget exhausted before final-answer composition; the draft was not published"})
                    request = final_answer_request(state, self.context, self.settings, defer_compaction=True)
                    request = constrain_answer_request(request, state)
                    request = prepare_request(request, state, "final_answer")
                    turn = state["model_turns"] + 1
                    state = {**state, "model_turns": turn}
                    trace.emit("model_requested", run_id=run_id, turn=turn, messages=request.messages,
                               tools=[t.name for t in request.tools], tool_definitions=request.tools,
                               tool_choice=request.tool_choice, phase="final_answer")
                    activity("model_requested", turn=turn, tool_choice=request.tool_choice, phase="final_answer")
                    try:
                        response = self.model.invoke(request)
                        trace.emit("model_responded", run_id=run_id, turn=turn, response=response, phase="final_answer")
                        metadata = {**state["metadata"], "usage": state["metadata"]["usage"] + [response.usage]}
                        state = {**state, "metadata": metadata}
                        response = resolve_final_answer(response, request)
                        if response.finish_reason != "stop" or response.tool_calls or not response.content.strip():
                            raise ModelProtocolError("Final-answer composition requires complete nonempty text and authorizes no tool calls")
                    except ModelProtocolError as exc:
                        trace.emit("model_protocol_error", run_id=run_id, error=str(exc), phase="final_answer")
                        return reject_final(state, [CompletionIssue(str(exc) + "; no tool from that response was executed")])
                    state = {**state, "answer": response.content,
                             "metadata": {**metadata, "final_answer_composed": True}}
                    if cancel.is_set():
                        return record({"status": "stopped", "answer": "", "last_error": "Stopped by user",
                                       "model_turns": state["model_turns"], "metadata": state["metadata"]}, state)
                    issues = artifact_issues(state, execution)
                    for check in self.completion_checks:
                        issues.extend(check(state))
                    if issues:
                        return reject_final(state, issues)
                length_issues = answer_length_issues(state)
                if length_issues:
                    return reject_final(state, length_issues)
                review = assess("answer")
                if review is None:
                    return finish_review(state)
                metadata = state["metadata"]
                state["metadata"] = {**metadata, "completion_reviews": metadata.get("completion_reviews", []) + [review]}
                if review["verdict"] in ("clarify", "cannot_complete"):
                    receipt_issue = knowledge_receipt_feedback(state, review["feedback"])
                    if receipt_issue:
                        return reject_final(state, [CompletionIssue(receipt_issue, False)])
                    if review["verdict"] == "clarify" and checkpoint_path is not None:
                        return ask_human(state, {"question": review["feedback"], "reason": review["feedback"], "missing": [], "options": []})
                    return publish(state, "needs_input" if review["verdict"] == "clarify" else "incomplete", review["feedback"])
                issues = review_evidence_issues(review, state, execution)
                if review["verdict"] != "complete":
                    issues.append(CompletionIssue(review["feedback"] or "The candidate does not cover the task", review["verdict"] == "continue"))
                if issues:
                    return reject_final(state, issues)
                return publish(state)
            except Exception as exc:
                reason = f"Completion check failed: {type(exc).__name__}: {exc}"
                trace.emit("completion_check_error", run_id=run_id, error=reason)
                return record({"status": "failed", "answer": "", "last_error": reason,
                               "model_turns": state["model_turns"], "metadata": state["metadata"]}, state)

        try:
            maximum = self.settings.max_model_turns
            from .human_input import durable_checkpoint
            if self.context_store is not None:
                self.context_store.begin_run(run_id, query, workspace)
                if resume is None:
                    self.context_store.sync_state(initial)
            checkpoint = (self.context_store.checkpoint() if self.context_store is not None else
                          durable_checkpoint(checkpoint_path) if checkpoint_path is not None else nullcontext(None))
            with checkpoint as saver:
                graph = build_graph(model_turn, execute_tools, finalize,
                                    human_input=wait_for_human if saver is not None else None, checkpointer=saver,
                                    retrieve_knowledge=retrieve_knowledge if self.settings.knowledge_enabled else None)
                config = {"recursion_limit": maximum * 3 + 10 if maximum is not None else 1_000_000_000,
                          "configurable": {"thread_id": self.context_store.thread_id(run_id) if self.context_store is not None else run_id}}
                graph_input = initial
                if resume is not None:
                    from langgraph.types import Command
                    saved = graph.get_state(config)
                    if "human" not in saved.next or not saved.values or saved.values["metadata"].get("workspace") != str(workspace):
                        raise ValueError("No resumable input request exists for this workspace")
                    if resume.get("request_id") != saved.values["metadata"].get("pending_input", {}).get("id"):
                        raise ValueError("Stale human response")
                    latest = saved.values
                    from ..research_plan import restore_research_plan
                    restore_research_plan(latest["metadata"].get("research_plan"), execution)
                    graph_input = Command(resume={k: v for k, v in resume.items() if k != "run_id"})
                with getattr(trace, "execution_context", nullcontext)():
                    result = graph.invoke(graph_input, config)
                if saver is not None and result.get("__interrupt__"):
                    result = dict(graph.get_state(config).values)
                    trace.emit("human_input_requested", run_id=run_id, request=result["metadata"]["pending_input"])
                    activity("human_input_requested", request=result["metadata"]["pending_input"])
        except KeyboardInterrupt:
            cancel.set()
            result = {**latest, "status": "stopped", "last_error": "Interrupted by user; files retained"}
        except Exception as exc:
            result = {**latest, "status": "failed", "last_error": f"Runtime error: {type(exc).__name__}: {exc}"}
        if result["status"] in ("failed", "budget_exhausted") or (
                result["status"] == "incomplete" and not result["answer"].strip()):
            result = source_partial(result)
            result["messages"].append(Message("assistant", result["answer"]))
            pending_delivery = (result["status"], result["answer"])
        result["metadata"] = {**result["metadata"], "elapsed_seconds": time.monotonic() - started}
        if self.context_store is not None:
            try:
                self.context_store.sync_state(result)
            except Exception:
                result = {**result, "status": "failed", "answer": "",
                          "last_error": "Context archive commit failed; completion was not published as successful"}
        if pending_delivery == (result["status"], result["answer"]) and result["answer"]:
            try:
                if on_text is not None:
                    on_text(result["answer"])
                activity("answer_published", status=result["status"])
            except Exception as exc:
                trace.emit("answer_delivery_callback_failed", run_id=run_id, error_type=type(exc).__name__)
        trace.emit("run_finished", run_id=run_id, status=result["status"], error=result["last_error"],
                   answer=result["answer"], artifacts=result["artifacts"], metadata=result["metadata"], model_turns=result["model_turns"])
        return RunResult(run_id, result["status"], result["answer"], tuple(result["artifacts"]),
                         result["last_error"], result["model_turns"], result)


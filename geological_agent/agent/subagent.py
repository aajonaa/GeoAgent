"""Isolated-context subagent orchestration for parallel research and analysis.

Subagents execute inside their own ephemeral context window (preventing context
rot in the lead agent), share cancellation and turn budgets with the parent run,
enforce hard depth=1 (no recursive subagents, no direct human prompts), and return
structured provenance-bound summaries + verified workspace artifacts.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import json
from threading import Lock
import time
import uuid

from ..contracts import ArtifactRef, Message
from ..knowledge import NullKnowledgeRetriever
from ..memory import NullMemoryStore
from ..settings import Settings
from ..skills import SkillLoader, SkillRegistry
from ..tools import Tool, ToolDefinition, ToolFailure, ToolOutput, ToolRegistry, artifact, object_schema

MAX_SUBAGENT_TURNS = 16
DEFAULT_SUBAGENT_TURNS = 8
MAX_PARALLEL_SUBAGENTS = 4
MAX_SUMMARY_CHARS = 6000

FORBIDDEN_IN_SUBAGENT = frozenset({
    "delegate_subagent",
    "run_subagents_parallel",
    "request_user_input",
    "update_todo",
})

SUBAGENT_ROLES = {
    "literature_researcher": {
        "title": "文献深研子智能体 (Literature Researcher)",
        "read_only": True,
        "preferred_tools": (
            "read_file", "web_search", "web_fetch",
            "context_search", "context_read", "GeoOpenAlexSearch", "skill_find",
        ),
        "instructions": (
            "You are a focused Literature Research Subagent operating in an isolated context window. "
            "Read and search only available literature, workspace documents, and authorized sources. "
            "Do NOT fabricate citations, measurements, or URLs. "
            "Distill raw passages into a compact, high-density structured brief for the lead agent: "
            "preserve exact [K...] citation IDs, paper titles, page numbers, URLs actually read, "
            "numerical ranges with units, and explicit gaps or contradictions."
        ),
    },
    "data_analyst": {
        "title": "数据处理与绘图子智能体 (Data Analyst & Plotter)",
        "read_only": False,
        "preferred_tools": (
            "read_file", "write_file", "execute_python", "skill_find", "skill_load",
        ),
        "instructions": (
            "You are a focused Data Analysis & Plotting Subagent operating in an isolated context window. "
            "Use available scientific tools and Python in the shared workspace to process data, compute results, "
            "and generate requested figures or tables. Verify every saved file and numerical value by reading "
            "or asserting outputs during execution. Never fabricate input data or claim unverified outputs. "
            "Return a concise structured summary listing exact created file paths, key observed metrics with units, "
            "verification checks performed, and any limitations."
        ),
    },
    "general": {
        "title": "通用子任务智能体 (General Subagent)",
        "read_only": False,
        "preferred_tools": None,
        "instructions": (
            "You are a focused Subagent executing one bounded sub-task in an isolated context window "
            "for the lead orchestrator. Use only exposed tools, verify observed results, never fabricate "
            "files or measurements, and return a concise structured report of findings, created files, and gaps."
        ),
    },
}

def _extract_subagent_evidence(result_state, workspace):
    """Extract verified tool usage, citations, URLs, and disk-verified artifacts."""
    tools_used = []
    urls_read = []
    for msg in result_state.get("messages", ()):
        if msg.role != "tool":
            continue
        try:
            receipt = json.loads(msg.content)
        except (ValueError, TypeError):
            continue
        if not isinstance(receipt, dict):
            continue
        name = receipt.get("name")
        if name and receipt.get("status") == "ok":
            tools_used.append(name)
            data = receipt.get("data") or {}
            if name == "web_fetch" and isinstance(data.get("url"), str):
                urls_read.append(data["url"])
    verified_files = []
    seen_paths = set()
    for art in result_state.get("artifacts", ()):
        rel = art.path
        if rel in seen_paths or rel.startswith(".agent/"):
            continue
        path = (workspace / rel).resolve()
        if path.is_file() and path.is_relative_to(workspace.resolve()):
            raw = path.read_bytes()
            verified_files.append({
                "path": rel,
                "media_type": art.media_type,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            })
            seen_paths.add(rel)
    return {
        "successful_tools": list(dict.fromkeys(tools_used)),
        "urls_read": list(dict.fromkeys(urls_read))[:20],
        "artifacts": verified_files,
    }


class SubagentCoordinator:
    """Runs bounded, depth-1 isolated subagents on behalf of a parent AgentRuntime."""

    def __init__(self, *, parent_runtime, parent_run_id, workspace, cancel,
                 parent_metadata, metadata_lock, trace, activity, remaining_budget_fn):
        self.parent = parent_runtime
        self.parent_run_id = parent_run_id
        self.workspace = workspace
        self.cancel = cancel
        self.parent_metadata = parent_metadata
        self.metadata_lock = metadata_lock
        self.trace = trace
        self.activity = activity
        self.remaining_budget_fn = remaining_budget_fn

    def _build_sub_registry(self, role_cfg, skill_ids, parent_exposed):
        sub_reg = ToolRegistry()
        sub_skills_reg = SkillRegistry()
        read_only = role_cfg["read_only"]
        preferred = role_cfg["preferred_tools"]
        if preferred is not None:
            candidate_names = [n for n in preferred if n not in FORBIDDEN_IN_SUBAGENT]
        else:
            candidate_names = [n for n in parent_exposed if n not in FORBIDDEN_IN_SUBAGENT]

        base_tools = []
        for name in candidate_names:
            try:
                tool = self.parent.tools.get(name)
            except ToolFailure:
                continue
            # Tool is already validated in parent registry; avoid re-running meta-schema checks.
            sub_reg._tools[tool.definition.name] = tool
            base_tools.append(name)

        selected_skill_ids = []
        if not read_only:
            for summary in self.parent.skills.registry.list():
                skill = self.parent.skills.load(summary.id)
                sub_skills_reg.register(skill)
                for tname in skill.tool_names:
                    if tname in FORBIDDEN_IN_SUBAGENT:
                        continue
                    if tname not in sub_reg._tools:
                        try:
                            tool = self.parent.tools.get(tname)
                            sub_reg._tools[tool.definition.name] = tool
                        except ToolFailure:
                            continue
            for sid in skill_ids or ():
                skill = self.parent.skills.load(sid)
                selected_skill_ids.append(sid)
                for tname in skill.tool_names:
                    if tname not in FORBIDDEN_IN_SUBAGENT and tname in sub_reg._tools and tname not in base_tools:
                        base_tools.append(tname)

        sub_loader = SkillLoader(sub_skills_reg)
        sub_loader.source_statuses = getattr(self.parent.skills, "source_statuses", {})
        sub_loader.unavailable_skills = getattr(self.parent.skills, "unavailable_skills", [])
        return sub_reg, sub_loader, tuple(base_tools), selected_skill_ids

    def run_one(self, *, role: str, task: str, skill_ids=(), max_turns=None, parent_exposed=()):
        from .runtime import AgentRuntime

        if role not in SUBAGENT_ROLES:
            raise ToolFailure("invalid_subagent_role", f"Unsupported subagent role: {role}", retryable=True)
        if not isinstance(task, str) or not task.strip():
            raise ToolFailure("empty_subagent_task", "Subagent task must be nonempty.", retryable=True)
        if self.cancel.is_set():
            raise ToolFailure("cancelled", "Parent execution was stopped.")

        role_cfg = SUBAGENT_ROLES[role]
        requested = int(max_turns) if max_turns is not None else DEFAULT_SUBAGENT_TURNS
        budget = max(1, min(requested, MAX_SUBAGENT_TURNS))
        remaining = self.remaining_budget_fn()
        if remaining is not None:
            # Reserve at least 1 turn for the lead orchestrator to synthesize results.
            available = remaining - 1
            if available < 1:
                raise ToolFailure("subagent_budget_exhausted",
                                  "Insufficient remaining parent model-turn budget to launch a subagent.",
                                  retryable=False)
            budget = min(budget, available)

        sub_id = "sub_" + uuid.uuid4().hex[:12]
        sub_reg, sub_skills, sub_base, validated_skills = self._build_sub_registry(
            role_cfg, skill_ids, parent_exposed
        )
        # Keep subagent lean: disable redundant outer completion review; lead agent audits final output.
        parent_s = self.parent.settings
        sub_settings = Settings(
            max_model_turns=budget,
            tool_timeout_seconds=parent_s.tool_timeout_seconds,
            max_context_chars=parent_s.max_context_chars,
            max_tool_output_chars=parent_s.max_tool_output_chars,
            max_file_bytes=parent_s.max_file_bytes,
            memory_enabled=False,
            knowledge_enabled=parent_s.knowledge_enabled if role == "literature_researcher" else False,
            verify_completion=False,
            context_window_tokens=parent_s.context_window_tokens,
            context_model=parent_s.context_model,
            max_output_tokens=parent_s.max_output_tokens,
        )
        sub_knowledge = self.parent.context.knowledge if sub_settings.knowledge_enabled else NullKnowledgeRetriever()
        sub_runtime = AgentRuntime(
            self.parent.model,
            sub_settings,
            sub_reg,
            sub_skills,
            NullMemoryStore(),
            sub_knowledge,
            sub_base,
            read_only=role_cfg["read_only"],
            is_subagent=True,
        )
        framed_task = (
            f"[Subagent Role: {role_cfg['title']}]\n"
            f"{role_cfg['instructions']}\n\n"
            f"Assigned sub-task:\n{task.strip()}"
        )

        self.trace.emit("subagent_started", run_id=self.parent_run_id, subagent_id=sub_id,
                        role=role, max_turns=budget, skill_ids=validated_skills)
        self.activity("subagent_started", subagent_id=sub_id, role=role, title=role_cfg["title"])
        t0 = time.monotonic()
        outcome = sub_runtime.run(
            framed_task,
            workspace=self.workspace,
            skill_id=validated_skills[0] if len(validated_skills) == 1 else None,
            cancel_event=self.cancel,
        )
        elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
        evidence = _extract_subagent_evidence(outcome.state, self.workspace)
        sub_metadata = outcome.state["metadata"]
        receipt = sub_metadata.get("knowledge_retrieval_receipt")
        sub_refs = []
        if receipt and receipt.get("run_id") == outcome.state["run_id"]:
            if receipt["status"] == "matched":
                selected = set(receipt["reference_ids"])
                sub_refs = [row for row in sub_metadata["knowledge"]["references"]
                            if row.get("citation_id") in selected]
            receipt = {**receipt, "parent_run_id": self.parent_run_id, "subagent_id": sub_id}
        else:
            receipt = None
        summary = (outcome.answer or "").strip()
        if len(summary) > MAX_SUMMARY_CHARS:
            summary = summary[:MAX_SUMMARY_CHARS] + "\n...[truncated; see subagent audit file for full text]"
        record = {
            "subagent_id": sub_id,
            "role": role,
            "status": outcome.status,
            "turns_used": outcome.model_turns,
            "elapsed_ms": elapsed_ms,
            "summary": summary,
            "limitations": outcome.reason or "",
            "citation_ids": [row["citation_id"] for row in sub_refs],
            **evidence,
        }
        if receipt:
            record["knowledge_retrieval_receipt"] = receipt

        # Persist immutable subagent audit trail under .agent/subagents/
        audit_rel = f".agent/subagents/{sub_id}.json"
        audit_path = (self.workspace / audit_rel).resolve()
        if audit_path.is_relative_to(self.workspace.resolve()):
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit_path.write_text(json.dumps({
                **record,
                "task": task.strip(),
                "full_answer": outcome.answer or "",
                "knowledge_references": sub_refs,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            record["audit_path"] = audit_rel

        sub_usage = sub_metadata.get("usage", [])
        with self.metadata_lock:
            self.parent_metadata["usage"] = self.parent_metadata.get("usage", []) + list(sub_usage)
            if receipt:
                self.parent_metadata["delegated_knowledge_retrieval_receipts"] = [
                    *self.parent_metadata.get("delegated_knowledge_retrieval_receipts", ()), receipt]
            if sub_refs:
                # Propagate real retriever-sourced references discovered by a subagent
                # into the parent's knowledge ledger so parent citation_issues & UI
                # citation panels recognize and bind them accurately.
                parent_k = dict(self.parent_metadata.get("knowledge") or {"status": "matched", "references": []})
                existing = list(parent_k.get("references") or [])
                known_cids = {row.get("citation_id") for row in existing if isinstance(row, dict)}
                for row in sub_refs:
                    if isinstance(row, dict) and row.get("citation_id") and row["citation_id"] not in known_cids:
                        existing.append(row)
                        known_cids.add(row["citation_id"])
                parent_k["references"] = existing
                parent_k["status"] = "matched"
                self.parent_metadata["knowledge"] = parent_k
            self.parent_metadata["subagent_runs"] = self.parent_metadata.get("subagent_runs", []) + [{
                "subagent_id": sub_id,
                "role": role,
                "status": outcome.status,
                "turns_used": outcome.model_turns,
                "elapsed_ms": elapsed_ms,
                "artifacts": [a["path"] for a in evidence["artifacts"]],
            }]
        if receipt:
            self.trace.emit("delegated_knowledge_completed", run_id=self.parent_run_id, subagent_id=sub_id,
                            source_run_id=receipt["run_id"], returned_count=receipt["returned_count"],
                            result={"status": receipt["status"], "duration_ms": receipt["duration_ms"],
                                    "references": sub_refs})
        self.trace.emit("subagent_completed", run_id=self.parent_run_id, subagent_id=sub_id,
                        role=role, status=outcome.status, turns_used=outcome.model_turns,
                        elapsed_ms=elapsed_ms, artifacts=[a["path"] for a in evidence["artifacts"]])
        self.activity("subagent_completed", subagent_id=sub_id, role=role,
                      status=outcome.status, turns_used=outcome.model_turns, elapsed_ms=elapsed_ms)
        return record, evidence["artifacts"]

    def run_parallel(self, specs, *, parent_exposed=()):
        if not specs:
            raise ToolFailure("empty_subagent_batch", "Provide at least one subagent task.", retryable=True)
        if len(specs) > MAX_PARALLEL_SUBAGENTS:
            raise ToolFailure("too_many_subagents",
                              f"At most {MAX_PARALLEL_SUBAGENTS} parallel subagents are allowed per call.",
                              retryable=True)
        if len(specs) == 1:
            rec, arts = self.run_one(
                role=specs[0]["role"],
                task=specs[0]["task"],
                skill_ids=specs[0].get("skill_ids", ()),
                max_turns=specs[0].get("max_turns"),
                parent_exposed=parent_exposed,
            )
            return [rec], arts

        t0 = time.monotonic()

        def _exec(spec):
            try:
                return self.run_one(
                    role=spec["role"],
                    task=spec["task"],
                    skill_ids=spec.get("skill_ids", ()),
                    max_turns=spec.get("max_turns"),
                    parent_exposed=parent_exposed,
                ), None
            except ToolFailure as exc:
                return None, exc

        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_SUBAGENTS, len(specs))) as pool:
            futures = [pool.submit(_exec, spec) for spec in specs]
            outcomes = [f.result() for f in futures]

        records = []
        all_artifacts = []
        for spec, (pair, err) in zip(specs, outcomes):
            if err is not None:
                records.append({
                    "subagent_id": "",
                    "role": spec["role"],
                    "status": "failed",
                    "turns_used": 0,
                    "elapsed_ms": 0.0,
                    "summary": "",
                    "limitations": err.error.message,
                    "successful_tools": [],
                    "urls_read": [],
                    "citation_ids": [],
                    "artifacts": [],
                })
            else:
                rec, arts = pair
                records.append(rec)
                all_artifacts.extend(arts)
        elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
        self.trace.emit("subagent_parallel_batch", run_id=self.parent_run_id,
                        count=len(specs), roles=[s["role"] for s in specs], elapsed_ms=elapsed_ms)
        return records, all_artifacts


def _delegate_handler(args, ctx):
    if ctx.subagent_runner is None:
        raise ToolFailure("subagents_unavailable", "Subagent delegation is not enabled in this execution context.")
    record, file_rows = ctx.subagent_runner.run_one(
        role=args["role"],
        task=args["task"],
        skill_ids=args.get("skill_ids", ()),
        max_turns=args.get("max_turns"),
        parent_exposed=ctx.allowed_tool_names,
    )
    refs = tuple(artifact(ctx.path(row["path"]), ctx) for row in file_rows)
    return ToolOutput(record, refs)


def _parallel_handler(args, ctx):
    if ctx.subagent_runner is None:
        raise ToolFailure("subagents_unavailable", "Subagent delegation is not enabled in this execution context.")
    records, file_rows = ctx.subagent_runner.run_parallel(
        args["tasks"],
        parent_exposed=ctx.allowed_tool_names,
    )
    seen = set()
    refs = []
    for row in file_rows:
        if row["path"] not in seen:
            seen.add(row["path"])
            refs.append(artifact(ctx.path(row["path"]), ctx))
    return ToolOutput({"results": records, "count": len(records)}, tuple(refs))


def register_subagent_tools(registry):
    text = {"type": "string"}
    role_enum = list(SUBAGENT_ROLES)
    task_spec = object_schema({
        "role": {**text, "enum": role_enum,
                 "description": "Subagent specialization: literature_researcher (read-only literature/evidence synthesis), data_analyst (Python/scientific tools/plotting), or general."},
        "task": {**text, "minLength": 1, "maxLength": 4000,
                 "description": "Self-contained sub-task brief including exact inputs, target files, and expected output format."},
        "skill_ids": {"type": "array", "items": text, "maxItems": 6,
                      "description": "Optional skill IDs to pre-load for data_analyst/general subagents."},
        "max_turns": {"type": "integer", "minimum": 1, "maximum": MAX_SUBAGENT_TURNS,
                      "description": f"Optional max model turns for this subagent (default {DEFAULT_SUBAGENT_TURNS}, max {MAX_SUBAGENT_TURNS})."},
    }, ["role", "task"])
    single_out = {"type": "object", "required": ["subagent_id", "role", "status", "summary", "artifacts"]}
    parallel_in = object_schema({
        "tasks": {"type": "array", "items": task_spec, "minItems": 1, "maxItems": MAX_PARALLEL_SUBAGENTS,
                  "description": f"Up to {MAX_PARALLEL_SUBAGENTS} independent sub-tasks to run concurrently in isolated contexts."},
    }, ["tasks"])
    parallel_out = object_schema({
        "results": {"type": "array", "items": {"type": "object"}},
        "count": {"type": "integer"},
    }, ["results", "count"])

    registry.register(Tool(
        ToolDefinition(
            "delegate_subagent",
            "Run one focused sub-task in an isolated context window (literature_researcher, data_analyst, or general) and return a distilled provenance-bound summary plus created files.",
            "Offload heavy literature searches, multi-file reading, or iterative Python coding/plotting to prevent polluting the main context window.",
            task_spec,
            single_out,
        ),
        _delegate_handler,
    ))
    registry.register(Tool(
        ToolDefinition(
            "run_subagents_parallel",
            f"Run up to {MAX_PARALLEL_SUBAGENTS} independent subagents concurrently in isolated contexts and collect all structured reports and artifacts.",
            "Parallelize independent research branches (e.g. compare multiple ore belts, or combine literature_researcher with data_analyst simultaneously).",
            parallel_in,
            parallel_out,
        ),
        _parallel_handler,
    ))
    return ("delegate_subagent", "run_subagents_parallel")

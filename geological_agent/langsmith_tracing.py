"""Optional event-based LangSmith instrumentation, not a tool-call adapter."""
from datetime import datetime, timezone


class LangSmithTrace:
    def __init__(self, local, client, *, project, capture_content=False, model="", release="local-cli", run_factory=None):
        if run_factory is None:
            from langsmith.run_trees import RunTree
            run_factory = RunTree
        self.local, self.client, self.project = local, client, project
        self.capture_content, self.model = capture_content, model
        self.release = release
        self.provider = 'vllm'
        self.run_factory, self.root = run_factory, None
        self.active, self.latest_model = {}, None
        self.failed = False

    def set_model(self, model, provider):
        self.model, self.provider = model, provider

    def execution_context(self):
        return self.local.execution_context()

    def _inputs(self, fields):
        return fields if self.capture_content else {}

    def _begin(self, key, name, kind, inputs, metadata):
        run = self.root.create_child(name=name, run_type=kind,
            inputs=self._inputs(inputs), extra={"metadata": metadata})
        self.active[key] = run
        run.post()
        return run

    def _end(self, key, outputs, error=None):
        run = self.active.pop(key, None)
        if run is None:
            self.local.emit("langsmith_unmatched_completion", key=str(key))
            return
        run.end(outputs=outputs, error=error)
        run.patch()

    @staticmethod
    def _usage(response):
        usage = response.get("usage") or {}
        return {target: usage[source] for source, target in (
            ("prompt_tokens", "input_tokens"), ("completion_tokens", "output_tokens"),
            ("total_tokens", "total_tokens")) if source in usage and usage[source] is not None}

    def emit(self, event, **fields):
        self.local.emit(event, **fields)
        if self.failed:
            return
        safe = self.local._safe(fields)
        try:
            self._export(event, safe)
        except Exception as exc:
            self.failed = True
            self.local.emit("langsmith_export_failed", event_name=event, error_type=type(exc).__name__)

    def _export(self, event, fields):
        if event == "run_started":
            self.root = self.run_factory(name="GeoToolAgent task", run_type="chain", project_name=self.project,
                ls_client=self.client, inputs=self._inputs({"task": fields.get("task", "")}),
                extra={"metadata": {"geotool_run_id": fields.get("run_id"), "capture_content": self.capture_content,
                                    "model": self.model, "release": self.release}},
                tags=["geotoolagent", "local-cli"], dangerously_allow_filesystem=False)
            self.root.post()
            self.local.emit("langsmith_trace_queued", trace_id=str(self.root.id), project=self.project)
            return
        if self.root is None:
            return
        if event == "knowledge_requested":
            self._begin(("knowledge", fields["run_id"]), "Knowledge retrieval + cross-encoder", "retriever",
                        {"query": fields.get("query", "")}, {"scope": "authenticated-owner", "automatic": True})
        elif event in ("knowledge_completed", "knowledge_failed"):
            self._end(("knowledge", fields["run_id"]), fields.get("result", {}) if self.capture_content else
                      {"status": fields.get("result", {}).get("status")},
                      "knowledge_unavailable" if event == "knowledge_failed" else None)
        elif event in ("model_requested", "completion_review_requested"):
            review = event == "completion_review_requested"
            key = ("review" if review else "model", fields["turn"])
            request = fields.get("request", fields)
            name = ("Knowledge semantic review" if review and fields.get("phase") == "knowledge_semantics" else
                    "Completion review" if review else "Model decision")
            self._begin(key, name, "llm",
                {"messages": request.get("messages", []), "tools": request.get("tool_definitions", request.get("tools", []))},
                {"turn": fields["turn"], "tool_choice": request.get("tool_choice", "required" if review else "auto"),
                 "phase": fields.get("phase"), "attempt": fields.get("attempt"),
                 "ls_provider": self.provider, "ls_model_name": self.model, "ls_model_type": "chat"})
            self.latest_model = key
        elif event in ("model_responded", "completion_review_responded"):
            response = fields["response"]
            key = ("review" if event == "completion_review_responded" else "model", fields["turn"])
            outputs = {"finish_reason": response.get("finish_reason"), "usage_metadata": self._usage(response)}
            if self.capture_content:
                outputs["message"] = {"role": "assistant", "content": response.get("content", ""),
                                      "tool_calls": response.get("tool_calls", [])}
                outputs["provider_metadata"] = response.get("provider_metadata", {})
                outputs["provider_metadata_scope"] = (
                    "Provider-reported diagnostics; not caller-owned tool execution evidence.")
            self._end(key, outputs)
        elif event == "model_failed":
            self._end(self.latest_model, {}, fields.get("error") if self.capture_content else "model_failed")
        elif event == "tool_requested":
            call = fields["call"]
            self._begin(("tool", call["id"]), call["name"], "tool", {"arguments": call["arguments"]},
                        {"tool_call_id": call["id"]})
        elif event in ("tool_completed", "tool_failed"):
            result = fields["result"]
            error = result.get("error") or {}
            outputs = result if self.capture_content else {"status": result["status"], "cached": result.get("cached", False),
                        "artifact_count": len(result.get("artifacts", [])), "error_code": error.get("code")}
            self._end(("tool", result["call_id"]), outputs,
                (error.get("message") if self.capture_content else error.get("code", "tool_failed")) if result["status"] != "ok" else None)
        elif event == "run_finished":
            for key in list(self.active):
                self._end(key, {}, "Run ended without a corresponding completion event")
            outputs = {"status": fields["status"], "model_turns": fields.get("model_turns"),
                       "artifact_count": len(fields.get("artifacts", []))}
            if self.capture_content:
                outputs.update(answer=fields.get("answer", ""), artifacts=fields.get("artifacts", []))
            unsuccessful = fields["status"] not in ("completed", "needs_input")
            self.root.end(outputs=outputs, error=(fields.get("error") if self.capture_content else fields["status"]) if unsuccessful else None)
            self.root.patch()
            self.client.flush(timeout=5)
        else:
            # Keep rejections and protocol failures searchable, including cases
            # where the model call succeeded but its answer did not pass checks.
            safe_metadata = {"event": event, "turn": fields.get("turn"),
                             "phase": fields.get("phase"), "attempt": fields.get("attempt")}
            key = ("event", event, datetime.now(timezone.utc).isoformat())
            self._begin(key, event, "chain", fields, safe_metadata)
            self._end(key, fields if self.capture_content else {"event": event},
                      event if event in ("completion_rejected", "model_protocol_error", "completion_review_protocol_error", "completion_check_error") else None)

    def acceptance(self, passed, *, task, errors=()):
        """External acceptance is separate from the agent's self-reported status."""
        self.local.emit("independent_acceptance", passed=passed, task=task, errors=list(errors))
        if self.failed or self.root is None:
            return
        try:
            comment = "Independent acceptance: " + task
            if self.capture_content and errors:
                comment += "; " + "; ".join(self.local._safe(list(errors)))
            self.client.create_feedback(self.root.id, key="independent_acceptance", score=int(passed), comment=comment)
            self.client.flush(timeout=5)
        except Exception as exc:
            self.local.emit("langsmith_feedback_failed", error_type=type(exc).__name__)

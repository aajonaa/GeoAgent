"""Reuse the service account's existing Python environment. NOT a sandbox."""
from contextlib import nullcontext
from pathlib import Path
import os
import re
from ..bootstrap import create_agent
from ..settings import Settings
from .isolation import Cancelled
from .protocol import unpack_files
from .worker import snapshot


class TrustedLocalRunner:
    isolated = False
    memory_snapshot_enabled = True
    provenance_enabled = True
    description = 'service Python environment; OS sandbox disabled'

    def __init__(self, jobs_root, *, process_worker=None, process_scope_certified=False):
        self.jobs_root = Path(jobs_root).resolve()
        self.jobs_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.hitl_enabled = os.environ.get("GEOTOOL_HITL", "0") == "1"
        self.context_dsn_file = os.environ.get("GEOTOOL_CONTEXT_DSN_FILE")
        self.context_archive_enabled = bool(self.context_dsn_file)
        self.process_worker = process_worker  # Trusted construction only; never an HTTP option.
        self.process_scope_certified = process_scope_certified is True
        self.process_ownership = None
        if self.hitl_enabled:
            from .store import Store
            self.store = Store(self.jobs_root.parent)

    def stop(self, rid):
        if self.process_ownership is not None:
            run = self.process_ownership.recovery._load(rid)
            return self.process_ownership.stop_run(run['uid'], rid)
        # Legacy deployments are unchanged and do not acquire a cleanup proof.
        return None

    def run(self, rid, query, files, cancel, model_call, on_trace, *, settings=None, **kwargs):
        if self.process_ownership is not None:
            from .trusted_process import run_managed
            return run_managed(self, rid, query, files, cancel, model_call, on_trace, settings=settings, **kwargs)
        return self._run_local(rid, query, files, cancel, model_call, on_trace, settings=settings, **kwargs)

    def _run_local(self, rid, query, files, cancel, model_call, on_trace, *, settings=None, **kwargs):
        if not re.fullmatch(r'[a-f0-9]{32}', rid):
            raise ValueError('Invalid job ID')
        if cancel.is_set():
            raise Cancelled('Stopped before execution')
        reply = self.store.input_for_reply(rid) if self.hitl_enabled else None
        job_id = reply["job_id"] if reply else rid
        work = self.jobs_root / job_id
        if reply:
            if not work.is_dir():
                raise ValueError("The saved task directory is missing; refusing to restart it as a new task")
        else:
            work.mkdir(mode=0o700)
        from .protocol import relative_name
        for name, data in files.items():
            target = work / relative_name(name)
            if target.is_symlink() or not target.resolve().is_relative_to(work.resolve()):
                raise ValueError("A supplied file cannot overwrite a link or leave its task directory")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        class NativeModel:
            def invoke(self, request):
                return model_call(request, cancel)

        class NativeTrace:
            def emit(self, event, **fields):
                on_trace(event, fields)

            def execution_context(self):
                return nullcontext()

        agent_options = {"human_input": True} if self.hitl_enabled else {}
        if kwargs.get("read_only"):
            agent_options["read_only"] = True
        old_checkpoint = self.jobs_root.parent / "checkpoints" / (job_id + ".sqlite3")
        # Existing paused SQLite tasks keep their original graph. New tasks use
        # PostgreSQL without migrating accounts, credentials, or old checkpoints.
        if self.context_archive_enabled and not (reply and old_checkpoint.is_file()):
            from ..context_store import ContextScope, PostgresContextStore, private_dsn
            scope = kwargs.get("context_scope")
            if not isinstance(scope, dict) or set(scope) != {"owner_id", "conversation_id"}:
                raise ValueError("The authenticated broker must supply the context ownership scope")
            agent_options["context_store"] = PostgresContextStore(private_dsn(self.context_dsn_file), ContextScope(**scope))
        if "memory_records" in kwargs:
            from ..memory import SnapshotMemoryStore
            agent_options["memory"] = SnapshotMemoryStore.from_payload(kwargs["memory_records"])
        agent = create_agent(NativeModel(), settings=Settings(**(settings or {})),
                             trace_factory=lambda *args: NativeTrace(), **agent_options)
        run_options = {}
        if "skill_id" in kwargs:
            run_options["skill_id"] = kwargs["skill_id"]
        if "input_origins" in kwargs:
            run_options["input_origins"] = kwargs["input_origins"]
        if self.hitl_enabled:
            run_options["checkpoint_path"] = self.jobs_root.parent / "checkpoints" / (job_id + ".sqlite3")
        if reply:
            run_options["resume"] = {"run_id": reply["core_id"], "request_id": reply["id"],
                                     "text": reply["query"], "files": sorted(files)}
        outcome = agent.run(query, workspace=work, cancel_event=cancel, **run_options)
        if cancel.is_set():
            raise Cancelled('Stopped. The last committed files are retained.')
        if self.hitl_enabled and outcome.status == "needs_input":
            self.store.pause_input(rid, outcome.run_id, job_id, outcome.state["metadata"]["pending_input"])
        return {'status': outcome.status, 'answer': outcome.answer, 'reason': outcome.reason or '',
                'turns': outcome.model_turns, 'files': unpack_files(snapshot(work)),
                'file_origins': getattr(outcome, "state", {}).get("metadata", {}).get("tool_evidence", {}).get("files", {})}

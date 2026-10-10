"""Live presentation of native transport, never an alternative execution protocol."""
import re
from threading import RLock
import time
import uuid

from ..llm import ModelProtocolError
from ..run_status import issue_for_event, task_outcome
from .isolation import Cancelled
from .protocol import scrub


class StreamRedactor:
    """Delay incomplete credential prefixes so split SSE packets cannot leak them."""
    def __init__(self, secrets=()):
        self.secrets = tuple(sorted({s for s in secrets if isinstance(s, str) and s}, key=len, reverse=True))
        self.pending = ""

    def feed(self, text, *, final=False):
        self.pending += text
        cut = len(self.pending)
        if not final:
            for prefix in (*self.secrets, "Bearer ", "lsv2_"):
                source = self.pending.lower() if prefix == "Bearer " else self.pending
                target = prefix.lower() if prefix == "Bearer " else prefix
                for size in range(min(len(target), len(source)), 0, -1):
                    if source.endswith(target[:size]):
                        cut = min(cut, len(self.pending) - size)
                        break
            for pattern in (r"(?i)Bearer\s+[A-Za-z0-9_.~+/=-]*$", r"lsv2_[A-Za-z0-9_]*$"):
                match = re.search(pattern, self.pending)
                if match:
                    cut = min(cut, match.start())
        ready, self.pending = self.pending[:cut], self.pending[cut:]
        return scrub(ready, self.secrets)


class RunProgress:
    """Mutually exclusive stage accounting; wall time is only a display anchor."""
    def __init__(self, publish, secrets=(), *, clock=time.monotonic, wall=time.time):
        self.publish, self.secrets, self.clock, self.wall = publish, secrets, clock, wall
        self.lock = RLock()
        self.active, self.since, self.totals = "runtime", clock(), {}
        self.closed = False
        self.model_phase, self.turn, self.streamed_process = "execution", None, False
        self.tool_starts, self.tool_durations = {}, {}
        self.last_issue = None

    def emit(self, data):
        with self.lock:
            if not self.closed:
                self.publish(scrub(data, self.secrets))

    def switch(self, stage):
        with self.lock:
            if self.closed:
                return
            now = self.clock()
            if self.active:
                self.totals[self.active] = self.totals.get(self.active, 0.0) + max(0.0, now - self.since)
            self.active, self.since = stage, now
            self.emit({"kind": "stage_timing", "active": stage,
                       "totals_seconds": dict(self.totals), "recorded_at": self.wall()})

    def close(self):
        with self.lock:
            if not self.closed:
                self.switch(None)
                self.closed = True

    def observe(self, kind, fields):
        with self.lock:
            issue = issue_for_event(kind, fields)
            if issue is not None:
                self.last_issue = issue
                self.emit({"kind": "diagnostic", **issue})
            if kind == "knowledge_semantic_checked":
                self.emit({"kind": "review_result", "passed": fields.get("passed") is True,
                           "phase": "knowledge_semantics", "turn": fields.get("turn")})
            if kind == "run_finished":
                self.emit({"kind": "run_outcome", **task_outcome(fields, self.last_issue)})
            if kind in ("model_requested", "completion_review_requested"):
                self.model_phase = ("review" if kind == "completion_review_requested"
                                    else fields.get("phase") or "execution")
                self.turn = fields.get("turn")
                self.streamed_process = False
            elif kind == "knowledge_requested":
                self.switch("retrieval")
            elif kind == "knowledge_completed":
                self.switch("runtime")
            elif kind == "tool_requested":
                call = fields.get("call", {})
                self.tool_starts[call.get("id")] = self.clock()
                self.switch("tools")
            elif kind in ("tool_completed", "tool_failed"):
                call_id = fields.get("result", {}).get("call_id")
                start = self.tool_starts.pop(call_id, None)
                if start is not None:
                    self.tool_durations[call_id] = max(0.0, self.clock() - start)
                self.switch("tools" if self.tool_starts else "runtime")

    def begin_model(self):
        with self.lock:
            call = {"id": uuid.uuid4().hex, "phase": self.model_phase, "turn": self.turn,
                    "queued": self.clock(), "return_stage": self.active or "runtime"}
            self.switch("queue")
            return call


def consume_model_stream(client, request, progress, call, cancel):
    """Drain one request once; only its fully assembled response reaches runtime."""
    started = progress.clock()
    review = call["phase"] == "review"
    prefix = "review" if review else "model"
    progress.switch(prefix + "_wait")
    streaming = request.transport != "full_response" and callable(getattr(client, "stream", None))
    full_required = request.tool_choice == "required" and getattr(client, "required_streaming", True) is False
    transport = "native_stream" if streaming and not full_required else "full_response"
    common = {"request_id": call["id"], "phase": call["phase"], "turn": call["turn"]}
    progress.emit({"kind": "stream_open", **common, "transport": transport,
                   "queue_seconds": max(0.0, started - call["queued"])})
    masks = {key: StreamRedactor(progress.secrets) for key in ("text", "reasoning")}
    pending = {"text": "", "reasoning": ""}
    offsets = {"text": 0, "reasoning": 0}
    last_flush, first = started, None
    completed = None
    public = call["phase"] in ("execution", "intent", "final_answer")

    def flush(final=False):
        nonlocal last_flush
        for channel in pending:
            if final:
                pending[channel] += masks[channel].feed("", final=True)
            if not pending[channel]:
                continue
            text = pending[channel]
            pending[channel] = ""
            progress.emit({"kind": "stream_delta", **common, "channel": channel,
                           "text": text, "offset": offsets[channel], "verified": False})
            offsets[channel] += len(text)
            if channel == "reasoning":
                progress.streamed_process = True
        last_flush = progress.clock()

    try:
        if cancel.is_set():
            raise Cancelled("Stopped before the model request")
        if not streaming:
            completed = client.invoke(request)
        else:
            for event in client.stream(request):
                if cancel.is_set():
                    raise Cancelled("Stopped while receiving the model response")
                if completed is not None:
                    raise ModelProtocolError("Model stream continued after its completed response")
                if event.kind == "response":
                    completed = event.response
                elif event.kind in ("text_delta", "reasoning_delta"):
                    if not isinstance(event.text, str):
                        raise ModelProtocolError("Model stream fragments must be text")
                    if first is None and event.text:
                        first = progress.clock()
                        progress.switch(prefix + "_stream")
                    if public and (event.kind != "reasoning_delta" or call["phase"] != "final_answer"):
                        channel = "reasoning" if event.kind == "reasoning_delta" else "text"
                        pending[channel] += masks[channel].feed(event.text)
                        if offsets[channel] == 0 or progress.clock() - last_flush >= 0.08:
                            flush()
        if completed is None or not completed.finish_reason:
            raise ModelProtocolError("Model stream ended without a completed response; no tool was dispatched")
        if cancel.is_set():
            raise Cancelled("Stopped before accepting the model response")
        flush(final=True)
        progress.emit({"kind": "stream_end", **common, "transport": transport, "complete": True,
                       "duration_seconds": max(0.0, progress.clock() - started),
                       "first_text_seconds": max(0.0, first - started) if first is not None else None,
                       "native_tool_calls": len(completed.tool_calls),
                       "finish_reason": completed.finish_reason})
        return completed
    except Exception as exc:
        flush(final=True)
        progress.emit({"kind": "stream_end", **common, "transport": transport, "complete": False,
                       "duration_seconds": max(0.0, progress.clock() - started),
                       "first_text_seconds": max(0.0, first - started) if first is not None else None,
                       "error_type": type(exc).__name__, "error": str(exc),
                       "diagnostic": getattr(exc, "diagnostic", {})})
        raise
    finally:
        progress.switch(call["return_stage"])

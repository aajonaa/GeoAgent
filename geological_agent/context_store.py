"""Owner/conversation-scoped PostgreSQL evidence and LangGraph persistence.

Authentication remains in the existing team store. Scope is supplied by the
authenticated broker, never by an LLM tool argument. Originals are append-only.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path

from .tools import Tool, ToolDefinition, ToolOutput, ToolFailure, object_schema


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class ContextStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContextScope:
    owner_id: str
    conversation_id: str

    def __post_init__(self):
        if any(not isinstance(v, str) or not v or len(v) > 256
               for v in (self.owner_id, self.conversation_id)):
            raise ValueError("A server-authenticated owner and conversation are required")


def private_dsn(path):
    path = Path(path)
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ContextStoreError("The PostgreSQL credential file must be private (0600)")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ContextStoreError("The PostgreSQL credential file is empty")
    return value


SCHEMA = """
CREATE SCHEMA IF NOT EXISTS geotool_context;
CREATE SCHEMA IF NOT EXISTS geotool_checkpoints;
CREATE TABLE IF NOT EXISTS geotool_context.runs (
    run_id text PRIMARY KEY, owner_id text NOT NULL, conversation_id text NOT NULL,
    workspace_digest text NOT NULL, task text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (owner_id, conversation_id, run_id)
);
CREATE TABLE IF NOT EXISTS geotool_context.evidence (
    seq bigserial UNIQUE NOT NULL, evidence_id text PRIMARY KEY,
    owner_id text NOT NULL, conversation_id text NOT NULL, run_id text NOT NULL,
    kind text NOT NULL, source_key text NOT NULL, sha256 text NOT NULL,
    raw_json text NOT NULL, payload jsonb NOT NULL, label text NOT NULL,
    search_text tsvector GENERATED ALWAYS AS (to_tsvector('simple', label || ' ' || raw_json)) STORED,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (owner_id, conversation_id, run_id, kind, source_key),
    FOREIGN KEY (owner_id, conversation_id, run_id)
        REFERENCES geotool_context.runs(owner_id, conversation_id, run_id)
);
CREATE INDEX IF NOT EXISTS evidence_scope_seq ON geotool_context.evidence(owner_id, conversation_id, seq);
CREATE INDEX IF NOT EXISTS evidence_scope_run ON geotool_context.evidence(owner_id, conversation_id, run_id, kind);
CREATE INDEX IF NOT EXISTS evidence_text ON geotool_context.evidence USING gin(search_text);
CREATE OR REPLACE FUNCTION geotool_context.reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Context originals are append-only'; END $$;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='context_evidence_immutable'
                AND tgrelid='geotool_context.evidence'::regclass) THEN
  CREATE TRIGGER context_evidence_immutable BEFORE UPDATE OR DELETE
    ON geotool_context.evidence FOR EACH ROW EXECUTE FUNCTION geotool_context.reject_mutation();
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='context_run_immutable'
                AND tgrelid='geotool_context.runs'::regclass) THEN
  CREATE TRIGGER context_run_immutable BEFORE UPDATE OR DELETE
    ON geotool_context.runs FOR EACH ROW EXECUTE FUNCTION geotool_context.reject_mutation();
 END IF;
END $$;
"""


class PostgresContextStore:
    def __init__(self, dsn, scope):
        if not isinstance(scope, ContextScope):
            raise TypeError("ContextScope is required")
        self._dsn, self.scope = dsn, scope

    @contextmanager
    def connection(self, *, autocommit=False, checkpoints=False):
        import psycopg
        from psycopg.rows import dict_row
        try:
            with psycopg.connect(self._dsn, autocommit=autocommit, row_factory=dict_row,
                                 connect_timeout=8, prepare_threshold=0,
                                 options="-c search_path=geotool_checkpoints" if checkpoints else
                                         "-c search_path=public -c statement_timeout=15000") as conn:
                yield conn
        except psycopg.Error:
            # Driver errors must never expose the DSN or SQL containing data.
            raise ContextStoreError("PostgreSQL context persistence failed; originals were not replaced") from None

    def setup(self):
        with self.connection(autocommit=True) as conn:
            conn.execute(SCHEMA, prepare=False)
        with self.checkpoint() as saver:
            saver.setup()

    @contextmanager
    def checkpoint(self):
        from langgraph.checkpoint.postgres import PostgresSaver
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
        allowed = [("geological_agent.contracts", name) for name in ("Message", "ToolCall", "ArtifactRef")]
        serde = JsonPlusSerializer(pickle_fallback=False, allowed_msgpack_modules=allowed,
                                   allowed_json_modules=allowed)
        with self.connection(autocommit=True, checkpoints=True) as conn:
            yield PostgresSaver(conn, serde=serde)

    def thread_id(self, run_id):
        return "context:" + digest([self.scope.owner_id, self.scope.conversation_id, run_id])

    def begin_run(self, run_id, task, workspace):
        owner, conversation = self.scope.owner_id, self.scope.conversation_id
        workspace_digest = digest(str(Path(workspace).resolve()))
        with self.connection() as conn:
            conn.execute("""INSERT INTO geotool_context.runs
                (run_id,owner_id,conversation_id,workspace_digest,task) VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (run_id) DO NOTHING""", (run_id, owner, conversation, workspace_digest, task))
            row = conn.execute("SELECT owner_id,conversation_id,workspace_digest FROM geotool_context.runs WHERE run_id=%s",
                               (run_id,)).fetchone()
            if row != {"owner_id": owner, "conversation_id": conversation, "workspace_digest": workspace_digest}:
                raise ContextStoreError("Run ownership or workspace does not match the saved context")

    def _put(self, conn, run_id, kind, source_key, payload, label=""):
        from psycopg.types.json import Jsonb
        raw = canonical(payload)
        checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        owner, conversation = self.scope.owner_id, self.scope.conversation_id
        identity = "ev_" + digest([owner, conversation, run_id, kind, source_key])
        # JSONB cannot represent U+0000. Preserve its exact escaped JSON in the
        # raw text column rather than rejecting or deleting that evidence.
        indexed = {"raw_json_storage": True} if "\\u0000" in raw else payload
        conn.execute("""INSERT INTO geotool_context.evidence
            (evidence_id,owner_id,conversation_id,run_id,kind,source_key,sha256,raw_json,payload,label)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (evidence_id) DO NOTHING""",
            (identity, owner, conversation, run_id, kind, source_key, checksum, raw, Jsonb(indexed), label))
        row = conn.execute("""SELECT sha256,run_id,kind FROM geotool_context.evidence
            WHERE evidence_id=%s AND owner_id=%s AND conversation_id=%s""",
            (identity, owner, conversation)).fetchone()
        if not row or row["sha256"] != checksum:
            raise ContextStoreError("An immutable evidence identity cannot be overwritten")
        return {"evidence_id": identity, "sha256": checksum, "source_run_id": run_id,
                "kind": kind, "total_chars": len(raw)}

    def put(self, run_id, kind, source_key, payload, label=""):
        with self.connection() as conn:
            return self._put(conn, run_id, kind, source_key, payload, label)

    def sync_state(self, state):
        metadata = state.setdefault("metadata", {})
        start = metadata.get("context_archived_messages", 0)
        if start > len(state["messages"]):
            raise ContextStoreError("Archived history cannot be replaced by a shorter history")
        with self.connection() as conn:
            for index in range(start, len(state["messages"])):
                message = state["messages"][index]
                label = " ".join([message.role, message.tool_call_id or "",
                                  *(call.name + " " + call.id for call in message.tool_calls)])
                self._put(conn, state["run_id"], "message", str(index), asdict(message), label)
            for key, note in metadata.get("context_summaries", {}).items():
                self._put(conn, state["run_id"], "summary", key, note, "unverified continuation summary")
            if state.get("artifacts"):
                self._put(conn, state["run_id"], "artifact_manifest", digest([asdict(a) for a in state["artifacts"]]),
                          [asdict(a) for a in state["artifacts"]], "recorded artifact paths and producing call IDs")
        metadata["context_archived_messages"] = len(state["messages"])

    def read(self, evidence_id, *, offset=0, limit=4000):
        if not isinstance(offset, int) or not isinstance(limit, int) or offset < 0 or limit < 1 or limit > 12000:
            raise ValueError("Use a nonnegative offset and a page size of 1 to 12000 characters")
        with self.connection() as conn:
            row = conn.execute("""SELECT evidence_id,run_id,kind,sha256,raw_json,created_at
                FROM geotool_context.evidence WHERE evidence_id=%s AND owner_id=%s AND conversation_id=%s""",
                (evidence_id, self.scope.owner_id, self.scope.conversation_id)).fetchone()
        if not row:
            raise KeyError("Evidence not found in this conversation")
        raw = row.pop("raw_json")
        if hashlib.sha256(raw.encode("utf-8")).hexdigest() != row["sha256"]:
            raise ContextStoreError("Archived evidence checksum mismatch")
        if offset > len(raw):
            raise ValueError("Offset exceeds the evidence length")
        end = min(len(raw), offset + limit)
        return {"evidence_id": row["evidence_id"], "source_run_id": row["run_id"], "kind": row["kind"],
                "sha256": row["sha256"], "created_at": row["created_at"].isoformat(),
                "content": raw[offset:end], "format": "original_json_fragment",
                "offset": offset, "next_offset": end, "total_chars": len(raw), "has_more": end < len(raw),
                "trust": "Historical record, not a new execution. Check source_run_id and file version before reuse."}

    def search(self, query="", *, run_id=None, kind=None, after=0, limit=10):
        if not isinstance(query, str) or len(query) > 2000 or not isinstance(after, int) or after < 0 or not 1 <= limit <= 30:
            raise ValueError("Invalid evidence search or page size")
        predicates = ["owner_id=%s", "conversation_id=%s", "seq>%s"]
        values = [self.scope.owner_id, self.scope.conversation_id, after]
        if run_id is not None:
            predicates.append("run_id=%s")
            values.append(run_id)
        if kind is not None:
            predicates.append("kind=%s")
            values.append(kind)
        if query:
            # Literal fallback handles call IDs, punctuation and Chinese text
            # without pretending the default text-search parser segments Chinese.
            predicates.append("(search_text @@ plainto_tsquery('simple',%s) OR strpos(lower(raw_json),lower(%s))>0 OR strpos(lower(label),lower(%s))>0)")
            values.extend([query, query, query])
        values.append(limit + 1)
        with self.connection() as conn:
            rows = conn.execute("""SELECT seq,evidence_id,run_id,kind,sha256,label,
                char_length(raw_json) AS total_chars, left(raw_json,240) AS preview
                FROM geotool_context.evidence WHERE """ + " AND ".join(predicates) + " ORDER BY seq LIMIT %s",
                values).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        return {"matches": rows, "has_more": more, "next_after": rows[-1]["seq"] if rows else after,
                "preview_is_complete": False, "scope": "authenticated conversation"}


def register_context_tools(registry, store):
    text = {"type": "string"}
    def search(args, ctx):
        ctx.check()
        return ToolOutput(store.search(args.get("query", ""), run_id=args.get("run_id"),
                                       kind=args.get("kind"), after=args.get("after", 0), limit=args.get("limit", 10)))
    def read(args, ctx):
        ctx.check()
        try:
            return ToolOutput(store.read(args["evidence_id"], offset=args.get("offset", 0),
                                         limit=min(args.get("limit", 4000), ctx.settings.max_tool_output_chars)))
        except KeyError:
            raise ToolFailure("evidence_not_found", "Evidence is not available in this authenticated conversation", retryable=True) from None

    search_schema = object_schema({
        "query": {**text, "description": "Literal terms, original call ID, tool name, or filename. Empty lists available records."},
        "run_id": {**text, "description": "Optional source run ID. Omit to search this authenticated conversation only."},
        "kind": {**text, "enum": ["message", "exchange", "summary", "artifact_manifest"], "description": "Optional record type."},
        "after": {"type": "integer", "minimum": 0, "description": "Pagination cursor returned as next_after, initially zero."},
        "limit": {"type": "integer", "minimum": 1, "maximum": 30, "description": "Records per page; use next_after to continue."}})
    read_schema = object_schema({
        "evidence_id": {**text, "description": "Exact evidence ID from the compaction index or context_search."},
        "offset": {"type": "integer", "minimum": 0, "description": "Character offset, initially zero."},
        "limit": {"type": "integer", "minimum": 1, "maximum": 12000, "description": "Characters per page. Continue at next_offset while has_more is true."}
    }, ["evidence_id"])
    search_output = object_schema({
        "matches": {"type": "array", "items": {"type": "object"}}, "has_more": {"type": "boolean"},
        "next_after": {"type": "integer"}, "preview_is_complete": {"type": "boolean"}, "scope": text
    }, ["matches", "has_more", "next_after", "preview_is_complete", "scope"])
    read_output = object_schema({
        **{key: text for key in ("evidence_id", "source_run_id", "kind", "sha256", "created_at", "content", "format", "trust")},
        **{key: {"type": "integer"} for key in ("offset", "next_offset", "total_chars")},
        "has_more": {"type": "boolean"}
    }, ["evidence_id", "source_run_id", "kind", "sha256", "created_at", "content", "format", "trust",
        "offset", "next_offset", "total_chars", "has_more"])
    registry.register(Tool(ToolDefinition("context_search", "Find archived evidence in this private conversation; does not execute prior tools.",
        "Compaction omitted an older observation or its evidence ID is unknown.", search_schema, search_output), search))
    registry.register(Tool(ToolDefinition("context_read", "Read exact archived evidence with provenance and explicit pagination.",
        "Inspect an earlier observation before relying on it. A summary or search preview is not proof.", read_schema, read_output), read))

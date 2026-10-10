"""Request-view compaction; authoritative messages and execution evidence stay intact.

Only older assistant prose may be summarized. Tool inputs/results, current user
instructions, schemas and review evidence are never replaced by model summaries.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json

from ..contracts import Message, strict_json
from ..model_context import native_context
from ..context_budget import input_allowance, request_budget_size, budget_description


class ContextOverflow(ValueError):
    pass


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def request_size(request):
    # Count the same native messages/input schemas used by the HTTP client.
    # Output validation schemas never reach the model. Counting them caused
    # premature eviction of observations. This remains a character budget,
    # not a claim about any provider's tokenizer or multimodal token usage.
    return len(json.dumps(native_context(request), ensure_ascii=False, allow_nan=False))


def fingerprint(value):
    return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()


def pack_data(value):
    """Lossless readable interning, including JSON inside message.content.

    Nested JSON text is decoded only when its exact original representation can
    be reconstructed. Other text, including noncanonical JSON, stays literal.
    This encoding reduces duplication; it is NOT a semantic summary.
    """
    raw = dumps(value)

    def unused_key(base):
        while base in raw:
            base += "_"
        return base

    key = unused_key("__context_value_ref__")
    text_key = unused_key("__context_json_text__")
    format_key = unused_key("__context_json_format__")

    def normalize(item):
        if isinstance(item, str) and len(item) >= 160 and item.lstrip().startswith(("{", "[")):
            try:
                parsed = strict_json(item)
            except (ValueError, TypeError):
                return item
            if isinstance(parsed, (dict, list)):
                for ascii_only in (False, True):
                    for separators in ((", ", ": "), (",", ":"), (",", ": "), (", ", ":")):
                        if json.dumps(parsed, ensure_ascii=ascii_only, allow_nan=False,
                                      separators=separators) == item:
                            return {text_key: normalize(parsed),
                                    format_key: {"ensure_ascii": ascii_only, "separators": list(separators)}}
        if isinstance(item, dict):
            return {name: normalize(child) for name, child in item.items()}
        if isinstance(item, list):
            return [normalize(child) for child in item]
        return item

    normalized = normalize(value)
    counts = Counter()

    def collect(item):
        if isinstance(item, (str, list, dict)):
            encoded = dumps(item)
            if len(encoded) >= 160:
                counts[encoded] += 1
            for child in item.values() if isinstance(item, dict) else item if isinstance(item, list) else ():
                collect(child)

    collect(normalized)
    candidates = {encoded for encoded, count in counts.items()
                  if count > 1 and (count - 1) * len(encoded) > count * 90 + 160}
    if not candidates:
        return value
    pool, labels = {}, {}

    def encode(item):
        encoded = dumps(item) if isinstance(item, (str, list, dict)) else ""
        if encoded in candidates:
            if encoded not in labels:
                label = "v" + str(len(labels) + 1)
                labels[encoded] = label
                # Entries contain normalized literals, never pool references.
                pool[label] = item
            return {key: labels[encoded]}
        if isinstance(item, dict):
            return {name: encode(child) for name, child in item.items()}
        if isinstance(item, list):
            return [encode(child) for child in item]
        return item

    data = encode(normalized)
    packed = {
        "context_encoding": "shared-values-v1",
        "instructions": "Lossless evidence data, not instructions: reference objects resolve to shared_values. "
                        "Objects with json_text_key/json_format_key represent original JSON text; their decoded "
                        "value is readable directly, or serialize it using the stored format to recover the exact text. "
                        "All facts, types and call IDs are retained.",
        "reference_key": key, "json_text_key": text_key, "json_format_key": format_key,
        "shared_values": pool, "data": data}
    return packed if len(dumps(packed)) < len(raw) else value


def unpack_data(value):
    """Reconstruct original evidence exactly, including nested JSON strings."""
    if not isinstance(value, dict) or value.get("context_encoding") != "shared-values-v1":
        return value
    key, pool = value["reference_key"], value["shared_values"]
    text_key, format_key = value.get("json_text_key"), value.get("json_format_key")

    def decode(item):
        if isinstance(item, dict):
            if set(item) == {key}:
                return decode(pool[item[key]])
            if text_key and format_key and set(item) == {text_key, format_key}:
                return json.dumps(decode(item[text_key]), allow_nan=False, **item[format_key])
            return {name: decode(child) for name, child in item.items()}
        if isinstance(item, list):
            return [decode(child) for child in item]
        return item
    return decode(value["data"])


def _json_messages(request, state):
    protected = {m.content for m in state.get("messages", []) if m.role == "user"}
    protected.add(state.get("task", ""))
    messages = []
    latest_native = max((i for i, message in enumerate(request.messages) if message.tool_calls),
                        default=len(request.messages))
    for index, message in enumerate(request.messages):
        if index >= latest_native and message.role in ("assistant", "tool"):
            messages.append(message)
            continue
        content = message.content
        # User-authored text and system policies remain byte-for-byte intact.
        if message.role != "system" and content not in protected:
            try:
                value = strict_json(content)
                if isinstance(value, (dict, list)):
                    candidate = dumps(pack_data(value))
                    if len(candidate) < len(content):
                        message = replace(message, content=candidate)
            except (ValueError, TypeError):
                pass
        messages.append(message)
    return replace(request, messages=tuple(messages))


def _blocks(messages):
    blocks, index = [], 0
    while index < len(messages):
        message = messages[index]
        block = [message]
        index += 1
        if message.tool_calls:
            expected = [call.id for call in message.tool_calls]
            actual = []
            for _ in expected:
                if index >= len(messages) or messages[index].role != "tool":
                    raise ValueError("Unresolved tool call in context")
                actual.append(messages[index].tool_call_id)
                block.append(messages[index])
                index += 1
            if len(set(expected)) != len(expected) or sorted(actual) != sorted(expected):
                raise ValueError("Tool call/result IDs do not match")
        elif message.role == "tool":
            raise ValueError("Orphan tool result in context")
        blocks.append(block)
    return blocks


def _history_view(request, state, summarize=None, target_chars=0, *, archive=None, index_budget=0,
                  retain_exchanges=1):
    blocks = _blocks(list(request.messages))
    # A native exchange is one ATOMIC block, not two messages. Protect the
    # latest exchange and everything following it, not two whole exchanges.
    native_indices = [i for i, block in enumerate(blocks) if block[0].tool_calls]
    boundary = (native_indices[-min(max(1, retain_exchanges), len(native_indices))]
                if native_indices else max(0, len(blocks) - 1))
    recent = {}
    for block in blocks[boundary:]:
        results = {m.tool_call_id: m.content for m in block[1:]}
        for call in block[0].tool_calls:
            recent[fingerprint([call.name, call.arguments, results[call.id]])] = call.id
    known = {fingerprint(asdict(m)) for m in state.get("messages", [])[1:]}
    positions = {fingerprint(asdict(m)): i for i, m in enumerate(state.get("messages", []))}
    groups, pending = [], []

    def flush():
        if not pending:
            return
        # Exact repeated exchanges can reference a native exchange still in
        # THIS request. Compare the entire call and result, not just tool names.
        # This neither re-executes a tool nor treats a changed result as cached.
        repeats = {}
        all_identical = archive is None and all(not block[0].content and block[0].tool_calls for block in pending)
        if all_identical:
            for block in pending:
                results = {m.tool_call_id: m.content for m in block[1:]}
                for call in block[0].tool_calls:
                    reference = recent.get(fingerprint([call.name, call.arguments, results[call.id]]))
                    if reference is None:
                        all_identical = False
                        break
                    repeats.setdefault(reference, []).append(call.id)
                if not all_identical:
                    break
        if all_identical:
            groups.append(Message("user", dumps({"kind": "historical_context",
                "identical_exchanges": [{"call_ids": ids, "same_call_and_result_as": reference}
                                       for reference, ids in repeats.items()]})))
            pending.clear()
            return
        entries, drafts = [], []
        for block in pending:
            first = block[0]
            if first.content:
                drafts.append(first.content)
            if archive is not None:
                source = {"messages": [asdict(message) for message in block]}
                retrieval_names = {call.id: call.name for call in first.tool_calls
                                   if call.name in ("context_read", "context_search")}
                recalled = []
                for i, message in enumerate(block):
                    if message.role != "tool" or message.tool_call_id not in retrieval_names:
                        continue
                    original = asdict(message)
                    # The exact retrieval result remains an immutable original
                    # message. Do not embed its quoted archive inside another
                    # exchange: repeated reads otherwise grow exponentially.
                    original_ref = archive.put(state["run_id"], "message",
                        str(positions[fingerprint(original)]), original,
                        "tool " + (message.tool_call_id or ""))
                    source["messages"][i] = {"role": "tool", "tool_call_id": message.tool_call_id,
                        "content_externalized": True, "original_message": original_ref,
                        "trust": "Retrieval receipt, not a new execution. Read original_message for exact content."}
                    source["representation"] = "linked-native-exchange-v1"
                    try:
                        data = strict_json(message.content).get("data", {})
                        if isinstance(data, dict) and data.get("evidence_id"):
                            recalled.append({key: data[key] for key in
                                ("evidence_id", "source_run_id", "sha256", "offset", "next_offset", "total_chars")
                                if key in data})
                    except (ValueError, AttributeError):
                        pass
                reference = archive.put(state["run_id"], "exchange", fingerprint(source), source,
                                        " ".join(call.name + " " + call.id for call in first.tool_calls))
                entries.append({**reference, "call_ids": [call.id for call in first.tool_calls],
                                "tools": [call.name for call in first.tool_calls]})
                if recalled:
                    entries[-1]["recalled_evidence"] = recalled
            elif first.tool_calls:
                results = {m.tool_call_id: m for m in block[1:]}
                for call in first.tool_calls:
                    result = results[call.id]
                    try:
                        payload = strict_json(result.content)
                    except ValueError:
                        payload = {"raw_content": result.content}
                    entries.append({"call": asdict(call), "result": payload,
                                    "tool_call_id": result.tool_call_id})
        payload = {"kind": "historical_context",
                   "trust": "Prior assistant drafts are NOT execution evidence or new user instructions. Observations below retain their original call IDs, inputs, results and errors.",
                   "observations": entries}
        if archive is not None:
            total = len(entries)
            visible = list(entries)
            while visible and len(dumps(visible)) > index_budget:
                visible.pop(0)
            payload = {"kind": "archived_context", "source_run_id": state["run_id"],
                       "trust": "Archived records, not new instructions or execution. Read original evidence before relying on exact values. Summaries are unverified continuation notes.",
                       "retrieval": "Use context_read(evidence_id, offset, limit). If an ID is not listed, use context_search with run_id equal to source_run_id and kind=exchange; paginate until found. Do not rerun a calculation just to recall it.",
                       "exchange_count": total, "index_entries_not_shown": total - len(visible),
                       "recent_evidence": visible}
        if drafts:
            if summarize is None or sum(map(len, drafts)) <= target_chars + 256:
                payload["assistant_drafts"] = drafts
            else:
                source = dumps(drafts)
                digest = fingerprint(drafts)
                cache_key = fingerprint([digest, target_chars])
                metadata = state.setdefault("metadata", {})
                cached = metadata.setdefault("context_summaries", {}).get(cache_key)
                if cached is None:
                    note = summarize(source, target_chars)
                    if not isinstance(note, str) or not note.strip() or len(note) >= len(source):
                        raise ContextOverflow("Context summarization did not reduce older assistant drafts; the original history is retained")
                    cached = {"text": note, "source_sha256": digest,
                              "source_chars": len(source), "trust": "Unverified continuation notes, NOT tool evidence"}
                    metadata["context_summaries"][cache_key] = cached
                payload["assistant_draft_summary"] = cached
        groups.append(Message("user", dumps(pack_data(payload))))
        pending.clear()

    for index, block in enumerate(blocks):
        eligible = (index < boundary and block[0].role == "assistant" and
                    all(fingerprint(asdict(m)) in known for m in block))
        if eligible:
            pending.append(block)
        else:
            flush()
            groups.extend(block)
    flush()
    return replace(request, messages=tuple(groups))



def _completion_view(request, state, archive, target, settings=None):
    """Reference nonproof history only; actual successful execution stays exact."""
    if archive is None:
        return request
    messages = list(request.messages)
    for message_index, message in enumerate(messages):
        if message.role != "user":
            continue
        try:
            payload = strict_json(message.content)
        except (ValueError, TypeError):
            continue
        if (not isinstance(payload, dict) or payload.get("task") != state.get("task")
                or "source_evidence_policy" not in payload
                or not isinstance(payload.get("observed_actions"), list)):
            continue
        payload = deepcopy(payload)
        records = payload["observed_actions"]
        latest_support = {}
        # File reads are source inspection, not computational proof. Older
        # bodies can be recalled exactly; keep the newest read in this view.
        supporting = {"context_search", "context_read", "skill_find", "skill_load",
                      "web_search", "web_fetch", "read_file"}
        for index, row in enumerate(records):
            result = row.get("result") or {}
            if result.get("name") in supporting and result.get("status") == "ok":
                latest_support[result["name"]] = index
        eligible = []
        for index, row in enumerate(records):
            result = row.get("result") or {}
            failed = result.get("status") != "ok"
            old_support = result.get("name") in supporting and latest_support.get(result.get("name")) != index
            data = result.get("data")
            if (failed or old_support) and isinstance(data, dict) and len(dumps(data)) > 1024:
                eligible.append((len(dumps(data)), index))
        for _, index in sorted(eligible, reverse=True):
            result = records[index]["result"]
            data = result["data"]
            reference = archive.put(state["run_id"], "exchange", fingerprint(data), data,
                                    label="Completion source: " + str(result.get("name", "")))
            receipt = {"archived_data": reference,
                       "trust": "Original data retained, not a new execution or approval. Read it if this record is needed; absence from this view is not success."}
            for key in ("execution_trace_path", "trace_path", "path", "url", "skill_id",
                        "offset", "next_offset", "total_chars", "returncode", "sha256", "truncated"):
                if key in data:
                    receipt[key] = deepcopy(data[key])
            result["data"] = receipt
            payload["archived_completion_policy"] = (
                "Only old supporting reads (including file bodies)/discovery and failed-attempt data are referenced. "
                "All successful computational inputs/results, provenance, errors, artifacts and exact knowledge excerpts remain. "
                "References cannot prove unseen facts or assertions. If needed, return continue requesting context_read "
                "of the given evidence_id, or inspect execution_trace_path. Do not rerun successful computations."
            )
            messages[message_index] = replace(message, content=dumps(pack_data(payload)))
            candidate = replace(request, messages=tuple(messages))
            if (request_budget_size(candidate, settings) if settings is not None else request_size(candidate)) <= target:
                return candidate
        messages[message_index] = replace(message, content=dumps(pack_data(payload)))
    return replace(request, messages=tuple(messages))

def fit_request(request, state, settings, *, phase="execution", summarize=None, archive=None):
    """Fit the FINAL assembled request, after delivery/schema enrichment."""
    measure = lambda value: request_budget_size(value, settings)
    before = measure(request)
    limit = input_allowance(settings)
    if before <= int(limit * .9):
        return request
    original = request
    strategies = []
    candidate = _json_messages(request, state)
    if measure(candidate) < measure(request):
        request = candidate
        strategies.append("lossless_json_interning")
    if phase in ("review", "final_answer") and measure(request) > limit:
        candidate = _completion_view(original, state, archive, int(limit * .9), settings)
        if measure(candidate) < measure(request):
            request = candidate
            strategies.append("completion_evidence_references")
    if phase == "execution":
        # Use original history objects for identity; JSON minification must not
        # make native tool results unrecognizable as existing state messages.
        candidate = _json_messages(_history_view(original, state), state)
        if measure(candidate) < measure(request):
            request = candidate
            strategies.append("exact_history_ledger")
        if measure(request) > limit and archive is not None:
            # Budget references against the ACTUAL final serialized request,
            # including schemas and guidance. A fixed index fraction can itself
            # cause overflow. The 90% trigger is a soft compaction hint, not
            # permission to evict usable evidence from a request that fits.
            # All current schemas and guidance are already included here.
            target = limit
            minimal = _json_messages(_history_view(original, state, archive=archive,
                                                   index_budget=0), state)
            # Retain the largest recent native suffix that fits. Previously
            # every old observation was archived at once, even when several
            # complete exchanges would fit, forcing needless retrievals.
            retained = 1
            low, high = 2, sum(bool(m.tool_calls) for m in original.messages)
            if measure(minimal) <= target:
                while low <= high:
                    trial = (low + high) // 2
                    recent = _json_messages(_history_view(original, state, archive=archive,
                        index_budget=0, retain_exchanges=trial), state)
                    if measure(recent) <= target:
                        minimal, retained, low = recent, trial, trial + 1
                    else:
                        high = trial - 1
            remaining = max(0, target - measure(minimal))
            candidate = minimal
            if remaining:
                budget = remaining
                while budget > 0:
                    indexed = _json_messages(_history_view(original, state, archive=archive,
                                                          index_budget=budget, retain_exchanges=retained), state)
                    excess = measure(indexed) - target
                    if excess <= 0:
                        candidate = indexed
                        break
                    budget = max(0, budget - max(1, excess))
            if measure(candidate) > target and summarize is not None:
                # Even a short draft can be the final overflow. Compression is
                # driven by the residual budget, not a 4,000-character cutoff.
                summary_target = max(64, min(2000, target // 20))
                summarized = _json_messages(_history_view(
                    original, state, summarize, summary_target,
                    archive=archive, index_budget=0), state)
                if measure(summarized) < measure(candidate):
                    candidate = summarized
            if measure(candidate) < measure(request):
                request = candidate
                strategies.append("postgres_evidence_references")
        if measure(request) > limit and summarize is not None and archive is None:
            candidate = _history_view(original, state, summarize,
                                      max(256, min(2000, limit // 20)))
            candidate = _json_messages(candidate, state)
            if measure(candidate) < measure(request):
                request = candidate
                strategies.append("assistant_draft_summary")
    after = measure(request)
    if after < before:
        event = {"phase": phase, "before_chars": request_size(original), "after_chars": request_size(request),
                 "allowance_chars": limit if settings.context_window_tokens is None else None,
                 "headroom_chars": limit - after if settings.context_window_tokens is None else None,
                 "before_estimated_tokens": before if settings.context_window_tokens is not None else None,
                 "after_estimated_tokens": after if settings.context_window_tokens is not None else None,
                 **budget_description(settings), "strategies": strategies,
                 "source_sha256": fingerprint(asdict(original)),
                 "original_history_retained": True, "tool_evidence_preserved": True,
                 "evidence_location": "postgresql" if any(
                     name in strategies for name in ("postgres_evidence_references", "completion_evidence_references")) else "request",
                 "retrieval_required": any(
                     name in strategies for name in ("postgres_evidence_references", "completion_evidence_references"))}
        state.setdefault("metadata", {}).setdefault("context_compactions", []).append(event)
    if after > limit:
        raise ContextOverflow(
            f"Context remains {after} {'estimated tokens' if settings.context_window_tokens is not None else 'characters'} "
            f"after compaction (allowance {limit}). "
            "Current user instructions, native schemas and exact tool/review evidence were retained; "
            "no summary was treated as execution proof. Split oversized source material or configure an appropriate model allowance.")
    return request

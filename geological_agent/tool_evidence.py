"""Runtime-owned input lineage and state-dependent failure recovery.

This is an audit aid for trusted execution, not an OS security boundary.
An input's origin is not certification of its scientific correctness.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

from .contracts import ErrorInfo, ToolResult, strict_json


def digest(value):
    return hashlib.sha256(value).hexdigest()


def identity(value):
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))


def file_stamp(path):
    if not path.exists():
        return {"exists": False}
    if path.is_file():
        with path.open("rb") as stream:
            value = hashlib.file_digest(stream, "sha256").hexdigest()
        return {"exists": True, "sha256": value}
    return {"exists": True, "kind": "directory"}


class EvidenceLedger:
    def __init__(self, context):
        self.ctx = context
        self.state = context.evidence_state
        self.files = self.state.setdefault("files", {})
        self.failures = self.state.setdefault("failures", {})
        self.sources = self.state.setdefault("sources", {})

    def inputs(self, tool, args):
        rows = []
        for field in tool.input_paths:
            values = args.get(field, [])
            for name in values if isinstance(values, list) else [values]:
                if not isinstance(name, str):
                    continue
                path = self.ctx.path(name)
                stamp = file_stamp(path)
                old = self.files.get(name, {})
                origin = old if old.get("sha256") == stamp.get("sha256") and stamp.get("sha256") else {}
                rows.append({"parameter": field, "path": name, **stamp,
                             "origin": origin.get("origin", "unknown"),
                             "source": deepcopy(origin),
                             "reference_data": field in tool.reference_paths})
        return rows

    def unchanged(self, row):
        try:
            return file_stamp(self.ctx.path(row["path"])) == {
                k: row[k] for k in ("exists", "sha256", "kind") if k in row}
        except (OSError, ValueError):
            return False

    def blocked(self, call, args, inputs):
        for key, record in self.failures.items():
            if record["code"] == "missing_input":
                same = (any(row["path"] == dep["path"] for row in inputs for dep in record["dependencies"])
                        and all(self.unchanged(dep) for dep in record["dependencies"]))
            else:
                same = key == identity([call.name, args])
            if not same:
                continue
            record["suppressed"] += 1
            return ToolResult(call.id, call.name, "error", error=ErrorInfo(
                "unchanged_failure",
                "This operation was not re-executed: " + record["message"] +
                " The relevant input has not changed. Acquire the real missing input, correct the arguments, "
                "or ask for the missing resource. Do not invent source records to make a tool pass.", False),
                evidence={"execution": "suppressed", "original_error": record["code"],
                          "blocker_key": key, "suppressed_attempts": record["suppressed"],
                          "input_files": deepcopy(inputs)})
        return None

    def observe(self, call, args, tool, inputs, result):
        evidence = {"execution": "cached" if result.cached else "executed",
                    "input_files": deepcopy(inputs)}
        if tool is not None:
            evidence["operation_key"] = identity([call.name, {
                k: v for k, v in args.items() if k not in tool.input_paths}])
        if result.error and not result.error.outcome_unknown:
            code = result.error.code
            missing = [row for row in inputs if not row["exists"]]
            if code == "missing_input" and missing:
                key = identity(["missing_input", sorted(row["path"] for row in missing)])
                self.failures[key] = {"code": code, "message": result.error.message,
                                      "dependencies": deepcopy(missing), "suppressed": 0}
            elif code in {"invalid_arguments", "invalid_path"}:
                self.failures[identity([call.name, args])] = {
                    "code": code, "message": result.error.message,
                    "dependencies": [], "suppressed": 0}
        if result.status == "ok":
            # Only an actual fetch response supplies a source body, never a URL
            # written by the model or a search snippet. Exact copies inherit
            # this observed origin; arbitrary transformations do not.
            if call.name == "web_fetch" and isinstance(result.data.get("content"), str) and result.data["content"]:
                content = result.data["content"].encode("utf-8")
                self.sources[digest(content)] = {
                    "origin": "retrieved", "sha256": digest(content),
                    "source_url": result.data.get("url"),
                    "retrieved_at": result.data.get("retrieved_at"), "call_id": call.id,
                    "scope": "observed source excerpt; not independent scientific validation",
                    "offset": result.data.get("offset", 0),
                    "truncated": result.data.get("truncated", False)}
            for artifact in result.artifacts:
                stamp = file_stamp(self.ctx.path(artifact.path))
                if "sha256" not in stamp:
                    continue
                source = self.sources.get(stamp["sha256"])
                self.files[artifact.path] = deepcopy(source) if source else {
                    "origin": "model_authored" if call.name == "write_file" else "derived_unverified",
                    "sha256": stamp["sha256"], "call_id": call.id,
                    "scope": "generated artifact, not an independently acquired reference dataset"}
        return replace(result, evidence=evidence)

    def pending_missing(self):
        return [record for record in self.failures.values()
                if record["code"] == "missing_input" and record["suppressed"] >= 2
                and all(self.unchanged(dep) for dep in record["dependencies"])]


def reference_gaps(state):
    # A corrected rerun of the same logical query supersedes its previous
    # input version. Historical evidence itself remains immutable.
    latest = {}
    for message in state["messages"]:
        if message.role != "tool":
            continue
        result = strict_json(message.content)
        evidence = result.get("evidence", {})
        if result.get("status") == "ok" and evidence.get("operation_key"):
            latest[evidence["operation_key"]] = result
    gaps = []
    for result in latest.values():
        for row in result.get("evidence", {}).get("input_files", []):
            if row.get("reference_data") and row.get("origin") not in {"user_supplied", "retrieved"}:
                gaps.append({"call_id": result["call_id"], "tool": result["name"],
                             "path": row["path"], "sha256": row.get("sha256"),
                             "origin": row.get("origin", "unknown")})
    return gaps


def reference_gap_message(gaps):
    return ("Reference-data provenance is unresolved: " +
            "; ".join(sorted({row["path"] + " (" + row["origin"] + ")" for row in gaps})) +
            ". Successful lookup only proves that these local rows were read. It does not establish "
            "that the records came from the claimed external source. Acquire the actual source, or "
            "request a caller-supplied dataset. Keep unverified files intact; do not invent or relabel evidence.")

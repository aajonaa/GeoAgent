"""Deterministic request errors do not execute; corrected requests remain usable."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib
import json
from pathlib import Path
from threading import Event

import pytest

from geological_agent.bootstrap import build_registry
from geological_agent.contracts import ToolCall
from geological_agent.settings import Settings
from geological_agent.tools import ToolExecutionContext, ToolExecutor, ToolFailure
from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog
from collection_acceptance.native_cpu_checks import check

CASES = [
    ("HydroVICPrecipitationPhase", "unknown_command"),
    ("SeismicMadagascarFFT", "unknown_command"),
    ("GeoHPGLDirectionalSemivariogram", "unknown_command"),
    ("SeismicMadagascarFFT", "zero_interval"),
]


def examples(name):
    return deepcopy(next(row["example_arguments"] for row in catalog()["tools"] if row["id"] == name))


@pytest.mark.parametrize("name,kind", CASES)
def test_invalid_request_never_enters_handler_and_new_corrected_call_succeeds(name, kind, tmp_path, monkeypatch):
    registry, loader, base = build_registry()
    original = registry.get(name)
    entered = []
    def observed(args, context):
        entered.append(deepcopy(args))
        return original.handler(args, context)
    monkeypatch.setitem(registry._tools, name, replace(original, handler=observed))
    good = examples(name)
    bad = deepcopy(good)
    if kind == "unknown_command":
        bad["command"] = "must never execute"
    else:
        bad["sampling_interval_s"] = 0
    before = json.dumps(bad, sort_keys=True, allow_nan=False)
    sentinel = tmp_path/"unchanged-input.txt"
    sentinel.write_bytes(b"Explicit test sentinel, not scientific observations.\n")
    fingerprint = hashlib.sha256(sentinel.read_bytes()).hexdigest()
    context = ToolExecutionContext("native-error-policy-r8", tmp_path, (name,), Settings(), Event())
    executor = ToolExecutor(registry)
    first = executor.execute(ToolCall("invalid-r8-"+kind+"-"+name, name, bad), context)
    assert first.status == "error" and first.error.code == "invalid_arguments"
    assert first.error.retryable is False and not first.error.outcome_unknown
    assert first.data == {} and not first.artifacts and entered == []
    assert json.dumps(bad, sort_keys=True, allow_nan=False) == before
    assert list(tmp_path.iterdir()) == [sentinel]
    repeated = executor.execute(ToolCall("same-request-r8-"+kind+"-"+name, name, deepcopy(bad)), context)
    assert repeated.status == "error" and not repeated.artifacts and entered == []
    assert list(tmp_path.iterdir()) == [sentinel]
    corrected_id = "corrected-r8-"+kind+"-"+name
    corrected = executor.execute(ToolCall(corrected_id, name, good), context)
    assert corrected_id != first.call_id and corrected.call_id == corrected_id
    assert corrected.status == "ok" and corrected.error is None and not corrected.artifacts
    assert entered == [good]
    check(name, corrected.data, good, output_dir=None)
    assert hashlib.sha256(sentinel.read_bytes()).hexdigest() == fingerprint
    assert list(tmp_path.iterdir()) == [sentinel]


@pytest.mark.parametrize("code", ["temporary_failure", "service_unavailable", "tool_timeout"])
def test_recoverable_runtime_error_flags_are_preserved(code, tmp_path, monkeypatch):
    """Explicit handler failure fixtures, not a claim of actual service outages."""
    name = "HydroVICPrecipitationPhase"
    registry, loader, base = build_registry()
    tool = registry.get(name)
    def temporary(args, context):
        raise ToolFailure(code, "Explicit recoverable-error test fixture", retryable=True,
                          outcome_unknown=code == "tool_timeout")
    monkeypatch.setitem(registry._tools, name, replace(tool, handler=temporary))
    context = ToolExecutionContext("native-transient-r8", tmp_path, (name,), Settings(), Event())
    result = ToolExecutor(registry).execute(ToolCall("transient-r8-"+code, name, examples(name)), context)
    assert result.status == ("timeout" if code == "tool_timeout" else "error")
    assert result.error.code == code and result.error.retryable is True
    assert result.error.outcome_unknown is (code == "tool_timeout")
    assert not result.artifacts


def test_source_integrity_failure_stops_before_child_and_remains_nonretryable(tmp_path, monkeypatch):
    """Inject digest observation only; original source and binaries stay untouched."""
    bridge = importlib.import_module("geological_agent.geology.native_cpu_bridge")
    profile = json.loads(bridge.PROFILE_FILE.read_text(encoding="utf-8"))
    name = "HydroVICPrecipitationPhase"
    source = Path(profile["operations"][name]["root"])/"vendor/vic/calc_rainonly.c"
    original_digest = bridge.digest
    source_before = original_digest(source)
    def observed_digest(path):
        return "0"*64 if Path(path).resolve() == source.resolve() else original_digest(path)
    started = []
    def forbidden_process(*args, **kwargs):
        started.append(True)
        raise AssertionError("A source-integrity failure must never start the CPU child")
    monkeypatch.setattr(bridge, "digest", observed_digest)
    monkeypatch.setattr(bridge.subprocess, "run", forbidden_process)
    registry, loader, base = build_registry()
    context = ToolExecutionContext("native-integrity-r8", tmp_path, (name,), Settings(), Event())
    result = ToolExecutor(registry).execute(ToolCall("integrity-r8", name, examples(name)), context)
    assert result.status == "error" and result.error.code == "integrity_error"
    assert result.error.retryable is False and not result.artifacts and started == []
    assert original_digest(source) == source_before

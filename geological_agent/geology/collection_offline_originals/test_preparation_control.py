"""Failure-gate tests do not execute scientific kernels or alter original evidence."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def prepared_module():
    source = Path(__file__).with_name("prepare.py")
    sys.path.insert(0, str(source.parent))
    spec = importlib.util.spec_from_file_location("offline_originals_prepare_control", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_terminal_preserves_original_failure_and_exits_nonzero(prepared_module, monkeypatch, tmp_path):
    class FailedFlow:
        def __init__(self, *args, **kwargs):
            assert kwargs["max_workers"] == 1
            assert str(tmp_path) in kwargs["journal_path"]

        def run(self):
            return {"select_sources": SimpleNamespace(status="FAILED", error="original source gate rejected input")}

        def summary(self):
            return "FAILED select_sources; terminal not executed"

        def value(self, terminal):
            raise KeyError("terminal not executed")

    monkeypatch.setattr(prepared_module, "HERE", tmp_path)
    monkeypatch.setattr(prepared_module, "Flow", FailedFlow)
    assert prepared_module.main() == 1
    receipt = json.loads((tmp_path / ("preparation-failure-" + prepared_module.REVISION + ".json")).read_text())
    assert receipt["complete"] is False and receipt["exit_code"] == 1
    assert receipt["tasks"]["select_sources"]["error"] == "original source gate rejected input"
    assert "KeyError" not in json.dumps(receipt)


def test_unexpected_preparation_failure_is_reported_without_success(prepared_module, monkeypatch, tmp_path):
    class CrashedFlow:
        def __init__(self, *args, **kwargs):
            pass

        def run(self):
            raise OSError("deliberate isolated preparation failure")

    monkeypatch.setattr(prepared_module, "HERE", tmp_path)
    monkeypatch.setattr(prepared_module, "Flow", CrashedFlow)
    assert prepared_module.main() == 1
    receipt = json.loads((tmp_path / ("preparation-failure-" + prepared_module.REVISION + ".json")).read_text())
    assert receipt["complete"] is False and receipt["exit_code"] == 1
    assert receipt["error"] == "deliberate isolated preparation failure"
    assert "OSError" in receipt["traceback"]


def test_identical_original_bytes_are_reused_unchanged(prepared_module, tmp_path):
    target = tmp_path / "immutable-source.py"
    raw = b"# original source\r\nvalue = 1\r\n"
    prepared_module.immutable_write(target, raw)
    before = target.stat().st_mtime_ns
    prepared_module.immutable_write(target, raw)
    assert target.read_bytes() == raw
    assert target.stat().st_mtime_ns == before


def test_changed_original_bytes_are_not_overwritten(prepared_module, tmp_path):
    target = tmp_path / "immutable-license.txt"
    raw = b"retained original license\r\n"
    target.write_bytes(raw)
    with pytest.raises(RuntimeError, match="Existing preparation evidence differs"):
        prepared_module.immutable_write(target, b"changed license\n")
    assert target.read_bytes() == raw


@pytest.mark.parametrize("ending", [b"\n", b"\r\n"])
def test_only_generated_initializer_may_reuse_newline_equivalent_bytes(prepared_module, monkeypatch, tmp_path, ending):
    monkeypatch.setattr(prepared_module, "HERE", tmp_path)
    target = tmp_path / "vendor" / "__init__.py"
    target.parent.mkdir()
    text = b'"""Verbatim selected original kernels and original license notices."""'
    raw = text + ending
    target.write_bytes(raw)
    prepared_module.generated_initializer(target, text + b"\n")
    assert target.read_bytes() == raw


def test_generated_initializer_content_change_remains_rejected(prepared_module, monkeypatch, tmp_path):
    monkeypatch.setattr(prepared_module, "HERE", tmp_path)
    target = tmp_path / "vendor" / "__init__.py"
    target.parent.mkdir()
    target.write_bytes(b"unexpected_code = True\r\n")
    with pytest.raises(RuntimeError, match="Generated vendor initializer content differs"):
        prepared_module.generated_initializer(target, b'"""Expected generated marker."""\n')
    assert target.read_bytes() == b"unexpected_code = True\r\n"



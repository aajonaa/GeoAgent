"""Cache placement for BPE vocabularies; synthetic payloads, no model API calls."""
import hashlib
import os
from pathlib import Path
import tempfile

import pytest
import tiktoken
import tiktoken.load
import tiktoken.registry

from geological_agent import context_budget
from geological_agent.context_budget import _pin_tokenizer_cache


@pytest.fixture
def cache_env(monkeypatch, tmp_path):
    monkeypatch.delenv("TIKTOKEN_CACHE_DIR", raising=False)
    monkeypatch.delenv("DATA_GYM_CACHE_DIR", raising=False)
    original = {"HOME": os.environ.get("HOME", "")}
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    context_budget._encodings.cache_clear()
    yield tmp_path, original
    context_budget._encodings.cache_clear()


def test_default_is_a_persistent_directory_under_home(cache_env):
    tmp_path, _ = cache_env
    _pin_tokenizer_cache()
    assert Path(os.environ["TIKTOKEN_CACHE_DIR"]) == tmp_path / "home" / ".cache" / "geotool-tiktoken"
    assert Path(os.environ["TIKTOKEN_CACHE_DIR"]).is_dir()


@pytest.mark.parametrize("configured", ["/srv/tiktoken", ""])
def test_operator_setting_always_wins(monkeypatch, configured):
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", configured)
    _pin_tokenizer_cache()
    assert os.environ["TIKTOKEN_CACHE_DIR"] == configured


def test_read_only_home_keeps_the_previous_behavior(monkeypatch, tmp_path):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("cannot contain a cache", encoding="utf-8")
    monkeypatch.delenv("TIKTOKEN_CACHE_DIR", raising=False)
    monkeypatch.setenv("HOME", str(blocked))
    _pin_tokenizer_cache()
    assert "TIKTOKEN_CACHE_DIR" not in os.environ


def _seed_from_existing_cache(target, original_home):
    """Reuse vocabulary blobs this machine already holds so the test stays offline-fast."""
    import shutil
    places = [Path(os.environ.get("TIKTOKEN_CACHE_DIR", "")), Path(original_home) / ".cache" / "geotool-tiktoken",
              Path(tempfile.gettempdir()) / "data-gym-cache"]
    seeded = 0
    for directory in places:
        if not directory.is_dir():
            continue
        for blob in directory.iterdir():
            name = blob.name
            if blob.is_file() and len(name) == 40 and all(char in "0123456789abcdef" for char in name) \
                    and not (target / name).exists():
                shutil.copyfile(blob, target / name)
                seeded += 1
    return seeded


def test_pinned_cache_is_what_tiktoken_reads(cache_env, monkeypatch):
    """A cold interpreter must reuse the pinned blobs instead of the network."""
    _, original = cache_env
    _pin_tokenizer_cache()
    cached = Path(os.environ["TIKTOKEN_CACHE_DIR"])
    _seed_from_existing_cache(cached, original["HOME"])
    seen, real_read = set(), tiktoken.load.read_file

    def recording(path):
        seen.add(path)
        try:
            return real_read(path)
        except Exception as exc:  # A machine with neither cache nor egress cannot be tested here.
            pytest.skip(f"tiktoken vocabulary unreachable: {type(exc).__name__}")

    monkeypatch.setattr(tiktoken.load, "read_file", recording)
    for name in ("cl100k_base", "o200k_base"):
        tiktoken.get_encoding(name)
    assert all((cached / hashlib.sha1(url.encode()).hexdigest()).is_file() for url in seen) or not seen
    monkeypatch.setattr(tiktoken.registry, "ENCODINGS", {})
    monkeypatch.setattr(tiktoken.load, "read_file",
                        lambda path: pytest.fail(f"network fetch on a warm cache: {path}"))
    for name in ("cl100k_base", "o200k_base"):
        assert len(tiktoken.get_encoding(name).encode("地质 geology")) > 0


def test_worker_receives_the_cache(cache_env):
    from geological_agent.team.trusted_process import worker_environment

    _pin_tokenizer_cache()
    assert worker_environment()["TIKTOKEN_CACHE_DIR"] == os.environ["TIKTOKEN_CACHE_DIR"]

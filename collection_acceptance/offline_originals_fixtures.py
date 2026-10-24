"""Safe repeatable synthetic fixtures for the shared probe; no input overwrite."""
import hashlib
import json
from pathlib import Path

from geological_agent.geology.collection_offline_originals.fixtures import create as original_create


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create(root):
    root = Path(root)
    folder = root / "assets/offline-originals"
    expected = json.loads(Path(__file__).with_name("offline_originals_fixture_hashes.json").read_text())
    if folder.exists():
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError("Synthetic fixture target must be a regular directory")
        files = {path.name: path for path in folder.iterdir()}
        if set(files) != set(expected) or any(path.is_symlink() or not path.is_file() or digest(path) != expected[name] for name, path in files.items()):
            raise ValueError("Existing input differs from the immutable synthetic fixture receipt; no file was overwritten")
        return {"directory": str(folder), "kind": "explicit synthetic acceptance fixtures", "reused_unchanged": True}
    result = original_create(root)
    actual = {path.name: digest(path) for path in folder.iterdir() if path.is_file()}
    if actual != expected:
        raise ValueError("Generated synthetic fixture bytes differ from the frozen version-bound receipt")
    return result


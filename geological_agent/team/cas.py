"""Content-addressed filesystem blob store (CAS) for conversation file snapshots.

Replaces storing duplicate multi-megabyte BLOBs inside `team.sqlite3`.
Blobs are immutable, SHA-256 addressed under `<root>/<sha[:2]>/<sha[2:4]>/<sha>`,
written atomically via temp-file + fsync + replace, and verified on read.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import time
import uuid

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


class ContentAddressedStore:
    """Immutable SHA-256 content-addressed binary store on the local filesystem."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.root.chmod(0o700)

    def path_for(self, sha256: str) -> Path:
        if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
            raise ValueError("Invalid CAS SHA-256 digest")
        return self.root / sha256[:2] / sha256[2:4] / sha256

    def exists(self, sha256: str) -> bool:
        try:
            return self.path_for(sha256).is_file()
        except ValueError:
            return False

    def size(self, sha256: str) -> int | None:
        target = self.path_for(sha256)
        if not target.is_file():
            return None
        return target.stat().st_size

    def put(self, data: bytes) -> tuple[str, int]:
        """Store `data` immutably; deduplicates if the SHA-256 blob already exists."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("CAS requires bytes")
        raw = bytes(data)
        sha = hashlib.sha256(raw).hexdigest()
        target = self.path_for(sha)
        if target.is_file():
            # Fast deduplication path; confirm expected byte length.
            if target.stat().st_size == len(raw):
                return sha, len(raw)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = target.parent / f".{sha}.{uuid.uuid4().hex}.tmp"
        try:
            with tmp.open("wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            if os.name != "nt":
                tmp.chmod(0o600)
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
        return sha, len(raw)

    def get(self, sha256: str) -> bytes:
        """Read and integrity-verify the blob for `sha256`."""
        target = self.path_for(sha256)
        if not target.is_file():
            raise FileNotFoundError(f"CAS blob missing: {sha256}")
        raw = target.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != sha256:
            raise RuntimeError(f"CAS blob integrity mismatch for {sha256}")
        return raw

    def gc(self, live_hashes: set[str], *, min_temp_age_seconds: float = 60.0) -> dict:
        """Remove unreferenced CAS blobs while preserving any hash in `live_hashes`."""
        removed_blobs = 0
        reclaimed_bytes = 0
        now = time.time()
        if not self.root.is_dir():
            return {"removed_blobs": 0, "reclaimed_bytes": 0}
        for path in list(self.root.rglob("*")):
            if not path.is_file():
                continue
            name = path.name
            if name.endswith(".tmp"):
                try:
                    if now - path.stat().st_mtime >= min_temp_age_seconds:
                        path.unlink(missing_ok=True)
                except OSError:
                    pass
                continue
            if not _SHA256_RE.fullmatch(name):
                continue
            if name not in live_hashes:
                try:
                    nbytes = path.stat().st_size
                    path.unlink(missing_ok=True)
                    removed_blobs += 1
                    reclaimed_bytes += nbytes
                except OSError:
                    pass
        return {"removed_blobs": removed_blobs, "reclaimed_bytes": reclaimed_bytes}

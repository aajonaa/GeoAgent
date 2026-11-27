"""Git-first immutable release staging, atomic symlink switching, and instant rollback.

Replaces in-place mutable file overwriting (which could not safely add, rename,
or delete files across releases) with an immutable directory + atomic symlink
layout:

    <deploy_root>/
      releases/<release_id>/       # Full immutable tree + .release_manifest.json
      current -> releases/<id>     # Atomically swapped via tmp symlink + os.replace
      previous -> releases/<prev>  # Instant O(1) rollback target
      release-ledger.json          # Append-only deployment & rollback audit ledger
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import uuid

MANIFEST_NAME = ".release_manifest.json"
LEDGER_NAME = "release-ledger.json"
DEFAULT_EXCLUDES = frozenset({
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", "node_modules", ".DS_Store",
})


class ReleaseError(RuntimeError):
    pass


class ReleaseDrainError(ReleaseError):
    pass


class ReleaseActivationError(ReleaseError):
    def __init__(self, message: str, *, rolled_back: bool, rollback_target: str | None = None):
        super().__init__(message)
        self.rolled_back = rolled_back
        self.rollback_target = rollback_target


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _should_exclude(rel_parts: tuple[str, ...], excludes: frozenset[str]) -> bool:
    for part in rel_parts:
        if part in excludes or part.endswith(".pyc"):
            return True
    return False


def compute_tree_digest(source_root: str | Path, *, excludes: frozenset[str] = DEFAULT_EXCLUDES) -> tuple[str, dict[str, str]]:
    """Compute deterministic tree SHA-256 and `{rel_posix: file_sha256}` manifest."""
    root = Path(source_root).resolve()
    if not root.is_dir():
        raise ReleaseError(f"Source directory does not exist: {root}")
    manifest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if rel.name == MANIFEST_NAME or _should_exclude(rel.parts, excludes):
            continue
        if path.is_symlink():
            raise ReleaseError(f"Refusing to package unmanaged symlink in release source: {rel.as_posix()}")
        if path.is_file():
            manifest[rel.as_posix()] = _file_sha256(path)
    if not manifest:
        raise ReleaseError("Refusing to stage an empty release source directory")
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest(), manifest


def _detect_git_sha(source_root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        sha = proc.stdout.strip()
        if proc.returncode == 0 and len(sha) == 40:
            return sha
    except Exception:
        pass
    return None


def _make_readonly(tree: Path) -> None:
    if os.name == "nt":
        return
    for dirpath, _, filenames in os.walk(tree, topdown=False):
        for name in filenames:
            p = Path(dirpath) / name
            mode = p.stat().st_mode
            p.chmod(mode & ~0o222)
        d = Path(dirpath)
        d.chmod(d.stat().st_mode & ~0o222)


def _make_writable_tree(tree: Path) -> None:
    if os.name == "nt":
        for p in tree.rglob("*"):
            try:
                p.chmod(stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass
        return
    for dirpath, _, filenames in os.walk(tree):
        os.chmod(dirpath, os.stat(dirpath).st_mode | 0o700)
        for name in filenames:
            p = os.path.join(dirpath, name)
            if not os.path.islink(p):
                os.chmod(p, os.stat(p).st_mode | 0o200)


def _read_link_target(link_path: Path) -> Path | None:
    """Resolve `current` / `previous` pointer (POSIX symlink or cross-platform pointer file)."""
    if link_path.is_symlink():
        return link_path.resolve()
    pointer = link_path.with_suffix(".release-ptr")
    if pointer.is_file():
        target = Path(pointer.read_text(encoding="utf-8").strip())
        return target.resolve() if target.exists() else None
    return None


def _atomic_switch_pointer(link_path: Path, target_dir: Path) -> str:
    """Atomically switch `link_path` to `target_dir` using tmp symlink + os.replace on POSIX."""
    link_path.parent.mkdir(parents=True, exist_ok=True)
    target_dir = target_dir.resolve()
    rel_target = os.path.relpath(target_dir, link_path.parent)
    if os.name != "nt":
        tmp_link = link_path.parent / f".{link_path.name}.{uuid.uuid4().hex}.tmp"
        try:
            os.symlink(rel_target, tmp_link)
            os.replace(tmp_link, link_path)
            return "symlink"
        finally:
            if tmp_link.is_symlink() or tmp_link.exists():
                tmp_link.unlink(missing_ok=True)
    # Windows without Developer Mode may forbid symlinks; try symlink first, then atomic pointer file.
    tmp_link = link_path.parent / f".{link_path.name}.{uuid.uuid4().hex}.tmp"
    try:
        os.symlink(str(target_dir), tmp_link, target_is_directory=True)
        os.replace(tmp_link, link_path)
        return "symlink"
    except OSError:
        if tmp_link.is_symlink() or tmp_link.exists():
            tmp_link.unlink(missing_ok=True)
        pointer = link_path.with_suffix(".release-ptr")
        tmp_ptr = link_path.parent / f".{pointer.name}.{uuid.uuid4().hex}.tmp"
        tmp_ptr.write_text(str(target_dir), encoding="utf-8")
        os.replace(tmp_ptr, pointer)
        return "pointer_file"


def _append_ledger(deploy_root: Path, entry: dict) -> None:
    ledger_path = deploy_root / LEDGER_NAME
    if ledger_path.is_file():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    else:
        ledger = {"schema": 1, "entries": []}
    ledger.setdefault("entries", []).append(entry)
    tmp = deploy_root / f".{LEDGER_NAME}.{uuid.uuid4().hex}.tmp"
    tmp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, ledger_path)


def stage_release(
    deploy_root: str | Path,
    source_root: str | Path,
    *,
    version: str,
    notes: str = "",
    git_sha: str | None = None,
    release_id: str | None = None,
    excludes: frozenset[str] = DEFAULT_EXCLUDES,
) -> dict:
    """Stage a full immutable release directory from `source_root` and verify its SHA-256 manifest."""
    deploy = Path(deploy_root).resolve()
    source = Path(source_root).resolve()
    releases_dir = deploy / "releases"
    releases_dir.mkdir(parents=True, exist_ok=True)

    tree_sha, manifest = compute_tree_digest(source, excludes=excludes)
    resolved_git_sha = git_sha or _detect_git_sha(source) or "unknown"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rid = release_id or f"{ts}-{tree_sha[:12]}"
    if not rid or "/" in rid or "\\" in rid or ".." in rid:
        raise ReleaseError(f"Invalid release_id: {rid!r}")

    final_dir = releases_dir / rid
    if final_dir.exists():
        raise ReleaseError(f"Release directory already exists: {final_dir}")

    staging_dir = releases_dir / f".staging-{rid}-{uuid.uuid4().hex[:8]}"
    staging_dir.mkdir(parents=True, exist_ok=False)
    try:
        for rel_posix in manifest:
            src_file = source / rel_posix
            dst_file = staging_dir / rel_posix
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)

        staged_sha, staged_manifest = compute_tree_digest(staging_dir, excludes=frozenset())
        if staged_sha != tree_sha or staged_manifest != manifest:
            raise ReleaseError("Staged release hash verification failed")

        meta = {
            "schema": 1,
            "release_id": rid,
            "version": version,
            "notes": notes,
            "git_sha": resolved_git_sha,
            "source_sha256": tree_sha,
            "build": tree_sha[:12],
            "file_count": len(manifest),
            "staged_at": _utc_now(),
            "files": manifest,
        }
        (staging_dir / MANIFEST_NAME).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        _make_readonly(staging_dir)
        os.replace(staging_dir, final_dir)
        return {k: v for k, v in meta.items() if k != "files"}
    except BaseException:
        if staging_dir.exists():
            _make_writable_tree(staging_dir)
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise


def verify_release(release_dir: str | Path) -> dict:
    """Verify every file in a staged release directory matches `.release_manifest.json`."""
    rdir = Path(release_dir).resolve()
    manifest_path = rdir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ReleaseError(f"Missing release manifest in {rdir}")
    meta = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_files = meta.get("files")
    if not isinstance(expected_files, dict):
        raise ReleaseError("Invalid release manifest files map")
    actual_sha, actual_files = compute_tree_digest(rdir, excludes=frozenset())
    if actual_sha != meta.get("source_sha256") or actual_files != expected_files:
        missing = sorted(set(expected_files) - set(actual_files))
        extra = sorted(set(actual_files) - set(expected_files))
        changed = sorted(k for k in set(expected_files) & set(actual_files) if expected_files[k] != actual_files[k])
        raise ReleaseError(
            f"Release integrity check failed (missing={len(missing)}, extra={len(extra)}, changed={len(changed)})"
        )
    return {k: v for k, v in meta.items() if k != "files"}


def prune_releases(deploy_root: str | Path, *, keep_releases: int = 5) -> list[str]:
    """Prune oldest non-active releases while preserving `current`, `previous`, and `keep_releases` newest."""
    deploy = Path(deploy_root).resolve()
    releases_dir = deploy / "releases"
    if not releases_dir.is_dir() or keep_releases < 1:
        return []
    protected = set()
    for name in ("current", "previous"):
        target = _read_link_target(deploy / name)
        if target is not None:
            protected.add(target.name)
    candidates = sorted(
        [p for p in releases_dir.iterdir() if p.is_dir() and not p.name.startswith(".")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed = []
    for old in candidates[keep_releases:]:
        if old.name in protected:
            continue
        _make_writable_tree(old)
        shutil.rmtree(old)
        removed.append(old.name)
    return removed


def activate_release(
    deploy_root: str | Path,
    release_id: str,
    *,
    drain_check=None,
    health_check=None,
    keep_releases: int = 5,
    allow_same: bool = False,
) -> dict:
    """Atomically switch `current` to `release_id` with drain guard and automatic rollback on failed health check."""
    deploy = Path(deploy_root).resolve()
    target_dir = (deploy / "releases" / release_id).resolve()
    if not target_dir.is_dir():
        raise ReleaseError(f"Staged release not found: {release_id}")

    meta = verify_release(target_dir)
    current_link = deploy / "current"
    previous_link = deploy / "previous"
    prior_target = _read_link_target(current_link)
    if prior_target == target_dir and not allow_same:
        raise ReleaseError(f"Release {release_id} is already active")

    if drain_check is not None:
        drained = drain_check()
        if drained is False:
            raise ReleaseDrainError("Active tasks remain running; aborting release switch before modifying current")

    switch_mode = _atomic_switch_pointer(current_link, target_dir)

    if health_check is not None:
        healthy = False
        error_detail = ""
        try:
            healthy = bool(health_check(target_dir, meta))
            if not healthy:
                error_detail = "Health check returned unhealthy"
        except Exception as exc:
            error_detail = f"{type(exc).__name__}: {exc}"
        if not healthy:
            rolled_back = False
            rollback_id = None
            if prior_target is not None and prior_target.is_dir():
                _atomic_switch_pointer(current_link, prior_target)
                rolled_back = True
                rollback_id = prior_target.name
            _append_ledger(deploy, {
                "action": "activate_failed_auto_rollback",
                "timestamp": _utc_now(),
                "release_id": release_id,
                "version": meta["version"],
                "build": meta["build"],
                "error": error_detail,
                "rolled_back": rolled_back,
                "rollback_target": rollback_id,
            })
            raise ReleaseActivationError(
                f"Release {release_id} failed post-switch health check ({error_detail}); "
                + (f"automatically rolled back to {rollback_id}" if rolled_back else "no prior release to roll back to"),
                rolled_back=rolled_back,
                rollback_target=rollback_id,
            )

    if prior_target is not None and prior_target.is_dir() and prior_target != target_dir:
        _atomic_switch_pointer(previous_link, prior_target)

    pruned = prune_releases(deploy, keep_releases=keep_releases)
    receipt = {
        "action": "activate",
        "timestamp": _utc_now(),
        "release_id": release_id,
        "version": meta["version"],
        "notes": meta["notes"],
        "git_sha": meta["git_sha"],
        "source_sha256": meta["source_sha256"],
        "build": meta["build"],
        "previous_release_id": prior_target.name if prior_target else None,
        "switch_mode": switch_mode,
        "pruned_releases": pruned,
    }
    _append_ledger(deploy, receipt)
    return receipt


def rollback_release(
    deploy_root: str | Path,
    *,
    target_release_id: str | None = None,
    health_check=None,
) -> dict:
    """Instant O(1) atomic rollback to `previous` or a specific retained release."""
    deploy = Path(deploy_root).resolve()
    current_link = deploy / "current"
    previous_link = deploy / "previous"
    current_target = _read_link_target(current_link)

    if target_release_id is not None:
        target_dir = (deploy / "releases" / target_release_id).resolve()
    else:
        target_dir = _read_link_target(previous_link)
    if target_dir is None or not target_dir.is_dir():
        raise ReleaseError("No valid rollback target release is available")

    meta = verify_release(target_dir)
    switch_mode = _atomic_switch_pointer(current_link, target_dir)
    if current_target is not None and current_target.is_dir() and current_target != target_dir:
        _atomic_switch_pointer(previous_link, current_target)

    if health_check is not None:
        if not bool(health_check(target_dir, meta)):
            raise ReleaseError(f"Rollback target {target_dir.name} failed health verification")

    receipt = {
        "action": "rollback",
        "timestamp": _utc_now(),
        "release_id": target_dir.name,
        "version": meta["version"],
        "build": meta["build"],
        "source_sha256": meta["source_sha256"],
        "rolled_back_from": current_target.name if current_target else None,
        "switch_mode": switch_mode,
    }
    _append_ledger(deploy, receipt)
    return receipt


def release_status(deploy_root: str | Path) -> dict:
    deploy = Path(deploy_root).resolve()
    cur = _read_link_target(deploy / "current")
    prev = _read_link_target(deploy / "previous")
    releases_dir = deploy / "releases"
    retained = sorted(p.name for p in releases_dir.iterdir() if p.is_dir() and not p.name.startswith(".")) if releases_dir.is_dir() else []
    ledger_path = deploy / LEDGER_NAME
    entries = json.loads(ledger_path.read_text(encoding="utf-8")).get("entries", []) if ledger_path.is_file() else []
    cur_meta = json.loads((cur / MANIFEST_NAME).read_text(encoding="utf-8")) if (cur and (cur / MANIFEST_NAME).is_file()) else None
    return {
        "current": cur.name if cur else None,
        "current_version": cur_meta.get("version") if cur_meta else None,
        "current_build": cur_meta.get("build") if cur_meta else None,
        "previous": prev.name if prev else None,
        "retained_releases": retained,
        "ledger_entries": len(entries),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Git-first immutable release and atomic rollback manager")
    parser.add_argument("--deploy-root", required=True, help="Root deployment directory holding releases/, current, previous")
    sub = parser.add_subparsers(dest="command", required=True)

    p_stage = sub.add_parser("stage")
    p_stage.add_argument("--source", required=True)
    p_stage.add_argument("--version", required=True)
    p_stage.add_argument("--notes", default="")
    p_stage.add_argument("--git-sha", default=None)
    p_stage.add_argument("--release-id", default=None)

    p_verify = sub.add_parser("verify")
    p_verify.add_argument("--release-id", required=True)

    p_activate = sub.add_parser("activate")
    p_activate.add_argument("--release-id", required=True)
    p_activate.add_argument("--keep", type=int, default=5)

    p_rollback = sub.add_parser("rollback")
    p_rollback.add_argument("--release-id", default=None)

    sub.add_parser("status")

    args = parser.parse_args(argv)
    if args.command == "stage":
        out = stage_release(args.deploy_root, args.source, version=args.version, notes=args.notes, git_sha=args.git_sha, release_id=args.release_id)
    elif args.command == "verify":
        out = verify_release(Path(args.deploy_root) / "releases" / args.release_id)
    elif args.command == "activate":
        out = activate_release(args.deploy_root, args.release_id, keep_releases=args.keep)
    elif args.command == "rollback":
        out = rollback_release(args.deploy_root, target_release_id=args.release_id)
    else:
        out = release_status(args.deploy_root)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

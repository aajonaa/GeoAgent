"""Strict Linux bubblewrap (bwrap) sandbox command builder and isolation self-probe.

Shared by `execute_python` (for both TrustedLocalRunner workers and direct runs)
and `SandboxRunner` (per-ToolCall isolation). Enforces user/PID/network/IPC/UTS
namespace isolation, `--cap-drop ALL`, `--clearenv`, read-only Python runtime
mounts, and `/work`-only read-write workspace binding.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

BWRAP_ENV_KEYS = ("GEOTOOL_SANDBOX_BWRAP", "GEOTOOL_TRUSTED_PROCESS_BWRAP")
PYTHON_SANDBOX_MODES = ("auto", "bwrap", "required", "off")
SYSTEM_RO_MOUNTS = ("/usr", "/bin", "/lib", "/lib64", "/etc/alternatives")
FORBIDDEN_RO_ROOTS = frozenset(Path(p) for p in ("/", "/data", "/home", "/run", "/etc", "/var", "/tmp", "/proc", "/dev"))


def resolve_bwrap(explicit: str | Path | None = None) -> Path | None:
    """Return an inspected absolute bwrap binary path if configured, else None."""
    candidates: list[str | Path] = []
    if explicit is not None:
        candidates.append(explicit)
    else:
        for key in BWRAP_ENV_KEYS:
            value = os.environ.get(key, "").strip()
            if value:
                candidates.append(value)
    for raw in candidates:
        path = Path(raw)
        if path.is_absolute() and path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def python_sandbox_mode(explicit: str | None = None) -> str:
    """Resolve `GEOTOOL_PYTHON_SANDBOX` mode: auto | bwrap | required | off."""
    raw = (explicit if explicit is not None else os.environ.get("GEOTOOL_PYTHON_SANDBOX", "auto")).strip().lower()
    if raw not in PYTHON_SANDBOX_MODES:
        raise ValueError(
            f"GEOTOOL_PYTHON_SANDBOX must be one of {', '.join(PYTHON_SANDBOX_MODES)}, got {raw!r}"
        )
    return raw


def _existing_system_mounts() -> tuple[Path, ...]:
    return tuple(Path(p) for p in SYSTEM_RO_MOUNTS if Path(p).exists())


def _is_under_system_mount(path: Path, system_mounts: tuple[Path, ...]) -> bool:
    for base in system_mounts:
        try:
            if path == base or path.is_relative_to(base):
                return True
        except ValueError:
            continue
    return False


def collect_python_runtime_roots(
    python_executable: str | Path | None = None,
    *,
    extra_readonly: tuple[str | Path, ...] | list[str | Path] = (),
) -> list[Path]:
    """Collect deduplicated read-only roots needed for Python (including symlinked venvs)."""
    py = Path(python_executable or sys.executable)
    candidates: list[Path] = []
    for raw in (
        Path(sys.prefix),
        Path(sys.prefix).resolve(),
        Path(sys.base_prefix),
        Path(sys.base_prefix).resolve(),
        Path(sys.exec_prefix),
        Path(sys.exec_prefix).resolve(),
    ):
        candidates.append(raw)
    # Include both the venv layout (unresolved) and real interpreter prefix (resolved)
    # so symlinked venv binaries (e.g. venv/bin/python -> python312/bin/python3.12) work.
    if py.is_absolute():
        if len(py.parents) >= 2:
            candidates.append(py.parents[1])
        resolved_py = py.resolve()
        if len(resolved_py.parents) >= 2:
            candidates.append(resolved_py.parents[1])
    # Also include read-only site-packages / dist-packages directories wired via
    # .pth files in layered virtualenvs (never arbitrary working/app directories).
    for entry in sys.path:
        if not entry:
            continue
        sp = Path(entry)
        if sp.is_absolute() and sp.name in ("site-packages", "dist-packages") and sp.is_dir():
            candidates.append(sp.resolve())
    system_mounts = _existing_system_mounts()
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if not path.is_absolute() or not path.is_dir():
            continue
        if _is_under_system_mount(path, system_mounts):
            continue
        if path in FORBIDDEN_RO_ROOTS:
            continue
        if path not in seen:
            seen.add(path)
            unique.append(path)

    # Sort shortest-path-first and drop any auto-discovered root already covered by an included ancestor.
    unique.sort(key=lambda p: (len(p.parts), str(p)))
    pruned: list[Path] = []
    for path in unique:
        if any(path.is_relative_to(existing) for existing in pruned):
            continue
        pruned.append(path)

    # Explicit caller-supplied readonly roots are NEVER silently dropped so that
    # invalid/broad mounts fail closed in validate_readonly_roots().
    for item in extra_readonly:
        if not item:
            continue
        raw_path = Path(item)
        resolved = raw_path.resolve() if raw_path.exists() else raw_path
        if resolved in FORBIDDEN_RO_ROOTS or raw_path in FORBIDDEN_RO_ROOTS or not raw_path.is_absolute() or not resolved.is_dir():
            if raw_path not in pruned:
                pruned.append(raw_path)
            continue
        if _is_under_system_mount(resolved, system_mounts):
            continue
        if any(resolved.is_relative_to(existing) for existing in pruned if existing.is_dir()):
            continue
        if resolved not in pruned:
            pruned.append(resolved)
    return pruned


def validate_readonly_roots(
    roots: list[Path] | tuple[Path, ...],
    *,
    forbidden_overlap: tuple[Path, ...] = (),
) -> list[Path]:
    """Fail-closed validation ensuring read-only mounts never expose host roots or workspace/state."""
    normalized_forbidden = [Path(p).resolve() for p in forbidden_overlap if p is not None]
    validated: list[Path] = []
    for raw in roots:
        path = Path(raw)
        if not path.is_absolute() or not path.is_dir():
            raise RuntimeError(f"Unsafe sandbox runtime mount (not an existing absolute directory): {path}")
        resolved = path.resolve()
        if path in FORBIDDEN_RO_ROOTS or resolved in FORBIDDEN_RO_ROOTS:
            raise RuntimeError(f"Unsafe sandbox runtime mount (broad host root forbidden): {path}")
        for blocked in normalized_forbidden:
            if resolved.is_relative_to(blocked) or blocked.is_relative_to(resolved):
                raise RuntimeError(f"Unsafe sandbox runtime mount overlaps protected path: {path}")
        validated.append(path)
    return validated


def build_bwrap_command(
    bwrap_path: str | Path,
    workspace: str | Path,
    command: list[str] | tuple[str, ...],
    *,
    readonly_roots: list[Path] | tuple[Path, ...] = (),
    forbidden_overlap: tuple[Path, ...] = (),
    env: dict[str, str] | None = None,
    chdir: str = "/work",
    unshare_cgroup: bool = False,
) -> list[str]:
    """Build a strict namespace-isolated bubblewrap argv for untrusted code or tools."""
    if sys.platform != "linux":
        raise RuntimeError("Bubblewrap sandbox requires Linux")
    bwrap = Path(bwrap_path)
    if not bwrap.is_absolute() or not bwrap.is_file():
        raise RuntimeError("An inspected absolute bubblewrap executable is required")
    work = Path(workspace).resolve()
    if not work.is_dir():
        raise RuntimeError("Sandbox workspace directory does not exist")

    roots = validate_readonly_roots(
        list(readonly_roots),
        forbidden_overlap=(work, *forbidden_overlap),
    )

    argv: list[str] = [
        str(bwrap),
        "--unshare-user",
        "--uid", str(os.getuid()),
        "--gid", str(os.getgid()),
        "--unshare-pid",
        "--unshare-net",
        "--unshare-ipc",
        "--unshare-uts",
        "--cap-drop", "ALL",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
    ]
    if unshare_cgroup:
        argv.append("--unshare-cgroup")

    for sys_dir in _existing_system_mounts():
        argv += ["--ro-bind", str(sys_dir), str(sys_dir)]
    for root in roots:
        argv += ["--ro-bind", str(root), str(root)]

    argv += [
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--bind", str(work), "/work",
        "--chdir", chdir,
    ]

    clean_env = {
        "HOME": "/work",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if env:
        clean_env.update({str(k): str(v) for k, v in env.items()})
    for key, value in sorted(clean_env.items()):
        argv += ["--setenv", key, value]

    argv += ["--", *[str(arg) for arg in command]]
    return argv


def verify_sandbox_isolation(
    bwrap_path: str | Path,
    workspace: str | Path,
    *,
    python_executable: str | Path | None = None,
    probe_hidden_paths: tuple[str, ...] = (),
    probe_ports: tuple[int, ...] = (50018,),
    timeout: float = 10.0,
) -> dict:
    """Run a live self-probe inside strict bwrap to verify namespace, fs, env, and net isolation."""
    py = str(python_executable or sys.executable)
    roots = collect_python_runtime_roots(py)
    probe_code = (
        "import json, os, socket, sys\n"
        "hidden = json.loads(sys.argv[1])\n"
        "ports = json.loads(sys.argv[2])\n"
        "def can_connect(host, port):\n"
        "    s = socket.socket()\n"
        "    s.settimeout(0.5)\n"
        "    try:\n"
        "        s.connect((host, port))\n"
        "        return True\n"
        "    except OSError:\n"
        "        return False\n"
        "    finally:\n"
        "        s.close()\n"
        "can_write = False\n"
        "try:\n"
        "    with open('/work/.sandbox_probe', 'w', encoding='utf-8') as f:\n"
        "        f.write('ok')\n"
        "    os.unlink('/work/.sandbox_probe')\n"
        "    can_write = True\n"
        "except OSError:\n"
        "    can_write = False\n"
        "print(json.dumps({\n"
        "    'pid': os.getpid(),\n"
        "    'cwd': os.getcwd(),\n"
        "    'can_write_work': can_write,\n"
        "    'hidden_paths_blocked': all(not os.path.exists(p) for p in hidden),\n"
        "    'external_net_blocked': not can_connect('1.1.1.1', 443),\n"
        "    'loopback_ports_blocked': all(not can_connect('127.0.0.1', p) for p in ports),\n"
        "    'env_keys': sorted(os.environ.keys()),\n"
        "}))\n"
    )
    argv = build_bwrap_command(
        bwrap_path,
        workspace,
        [py, "-I", "-c", probe_code, json.dumps(list(probe_hidden_paths)), json.dumps(list(probe_ports))],
        readonly_roots=roots,
        env={"PATH": str(Path(py).parent) + ":/usr/bin:/bin"},
    )
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    if proc.returncode != 0:
        return {"ok": False, "returncode": proc.returncode, "stderr": proc.stderr.strip()}
    payload = json.loads(proc.stdout.strip())
    secret_words = ("KEY", "TOKEN", "SECRET", "PASSWORD", "DSN", "AUTHORIZATION")
    env_clean = not any(any(w in k.upper() for w in secret_words) for k in payload["env_keys"])
    payload["pid_isolated"] = payload["pid"] <= 2
    payload["env_clean"] = env_clean
    payload["ok"] = bool(
        payload["pid_isolated"]
        and payload["cwd"] == "/work"
        and payload["can_write_work"]
        and payload["hidden_paths_blocked"]
        and payload["external_net_blocked"]
        and payload["loopback_ports_blocked"]
        and payload["env_clean"]
    )
    return payload

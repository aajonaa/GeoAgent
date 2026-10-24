"""Release the tested mineral tools without replacing unrelated live changes.

Run on the application host. Browser acceptance is deliberately not performed or
claimed here. The retained environment file is private and must not be published.
"""
import argparse
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import traceback
from pathlib import Path

os.environ.update(CUDA_VISIBLE_DEVICES="", NVIDIA_VISIBLE_DEVICES="none",
                  PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
sys.dont_write_bytecode = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--extra-deps", type=Path, required=True)
    parser.add_argument("--expected-pid", type=int, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--flow-module", type=Path, required=True)
    args = parser.parse_args()
    base = Path("/data/wangjian")
    root = args.root.resolve()
    app = root / "app"
    record = root / "deployment-r1"
    record.mkdir(mode=0o700, exist_ok=False)
    unit = "geotoolagent-hitl-candidate.service"
    dropin = base / ".config/systemd/user" / (unit + ".d") / "50-github-minerals-20261025.conf"
    python = base / "earth-python-coverage101-imports-20261022/venv/bin/python"
    serve = base / "geoagent-recovery-20261003-r2/serve.py"
    launcher = record / "launch.py"
    private_env = record / "environment.private.json"
    state = {"switched": False}

    def run(command, **kwargs):
        return subprocess.run(command, check=True, text=True, capture_output=True, **kwargs)

    def read(path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def sha(path):
        h = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()

    def write(name, value):
        with (record / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=True, sort_keys=True, indent=2)

    def pid():
        return int(run(["systemctl", "--user", "show", unit, "-p", "MainPID", "--value"]).stdout.strip())

    def proc_env(process):
        return dict(item.split("=", 1) for item in Path(f"/proc/{process}/environ").read_text().split("\0") if "=" in item)

    def saved_state():
        db = base / "geotoolagent-hitl-state-20260930-r1/team.sqlite3"
        with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
            result = {}
            for table in ("users", "model_profiles"):
                rows = list(conn.execute("SELECT rowid,* FROM " + table + " ORDER BY rowid"))
                raw = json.dumps(rows, ensure_ascii=True, default=lambda b: {"hex": b.hex()}, separators=(",", ":")).encode()
                result[table] = {"count": len(rows), "sha256": hashlib.sha256(raw).hexdigest()}
            result["paused_runs"] = conn.execute("SELECT count(*) FROM runs WHERE status='needs_input'").fetchone()[0]
            result["active_runs"] = conn.execute("SELECT count(*) FROM runs WHERE status in ('queued','running','starting','pending')").fetchone()[0]
        return result

    def other_services():
        names = ("geogpt-awq-single-gpu1.service", "geoagent-qwen-retrieval-side.service",
                 "acaagent.service", "geoagent-project-board.service", "geotoolagent-knowledge-encoder.service")
        return {name: run(["systemctl", "--user", "show", name, "-p", "MainPID", "-p", "ActiveState", "-p", "ActiveEnterTimestampMonotonic"]).stdout for name in names}

    def check_runtime(environment):
        env = dict(environment)
        env.update(LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false", GEOTOOL_LANGSMITH_ENABLED="0")
        code = '''import os,json,importlib.metadata as m
import psycopg
from geological_agent.context_store import private_dsn
from geological_agent.bootstrap import build_registry
from geological_agent.team.library import LibraryCatalog
from geological_agent.team import server
from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog,ROOT
with psycopg.connect(private_dsn(os.environ["GEOTOOL_CONTEXT_DSN_FILE"]),autocommit=True) as connection:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone()==(1,)
registry,skills,base=build_registry(human_input=True)
counts=LibraryCatalog(human_input=True).summary()["counts"]
assert counts["professional_tools"]==229 and counts["skills"]==50
assert len(catalog()["tools"])==229 and len(catalog()["skills"])==50
assert not skills.unavailable_skills
for name,version in {"spectral":"0.25","pyrolite":"0.3.7","mplstereonet":"0.6.3","pandas":"2.3.0","numpy":"2.1.3"}.items():
    assert m.version(name)==version,(name,m.version(name))
print(json.dumps({"server_source":server.__file__,"catalog_root":str(ROOT),"counts":counts,
 "registered_tools_total":len(registry.names()),"unavailable_skills":len(skills.unavailable_skills),"postgres_select_1":True}))
'''
        result = run([str(python), "-c", code], env=env, cwd=app)
        info = json.loads(result.stdout)
        assert info["server_source"] == str(app / "geological_agent/team/server.py")
        assert info["catalog_root"] == str(app)
        return info

    sys.path.insert(0, str(args.flow_module.resolve().parent))
    from flowing import Flow, task

    @task
    def preflight():
        gate = read(root / "acceptance.json")
        assert gate["state"] == "passed" and gate["passed"] == 292
        assert gate["failed"] == gate["skipped"] == 0
        assert gate["native_professional_operations"] == 229
        assert len(gate["cases"]) == 292
        assert pid() == args.expected_pid, "Live baseline changed; refusing switch"
        oldenv = proc_env(args.expected_pid)
        assert oldenv["PYTHONPATH"].split(":")[0] == str(args.baseline)
        assert not dropin.exists(), "Existing service override must not be replaced"
        manifest = read(args.source_manifest)
        for name, digest in manifest.items():
            relative = Path(name)
            assert not relative.is_absolute() and ".." not in relative.parts
            assert sha(app / relative) == digest, name
        for name, digest in gate["source_sha256"].items():
            assert sha(app / name) == digest, name
        preserved = {}
        for folder in ("geological_agent", "geotool", "legacy", "catalog", "assets"):
            for source in (args.baseline / folder).rglob("*"):
                if "__pycache__" in source.parts or not source.is_file():
                    continue
                relative = source.relative_to(args.baseline).as_posix()
                if relative in manifest:
                    continue
                digest = sha(source)
                assert sha(app / relative) == digest, "Unrelated live file changed: " + relative
                preserved[relative] = digest
        state["saved"] = saved_state()
        assert state["saved"]["active_runs"] == 0, "Foreground task active; no restart"
        state["services"] = other_services()
        state["old_env_hash"] = hashlib.sha256(json.dumps(oldenv, sort_keys=True).encode()).hexdigest()
        env = dict(oldenv)
        env.update(CUDA_VISIBLE_DEVICES="", NVIDIA_VISIBLE_DEVICES="none", PYTHONDONTWRITEBYTECODE="1",
                   PYTHONNOUSERSITE="1", GEOTOOL_RELEASE="github-minerals-20261025-r3",
                   GEOTOOL_TOOLS_SOURCE_COMMIT=args.source_commit,
                   MPLCONFIGDIR=str(root / "runtime-cache/matplotlib"), XDG_CACHE_HOME=str(root / "runtime-cache/xdg"))
        env["PYTHONPATH"] = ":".join((str(app), str(root / "deps"), str(args.extra_deps), str(base / "geotoolagent-context-postgres/python")))
        for key in ("MPLCONFIGDIR", "XDG_CACHE_HOME"):
            Path(env[key]).mkdir(parents=True, exist_ok=True)
        state["environment"] = env
        info = check_runtime(env)
        write("PREFLIGHT.json", {"status": "passed", "runtime": info, "source_commit": args.source_commit,
                                "preserved_live_files": preserved, "saved_state_hashes": state["saved"],
                                "manifest_sha256": sha(args.source_manifest), "acceptance_sha256": sha(root / "acceptance.json")})
        return {"passed": True}

    def checked(preflight):
        assert preflight["passed"] is True

    @task(depends_on=[preflight], validate=checked)
    def switch(preflight):
        assert pid() == args.expected_pid and saved_state()["active_runs"] == 0
        current = hashlib.sha256(json.dumps(proc_env(args.expected_pid), sort_keys=True).encode()).hexdigest()
        assert current == state["old_env_hash"], "Live environment changed"
        fd = os.open(private_env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state["environment"], stream)
        launch = ("import json,os\nfrom pathlib import Path\n"
                  + "env=json.loads(Path(" + repr(str(private_env)) + ").read_text())\n"
                  + "os.execve(" + repr(str(python)) + "," + repr([str(python), str(serve)]) + ",env)\n")
        with launcher.open("x", encoding="utf-8") as stream:
            stream.write(launch)
        override = "[Service]\nExecStart=\nExecStart=/usr/bin/python3 " + str(launcher) + "\n"
        with dropin.open("x", encoding="utf-8") as stream:
            stream.write(override)
        state["switched"] = True
        state["override"] = override
        run(["systemctl", "--user", "daemon-reload"])
        run(["systemctl", "--user", "restart", unit])
        write("SWITCH.json", {"dropin": str(dropin), "launcher_sha256": sha(launcher), "source_commit": args.source_commit})
        return {"switched": True}

    @task(depends_on=[switch])
    def accept(switch):
        assert switch["switched"]
        deadline = time.monotonic() + 45
        ready = False
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", 50015), timeout=1):
                    ready = True
                    break
            except OSError:
                time.sleep(0.5)
        assert ready, "Application port did not become ready"
        newpid = pid()
        assert newpid and newpid != args.expected_pid
        env = proc_env(newpid)
        for key in ("PYTHONPATH", "CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES", "GEOTOOL_TOOLS_SOURCE_COMMIT", "GEOTOOL_RELEASE"):
            assert env[key] == state["environment"][key], key
        info = check_runtime(env)
        assert saved_state() == state["saved"], "Account/model/pause state changed"
        assert other_services() == state["services"], "Unrelated service changed"
        result = {"status": "deployed_backend_accepted_browser_pending", "unit": unit, "pid": newpid,
                  "app": str(app), "source_commit": args.source_commit, "runtime": info,
                  "fresh_tests_passed": 292, "native_professional_operations": 229,
                  "preserved_baseline": str(args.baseline), "other_services_unchanged": True,
                  "users_model_profiles_paused_runs_unchanged": True, "gpu_used": False,
                  "model_calls": False, "browser_validation": "blocked_by_saved_origin_permission",
                  "rollback": "Remove only " + str(dropin) + "; daemon-reload and restart " + unit}
        write("DEPLOYMENT-RESULT.json", result)
        print(json.dumps(result), flush=True)
        return result

    try:
        results = Flow(accept, max_workers=1, fail_fast=True, journal_path=str(record / "flow.jsonl")).run()
        errors = [item.error for item in results.values() if item.error is not None]
        if errors:
            raise errors[0]
    except BaseException as exc:
        write("FAILURE.json", {"error": str(exc), "traceback": traceback.format_exc(), "switched": state["switched"]})
        if state["switched"]:
            assert dropin.read_text() == state["override"], "Override changed; refusing to remove another deployment"
            dropin.unlink()
            run(["systemctl", "--user", "daemon-reload"])
            run(["systemctl", "--user", "restart", unit])
            write("ROLLBACK.json", {"previous_override_restored": True, "unit": unit})
        raise


if __name__ == "__main__":
    main()

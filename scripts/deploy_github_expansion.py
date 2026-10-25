"""Guarded CPU-only publication of the accepted 117-operation expansion."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


UNIT = "geotoolagent-hitl-candidate.service"
PYTHON = "/data/wangjian/earth-python-coverage101-imports-20261022/venv/bin/python"
SERVE = "/data/wangjian/geoagent-recovery-20261003-r2/serve.py"
DATABASE = "/data/wangjian/geotoolagent-hitl-state-20260930-r1/team.sqlite3"
FLOW = "/data/wangjian/earth-python-coverage101-offline-originals-20261022/u13-parent-r3/flowing.py"
OTHER_UNITS = (
    "geogpt-awq-single-gpu1.service", "geoagent-qwen-retrieval-side.service",
    "acaagent.service", "geoagent-project-board.service",
    "geotoolagent-knowledge-encoder.service",
)


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def main_pid():
    return int(command("systemctl", "--user", "show", UNIT, "--property=MainPID", "--value"))


def process_environment(pid):
    raw = Path("/proc", str(pid), "environ").read_bytes()
    env = dict(item.split("=", 1) for item in raw.decode().split("\0") if "=" in item)
    return env, hashlib.sha256(raw).hexdigest()


def saved_state():
    terminal = {"completed", "failed", "needs_input", "stopped", "budget_exhausted",
                "incomplete", "cancelled", "canceled", "paused"}
    with sqlite3.connect("file:" + DATABASE + "?mode=ro", uri=True) as db:
        states = dict(db.execute("SELECT status,count(*) FROM runs GROUP BY status"))
        result = {"active_runs": sum(n for state, n in states.items() if state not in terminal)}
        for table in ("users", "model_profiles"):
            rows = list(db.execute("SELECT * FROM " + table + " ORDER BY rowid"))
            encoded = json.dumps(rows, ensure_ascii=False, default=lambda x: x.hex()).encode()
            result[table + "_sha256"] = hashlib.sha256(encoded).hexdigest()
        for table in ("conversations", "files"):
            result[table + "_count"] = db.execute("SELECT count(*) FROM " + table).fetchone()[0]
        result["paused_runs"] = states.get("needs_input", 0)
    return result


def other_services():
    return {unit: command("systemctl", "--user", "show", unit,
                          "--property=MainPID,ActiveState,ActiveEnterTimestampMonotonic")
            for unit in OTHER_UNITS}


def runtime_check(env, app):
    probe_env = dict(env, LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false",
                     PYTHONDONTWRITEBYTECODE="1")
    code = '''
import json
from pathlib import Path
import psycopg
from geological_agent.context_store import private_dsn
from geological_agent.bootstrap import build_registry
from geological_agent.team.library import LibraryCatalog
from geological_agent.team import server
import os
with psycopg.connect(private_dsn(os.environ["GEOTOOL_CONTEXT_DSN_FILE"]), autocommit=True) as connection:
    assert connection.execute("SELECT 1").fetchone()[0] == 1
registry, skills, base = build_registry(human_input=True)
counts = LibraryCatalog(human_input=True).summary()["counts"]
assert counts["professional_tools"] == 346 and counts["skills"] == 70, counts
assert counts["registered_tools"] == 358 and counts["runtime_tools"] == 12, counts
assert not skills.unavailable_skills, skills.unavailable_skills
print(json.dumps({"counts":counts,"server_source":str(Path(server.__file__).resolve()),
 "registered_total":len(registry.names()),"unavailable_skills":0,"postgres_select_1":True}))
'''
    process = subprocess.run([PYTHON, "-c", code], cwd=app, env=probe_env,
                             text=True, capture_output=True)
    if process.returncode:
        raise RuntimeError("Runtime preflight failed; exit=" + str(process.returncode)
                           + "; " + process.stderr[-3000:])
    result = json.loads(process.stdout.strip().splitlines()[-1])
    if result["server_source"] != str(app / "geological_agent/team/server.py"):
        raise RuntimeError("Runtime imported a different application")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--expected-pid", type=int, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        raise ValueError("An exact source commit is required")
    root = Path(args.root).resolve(strict=True)
    app = (root / "app").resolve(strict=True)
    app.relative_to(root)
    baseline = Path(args.baseline).resolve(strict=True)
    record = root / "deployment-r1"
    record.mkdir(mode=0o700)
    dropin = Path("/data/wangjian/.config/systemd/user", UNIT + ".d",
                  "60-github-expansion346-20261025.conf")
    manifest = read_json(root / "source-manifest.json")
    import_rows = read_json(root / "import-manifest.json")
    changed = {row["path"] for row in import_rows}
    state = {"switched": False}
    spec = importlib.util.spec_from_file_location("flowing", FLOW)
    module = importlib.util.module_from_spec(spec)
    sys.modules["flowing"] = module
    spec.loader.exec_module(module)
    Flow, task = module.Flow, module.task

    def verify_sources():
        for row in import_rows:
            old = baseline / row["path"]
            if row["old_sha256"] is not None:
                if not old.is_file() or sha(old) != row["old_sha256"]:
                    raise RuntimeError("Changed live input: " + row["path"])
            elif old.exists():
                raise RuntimeError("New live file conflicts with release: " + row["path"])
        for relative, expected in manifest.items():
            path = app / relative
            path.resolve(strict=True).relative_to(app)
            if sha(path) != expected:
                raise RuntimeError("Release source changed: " + relative)
            old = baseline / relative
            if relative not in changed and old.is_file() and sha(old) != expected:
                raise RuntimeError("Live baseline changed: " + relative)

    @task
    def preflight():
        suites = {name: read_json(root / "reports/cpu-acceptance" / (name + ".json"))
                  for name in ("contracts", "geophysics", "remote", "geology", "spatial", "native-new", "baseline229")}
        expected = {"contracts":237, "geophysics":5, "remote":15, "geology":89,
                    "spatial":44, "native-new":117, "baseline229":244}
        for name, report in suites.items():
            if not (report["accepted"] and report["return_code"] == 0
                    and report["passed_cases"] == expected[name]
                    and report["junit_cases"] == expected[name]
                    and all(report[key] == 0 for key in ("failures", "errors", "skipped"))):
                raise RuntimeError("Formal regression gate failed: " + name)
        diagnostic = list(ET.parse(root / "reports/cpu-acceptance/blocked-stress-diagnostic.xml").getroot().iter("testcase"))
        if not (len(diagnostic) == 1 and diagnostic[0].get("name") == "test_unequal_strain_angular_integral"
                and diagnostic[0].find("skipped") is not None
                and diagnostic[0].find("skipped").get("type") == "pytest.xfail"
                and diagnostic[0].find("failure") is None and diagnostic[0].find("error") is None):
            raise RuntimeError("Historical diagnostic evidence is missing or changed")
        verify_sources()
        if main_pid() != args.expected_pid or dropin.exists():
            raise RuntimeError("Deployment baseline changed or override already exists")
        old_env, old_hash = process_environment(args.expected_pid)
        old_paths = old_env.get("PYTHONPATH", "").split(os.pathsep)
        if old_paths[0] != str(baseline):
            raise RuntimeError("Unexpected live source root")
        before = saved_state()
        if before["active_runs"]:
            raise RuntimeError("Active user tasks prevent service restart")
        others = other_services()
        env = dict(old_env)
        env.update(CUDA_VISIBLE_DEVICES="", NVIDIA_VISIBLE_DEVICES="void",
                   HIP_VISIBLE_DEVICES="", ROCR_VISIBLE_DEVICES="", PYTHONNOUSERSITE="1",
                   GEOTOOL_RELEASE=root.name, GEOTOOL_TOOLS_SOURCE_COMMIT=args.source_commit)
        env["PYTHONPATH"] = os.pathsep.join([str(app), str(root / "deps"), *old_paths[1:]])
        for key, name in (("MPLCONFIGDIR", "mpl"), ("NUMBA_CACHE_DIR", "numba"),
                          ("PYTHONPYCACHEPREFIX", "bytecode")):
            directory = record / name
            directory.mkdir()
            env[key] = str(directory)
        runtime = runtime_check(env, app)
        state.update(env=env, old_hash=old_hash, before=before, others=others)
        receipt = {"state":"preflight_passed", "source_commit":args.source_commit,
                   "formal_passed":751, "formal_failed":0, "formal_skipped":0,
                   "source_manifest_sha256":sha(root / "source-manifest.json"),
                   "previous_pid":args.expected_pid, "saved_state":before,
                   "other_services":others, "runtime":runtime, "gpu_used":False}
        write_new(record / "PREFLIGHT.json", receipt)
        return receipt

    @task(depends_on=[preflight], validate=lambda preflight: preflight["state"] == "preflight_passed")
    def switch(preflight):
        verify_sources()
        if (main_pid() != args.expected_pid or saved_state() != state["before"]
                or process_environment(args.expected_pid)[1] != state["old_hash"]
                or other_services() != state["others"]):
            raise RuntimeError("Concurrent changes prevent deployment")
        private = record / "environment.private.json"
        fd = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state["env"], stream)
        launcher = record / "launch.py"
        with launcher.open("x", encoding="utf-8") as stream:
            stream.write("import json,os\nfrom pathlib import Path\n"
                         + "env=json.loads(Path(" + repr(str(private)) + ").read_text())\n"
                         + "os.chdir(" + repr(str(app)) + ")\n"
                         + "os.execve(" + repr(PYTHON) + "," + repr([PYTHON, SERVE]) + ",env)\n")
        override = "[Service]\nExecStart=\nExecStart=/usr/bin/python3 " + str(launcher) + "\n"
        with dropin.open("x", encoding="utf-8") as stream:
            stream.write(override)
        state.update(switched=True, override=override)
        command("systemctl", "--user", "daemon-reload")
        command("systemctl", "--user", "restart", UNIT)
        return {"state":"switched", "source_commit":args.source_commit}

    @task(depends_on=[switch], validate=lambda switch: switch["state"] == "switched")
    def accept(switch):
        deadline = time.monotonic() + 45
        while True:
            try:
                with socket.create_connection(("127.0.0.1", 50015), timeout=1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("GeoAgent did not open its backend port")
                time.sleep(1)
        pid = main_pid()
        if pid == args.expected_pid or command("systemctl", "--user", "is-active", UNIT) != "active":
            raise RuntimeError("Service did not switch to a healthy process")
        actual, _ = process_environment(pid)
        for key in ("PYTHONPATH", "GEOTOOL_RELEASE", "GEOTOOL_TOOLS_SOURCE_COMMIT",
                    "CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES", "HIP_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES"):
            if actual.get(key) != state["env"].get(key):
                raise RuntimeError("Unexpected service environment key: " + key)
        runtime = runtime_check(actual, app)
        verify_sources()
        if saved_state() != state["before"] or other_services() != state["others"]:
            raise RuntimeError("Saved state or another service changed during deployment")
        receipt = {"state":"deployed_backend_accepted", "source_commit":args.source_commit,
                   "root":str(root), "pid":pid, "runtime":runtime, "formal_passed":751,
                   "formal_failed":0, "formal_skipped":0, "gpu_used":False,
                   "saved_state_preserved":True, "other_services_unchanged":True,
                   "browser_acceptance":"pending_saved_permission_denial",
                   "receiving_lab_delivery_approved":False}
        write_new(record / "DEPLOYMENT-RESULT.json", receipt)
        return receipt

    try:
        flow = Flow(accept, max_workers=1, fail_fast=True, journal_path=str(record / "flow.jsonl"))
        results = flow.run()
        for result in results.values():
            if result.error is not None:
                raise result.error
        print(json.dumps(flow.value(accept), ensure_ascii=False))
    except Exception as error:
        write_new(record / "FAILURE.json", {"error":str(error), "switched":state["switched"]})
        if state["switched"]:
            if dropin.read_text(encoding="utf-8") != state["override"]:
                raise RuntimeError("Override changed externally; automatic rollback refused") from error
            dropin.unlink()
            command("systemctl", "--user", "daemon-reload")
            command("systemctl", "--user", "restart", UNIT)
            write_new(record / "ROLLBACK.json", {"state":"previous_override_restored", "pid":main_pid()})
        raise


if __name__ == "__main__":
    main()

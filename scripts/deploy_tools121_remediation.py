"""Publish a source-bound tools121 remediation without replacing prior overrides."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--helpers", type=Path, required=True)
    parser.add_argument("--attempt", default="deployment")
    args = parser.parse_args()
    root = args.release.resolve(strict=True)
    assert root.parent == Path("/data/wangjian") and root.name.startswith("github-tools121-")
    assert re.fullmatch(r"[a-f0-9]{40}", args.source_commit)
    app = root / "app"
    receipt_path = root / "release-acceptance.json"
    acceptance_bytes = receipt_path.read_bytes()
    receipt = json.loads(acceptance_bytes)
    assert receipt["state"] == "accepted_for_internal_release"
    assert receipt["source_commit"] == args.source_commit
    assert receipt["scientific_failed_in_published_subset"] == 0
    assert receipt["runtime_failed_in_published_subset"] == 0
    assert receipt["formal_skipped_in_published_subset"] == 0
    assert receipt["gpu_used"] is False
    passed = receipt["passed_tool_ids"]
    excluded = receipt["excluded_tool_ids"]
    assert passed and len(set(passed)) == len(passed)
    assert not set(passed) & set(excluded) and len(passed) + len(excluded) == 121
    assert receipt["professional_tools"] == 346 + len(passed)
    helpers = load("release121_helpers", args.helpers)
    flowing = load("flowing", helpers.FLOW)
    task, Flow = flowing.task, flowing.Flow
    assert re.fullmatch(r"deployment(?:-r[1-9][0-9]*)?", args.attempt)
    record = root / args.attempt
    record.mkdir(exist_ok=False)
    dropin = Path.home() / ".config/systemd/user" / (helpers.UNIT + ".d") / "81-tools121-remediation-20261026.conf"
    assert not dropin.exists()
    state = {"switched": False}

    def write(name, value):
        with (record / name).open("x") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")

    def verify_sources():
        assert receipt_path.read_bytes() == acceptance_bytes, "Acceptance receipt changed"
        for relative, digest in receipt["source_files"].items():
            path = app / relative
            assert path.resolve().is_relative_to(app) and not path.is_symlink()
            assert sha(path) == digest, "Release source changed: " + relative
        old = Path(receipt["live_root"])
        for relative, digest in receipt["live_files"].items():
            path = old / relative
            assert path.resolve().is_relative_to(old) and not path.is_symlink()
            assert sha(path) == digest, "Live baseline changed: " + relative
        for evidence in receipt["evidence_files"]:
            assert sha(evidence["path"]) == evidence["sha256"], "Acceptance evidence changed"

    def unit_sources():
        paths = subprocess.check_output([
            "systemctl", "--user", "show", helpers.UNIT,
            "--property=FragmentPath,DropInPaths", "--value"], text=True).split()
        return {path: sha(path) for path in paths}

    def runtime(environment):
        code = "\n".join([
            "import json,pathlib",
            "from geological_agent.bootstrap import build_registry",
            "from geological_agent.team.library import LibraryCatalog",
            "from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog",
            "r,s,_=build_registry(human_input=True)",
            "counts=LibraryCatalog(human_input=True).summary()['counts']",
            "assert counts['professional_tools']==" + str(receipt["professional_tools"]),
            "assert counts['skills']==" + str(receipt["skills"]),
            "assert counts['registered_tools']==len(r.names())",
            "assert not s.unavailable_skills",
            "ids={t['id'] for t in catalog()['tools']}",
            "assert set(" + repr(passed) + ") <= ids",
            "assert not set(" + repr(excluded) + ") & ids",
            "import geological_agent.geology.source_registry as sr",
            "assert pathlib.Path(sr.__file__).resolve().is_relative_to(pathlib.Path(" + repr(str(app)) + "))",
            "print(json.dumps(counts))",
        ])
        result = subprocess.run([helpers.PYTHON, "-B", "-c", code], env=environment, cwd=app,
                                capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise RuntimeError("Runtime check failed: " + result.stderr[-8000:])
        return json.loads(result.stdout.strip().splitlines()[-1])

    @task
    def preflight():
        verify_sources()
        assert helpers.main_pid() == receipt["expected_live_pid"], "Live process changed"
        old_env, old_hash = helpers.process_environment(receipt["expected_live_pid"])
        assert old_env["PYTHONPATH"].split(os.pathsep)[0] == receipt["live_root"]
        before, others = helpers.saved_state(), helpers.other_services()
        assert before["active_runs"] == 0, "A user task is active; do not interrupt it"
        environment = dict(old_env)
        environment.update(CUDA_VISIBLE_DEVICES="", NVIDIA_VISIBLE_DEVICES="void",
                           HIP_VISIBLE_DEVICES="", ROCR_VISIBLE_DEVICES="",
                           GEOAGENT_EXPANSION501_GEOLOGY_CPU="expansion501-geology-cpu-v1",
                           JAX_PLATFORMS="cpu",
                           PYTHONDONTWRITEBYTECODE="1", GEOTOOL_RELEASE=root.name,
                           GEOTOOL_TOOLS_SOURCE_COMMIT=args.source_commit)
        paths = [str(app)] + receipt["dependency_paths"] + old_env["PYTHONPATH"].split(os.pathsep)[1:]
        environment["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(paths))
        for key, name in (("MPLCONFIGDIR", "mpl"), ("NUMBA_CACHE_DIR", "numba")):
            path = record / name
            path.mkdir()
            environment[key] = str(path)
        counts = runtime(environment)
        state.update(env=environment, old_hash=old_hash, before=before, others=others,
                     unit_sources=unit_sources())
        result = {"state": "ready", "counts": counts, "passed_new_tools": len(passed),
                  "excluded_new_tools": len(excluded), "gpu_used": False,
                  "saved_state": before, "protected_services": others}
        write("PREFLIGHT.json", result)
        return result

    def ready(preflight):
        assert preflight["state"] == "ready"

    @task(depends_on=[preflight], validate=ready)
    def switch(preflight):
        verify_sources()
        assert helpers.main_pid() == receipt["expected_live_pid"]
        assert helpers.process_environment(receipt["expected_live_pid"])[1] == state["old_hash"]
        assert helpers.saved_state() == state["before"]
        assert helpers.other_services() == state["others"]
        assert unit_sources() == state["unit_sources"], "Service configuration changed"
        private = record / "environment.private.json"
        fd = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(state["env"], stream)
        launcher = record / "launch.py"
        with launcher.open("x") as stream:
            stream.write("import json,os\nfrom pathlib import Path\n"
                         + "env=json.loads(Path(" + repr(str(private)) + ").read_text())\n"
                         + "os.chdir(" + repr(str(app)) + ")\n"
                         + "os.execve(" + repr(helpers.PYTHON) + ","
                         + repr([helpers.PYTHON, helpers.SERVE]) + ",env)\n")
        override = "[Service]\nExecStart=\nExecStart=/usr/bin/python3 " + str(launcher) + "\n"
        with dropin.open("x") as stream:
            stream.write(override)
        state.update(switched=True, override=override)
        helpers.command("systemctl", "--user", "daemon-reload")
        helpers.command("systemctl", "--user", "restart", helpers.UNIT)
        return {"state": "switched"}

    def switched(switch):
        assert switch["state"] == "switched"

    @task(depends_on=[switch], validate=switched)
    def accept(switch):
        deadline = time.monotonic() + 60
        while True:
            try:
                with socket.create_connection(("127.0.0.1", 50015), timeout=1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("App did not open its backend socket")
                time.sleep(1)
        pid = helpers.main_pid()
        assert pid != receipt["expected_live_pid"] and pid > 0
        assert helpers.command("systemctl", "--user", "is-active", helpers.UNIT) == "active"
        actual, _ = helpers.process_environment(pid)
        for key in ("PYTHONPATH", "CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES", "HIP_VISIBLE_DEVICES",
                    "ROCR_VISIBLE_DEVICES", "GEOTOOL_RELEASE", "GEOTOOL_TOOLS_SOURCE_COMMIT"):
            assert actual.get(key) == state["env"].get(key), key
        counts = runtime(actual)
        verify_sources()
        assert helpers.saved_state() == state["before"], "Saved user state changed"
        assert helpers.other_services() == state["others"], "Another service changed"
        result = {"state": "deployed_backend_accepted", "source_commit": args.source_commit,
                  "pid": pid, "counts": counts, "passed_new_tools": passed, "excluded_new_tools": excluded,
                  "gpu_used": False, "saved_state_preserved": True, "other_services_unchanged": True,
                  "browser_acceptance": "blocked_saved_site_permission", "ai_lab_certified": False}
        write("DEPLOYMENT-RESULT.json", result)
        return result

    try:
        flow = Flow(accept, max_workers=1, fail_fast=True)
        results = flow.run()
        for result in results.values():
            if result.error is not None:
                raise result.error
        print(json.dumps(flow.value(accept)))
    except Exception as error:
        write("FAILURE.json", {"error": repr(error), "switched": state["switched"]})
        if state["switched"]:
            if dropin.read_text() != state["override"]:
                raise RuntimeError("Another writer changed the override; automatic rollback refused") from error
            dropin.unlink()
            helpers.command("systemctl", "--user", "daemon-reload")
            helpers.command("systemctl", "--user", "restart", helpers.UNIT)
            write("ROLLBACK.json", {"state": "previous_service_restored", "pid": helpers.main_pid()})
        raise


if __name__ == "__main__":
    main()

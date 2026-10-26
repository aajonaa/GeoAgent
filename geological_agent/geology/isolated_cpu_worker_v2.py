"""Fixed v2 worker. Not a general module/command dispatcher."""
import contextlib
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import struct
import sys


GPR_PROFILE_ID = "expansion501-geology-gpr-cpu-v2"
_GEOLOGY_CPU_KEY = "GEOAGENT_EXPANSION501_GEOLOGY_CPU"
_GEOLOGY_CPU_VALUE = "expansion501-geology-cpu-v1"


@contextlib.contextmanager
def _scientific_cpu_policy(bridge, profile, profile_id):
    """Fixed policy after profile/source verification; never accepts user env data."""
    context = bridge.CHILD.get()
    bridge.need(context is not None and context.get("pid") == os.getpid() and
                context.get("profile") is profile and context.get("tool") == profile["tool"],
                "Scientific CPU policy requires the fixed worker's trusted child context.")
    environment = {}
    if profile["tool"] == "GeoConditionedResourceEnsemble":
        bridge.need(profile_id == GPR_PROFILE_ID and
                    profile["module"] == "geological_agent.geology.expansion501_geology" and
                    profile["callable"] == "conditioned_resource_ensemble",
                    "GPR requires the reviewed fixed CPU profile and entrypoint.", "missing_dependency")
        environment = {_GEOLOGY_CPU_KEY: _GEOLOGY_CPU_VALUE}
    previous = {name: os.environ.get(name) for name in environment}
    try:
        for name, value in environment.items():
            os.environ[name] = value
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main():
    # Reserve the protocol FD; Python and native stdout writes go to bounded stderr.
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    from geological_agent.geology import isolated_cpu_bridge_v2 as bridge
    nonce, tool = "", ""
    limit = 4000000
    try:
        bridge.need(len(sys.argv) == 4, "Only the fixed administrator launch is supported.")
        profile_id, job_arg, config_digest = sys.argv[1:]
        job = Path(job_arg)
        bridge.need(job.is_absolute(), "Private job path must be absolute.")
        bridge.no_links(job)
        registry = job / "control/registry.json"
        bridge.regular(registry)
        bridge.need(registry.stat().st_size <= 1048576 and bridge.sha(registry) == config_digest,
                    "Private administrator profile snapshot mismatch.")
        config = bridge.strict_json(registry.read_bytes(), 1048576)
        bridge.closed(config, {"protocol", "profiles"})
        bridge.need(config["protocol"] == bridge.PROTOCOL and profile_id in config["profiles"],
                    "Unknown fixed profile.")
        declared = config["profiles"][profile_id]
        tool = declared["tool"]
        p, raw = bridge.load_profile(profile_id, tool, registry=registry)
        bridge.within(p["private_root"], job)
        bridge.need(Path(p["worker"]).resolve() == Path(__file__).resolve() and
                    Path(sys.executable).resolve() == Path(p["python_realpath"]).resolve() and
                    Path(sys.prefix).resolve() == Path(p["python_prefix"]).resolve() and
                    ".".join(map(str, sys.version_info[:3])) == p["python_version"],
                    "Worker is not running the exact reviewed interpreter/source.")
        limits = p["limits"]
        limit = limits["response_json_bytes"]
        if os.name != "nt":
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (limits["memory_bytes"], limits["memory_bytes"]))
            cpu_seconds = math.ceil(limits["timeout_seconds"] * 2)
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            resource.setrlimit(resource.RLIMIT_FSIZE, (limits["output_bytes"], limits["output_bytes"]))
            if hasattr(os, "sched_getaffinity"):
                os.sched_setaffinity(0, set(sorted(os.sched_getaffinity(0))[:2]))
        request = bridge.read_header(sys.stdin.buffer, limits["request_bytes"])
        bridge.closed(request, {"protocol", "tool", "profile_id", "nonce", "spec_sha256", "args", "inputs"})
        nonce = request["nonce"]
        bridge.need(request["protocol"] == bridge.PROTOCOL and request["tool"] == tool and
                    request["profile_id"] == profile_id and isinstance(nonce, str) and
                    len(nonce) == 48 and all(x in "0123456789abcdef" for x in nonce),
                    "Request identity mismatch.")
        bridge.need(sys.stdin.buffer.read(1) == b"", "Unexpected trailing request bytes.")
        bridge.check_snapshots(job / "inputs", request["inputs"])
        # Actual canonical dependencies are imported inside this interpreter.
        from legacy.ToolsAgent.ToolsFuns import source_contracts
        source_contracts.ROOT = root
        source_contracts.catalog.cache_clear()
        spec = source_contracts.definition(tool)
        bridge.need(hashlib.sha256(bridge.json_bytes(spec)).hexdigest() == request["spec_sha256"],
                    "Worker catalog contract hash mismatch.")
        bridge.need(spec.get("registration_metadata", {}).get("runtime", {}).get("isolation_profile_id") == profile_id,
                    "Catalog is not bound to this fixed profile.")
        bridge.need(bridge.expected_requirements(spec) == bridge.pin_map(p["requirements"]),
                    "Child profile and catalog dependency pins disagree.")
        target = getattr(importlib.import_module(p["module"]), p["callable"])
        bridge.need(getattr(target, "__geoagent_operation_id__", None) == tool and
                    getattr(target, "__wrapped__", None) is not None,
                    "Fixed child target must be the canonical operation decorator.")
        token = bridge.CHILD.set({"pid": os.getpid(), "tool": tool, "spec_sha256": request["spec_sha256"],
                                  "profile": p})
        try:
            output = str(job / "outputs") if spec["source_interface"]["entrypoint"].get("output_directory_parameter") else None
            # The existing decorator runs _dependencies() here, without bypass.
            with _scientific_cpu_policy(bridge, p, profile_id):
                result = target(request["args"], output_dir=output)
        finally:
            bridge.CHILD.reset(token)
        bridge.check_snapshots(job / "inputs", request["inputs"])
        bridge.validate_profile(profile_id, p, tool)
        installed = result.get("provenance", {}).get("installed_versions")
        bridge.need(installed == bridge.pin_map(p["requirements"]), "Actual child dependency guard receipt mismatch.")
        files = []
        total = 0
        for directory, dirs, names in os.walk(job / "outputs", followlinks=False):
            for name in dirs:
                bridge.no_links(Path(directory) / name)
            for name in names:
                path = Path(directory) / name
                info = bridge.regular(path, single_link=True)
                rel = path.relative_to(job / "outputs").as_posix()
                bridge.relative(rel)
                total += info.st_size
                bridge.need(info.st_size <= limits["file_bytes"] and total <= limits["output_bytes"]
                            and len(files) < limits["output_files"], "Worker artifacts exceed budget.", "resource_limit")
                validator = bridge.artifact_validator(p, rel)
                bridge.content_check(path, validator, semantic=True)
                files.append({"path": rel, "bytes": info.st_size, "sha256": bridge.sha(path),
                              "validator_id": validator})
        files.sort(key=lambda item: item["path"])
        expected = {item["path"]: item["sha256"] for item in files}
        bridge.need(result["provenance"].get("output_sha256") == expected,
                    "Worker artifact enumeration and canonical contract hashes disagree.")
        absolute_artifacts = sorted(str((job / "outputs" / item["path"]).resolve()) for item in files)
        bridge.need(sorted(result.get("artifacts", [])) == absolute_artifacts,
                    "Canonical worker artifact paths disagree.")
        result["artifacts"] = [item["path"] for item in files]
        proof = {"profile_id": profile_id, "profile_sha256": hashlib.sha256(raw).hexdigest(),
                 "worker_sha256": p["worker_sha256"], "python_version": p["python_version"],
                 "python_sha256": p["python_sha256"], "build_receipt_sha256": p["build_receipt_sha256"],
                 "installed_versions": installed, "spec_sha256": request["spec_sha256"]}
        response = {"protocol": bridge.PROTOCOL, "tool": tool, "nonce": nonce, "status": "ok",
                    "data": result, "files": files, "proof": proof}
        bridge.write_header(protocol, response, limit)
        for item in files:
            path = job / "outputs" / item["path"]
            bridge.need(bridge.sha(path) == item["sha256"], "Artifact changed before framed transport.")
            protocol.write(struct.pack(">Q", item["bytes"]))
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(262144), b""):
                    protocol.write(block)
        protocol.flush()
        return 0
    except BaseException as error:
        code = getattr(error, "code", None)
        if code is None:
            code = "missing_dependency" if isinstance(error, (ImportError, ModuleNotFoundError)) else "upstream_failure"
        chain, cause = [], error
        while cause is not None and len(chain) < 4:
            chain.append({"type": type(cause).__module__ + "." + type(cause).__name__,
                          "message": str(cause)[:4096]})
            cause = cause.__cause__ or cause.__context__
        try:
            bridge.write_header(protocol, {"protocol": bridge.PROTOCOL, "tool": tool, "nonce": nonce,
                                           "status": "error", "error": {"code": code, "message": str(error)[:4096],
                                                                       "retryable": False, "exception_chain": chain}}, limit)
            protocol.flush()
        except BaseException:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

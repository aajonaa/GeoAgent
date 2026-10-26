"""Read-only runtime inventory; write identity receipts only in this geology group."""
from __future__ import annotations

import base64
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import platform
import re
import struct
import sys
import sysconfig
from urllib.parse import urlparse, unquote

ROOT = Path(__file__).resolve().parents[6]
REL = "catalog/source_delivery/expansion501-20261026/groups/geology"
GROUP = ROOT / REL
RUN = GROUP / "acceptance/local-r6-gpr-20261026"
VENV = RUN / "venv"
SOURCE = RUN / "source"
OUT = GROUP / "resolution-r6/runtime-identity-r1"
TEST_ENTRY = GROUP / "acceptance/local_gpr_acceptance_r6.py"
EXPECTED = {
    "python": "8e11f5c0c4cdea438059feea1b750721929433374b389674c8368ae8bfcbf525",
    "adapter": "20830b7edd3a93aecc6a99f3cf69d9f8d256201c9a44aea6286dcc2480259376",
    "contract": "25f805cf5531ff8bf1f8894f006dca40c6035efd44967507583c820dcc323fa9",
    "registry": "c107ec7ab91587122fcc77c9e02756ca2aa8800319407b5d7879e651362e3576",
    "catalog": "c1d6acd39009465f3ce8212e83224df58b0890cf754618223732b5c6845ea2e6",
    "tests": "e11966ace50f7caf44fb13e15516a84dad01b5f3d4159bd87226b994e1b119ce",
    "report": "e7ce1d2f62825c2cf3026ecdeaddf1b7e1a27200be4887327a0a6b1e31d71471",
}
PATHS = {
    "python": VENV / "Scripts/python.exe",
    "adapter": SOURCE / "geological_agent/geology/expansion501_geology.py",
    "contract": SOURCE / "geological_agent/geology/collection_contracts.py",
    "registry": SOURCE / "geological_agent/geology/source_registry.py",
    "catalog": SOURCE / "catalog/registry.json",
    "tests": TEST_ENTRY,
    "report": RUN / "gpr-report.json",
}

def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()

def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def save(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")

def file_identity(path):
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha(path)}

def main():
    if sys.version_info[:3] != (3, 12, 14) or Path(sys.prefix).resolve() != VENV.resolve():
        raise RuntimeError("Use only the already-tested private Python 3.12.14 interpreter.")
    if sys.prefix == sys.base_prefix:
        raise RuntimeError("Refusing execution in the shared base environment.")
    if OUT.exists():
        raise RuntimeError("Identity revision already exists; preserve it.")
    OUT.mkdir(parents=True)
    sys.path.insert(0, "C:/Users/jona/.codex/skills/flowing/scripts")
    from flowing import Flow, task

    @task
    def identity_and_receipt_gate():
        identities = {name: file_identity(path) for name, path in PATHS.items()}
        for name, expected in EXPECTED.items():
            if identities[name]["sha256"] != expected:
                raise RuntimeError("Identity precondition changed: " + name)
        report = read(RUN / "gpr-report.json")
        if report["passed"] != 20 or report["failures"] or report["errors"] or report["skipped"]:
            raise RuntimeError("The receipt must reference the real completed 20-test run.")
        recorded = {norm(x["name"]): x["version"] for x in read(RUN / "installed-distributions.json")}
        actual = {}
        for dist in metadata.distributions():
            key = norm(dist.metadata["Name"])
            if key in actual:
                raise RuntimeError("Duplicate installed distribution: " + key)
            actual[key] = dist.version
        if actual != recorded:
            raise RuntimeError("Installed distribution set/version drift; do not change pins or repair here.")
        wheels, receipts = {}, []
        for filename in ("pip-install-report.json", "pip-runtime-support-report.json"):
            path = RUN / filename
            document = read(path)
            receipts.append(file_identity(path))
            for item in document["install"]:
                name, version = item["metadata"]["name"], item["metadata"]["version"]
                url = item["download_info"]["url"]
                checksum = item["download_info"]["archive_info"]["hashes"].get("sha256")
                if not re.fullmatch(r"[0-9a-f]{64}", checksum or "") or not urlparse(url).path.endswith(".whl"):
                    raise RuntimeError("Missing actual wheel/SHA256 evidence: " + name)
                key = norm(name)
                if key in wheels or actual.get(key) != version:
                    raise RuntimeError("Receipt does not uniquely match installed distribution: " + name)
                wheels[key] = {
                    "name": name, "normalized_name": key, "version": version,
                    "url": url, "filename": unquote(urlparse(url).path.rsplit("/", 1)[-1]),
                    "wheel_sha256": checksum, "requested_directly": item["requested"],
                    "hash_basis": "pip_install_report_archive_info",
                    "archive_rehashed_now": False, "archive_retention": "not_assumed",
                    "receipt": path.relative_to(ROOT).as_posix(),
                    "source_distribution_or_git_correspondence": "not_established"}
        uncovered = sorted(set(actual) - set(wheels))
        if uncovered != ["pip"]:
            raise RuntimeError("Unexpected receipt coverage gap: " + repr(uncovered))
        preconditions = read(RUN / "source-preconditions.json")
        source_files = []
        for item in preconditions["files"]:
            path = SOURCE / item["relative"]
            identity = file_identity(path)
            if identity["sha256"] != item["sha256"]:
                raise RuntimeError("Tested private source changed: " + item["relative"])
            source_files.append({"relative": item["relative"], **identity})
        return {"identities": identities, "installed": actual, "wheels": wheels,
                "receipt_files": receipts, "source_files": source_files,
                "required_environment": preconditions["environment"], "ready": True}

    @task(depends_on=[identity_and_receipt_gate],
          when=lambda identity_and_receipt_gate: identity_and_receipt_gate["ready"])
    def installed_file_manifest(identity_and_receipt_gate):
        # RECORD enumeration only: no recursive scan, install, import of scientific packages or network.
        files, distributions, missing, mismatches = {}, [], [], []
        total_bytes = 0
        for dist in sorted(metadata.distributions(), key=lambda d: norm(d.metadata["Name"])):
            key = norm(dist.metadata["Name"])
            entries = dist.files
            if entries is None:
                raise RuntimeError("Installed distribution has no file inventory: " + key)
            record_path = None
            owned = []
            unchecked = 0
            for entry in entries:
                path = Path(dist.locate_file(entry)).resolve()
                if not path.is_relative_to(VENV.resolve()):
                    raise RuntimeError("Distribution file escaped the private venv: " + str(path))
                if not path.is_file():
                    missing.append({"distribution": key, "record_path": str(entry)})
                    continue
                relative = path.relative_to(VENV.resolve()).as_posix()
                if relative not in files:
                    size = path.stat().st_size
                    total_bytes += size
                    if len(files) >= 50000 or total_bytes > 2 * 1024 ** 3:
                        raise RuntimeError("Read-only file manifest budget exceeded.")
                    files[relative] = {"path": relative, "bytes": size, "sha256": sha(path), "owners": []}
                observed = files[relative]
                observed["owners"].append(key)
                owned.append(relative)
                if str(entry).endswith(".dist-info/RECORD"):
                    record_path = relative
                if entry.hash is None:
                    unchecked += 1
                elif entry.hash.mode == "sha256":
                    encoded = base64.urlsafe_b64encode(bytes.fromhex(observed["sha256"])).decode().rstrip("=")
                    if encoded != entry.hash.value:
                        mismatches.append({"distribution": key, "path": relative,
                                           "record_hash": entry.hash.value, "observed": encoded})
                else:
                    raise RuntimeError("Unsupported RECORD hash algorithm: " + entry.hash.mode)
                if entry.size is not None and entry.size != observed["bytes"]:
                    mismatches.append({"distribution": key, "path": relative, "issue": "RECORD_size_mismatch"})
            distributions.append({"name": key, "version": dist.version, "record_path": record_path,
                                  "file_count": len(owned), "files_without_record_hash": unchecked})
        payload = {
            "scope": "current_RECORD_enumerated_installed_files_only_not_wheel_archive_hashes",
            "venv": str(VENV), "distributions": distributions, "files": sorted(files.values(), key=lambda x: x["path"]),
            "file_count": len(files), "total_bytes": total_bytes, "missing": missing, "record_mismatches": mismatches,
            "qualification": "Hashes observe installed bytes now. Matching local RECORD is an internal consistency check, not independent wheel-to-install or source-commit attestation. Unlisted/cache files and the shared standard library are outside this package manifest."}
        save(OUT / "installed-files-sha256.json", payload)
        if missing or mismatches:
            raise RuntimeError("Installed-file inconsistency preserved; do not repair or reinstall.")
        return {"file_count": len(files), "bytes": total_bytes, "distribution_count": len(distributions),
                "manifest": file_identity(OUT / "installed-files-sha256.json"), "consistent": True}

    @task(depends_on=[identity_and_receipt_gate, installed_file_manifest],
          when=lambda identity_and_receipt_gate, installed_file_manifest: installed_file_manifest["consistent"])
    def finish_receipt(identity_and_receipt_gate, installed_file_manifest):
        info = identity_and_receipt_gate
        bootstrap_version = info["installed"]["pip"]
        bootstrap_wheel = Path(sys.base_prefix) / "Lib/ensurepip/_bundled" / ("pip-" + bootstrap_version + "-py3-none-any.whl")
        bootstrap = {"name": "pip", "version": bootstrap_version, "download_receipt": None,
                     "kind": "venv_ensurepip_bootstrap", "installed_file_manifest": "installed-files-sha256.json",
                     "local_bootstrap_wheel": file_identity(bootstrap_wheel) if bootstrap_wheel.is_file() else None,
                     "source_distribution_or_git_correspondence": "not_established",
                     "qualification": "A local bundle SHA, if present, is not a recorded download URL or proof that installed files came from that exact archive."}
        wheels = [info["wheels"][key] for key in sorted(info["wheels"])]
        package_lock = {
            "platform": "Windows AMD64 CPython 3.12", "status": "observed_exact_private_runtime_lock",
            "runtime_wheel_count": len(wheels), "installed_distribution_count": len(info["installed"]),
            "runtime_transitive_receipt_coverage": "26/26",
            "wheels": wheels, "bootstrap": bootstrap, "receipts": info["receipt_files"],
            "unresolved_source_correspondence": "No wheel is claimed byte-correspondent to a reviewed Git commit. No sdist was used or invented.",
            "linux_compatibility": "not_verified"}
        save(OUT / "windows-cp312-wheel-lock.json", package_lock)
        lock_text = (
            "# Observed Windows AMD64 CPython 3.12 runtime closure, not a Linux lock.\n"
            "# Exact URLs and recorded artifact hashes: windows-cp312-wheel-lock.json.\n"
            "# pip bootstrap is separate; no download receipt was fabricated for it.\n"
            "--require-hashes\n--only-binary=:all:\n"
            + "\n".join(x["normalized_name"] + "==" + x["version"] + " --hash=sha256:" + x["wheel_sha256"]
                        for x in wheels) + "\n")
        with (OUT / "requirements-windows-cp312-hashed.txt").open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(lock_text)
        runtime_files = []
        paths = [Path(sys._base_executable), VENV / "pyvenv.cfg"]
        paths.extend(Path(sys.base_prefix) / name for name in (
            "python312.dll", "python3.dll", "vcruntime140.dll", "vcruntime140_1.dll"))
        for path in dict.fromkeys(paths):
            if path.is_file():
                runtime_files.append(file_identity(path))
        runtime = {
            "status": "current_local_identity_verified_no_new_tests", "tool_id": "GeoConditionedResourceEnsemble",
            "fixed_callable": "geological_agent.geology.expansion501_geology:conditioned_resource_ensemble",
            "argument_parameter": "args", "python": info["identities"]["python"],
            "python_version": platform.python_version(), "python_build": sys.version,
            "platform": sysconfig.get_platform(), "architecture_bits": struct.calcsize("P") * 8,
            "code_root": str(SOURCE), "test_entry": info["identities"]["tests"],
            "test_class": "LocalGPR", "test_count": 20,
            "test_entry_replay": "The original main() is deliberately one-shot and refuses overwriting the existing run. Parent must use a fresh acceptance revision, not rerun it in place.",
            "binding_files": info["identities"], "source_files": info["source_files"],
            "sys_prefix": sys.prefix, "sys_base_prefix": sys.base_prefix,
            "base_executable": sys._base_executable, "base_runtime_files": runtime_files,
            "portability": "Identity receipt, not a relocatable standalone venv. Windows venv depends on its read-only base_prefix and host OS; shared standard-library/OS DLL build provenance is not fully attested.",
            "dependency_lock": file_identity(OUT / "windows-cp312-wheel-lock.json"),
            "hash_checked_requirements": file_identity(OUT / "requirements-windows-cp312-hashed.txt"),
            "installed_files": installed_file_manifest,
            "required_environment_from_test": info["required_environment"],
            "binding_cautions": [
                "Private source snapshot contains the pre-v2 collection_contracts guard and parent r3 source whitelist; do not overwrite this accepted test evidence.",
                "Ramanujan owns the v2 common profile/schema and actual cross-interpreter acceptance.",
                "Version checks remain in the real child interpreter; CPU marker alone is not IPC authentication.",
                "JSON-only args/result; artifacts=[], no output_dir, user executable, shell, module or arbitrary callable.",
                "No acceptance count is added by hashing; local GPR remains 20/20, Linux/v2/model/platform not_run."],
            "scientific_source_commit_reviewed_separately": "25dee604bae18205b01548348388baf7a1cdfe0e",
            "scientific_git_to_wheel_correspondence": "not_established",
            "source_authored": 26, "blocked": 5, "formal_eligible": False,
            "deployment_status": "not_deployed", "submission_status": "not_submitted"}
        save(OUT / "runtime-identity.json", runtime)
        manifest_path = GROUP / "delivery-files.json"
        manifest = read(manifest_path)
        new_files = [Path(__file__), OUT / "installed-files-sha256.json",
                     OUT / "windows-cp312-wheel-lock.json", OUT / "requirements-windows-cp312-hashed.txt",
                     OUT / "runtime-identity.json", OUT / "receipt-flow.jsonl"]
        manifest["files"] = sorted(set(manifest["files"] + [p.relative_to(ROOT).as_posix() for p in new_files]))
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8", newline="\n")
        return {"runtime_identity": file_identity(OUT / "runtime-identity.json"),
                "runtime_wheels": len(wheels), "installed_distributions": len(info["installed"]),
                "bootstrap_wheel_available": bootstrap["local_bootstrap_wheel"] is not None,
                "installed_file_count": installed_file_manifest["file_count"],
                "manifest_files": len(manifest["files"]), "new_tests_executed": 0}

    flow = Flow(finish_receipt, max_workers=1, fail_fast=True, journal_path=str(OUT / "receipt-flow.jsonl"))
    flow.run()
    print(json.dumps(flow.value(finish_receipt), ensure_ascii=False))

if __name__ == "__main__":
    main()


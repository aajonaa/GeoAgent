"""Bind already accepted tool environments to the existing CPU-v2 protocol.

This is a release-time operation, never a tool-time dependency installer.
The input manifest is assembled from reviewed, immutable group receipts.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


MANDATORY = (
    "geological_agent/geology/isolated_cpu_worker_v2.py",
    "geological_agent/geology/isolated_cpu_bridge_v2.py",
    "geological_agent/geology/collection_contracts.py",
    "legacy/ToolsAgent/ToolsFuns/source_contracts.py",
    "legacy/ToolsAgent/ToolsFuns/GeoEval/scientific_tools.py",
)
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;]+)$")


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_new(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def encoded(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def bound_file(root, relative):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Unsafe source-relative path: " + str(relative))
    target = root / path
    if target.is_symlink() or not target.resolve().is_relative_to(root) or not target.is_file():
        raise ValueError("Missing or untrusted source file: " + str(relative))
    for parent in target.parents:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError("Symlink in source closure: " + str(relative))
    return target


def local_module(root, module):
    if not module or not all(part.isidentifier() for part in module.split(".")):
        return None
    stem = Path(*module.split("."))
    for relative in (stem.with_suffix(".py"), stem / "__init__.py"):
        if (root / relative).is_file():
            return relative.as_posix()
    return None


def source_closure(root, module, extra_files=()):
    """Include static local imports, package initializers and declared dynamic imports."""
    root = Path(root).resolve()
    entry = local_module(root, module)
    if entry is None:
        raise ValueError("Implementation module is absent: " + module)
    pending, found = list(MANDATORY) + [entry] + list(extra_files), {}
    while pending:
        relative = pending.pop()
        if relative in found:
            continue
        path = bound_file(root, relative)
        found[relative] = digest(path)
        if path.suffix != ".py":
            continue
        parts = Path(relative).with_suffix("").parts
        package = parts[:-1]
        for length in range(1, len(package) + 1):
            initial = Path(*package[:length], "__init__.py").as_posix()
            if (root / initial).is_file():
                pending.append(initial)
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    if node.level > len(package):
                        raise ValueError("Invalid relative import in " + relative)
                    base = list(package[:len(package) - node.level + 1])
                else:
                    base = []
                if node.module:
                    base.extend(node.module.split("."))
                imports.append(".".join(base))
                imports.extend(".".join(base + [alias.name]) for alias in node.names if alias.name != "*")
            elif isinstance(node, ast.Call) and node.args:
                function = node.func
                name = function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", "")
                if name in ("import_module", "__import__") and isinstance(node.args[0], ast.Constant):
                    value = node.args[0].value
                    if isinstance(value, str) and not value.startswith("."):
                        imports.append(value)
        for imported in imports:
            imported_file = local_module(root, imported)
            if imported_file:
                pending.append(imported_file)
    return dict(sorted(found.items()))


def canonical_pins(lines):
    result = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN.fullmatch(line)
        if not match:
            raise ValueError("Non-exact dependency: " + line)
        name = re.sub(r"[-_.]+", "-", match[1]).lower()
        if name in result:
            raise ValueError("Duplicate dependency: " + name)
        result[name] = match[2]
    return result


def isolation_schema(profile_id, requirements, projects):
    """Declare the worker's additive proof without opening scientific schemas."""
    hash_field = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    properties = {
        "profile_id": {"const": profile_id},
        "profile_sha256": hash_field, "worker_sha256": hash_field,
        "python_version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"},
        "python_sha256": hash_field, "build_receipt_sha256": hash_field,
        "installed_versions": {"type": "object", "additionalProperties": False,
            "properties": {key: {"const": value} for key, value in requirements.items()},
            "required": sorted(requirements)},
        "spec_sha256": hash_field,
        "protocol": {"const": "geoagent-isolated-cpu-v2"},
        "native_projects": {"type": "object", "additionalProperties": False,
            "properties": {key: {"const": value["version"]} for key, value in projects.items()},
            "required": sorted(projects)},
        "gpu_requested": {"const": False}, "runtime_install": {"const": False},
        "os_sandbox": {"const": False},
        "evidence_directory": {"type": "string", "minLength": 1, "maxLength": 4096},
    }
    return {"type": "object", "properties": properties, "required": sorted(properties),
            "additionalProperties": False}


def checked_evidence(records, destination):
    if not records:
        raise ValueError("Original source/license evidence is required")
    copied = []
    for index, record in enumerate(records):
        source = Path(record["path"])
        actual = digest(source)
        if actual != record["sha256"]:
            raise ValueError("Evidence hash changed: " + str(source))
        target = destination / (str(index) + "-" + source.name)
        write_new(target, source.read_bytes())
        copied.append({**record, "published_path": str(target), "sha256": actual})
    return copied


def probe_environment(item, private_root):
    executable = Path(item["python"])
    real = executable.resolve(strict=True)
    if str(real) != item["python_realpath"]:
        raise ValueError("Interpreter target changed")
    probe_home = private_root / "environment-probe"
    probe_home.mkdir(parents=True, exist_ok=False)
    environment = {
        "HOME": str(probe_home), "TMPDIR": str(probe_home),
        "CUDA_VISIBLE_DEVICES": "", "NVIDIA_VISIBLE_DEVICES": "void",
        "HIP_VISIBLE_DEVICES": "", "ROCR_VISIBLE_DEVICES": "",
        "JAX_PLATFORMS": "cpu", "PYTHONNOUSERSITE": "1",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1", "PROJ_NETWORK": "OFF",
    }
    code = (
        "import sys,json,importlib.metadata as m; import jsonschema; "
        "print(json.dumps({'prefix':sys.prefix,'version':'.'.join(map(str,sys.version_info[:3])),"
        "'packages':[(d.metadata['Name'],d.version) for d in m.distributions()], 'sys_path':sys.path}))"
    )
    completed = subprocess.run([str(executable), "-I", "-B", "-c", code], env=environment,
                               capture_output=True, text=True, timeout=120, check=True)
    report = json.loads(completed.stdout)
    if report["prefix"] != item["python_prefix"] or report["version"] != item["python_version"]:
        raise ValueError("Python identity differs from accepted environment")
    pins = canonical_pins([name + "==" + version for name, version in report["packages"]])
    lock = Path(item["dependency_lock"])
    if digest(lock) != item["dependency_lock_sha256"]:
        raise ValueError("Full environment lock changed")
    if pins != canonical_pins(lock.read_text(encoding="utf-8").splitlines()):
        raise ValueError("Installed environment does not exactly match its frozen lock")
    return report, digest(real)


def build(app, manifest_path, private_root, workspace_root):
    app, private_root, workspace_root = (Path(value).resolve() for value in (app, private_root, workspace_root))
    manifest = read_json(manifest_path)
    if manifest.get("format") != "geoagent-fixed-cpu-release-v1" or not manifest.get("tools"):
        raise ValueError("Expected reviewed geoagent-fixed-cpu-release-v1 manifest")
    private_root.mkdir(parents=True, exist_ok=False)
    if not workspace_root.is_dir():
        raise ValueError("Task workspace root does not exist")
    sys.path.insert(0, str(app))
    from geological_agent.geology.isolated_cpu_bridge_v2 import expected_requirements, load_profile, PROTOCOL
    catalog_path = app / "catalog/registry.json"
    original_catalog = catalog_path.read_bytes()
    catalog = read_json(catalog_path)
    tools = {spec["id"]: spec for spec in catalog["tools"]}
    for tool_id, item in manifest["tools"].items():
        spec = tools[tool_id]
        provenance = spec["output_schema"]["properties"]["provenance"]
        proof_schema = isolation_schema(item["profile_id"], expected_requirements(spec), item.get("projects", {}))
        previous = provenance.get("properties", {}).get("isolation")
        if previous is not None and previous != proof_schema:
            raise ValueError("Existing isolation schema differs; explicit merge required")
        provenance.setdefault("properties", {})["isolation"] = proof_schema
    if catalog_path.read_bytes() != original_catalog:
        raise ValueError("Catalog changed before proof schema binding")
    catalog_path.write_bytes((json.dumps(catalog, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    catalog_sha = digest(catalog_path)
    target = app / "catalog/source_delivery/expansion501-20261026/shared-isolation-v2/profiles.json"
    original = target.read_bytes()
    config = json.loads(original)
    if config["protocol"] != PROTOCOL:
        raise ValueError("Unexpected isolation protocol")
    evidence_root = target.parent / manifest["release_id"]
    if evidence_root.exists():
        raise ValueError("Release evidence directory already exists")
    receipts = {}
    for tool_id, item in sorted(manifest["tools"].items()):
        spec = tools[tool_id]
        profile_id = item["profile_id"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,119}", profile_id):
            raise ValueError("Unsafe profile ID")
        if profile_id in config["profiles"]:
            raise ValueError("Refusing to replace an existing profile")
        if spec["registration_metadata"]["runtime"].get("isolation_profile_id") != profile_id:
            raise ValueError("Catalog is not explicitly bound to the profile")
        if item.get("scientific_acceptance") != "passed" or item.get("license_review_complete") is not True:
            raise ValueError("Scientific acceptance and reviewed original licenses are required")
        required = sorted(name + "==" + version for name, version in expected_requirements(spec).items())
        if canonical_pins(required) != canonical_pins(item["requirements"]):
            raise ValueError("Profile requirements differ from canonical tool requirements")
        output = evidence_root / profile_id
        output.mkdir(parents=True)
        evidence = {
            key: checked_evidence(item[key], output / key)
            for key in ("license_evidence", "source_evidence", "acceptance_evidence")
        }
        private = private_root / profile_id
        private.mkdir()
        identity, python_sha = probe_environment(item, private)
        for name, version in canonical_pins(required).items():
            installed = canonical_pins([n + "==" + v for n, v in identity["packages"]])
            if installed.get(name) != version:
                raise ValueError("Canonical dependency is absent: " + name)
        closure = source_closure(app, item["module"], item.get("extra_source_files", []))
        lock = output / "requirements.txt"
        write_new(lock, ("\n".join(required) + "\n").encode())
        receipt = output / "build-receipt.json"
        write_new(receipt, encoded({
            "profile_id": profile_id, "python_version": item["python_version"],
            "python_sha256": python_sha, "dependency_lock_sha256": digest(lock),
            "license_review_complete": True, "source_closure_complete": True,
            "projects": sorted(item.get("projects", {})),
        }))
        worker = app / MANDATORY[0]
        profile = {
            "tool": tool_id, "source_root": str(app), "private_root": str(private),
            "input_root": str(workspace_root), "output_root": str(workspace_root),
            "python": item["python"], "python_realpath": item["python_realpath"],
            "python_prefix": item["python_prefix"], "python_sha256": python_sha,
            "python_version": item["python_version"], "worker": str(worker), "worker_sha256": digest(worker),
            "module": item["module"], "callable": item["callable"],
            "catalog": str(catalog_path), "catalog_sha256": catalog_sha,
            "source_files": closure, "requirements": required,
            "dependency_lock": str(lock), "dependency_lock_sha256": digest(lock),
            "build_receipt": str(receipt), "build_receipt_sha256": digest(receipt),
            "source_closure_complete": True, "projects": item.get("projects", {}),
            "artifact_rules": item.get("artifact_rules", []),
            "limits": item["limits"],
        }
        config["profiles"][profile_id] = profile
        receipts[tool_id] = {"profile_id": profile_id, "environment": identity, "evidence": evidence}
    raw = encoded(config)
    if len(raw) > 1024 * 1024:
        raise ValueError("Profile registry exceeds the existing CPU-v2 size bound")
    temporary = target.with_name("profiles-" + manifest["release_id"] + ".candidate.json")
    write_new(temporary, raw)
    for tool_id, item in manifest["tools"].items():
        load_profile(item["profile_id"], tool_id, registry=temporary)
    if target.read_bytes() != original or digest(catalog_path) != catalog_sha:
        raise ValueError("Candidate changed during profile construction")
    os.replace(temporary, target)
    result = {"format": manifest["format"], "catalog_sha256": catalog_sha,
              "profiles_sha256": digest(target), "tools": receipts, "gpu_used": False}
    write_new(evidence_root / "profile-construction.json", encoded(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("app", "manifest", "private-root", "workspace-root"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    result = build(args.app, args.manifest, args.private_root, args.workspace_root)
    print(json.dumps({"profile_count": len(result["tools"]), "catalog_sha256": result["catalog_sha256"]}))

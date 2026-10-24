"""Per-operation CPU evidence before anything is eligible for the accepted catalog."""
import copy
from dataclasses import asdict
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
from threading import Event
import time
import traceback


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "" or os.environ.get("NVIDIA_VISIBLE_DEVICES") != "none":
        raise RuntimeError("All GPUs must be disabled")
    root = Path(__file__).resolve().parent
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=False)
    manifests = json.loads((root / "collection-manifests.json").read_text(encoding="utf-8"))
    catalog = json.loads((root / "catalog/registry.json").read_text(encoding="utf-8"))
    specs = {row["id"]: row for row in catalog["tools"]}
    fixture_errors = {}
    for group, manifest in manifests.items():
        try:
            fixture = importlib.import_module("collection_acceptance." + group + "_fixtures")
            fixture.create(root)
        except Exception:
            fixture_errors[group] = traceback.format_exc()
    from geological_agent.bootstrap import build_registry
    from geological_agent.contracts import ToolCall
    from geological_agent.settings import Settings
    from geological_agent.tools import ToolExecutionContext, ToolExecutor
    from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError
    registry, _, base_tools = build_registry()
    results = []
    for group, manifest in manifests.items():
        check = importlib.import_module("collection_acceptance." + group + "_checks").check
        for operation in manifest["operations"]:
            name = operation["name"]
            spec = specs[name]
            row = {"name": name, "group": group, "project_id": operation["project_id"], "status": "failed", "checks": [], "gpu_used": False, "model_used": False, "live_service_validation": "not_run"}
            started = time.monotonic()
            try:
                if group in fixture_errors:
                    raise RuntimeError("Synthetic fixture creation failed: " + fixture_errors[group])
                if operation.get("network_required"):
                    raise RuntimeError("Live-service operations are not eligible for offline CPU acceptance")
                module_name, function_name = spec["source_interface"]["entrypoint"]["callable"].split(":")
                function = getattr(importlib.import_module(module_name), function_name)
                args = copy.deepcopy(spec["example_arguments"])
                originals = {}
                for field in spec["source_interface"].get("path_fields", []):
                    values = args[field] if isinstance(args[field], list) else [args[field]]
                    originals.update({str(root / value): digest(root / value) for value in values})
                    args[field] = [str(root / value) for value in values] if isinstance(args[field], list) else str(root / values[0])
                generates = bool(spec["source_interface"]["entrypoint"].get("output_directory_parameter"))
                original_connect = socket.socket.connect
                original_create = socket.create_connection
                def deny_network(*_args, **_kwargs):
                    raise RuntimeError("Unexpected network call from an offline scientific operation")
                socket.socket.connect = deny_network
                socket.create_connection = deny_network
                try:
                    direct = []
                    for mode in ["object", "json", "keyword"]:
                        directory = out / name / mode
                        kwargs = {"output_dir": directory} if generates else {}
                        value = function(args=copy.deepcopy(args), **kwargs) if mode == "keyword" else function(json.dumps(args) if mode == "json" else copy.deepcopy(args), **kwargs)
                        check(name, value, args, directory if generates else None)
                        assert value["units"] and value["provenance"]["tool"] == name
                        assert value["provenance"]["implementation_sha256"] == digest(Path(function.__wrapped__.__code__.co_filename))
                        assert all(digest(Path(path)) == expected for path, expected in originals.items())
                        for relative, expected in value["provenance"]["output_sha256"].items():
                            assert digest(directory / relative) == expected
                        direct.append(value)
                        row["checks"].append("direct_" + mode + "_numeric_content_units_source_and_artifact_hashes")
                    if not generates:
                        assert direct[0] == direct[1] == direct[2]
                    invalid = copy.deepcopy(args)
                    invalid["__unexpected_acceptance_argument__"] = True
                    try:
                        function(invalid, **({"output_dir": out / name / "invalid"} if generates else {}))
                    except ScientificToolError as error:
                        assert error.code == "invalid_arguments" and not error.retryable
                    else:
                        raise AssertionError("An undeclared input argument was accepted")
                    row["checks"].append("undeclared_argument_rejected")
                    workspace = out / name / "native-workspace"
                    workspace.mkdir(parents=True)
                    native_args = copy.deepcopy(spec["example_arguments"])
                    for field in spec["source_interface"].get("path_fields", []):
                        values = native_args[field] if isinstance(native_args[field], list) else [native_args[field]]
                        for value in values:
                            destination = workspace / value
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(root / value, destination)
                    context = ToolExecutionContext("earth-collection-acceptance", workspace, (name,), Settings(), Event())
                    native = ToolExecutor(registry).execute(ToolCall("native-" + name, name, native_args), context)
                    assert native.status == "ok", native.error
                    assert name not in base_tools
                    assert bool(native.artifacts) == generates
                    output_dir = workspace / native.artifacts[0].path if native.artifacts else None
                    if output_dir is not None:
                        # Every declared artifact producer writes into the single native result root.
                        output_dir = workspace / "results" / Path(native.artifacts[0].path).parts[1]
                    check(name, native.data, native_args, output_dir)
                    manifest_hashes = native.data["provenance"]["output_sha256"]
                    assert isinstance(manifest_hashes, dict)
                    assert bool(manifest_hashes) == generates
                    manifest_files = {}
                    for relative, expected in manifest_hashes.items():
                        assert output_dir is not None and not Path(relative).is_absolute()
                        path = (output_dir / relative).resolve(strict=True)
                        assert path.is_relative_to(output_dir.resolve()) and path.is_file()
                        assert digest(path) == expected
                        assert path not in manifest_files
                        manifest_files[path] = expected
                    native_files = [(workspace / artifact.path).resolve(strict=True) for artifact in native.artifacts]
                    assert len(native_files) == len(set(native_files))
                    assert set(native_files) == set(manifest_files)
                    assert all(path.is_relative_to(workspace.resolve()) and path.is_file() and digest(path) == manifest_files[path] for path in native_files)
                    for field in spec["source_interface"].get("path_fields", []):
                        values = native_args[field] if isinstance(native_args[field], list) else [native_args[field]]
                        assert all(digest(workspace / value) == digest(root / value) for value in values)
                    row["checks"].append("real_native_runtime_artifacts_and_immutable_inputs")
                    row["native_result"] = asdict(native)
                finally:
                    socket.socket.connect = original_connect
                    socket.create_connection = original_create
                row["status"] = "passed"
            except Exception as error:
                row["error_type"] = type(error).__name__
                row["error"] = str(error)
                row["error_code"] = getattr(error, "code", None)
                row["traceback"] = traceback.format_exc()
            row["elapsed_seconds"] = time.monotonic() - started
            results.append(row)
            (out / "probe-results.json").write_text(json.dumps({"cases": results, "complete": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({key: row.get(key) for key in ["name", "status", "elapsed_seconds", "error_code", "error"]}), flush=True)
    receipt = {"cases": results, "complete": True, "passed": sum(row["status"] == "passed" for row in results), "failed": sum(row["status"] != "passed" for row in results), "skipped": 0, "production_changed": False, "gpu_used": False, "model_used": False}
    (out / "probe-results.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in receipt.items() if key != "cases"}), flush=True)


if __name__ == "__main__":
    main()

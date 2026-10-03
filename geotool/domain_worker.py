"""JSON transport for original structured functions, not an algorithm adapter."""
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from legacy.ToolsAgent.ToolsFuns.source_contracts import arguments, definition, decode

PURE = {"GeoMagnitudeToEnergy", "GeoHaversineDistance", "GeoBearing",
        "GeoDecimalToDMS", "GeoWGS84BBoxAreaKm2", "GeoCheckCRSConsistency"}


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def original_call(name, params, output):
    spec = definition(name)["source_interface"]
    if spec["kind"] == "native":
        from legacy.ToolsAgent.ToolsFuns.Geoscience.tool_name_dict import GEOSCIENCE_TOOLS_DICT
        return GEOSCIENCE_TOOLS_DICT[name](params)
    if spec["kind"] == "geoeval":
        from legacy.ToolsAgent.ToolsFuns.GeoEval.runtime import dispatch
        return dispatch(name, params, output_dir=output)
    if spec["kind"] == "earthquake":
        module, function = spec["implementation"].split(":")
        if module != "legacy.ToolsAgent.ToolsFuns.Geo.geoscienceTools":
            raise ValueError("Unexpected original implementation module.")
        return getattr(importlib.import_module(module), function)(params, output_dir=output)
    raise NotImplementedError("No original implementation registered.")


def remap(value, paths):
    if isinstance(value, str):
        return paths.get(value, value)
    if isinstance(value, list):
        return [remap(item, paths) for item in value]
    if isinstance(value, dict):
        return {key: remap(item, paths) for key, item in value.items()}
    return value


def run(request):
    name = request["tool_id"]
    spec = definition(name)
    interface = spec.get("source_interface", {})
    revised = interface.get("status") == "source_revised_unverified"
    if request.get("describe"):
        return {"ok": True, "available": revised, "interface": interface, "validation": "Source revision untested."}
    if not revised:
        raise NotImplementedError(interface.get("reason", "Source implementation blocked."))
    params = arguments(name, request["input"])
    fields = interface.get("path_fields", [])
    if not fields:
        return {"ok": True, "result": original_call(name, params, None), "validation_scope": "Source schema checks; no acceptance claim."}
    workspace = Path(request["workspace"]).resolve(strict=True)
    output = (workspace / ".domain-results" / uuid.uuid4().hex).resolve()
    if not workspace.is_dir() or not output.is_relative_to(workspace):
        raise PermissionError("Invalid workspace or result path.")
    output.mkdir(parents=True, exist_ok=False)
    paths, sources = {}, []
    with tempfile.TemporaryDirectory(prefix="geotool-source-") as temporary:
        for key in fields:
            values = params[key] if isinstance(params[key], list) else [params[key]]
            prepared = []
            for value in values:
                if Path(value).is_absolute():
                    raise PermissionError("Application input paths must be workspace-relative.")
                original = (workspace / value).resolve(strict=True)
                if not original.is_relative_to(workspace):
                    raise PermissionError("Input escapes workspace.")
                if key == "dir_path":
                    if not original.is_dir():
                        raise ValueError("Expected a directory.")
                    if any(not child.resolve().is_relative_to(workspace) for child in original.rglob("*")):
                        raise PermissionError("Directory contains a link outside the workspace.")
                    prepared.append(str(original))
                    paths[str(original)] = value
                    continue
                if not original.is_file():
                    raise ValueError("Expected a regular file.")
                target = Path(temporary) / str(len(sources)) / original.name
                target.parent.mkdir()
                before = digest(original)
                shutil.copyfile(original, target)
                if digest(target) != before or digest(original) != before:
                    raise RuntimeError("Input changed while creating its snapshot.")
                prepared.append(str(target))
                paths[str(target)] = value
                sources.append({"path": value, "sha256": before})
            params[key] = prepared if isinstance(params[key], list) else prepared[0]
        result = original_call(name, params, output)
    artifacts = []
    for path in sorted(output.rglob("*")):
        if path.is_file():
            if not path.resolve().is_relative_to(output):
                raise PermissionError("Output link escapes result directory.")
            relative = path.relative_to(workspace).as_posix()
            paths[str(path)] = relative
            artifacts.append({"path": relative, "sha256": digest(path), "size_bytes": path.stat().st_size})
    return {"ok": True, "result": remap(result, paths), "artifacts": artifacts,
            "provenance": {"sources": sources}, "validation_scope": "Source schemas and file hashes only."}


if __name__ == "__main__":
    try:
        print(json.dumps(run(decode(sys.stdin.read())), ensure_ascii=False, allow_nan=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)

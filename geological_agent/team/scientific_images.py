"""Read-only scientific viewers bound to owner, execution receipt and generation."""
import hashlib
import json
import math
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from ..scientific_imaging import DESCRIPTIONS


def manifests(store, uid, rid):
    run = store.run(uid, rid)
    generation = run.get("generation")
    if not generation:
        return {"run_id": rid, "conversation_id": run["cid"], "generation": "", "analyses": [], "errors": []}
    files = store.files(uid, run["cid"], generation)
    analyses, errors, cursor, seen = [], [], 0, set()
    while True:
        events = store.events(uid, rid, cursor)
        if not events:
            break
        for row in events:
            cursor = row["id"]
            event = row["data"]
            result = event.get("result", {})
            if event.get("kind") != "tool_result" or result.get("status") != "ok" or result.get("name") not in DESCRIPTIONS:
                continue
            data = result.get("data", {})
            name = data.get("manifest_path")
            if not isinstance(name, str) or name in seen:
                continue
            seen.add(name)
            try:
                reference = next(item for item in data["outputs"] if item["path"] == name and item["role"] == "analysis_manifest")
                raw = files[name]
                if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
                    raise ValueError("Manifest does not match the execution receipt")
                doc = json.loads(raw)
                if doc.get("schema") != "geoagent.scientific-image/v1":
                    raise ValueError("Unsupported analysis schema")
                outputs = {item["path"]: item for item in doc["outputs"]}
                for item in doc["outputs"]:
                    if hashlib.sha256(files[item["path"]]).hexdigest() != item["sha256"]:
                        raise ValueError("An analysis output changed after execution")
                for layer in doc["layers"]:
                    if layer["media_type"] != "image/png" or outputs.get(layer["path"]) != {k: layer[k] for k in ("path", "sha256", "media_type", "role")}:
                        raise ValueError("Layer is not an exact committed PNG output")
                if doc.get("pixel_file") and outputs.get(doc["pixel_file"]["path"]) != doc["pixel_file"]:
                    raise ValueError("Pixel source is not a committed scientific output")
                analyses.append({"manifest_path": name, "manifest_sha256": reference["sha256"],
                                 "call_id": result["call_id"], "document": doc})
            except (ValueError, KeyError, TypeError, StopIteration) as exc:
                errors.append({"manifest_path": name, "error": str(exc) or "Incomplete scientific result"})
    return {"run_id": rid, "conversation_id": run["cid"], "generation": generation, "analyses": analyses, "errors": errors}


def install_scientific_image_routes(app, auth, store):
    @app.get("/scientific-assets/{name}")
    def asset(name: str):
        if name not in ("scientific-viewer.js", "scientific-viewer.css"):
            raise HTTPException(404)
        return FileResponse(Path(__file__).parent / "web" / name)

    @app.get("/api/runs/{rid}/scientific-images")
    def analyses(rid: str, request: Request):
        return manifests(store, auth(request)["id"], rid)

    @app.get("/api/runs/{rid}/scientific-pixel")
    def pixel(rid: str, request: Request, manifest: str, column: int, row: int):
        uid = auth(request)["id"]
        bundle = manifests(store, uid, rid)
        chosen = next((item for item in bundle["analyses"] if item["manifest_path"] == manifest), None)
        if not chosen or not chosen["document"].get("pixel_file"):
            raise HTTPException(404, "No verified scientific pixel source")
        raw = store.files(uid, bundle["conversation_id"], bundle["generation"])[chosen["document"]["pixel_file"]["path"]]
        from rasterio.io import MemoryFile
        from rasterio.windows import Window
        with MemoryFile(raw) as memory, memory.open() as raster:
            if not 0 <= column < raster.width or not 0 <= row < raster.height:
                raise HTTPException(422, "Pixel lies outside the scientific raster")
            value = raster.read(1, window=Window(column, row, 1, 1), masked=True)[0, 0]
            valid = not bool(getattr(value, "mask", False)) and math.isfinite(float(value))
            x, y = raster.xy(row, column)
            return {"column": column, "row": row, "x": x, "y": y, "crs": str(raster.crs),
                    "value": float(value) if valid else None, "valid": valid,
                    "unit": raster.tags(1).get("unit", "unspecified"),
                    "sha256": chosen["document"]["pixel_file"]["sha256"]}

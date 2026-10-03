"""Native scientific image tools; deterministic data, separate display products.

No model-written code, inferred spectral roles, implicit resampling, or automatic
geological identification. ``operate`` is also the standalone JSON entry point.
"""
from contextlib import ExitStack
import csv
from io import BytesIO, StringIO
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator

from .contracts import ArtifactRef
from .imaging import MAX_BYTES, MAX_PIXELS, decoded_image, digest, png_bytes, task_path
from .tools import Tool, ToolDefinition, ToolFailure, ToolOutput, object_schema

TEXT = {"type": "string"}
PATH = {**TEXT, "minLength": 1, "description": "Existing task-relative file, not a URL. Source files stay unchanged."}
PREFIX = {**TEXT, "minLength": 1, "description": "New task-relative output directory; must not already exist."}
NUMBER = {"type": "number"}
RGB = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 255},
       "minItems": 3, "maxItems": 3, "description": "Explicit [red, green, blue] sample in 8-bit sRGB."}
ROI = {"type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 4, "maxItems": 4,
       "description": "[left, top, right, bottom] in EXIF-oriented source pixels, right/bottom exclusive. Exclude legends and axes."}
CALIBRATION = object_schema({
    "pixel_start": NUMBER, "value_start": NUMBER, "pixel_end": NUMBER, "value_end": NUMBER,
    "scale": {"type": "string", "enum": ["linear", "log10"]},
    "unit": {**TEXT, "minLength": 1, "maxLength": 64},
}, ["pixel_start", "value_start", "pixel_end", "value_end", "scale", "unit"])
CALIBRATION["description"] = "Two known tick positions and values. X uses image column; Y uses image row increasing downward. Log values must be positive. Never guess unreadable ticks."
SCHEMAS = {
    "GeoRasterIndexAnalysis": object_schema({
        "path": PATH, "output_dir": PREFIX,
        "index": {"type": "string", "enum": ["NDVI", "NDWI", "NBR"]},
        "bands": {**object_schema({k: {"type": "integer", "minimum": 1} for k in ("red", "green", "blue", "nir", "swir2")}),
                  "description": "Actual one-based spectral band roles, from source metadata. NDVI uses NIR/red, NDWI green/NIR, NBR NIR/SWIR2. Optional red/green/blue enable true-color preview."},
        "calibration_source": {**TEXT, "minLength": 1, "description": "Source/version confirming dataset scale and offset convert stored values to dimensionless reflectance. This statement is attribution, not automatic verification."},
        "valid_mask_path": {**PATH, "description": "Optional aligned one-band mask: valid finite values >0 are included. Supply QA-derived clear pixels; no cloud detection is guessed."},
        "breaks": {"type": "array", "items": {"type": "number", "exclusiveMinimum": -1, "exclusiveMaximum": 1},
                   "minItems": 1, "maxItems": 8, "description": "Strictly increasing display/statistical class edges. Default [0,0.2,0.5]; intervals are NOT land-cover labels."},
    }, ["path", "output_dir", "index", "bands", "calibration_source"]),
    "GeoRasterChangeAnalysis": object_schema({
        "before_path": PATH, "after_path": PATH, "output_dir": PREFIX,
        "threshold": {"type": "number", "exclusiveMinimum": 0, "description": "Symmetric change threshold in value_unit; classification is numerical, not causal attribution."},
        "value_unit": {**TEXT, "minLength": 1, "maxLength": 64},
    }, ["before_path", "after_path", "output_dir", "threshold", "value_unit"]),
    "GeoMapColorExtract": object_schema({
        "path": PATH, "output_dir": PREFIX, "roi": ROI,
        "classes": {"type": "array", "minItems": 1, "maxItems": 12, "items": object_schema({
            "label": {**TEXT, "minLength": 1, "maxLength": 100}, "rgb": RGB,
            "tolerance": {"type": "number", "minimum": 0, "maximum": 120,
                          "description": "Maximum Euclidean RGB distance in 8-bit sRGB; nearest eligible color wins; exact ties are excluded."},
        }, ["label", "rgb", "tolerance"])},
        "minimum_pixels": {"type": "integer", "minimum": 1, "default": 20,
                           "description": "Minimum 4-connected component size. Removed components are counted, never relabelled."},
        "reference_raster": {**PATH, "description": "Optional georeferenced GeoTIFF aligned pixel-for-pixel with the oriented image. Otherwise vectors use image pixels, not geographic coordinates."},
    }, ["path", "output_dir", "roi", "classes"]),
    "GeoPlotDigitize": object_schema({
        "path": PATH, "output_dir": PREFIX, "roi": ROI, "rgb": RGB,
        "tolerance": {"type": "number", "minimum": 0, "maximum": 120},
        "x_axis": CALIBRATION, "y_axis": CALIBRATION,
        "max_thickness": {"type": "integer", "minimum": 1, "maximum": 50, "default": 8,
                          "description": "Maximum vertical pixel span per column. Thicker or disconnected matches are ambiguous and omitted; no interpolation."},
    }, ["path", "output_dir", "roi", "rgb", "tolerance", "x_axis", "y_axis"]),
}
FILE = object_schema({"path": TEXT, "sha256": TEXT, "media_type": TEXT, "role": TEXT},
                     ["path", "sha256", "media_type", "role"])
OUTPUT_SCHEMA = object_schema({
    "analysis_type": TEXT, "manifest_path": TEXT,
    "outputs": {"type": "array", "items": FILE},
    "statistics": {"type": "object", "description": "Actual computed statistics; null means unavailable, never zero."},
    "warnings": {"type": "array", "items": TEXT},
}, ["analysis_type", "manifest_path", "outputs", "statistics", "warnings"])
DESCRIPTIONS = {
    "GeoRasterIndexAnalysis": "Compute calibrated NDVI/NDWI/NBR, interval statistics and scientific GeoTIFF; create aligned RGB/index/class layers with a reproducible analysis manifest.",
    "GeoRasterChangeAnalysis": "Compare aligned one-band rasters: calibrated after minus before, threshold classes, statistics and synchronized image layers. Reject grid/CRS mismatch; never silently resample.",
    "GeoMapColorExtract": "Extract candidate map regions by explicit legend colors inside a supplied ROI; create a mask, polygons and overlay. Color matching is not geological identification.",
    "GeoPlotDigitize": "Digitize one explicitly selected colored curve using supplied linear/log axis calibration. Save CSV, pixel uncertainty, selected-point overlay and reconstructed plot; omit ambiguous columns.",
}

# The runtime and exported asset definitions use these same schemas. Descriptions
# explain the physical contract without changing the accepted values or algorithms.
_PARAMETER_DESCRIPTIONS = {
    "index": "Index formula: NDVI=(NIR-red)/(NIR+red), NDWI=(green-NIR)/(green+NIR), NBR=(NIR-SWIR2)/(NIR+SWIR2). Results are dimensionless.",
    "value_unit": "Shared physical unit of the two comparable calibrated rasters and the change threshold, e.g. dimensionless or K. No unit conversion or physical comparability is inferred.",
    "classes": "Explicit legend labels, sRGB samples and tolerances for candidate region extraction; these do not infer geological identity.",
    "tolerance": "Maximum Euclidean distance from the selected curve color in 8-bit sRGB; unrelated matching pixels must be excluded by the ROI.",
}
for _schema in SCHEMAS.values():
    for _key, _description in _PARAMETER_DESCRIPTIONS.items():
        if _key in _schema["properties"] and not _schema["properties"][_key].get("description"):
            _schema["properties"][_key] = {**_schema["properties"][_key], "description": _description}
for _key, _description in {
    "analysis_type": "Analysis family identifying the scientific processing method, not a geological classification.",
    "manifest_path": "Task-relative analysis.geoanalysis.json containing input/output hashes, parameters, grid, layers, statistics and limitations.",
    "outputs": "Actual generated files with task-relative paths, SHA-256 hashes, MIME types and scientific/display roles.",
    "warnings": "Scientific and data-quality limitations that must accompany interpretation; not evidence of successful independent scientific certification.",
}.items():
    OUTPUT_SCHEMA["properties"][_key] = {**OUTPUT_SCHEMA["properties"][_key], "description": _description}


def fail(code, message):
    raise ToolFailure(code, message)


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")


def csv_bytes(rows):
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def source(workspace, name):
    p = task_path(workspace, name)
    if p.stat().st_size > MAX_BYTES:
        fail("input_too_large", "Use a documented spatial subset below the deployment's 8 MiB per-file limit")
    raw = p.read_bytes()
    return raw, {"path": name, "sha256": digest(raw)}


def open_raster(stack, raw):
    import rasterio
    from rasterio.io import MemoryFile
    stack.enter_context(rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"))
    mem = stack.enter_context(MemoryFile(raw))
    ds = stack.enter_context(mem.open())
    if ds.driver != "GTiff" or ds.width * ds.height > MAX_PIXELS:
        fail("invalid_raster", "Use a GeoTIFF within the documented 20 megapixel processing allowance")
    if not ds.crs or ds.transform.is_identity or not all(math.isfinite(v) for v in tuple(ds.transform)):
        fail("missing_georeferencing", "A real CRS and non-identity affine transform are required")
    if ds.transform.determinant == 0:
        fail("invalid_georeferencing", "Raster affine transform is singular")
    return ds


def same_grid(a, b):
    if a.crs != b.crs or a.shape != b.shape or a.transform != b.transform:
        fail("grid_mismatch", "Inputs must have exactly the same CRS, shape and affine grid; no implicit reprojection/resampling")


def calibrated(ds, band):
    import numpy as np
    if not 1 <= band <= ds.count or np.dtype(ds.dtypes[band - 1]).kind not in "iuf":
        fail("invalid_band", "Choose an existing real-valued one-based band")
    scale, offset = ds.scales[band - 1], ds.offsets[band - 1]
    if not math.isfinite(scale) or not math.isfinite(offset) or scale == 0:
        fail("invalid_calibration", "Raster scale must be finite/nonzero and offset finite")
    a = ds.read(band, masked=True).astype("float64")
    values = a.filled(np.nan) * scale + offset
    return values, ~np.ma.getmaskarray(a) & np.isfinite(values)


def grid_info(ds):
    factor = ds.crs.linear_units_factor[1] if ds.crs.is_projected else None
    area = abs(ds.transform.determinant) * factor ** 2 if factor is not None else None
    return {"width": ds.width, "height": ds.height, "crs": ds.crs.to_string(),
            "transform": list(ds.transform)[:6], "pixel_area_m2": area,
            "area_method": "planar CRS cell area" if area is not None else "unavailable for geographic CRS"}


def raster_bytes(ds, values, *, unit, dtype="float32", nodata=float("nan")):
    import numpy as np
    from rasterio.io import MemoryFile
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=ds.width, height=ds.height, count=1, dtype=dtype,
                      crs=ds.crs, transform=ds.transform, nodata=nodata, compress="deflate") as out:
            out.write(np.asarray(values, dtype=dtype), 1)
            out.update_tags(1, unit=unit)
        return mem.read()


def color_png(values, valid, low, high, colors):
    import numpy as np
    from PIL import Image
    t = np.zeros(values.shape, dtype=float)
    t[valid] = np.clip((values[valid] - low) / (high - low), 0, 1) if high > low else 0.5
    palette = np.asarray(colors)
    rgb = np.stack([np.interp(t, np.linspace(0, 1, len(palette)), palette[:, k]) for k in range(3)], axis=-1)
    return png_bytes(Image.fromarray(np.dstack((rgb.astype("uint8"), valid.astype("uint8") * 255))))


COLORS = [[151, 70, 50], [225, 200, 136], [243, 243, 214], [128, 174, 99], [26, 99, 68]]
CHANGE_COLORS = [[177, 61, 48], [250, 249, 239], [38, 114, 139]]


def interval_rows(values, valid, edges, area):
    import numpy as np
    selected = values[valid]
    if not len(selected):
        fail("no_valid_pixels", "No valid pixels remain; inspect masks, calibration and band roles")
    groups = np.searchsorted(edges, values, side="right")
    limits = [-math.inf, *edges, math.inf]
    rows = []
    for k in range(len(edges) + 1):
        count = int(np.count_nonzero(valid & (groups == k)))
        lo, hi = limits[k:k + 2]
        rows.append({"class_id": k + 1, "interval": f"[{lo:g}, {hi:g})", "pixel_count": count,
                     "fraction_valid": count / len(selected), "area_m2": count * area if area is not None else None})
    stats = {"valid_pixels": len(selected), "excluded_pixels": int(valid.size - len(selected)),
             "minimum": float(selected.min()), "maximum": float(selected.max()),
             "mean": float(selected.mean()), "standard_deviation": float(selected.std()),
             "valid_area_m2": len(selected) * area if area is not None else None}
    return np.where(valid, groups + 1, 0).astype("uint8"), rows, stats


def publish(workspace, args, kind, title, inputs, files, layers, stats, warnings, *, grid=None, legend=None, pixel_file=None):
    prefix = args["output_dir"].rstrip("/")
    target = task_path(workspace, prefix, output=True)
    records = [{"path": prefix + "/" + name, "sha256": digest(raw), "media_type": media, "role": role}
               for name, (raw, media, role) in files.items()]
    by_name = {r["path"].split("/")[-1]: r for r in records}
    resolved_layers = [{"id": name, "label": label, **by_name[name]} for name, label in layers]
    manifest = {"schema": "geoagent.scientific-image/v1", "analysis_type": kind, "title": title,
                "inputs": inputs, "parameters": args, "grid": grid, "layers": resolved_layers,
                "legend": legend or [], "statistics": stats, "warnings": warnings, "outputs": records,
                "pixel_file": by_name[pixel_file] if pixel_file else None}
    manifest_name = prefix + "/analysis.geoanalysis.json"
    manifest_raw = json_bytes(manifest)
    payloads = {**files, "analysis.geoanalysis.json": (manifest_raw, "application/json", "analysis_manifest")}
    if any(len(raw) > MAX_BYTES for raw, _, _ in payloads.values()):
        fail("output_too_large", "An output exceeds 8 MiB; choose a documented smaller input subset")
    if sum(len(raw) for raw, _, _ in payloads.values()) > 48 * 1024 * 1024:
        fail("output_too_large", "Output bundle exceeds 48 MiB; use a smaller spatial subset")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()  # Exclusive directory creation protects all existing outputs.
    for name, (raw, _, _) in payloads.items():
        with (target / name).open("xb") as stream:
            stream.write(raw)
    records.append({"path": manifest_name, "sha256": digest(manifest_raw), "media_type": "application/json", "role": "analysis_manifest"})
    return {"analysis_type": kind, "manifest_path": manifest_name, "outputs": records, "statistics": stats, "warnings": warnings}


def raster_analysis(name, args, workspace):
    import numpy as np
    from PIL import Image
    change = name == "GeoRasterChangeAnalysis"
    with ExitStack() as stack:
        raw, origin = source(workspace, args["before_path"] if change else args["path"])
        ds = open_raster(stack, raw)
        grid = grid_info(ds)
        origins = [origin]
        warnings = ["Class intervals are numerical bins, not automatic land-cover or geological labels."]
        if grid["pixel_area_m2"] is None:
            warnings.append("Geographic CRS: square-metre area is not computed from square degrees.")
        files, layers = {}, []
        if change:
            other, other_origin = source(workspace, args["after_path"])
            after = open_raster(stack, other)
            same_grid(ds, after)
            if ds.count != 1 or after.count != 1:
                fail("invalid_band", "Change analysis requires two one-band scientific rasters")
            a, va = calibrated(ds, 1)
            b, vb = calibrated(after, 1)
            for item in (ds, after):
                declared = item.tags(1).get("unit")
                if declared and declared != args["value_unit"]:
                    fail("unit_mismatch", "Declared raster unit conflicts with value_unit")
            valid = va & vb
            values = b - a
            edges = [-args["threshold"], args["threshold"]]
            unit, kind, title = args["value_unit"], "raster_change", "Raster change: after minus before"
            origins.append(other_origin)
            if not valid.any():
                fail("no_valid_pixels", "No overlapping valid pixels")
            low, high = float(min(a[valid].min(), b[valid].min())), float(max(a[valid].max(), b[valid].max()))
            for filename, array, label in (("before.png", a, "Before"), ("after.png", b, "After")):
                files[filename] = (color_png(array, valid, low, high, COLORS), "image/png", "aligned_preview")
                layers.append((filename, label))
            limit = max(float(np.abs(values[valid]).max()), args["threshold"])
            preview = color_png(values, valid, -limit, limit, CHANGE_COLORS)
            legend = [{"value": v, "color": color} for v, color in zip([-limit, 0, limit], CHANGE_COLORS)]
            warnings.append("Change is not causal attribution. Inputs must represent comparable quantities and processing.")
        else:
            roles = {"NDVI": ("nir", "red"), "NDWI": ("green", "nir"), "NBR": ("nir", "swir2")}[args["index"]]
            bands = args["bands"]
            if any(k not in bands for k in roles) or bands.get(roles[0]) == bands.get(roles[1]):
                fail("missing_spectral_bands", "Supply distinct actual bands for " + "/".join(roles))
            a, va = calibrated(ds, bands[roles[0]])
            b, vb = calibrated(ds, bands[roles[1]])
            valid = va & vb & (a >= 0) & (b >= 0) & ((a + b) > 0)
            if "valid_mask_path" in args:
                mask_raw, mask_origin = source(workspace, args["valid_mask_path"])
                mask_ds = open_raster(stack, mask_raw)
                same_grid(ds, mask_ds)
                mask, vm = calibrated(mask_ds, 1)
                valid &= vm & (mask > 0)
                origins.append(mask_origin)
            else:
                warnings.append("No quality/cloud mask supplied: clouds, haze, shadows and snow are not automatically removed.")
            values = np.full(a.shape, np.nan)
            np.divide(a - b, a + b, out=values, where=valid)
            edges = args.get("breaks", [0, 0.2, 0.5])
            if any(x >= y for x, y in zip(edges, edges[1:])):
                fail("invalid_arguments", "Breaks must be strictly increasing")
            unit, kind, title = "dimensionless", "raster_index", args["index"] + " analysis"
            preview = color_png(values, valid, -1, 1, COLORS)
            legend = [{"value": v, "color": color} for v, color in zip([-1, -.5, 0, .5, 1], COLORS)]
            if all(k in bands for k in ("red", "green", "blue")):
                channels, rgb_valid = [], valid.copy()
                for role in ("red", "green", "blue"):
                    channel, mask = calibrated(ds, bands[role])
                    rgb_valid &= mask
                    channels.append(np.rint(np.clip(np.nan_to_num(channel) / .3, 0, 1) * 255).astype("uint8"))
                rgb = np.dstack((*channels, rgb_valid.astype("uint8") * 255))
                files["source.png"] = (png_bytes(Image.fromarray(rgb)), "image/png", "true_color_preview")
                layers.append(("source.png", "RGB: 0-0.3 reflectance display stretch"))
            else:
                files["source.png"] = (color_png(a, valid, 0, .5, [[0, 0, 0], [255, 255, 255]]), "image/png", "single_band_preview")
                layers.append(("source.png", roles[0] + ": 0-0.5 reflectance display stretch"))
            warnings.append("Negative reflectance, NoData and zero denominators are excluded; scale/offset are applied before division.")
        valid &= np.isfinite(values)
        classes, rows, stats = interval_rows(values, valid, edges, grid["pixel_area_m2"])
        stats["unit"] = unit
        scientific = np.where(valid, values, np.nan)
        files.update({"values.tif": (raster_bytes(ds, scientific, unit=unit), "image/tiff", "scientific_raster"),
                      "classes.tif": (raster_bytes(ds, classes, unit="class_id", dtype="uint8", nodata=0), "image/tiff", "class_raster"),
                      "analysis.png": (preview, "image/png", "analysis_preview"),
                      "classes.png": (color_png(classes, valid, 1, len(rows), COLORS), "image/png", "class_preview"),
                      "statistics.csv": (csv_bytes(rows), "text/csv", "class_statistics")})
        layers.extend([("analysis.png", title), ("classes.png", "Numerical classes")])
        return publish(workspace, args, kind, title, origins, files, layers, stats, warnings,
                       grid=grid, legend=legend, pixel_file="values.tif")


def image_roi(args, workspace):
    import numpy as np
    raw, origin = source(workspace, args["path"])
    image, _ = decoded_image(raw)
    left, top, right, bottom = args["roi"]
    if not left < right <= image.width or not top < bottom <= image.height:
        fail("invalid_roi", "ROI must be a nonempty rectangle within the EXIF-oriented image")
    rgba = np.asarray(image)
    roi = np.zeros(rgba.shape[:2], dtype=bool)
    roi[top:bottom, left:right] = True
    roi &= rgba[..., 3] > 0
    return image, rgba, roi, origin


def map_extract(args, workspace):
    import numpy as np
    from PIL import Image
    from scipy.ndimage import label
    from rasterio.features import shapes
    from rasterio.transform import Affine
    from rasterio.warp import transform_geom
    image, rgba, roi, origin = image_roi(args, workspace)
    entries = args["classes"]
    if len({e["label"] for e in entries}) != len(entries):
        fail("invalid_arguments", "Class labels must be unique")
    best = np.full(roi.shape, np.inf)
    chosen = np.zeros(roi.shape, dtype="uint8")
    tied = np.zeros(roi.shape, dtype=bool)
    for i, item in enumerate(entries, 1):
        delta = rgba[..., :3].astype(float) - np.asarray(item["rgb"])
        distance = np.square(delta).sum(axis=2)
        eligible = roi & (distance <= item["tolerance"] ** 2)
        closer = eligible & (distance < best)
        tied[closer] = False
        tied |= eligible & (distance == best)
        chosen[closer] = i
        best[closer] = distance[closer]
    chosen[tied] = 0
    removed = 0
    for i in range(1, len(entries) + 1):
        components, _ = label(chosen == i)
        sizes = np.bincount(components.ravel())
        remove = (components > 0) & (sizes[components] < args.get("minimum_pixels", 20))
        removed += int(remove.sum())
        chosen[remove] = 0
    if not chosen.any():
        fail("no_matching_regions", "No regions remain; inspect explicit colors, ROI and component threshold")
    transform, crs, grid, origins = Affine.identity(), None, None, [origin]
    if "reference_raster" in args:
        raw, reference = source(workspace, args["reference_raster"])
        with ExitStack() as stack:
            ds = open_raster(stack, raw)
            if ds.shape != chosen.shape:
                fail("grid_mismatch", "Reference raster dimensions must match the oriented image exactly")
            transform, crs, grid = ds.transform, ds.crs, grid_info(ds)
        origins.append(reference)
    features = []
    for geometry, index in shapes(chosen, mask=chosen > 0, transform=transform, connectivity=4):
        if len(features) >= 10000:
            fail("too_many_regions", "More than 10,000 candidate regions; narrow ROI or increase minimum_pixels")
        if crs:
            geometry = transform_geom(crs, "EPSG:4326", geometry, precision=-1)
        features.append({"type": "Feature", "properties": {"class_id": int(index), "label": entries[int(index) - 1]["label"],
                         "status": "color-match candidate; not geological identification"}, "geometry": geometry})
    overlay = np.zeros_like(rgba)
    rows = []
    area = grid["pixel_area_m2"] if grid else None
    for i, entry in enumerate(entries, 1):
        selected = chosen == i
        overlay[selected] = [*entry["rgb"], 185]
        count = int(selected.sum())
        rows.append({"class_id": i, "label": entry["label"], "pixels": count,
                     "area_m2": count * area if area is not None else None})
    vector_name = "regions.geojson" if crs else "regions.pixel.json"
    collection = {"type": "FeatureCollection", "features": features}
    if not crs:
        collection["coordinate_space"] = "oriented image pixel edges; x right, y down; NOT RFC7946 geographic GeoJSON"
    files = {"source.png": (png_bytes(image), "image/png", "oriented_source_preview"),
             "overlay.png": (png_bytes(Image.fromarray(overlay)), "image/png", "candidate_overlay"),
             "mask.png": (png_bytes(Image.fromarray(chosen)), "image/png", "class_id_mask"),
             vector_name: (json_bytes(collection), "application/geo+json" if crs else "application/json", "candidate_vectors"),
             "statistics.csv": (csv_bytes(rows), "text/csv", "class_statistics")}
    stats = {"candidate_regions": len(features), "matched_pixels": int((chosen > 0).sum()),
             "ambiguous_pixels": int(tied.sum()), "removed_small_component_pixels": removed,
             "roi_valid_pixels": int(roi.sum()), "coordinate_space": "EPSG:4326 vectors" if crs else "image pixels"}
    warnings = ["Color matching cannot determine rock type, age or fault identity; labels are user-supplied hypotheses.",
                "Text, hatching and similar legend colors can contaminate candidates. Inspect overlays and correct the ROI/colors."]
    if crs:
        warnings.append("Pixel alignment with reference raster is a caller assertion; equal dimensions alone do not establish registration.")
    else:
        warnings.append("No georeferencing supplied; physical area and geographic coordinates are not reported.")
    return publish(workspace, args, "map_colors", "Map color candidates", origins, files,
                   [("source.png", "Original map"), ("overlay.png", "Candidate regions")], stats, warnings,
                   grid=grid, legend=[{"label": e["label"], "color": e["rgb"]} for e in entries])


def axis_converter(axis, lo, hi):
    p0, p1 = axis["pixel_start"], axis["pixel_end"]
    v0, v1 = axis["value_start"], axis["value_end"]
    if p0 == p1 or v0 == v1 or min(p0, p1) > lo or max(p0, p1) < hi:
        fail("invalid_calibration", "Distinct axis anchors must bracket the entire plot ROI; no extrapolation")
    logarithmic = axis["scale"] == "log10"
    if logarithmic:
        if min(v0, v1) <= 0:
            fail("invalid_calibration", "Logarithmic axis values must be positive")
        v0, v1 = math.log10(v0), math.log10(v1)
    def convert(pixel):
        value = v0 + (pixel - p0) / (p1 - p0) * (v1 - v0)
        return 10 ** value if logarithmic else value
    return convert


def digitize(args, workspace):
    import numpy as np
    from PIL import Image, ImageDraw
    image, rgba, roi, origin = image_roi(args, workspace)
    left, top, right, bottom = args["roi"]
    x = axis_converter(args["x_axis"], left, right - 1)
    y = axis_converter(args["y_axis"], top, bottom - 1)
    distance = np.square(rgba[..., :3].astype(float) - np.asarray(args["rgb"])).sum(axis=2)
    matched = roi & (distance <= args["tolerance"] ** 2)
    rows, ambiguous, missing = [], 0, 0
    overlay = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(overlay)
    for col in range(left, right):
        ys = np.flatnonzero(matched[:, col])
        if not len(ys):
            missing += 1
            continue
        if ys[-1] - ys[0] + 1 > args.get("max_thickness", 8) or (len(ys) > 1 and np.diff(ys).max() > 1):
            ambiguous += 1
            continue
        row = float(np.median(ys))
        ends = [y(float(ys[0])), y(float(ys[-1]))]
        rows.append({"pixel_column": col, "pixel_row": row, "x": x(col), "y": y(row),
                     "y_pixel_span_min": min(ends), "y_pixel_span_max": max(ends),
                     "x_unit": args["x_axis"]["unit"], "y_unit": args["y_axis"]["unit"]})
        draw.ellipse((col - 1, row - 1, col + 1, row + 1), fill=(224, 79, 36, 220))
    if len(rows) < 2:
        fail("insufficient_curve", "Fewer than two unambiguous columns; inspect ROI, curve color and calibration")
    plot = Image.new("RGB", (900, 520), "#fafbf7")
    painter = ImageDraw.Draw(plot)
    painter.line([(65, 35), (65, 460), (870, 460)], fill="#506459", width=2)
    # Reconstructed coordinates use the supplied axis scales, not arbitrary data extents.
    for point in rows:
        px = 65 + (point["pixel_column"] - left) / max(1, right - left - 1) * 805
        py = 35 + (point["pixel_row"] - top) / max(1, bottom - top - 1) * 425
        painter.ellipse((px - 1, py - 1, px + 1, py + 1), fill="#267860")
    painter.text((65, 475), f"x: {x(left):.6g} to {x(right - 1):.6g} ({args['x_axis']['scale']})", fill="#263a31")
    painter.text((65, 8), f"y top/bottom: {y(top):.6g} / {y(bottom - 1):.6g} ({args['y_axis']['scale']})", fill="#263a31")
    files = {"source.png": (png_bytes(image), "image/png", "oriented_source_preview"),
             "overlay.png": (png_bytes(overlay), "image/png", "digitized_point_overlay"),
             "reconstructed.png": (png_bytes(plot), "image/png", "reconstructed_plot"),
             "curve.csv": (csv_bytes(rows), "text/csv", "digitized_data")}
    stats = {"extracted_columns": len(rows), "ambiguous_columns": ambiguous, "unmatched_columns": missing,
             "x_unit": args["x_axis"]["unit"], "y_unit": args["y_axis"]["unit"], "interpolated_points": 0}
    warnings = ["Digitized values approximate rendered pixel positions, not the author's original measurements.",
                "Pixel span is not a statistical confidence interval; calibration uncertainty is not estimated.",
                "Ambiguous/disconnected columns are omitted. No interpolation or invented missing samples."]
    return publish(workspace, args, "plot_curve", "Calibrated curve digitization", [origin], files,
                   [("source.png", "Original figure"), ("overlay.png", "Extracted points")], stats, warnings)


def operate(name, args, *, workspace):
    try:
        json.dumps(args, allow_nan=False)
        Draft202012Validator(SCHEMAS[name]).validate(args)
    except Exception as exc:
        fail("invalid_arguments", str(exc).splitlines()[0])
    if name in ("GeoRasterIndexAnalysis", "GeoRasterChangeAnalysis"):
        return raster_analysis(name, args, workspace)
    if name == "GeoMapColorExtract":
        return map_extract(args, workspace)
    return digitize(args, workspace)


def register_scientific_image_tools(registry):
    for name, description in DESCRIPTIONS.items():
        def handler(args, ctx, tool_name=name):
            ctx.check()
            result = operate(tool_name, args, workspace=ctx.workspace)
            return ToolOutput(result, tuple(ArtifactRef(o["path"], o["media_type"], ctx.call_id) for o in result["outputs"]))
        paths = tuple(k for k in ("path", "before_path", "after_path", "valid_mask_path", "reference_raster")
                      if k in SCHEMAS[name]["properties"])
        registry.register(Tool(ToolDefinition(name, description,
            "Use the matching scientific image skill. Supply actual files, explicit spectral roles or calibration; never guess missing prerequisites.",
            SCHEMAS[name], OUTPUT_SCHEMA), handler, input_paths=paths))

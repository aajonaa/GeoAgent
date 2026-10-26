"""Source-only remote sensing adapters. No imports execute scientific kernels.

Parent staging is required before collection_contracts.operation can resolve IDs.
All arrays are bounded, explicitly georeferenced tiles, not implicit image files.
No operation downloads data, installs packages, or accepts a callable/command.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import threading
import time

from .collection_contracts import operation, reject

_MAX_ELEMENTS = 262144
_OTB_COMMIT = "154726b379fdb39b481ee8fd793fbd3d584884e6"
_OTB_APPS = frozenset({
    "OpticalCalibration", "Pansharpening", "MultivariateAlterationDetector",
    "SARDecompositions", "SARPolarSynth",
})


def _np():
    import numpy as np
    return np


def _array(value, name, ndim=None):
    np = _np()
    try:
        raw = np.asarray(value)
        if raw.dtype.kind not in "iuf" or raw.size == 0 or raw.size > _MAX_ELEMENTS:
            reject(name + ": nonempty bounded numeric array required")
        x = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError):
        reject(name + ": rectangular numeric array required")
    if not np.isfinite(x).all() or np.any(np.abs(x) > 1e15):
        reject(name + ": finite values with magnitude <= 1e15 required")
    if ndim is not None and x.ndim != ndim:
        reject(name + ": incorrect dimensionality")
    return x


def _grid(args, complete=False):
    np = _np()
    from rasterio.crs import CRS
    from rasterio.transform import Affine
    g = args["grid"]
    mask = np.asarray(g["mask"])
    if mask.dtype.kind != "b" or mask.ndim != 2:
        reject("grid.mask must be a rectangular boolean matrix")
    h, w = mask.shape
    if not (2 <= h <= 128 and 2 <= w <= 128) or not mask.any():
        reject("grid must be 2..128 pixels per dimension with a valid pixel")
    if complete and not mask.all():
        reject("this neighborhood/global kernel requires a complete valid tile; no filling")
    if not re.fullmatch(r"EPSG:[1-9][0-9]{2,6}", g["crs"]):
        reject("explicit EPSG CRS required")
    crs = CRS.from_user_input(g["crs"])
    if not (crs.is_projected or crs.is_geographic):
        reject("a projected or geographic horizontal CRS is required")
    affine = _array(g["affine"], "grid.affine", 1)
    if affine.shape != (6,):
        reject("affine order is a,b,c,d,e,f")
    transform = Affine(*affine.tolist())
    if abs(transform.determinant) < 1e-12:
        reject("singular affine transform")
    if crs.is_geographic:
        for col, row in ((0, 0), (w, 0), (0, h), (w, h)):
            lon, lat = transform * (col, row)
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                reject("geographic grid bounds exceed longitude/latitude ranges")
    nodata = g["nodata"]
    if nodata is not None and (not math.isfinite(nodata) or abs(nodata) > 1e15):
        reject("nodata must be null or a finite numeric sentinel")
    return {"mask": mask.copy(), "crs": crs, "transform": transform,
            "nodata": nodata, "height": h, "width": w}


def _cube(args, key, grid, bands=None, low=None, high=None):
    np = _np()
    x = _array(args[key], key)
    if x.ndim == 2:
        x = x[None, :, :]
    if x.ndim != 3 or x.shape[-2:] != grid["mask"].shape or x.shape[0] > 64:
        reject(key + ": expected band-first array on the declared grid")
    if bands is not None and x.shape[0] != bands:
        reject(key + ": incorrect number of bands")
    valid = x[:, grid["mask"]]
    if grid["nodata"] is not None and np.any(valid == grid["nodata"]):
        reject(key + ": nodata sentinel marked valid")
    if low is not None and np.any(valid < low):
        reject(key + ": below physical lower bound")
    if high is not None and np.any(valid > high):
        reject(key + ": above physical upper bound")
    return x


def _complex(args, key, grid, bands=1):
    np = _np()
    real = _cube(args, key + "_real", grid, bands)
    imag = _cube(args, key + "_imag", grid, bands)
    z = real + 1j * imag
    if np.any(np.abs(z[:, grid["mask"]]) > 1e9):
        reject("complex amplitude exceeds bounded tile range")
    return z


def _csv(root, name, header, rows):
    p = Path(root) / name
    if p.exists():
        reject("artifact already exists", "invalid_output_directory")
    with p.open("x", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def _stats(values, field, unit):
    np = _np()
    x = np.asarray(values)
    if x.size == 0:
        return {"field": field, "unit": unit, "count": 0,
                "minimum": 0.0, "maximum": 0.0, "mean": 0.0}
    if np.iscomplexobj(x) or not np.isfinite(x).all():
        reject("nonfinite or complex numeric result", "invalid_output")
    return {"field": field, "unit": unit, "count": int(x.size),
            "minimum": float(x.min()), "maximum": float(x.max()), "mean": float(x.mean())}


def _write_tiff(path, data, grid, labels=None, units=None):
    np = _np()
    import rasterio
    x = np.asarray(data)
    if x.ndim == 2:
        x = x[None, :, :]
    mask = grid["mask"]
    if x.ndim != 3 or x.shape[-2:] != mask.shape or not np.isfinite(x[:, mask]).all():
        reject("unexpected raster shape or finite-value failure", "invalid_output")
    nodata = grid["nodata"]
    if nodata is not None and np.any(x[:, mask] == nodata):
        reject("output collides with source nodata sentinel", "invalid_output")
    x = x.copy()
    x[:, ~mask] = nodata if nodata is not None else 0
    dtype = "complex128" if np.iscomplexobj(x) else "float64"
    with rasterio.open(path, "w", driver="GTiff", height=grid["height"],
                       width=grid["width"], count=x.shape[0], dtype=dtype,
                       crs=grid["crs"], transform=grid["transform"],
                       nodata=nodata, compress="deflate") as ds:
        ds.write(x.astype(dtype))
        ds.write_mask(mask.astype("uint8") * 255)
        for b in range(x.shape[0]):
            if labels:
                ds.set_band_description(b + 1, labels[b])
            if units:
                ds.update_tags(b + 1, units=units[b])
        ds.update_tags(source_status="source_revised_unverified",
                       scientific_claim="not mineral identification")


def _raster_result(root, data, grid, labels, units, warnings=()):
    np = _np()
    x = np.asarray(data)
    if x.ndim == 2:
        x = x[None, :, :]
    if x.ndim != 3 or x.shape[0] != len(labels) or len(units) != len(labels):
        reject("unexpected result band layout", "invalid_output")
    if x.size > _MAX_ELEMENTS or not grid["mask"].any():
        reject("empty or oversized raster result", "invalid_output")
    _write_tiff(Path(root) / "result.tif", x, grid, labels, units)
    statistics = [_stats(x[b, grid["mask"]], labels[b], units[b]) for b in range(x.shape[0])]
    _csv(root, "band-summary.csv", ["band", "label", "unit", "valid_pixels", "minimum", "maximum", "mean"],
         [[i + 1, s["field"], s["unit"], s["count"], s["minimum"], s["maximum"], s["mean"]]
          for i, s in enumerate(statistics)])
    return {"kind": "raster", "shape": list(x.shape), "valid_count": int(grid["mask"].sum()),
            "statistics": statistics, "units": {"result": "per-band unit in statistics",
            "coordinates": grid["crs"].to_string(), "auxiliary": "pixel"},
            "warnings": list(warnings)}


def _table_result(root, name, header, rows, numeric, unit, warnings=()):
    values = _array(numeric, "result") if len(numeric) else _np().array([], dtype=float)
    _csv(root, name, header, rows)
    return {"kind": "table", "shape": [len(rows), len(header)], "valid_count": len(rows),
            "statistics": [_stats(values, name, unit)],
            "units": {"result": unit, "coordinates": "as named in CSV columns", "auxiliary": "dimensionless"},
            "warnings": list(warnings)}


def _rank(x, required, name):
    np = _np()
    s = np.linalg.svd(x, compute_uv=False)
    if s.size < required or s[required - 1] <= max(s[0], 1e-15) * 1e-8:
        reject(name + ": rank deficient or ill-conditioned")


def _insar(args):
    meta = args["sar"]
    if meta["state"] != "coregistered_unwrapped_insar" or not meta["processing_provenance"].strip():
        reject("processed SAR acquisition provenance is required; RGB is not SAR")
    if meta["los_convention"] != "positive_toward_sensor":
        reject("LOS sign must be positive toward sensor")
    if not .001 <= meta["wavelength_m"] <= 2:
        reject("wavelength outside supported radar range")
    _private_mintpy()


def _private_mintpy():
    if os.environ.get("EXPANSION501_REMOTE_PROFILE") != "mintpy-1.6.4-cpu":
        reject("requires parent-created private mintpy-1.6.4-cpu environment", "missing_dependency")
    for package, expected in (("mintpy", "1.6.4"), ("numpy", "2.1.3"), ("scipy", "1.15.3")):
        if importlib.metadata.version(package) != expected:
            reject(package + ": private profile version mismatch", "incompatible_dependency")
    if os.environ.get("CUDA_VISIBLE_DEVICES") not in ("", "-1"):
        reject("private CPU profile must disable CUDA explicitly", "invalid_arguments")


def _dates(values):
    try:
        dates = [dt.datetime.strptime(v, "%Y%m%d") for v in values]
    except (ValueError, TypeError):
        reject("dates must be real YYYYMMDD calendar dates")
    if len(values) < 2 or len(values) > 64 or dates != sorted(set(dates)):
        reject("require 2..64 strictly increasing unique dates")
    return dates


def _pairs(args):
    dates = _dates(args["dates"])
    pairs = args["pairs"]
    if not 1 <= len(pairs) <= 256 or len(set(pairs)) != len(pairs):
        reject("require 1..256 unique interferogram pairs")
    for pair in pairs:
        parts = pair.split("_")
        if len(parts) != 2 or any(d not in args["dates"] for d in parts) or parts[0] >= parts[1]:
            reject("pairs must be earlier_later YYYYMMDD_YYYYMMDD from dates")
    used = {d for pair in pairs for d in pair.split("_")}
    if used != set(args["dates"]):
        reject("every acquisition must participate in the network")
    return dates, pairs


@operation("GeoRemotePhaseUnwrap")
def phase_unwrap(args, output_dir=None):
    np = _np()
    from skimage.restoration import unwrap_phase
    g = _grid(args, complete=True)
    image = _cube(args, "phase", g, 1, -math.pi, math.pi)[0]
    if args["phase_unit"] != "rad":
        reject("wrapped phase requires radians")
    result = unwrap_phase(image, wrap_around=False, rng=0)
    if result.shape != image.shape:
        reject("unexpected unwrapping shape", "invalid_output")
    return _raster_result(output_dir, result, g, ["unwrapped_phase"], ["rad"],
                          ["Absolute integer-cycle offset is unobservable; discontinuities need independent assessment."])


@operation("GeoRemoteBrightnessTemperature")
def brightness_temperature(args, output_dir=None):
    np = _np()
    from pyspectral.blackbody import blackbody_rad2temp
    g = _grid(args)
    radiance = _cube(args, "radiance", g, 1, 1e-20, 1e15)[0]
    wavelength = args["wavelength_m"]
    if args["radiance_unit"] != "W m-2 sr-1 m-1" or not 1e-6 <= wavelength <= 1e-3:
        reject("spectral radiance per metre and wavelength 1..1000 micrometres required")
    output = np.zeros(radiance.shape)
    values = np.asarray(blackbody_rad2temp(wavelength, radiance[g["mask"]])).reshape(-1)
    if values.size != int(g["mask"].sum()) or np.any(values <= 0) or np.any(values > 10000):
        reject("unsupported brightness temperature", "invalid_output")
    output[g["mask"]] = values
    return _raster_result(output_dir, output, g, ["brightness_temperature"], ["K"],
                          ["Monochromatic blackbody-equivalent temperature; no emissivity or atmospheric correction."])


@operation("GeoSARCoherentChange")
def coherent_change(args, output_dir=None):
    np = _np()
    from sarpy.processing.sicd.ccd import mem
    g = _grid(args, complete=True)
    _sar_pair(args)
    reference = _complex(args, "reference", g)[0]
    secondary = _complex(args, "secondary", g)[0]
    n = args["window_size"]
    if n < 3 or n > 15 or n % 2 != 1 or min(reference.shape) < n:
        reject("odd correlation window 3..15 must fit tile")
    if np.any(np.abs(reference) < 1e-12) or np.any(np.abs(secondary) < 1e-12):
        reject("zero-amplitude pixels are unsupported; no implicit coherence filling")
    complex_ccd, phase = mem(reference, secondary, corr_window_size=n)
    complex_ccd = np.asarray(complex_ccd)
    phase = np.asarray(phase)
    if complex_ccd.shape != reference.shape or phase.shape != reference.shape:
        reject("unexpected coherent-change shape", "invalid_output")
    if not np.isfinite(complex_ccd).all() or not np.isfinite(phase).all() or np.iscomplexobj(phase):
        reject("nonfinite correlation or non-real upstream phase", "invalid_output")
    coherence = np.abs(complex_ccd)
    if np.any(coherence < 0) or np.any(coherence > 1 + 1e-8):
        reject("coherence magnitude outside [0,1] within 1e-8 roundoff tolerance", "invalid_output")
    border = n // 2
    g["mask"][:border] = False
    g["mask"][-border:] = False
    g["mask"][:, :border] = False
    g["mask"][:, -border:] = False
    return _raster_result(output_dir, np.stack([coherence, phase]), g,
                          ["complex_correlation_magnitude", "correlation_phase"],
                          ["dimensionless", "rad"],
                          ["Incomplete edge windows are masked; no deformation inversion. Bounds allow 1e-8 roundoff without clipping."])



def _sar_pair(args):
    meta = args["complex_sar"]
    if meta["state"] != "coregistered_complex_slc" or not meta["processing_provenance"].strip():
        reject("complex co-registered SLC provenance required; intensity/RGB is insufficient")
    if meta["reference_acquisition"] == meta["secondary_acquisition"]:
        reject("distinct reference and secondary acquisition identifiers required")
    if not .001 <= meta["wavelength_m"] <= 2:
        reject("radar wavelength outside supported range")


def _training(args, g):
    np = _np()
    from spectral.algorithms.algorithms import create_training_classes
    cube = _cube(args, "image", g, low=0, high=1)
    labels = _array(args["training_labels"], "training_labels", 2)
    if labels.shape != g["mask"].shape or np.any(labels != np.floor(labels)) or np.any(labels < 0):
        reject("training labels must be same-grid nonnegative integers")
    if np.any(labels[~g["mask"]] != 0):
        reject("masked pixels cannot have training labels")
    class_ids = sorted(int(x) for x in np.unique(labels) if x > 0)
    if not 2 <= len(class_ids) <= 16 or cube.shape[0] > 16:
        reject("require 2..16 classes and at most 16 spectral bands")
    image = np.moveaxis(cube, 0, -1)
    for label in class_ids:
        samples = image[labels == label]
        if samples.shape[0] <= cube.shape[0]:
            reject("each class needs more training pixels than bands")
        _rank(samples - samples.mean(axis=0), cube.shape[0], "training covariance")
    classes = create_training_classes(image, labels.astype("int32"), calc_stats=True)
    for item in classes:
        item.class_prob = 1.0 / len(class_ids)
    return image, classes, class_ids


@operation("GeoRemoteGaussianClassify")
def gaussian_classify(args, output_dir=None):
    np = _np()
    from spectral.algorithms.classifiers import GaussianClassifier
    g = _grid(args)
    image, classes, class_ids = _training(args, g)
    classifier = GaussianClassifier(classes)
    result = np.zeros(g["mask"].shape)
    result[g["mask"]] = [classifier.classify_spectrum(v) for v in image[g["mask"]]]
    if any(int(v) not in class_ids for v in result[g["mask"]]):
        reject("classifier omitted a requested class or produced an invalid label", "invalid_output")
    return _raster_result(output_dir, result, g, ["equal_prior_gaussian_class"], ["categorical_class_id"],
                          ["Training labels are user-defined spectral classes, not verified minerals or ore grades."])


@operation("GeoRemoteEndmemberDiscovery")
def endmember_discovery(args, output_dir=None):
    np = _np()
    from spectral.algorithms.algorithms import smacc
    g = _grid(args)
    cube = _cube(args, "image", g, low=0, high=1)
    pixels = cube[:, g["mask"]].T
    k = args["endmember_count"]
    if not 2 <= k <= min(16, cube.shape[0], pixels.shape[0]):
        reject("endmember count must be 2..min(16,bands,valid pixels)")
    _rank(pixels, k, "spectral samples")
    spectra, fractions, residual = smacc(pixels, min_endmembers=k, max_residual_norm=float("inf"))
    if spectra.shape != (k, cube.shape[0]) or fractions.shape != (pixels.shape[0], k) or residual.shape != pixels.shape:
        reject("SMACC returned an unexpected factorization shape", "invalid_output")
    if not all(np.isfinite(x).all() for x in (spectra, fractions, residual)):
        reject("nonfinite SMACC factorization", "invalid_output")
    _csv(output_dir, "mixture-coefficients.csv", ["valid_pixel_index"] + ["coefficient_" + str(i + 1) for i in range(k)],
         [[i] + row.tolist() for i, row in enumerate(fractions)])
    _csv(output_dir, "residual.csv", ["valid_pixel_index"] + ["band_" + str(i + 1) for i in range(cube.shape[0])],
         [[i] + row.tolist() for i, row in enumerate(residual)])
    return _table_result(output_dir, "discovered-endmembers.csv",
                         ["endmember"] + ["band_" + str(i + 1) for i in range(cube.shape[0])],
                         [[i + 1] + row.tolist() for i, row in enumerate(spectra)], spectra.ravel().tolist(),
                         "reflectance_fraction",
                         ["Data-derived extreme spectra only; not library identification. Coefficients are not ore fractions."])


@operation("GeoRemoteClassSeparability")
def class_separability(args, output_dir=None):
    from spectral.algorithms.algorithms import bdist
    g = _grid(args)
    _, classes, ids = _training(args, g)
    by_id = {int(c.index): c for c in classes}
    rows = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            distance = float(bdist(by_id[a], by_id[b]))
            if not math.isfinite(distance) or distance < -1e-10:
                reject("invalid Bhattacharyya class distance", "invalid_output")
            rows.append([a, b, distance])
    return _table_result(output_dir, "separability.csv", ["class_a", "class_b", "bhattacharyya_distance"],
                         rows, [r[2] for r in rows], "dimensionless")


@operation("GeoRemoteDenseOpticalFlow")
def dense_optical_flow(args, output_dir=None):
    np = _np()
    from skimage.registration import optical_flow_tvl1
    g = _grid(args, complete=True)
    reference = _cube(args, "reference", g, 1, 0, 1)[0]
    moving = _cube(args, "moving", g, 1, 0, 1)[0]
    if min(reference.shape) < 16 or np.std(reference) < 1e-6 or np.std(moving) < 1e-6:
        reject("optical flow requires textured tiles at least 16 x 16")
    flow = optical_flow_tvl1(reference, moving, attachment=15, tightness=.3,
                            num_warp=5, num_iter=10, tol=1e-4, prefilter=False, dtype=np.float32)
    if flow.shape != (2,) + reference.shape:
        reject("unexpected flow shape", "invalid_output")
    return _raster_result(output_dir, flow, g, ["row_displacement", "column_displacement"], ["pixel", "pixel"],
                          ["Brightness-constancy apparent image motion, not InSAR displacement or ground velocity."])


@operation("GeoRemoteProjectiveTiePoints")
def projective_tie_points(args, output_dir=None):
    np = _np()
    from skimage.transform import ProjectiveTransform
    source = _array(args["source_points"], "source_points", 2)
    target = _array(args["target_points"], "target_points", 2)
    query = _array(args["query_points"], "query_points", 2)
    if source.shape != target.shape or source.shape[1] != 2 or not 4 <= len(source) <= 128 or query.shape[1] != 2:
        reject("require 4..128 paired column,row points and 2-column queries")
    _rank(np.column_stack((source, np.ones(len(source)))), 3, "source tie points")
    _rank(np.column_stack((target, np.ones(len(target)))), 3, "target tie points")
    model = ProjectiveTransform.from_estimate(source, target)
    if model is None or not np.isfinite(model.params).all():
        reject("projective estimation failed", "invalid_output")
    projected = model(query)
    fitted = model(source)
    if projected.shape != query.shape or not np.isfinite(projected).all():
        reject("points map to projective infinity", "invalid_output")
    _csv(output_dir, "homography.csv", ["row", "h0", "h1", "h2"],
         [[i] + row.tolist() for i, row in enumerate(model.params)])
    _csv(output_dir, "tiepoint-residuals.csv", ["point", "column_error", "row_error"],
         [[i] + row.tolist() for i, row in enumerate(fitted - target)])
    return _table_result(output_dir, "projected-points.csv", ["point", "column", "row"],
                         [[i] + row.tolist() for i, row in enumerate(projected)], projected.ravel().tolist(),
                         "pixel", ["No image resampling or CRS transformation; tie-point systems must be explicitly the declared pixel frames."])


@operation("GeoRemoteTemplateLocate")
def template_locate(args, output_dir=None):
    np = _np()
    from skimage.feature import match_template
    g = _grid(args, complete=True)
    image = _cube(args, "image", g, 1)[0]
    template = _array(args["template"], "template", 2)
    if min(template.shape) < 2 or any(template.shape[i] >= image.shape[i] for i in (0, 1)) or np.std(template) < 1e-10:
        reject("nonconstant template must be smaller than the image in both dimensions")
    result = match_template(image, template, pad_input=False)
    expected = tuple(image.shape[i] - template.shape[i] + 1 for i in (0, 1))
    if result.shape != expected or np.any(np.abs(result) > 1 + 1e-6):
        reject("unexpected normalized correlation", "invalid_output")
    g.update(height=expected[0], width=expected[1], mask=np.ones(expected, bool))
    peak = np.unravel_index(np.argmax(result), result.shape)
    _csv(output_dir, "peak-placement.csv", ["top_row", "left_column", "normalized_correlation"],
         [[int(peak[0]), int(peak[1]), float(result[peak])]])
    return _raster_result(output_dir, result, g, ["template_placement_correlation"], ["dimensionless"],
                          ["Output pixels locate template upper-left corners, not template centers."])


@operation("GeoRemoteScaleSpaceBlobs")
def scale_space_blobs(args, output_dir=None):
    np = _np()
    from skimage.feature import blob_log
    g = _grid(args, complete=True)
    image = _cube(args, "image", g, 1, 0, 1)[0]
    if args["min_sigma"] >= args["max_sigma"] or args["max_sigma"] > min(image.shape) / 4:
        reject("sigma interval must increase and fit the tile")
    blobs = blob_log(image, min_sigma=args["min_sigma"], max_sigma=args["max_sigma"],
                     num_sigma=args["num_sigma"], threshold=args["threshold"], overlap=.5,
                     log_scale=False, exclude_border=False)
    if blobs.ndim != 2 or blobs.shape[1] != 3 or len(blobs) > 16384:
        reject("unexpected LoG blob output", "invalid_output")
    rows = []
    for row, col, sigma in blobs:
        x, y = g["transform"] * (col + .5, row + .5)
        rows.append([float(row), float(col), float(sigma), float(math.sqrt(2) * sigma), x, y])
    return _table_result(output_dir, "blobs.csv", ["row", "column", "sigma_pixels", "radius_convention_pixels", "map_x", "map_y"],
                         rows, blobs[:, 2].tolist(), "pixel",
                         ["Bright scale-space extrema; radius is a convention, not an ore-body boundary. CRS: " + g["crs"].to_string()])


@operation("GeoRemoteHoughLineEvidence")
def hough_line_evidence(args, output_dir=None):
    np = _np()
    from skimage.transform import hough_line
    g = _grid(args, complete=True)
    edges = _cube(args, "edges", g, 1, 0, 1)[0]
    if not np.all((edges == 0) | (edges == 1)) or not np.any(edges):
        reject("nonempty binary edge evidence required")
    theta = _array(args["theta_rad"], "theta_rad", 1)
    if np.any(np.diff(theta) <= 0) or np.any(theta < -math.pi / 2) or np.any(theta >= math.pi / 2):
        reject("theta must strictly increase in [-pi/2,pi/2)")
    accumulator, angles, distances = hough_line(edges.astype(bool), theta=theta)
    if accumulator.shape != (len(distances), len(angles)):
        reject("unexpected Hough parameter space", "invalid_output")
    rows = [[float(rho), float(angle), int(accumulator[i, j])]
            for i, rho in enumerate(distances) for j, angle in enumerate(angles)]
    return _table_result(output_dir, "hough-evidence.csv", ["rho_pixels", "normal_angle_rad", "votes"],
                         rows, accumulator.ravel().tolist(), "edge_pixel_votes",
                         ["Parameter space is not a georeferenced raster; line evidence is not a mapped geological fault."])


@operation("GeoRemoteWaveletPyramid")
def wavelet_pyramid(args, output_dir=None):
    np = _np()
    import pywt
    g = _grid(args, complete=True)
    image = _cube(args, "image", g, 1)[0]
    level = args["level"]
    if level < 1 or level > 5 or any(s % (2 ** level) for s in image.shape):
        reject("Haar periodization requires dimensions divisible by 2**level")
    coefficients = pywt.wavedec2(image, wavelet="haar", mode="periodization", level=level)
    rows = []
    energy = []
    pieces = [("approximation", level, coefficients[0])]
    for i, trio in enumerate(coefficients[1:]):
        for label, data in zip(("horizontal", "vertical", "diagonal"), trio):
            pieces.append((label, level - i, data))
    for label, scale, data in pieces:
        if not np.isfinite(data).all():
            reject("nonfinite wavelet coefficients", "invalid_output")
        energy.append([label, scale, float(np.square(data).sum())])
        for (r, c), value in np.ndenumerate(data):
            rows.append([label, scale, r, c, float(value)])
    _csv(output_dir, "scale-energy.csv", ["component", "level", "squared_coefficient_energy"], energy)
    return _table_result(output_dir, "wavelet-coefficients.csv", ["component", "level", "row", "column", "coefficient"],
                         rows, [r[-1] for r in rows], args["image_unit"],
                         ["Coefficient lattice is not assigned the source CRS/affine; Haar with periodization is fixed."])


@operation("GeoSARDopplerDeskew")
def doppler_deskew(args, output_dir=None):
    np = _np()
    from sarpy.processing.sicd.normalize_sicd import apply_skew_poly
    g = _grid(args, complete=True)
    _sar_pair(args)
    image = _complex(args, "slc", g)[0]
    rows = _array(args["row_positions_m"], "row_positions_m", 1)
    cols = _array(args["column_positions_m"], "column_positions_m", 1)
    poly = _array(args["delta_kcoa_poly"], "delta_kcoa_poly", 2)
    if rows.size != g["height"] or cols.size != g["width"] or max(poly.shape) > 4:
        reject("physical sample coordinates and Doppler polynomial dimensions mismatch")
    if np.any(np.diff(rows) <= 0) or np.any(np.diff(cols) <= 0):
        reject("SICD sample coordinates must be strictly increasing in metres")
    result = apply_skew_poly(image, poly, rows, cols, args["fft_sign"], dimension=0, forward=False)
    if result.shape != image.shape:
        reject("unexpected deskew shape", "invalid_output")
    return _raster_result(output_dir, np.stack([result.real, result.imag]), g,
                          ["deskewed_real", "deskewed_imag"], ["complex_amplitude", "complex_amplitude"],
                          ["Row/azimuth deskew only. Polynomial coefficient (i,j) has units cycles/m^(1+i+j)."])


@operation("GeoSARSubaperture")
def subaperture(args, output_dir=None):
    np = _np()
    from sarpy.processing.sicd.subaperture import subaperture_processing_array
    g = _grid(args, complete=True)
    _sar_pair(args)
    image = _complex(args, "slc", g)[0]
    start, stop = args["azimuth_fft_interval"]
    if not 0 <= start < stop <= image.shape[0] or stop - start < 2 or stop - start >= image.shape[0]:
        reject("proper subaperture interval with >=2 frequency samples required")
    result = subaperture_processing_array(image, (start, stop), image.shape[0], dimension=0)
    if result.shape != image.shape:
        reject("unexpected subaperture shape", "invalid_output")
    return _raster_result(output_dir, np.stack([result.real, result.imag]), g,
                          ["subaperture_real", "subaperture_imag"], ["complex_amplitude", "complex_amplitude"],
                          ["Fixed azimuth aperture. Carrier is reindexed by upstream; not radiometric calibration."])


def _native_file(root, relative):
    if not isinstance(relative, str) or "\\" in relative or ":" in relative:
        reject("invalid native manifest relative path", "missing_dependency")
    parts = relative.split("/")
    if any(p in ("", ".", "..") for p in parts):
        reject("invalid native manifest path", "missing_dependency")
    p = root.joinpath(*parts)
    if not p.resolve().is_relative_to(root) or any(q.is_symlink() for q in [p] + list(p.parents) if q != root.parent):
        reject("native manifest paths cannot escape or use links", "missing_dependency")
    if not p.is_file():
        reject("native manifest file missing", "missing_dependency")
    return p


def _sha256_file(path):
    if path.stat().st_size > 512 * 1024 * 1024:
        reject("native identity file too large", "missing_dependency")
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _otb_identity(app):
    if app not in _OTB_APPS or os.name != "posix":
        reject("this fixed OTB worker currently requires a parent-provisioned Linux CPU profile", "missing_dependency")
    value = os.environ.get("EXPANSION501_OTB_ROOT", "")
    if not value or not Path(value).is_absolute():
        reject("EXPANSION501_OTB_ROOT must name the private verified OTB prefix", "missing_dependency")
    root = Path(value)
    if root.is_symlink() or not root.is_dir() or any(p.is_symlink() for p in root.parents):
        reject("native prefix must be a real directory without linked ancestors", "missing_dependency")
    root = root.resolve()
    manifest_path = _native_file(root, "expansion501-identity.json")
    if manifest_path.stat().st_size > 131072:
        reject("oversized native identity manifest", "missing_dependency")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != "9.1.1" or manifest.get("source_commit") != _OTB_COMMIT:
        reject("OTB release/source identity mismatch", "incompatible_dependency")
    files = manifest.get("files")
    launcher_name = "bin/otbApplicationLauncherCommandLine"
    app_name = "lib/otb/applications/otbapp_" + app + ".so"
    if not isinstance(files, dict) or not 2 <= len(files) <= 512 or any(k not in files for k in (launcher_name, app_name)):
        reject("native manifest must cover launcher, selected application and its runtime dependencies", "missing_dependency")
    total = 0
    for relative, expected in files.items():
        path = _native_file(root, relative)
        total += path.stat().st_size
        if total > 1024 * 1024 * 1024 or not re.fullmatch(r"[0-9a-f]{64}", str(expected)):
            reject("invalid or oversized native identity lock", "missing_dependency")
        if _sha256_file(path) != expected:
            reject("native binary/dependency checksum mismatch", "incompatible_dependency")
    return root, root / launcher_name, manifest, _sha256_file(manifest_path)


def _bounded_process(command, cwd, env, timeout=120):
    logs = {"stdout": bytearray(), "stderr": bytearray()}
    exceeded = threading.Event()
    process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               shell=False, start_new_session=True)
    def collect(stream, key):
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                available = 65536 - len(logs[key])
                if len(chunk) > available:
                    exceeded.set()
                logs[key].extend(chunk[:max(available, 0)])
        finally:
            stream.close()
    threads = [threading.Thread(target=collect, args=(process.stdout, "stdout"), daemon=True),
               threading.Thread(target=collect, args=(process.stderr, "stderr"), daemon=True)]
    for t in threads:
        t.start()
    deadline = time.monotonic() + timeout
    failure = None
    try:
        while process.poll() is None:
            if exceeded.is_set():
                failure = "native stdout/stderr exceeded 64 KiB per stream"
                break
            if time.monotonic() >= deadline:
                failure = "native CPU deadline exceeded"
                break
            time.sleep(.05)
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        code = process.wait()
        for t in threads:
            t.join(timeout=2)
    if any(t.is_alive() for t in threads):
        reject("native process left open output pipes", "upstream_failure")
    if exceeded.is_set():
        failure = "native stdout/stderr exceeded 64 KiB per stream"
    if failure or code != 0:
        reject((failure or ("native process exited " + str(code))) + "; " +
               bytes(logs["stderr"]).decode("utf-8", errors="replace")[-1500:], "upstream_failure")
    return code, {k: bytes(v).decode("utf-8", errors="replace") for k, v in logs.items()}


def _otb(app, args, root, grid, inputs, cli, expected_bands, auxiliaries=None, complex_output=False):
    np = _np()
    import rasterio
    prefix, launcher, manifest, manifest_hash = _otb_identity(app)
    with tempfile.TemporaryDirectory(prefix="otb-private-", dir=root) as temp:
        work = Path(temp)
        for name, data in inputs.items():
            _write_tiff(work / (name + ".tif"), data, grid)
        for name, content in (auxiliaries or {}).items():
            (work / name).write_text(content, encoding="ascii")
        env = {"PATH": str(prefix / "bin") + ":/usr/bin:/bin", "HOME": str(work),
               "TMPDIR": str(work), "XDG_CACHE_HOME": str(work / "cache"),
               "CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "1",
               "OPENBLAS_NUM_THREADS": "1", "ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS": "1",
               "LD_LIBRARY_PATH": str(prefix / "lib"),
               "OTB_APPLICATION_PATH": str(prefix / "lib/otb/applications"),
               "PROJ_NETWORK": "OFF", "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
               "GDAL_DATA": str(prefix / "share/gdal"), "PROJ_DATA": str(prefix / "share/proj")}
        command = [str(launcher), app, str(prefix / "lib/otb/applications")] + cli
        code, logs = _bounded_process(command, work, env)
        output = work / "native.tif"
        if output.is_symlink() or not output.is_file() or not 0 < output.stat().st_size <= 32 * 1024 * 1024:
            reject("native raster missing, linked, empty, or oversized", "invalid_output")
        with rasterio.open(output) as ds:
            if ds.driver != "GTiff" or ds.crs != grid["crs"] or ds.transform != grid["transform"]:
                reject("native output lost or changed CRS/affine", "invalid_output")
            if (ds.height, ds.width, ds.count) != (grid["height"], grid["width"], expected_bands):
                reject("native output dimensions/bands mismatch", "invalid_output")
            result = ds.read()
            if not ds.read_masks().all() or not np.isfinite(result).all():
                reject("native output contains missing/nonfinite values", "invalid_output")
        if np.iscomplexobj(result) and not complex_output:
            if np.max(np.abs(result.imag)) > 1e-7:
                reject("unexpected imaginary native output", "invalid_output")
            result = result.real
        _csv(root, "native-execution.csv", ["application", "version", "source_commit", "exit_status", "identity_sha256"],
             [[app, "9.1.1", _OTB_COMMIT, code, manifest_hash]])
        (Path(root) / "native-stdout.txt").write_text(logs["stdout"], encoding="utf-8")
        (Path(root) / "native-stderr.txt").write_text(logs["stderr"], encoding="utf-8")
        (Path(root) / "native-identity.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


@operation("GeoRemoteTOAReflectance")
def toa_reflectance(args, output_dir=None):
    np = _np()
    g = _grid(args, complete=True)
    dn = _cube(args, "digital_numbers", g, low=0, high=1e7)
    gains = _array(args["gains"], "gains", 1)
    biases = _array(args["biases"], "biases", 1)
    solar = _array(args["solar_irradiance"], "solar_irradiance", 1)
    if any(v.size != dn.shape[0] for v in (gains, biases, solar)) or np.any(gains <= 0) or np.any(solar <= 0):
        reject("one positive gain/irradiance and finite bias required per band")
    if np.any(dn / gains[:, None, None] + biases[:, None, None] < 0):
        reject("gain/bias would create negative radiance")
    auxiliary = {"gainbias.txt": ":".join(map(str, gains)) + "\n" + ":".join(map(str, biases)) + "\n",
                 "solar.txt": ":".join(map(str, solar)) + "\n"}
    cli = ["-in", "dn.tif", "-out", "native.tif", "double", "-level", "toa",
           "-milli", "false", "-clamp", "false", "-acqui.gainbias", "gainbias.txt",
           "-acqui.solarilluminations", "solar.txt", "-acqui.solardistance", str(args["sun_distance_au"]),
           "-acqui.sun.elev", str(args["sun_elevation_deg"]), "-ram", "256"]
    result = _otb("OpticalCalibration", args, output_dir, g, {"dn": dn}, cli, dn.shape[0], auxiliary)
    if np.any(result < -1e-8):
        reject("negative TOA reflectance", "invalid_output")
    return _raster_result(output_dir, result, g, ["toa_band_" + str(i + 1) for i in range(dn.shape[0])],
                          ["reflectance_fraction"] * dn.shape[0],
                          ["OTB convention: radiance=DN/gain+bias. TOA values may exceed one; no surface/atmospheric correction."])


@operation("GeoRemotePansharpenFusion")
def pansharpen_fusion(args, output_dir=None):
    np = _np()
    g = _grid(args, complete=True)
    pan = _cube(args, "pan", g, 1, 1e-8, 1e9)
    xs = _cube(args, "multispectral", g, low=0, high=1)
    if not 2 <= xs.shape[0] <= 16 or min(g["mask"].shape) < 5:
        reject("require 2..16 reflectance bands and at least 5x5 aligned PAN grid")
    cli = ["-inp", "pan.tif", "-inxs", "xs.tif", "-out", "native.tif", "double",
           "-method", "rcs", "-method.rcs.radiusx", "2", "-method.rcs.radiusy", "2", "-ram", "256"]
    result = _otb("Pansharpening", args, output_dir, g, {"pan": pan, "xs": xs}, cli, xs.shape[0])
    if np.any(result < -1e-8):
        reject("negative fused reflectance", "invalid_output")
    return _raster_result(output_dir, result, g, ["fused_band_" + str(i + 1) for i in range(xs.shape[0])],
                          ["reflectance_fraction"] * xs.shape[0],
                          ["RCS on already co-registered/resampled inputs; high-frequency injection can distort spectra."])


@operation("GeoRemoteMADChange")
def mad_change(args, output_dir=None):
    np = _np()
    g = _grid(args, complete=True)
    first = _cube(args, "reference", g, low=0, high=1)
    second = _cube(args, "secondary", g, first.shape[0], 0, 1)
    if not 2 <= first.shape[0] <= 8 or g["mask"].sum() <= 4 * first.shape[0]:
        reject("MAD needs 2..8 bands and >4 times as many pixels")
    for name, cube in (("reference covariance", first), ("secondary covariance", second)):
        data = cube.reshape(cube.shape[0], -1).T
        _rank(data - data.mean(axis=0), cube.shape[0], name)
    cli = ["-in1", "first.tif", "-in2", "second.tif", "-out", "native.tif", "double", "-ram", "256"]
    result = _otb("MultivariateAlterationDetector", args, output_dir, g,
                  {"first": first, "second": second}, cli, first.shape[0])
    _csv(output_dir, "mad-sample-variance.csv", ["band", "variance"],
         [[i + 1, float(np.var(b, ddof=1))] for i, b in enumerate(result)])
    return _raster_result(output_dir, result, g, ["mad_" + str(i + 1) for i in range(first.shape[0])],
                          ["dimensionless_canonical_difference"] * first.shape[0],
                          ["Canonical signs are arbitrary; radiometric change is not mineral alteration identification."])


@operation("GeoSARPolarimetricHAlpha")
def polarimetric_halpha(args, output_dir=None):
    np = _np()
    g = _grid(args, complete=True)
    _sar_pair(args)
    hh = _complex(args, "hh", g)
    hv = _complex(args, "hv", g)
    vv = _complex(args, "vv", g)
    if min(g["mask"].shape) < 11:
        reject("9x9 H-alpha neighborhood requires tile at least 11x11")
    if np.any(np.abs(hh) ** 2 + 2 * np.abs(hv) ** 2 + np.abs(vv) ** 2 < 1e-12):
        reject("zero-span scattering is unsupported")
    cli = ["-inhh", "hh.tif", "-inhv", "hv.tif", "-invv", "vv.tif",
           "-out", "native.tif", "cdouble", "-decomp", "haa", "-inco.kernelsize", "4", "-ram", "256"]
    result = _otb("SARDecompositions", args, output_dir, g, {"hh": hh, "hv": hv, "vv": vv}, cli, 3)
    g["mask"][:4] = False
    g["mask"][-4:] = False
    g["mask"][:, :4] = False
    g["mask"][:, -4:] = False
    for b, bound in ((0, 1), (1, 90), (2, 1)):
        if np.any(result[b, g["mask"]] < -1e-6) or np.any(result[b, g["mask"]] > bound + 1e-6):
            reject("H-alpha output outside physical bounds", "invalid_output")
    return _raster_result(output_dir, result, g, ["entropy", "alpha", "anisotropy"],
                          ["dimensionless", "degree", "dimensionless"],
                          ["Reciprocity HV=VH assumed. Fixed OTB radius 4 means a 9x9 coherency neighborhood."])


@operation("GeoSARPolarizationSynthesis")
def polarization_synthesis(args, output_dir=None):
    np = _np()
    g = _grid(args, complete=True)
    _sar_pair(args)
    scattering = _complex(args, "scattering", g, 4)
    if np.any(np.sum(np.abs(scattering) ** 2, axis=0) < 1e-12):
        reject("zero scattering matrix has no useful polarization power")
    cli = ["-in", "scattering.tif", "-out", "native.tif", "double", "-mode", "none",
           "-psii", str(args["transmit_orientation_deg"]), "-khii", str(args["transmit_ellipticity_deg"]),
           "-psir", str(args["receive_orientation_deg"]), "-khir", str(args["receive_ellipticity_deg"]), "-ram", "256"]
    result = _otb("SARPolarSynth", args, output_dir, g, {"scattering": scattering}, cli, 1)
    if np.any(result < -1e-8):
        reject("negative synthesized power", "invalid_output")
    return _raster_result(output_dir, result, g, ["synthesized_polarization_power"], ["amplitude_squared"],
                          ["Input order HH,HV,VH,VV; calibrated complex scattering required for absolute power interpretation."])


def _invert_phase(args, key, g):
    np = _np()
    from mintpy.objects import ifgramStack
    from mintpy.ifgram_inversion import estimate_timeseries
    dates, pairs = _pairs(args)
    observations = _cube(args, key, g, len(pairs))
    A, B = ifgramStack.get_design_matrix4timeseries(pairs, refDate=args["dates"][0])
    if A.shape != (len(pairs), len(dates) - 1):
        reject("unexpected upstream interferogram design", "invalid_output")
    _rank(A, len(dates) - 1, "interferogram network")
    row, col = args["reference_pixel"]
    if not (0 <= row < g["height"] and 0 <= col < g["width"] and g["mask"][row, col]):
        reject("reference pixel outside valid grid")
    y = observations[:, g["mask"]] - observations[:, row, col][:, None]
    tbase = np.asarray([(d - dates[0]).total_seconds() / (365.25 * 86400) for d in dates])
    result, quality, count = estimate_timeseries(A, B, y, np.diff(tbase)[:, None],
                                               weight_sqrt=None, min_norm_velocity=False,
                                               min_redundancy=1, inv_quality_name="temporalCoherence",
                                               print_msg=False)
    if result.shape != (len(dates), int(g["mask"].sum())) or int(count) != len(pairs):
        reject("upstream inversion skipped observations or returned wrong shape", "invalid_output")
    if not np.isfinite(result).all() or not np.isfinite(quality).all():
        reject("nonfinite phase inversion", "invalid_output")
    # A connected finite system should satisfy its normal equations even when noisy.
    residual = A @ result[1:] - y
    if np.linalg.norm(A.T @ residual) > 1e-4 * max(1.0, np.linalg.norm(y)):
        reject("upstream phase inversion failed normal-equation residual check", "invalid_output")
    output = np.zeros((len(dates), g["height"], g["width"]))
    output[:, g["mask"]] = result * (-args["sar"]["wavelength_m"] / (4 * math.pi))
    _csv(output_dir := args["_output_root"], "network-quality.csv", ["valid_pixel_index", "temporal_coherence"],
         [[i, float(v)] for i, v in enumerate(np.broadcast_to(quality, (int(g["mask"].sum()),)))])
    return output


@operation("GeoInSARNetworkDisplacement")
def network_displacement(args, output_dir=None):
    _insar(args)
    g = _grid(args)
    work = dict(args, _output_root=output_dir)
    output = _invert_phase(work, "unwrapped_phase", g)
    return _raster_result(output_dir, output, g, ["los_" + d for d in args["dates"]],
                          ["m"] * len(args["dates"]),
                          ["Requires co-registered, unwrapped, flat-earth/topography-corrected interferograms; no RGB-to-InSAR path."])


@operation("GeoInSARResidualDEM")
def residual_dem(args, output_dir=None):
    np = _np()
    _insar(args)
    from mintpy.dem_error import estimate_dem_error
    g = _grid(args)
    dates = _dates(args["dates"])
    if len(dates) < 4:
        reject("DEM residual plus intercept/velocity needs at least four dates")
    series = _cube(args, "los_displacement_m", g, len(dates))
    baseline = _array(args["perpendicular_baseline_m"], "perpendicular_baseline_m", 1)
    if baseline.size != len(dates) or abs(baseline[0]) > 1e-9:
        reject("one baseline per date, relative to first date, is required")
    if np.any(np.abs(series[0, g["mask"]]) > 1e-8):
        reject("displacement must be referenced to first date")
    incidence = _cube(args, "incidence_deg", g, 1, 5, 85)[0]
    distance = _cube(args, "slant_range_m", g, 1, 1e4, 1e8)[0]
    tbase = np.asarray([(d - dates[0]).total_seconds() / (365.25 * 86400) for d in dates])
    corrected = np.zeros_like(series)
    residual = np.zeros_like(series)
    dem = np.zeros(g["mask"].shape)
    for r, c in zip(*np.where(g["mask"])):
        geom = baseline / (distance[r, c] * math.sin(math.radians(incidence[r, c])))
        design = np.column_stack((geom, np.ones(len(dates)), tbase))
        _rank(design, 3, "DEM/baseline versus linear deformation design")
        dz, cor, res = estimate_dem_error(series[:, r, c], design, tbase, phase_velocity=False)
        if np.asarray(dz).size != 1 or np.asarray(cor).size != len(dates) or np.asarray(res).size != len(dates):
            reject("unexpected DEM residual fit shape", "invalid_output")
        dem[r, c] = np.asarray(dz).item()
        corrected[:, r, c] = np.asarray(cor).reshape(-1)
        residual[:, r, c] = np.asarray(res).reshape(-1)
    _write_tiff(Path(output_dir) / "fit-residual.tif", residual, g, args["dates"], ["m"] * len(dates))
    return _raster_result(output_dir, np.concatenate((dem[None], corrected)), g,
                          ["dem_height_error"] + ["corrected_" + d for d in args["dates"]],
                          ["m"] * (len(dates) + 1),
                          ["Fixed intercept+linear displacement model; DEM residual is confounded if baseline and motion are collinear."])


@operation("GeoInSARIonosphericDelay")
def ionospheric_delay(args, output_dir=None):
    np = _np()
    _insar(args)
    if args["ionosphere_product"] != "split_spectrum_ionospheric_phase_at_full_band":
        reject("full-band-scaled split-spectrum ionospheric phase required")
    g = _grid(args)
    work = dict(args, _output_root=output_dir)
    delay = _invert_phase(work, "ionospheric_phase", g)
    series = _cube(args, "los_displacement_m", g, len(args["dates"]))
    r, c = args["reference_pixel"]
    if np.any(np.abs(series[0, g["mask"]]) > 1e-8) or np.any(np.abs(series[:, r, c]) > 1e-8):
        reject("LOS series and ionosphere must share first-date and spatial reference")
    _write_tiff(Path(output_dir) / "ionospheric-los-delay.tif", delay, g,
                args["dates"], ["m"] * len(args["dates"]))
    return _raster_result(output_dir, series - delay, g, ["corrected_" + d for d in args["dates"]],
                          ["m"] * len(args["dates"]),
                          ["Inverts precomputed split-spectrum ionospheric pairs; does not estimate ionosphere from RGB or a single-band SLC."])


@operation("GeoInSARPlateFrameCorrection")
def plate_frame_correction(args, output_dir=None):
    np = _np()
    _insar(args)
    from mintpy.objects.euler_pole import EulerPole
    from mintpy.utils import utils as ut
    g = _grid(args)
    if g["crs"].to_epsg() != 4326:
        reject("plate correction currently requires explicit WGS84 geographic grid")
    velocity = _cube(args, "los_velocity_m_per_year", g, 1)[0]
    incidence = _cube(args, "incidence_deg", g, 1, 0, 89.9)[0]
    azimuth = _cube(args, "azimuth_deg", g, 1, -180, 180)[0]
    omega = _array(args["euler_cartesian_mas_per_year"], "euler_cartesian_mas_per_year", 1)
    if omega.size != 3 or np.any(omega == 0) or np.any(np.abs(omega) > 100):
        reject("MintPy 1.6.4 EulerPole requires three nonzero Cartesian components; no local workaround")
    yy, xx = np.indices(g["mask"].shape)
    tr = g["transform"]
    longitude = tr.a * (xx + .5) + tr.b * (yy + .5) + tr.c
    latitude = tr.d * (xx + .5) + tr.e * (yy + .5) + tr.f
    pole = EulerPole(wx=float(omega[0]), wy=float(omega[1]), wz=float(omega[2]), unit="mas/yr")
    east, north, up = pole.get_velocity_enu(latitude, longitude, alt=0.0, ellps=True, print_msg=False)
    vectors = ut.get_unit_vector4component_of_interest(incidence, azimuth, comp="enu2los")
    model = east * vectors[0] + north * vectors[1] + up * vectors[2]
    r, c = args["reference_pixel"]
    if not (0 <= r < g["height"] and 0 <= c < g["width"] and g["mask"][r, c]):
        reject("valid spatial reference pixel required")
    if abs(velocity[r, c]) > 1e-8:
        reject("observed LOS velocity must be zero at the declared reference")
    model = model - model[r, c]
    _write_tiff(Path(output_dir) / "plate-enu.tif", np.stack([east, north, up]), g,
                ["east", "north", "up"], ["m/year"] * 3)
    return _raster_result(output_dir, np.stack([velocity - model, model]), g,
                          ["plate_relative_los_velocity", "reference_adjusted_plate_los"],
                          ["m/year", "m/year"],
                          ["User-supplied ITRF2014 Euler vector; no plate-boundary inference or automatic frame conversion."])


@operation("GeoInSARAscDescDecomposition")
def asc_desc_decomposition(args, output_dir=None):
    np = _np()
    _insar(args)
    from mintpy.asc_desc2horz_vert import asc_desc2horz_vert, get_design_matrix4horz_vert
    g = _grid(args)
    los = _cube(args, "asc_desc_los_m", g, 2)
    incidence = _array(args["incidence_deg"], "incidence_deg", 1)
    azimuth = _array(args["azimuth_deg"], "azimuth_deg", 1)
    if incidence.shape != (2,) or azimuth.shape != (2,) or np.any(incidence <= 0) or np.any(incidence >= 90):
        reject("two constant incidence/azimuth pairs required")
    design = get_design_matrix4horz_vert(incidence, azimuth, horz_az_angle=-90)
    _rank(design, 2, "ascending/descending LOS geometry")
    if np.linalg.cond(design) > 100:
        reject("LOS geometry condition number exceeds 100")
    safe = los.copy()
    safe[:, ~g["mask"]] = 0
    horizontal, vertical = asc_desc2horz_vert(safe, incidence, azimuth, horz_az_angle=-90, step=1)
    return _raster_result(output_dir, np.stack([horizontal, vertical]), g,
                          ["east_displacement", "up_displacement"], ["m", "m"],
                          ["North displacement fixed to zero. Two tracks must share acquisition interval, datum and spatial reference."])


@operation("GeoInSAREnvisatOscillatorCorrection")
def envisat_oscillator_correction(args, output_dir=None):
    np = _np()
    _insar(args)
    import h5py
    from mintpy.local_oscilator_drift import correct_local_oscilator_drift
    g = _grid(args, complete=True)
    if g["crs"].to_epsg() != 4326 or g["transform"].b != 0 or g["transform"].d != 0:
        reject("ENVISAT HDF transport requires north-up axis-aligned EPSG:4326")
    dates = _dates(args["dates"])
    if any(not 2002 <= d.year <= 2012 for d in dates):
        reject("ENVISAT acquisition date outside mission years 2002..2012")
    series = _cube(args, "los_displacement_m", g, len(dates))
    ranges = _cube(args, "slant_range_m", g, 1, 1e4, 1e8)[0]
    r, c = args["reference_pixel"]
    if not (0 <= r < g["height"] and 0 <= c < g["width"]):
        reject("reference pixel outside tile")
    if np.any(np.abs(series[0]) > 1e-8) or np.any(np.abs(series[:, r, c]) > 1e-8):
        reject("ENVISAT series must be referenced to first date and declared pixel")
    tr = g["transform"]
    metadata = {"FILE_TYPE": "timeseries", "UNIT": "m", "PLATFORM": "ENVISAT",
                "WAVELENGTH": str(args["sar"]["wavelength_m"]), "REF_DATE": args["dates"][0],
                "REF_Y": str(r), "REF_X": str(c), "LENGTH": str(g["height"]), "WIDTH": str(g["width"]),
                "X_FIRST": str(tr.c), "Y_FIRST": str(tr.f), "X_STEP": str(tr.a), "Y_STEP": str(tr.e),
                "X_UNIT": "degrees", "Y_UNIT": "degrees", "EPSG": "4326"}
    with tempfile.TemporaryDirectory(prefix="envisat-private-", dir=output_dir) as temp:
        source = Path(temp) / "timeseries.h5"
        geometry = Path(temp) / "geometry.h5"
        destination = Path(temp) / "corrected.h5"
        with h5py.File(source, "w") as f:
            f.create_dataset("date", data=np.asarray(args["dates"], dtype="S8"))
            f.create_dataset("timeseries", data=series.astype("float32"))
            f.create_dataset("bperp", data=np.zeros(len(dates), dtype="float32"))
            for key, value in metadata.items():
                f.attrs[key] = value
        with h5py.File(geometry, "w") as f:
            f.create_dataset("slantRangeDistance", data=ranges)
            for key, value in dict(metadata, FILE_TYPE="geometry").items():
                f.attrs[key] = value
        correct_local_oscilator_drift(str(source), str(geometry), str(destination))
        if destination.is_symlink() or not destination.is_file() or destination.stat().st_size > 32 * 1024 * 1024:
            reject("invalid corrected HDF5 artifact", "invalid_output")
        with h5py.File(destination, "r") as f:
            d = f.get("timeseries", getlink=True)
            if not isinstance(d, h5py.HardLink):
                reject("upstream output uses an external/soft link", "invalid_output")
            dataset = f["timeseries"]
            if dataset.shape != series.shape or dataset.is_virtual or dataset.external:
                reject("unexpected upstream HDF5 storage/shape", "invalid_output")
            result = dataset[:]
            if list(f["date"][:].astype(str)) != args["dates"]:
                reject("upstream altered acquisition dates", "invalid_output")
    return _raster_result(output_dir, result, g, ["corrected_" + d for d in args["dates"]],
                          ["m"] * len(dates),
                          ["ENVISAT-only empirical oscillator correction; not a correction for Sentinel-1."])


@operation("GeoInSARCoherenceNetworkSelection")
def coherence_network_selection(args, output_dir=None):
    np = _np()
    _insar(args)
    from mintpy.modify_network import get_mst_date12
    from mintpy.objects import ifgramStack
    dates, pairs = _pairs(args)
    coherence = _array(args["mean_coherence"], "mean_coherence", 1)
    if len(coherence) != len(pairs) or np.any(coherence <= 0) or np.any(coherence > 1):
        reject("one mean coherence in (0,1] per actual interferogram")
    matrix = ifgramStack.get_design_matrix4timeseries(pairs, refDate=args["dates"][0])[0]
    _rank(matrix, len(dates) - 1, "input interferogram network")
    mst, _ = get_mst_date12(True, coherence.tolist(), pairs, [], args["minimum_coherence"])
    if any(p not in pairs for p in mst):
        reject("upstream MST returned a non-input pair", "invalid_output")
    keep = [p in mst or value >= args["minimum_coherence"] for p, value in zip(pairs, coherence)]
    kept = [p for p, flag in zip(pairs, keep) if flag]
    selected = ifgramStack.get_design_matrix4timeseries(kept, refDate=args["dates"][0])[0]
    _rank(selected, len(dates) - 1, "selected interferogram network")
    rows = [[p, float(v), int(p in mst), int(flag)] for p, v, flag in zip(pairs, coherence, keep)]
    return _table_result(output_dir, "selected-network.csv", ["pair", "mean_coherence", "in_mst", "keep"],
                         rows, [int(x) for x in keep], "binary_keep",
                         ["Uses spatial mean coherence from real co-registered SAR pairs; MST connectivity is not a quality guarantee."])

"""Bounded offline remote-sensing kernels. SOURCE AUTHORED; NOT TESTED.

Scientific implementations are delegated to the pinned upstream libraries.
All imports of numerical/plotting/raster dependencies are lazy. Missing data
are excluded by an upstream mask or rejected, never radiometrically imputed.
"""
import csv
import json
from pathlib import Path

from .collection_contracts import operation, reject

MAX_PIXELS = 65536
MAX_ELEMENTS = 1048576


def _read(path):
    import numpy as np
    import rasterio

    p = Path(path)
    if p.suffix.lower() not in (".tif", ".tiff") or p.is_symlink():
        reject("Expected a local, single-file GeoTIFF", "invalid_path")
    with rasterio.open(p) as ds:
        if ds.driver != "GTiff" or ds.crs is None or len(ds.files) != 1:
            reject("A single-file GTiff with explicit CRS is required")
        if not (2 <= ds.width <= 512 and 2 <= ds.height <= 512 and 1 <= ds.count <= 64):
            reject("Raster dimensions exceed the declared profile", "resource_limit")
        if ds.width * ds.height > MAX_PIXELS or ds.width * ds.height * ds.count > MAX_ELEMENTS:
            reject("Raster exceeds the pixel or spectral-element budget", "resource_limit")
        affine = tuple(ds.transform)[:6]
        if not np.isfinite(affine).all() or ds.transform.determinant == 0:
            reject("Raster affine must be finite and nonsingular")
        if any(v != 1 for v in ds.scales) or any(v != 0 for v in ds.offsets):
            reject("Supply already calibrated values with identity stored scale/offset")
        image = ds.read(out_dtype="float64")
        band_valid = ds.read_masks() != 0
        if not np.isfinite(image[band_valid]).all():
            reject("Unmasked raster values must be finite")
        valid = band_valid.all(axis=0)
        if not valid.any():
            reject("No pixels valid in every band", "empty_input")
        grid = {"width": ds.width, "height": ds.height, "bands": ds.count,
                "crs": ds.crs.to_string(), "affine": list(affine),
                "coordinate_unit": "degree" if ds.crs.is_geographic else ds.crs.linear_units,
                "input_nodata": [None if n is None else str(n) for n in ds.nodatavals]}
        profile = {"driver": "GTiff", "width": ds.width, "height": ds.height,
                   "crs": ds.crs, "transform": ds.transform, "dtype": "float64",
                   "compress": "deflate", "nodata": ds.nodata}
    return np.moveaxis(image, 0, -1), valid, grid, profile


def _aligned(first, other):
    if any(first[k] != other[k] for k in ("width", "height", "crs", "affine")):
        reject("Raster grids differ; no implicit resampling or reprojection")


def _load(args, *, complete=False, single=False):
    import numpy as np
    image, valid, grid, profile = _read(args["raster_path"])
    if "quality_mask_path" in args:
        q, qvalid, qgrid, _ = _read(args["quality_mask_path"])
        _aligned(grid, qgrid)
        if q.shape[-1] != 1 or not np.isin(q[..., 0][qvalid], [0, 1]).all():
            reject("Quality mask must be one band with explicit 0/1 values")
        valid &= qvalid & (q[..., 0] == 1)
    if not valid.any():
        reject("No pixels remain after quality exclusions", "empty_input")
    if complete and not valid.all():
        reject("This spatial kernel requires a complete valid rectangular patch; no gap filling", "unsupported_conditions")
    if single and image.shape[-1] != 1:
        reject("This operation requires exactly one raster band")
    grid.update(valid_pixels=int(valid.sum()), excluded_pixels=int(valid.size - valid.sum()))
    if np.max(np.abs(image[valid])) > 1e12:
        reject("Calibrated magnitudes exceed the bounded numeric profile")
    return (image[..., 0] if single else image), valid, grid, profile


def _aux(args, key, grid, valid):
    import numpy as np
    image, mask, other, _ = _read(args[key])
    _aligned(grid, other)
    if image.shape[-1] != 1 or not np.all(mask[valid]):
        reject("Auxiliary raster must have one valid band throughout the analysis domain")
    return image[..., 0]


def _binary(args):
    import numpy as np
    image, valid, grid, profile = _load(args, complete=True, single=True)
    if args["input_unit"] != "binary" or not np.isin(image, [0, 1]).all():
        reject("Binary morphology requires unit=binary and exact 0/1 pixels")
    return image.astype(bool), valid, grid, profile


def _gray(args, *, complete=True):
    import numpy as np
    image, valid, grid, profile = _load(args, complete=complete, single=True)
    if args["input_unit"] != "DN" or not np.equal(image[valid], np.floor(image[valid])).all():
        reject("Supply explicitly quantized integer DN; no automatic radiometric binning")
    if image[valid].min() < 0 or image[valid].max() >= args.get("levels", 256):
        reject("Quantized DN must be inside the declared levels")
    return np.where(valid, image, 0).astype(np.uint8), valid, grid, profile


def _spectral(args, *, complete=False):
    import numpy as np
    image, valid, grid, profile = _load(args, complete=complete)
    wavelengths = np.asarray(args["wavelength_nm"], dtype=float)
    if image.shape[-1] < 2 or wavelengths.size != image.shape[-1] or not (np.diff(wavelengths) > 0).all():
        reject("Declare one strictly increasing wavelength per band, with at least two bands")
    if valid.sum() <= image.shape[-1]:
        reject("More valid pixels than spectral bands are required")
    if args["input_unit"] not in ("reflectance", "radiance", "DN"):
        reject("Spectral statistics require a shared reflectance, radiance or DN unit")
    return image, valid, grid, profile


def _covariance(value, bands):
    import numpy as np
    cov = np.asarray(value, dtype=float)
    if cov.shape != (bands, bands) or not np.isfinite(cov).all() or not np.allclose(cov, cov.T, rtol=0, atol=1e-12):
        reject("Covariance must be finite, square and symmetric in the declared band order")
    eig = np.linalg.eigvalsh(cov)
    if eig[0] <= 0 or eig[-1] / eig[0] > 1e10:
        reject("Covariance must be positive definite with condition number <=1e10")
    return cov


def _background(args, bands):
    import numpy as np
    from spectral.algorithms.algorithms import GaussianStats
    mean = np.asarray(args["background_mean"], dtype=float)
    if mean.shape != (bands,):
        reject("Background mean must match the raster band count")
    return GaussianStats(mean=mean, cov=_covariance(args["background_covariance"], bands))


def _target(args, background):
    import numpy as np
    target = np.asarray(args["target"], dtype=float)
    if target.shape != background.mean.shape or np.linalg.norm(target - background.mean) <= 1e-12:
        reject("Target must match band count and differ from the supplied background mean")
    return target


def _write_raster(root, name, output, valid, profile, descriptions, band_tags=None):
    import numpy as np
    import rasterio
    data = np.asarray(output, dtype=float)
    if data.ndim == 2:
        data = data[..., None]
    if data.shape[:2] != valid.shape or not np.isfinite(data[valid]).all():
        reject("Upstream raster result is nonfinite or has a wrong shape", "invalid_result")
    nodata = profile["nodata"]
    if nodata is None or not np.isfinite(nodata) or np.any(data[valid] == nodata):
        nodata = -1.7976931348623157e308
    if np.any(data[valid] == nodata):
        reject("Output NoData sentinel collides with a valid result", "invalid_result")
    copied = np.where(valid[..., None], data, nodata)
    options = {**profile, "count": data.shape[-1], "nodata": nodata}
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
        with rasterio.open(root / name, "w", **options) as dst:
            dst.write(np.moveaxis(copied, -1, 0))
            dst.write_mask(valid.astype("uint8") * 255)
            for i, description in enumerate(descriptions, 1):
                dst.set_band_description(i, description)
            if band_tags is not None:
                for i, tags in enumerate(band_tags, 1):
                    dst.update_tags(i, **tags)
            dst.update_tags(scope="Scientific processing; not mineral identification or ore grade")
    return data, nodata


def _finish(args, root, grid, profile, valid, measurements, measurement_units,
            output=None, output_unit="dimensionless", descriptions=None, band_tags=None):
    import numpy as np
    units = {"input": args["input_unit"], **measurement_units}
    stats = []
    nodata = None
    if output is not None:
        output, nodata = _write_raster(root, "result.tif", output, valid, profile,
                                      descriptions or ["scientific result"], band_tags=band_tags)
        for i in range(output.shape[-1]):
            values = output[..., i][valid]
            stats.append({"band": i + 1, "minimum": float(values.min()),
                          "maximum": float(values.max()), "mean": float(values.mean()),
                          "valid_pixels": int(values.size), "unit": output_unit})
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        fig = Figure(figsize=(6, 4), dpi=120)
        FigureCanvasAgg(fig)
        ax = fig.add_subplot(111)
        im = ax.imshow(np.ma.array(output[..., 0], mask=~valid), cmap="cividis", interpolation="nearest")
        fig.colorbar(im, ax=ax, label=output_unit)
        ax.set(xlabel="column (pixels)", ylabel="row (pixels)", title="Scientific result, first band")
        fig.tight_layout()
        fig.savefig(root / "preview.png")
        fig.clear()
    with (root / "measurements.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["measurement", "value_or_json", "unit"])
        for key, value in measurements.items():
            writer.writerow([key, json.dumps(value, allow_nan=False), measurement_units[key]])
    return {"grid": grid, "measurements": measurements, "raster_statistics": stats,
            "output_nodata": None if nodata is None else str(nodata), "units": units}


def _image_result(args, root, loaded, output, output_unit, extra=None, extra_units=None):
    import numpy as np
    _, valid, grid, profile = loaded
    values = np.asarray(output)
    selected = values[valid]
    measurements = {"minimum": float(selected.min()), "maximum": float(selected.max()),
                    "mean": float(selected.mean()), **(extra or {})}
    measurement_units = {"minimum": output_unit, "maximum": output_unit, "mean": output_unit,
                         **(extra_units or {})}
    return _finish(args, root, grid, profile, valid, measurements, measurement_units,
                   output, output_unit)


@operation("GeoRemotePCA")
def spectral_pca(args, output_dir=None):
    import numpy as np
    from spectral.algorithms.algorithms import principal_components
    image, valid, grid, profile = _spectral(args)
    count = args["components"]
    if count > image.shape[-1]:
        reject("Component count exceeds the number of spectral bands")
    pc = principal_components(image[valid])
    if not np.isrealobj(pc.eigenvalues) or pc.eigenvalues.sum() <= 0:
        reject("PCA requires positive spectral variance")
    scores = np.zeros((*valid.shape, count))
    scores[valid] = pc.reduce(num=count).transform(image[valid])
    return _finish(args, output_dir, grid, profile, valid,
                   {"eigenvalues": pc.eigenvalues.tolist(), "band_mean": pc.mean.tolist(),
                    "loadings": pc.eigenvectors[:, :count].tolist()},
                   {"eigenvalues": args["input_unit"] + "^2", "band_mean": args["input_unit"], "loadings": "dimensionless"},
                   scores, args["input_unit"], ["PC " + str(i + 1) for i in range(count)])


@operation("GeoRemoteNoiseCovariance")
def spectral_noise_covariance(args, output_dir=None):
    from spectral.algorithms.algorithms import noise_from_diffs
    image, valid, grid, profile = _spectral(args, complete=True)
    noise = noise_from_diffs(image, direction="right")
    return _finish(args, output_dir, grid, profile, valid,
                   {"covariance": noise.cov.tolist(), "difference_mean": noise.mean.tolist(),
                    "difference_pairs": int(noise.nsamples)},
                   {"covariance": args["input_unit"] + "^2", "difference_mean": args["input_unit"], "difference_pairs": "pairs"})


@operation("GeoRemoteMNF")
def spectral_mnf(args, output_dir=None):
    import numpy as np
    from spectral.algorithms.algorithms import calc_stats, GaussianStats, mnf
    image, valid, grid, profile = _spectral(args)
    bands = image.shape[-1]
    if args["components"] > bands:
        reject("Component count exceeds the number of spectral bands")
    noise = GaussianStats(mean=np.zeros(bands), cov=_covariance(args["noise_covariance"], bands))
    result = mnf(calc_stats(image[valid]), noise)
    scores = np.zeros((*valid.shape, args["components"]))
    scores[valid] = result.reduce(image[valid], num=args["components"])
    return _finish(args, output_dir, grid, profile, valid,
                   {"noise_adjusted_eigenvalues": result.napc.eigenvalues.tolist()},
                   {"noise_adjusted_eigenvalues": "signal_plus_noise_to_noise_ratio"}, scores,
                   "noise_standard_deviation", ["MNF " + str(i + 1) for i in range(args["components"])])


@operation("GeoRemoteRX")
def spectral_rx(args, output_dir=None):
    import numpy as np
    from spectral.algorithms.detectors import rx
    loaded = _spectral(args)
    image, valid, _, _ = loaded
    background = _background(args, image.shape[-1])
    output = np.zeros(valid.shape)
    output[valid] = rx(image[valid], background=background)
    return _image_result(args, output_dir, loaded, output, "squared_Mahalanobis_distance")


@operation("GeoRemoteMatchedFilter")
def spectral_matched_filter(args, output_dir=None):
    import numpy as np
    from spectral.algorithms.detectors import matched_filter
    loaded = _spectral(args)
    image, valid, _, _ = loaded
    background = _background(args, image.shape[-1])
    output = np.zeros(valid.shape)
    scores = np.asarray(matched_filter(image[valid], _target(args, background), background=background))
    count = int(valid.sum())
    if scores.shape == (count, 1):
        scores = scores[:, 0]
    elif scores.shape != (count,):
        reject("Unexpected matched-filter score shape", "invalid_result")
    if not np.isrealobj(scores) or not np.isfinite(scores).all():
        reject("Matched-filter scores must be real and finite", "invalid_result")
    output[valid] = scores
    return _image_result(args, output_dir, loaded, output, "matched_filter_response")


@operation("GeoRemoteACE")
def spectral_ace(args, output_dir=None):
    import numpy as np
    from spectral.algorithms.detectors import ace
    loaded = _spectral(args)
    image, valid, _, _ = loaded
    background = _background(args, image.shape[-1])
    if np.any(np.linalg.norm(image[valid] - background.mean, axis=1) <= 1e-12):
        reject("ACE is undefined at the background mean; supply a quality exclusion")
    output = np.zeros(valid.shape)
    output[valid] = ace(image[valid], _target(args, background), background=background)
    return _image_result(args, output_dir, loaded, output, "squared_whitened_cosine")


@operation("GeoRemoteWhiteTophat")
def white_tophat_features(args, output_dir=None):
    import numpy as np
    from skimage.morphology import white_tophat
    loaded = _load(args, complete=True, single=True)
    size = 2 * args["radius_pixels"] + 1
    result = white_tophat(loaded[0], footprint=np.ones((size, size), dtype=bool), mode="reflect")
    return _image_result(args, output_dir, loaded, result, args["input_unit"])


@operation("GeoRemoteSeedReconstruction")
def seeded_reconstruction(args, output_dir=None):
    from skimage.morphology import reconstruction
    loaded = _load(args, complete=True, single=True)
    mask, valid, grid, _ = loaded
    seed = _aux(args, "seed_path", grid, valid)
    if (seed > mask).any():
        reject("Every dilation seed must be <= its corresponding constraint image value")
    result = reconstruction(seed, mask, method="dilation")
    return _image_result(args, output_dir, loaded, result, args["input_unit"])


@operation("GeoRemoteSkeleton")
def binary_skeleton(args, output_dir=None):
    from skimage.morphology import skeletonize
    loaded = _binary(args)
    result = skeletonize(loaded[0], method="zhang")
    return _image_result(args, output_dir, loaded, result, "binary",
                         {"skeleton_pixels": int(result.sum())}, {"skeleton_pixels": "pixels"})


@operation("GeoRemoteRemoveSmallObjects")
def remove_small_objects(args, output_dir=None):
    from skimage.morphology import remove_small_objects as upstream
    loaded = _binary(args)
    result = upstream(loaded[0], max_size=args["max_size_pixels"], connectivity=1)
    return _image_result(args, output_dir, loaded, result, "binary",
                         {"removed_pixels": int(loaded[0].sum() - result.sum()), "foreground_pixels": int(result.sum())},
                         {"removed_pixels": "pixels", "foreground_pixels": "pixels"})


@operation("GeoRemoteFillSmallHoles")
def fill_small_holes(args, output_dir=None):
    from skimage.morphology import remove_small_holes
    loaded = _binary(args)
    result = remove_small_holes(loaded[0], max_size=args["max_size_pixels"], connectivity=1)
    return _image_result(args, output_dir, loaded, result, "binary",
                         {"filled_pixels": int(result.sum() - loaded[0].sum()), "foreground_pixels": int(result.sum())},
                         {"filled_pixels": "pixels", "foreground_pixels": "pixels"})


@operation("GeoRemoteHMaxima")
def prominence_maxima(args, output_dir=None):
    from skimage.morphology import h_maxima
    loaded = _load(args, complete=True, single=True)
    if loaded[0].max() == loaded[0].min():
        reject("Prominence requires a nonconstant image")
    result = h_maxima(loaded[0], h=args["height"])
    return _image_result(args, output_dir, loaded, result, "binary",
                         {"maxima_pixels": int(result.sum())}, {"maxima_pixels": "pixels"})


@operation("GeoRemoteGLCM")
def gray_cooccurrence_texture(args, output_dir=None):
    import numpy as np
    from skimage.feature import graycomatrix, graycoprops
    image, valid, grid, profile = _gray(args)
    distance = args["distance_pixels"]
    if distance >= min(image.shape):
        reject("Co-occurrence lag must be smaller than each image dimension")
    matrix = graycomatrix(image, [distance], [np.deg2rad(args["angle_degrees"])],
                          levels=args["levels"], symmetric=True, normed=True)
    measurements = {"probability_matrix": matrix[..., 0, 0].tolist()}
    for name in ("contrast", "dissimilarity", "homogeneity", "energy", "correlation"):
        measurements[name] = float(graycoprops(matrix, name)[0, 0])
    return _finish(args, output_dir, grid, profile, valid, measurements,
                   {"probability_matrix": "probability", "contrast": "DN^2", "dissimilarity": "DN",
                    "homogeneity": "dimensionless", "energy": "dimensionless", "correlation": "dimensionless"})


@operation("GeoRemoteLocalEntropy")
def local_entropy(args, output_dir=None):
    import numpy as np
    from skimage.filters.rank import entropy
    loaded = _gray(args, complete=False)
    image, valid, _, _ = loaded
    size = 2 * args["radius_pixels"] + 1
    result = entropy(image, np.ones((size, size), dtype=np.uint8), mask=valid.astype(np.uint8))
    return _image_result(args, output_dir, loaded, result, "bits")


@operation("GeoRemoteLBP")
def local_binary_patterns(args, output_dir=None):
    from skimage.feature import local_binary_pattern
    loaded = _gray(args)
    result = local_binary_pattern(loaded[0], P=8, R=1, method="default")
    return _image_result(args, output_dir, loaded, result, "LBP8_code")


@operation("GeoRemoteStructureTensor")
def image_structure_tensor(args, output_dir=None):
    import numpy as np
    from skimage.feature import structure_tensor, structure_tensor_eigenvalues
    loaded = _load(args, complete=True, single=True)
    elems = structure_tensor(loaded[0], sigma=args["sigma_pixels"], mode="reflect", order="rc")
    eigenvalues = structure_tensor_eigenvalues(elems)
    result = np.moveaxis(np.stack([*elems, *eigenvalues]), 0, -1)
    return _finish(args, output_dir, loaded[2], loaded[3], loaded[1],
                   {"maximum_principal_eigenvalue": float(eigenvalues[0].max())},
                   {"maximum_principal_eigenvalue": args["input_unit"] + "^2_Sobel_pixel"},
                   result, args["input_unit"] + "^2_Sobel_pixel", ["Arr", "Arc", "Acc", "lambda_max", "lambda_min"])


@operation("GeoRemoteGabor")
def oriented_gabor_texture(args, output_dir=None):
    import numpy as np
    from skimage.filters import gabor
    loaded = _load(args, complete=True, single=True)
    real, imag = gabor(loaded[0], frequency=args["frequency_cycles_per_pixel"],
                       theta=np.deg2rad(args["orientation_degrees"]), sigma_x=args["sigma_pixels"],
                       sigma_y=args["sigma_pixels"], n_stds=3, mode="reflect")
    return _finish(args, output_dir, loaded[2], loaded[3], loaded[1],
                   {"maximum_real_response": float(real.max())}, {"maximum_real_response": args["input_unit"]},
                   np.stack([real, imag], axis=-1), args["input_unit"], ["Gabor real", "Gabor imaginary"])


@operation("GeoRemoteCanny")
def canny_boundaries(args, output_dir=None):
    from skimage.feature import canny
    loaded = _load(args, single=True)
    image, valid, _, _ = loaded
    if args["low_threshold"] > args["high_threshold"]:
        reject("Canny low threshold must not exceed high threshold")
    if image[valid].min() < 0 or image[valid].max() > 1:
        reject("Canny profile requires supplied intensities in [0,1]")
    # The upstream mask excludes invalid pixels and its neighborhood.
    import numpy as np
    image = np.where(valid, image, 0)
    result = canny(image, sigma=args["sigma_pixels"], low_threshold=args["low_threshold"],
                   high_threshold=args["high_threshold"], mask=valid, mode="reflect")
    return _image_result(args, output_dir, loaded, result, "binary",
                         {"edge_pixels": int(result[valid].sum())}, {"edge_pixels": "pixels"})


@operation("GeoRemoteOtsu")
def otsu_segmentation(args, output_dir=None):
    from skimage.filters import threshold_otsu
    loaded = _gray(args, complete=False)
    image, valid, _, _ = loaded
    if image[valid].max() == image[valid].min():
        reject("Otsu segmentation requires at least two observed levels")
    threshold = float(threshold_otsu(image[valid]))
    result = image > threshold
    return _image_result(args, output_dir, loaded, result, "binary",
                         {"threshold": threshold, "foreground_pixels": int(result[valid].sum())},
                         {"threshold": "DN", "foreground_pixels": "pixels"})


def _markers(args, grid, valid):
    import numpy as np
    image = _aux(args, "markers_path", grid, valid)
    if (image[valid] < 0).any() or (image[valid] > 128).any() or not np.equal(image[valid], np.floor(image[valid])).all():
        reject("Markers must be integer labels 0..128, with zero unseeded")
    labels = np.unique(image[valid & (image > 0)]).astype(int)
    if len(labels) == 0 or labels.tolist() != list(range(1, len(labels) + 1)):
        reject("Positive marker labels must be consecutive from one")
    return np.where(valid, image, 0).astype(np.int32), labels


def _labels_result(args, root, loaded, result):
    import numpy as np
    labels, counts = np.unique(result[loaded[1]], return_counts=True)
    keep = labels > 0
    return _image_result(args, root, loaded, result, "label",
                         {"labels": labels[keep].tolist(), "region_pixels": counts[keep].tolist(),
                          "region_count": int(keep.sum())},
                         {"labels": "label", "region_pixels": "pixels", "region_count": "regions"})


@operation("GeoRemoteWatershed")
def marker_watershed(args, output_dir=None):
    import numpy as np
    from skimage.segmentation import watershed
    from scipy.ndimage import label
    loaded = _load(args, single=True)
    image, valid, grid, _ = loaded
    markers, _ = _markers(args, grid, valid)
    domains, count = label(valid)
    if any(not (markers[domains == i] > 0).any() for i in range(1, count + 1)):
        reject("Every connected valid domain must contain a supplied marker")
    result = watershed(np.where(valid, image, 0), markers, connectivity=1, mask=valid)
    return _labels_result(args, output_dir, loaded, result)


@operation("GeoRemoteSLIC")
def slic_superpixels(args, output_dir=None):
    from skimage.segmentation import slic
    loaded = _load(args, complete=True, single=True)
    if args["segments"] > loaded[1].sum():
        reject("Requested segments exceed valid pixels")
    result = slic(loaded[0], n_segments=args["segments"], compactness=args["compactness"],
                   max_num_iter=20, sigma=0, convert2lab=False, enforce_connectivity=True,
                   start_label=1, channel_axis=None)
    return _labels_result(args, output_dir, loaded, result)


@operation("GeoRemoteFelzenszwalb")
def graph_segmentation(args, output_dir=None):
    from skimage.segmentation import felzenszwalb
    loaded = _load(args, complete=True, single=True)
    result = felzenszwalb(loaded[0], scale=args["scale"], sigma=0,
                          min_size=args["min_size_pixels"], channel_axis=None) + 1
    return _labels_result(args, output_dir, loaded, result)


@operation("GeoRemoteRandomWalker")
def seeded_random_walker(args, output_dir=None):
    import numpy as np
    from skimage.segmentation import random_walker
    loaded = _load(args, complete=True, single=True)
    image, valid, grid, profile = loaded
    if valid.size > 4096:
        reject("Direct sparse solver is limited to 4096 pixels", "resource_limit")
    markers, labels = _markers(args, grid, valid)
    if not (2 <= len(labels) <= 8) or not (markers == 0).any() or image.std() <= 0:
        reject("Random walker needs 2..8 seeded classes, unseeded pixels and nonconstant intensity")
    probabilities = random_walker(image, markers, beta=args["beta"], mode="bf", return_full_prob=True)
    _write_raster(output_dir, "class-labels.tif", np.argmax(probabilities, axis=0) + 1,
                  valid, profile, ["Most probable seeded class"])
    return _finish(args, output_dir, grid, profile, valid,
                   {"labels": labels.tolist(), "probability_sums": probabilities.sum(axis=(1, 2)).tolist()},
                   {"labels": "label", "probability_sums": "probability_pixel_sum"},
                   np.moveaxis(probabilities, 0, -1), "probability", ["Class " + str(x) for x in labels])


@operation("GeoRemoteRegionProperties")
def segmented_region_properties(args, output_dir=None):
    import numpy as np
    from skimage.measure import regionprops_table
    image, valid, grid, profile = _load(args, single=True)
    if args["input_unit"] != "label" or not np.equal(image[valid], np.floor(image[valid])).all():
        reject("Region measurement requires integer label values")
    if image[valid].min() < 0 or image[valid].max() > 4096:
        reject("Region labels must be in 0..4096")
    table = regionprops_table(np.where(valid, image, 0).astype(np.int32),
                              properties=("label", "area", "centroid", "eccentricity", "orientation", "solidity", "extent"))
    if not len(table["label"]):
        reject("No positive labeled regions", "empty_input")
    rows = {k: v.tolist() for k, v in table.items()}
    with (output_dir / "regions.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(rows)
        writer.writerows(zip(*rows.values()))
    return _finish(args, output_dir, grid, profile, valid, rows,
                   {"label": "label", "area": "pixels", "centroid-0": "row_pixels", "centroid-1": "column_pixels",
                    "eccentricity": "dimensionless", "orientation": "radians_from_row_axis",
                    "solidity": "dimensionless", "extent": "dimensionless"})


def _pair(args, *, complete=True):
    import numpy as np
    first, valid, grid, profile = _load(args, complete=complete, single=True)
    second, other_valid, other_grid, _ = _read(args["reference_path"])
    _aligned(grid, other_grid)
    if second.shape[-1] != 1:
        reject("Reference image must contain exactly one band")
    valid &= other_valid
    if not valid.any() or (complete and not valid.all()):
        reject("Both images need the required valid support", "unsupported_conditions")
    if np.max(np.abs(second[..., 0][valid])) > 1e12:
        reject("Reference calibrated magnitudes exceed the bounded numeric profile")
    grid.update(valid_pixels=int(valid.sum()), excluded_pixels=int(valid.size - valid.sum()))
    return (first, valid, grid, profile), second[..., 0]


@operation("GeoRemotePhaseRegistration")
def phase_registration(args, output_dir=None):
    import numpy as np
    from skimage.registration import phase_cross_correlation
    loaded, reference = _pair(args)
    moving, valid, grid, profile = loaded
    if moving.std() <= 0 or reference.std() <= 0:
        reject("Registration requires spatial contrast in both images")
    shift, error, phase = phase_cross_correlation(reference, moving,
                                                 upsample_factor=args["upsample_factor"], normalization=None)
    a, b, _, d, e, _ = grid["affine"]
    return _finish(args, output_dir, grid, profile, valid,
                   {"shift_row_pixels": float(shift[0]), "shift_column_pixels": float(shift[1]),
                    "shift_x": float(a * shift[1] + b * shift[0]), "shift_y": float(d * shift[1] + e * shift[0]),
                    "normalized_error": float(error), "phase_difference": float(phase)},
                   {"shift_row_pixels": "pixels", "shift_column_pixels": "pixels", "shift_x": grid["coordinate_unit"],
                    "shift_y": grid["coordinate_unit"], "normalized_error": "dimensionless", "phase_difference": "radians"})


@operation("GeoRemoteSSIMChange")
def structural_similarity_change(args, output_dir=None):
    from skimage.metrics import structural_similarity
    loaded, reference = _pair(args)
    image, valid, grid, profile = loaded
    window = args["window_pixels"]
    if window % 2 == 0 or window > min(image.shape):
        reject("SSIM window must be odd and fit inside the image")
    if max(image.max(), reference.max()) - min(image.min(), reference.min()) > args["data_range"]:
        reject("Declared data range must cover the observed common intensity range")
    score, similarity = structural_similarity(reference, image, data_range=args["data_range"],
                                               win_size=window, channel_axis=None, full=True)
    return _finish(args, output_dir, grid, profile, valid, {"mean_ssim": float(score)},
                   {"mean_ssim": "dimensionless"}, 1 - similarity, "one_minus_SSIM")


@operation("GeoRemoteSensorBandResample")
def sensor_band_resample(args, output_dir=None):
    import numpy as np
    from spectral.algorithms.resampling import BandResampler

    image, valid, grid, profile = _load(args)
    if args["input_unit"] != "reflectance" or image[valid].min() < 0 or image[valid].max() > 1:
        reject("This bandpass profile requires calibrated reflectance in [0,1], not DN or categorical values")
    source_centers = np.asarray(args["wavelength_nm"], dtype=float)
    source_widths = np.asarray(args["source_fwhm_nm"], dtype=float)
    target_centers = np.asarray(args["target_wavelength_nm"], dtype=float)
    target_widths = np.asarray(args["target_fwhm_nm"], dtype=float)
    bands = image.shape[-1]
    if bands < 2 or source_centers.shape != (bands,) or source_widths.shape != (bands,):
        reject("Supply a center and FWHM for each of at least two source bands")
    if target_centers.ndim != 1 or not 1 <= target_centers.size <= 64 or target_widths.shape != target_centers.shape:
        reject("Supply matching target center/FWHM vectors for 1..64 bands")
    if valid.size * target_centers.size > MAX_ELEMENTS:
        reject("Resampled raster exceeds the spectral-element budget", "resource_limit")
    for centers, widths in ((source_centers, source_widths), (target_centers, target_widths)):
        if not np.isfinite(centers).all() or not np.isfinite(widths).all():
            reject("Band centers and FWHMs must be finite")
        if not (np.diff(centers) > 0).all() or not (widths > 0).all():
            reject("Band centers must increase strictly and every FWHM must be positive")
        low, high = centers - widths / 2, centers + widths / 2
        if (low < 100).any() or (high > 30000).any() or not (high > low).all():
            reject("Every nonzero-width FWHM interval must lie within 100..30000 nm")
    source_low, source_high = source_centers - source_widths / 2, source_centers + source_widths / 2
    if (source_low[1:] < source_high[:-1]).any():
        reject("Overlapping source FWHM intervals are outside this conservative response profile", "unsupported_conditions")
    for center, width in zip(target_centers, target_widths):
        cursor, end = center - width / 2, center + width / 2
        for low, high in zip(source_low, source_high):
            if high <= cursor:
                continue
            if low > cursor:
                break
            cursor = max(cursor, high)
            if cursor >= end:
                break
        if cursor < end:
            reject("Unsupported target coverage: its full FWHM interval must be covered without gaps or extrapolation", "unsupported_conditions")

    # SPy owns the Gaussian overlap integral and spectral transformation.
    # Coverage checks forbid its otherwise silent partial-support renormalization.
    resampler = BandResampler(source_centers, target_centers, source_widths, target_widths)
    weights = np.asarray(resampler.matrix)
    if (weights.shape != (target_centers.size, bands) or not np.isrealobj(weights)
            or not np.isfinite(weights).all() or (weights < 0).any()
            or not np.allclose(weights.sum(axis=1), 1, rtol=0, atol=1e-12)):
        reject("Invalid upstream band-response weights", "invalid_result")
    mapped = np.asarray([resampler(pixel) for pixel in image[valid]])
    if (mapped.shape != (int(valid.sum()), target_centers.size)
            or not np.isrealobj(mapped) or not np.isfinite(mapped).all()):
        reject("Invalid upstream resampled spectrum shape or finite values", "invalid_result")
    output = np.zeros((*valid.shape, target_centers.size))
    output[valid] = mapped
    with (output_dir / "resampling-weights.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["target_band", "source_band", "target_center_nm", "target_fwhm_nm",
                         "source_center_nm", "source_fwhm_nm", "weight"])
        for target_index in range(target_centers.size):
            for source_index in range(bands):
                writer.writerow([target_index + 1, source_index + 1,
                                 target_centers[target_index], target_widths[target_index],
                                 source_centers[source_index], source_widths[source_index],
                                 weights[target_index, source_index]])
    measurements = {"minimum": float(mapped.min()), "maximum": float(mapped.max()), "mean": float(mapped.mean()),
                    "source_wavelength_nm": source_centers.tolist(), "source_fwhm_nm": source_widths.tolist(),
                    "target_wavelength_nm": target_centers.tolist(), "target_fwhm_nm": target_widths.tolist(),
                    "resampling_weights": weights.tolist()}
    measurement_units = {"minimum": "reflectance", "maximum": "reflectance", "mean": "reflectance",
                         "source_wavelength_nm": "nm", "source_fwhm_nm": "nm",
                         "target_wavelength_nm": "nm", "target_fwhm_nm": "nm", "resampling_weights": "dimensionless"}
    descriptions = [f"Target band {i + 1}: {center:g} nm, FWHM {width:g} nm"
                    for i, (center, width) in enumerate(zip(target_centers, target_widths))]
    tags = [{"wavelength_nm": str(float(center)), "fwhm_nm": str(float(width)), "wavelength_unit": "nm",
             "radiometric_unit": "reflectance", "response_model": "Gaussian_within_FWHM"}
            for center, width in zip(target_centers, target_widths)]
    return _finish(args, output_dir, grid, profile, valid, measurements, measurement_units,
                   output, "reflectance", descriptions, band_tags=tags)


@operation("GeoRemoteTVDenoise")
def total_variation_denoise(args, output_dir=None):
    from skimage.restoration import denoise_tv_chambolle
    unit = args["input_unit"]
    if unit not in ("reflectance", "radiance", "DN", "brightness_temperature_K", "normalized_intensity"):
        reject("TV denoising requires continuous radiometry, not binary or label codes")
    loaded = _load(args, complete=True, single=True)
    if loaded[0].min() < 0 or (unit in ("reflectance", "normalized_intensity") and loaded[0].max() > 1):
        reject("TV radiometry must be nonnegative; this profile bounds reflectance and normalized intensity to [0,1]")
    result = denoise_tv_chambolle(loaded[0], weight=args["weight"], eps=1e-6,
                                  max_num_iter=args["iterations"], channel_axis=None)
    return _image_result(args, output_dir, loaded, result, args["input_unit"])


@operation("GeoRemoteRichardsonLucy")
def richardson_lucy_deconvolution(args, output_dir=None):
    import numpy as np
    from skimage.restoration import richardson_lucy
    loaded = _load(args, complete=True, single=True)
    psf = np.asarray(args["psf"], dtype=float)
    if psf.ndim != 2 or min(psf.shape) < 1 or max(psf.shape) > 31 or any(n % 2 == 0 for n in psf.shape):
        reject("PSF must be an odd rectangular matrix with dimensions <=31")
    if (psf < 0).any() or not np.isclose(psf.sum(), 1, rtol=0, atol=1e-10) or loaded[0].min() < 0:
        reject("Richardson-Lucy requires nonnegative data and a supplied nonnegative unit-sum PSF")
    result = richardson_lucy(loaded[0], psf, num_iter=args["iterations"], clip=False)
    return _image_result(args, output_dir, loaded, result, args["input_unit"])


@operation("GeoRemoteRollingBall")
def rolling_ball_background(args, output_dir=None):
    import numpy as np
    from skimage.restoration import rolling_ball
    loaded = _load(args, complete=True, single=True)
    image, valid, grid, profile = loaded
    background = rolling_ball(image, radius=args["radius_pixels"], workers=1)
    return _finish(args, output_dir, grid, profile, valid,
                   {"background_mean": float(background.mean()), "residual_mean": float((image - background).mean())},
                   {"background_mean": args["input_unit"], "residual_mean": args["input_unit"]},
                   np.stack([background, image - background], axis=-1), args["input_unit"], ["Rolling ball background", "Residual"])

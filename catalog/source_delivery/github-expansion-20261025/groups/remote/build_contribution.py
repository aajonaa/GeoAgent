"""Generate ONLY this group's additive source artifacts; no scientific execution.

Uses Python's standard library. Does not read/write the global catalog, install
dependencies, run tests, fetch resources, or alter deployed state.
"""
import copy
import json
import math
from pathlib import Path
import struct

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
ASSET = "assets/github-expansion-remote"
GROUP = "catalog/source_delivery/github-expansion-20261025/groups/remote"
MODULE = "geological_agent.geology.github_expansion_remote"
PINS = ["numpy==2.1.3", "scipy==1.15.3", "rasterio==1.4.3", "matplotlib==3.10.7",
        "jsonschema==4.25.1", "spectral==0.25", "scikit-image==0.26.0"]
CONTINUOUS_UNITS = ["reflectance", "radiance", "DN", "brightness_temperature_K", "normalized_intensity"]
SOURCES = {
    "spectral": {"version": "0.25", "repository": "spectralpython/spectral",
                 "commit": "bd91dc47377028683ef5c97bc7c1cc2dff14012c", "tag": "0.25",
                 "license": "MIT", "license_path": "LICENSE.txt",
                 "release_url": "https://github.com/spectralpython/spectral/releases/tag/0.25",
                 "release_tag_object": "93b1dca87034fbf612d67bc3e80a14c8fabd4f60"},
    "scikit-image": {"version": "0.26.0", "repository": "scikit-image/scikit-image",
                     "commit": "ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8", "tag": "v0.26.0",
                     "license": "BSD-3-Clause AND BSD-2-Clause AND MIT", "license_path": "LICENSE.txt",
                     "release_url": "https://github.com/scikit-image/scikit-image/releases/tag/v0.26.0",
                     "release_tag_object": "ecd06885a44eec47cf268af923cd55e79db8a686"},
}


def obj(properties, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required, "additionalProperties": False}


def number(description, **bounds):
    return {"type": "number", "description": description, **bounds}


def integer(description, minimum=1, maximum=65536):
    return {"type": "integer", "description": description, "minimum": minimum, "maximum": maximum}


def text(description, **kwargs):
    return {"type": "string", "description": description, "minLength": 1, "maxLength": 512, **kwargs}


def array(description, items=None, minimum=1, maximum=65536):
    return {"type": "array", "description": description, "items": items or {"type": "number"},
            "minItems": minimum, "maxItems": maximum}


def matrix(description, maximum=64):
    return array(description, array("Ordered row", maximum=maximum), maximum=maximum)


def numeric_map():
    return {"minimum": number("Minimum valid raster result in the output unit."),
            "maximum": number("Maximum valid raster result in the output unit."),
            "mean": number("Arithmetic mean of valid raster results in the output unit.")}


def records():
    rows = []
    def add(short, function, workflow, api, source_path, task, distinct, fixture, unit,
            fields, parameters, measurements, oracle, bad, limitation, package="scikit-image", raster_probe=None):
        rows.append({"tool_id": "GeoRemote" + short, "function": function, "workflow": workflow,
                     "package": package, "upstream_callable": api, "source_path": source_path,
                     "scientific_task": task, "distinct_from_existing": distinct,
                     "fields": fields, "example": {"raster_path": ASSET + "/" + fixture + ".tif", "input_unit": unit, **parameters},
                     "measurements": measurements, "oracle": oracle, "negative": bad,
                     "limitation": limitation, "raster_probe": raster_probe})
    wave = {"wavelength_nm": array("Strictly increasing band centers, nm, one per raster band.",
                                    number("Wavelength in nm", minimum=100, maximum=30000), minimum=2, maximum=64)}
    comp = {"components": integer("Retained spectral components", 1, 64)}
    background = {"background_mean": array("Supplied background mean, shared input unit and band order.", maximum=64),
                  "background_covariance": matrix("Supplied positive-definite covariance, input_unit squared."),
                  "background_source": text("Caller-declared measured background provenance; not independently authenticated.")}
    target = {"target": array("Supplied target spectrum in shared input units and ordered bands.", maximum=64),
              "target_source": text("Caller-declared target provenance; similarity is not mineral identification.")}
    background_example = {"background_mean": [0, 0], "background_covariance": [[4, 0], [0, 1]],
                          "background_source": "SYNTHETIC analytic diagonal covariance; not measured"}
    target_example = {"target": [2, 0], "target_source": "SYNTHETIC target; not a mineral spectrum"}
    waves = {"wavelength_nm": [1000, 1500]}
    specpath = "spectral/algorithms/algorithms.py"
    detpath = "spectral/algorithms/detectors.py"
    add("PCA", "spectral_pca", "spectral", "spectral.algorithms.algorithms.principal_components", specpath,
        "Reduce calibrated multispectral imagery to principal components with eigenvalues and band loadings.",
        "GeoSpectralLinearUnmix fits supplied endmembers; PCA learns orthogonal variance directions without an endmember library.",
        "spectral-pca", "DN", {**wave, **comp}, {**waves, "components": 1},
        {"eigenvalues": array("Sample covariance eigenvalues, input_unit squared.", maximum=64),
         "band_mean": array("Band means in input units.", maximum=64), "loadings": matrix("Signed orthonormal loadings; eigenvector sign is arbitrary.")},
        {"path": ["eigenvalues", 0], "expected": 16 / 3, "reason": "Four corners (0,0),(2,0),(0,4),(2,4) have unbiased covariance diag(4/3,16/3); the largest eigenvalue is 16/3."},
        {"components": 65}, "Axes maximize variance, not mineral separability; sign and repeated-eigenvalue bases are not unique.", "spectral")
    add("NoiseCovariance", "spectral_noise_covariance", "spectral", "spectral.algorithms.algorithms.noise_from_diffs", specpath,
        "Estimate spectral noise covariance from horizontal adjacent-pixel differences in a declared homogeneous patch.",
        "Existing spectral continuum and angle tools do not estimate sensor-noise cross-band covariance.",
        "spectral-noise", "DN", {**wave, "homogeneous_patch_source": text("Evidence or assumption supporting a homogeneous patch.")},
        {**waves, "homogeneous_patch_source": "SYNTHETIC repeated differences; stationarity assumed for oracle"},
        {"covariance": matrix("Half the unbiased adjacent-difference covariance, input_unit squared."),
         "difference_mean": array("Mean of left-minus-right differences, input units.", maximum=64), "difference_pairs": integer("Adjacent pairs")},
        {"path": ["covariance", 0, 0], "expected": 2 / 3, "reason": "Differences -1,+1,-1,+1 have sample variance 4/3; independent equal-variance pixel noise contributes half, 2/3."},
        {"wavelength_nm": [1500, 1000]}, "Spatial texture can bias the estimate; independence and local stationarity are assumptions, not certified sensor noise.", "spectral")
    add("MNF", "spectral_mnf", "spectral", "spectral.algorithms.algorithms.mnf", specpath,
        "Reduce spectral dimensions after whitening by an explicitly supplied noise covariance.",
        "PCA orders raw variance; MNF orders variance relative to measured noise. Existing spectral matching/unmixing does neither noise whitening nor MNF.",
        "spectral-pca", "DN", {**wave, **comp, "noise_covariance": matrix("Positive-definite noise covariance, input_unit squared."), "noise_source": text("Caller-declared noise-estimation provenance.")},
        {**waves, "components": 1, "noise_covariance": [[1, 0], [0, 2]], "noise_source": "SYNTHETIC diagonal noise covariance"},
        {"noise_adjusted_eigenvalues": array("Total-to-noise variance ratios; SNR interpretation requires a valid additive-noise model.", maximum=64)},
        {"path": ["noise_adjusted_eigenvalues", 0], "expected": 8 / 3, "reason": "Whitening diag(4/3,16/3) by noise diag(1,2) yields diag(4/3,8/3)."},
        {"noise_covariance": [[0, 0], [0, 1]]}, "Requires physically justified positive-definite noise covariance; retained scores are not abundances.", "spectral")
    detection = [
        ("RX", "spectral_rx", "rx", "Detect multivariate spectral anomalies relative to supplied background statistics.",
         "GeoSpectralAngleMap compares reference directions; RX needs no target and measures squared background Mahalanobis distance.", 2,
         "For x=(2,1), mean=0 and covariance diag(4,1), x^T C^-1 x=4/4+1=2.", {"background_covariance": [[1, 1], [0, 1]]}),
        ("MatchedFilter", "spectral_matched_filter", "matched_filter", "Map covariance-weighted linear responses to a supplied spectral target.",
         "GeoSpectralLinearUnmix solves endmember coefficients; matched filtering uses an explicit background mean/covariance and one target, without interpreting coefficients as abundances.", 1,
         "For target=(2,0), x=(2,1), mean=0 and C=diag(4,1), t^T C^-1 x / (t^T C^-1 t)=1.", {"target": [0, 0]}),
        ("ACE", "spectral_ace", "ace", "Map adaptive coherence scores for a supplied target in background-whitened spectral space.",
         "GeoSpectralAngleMap is an unwhitened angle; ACE uses background covariance and squared normalized coherence, distinct from amplitude-sensitive matched filtering.", .5,
         "Whitened target=(1,0) and pixel=(1,1) have squared cosine 1/(1*2)=1/2.", {"background_mean": [2, 1]}),
    ]
    for short, fn, api, task, distinct, expected, reason, bad in detection:
        targeted = short != "RX"
        add(short, fn, "spectral", "spectral.algorithms.detectors." + api, detpath, task, distinct,
            "spectral-targets", "DN", {**wave, **background, **(target if targeted else {})},
            {**waves, **background_example, **(target_example if targeted else {})}, numeric_map(),
            {"path": ["mean"], "expected": expected, "reason": reason}, bad,
            "Background stationarity and band calibration must be justified; scores are neither probabilities of mineral presence nor ore grade. ACE at the exact background mean is rejected.", "spectral")
    radius = {"radius_pixels": integer("Square-footprint radius in pixels", 1, 16)}
    maxsize = {"max_size_pixels": integer("Inclusive connected-component area threshold in pixels", 1, 4096)}
    add("WhiteTophat", "white_tophat_features", "morphology", "skimage.morphology.white_tophat", "src/skimage/morphology/gray.py",
        "Extract compact bright image features by white top-hat morphology at an explicit spatial scale.",
        "RemoteSensingBatchHotspotRaster thresholds absolute brightness; top-hat measures brightness above a morphological local background.",
        "peak", "DN", radius, {"radius_pixels": 1}, numeric_map(),
        {"path": ["maximum"], "expected": 8, "reason": "A single value 10 on uniform 2 has 3x3 opening 2 and white top-hat peak 10-2=8."},
        {"radius_pixels": 0}, "Square footprint and reflect borders; complete patch required. Feature scale is pixels, not geological size.")
    add("SeedReconstruction", "seeded_reconstruction", "morphology", "skimage.morphology.reconstruction", "src/skimage/morphology/grayreconstruct.py",
        "Propagate supplied intensity seeds under a constraining image by grayscale geodesic reconstruction.",
        "GeoMapColorExtract uses legend color distance; reconstruction follows connected intensity support from explicit seed evidence.",
        "constraint", "DN", {"seed_path": text("Aligned single-band seed GeoTIFF; each seed <= constraint intensity.")},
        {"seed_path": ASSET + "/seed.tif"}, numeric_map(),
        {"path": ["maximum"], "expected": 2, "reason": "A seed of 2 propagates across the connected 3x3 plateau of height 5 but cannot cross its zero boundary; plateau value is 2."},
        {"seed_path": ASSET + "/peak.tif"}, "Dilation reconstruction, full 8-neighbor footprint, complete patch; supplied seeds determine results.", raster_probe={"band": 1, "row": 7, "column": 7, "expected": 2})
    add("Skeleton", "binary_skeleton", "morphology", "skimage.morphology.skeletonize", "src/skimage/morphology/_skeletonize.py",
        "Thin a supplied binary image feature mask to a one-pixel skeleton using Zhang thinning.",
        "Existing cloud and hotspot masks classify pixels; skeletonization extracts the topology of supplied linear image features.",
        "skeleton", "binary", {}, {}, {**numeric_map(), "skeleton_pixels": integer("Skeleton cell count", 0)},
        {"path": ["skeleton_pixels"], "expected": 9, "reason": "An already one-pixel-wide isolated horizontal segment with 9 cells is a fixed point of topology-preserving thinning."},
        {"input_unit": "DN"}, "Cell count is not physical line length or evidence of a fault; complete binary patch required.")
    add("RemoveSmallObjects", "remove_small_objects", "morphology", "skimage.morphology.remove_small_objects", "src/skimage/morphology/misc.py",
        "Remove small connected detections by inclusive pixel-area threshold with four-neighbor connectivity.",
        "Existing hotspot thresholding has no connected-area filtering; this rejects isolated detections based on spatial support.",
        "objects", "binary", maxsize, {"max_size_pixels": 1},
        {**numeric_map(), "removed_pixels": integer("Removed foreground cells", 0), "foreground_pixels": integer("Retained foreground cells", 0)},
        {"path": ["foreground_pixels"], "expected": 9, "reason": "A 9-cell connected square survives max_size=1 while a disconnected singleton is removed."},
        {"max_size_pixels": 0}, "Uses scikit-image 0.26 inclusive max_size, not deprecated exclusive min_size; complete patch required.")
    add("FillSmallHoles", "fill_small_holes", "morphology", "skimage.morphology.remove_small_holes", "src/skimage/morphology/misc.py",
        "Fill small connected background gaps in a supplied binary detection mask.",
        "Cloud masking excludes observations; hole filling edits supplied binary classification topology and does not reconstruct missing radiometry.",
        "holes", "binary", maxsize, {"max_size_pixels": 1},
        {**numeric_map(), "filled_pixels": integer("Filled binary cells", 0), "foreground_pixels": integer("Final foreground cells", 0)},
        {"path": ["filled_pixels"], "expected": 1, "reason": "A 3x3 foreground ring has a single-cell central background component; inclusive max_size=1 fills exactly one cell."},
        {"max_size_pixels": 0}, "Upstream can also fill a small background component touching the boundary; not an enclosed-hole-only guarantee. No NoData filling.")
    add("HMaxima", "prominence_maxima", "morphology", "skimage.morphology.h_maxima", "src/skimage/morphology/extrema.py",
        "Identify image maxima with a declared minimum intensity prominence.",
        "RemoteSensingMaxValueAndIndex finds a global scalar maximum; h-maxima detects spatial prominence above surrounding image support.",
        "peak", "DN", {"height": number("Minimum prominence in input units", exclusiveMinimum=0, maximum=1e12)}, {"height": 3},
        {**numeric_map(), "maxima_pixels": integer("Selected maxima cells", 0)},
        {"path": ["maxima_pixels"], "expected": 1, "reason": "The isolated height-10 peak above background 2 has prominence 8>=3 and occupies one cell."},
        {"height": 0}, "Returns maxima plateaus, not independent point objects or mineral targets; complete nonconstant patch required.")
    add("GLCM", "gray_cooccurrence_texture", "texture", "skimage.feature.graycomatrix", "src/skimage/feature/texture.py",
        "Measure directional gray-level co-occurrence texture from explicitly quantized image intensities.",
        "Existing batch means and hotspot percentages discard neighbor relationships; GLCM retains pairwise spatial texture at a declared lag.",
        "checkerboard", "DN", {"levels": integer("Number of caller-declared quantized levels", 2, 64), "distance_pixels": integer("Pixel-pair lag", 1, 16),
                                  "angle_degrees": {"type": "integer", "enum": [0, 45, 90, 135], "description": "Co-occurrence direction in image coordinates."}},
        {"levels": 2, "distance_pixels": 1, "angle_degrees": 0},
        {"probability_matrix": matrix("Symmetric normalized co-occurrence probabilities."),
         **{x: number("Upstream GLCM " + x + "; units documented in units dictionary.") for x in ["contrast", "dissimilarity", "homogeneity", "energy", "correlation"]}},
        {"path": ["contrast"], "expected": 1, "reason": "Horizontal neighbors of a binary checkerboard always differ by one; symmetric P01=P10=1/2, hence contrast=1."},
        {"levels": 1}, "No implicit quantization; one supplied patch, symmetric pairs. Upstream constant-texture correlation convention is 1.")
    add("LocalEntropy", "local_entropy", "texture", "skimage.filters.rank.entropy", "src/skimage/filters/rank/generic.py",
        "Map neighborhood Shannon entropy of explicitly quantized image intensities, excluding quality-mask pixels.",
        "Existing scalar coefficient-of-variation and kurtosis tools do not map local histogram information content.",
        "checkerboard", "DN", radius, {"radius_pixels": 1}, numeric_map(),
        {"path": ["maximum"], "expected": 1, "reason": "At a straight image edge the truncated 2x3 checkerboard footprint contains three zeros and three ones, giving entropy 1 bit."},
        {"radius_pixels": 0}, "Entropy depends on supplied quantization and valid footprint population; borders use truncated neighborhoods.",
        raster_probe={"band": 1, "row": 8, "column": 8, "expected": -(5/9)*math.log2(5/9)-(4/9)*math.log2(4/9)})
    add("LBP", "local_binary_patterns", "texture", "skimage.feature.local_binary_pattern", "src/skimage/feature/texture.py",
        "Encode eight-neighbor local binary texture patterns on a supplied quantized image.",
        "Existing optical indices compare spectral bands; LBP compares spatial neighbors with a center intensity to encode local texture.",
        "constant-dn", "DN", {}, {}, numeric_map(),
        {"path": ["maximum"], "expected": 255, "reason": "Inside a constant image all eight radius-one neighbors equal the center, so all bits are set: 2^8-1=255."},
        {"input_unit": "reflectance"}, "Fixed P=8, R=1, default LBP code; border samples follow upstream zero extension. Codes have no ordered physical magnitude.",
        raster_probe={"band": 1, "row": 8, "column": 8, "expected": 255})
    add("StructureTensor", "image_structure_tensor", "texture", "skimage.feature.structure_tensor", "src/skimage/feature/corner.py",
        "Map image structure tensors and principal eigenvalues for directional fabric evidence.",
        "GeoStereonetAnalysis uses supplied structural measurements; this estimates image-gradient anisotropy and does not infer geological strike/dip.",
        "ramp", "DN", {"sigma_pixels": number("Gaussian tensor aggregation sigma, pixels", minimum=0, maximum=8)}, {"sigma_pixels": 0},
        {"maximum_principal_eigenvalue": number("Largest eigenvalue of the unnormalized Sobel structure tensor.")},
        {"path": ["maximum_principal_eigenvalue"], "expected": 64, "reason": "For unit column ramp, the 3x3 Sobel derivative is 8 and row derivative is zero; the tensor eigenvalues are 64 and 0."},
        {"sigma_pixels": -1}, "Pixel-coordinate Sobel convention; not terrain derivatives, physical strain, azimuth, or a fault interpretation.",
        raster_probe={"band": 3, "row": 8, "column": 8, "expected": 64})
    add("Gabor", "oriented_gabor_texture", "texture", "skimage.filters.gabor", "src/skimage/filters/_gabor.py",
        "Map real and imaginary responses to an oriented, band-limited Gabor texture filter.",
        "GLCM measures quantized pairs; Gabor resolves signed local oscillation at a specified frequency and orientation, absent from baseline image tools.",
        "impulse", "normalized_intensity", {"frequency_cycles_per_pixel": number("Frequency in cycles/pixel", exclusiveMinimum=0, maximum=.5),
        "orientation_degrees": number("Harmonic direction from image x axis in degrees", minimum=0, maximum=180), "sigma_pixels": number("Gaussian envelope sigma in pixels", minimum=.5, maximum=8)},
        {"frequency_cycles_per_pixel": .25, "orientation_degrees": 0, "sigma_pixels": 1},
        {"maximum_real_response": number("Maximum real Gabor response, input units.")},
        {"path": ["maximum_real_response"], "expected": 1/(2*math.pi), "reason": "A unit impulse sampled at the center of a sigma_x=sigma_y=1 Gabor kernel has real response 1/(2*pi)."},
        {"frequency_cycles_per_pixel": 0}, "Truncated three-sigma filter; orientation is in image axes, not map azimuth. Complete patch required.")
    add("Canny", "canny_boundaries", "texture", "skimage.feature.canny", "src/skimage/feature/_canny.py",
        "Detect thin image boundaries using Gaussian smoothing, nonmaximum suppression and hysteresis.",
        "Existing hotspot masks classify intensity; Canny detects connected gradient boundaries using two hysteresis thresholds.",
        "step", "normalized_intensity", {"sigma_pixels": number("Gaussian smoothing sigma, pixels", minimum=0, maximum=5),
        "low_threshold": number("Low gradient threshold in supplied intensity units", minimum=0, maximum=4),
        "high_threshold": number("High gradient threshold in supplied intensity units", minimum=0, maximum=4)},
        {"sigma_pixels": 0, "low_threshold": .1, "high_threshold": .2},
        {**numeric_map(), "edge_pixels": integer("Detected edge cells", 0)},
        {"path": ["edge_pixels"], "expected": 28, "reason": "A 16x16 vertical unit step with sigma=0 has two equal Sobel-ridge columns; nonmaximum suppression keeps both on 14 interior rows: 28 cells."},
        {"low_threshold": .5, "high_threshold": .2}, "Input intensities must lie in [0,1]; upstream excludes the outer border and erodes support around quality gaps. An edge is not a mapped geological contact.")
    markers = {"markers_path": text("Aligned integer marker GeoTIFF: 0 unseeded, consecutive positive labels starting at 1.")}
    label_fields = {**numeric_map(), "labels": array("Positive region labels", {"type": "integer"}, minimum=0),
                    "region_pixels": array("Cells per region", {"type": "integer"}, minimum=0), "region_count": integer("Positive regions", 0)}
    add("Otsu", "otsu_segmentation", "segmentation", "skimage.filters.threshold_otsu", "src/skimage/filters/thresholding.py",
        "Derive an image threshold by maximizing between-class histogram variance and export its binary partition.",
        "RemoteSensingBatchHotspotRaster uses a caller-fixed threshold; Otsu estimates the threshold from the observed histogram.",
        "step-dn", "DN", {}, {}, {**numeric_map(), "threshold": number("Otsu threshold in DN"), "foreground_pixels": integer("Above-threshold cells", 0)},
        {"path": ["threshold"], "expected": 2, "reason": "Equal populations at integer DN=2 and 6 share the same optimal split for thresholds 2..5; the first maximizing bin is 2."},
        {"raster_path": ASSET + "/constant-dn.tif"}, "Binary histogram partition is not a land-cover or mineral label; caller quantization is retained.")
    add("Watershed", "marker_watershed", "segmentation", "skimage.segmentation.watershed", "src/skimage/segmentation/_watershed.py",
        "Partition an image cost surface by flooding from explicit labeled markers.",
        "GeoPyshedsFlowAccumulation is terrain hydrology; this is seeded image segmentation with arbitrary image costs, no drainage calculation.",
        "flat", "normalized_intensity", markers, {"markers_path": ASSET + "/markers-one.tif"}, label_fields,
        {"path": ["region_pixels", 0], "expected": 256, "reason": "A connected 16x16 flat cost domain with a single marker is entirely reached by that seed: 256 cells."},
        {"markers_path": ASSET + "/zeros.tif"}, "Four-neighbor image flooding; every connected valid domain must have a seed; markers are human/model inputs, not inferred ground truth.")
    add("SLIC", "slic_superpixels", "segmentation", "skimage.segmentation.slic", "src/skimage/segmentation/slic_superpixels.py",
        "Create compact image superpixels using joint intensity and pixel-coordinate clustering.",
        "GeoMapColorExtract matches legend colors to classes; SLIC forms unsupervised compact spatial support regions without semantic classes.",
        "flat", "normalized_intensity", {"segments": integer("Approximate requested number of superpixels", 1, 2048),
        "compactness": number("Spatial/intensity compactness parameter after upstream rescaling", exclusiveMinimum=0, maximum=10000)},
        {"segments": 1, "compactness": 10}, label_fields,
        {"path": ["region_pixels", 0], "expected": 256, "reason": "One requested cluster on a connected constant 16x16 image assigns all 256 cells to one superpixel."},
        {"segments": 0}, "Single-band profile; upstream rescales intensities internally; requested count is approximate, spatial scale uses pixels.")
    add("Felzenszwalb", "graph_segmentation", "segmentation", "skimage.segmentation.felzenszwalb", "src/skimage/segmentation/_felzenszwalb.py",
        "Segment intensity imagery by graph edge weights and adaptive component merging.",
        "SLIC imposes compact superpixels; graph segmentation follows intensity-edge component evidence without a requested region count, absent from the baseline.",
        "flat", "normalized_intensity", {"scale": number("Upstream graph merge scale parameter", exclusiveMinimum=0, maximum=10000),
        "min_size_pixels": integer("Upstream minimum component size", 1, 4096)}, {"scale": 100, "min_size_pixels": 1}, label_fields,
        {"path": ["region_pixels", 0], "expected": 256, "reason": "All graph edges of a constant connected 16x16 image have weight zero, so the positive-scale merge criterion combines all 256 cells."},
        {"scale": 0}, "No Gaussian prefilter, single-band image; labels are shifted from upstream zero-based to one-based for clear background semantics.")
    add("RandomWalker", "seeded_random_walker", "segmentation", "skimage.segmentation.random_walker", "src/skimage/segmentation/random_walker_segmentation.py",
        "Estimate seeded class probabilities by solving an intensity-weighted image diffusion problem.",
        "Watershed supplies hard flood labels; random walker solves a Dirichlet probability problem and exports per-class probability rasters, absent from baseline tools.",
        "walker", "normalized_intensity", {**markers, "beta": number("Intensity-gradient penalty; zero gives uniform conductance", minimum=0, maximum=500)},
        {"markers_path": ASSET + "/markers-walker.tif", "beta": 0},
        {"labels": array("Consecutive seeded labels", {"type": "integer"}, maximum=8), "probability_sums": array("Class probability summed over pixels", maximum=8)},
        {"path": ["probability_sums", 0], "expected": 32, "reason": "On an 8x8 uniform-conductance grid seeded left=1 and right=2, p1(c)=1-c/7; summing gives 8*4=32."},
        {"beta": -1}, "At most 4096 pixels and 2..8 classes, direct CPU sparse solve; probabilities condition on seeds/weights and are not geological posterior confidence.",
        raster_probe={"band": 1, "row": 4, "column": 3, "expected": 4/7})
    props = {x: array("Upstream region property " + x + "; units in units dictionary.", maximum=4096) for x in ["label", "area", "centroid-0", "centroid-1", "eccentricity", "orientation", "solidity", "extent"]}
    add("RegionProperties", "segmented_region_properties", "segmentation", "skimage.measure.regionprops_table", "src/skimage/measure/_regionprops.py",
        "Measure pixel area, centroid, orientation and shape descriptors of supplied labeled image regions.",
        "GeoShapelyGeometry measures vector geometry; this measures discrete labeled image regions and their intensity-independent shape moments.",
        "regions", "label", {}, {}, props,
        {"path": ["area", 0], "expected": 6, "reason": "A labeled rectangle covering rows 2,3 and columns 2,3,4 contains 2*3=6 cells with centroid (2.5,3)."},
        {"input_unit": "DN"}, "Labels 0..4096, zero ignored; disconnected cells sharing one label are one region. Areas/centroids are pixels, not projected area estimates.")
    pair = {"reference_path": text("Aligned single-band reference GeoTIFF with the same declared input unit.")}
    add("PhaseRegistration", "phase_registration", "radiometry", "skimage.registration.phase_cross_correlation", "src/skimage/registration/_phase_cross_correlation.py",
        "Estimate translational alignment between two same-grid image patches using Fourier cross-correlation.",
        "GeoRasterChangeAnalysis requires aligned imagery and only differences values; this estimates residual translation before change analysis.",
        "registration-moving", "normalized_intensity", {**pair, "upsample_factor": integer("Subpixel shift sampling factor", 1, 50)},
        {"reference_path": ASSET + "/registration-reference.tif", "upsample_factor": 1},
        {x: number("Translation/error estimate; units explicit in units dictionary.") for x in ["shift_row_pixels", "shift_column_pixels", "shift_x", "shift_y", "normalized_error", "phase_difference"]},
        {"path": ["shift_column_pixels"], "expected": 1, "reason": "Moving impulse at (8,5) and reference at (6,6) require shift (-2,+1); with 30 m pixels map translation is (+30,+60) m."},
        {"raster_path": ASSET + "/flat.tif"}, "Returns the shift to apply to the moving image; no resampling. Fourier shift is periodic/ambiguous for repetitive patterns; no rotation, deformation, or sensor-model correction.")
    add("SSIMChange", "structural_similarity_change", "radiometry", "skimage.metrics.structural_similarity", "src/skimage/metrics/_structural_similarity.py",
        "Map structural-similarity change between aligned acquisitions using an explicit intensity range and window.",
        "RemoteSensingTiffDifference and GeoRasterChangeAnalysis use pixel subtraction; SSIM compares local luminance, contrast and structure.",
        "flat", "normalized_intensity", {**pair, "data_range": number("Physical span of the shared calibrated intensity domain", exclusiveMinimum=0, maximum=1e12),
        "window_pixels": integer("Odd sliding window width", 3, 31)},
        {"reference_path": ASSET + "/quarter.tif", "data_range": 1, "window_pixels": 7}, {"mean_ssim": number("Interior-averaged upstream SSIM; not a probability.")},
        {"path": ["mean_ssim"], "expected": (.25+.0001)/(.3125+.0001), "reason": "Constant a=.25,b=.5 with range=1 give SSIM=(2ab+.01^2)/(a^2+b^2+.01^2); variance terms cancel."},
        {"window_pixels": 4}, "Complete co-registered patches required; full map has reflected borders while scalar SSIM excludes a window rim. Range/illumination affect interpretation.")
    widths = lambda description, minimum: array(description, number("Full width at half maximum, nm", exclusiveMinimum=0, maximum=30000), minimum=minimum, maximum=64)
    add("SensorBandResample", "sensor_band_resample", "radiometry", "spectral.algorithms.resampling.BandResampler", "spectral/algorithms/resampling.py",
        "Resample calibrated hyperspectral reflectance to explicit target sensor bands using Gaussian response-overlap integration.",
        "Original SAM/continuum/unmixing tools compare or decompose spectra, and current PCA/MNF changes statistical basis; none integrates explicit source/target wavelength bandwidths. Spatial reprojection changes map coordinates, not spectral response. Unlike original SkdownscaleQuantileBiasCorrection, no empirical scene-distribution mapping is fitted.",
        "spectral-resample", "reflectance", {**wave,
         "input_unit": text("Calibrated dimensionless reflectance in [0,1] only; not DN, radiance or categorical values.", enum=["reflectance"]),
         "source_fwhm_nm": widths("Explicit source FWHMs, one per ordered band; source intervals must not overlap.", 2),
         "target_wavelength_nm": array("Strictly increasing target centers, nm.", number("Target center, nm", minimum=100, maximum=30000), maximum=64),
         "target_fwhm_nm": widths("Explicit target FWHMs; each complete interval must be covered by source support without gaps.", 1),
         "bandpass_source": text("Caller-declared wavelength/bandwidth provenance and justification of the approximate Gaussian response model.")},
        {"wavelength_nm": [1000, 1100], "source_fwhm_nm": [100, 100], "target_wavelength_nm": [1050], "target_fwhm_nm": [200],
         "bandpass_source": "SYNTHETIC adjoining source intervals and symmetric Gaussian target; not a measured sensor response"},
        {**numeric_map(), "source_wavelength_nm": array("Source centers, nm", minimum=2, maximum=64),
         "source_fwhm_nm": array("Source widths, nm", minimum=2, maximum=64),
         "target_wavelength_nm": array("Target centers, nm", maximum=64), "target_fwhm_nm": array("Target widths, nm", maximum=64),
         "resampling_weights": matrix("Dimensionless upstream weights, target rows by source columns; every row sums to one.")},
        {"path": ["mean"], "expected": .4, "reason": "Source intervals [950,1050] and [1050,1150] nm partition a target Gaussian centered at 1050 nm with FWHM 200 nm into equal halves. Symmetry gives weights 1/2,1/2; reflectances .2,.6 therefore yield .4, independently of the upstream implementation."},
        {"target_wavelength_nm": [1300], "target_fwhm_nm": [100]},
        "Approximate Gaussian target response integrated only inside its FWHM; source values are constant across their FWHMs. Complete target coverage and nonoverlapping source intervals are required; no inferred widths, extrapolation or partial-coverage renormalization. All FWHM bounds must lie within 100..30000 nm. Reflectance profile [0,1] only. Preserves spatial CRS/affine and all-band/quality-mask exclusions; exports target-band tags and resampling-weights.csv. Not exact sensor RSR calibration, spectral super-resolution or mineral identification.",
        "spectral", raster_probe={"band": 1, "row": 3, "column": 3, "expected": .4})
    add("TVDenoise", "total_variation_denoise", "radiometry", "skimage.restoration.denoise_tv_chambolle", "src/skimage/restoration/_denoise.py",
        "Denoise image radiometry with Chambolle total-variation regularization.",
        "RemoteSensingTiffAverage averages acquisitions; TV regularizes spatial gradients within one image and does not require temporal repeats.",
        "flat", "normalized_intensity", {"input_unit": text("Continuous nonnegative radiometry; reflectance and normalized intensity restricted to [0,1]. Output retains this unit and is real-valued, never categorical.", enum=CONTINUOUS_UNITS),
         "weight": number("TV weight in supplied intensity units", exclusiveMinimum=0, maximum=10000),
        "iterations": integer("Maximum Chambolle iterations", 1, 200)}, {"weight": .1, "iterations": 20}, numeric_map(),
        {"path": ["mean"], "expected": .5, "reason": "A constant .5 field has zero total variation and is the exact minimizer of the nonnegative ROF objective; every output pixel remains .5."},
        {"weight": 0}, "Can suppress fine geologic texture and create staircase effects; complete patch, explicit weight, bounded iterations. Reject binary/label codes and negative radiometry; reflectance/normalized_intensity profile is [0,1]. Output is continuous in the declared input unit, including fractional DN, not a classification.")
    add("RichardsonLucy", "richardson_lucy_deconvolution", "radiometry", "skimage.restoration.richardson_lucy", "src/skimage/restoration/deconvolution.py",
        "Restore spatial blur by Richardson-Lucy iterations with an explicitly supplied normalized point-spread function.",
        "Existing image previews and difference tools do not invert a supplied instrument point-spread function.",
        "rl", "normalized_intensity", {"psf": matrix("Nonnegative odd-sized normalized PSF, dimensionless", maximum=31),
        "psf_source": text("Provenance of the supplied measured/model PSF."), "iterations": integer("Richardson-Lucy iteration count", 1, 100)},
        {"psf": [[0, 0, 0], [0, 1, 0], [0, 0, 0]], "psf_source": "SYNTHETIC identity PSF", "iterations": 4}, numeric_map(),
        {"path": ["mean"], "expected": .275, "reason": "An identity PSF leaves the row ramp .2+.01*c unchanged; c=0..15 has mean 7.5, giving .275 (tolerance allows upstream epsilon)."},
        {"psf": [[2]]}, "Nonnegative intensity/PSF only; caller PSF is not estimated or normalized silently. Noise amplification and boundary effects remain possible.",
        raster_probe={"band": 1, "row": 8, "column": 10, "expected": .3})
    add("RollingBall", "rolling_ball_background", "radiometry", "skimage.restoration.rolling_ball", "src/skimage/restoration/_rolling_ball.py",
        "Estimate a smooth image background with a rolling-ball intensity surface and export background plus residual.",
        "White top-hat uses a flat morphological footprint; rolling ball uses a curved nonflat intensity surface to estimate spatial background, absent from baseline calibration.",
        "background", "DN", {"radius_pixels": integer("Rolling-ball spatial radius in pixels; kernel height is numerically coupled to intensity scale", 1, 16)},
        {"radius_pixels": 3}, {"background_mean": number("Mean estimated background, input units."), "residual_mean": number("Mean input minus background, input units.")},
        {"path": ["background_mean"], "expected": 4, "reason": "For a constant field 4, the ball tangent at its center yields background exactly 4; no lower background candidate exists."},
        {"radius_pixels": 0}, "Assumes bright features above background. Ball height and spatial radius share a numerical scale, so intensity calibration materially affects behavior.")
    return rows


def output_schema(measurements, intensity_units=None):
    string = {"type": "string"}
    mapping = lambda pattern, value: {"type": "object", "patternProperties": {pattern: value}, "additionalProperties": False}
    provenance = obj({"tool": string, "upstream_url": string, "source_mode": {"const": "package_release"},
        "reviewed_archive_commit": {"type": "string", "pattern": "^[a-f0-9]{40}$"},
        "installed_versions": obj({p.split("==")[0]: {"const": p.split("==")[1]} for p in PINS}),
        "vendored_source": array("No vendored upstream code", string, minimum=0, maximum=0),
        "input_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "implementation_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "contract_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "output_sha256": mapping("^[A-Za-z0-9_.-]+$", {"type": "string", "pattern": "^[a-f0-9]{64}$"}),
        "network_required": {"const": False}, "runtime_source_correspondence": string})
    grid = obj({"width": integer("Columns"), "height": integer("Rows"), "bands": integer("Input spectral bands", 1, 64),
                "crs": string, "affine": array("Preserved affine a,b,c,d,e,f", minimum=6, maximum=6),
                "coordinate_unit": string, "input_nodata": array("Original per-band NoData declarations", {"type": ["string", "null"]}, maximum=64),
                "valid_pixels": integer("Effective analysis pixels", 1), "excluded_pixels": integer("Excluded pixels", 0)})
    schema = obj({"grid": grid, "measurements": obj(measurements),
                "raster_statistics": array("Per-output-band valid-pixel statistics", obj({"band": integer("Band"),
                    "minimum": number("Minimum"), "maximum": number("Maximum"), "mean": number("Mean"),
                    "valid_pixels": integer("Valid cells"), "unit": string}), minimum=0, maximum=64),
                "output_nodata": {"type": ["string", "null"]},
                "units": obj({"input": string, **{k: string for k in measurements}}),
                "artifacts": array("Local artifacts", string, minimum=1, maximum=8), "provenance": provenance})
    if intensity_units is not None:
        for field in ("input", "minimum", "maximum", "mean"):
            schema["properties"]["units"]["properties"][field] = {"type": "string", "enum": intensity_units}
        schema["properties"]["raster_statistics"]["items"]["properties"]["unit"] = {"type": "string", "enum": intensity_units}
    return schema


def spec(row):
    src = SOURCES[row["package"]]
    url = "https://github.com/" + src["repository"]
    source_url = url + "/blob/" + src["commit"] + "/" + row["source_path"]
    fields = {"raster_path": text("Local calibrated GeoTIFF; explicit CRS, affine and units; at most 65536 pixels/1048576 values."),
              "input_unit": text("Shared calibrated physical unit or explicit image coding.", enum=["reflectance", "radiance", "DN", "brightness_temperature_K", "normalized_intensity", "binary", "label"]),
              "quality_mask_path": text("Optional aligned one-band GeoTIFF: 1 valid, 0 excluded; NoData excluded."), **row["fields"]}
    schema = obj(fields, [k for k in fields if k != "quality_mask_path"])
    function = {"type": "function", "function": {"name": row["tool_id"], "description": row["scientific_task"], "parameters": schema}}
    intensity_units = fields["input_unit"]["enum"] if row["tool_id"] in ("GeoRemoteTVDenoise", "GeoRemoteSensorBandResample") else None
    metadata = {"asset_version": "1.1.0", "provider": src["repository"].split("/")[0],
                "license": None, "upstream_license": src["license"], "source_url": url,
                "source_commit": src["commit"], "official_protocol_version": None,
                "official_protocol": {"applicability": "not_applicable", "name": None, "version": None},
                "metadata_profile": "scientific", "runtime": {"python": "==3.12.*", "dependency_lock": GROUP + "/requirements.txt",
                "environment_version": "github-expansion-remote-20261025-r2"},
                "lifecycle": {"registration": "not_submitted", "contract_validation": "not_run", "unit_validation": "not_run",
                              "workflow_validation": "not_run", "platform_validation": "not_run", "release_status": "draft"},
                "pending_fields": ["adapter_license", "receiving_lab_approval", "cpu_acceptance"], "platform_validation": "not_run"}
    return {"id": row["tool_id"], "name": row["tool_id"], "description": row["scientific_task"],
            "input_schema": schema, "output_schema": output_schema(row["measurements"], intensity_units),
            "constraints": {"finite_numbers_only": True, "no_implicit_reprojection": True, "no_automatic_dependency_install": True,
                            "max_file_bytes": 67108864, "max_json_bytes": 4000000, "max_pixels": 65536, "max_elements": 1048576},
            "metadata": {"category": "github_expansion_remote", "input_format": "JSON args and local calibrated GeoTIFFs",
                         "output_format": "Strict JSON, CSV, and GeoTIFF/PNG for mapped results", "source": source_url,
                         "upstream": {"package": row["package"], "version": src["version"], "license": src["license"],
                                      "url": url, "requirements": PINS, "source_mode": "package_release",
                                      "callable": row["upstream_callable"], "api_source_url": source_url,
                                      "release_url": src["release_url"], "source_commit": src["commit"]},
                         "scientific_contract": {"implementation_kind": "upstream_library", "review_status": "acceptance_pending",
                                                 "formal_eligible": False, "numeric_oracle": row["oracle"]["reason"],
                                                 "fixture_status": "explicitly_synthetic", "execution_status": "NOT TESTED"}},
            "category": "github_expansion_remote", "function": function, "function_definition": copy.deepcopy(function),
            "version": "1.1.0", "example_arguments": row["example"],
            "limitations": [row["limitation"], "NOT TESTED / NOT DEPLOYED / NOT SUBMITTED. CPU acceptance is pending.",
                            "Synthetic fixtures are not observations. No mineral, ore-grade, reserve or geological-contact inference.",
                            "No automatic downloads or code selection. User-declared sources and units are not independent authentication."],
            "source_interface": {"status": "source_revised_unverified", "kind": "github_expansion_remote",
                                 "path_fields": [k for k in fields if k.endswith("_path")], "network_required": False,
                                 "pure": False, "validation": "acceptance_pending", "entrypoint": {
                                     "callable": MODULE + ":" + row["function"], "argument_parameter": "args",
                                     "bound_arguments": {}, "output_directory_parameter": "output_dir"}},
            "error_contract": {"direct_exception": "ScientificToolError", "fields": ["code", "message", "retryable"],
                               "codes": ["invalid_arguments", "missing_input", "missing_dependency", "incompatible_dependency",
                                         "resource_limit", "invalid_input", "invalid_result", "invalid_path", "empty_input",
                                         "unsupported_conditions", "output_conflict", "upstream_failure"],
                               "retry_policy": "Correct the declared inputs/dependency profile; do not retry deterministic failures blindly."},
            "tags": ["remote-sensing", "image-analysis", row["workflow"], row["package"]], "registration_metadata": metadata}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")


def write_tiff(path, values):
    """Author tiny synthetic GeoTIFF fixtures with stdlib, without importing kernels."""
    height, width = len(values), len(values[0])
    bands = len(values[0][0]) if isinstance(values[0][0], list) else 1
    samples = [v for row in values for pixel in row for v in (pixel if isinstance(pixel, list) else [pixel])]
    data = struct.pack("<" + "d" * len(samples), *samples)
    u16 = lambda seq: struct.pack("<" + "H" * len(seq), *seq)
    u32 = lambda v: struct.pack("<I", v)
    f64 = lambda seq: struct.pack("<" + "d" * len(seq), *seq)
    description = b"SYNTHETIC analytic acceptance fixture; NOT geological observations\0"
    tags = [(256, 4, 1, u32(width)), (257, 4, 1, u32(height)), (258, 3, bands, u16([64] * bands)),
            (259, 3, 1, u16([1])), (262, 3, 1, u16([1])), (270, 2, len(description), description),
            (273, 4, 1, b"\0" * 4), (277, 3, 1, u16([bands])), (278, 4, 1, u32(height)),
            (279, 4, 1, u32(len(data))), (284, 3, 1, u16([1])), (339, 3, bands, u16([3] * bands)),
            (33550, 12, 3, f64([30, 30, 0])), (33922, 12, 6, f64([0, 0, 0, 500000, 4500000, 0])),
            (34735, 3, 20, u16([1, 1, 0, 4, 1024, 0, 1, 1, 1025, 0, 1, 1, 3072, 0, 1, 32650, 3076, 0, 1, 9001])),
            (42113, 2, 6, b"-9999\0")]
    if bands > 1:
        tags.append((338, 3, bands - 1, u16([0] * (bands - 1))))
    tags.sort()
    offset = 8 + 2 + 12 * len(tags) + 4
    extra = bytearray()
    entries = []
    for tag, kind, count, value in tags:
        if len(value) > 4:
            if (offset + len(extra)) % 2:
                extra += b"\0"
            packed = u32(offset + len(extra))
            extra += value
        else:
            packed = value.ljust(4, b"\0")
        entries.append([tag, kind, count, packed])
    if (offset + len(extra)) % 8:
        extra += b"\0" * (8 - (offset + len(extra)) % 8)
    for entry in entries:
        if entry[0] == 273:
            entry[3] = u32(offset + len(extra))
    header = b"II" + u16([42]) + u32(8) + u16([len(entries)])
    table = b"".join(struct.pack("<HHI", *entry[:3]) + entry[3] for entry in entries) + u32(0)
    path.write_bytes(header + table + extra + data)


def fixtures():
    folder = ROOT / ASSET
    folder.mkdir(parents=True, exist_ok=True)
    grid = lambda fn, n=16: [[fn(r, c) for c in range(n)] for r in range(n)]
    block = lambda r, c: 7 <= r <= 9 and 7 <= c <= 9
    data = {
        "spectral-pca": [[[0, 0], [2, 0]], [[0, 4], [2, 4]]],
        "spectral-noise": [[[0, 0], [1, 2], [0, 0]], [[0, 0], [1, 2], [0, 0]]],
        "spectral-resample": grid(lambda r, c: [-9999, .6] if (r, c) == (0, 0) else [.2, .6], 8),
        "quality-spectral": grid(lambda r, c: int((r, c) != (1, 1)), 8),
        "spectral-targets": grid(lambda r, c: [-9999, -9999] if (r, c) == (0, 0) else [2, 1], 8),
        "peak": grid(lambda r, c: 10 if (r, c) == (8, 8) else 2),
        "constraint": grid(lambda r, c: 5 if block(r, c) else 0),
        "seed": grid(lambda r, c: 2 if (r, c) == (8, 8) else 0),
        "skeleton": grid(lambda r, c: int(r == 8 and 3 <= c < 12)),
        "objects": grid(lambda r, c: int(block(r, c) or (r, c) == (2, 2))),
        "holes": grid(lambda r, c: int(block(r, c) and (r, c) != (8, 8))),
        "checkerboard": grid(lambda r, c: (r + c) % 2),
        "constant-dn": grid(lambda r, c: 4), "ramp": grid(lambda r, c: c),
        "impulse": grid(lambda r, c: int((r, c) == (8, 8))),
        "step": grid(lambda r, c: int(c >= 8)), "step-dn": grid(lambda r, c: 6 if c >= 8 else 2),
        "flat": grid(lambda r, c: .5), "quarter": grid(lambda r, c: .25),
        "markers-one": grid(lambda r, c: int((r, c) == (8, 8))), "zeros": grid(lambda r, c: 0),
        "walker": grid(lambda r, c: c / 7, 8),
        "markers-walker": grid(lambda r, c: 1 if c == 0 else (2 if c == 7 else 0), 8),
        "regions": grid(lambda r, c: int(2 <= r < 4 and 2 <= c < 5)),
        "registration-reference": grid(lambda r, c: int((r, c) == (6, 6))),
        "registration-moving": grid(lambda r, c: int((r, c) == (8, 5))),
        "histogram-reference": grid(lambda r, c: 4 if c >= 8 else 2),
        "rl": grid(lambda r, c: .2 + .01*c), "background": grid(lambda r, c: 4),
        "quality": grid(lambda r, c: int((r, c) != (0, 0))),
    }
    for name, values in data.items():
        write_tiff(folder / (name + ".tif"), values)
    (folder / "README.md").write_text("# Synthetic remote-sensing inputs\n\nAll fixtures are synthetic analytic constructions, NOT observations or mineral evidence. "
        "Their arbitrary EPSG:32650 grid (30 m pixels, origin 500000,4500000) exists only to exercise georeferencing. "
        "Detector and band-resampling fixtures exclude the top-left pixel with NoData=-9999; the latter has NoData in only its first source band. "
        "The 8x8 quality-spectral fixture excludes (1,1). histogram-reference.tif is retained only for the excluded r1 duplicate record. No real location or sensor is represented. "
        "Fixture generation uses only the standard library; the r2 source revision remains NOT TESTED. Historical r1 CPU reports are not rewritten or claimed as r2 evidence.\n", encoding="utf-8")
    return [ASSET + "/" + name + ".tif" for name in data] + [ASSET + "/README.md"]


def excluded_candidates():
    """Historical source evidence only; never returned by records() or registered."""
    old_reason = "Equal populations at 0 and 1 map by empirical quantiles to equal reference populations at 2 and 4, with mean 3."
    return {"group": "remote", "operations": [{
        "tool_id": "GeoRemoteHistogramMatch", "status": "excluded_semantic_duplicate",
        "counted_as_new": False, "duplicate_of": "SkdownscaleQuantileBiasCorrection",
        "replacement_tool_id": "GeoRemoteSensorBandResample",
        "decision": "Both implement empirical CDF/inverse-CDF quantile mapping. Tie handling, plotting positions and raster packaging do not establish a distinct scientific operation.",
        "original_candidate": {"tool_id": "GeoRemoteHistogramMatch",
            "capability_key": "remote-sensing:relative-histogram-match",
            "upstream_callable": "skimage.exposure.match_histograms",
            "scientific_task": "Normalize one acquisition's empirical intensity distribution to a supplied reference acquisition.",
            "distinct_from_existing": "Existing raster scale/offset calibration is affine; empirical histogram matching applies a monotone quantile mapping to the common valid support.",
            "numeric_oracle": old_reason, "status": "source_authored_unverified"},
        "original_example": {"raster_path": ASSET + "/step.tif", "input_unit": "DN", "reference_path": ASSET + "/histogram-reference.tif"},
        "original_oracle": {"path": ["mean"], "expected": 3, "reason": old_reason},
        "upstream": {"package": "scikit-image", "version": SOURCES["scikit-image"]["version"],
            "source_commit": SOURCES["scikit-image"]["commit"], "license": SOURCES["scikit-image"]["license"],
            "source_url": "https://github.com/scikit-image/scikit-image/blob/" + SOURCES["scikit-image"]["commit"] + "/src/skimage/exposure/histogram_matching.py"},
        "baseline_source_url": "https://github.com/pangeo-data/scikit-downscale/blob/44d042584e0fd96bc16e2fca4caa928c5718b970/skdownscale/pointwise_models/quantile.py",
        "original_adapter_source": "@operation(\"GeoRemoteHistogramMatch\")\ndef relative_histogram_match(args, output_dir=None):\n    import numpy as np\n    from skimage.exposure import match_histograms\n    loaded, reference = _pair(args, complete=False)\n    image, valid, _, _ = loaded\n    result = np.zeros(image.shape)\n    result[valid] = match_histograms(image[valid], reference[valid], channel_axis=None)\n    return _image_result(args, output_dir, loaded, result, args[\"input_unit\"])\n",
        "historical_evidence": "The parent reported 29 passing r1 numeric subcases and a matched-filter shape failure. This record does not modify that report or treat the duplicate as net-new."}]}


def main():
    rows = records()
    tools = [spec(row) for row in rows]
    skills = []
    titles = {"spectral": "Spectral noise, dimensional reduction and detection", "morphology": "Image-mask morphology and feature support",
              "texture": "Remote-image texture and directional features", "segmentation": "Seeded and unsupervised image segmentation",
              "radiometry": "Image registration, sensor-band harmonization and restoration"}
    for workflow, title in titles.items():
        members = [row for row in rows if row["workflow"] == workflow]
        ids = [row["tool_id"] for row in members]
        key = "github-remote-" + workflow
        path = "catalog/skills/" + key + "/SKILL.md"
        meta = copy.deepcopy(tools[0]["registration_metadata"])
        meta.update(provider="GeoAgent", source_commit=None, source_url=None, upstream_license=None)
        skills.append({"id": key, "name": title, "description": "Choose among six bounded offline operations for " + title.lower() + ".",
                       "tool_references": ids, "skill_file": path, "metadata": {"canonical_skill_file": path, "validation": "not_run"},
                       "delivery": {"source_candidates": ids, "unavailable_references": [],
                                    "availability_status": "tool_candidates_available_workflow_unverified", "workflow_validation": "not_run",
                                    "deployment_status": "not_deployed", "submission_status": "not_submitted", "model_workflow_validation": "not_run",
                                    "receiving_lab_approval": "pending"}, "registration_metadata": meta})
        body = "---\nid: " + key.replace("-", "_") + "\nname: " + json.dumps(title) + "\ndescription: " + json.dumps(skills[-1]["description"]) + "\nwhen_to_use: " + json.dumps("Use when supplied calibrated imagery requires " + title.lower()) + "\ntools:\n"
        body += "".join("- " + tool + "\n" for tool in ids)
        body += "required_inputs:\n- Local calibrated GeoTIFFs with explicit CRS, affine transform and units\n- Operation-specific parameters, declared reference provenance, and quality exclusions\nconstraints:\n- Select only the relevant operation and preserve numerical evidence\n- Never infer ore grade, mineral presence or geological contacts from these outputs\n- Never install packages, fetch imagery or execute generated code at call time\nexpected_outputs:\n- Strict numeric JSON, units, input and artifact hashes\n- CSV and mapped GeoTIFF/PNG where applicable\n---\n\n# " + title
        body += "\n\n## When to use\n\nUse this workflow only with supplied image evidence and an explicit scientific question. Load the individual tool schema after selecting the needed operation."
        body += "\n\n## Required inputs\n\nEach operation takes args as a dictionary or JSON object string plus a new or empty output_dir. Input paths are local task assets. The caller declares physical units and reference provenance. Raster values must already be calibrated; nonidentity stored scales/offsets are rejected."
        body += "\n\n## Workflow\n\n1. Establish band order, units, image registration and valid support.\n2. Select the operation below whose scientific assumptions match the question.\n3. Inspect numeric results, preserved georeferencing and artifact hashes.\n4. Retain limitations and uncertainty; use independent observations for geological interpretation.\n"
        for row in members:
            src = SOURCES[row["package"]]
            source_url = "https://github.com/" + src["repository"] + "/blob/" + src["commit"] + "/" + row["source_path"]
            body += "\n## " + row["tool_id"] + "\n\n" + row["scientific_task"] + "\n\n" + row["limitation"]
            body += "\n\nSynthetic example:\n\n```json\n" + json.dumps(row["example"], indent=2) + "\n```\n"
            body += "\nUpstream: [" + row["upstream_callable"] + "](" + source_url + "), " + row["package"] + "==" + src["version"] + ".\n"
        body += "\n## Constraints and error behavior\n\nFinite values only. No spatial reprojection/resampling, imputed pixels or runtime networking. SensorBandResample alone changes spectral discretization under explicit full-coverage bandwidth constraints, not the spatial grid. Complete-patch kernels reject masked gaps; mask-aware/sample-wise kernels retain effective exclusions. ScientificToolError reports bounded native error codes. See the group's FILE_SCHEMAS.md and exact tool schema."
        body += "\n\n## Expected outputs and provenance\n\nCSV measurements accompany every result. Mapped operations also produce a float64 GeoTIFF with CRS/affine and effective mask preserved plus a PNG preview. Noise covariance, GLCM, region measurements and estimated registration shifts are tables. The input NoData declaration is retained in JSON; output sentinel is retained when finite and noncolliding, otherwise explicitly replaced. Hashes come from the native collection contract."
        body += "\n\n## Source interface and delivery\n\nFixed module: " + MODULE + ". source_interface.kind: github_expansion_remote. No arbitrary module, function, or code input is accepted. Central whitelist/worker integration belongs to the parent."
        body += "\n\n## Current availability\n\nNOT TESTED / NOT DEPLOYED / NOT SUBMITTED for r2. Historical r1 CPU reports are preserved and are not r2 acceptance evidence. Source authored only. Contract, CPU, model-workflow and platform acceptance for r2: not_run. Receiving lab approval and adapter license: pending. Existing deployed 229-tool catalog is unchanged by this contribution.\n"
        destination = ROOT / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(body, encoding="utf-8")
    write_json(HERE / "catalog-additions.json", {"tools": tools, "skills": skills})
    write_json(HERE / "examples-additions.json", {row["tool_id"]: row["example"] for row in rows})
    write_json(HERE / "candidate-operations.json", {"group": "remote", "operations": [
        {"tool_id": row["tool_id"], "capability_key": "remote-sensing:" + row["function"].replace("_", "-"),
         "upstream_callable": row["upstream_callable"], "scientific_task": row["scientific_task"],
         "distinct_from_existing": row["distinct_from_existing"], "numeric_oracle": row["oracle"]["reason"],
         "status": "source_authored_unverified"} for row in rows]})
    excluded = excluded_candidates()
    write_json(HERE / "excluded-candidates.json", excluded)
    sources = copy.deepcopy(SOURCES)
    for package, source in sources.items():
        base = "https://github.com/" + source["repository"]
        source.update(repository_url=base, license_url=base + "/blob/" + source["commit"] + "/" + source["license_path"],
                      license_evidence_file=GROUP + "/licenses/" + package + ".txt",
                      release_commit_correspondence="Annotated release tag dereferenced through official GitHub API to the exact source commit.",
                      distribution_correspondence="Published version and release-tag source reviewed; installed distribution contents have NOT been compared.")
    write_json(HERE / "sources.json", {"group": "remote", "research_date": "2026-10-25", "sources": sources,
        "operations": [{"tool_id": row["tool_id"], "upstream_callable": row["upstream_callable"],
                        "source_url": "https://github.com/" + SOURCES[row["package"]]["repository"] + "/blob/" + SOURCES[row["package"]]["commit"] + "/" + row["source_path"]} for row in rows],
        "excluded_operations": [{"tool_id": "GeoRemoteHistogramMatch", "duplicate_of": "SkdownscaleQuantileBiasCorrection",
                                 "counted_as_new": False, "record_file": GROUP + "/excluded-candidates.json",
                                 "upstream_callable": "skimage.exposure.match_histograms",
                                 "source_url": "https://github.com/scikit-image/scikit-image/blob/" + SOURCES["scikit-image"]["commit"] + "/src/skimage/exposure/histogram_matching.py"}],
        "compatibility": {"python": "3.12", "pins": PINS, "basis": "User-confirmed deployed versions plus upstream API/source review; NOT locally executed.",
                          "new_private_packages": [], "main_runtime_changes": "none", "transitive_lock": "Existing environment retained; this file pins direct imports, not a fresh-environment full transitive lock."},
        "pysptools": {"used": False, "documented_project": "https://pysptools.sourceforge.io/", "reason": "Not required; no reliance on the invalid pysptools/pysptools GitHub URL."}})
    (HERE / "requirements.txt").write_text("# Direct CPU dependency pins; preserve shared environment. NOT INSTALLED OR TESTED HERE.\n" + "\n".join(PINS) + "\n", encoding="utf-8")
    fixture_paths = fixtures()
    write_json(ROOT / ASSET / "oracles.json", {"fixture_status": "SYNTHETIC ONLY", "execution_status": "NOT TESTED",
        "operations": {row["tool_id"]: {"measurement": row["oracle"], "negative_overrides": row["negative"],
                                      "raster_probe": row["raster_probe"], "absolute_tolerance": 1e-7} for row in rows}})
    generated_paths = [GROUP + "/" + name for name in
                       ("catalog-additions.json", "examples-additions.json", "candidate-operations.json",
                        "sources.json", "requirements.txt", "excluded-candidates.json", "r2-delivery.json")]
    generated_paths += [skill["skill_file"] for skill in skills] + fixture_paths + [ASSET + "/oracles.json"]
    write_json(HERE / "r2-delivery.json", {
        "group": "remote", "revision": "r2", "source_operations": len(tools), "skills": len(skills),
        "excluded_semantic_duplicates": ["GeoRemoteHistogramMatch"], "pins": PINS,
        "status": "NOT TESTED / NOT DEPLOYED / NOT SUBMITTED",
        "history_policy": "Historical r1 CPU reports remain unchanged; no r1 pass is promoted to r2 verification.",
        "new_private_packages": [], "generated_paths": sorted(generated_paths),
        "authored_source_paths": ["geological_agent/geology/github_expansion_remote.py",
                                 "tests_local/test_github_expansion_remote.py", GROUP + "/build_contribution.py",
                                 GROUP + "/FILE_SCHEMAS.md", GROUP + "/R2_HANDOFF.md"],
        "pending": ["Parent CPU acceptance of all 30 operations and negative/provenance cases",
                    "Parent shared dispatch/registry integration", "Adapter license and receiving-lab approval"]})
    print(json.dumps({"group": "remote", "revision": "r2", "tools_authored": len(tools), "skills_authored": len(skills),
                      "excluded_duplicates": 1,
                      "status": "NOT TESTED / NOT DEPLOYED / NOT SUBMITTED", "global_catalog_modified": False}))


if __name__ == "__main__":
    main()

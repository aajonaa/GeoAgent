---
id: github_remote_segmentation
name: "Seeded and unsupervised image segmentation"
description: "Choose among six bounded offline operations for seeded and unsupervised image segmentation."
when_to_use: "Use when supplied calibrated imagery requires seeded and unsupervised image segmentation"
tools:
- GeoRemoteOtsu
- GeoRemoteWatershed
- GeoRemoteSLIC
- GeoRemoteFelzenszwalb
- GeoRemoteRandomWalker
- GeoRemoteRegionProperties
required_inputs:
- Local calibrated GeoTIFFs with explicit CRS, affine transform and units
- Operation-specific parameters, declared reference provenance, and quality exclusions
constraints:
- Select only the relevant operation and preserve numerical evidence
- Never infer ore grade, mineral presence or geological contacts from these outputs
- Never install packages, fetch imagery or execute generated code at call time
expected_outputs:
- Strict numeric JSON, units, input and artifact hashes
- CSV and mapped GeoTIFF/PNG where applicable
---

# Seeded and unsupervised image segmentation

## When to use

Use this workflow only with supplied image evidence and an explicit scientific question. Load the individual tool schema after selecting the needed operation.

## Required inputs

Each operation takes args as a dictionary or JSON object string plus a new or empty output_dir. Input paths are local task assets. The caller declares physical units and reference provenance. Raster values must already be calibrated; nonidentity stored scales/offsets are rejected.

## Workflow

1. Establish band order, units, image registration and valid support.
2. Select the operation below whose scientific assumptions match the question.
3. Inspect numeric results, preserved georeferencing and artifact hashes.
4. Retain limitations and uncertainty; use independent observations for geological interpretation.

## GeoRemoteOtsu

Derive an image threshold by maximizing between-class histogram variance and export its binary partition.

Binary histogram partition is not a land-cover or mineral label; caller quantization is retained.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/step-dn.tif",
  "input_unit": "DN"
}
```

Upstream: [skimage.filters.threshold_otsu](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/filters/thresholding.py), scikit-image==0.26.0.

## GeoRemoteWatershed

Partition an image cost surface by flooding from explicit labeled markers.

Four-neighbor image flooding; every connected valid domain must have a seed; markers are human/model inputs, not inferred ground truth.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/flat.tif",
  "input_unit": "normalized_intensity",
  "markers_path": "assets/github-expansion-remote/markers-one.tif"
}
```

Upstream: [skimage.segmentation.watershed](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/segmentation/_watershed.py), scikit-image==0.26.0.

## GeoRemoteSLIC

Create compact image superpixels using joint intensity and pixel-coordinate clustering.

Single-band profile; upstream rescales intensities internally; requested count is approximate, spatial scale uses pixels.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/flat.tif",
  "input_unit": "normalized_intensity",
  "segments": 1,
  "compactness": 10
}
```

Upstream: [skimage.segmentation.slic](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/segmentation/slic_superpixels.py), scikit-image==0.26.0.

## GeoRemoteFelzenszwalb

Segment intensity imagery by graph edge weights and adaptive component merging.

No Gaussian prefilter, single-band image; labels are shifted from upstream zero-based to one-based for clear background semantics.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/flat.tif",
  "input_unit": "normalized_intensity",
  "scale": 100,
  "min_size_pixels": 1
}
```

Upstream: [skimage.segmentation.felzenszwalb](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/segmentation/_felzenszwalb.py), scikit-image==0.26.0.

## GeoRemoteRandomWalker

Estimate seeded class probabilities by solving an intensity-weighted image diffusion problem.

At most 4096 pixels and 2..8 classes, direct CPU sparse solve; probabilities condition on seeds/weights and are not geological posterior confidence.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/walker.tif",
  "input_unit": "normalized_intensity",
  "markers_path": "assets/github-expansion-remote/markers-walker.tif",
  "beta": 0
}
```

Upstream: [skimage.segmentation.random_walker](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/segmentation/random_walker_segmentation.py), scikit-image==0.26.0.

## GeoRemoteRegionProperties

Measure pixel area, centroid, orientation and shape descriptors of supplied labeled image regions.

Labels 0..4096, zero ignored; disconnected cells sharing one label are one region. Areas/centroids are pixels, not projected area estimates.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/regions.tif",
  "input_unit": "label"
}
```

Upstream: [skimage.measure.regionprops_table](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/measure/_regionprops.py), scikit-image==0.26.0.

## Constraints and error behavior

Finite values only. No spatial reprojection/resampling, imputed pixels or runtime networking. SensorBandResample alone changes spectral discretization under explicit full-coverage bandwidth constraints, not the spatial grid. Complete-patch kernels reject masked gaps; mask-aware/sample-wise kernels retain effective exclusions. ScientificToolError reports bounded native error codes. See the group's FILE_SCHEMAS.md and exact tool schema.

## Expected outputs and provenance

CSV measurements accompany every result. Mapped operations also produce a float64 GeoTIFF with CRS/affine and effective mask preserved plus a PNG preview. Noise covariance, GLCM, region measurements and estimated registration shifts are tables. The input NoData declaration is retained in JSON; output sentinel is retained when finite and noncolliding, otherwise explicitly replaced. Hashes come from the native collection contract.

## Source interface and delivery

Fixed module: geological_agent.geology.github_expansion_remote. source_interface.kind: github_expansion_remote. No arbitrary module, function, or code input is accepted. Central whitelist/worker integration belongs to the parent.

## Current availability

NOT TESTED / NOT DEPLOYED / NOT SUBMITTED for r2. Historical r1 CPU reports are preserved and are not r2 acceptance evidence. Source authored only. Contract, CPU, model-workflow and platform acceptance for r2: not_run. Receiving lab approval and adapter license: pending. Existing deployed 229-tool catalog is unchanged by this contribution.

### Native call bindings

Use the registered native operation with its declared JSON input schema. The following bindings come from catalog/registry.json; use catalog/source_delivery/examples.json for exact accepted argument examples. Do not substitute guessed arguments, units or scientific algorithms.

| Native tool | Source callable |
| --- | --- |
| `GeoRemoteOtsu` | `geological_agent.geology.github_expansion_remote:otsu_segmentation` |
| `GeoRemoteWatershed` | `geological_agent.geology.github_expansion_remote:marker_watershed` |
| `GeoRemoteSLIC` | `geological_agent.geology.github_expansion_remote:slic_superpixels` |
| `GeoRemoteFelzenszwalb` | `geological_agent.geology.github_expansion_remote:graph_segmentation` |
| `GeoRemoteRandomWalker` | `geological_agent.geology.github_expansion_remote:seeded_random_walker` |
| `GeoRemoteRegionProperties` | `geological_agent.geology.github_expansion_remote:segmented_region_properties` |

Parameter constraints, units, result schema, artifact references and structured error semantics are defined by each tool in the registry. Pure numeric operations return their declared JSON result; operations with output files must preserve their artifact paths, sizes and hashes. Missing dependencies must remain explicit errors. Do not install packages or alter shared environments during execution.

### Current availability

tool_candidates_available_workflow_unverified

The native references resolve in the deployed OreSage registry. This documentation repair adds the missing handoff sections; it does not certify full Skill workflows, external data services or AI Lab acceptance. `workflow_validation=not_run` and `platform_validation=not_run` remain unchanged.

Earlier status statements in this source document are historical source-authoring records. Current deployment evidence is recorded in docs/releases/xiaoyu-skills-20261029.md; historical NOT DEPLOYED statements must not be read as the current runtime status. Upstream licenses, scientific limitations and prior failed records remain unchanged.

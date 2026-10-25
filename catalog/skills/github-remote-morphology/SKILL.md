---
id: github_remote_morphology
name: "Image-mask morphology and feature support"
description: "Choose among six bounded offline operations for image-mask morphology and feature support."
when_to_use: "Use when supplied calibrated imagery requires image-mask morphology and feature support"
tools:
- GeoRemoteWhiteTophat
- GeoRemoteSeedReconstruction
- GeoRemoteSkeleton
- GeoRemoteRemoveSmallObjects
- GeoRemoteFillSmallHoles
- GeoRemoteHMaxima
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

# Image-mask morphology and feature support

## When to use

Use this workflow only with supplied image evidence and an explicit scientific question. Load the individual tool schema after selecting the needed operation.

## Required inputs

Each operation takes args as a dictionary or JSON object string plus a new or empty output_dir. Input paths are local task assets. The caller declares physical units and reference provenance. Raster values must already be calibrated; nonidentity stored scales/offsets are rejected.

## Workflow

1. Establish band order, units, image registration and valid support.
2. Select the operation below whose scientific assumptions match the question.
3. Inspect numeric results, preserved georeferencing and artifact hashes.
4. Retain limitations and uncertainty; use independent observations for geological interpretation.

## GeoRemoteWhiteTophat

Extract compact bright image features by white top-hat morphology at an explicit spatial scale.

Square footprint and reflect borders; complete patch required. Feature scale is pixels, not geological size.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/peak.tif",
  "input_unit": "DN",
  "radius_pixels": 1
}
```

Upstream: [skimage.morphology.white_tophat](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/morphology/gray.py), scikit-image==0.26.0.

## GeoRemoteSeedReconstruction

Propagate supplied intensity seeds under a constraining image by grayscale geodesic reconstruction.

Dilation reconstruction, full 8-neighbor footprint, complete patch; supplied seeds determine results.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/constraint.tif",
  "input_unit": "DN",
  "seed_path": "assets/github-expansion-remote/seed.tif"
}
```

Upstream: [skimage.morphology.reconstruction](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/morphology/grayreconstruct.py), scikit-image==0.26.0.

## GeoRemoteSkeleton

Thin a supplied binary image feature mask to a one-pixel skeleton using Zhang thinning.

Cell count is not physical line length or evidence of a fault; complete binary patch required.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/skeleton.tif",
  "input_unit": "binary"
}
```

Upstream: [skimage.morphology.skeletonize](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/morphology/_skeletonize.py), scikit-image==0.26.0.

## GeoRemoteRemoveSmallObjects

Remove small connected detections by inclusive pixel-area threshold with four-neighbor connectivity.

Uses scikit-image 0.26 inclusive max_size, not deprecated exclusive min_size; complete patch required.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/objects.tif",
  "input_unit": "binary",
  "max_size_pixels": 1
}
```

Upstream: [skimage.morphology.remove_small_objects](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/morphology/misc.py), scikit-image==0.26.0.

## GeoRemoteFillSmallHoles

Fill small connected background gaps in a supplied binary detection mask.

Upstream can also fill a small background component touching the boundary; not an enclosed-hole-only guarantee. No NoData filling.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/holes.tif",
  "input_unit": "binary",
  "max_size_pixels": 1
}
```

Upstream: [skimage.morphology.remove_small_holes](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/morphology/misc.py), scikit-image==0.26.0.

## GeoRemoteHMaxima

Identify image maxima with a declared minimum intensity prominence.

Returns maxima plateaus, not independent point objects or mineral targets; complete nonconstant patch required.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/peak.tif",
  "input_unit": "DN",
  "height": 3
}
```

Upstream: [skimage.morphology.h_maxima](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/morphology/extrema.py), scikit-image==0.26.0.

## Constraints and error behavior

Finite values only. No spatial reprojection/resampling, imputed pixels or runtime networking. SensorBandResample alone changes spectral discretization under explicit full-coverage bandwidth constraints, not the spatial grid. Complete-patch kernels reject masked gaps; mask-aware/sample-wise kernels retain effective exclusions. ScientificToolError reports bounded native error codes. See the group's FILE_SCHEMAS.md and exact tool schema.

## Expected outputs and provenance

CSV measurements accompany every result. Mapped operations also produce a float64 GeoTIFF with CRS/affine and effective mask preserved plus a PNG preview. Noise covariance, GLCM, region measurements and estimated registration shifts are tables. The input NoData declaration is retained in JSON; output sentinel is retained when finite and noncolliding, otherwise explicitly replaced. Hashes come from the native collection contract.

## Source interface and delivery

Fixed module: geological_agent.geology.github_expansion_remote. source_interface.kind: github_expansion_remote. No arbitrary module, function, or code input is accepted. Central whitelist/worker integration belongs to the parent.

## Current availability

NOT TESTED / NOT DEPLOYED / NOT SUBMITTED for r2. Historical r1 CPU reports are preserved and are not r2 acceptance evidence. Source authored only. Contract, CPU, model-workflow and platform acceptance for r2: not_run. Receiving lab approval and adapter license: pending. Existing deployed 229-tool catalog is unchanged by this contribution.

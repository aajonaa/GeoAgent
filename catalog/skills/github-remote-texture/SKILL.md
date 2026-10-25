---
id: github_remote_texture
name: "Remote-image texture and directional features"
description: "Choose among six bounded offline operations for remote-image texture and directional features."
when_to_use: "Use when supplied calibrated imagery requires remote-image texture and directional features"
tools:
- GeoRemoteGLCM
- GeoRemoteLocalEntropy
- GeoRemoteLBP
- GeoRemoteStructureTensor
- GeoRemoteGabor
- GeoRemoteCanny
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

# Remote-image texture and directional features

## When to use

Use this workflow only with supplied image evidence and an explicit scientific question. Load the individual tool schema after selecting the needed operation.

## Required inputs

Each operation takes args as a dictionary or JSON object string plus a new or empty output_dir. Input paths are local task assets. The caller declares physical units and reference provenance. Raster values must already be calibrated; nonidentity stored scales/offsets are rejected.

## Workflow

1. Establish band order, units, image registration and valid support.
2. Select the operation below whose scientific assumptions match the question.
3. Inspect numeric results, preserved georeferencing and artifact hashes.
4. Retain limitations and uncertainty; use independent observations for geological interpretation.

## GeoRemoteGLCM

Measure directional gray-level co-occurrence texture from explicitly quantized image intensities.

No implicit quantization; one supplied patch, symmetric pairs. Upstream constant-texture correlation convention is 1.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/checkerboard.tif",
  "input_unit": "DN",
  "levels": 2,
  "distance_pixels": 1,
  "angle_degrees": 0
}
```

Upstream: [skimage.feature.graycomatrix](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/feature/texture.py), scikit-image==0.26.0.

## GeoRemoteLocalEntropy

Map neighborhood Shannon entropy of explicitly quantized image intensities, excluding quality-mask pixels.

Entropy depends on supplied quantization and valid footprint population; borders use truncated neighborhoods.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/checkerboard.tif",
  "input_unit": "DN",
  "radius_pixels": 1
}
```

Upstream: [skimage.filters.rank.entropy](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/filters/rank/generic.py), scikit-image==0.26.0.

## GeoRemoteLBP

Encode eight-neighbor local binary texture patterns on a supplied quantized image.

Fixed P=8, R=1, default LBP code; border samples follow upstream zero extension. Codes have no ordered physical magnitude.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/constant-dn.tif",
  "input_unit": "DN"
}
```

Upstream: [skimage.feature.local_binary_pattern](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/feature/texture.py), scikit-image==0.26.0.

## GeoRemoteStructureTensor

Map image structure tensors and principal eigenvalues for directional fabric evidence.

Pixel-coordinate Sobel convention; not terrain derivatives, physical strain, azimuth, or a fault interpretation.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/ramp.tif",
  "input_unit": "DN",
  "sigma_pixels": 0
}
```

Upstream: [skimage.feature.structure_tensor](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/feature/corner.py), scikit-image==0.26.0.

## GeoRemoteGabor

Map real and imaginary responses to an oriented, band-limited Gabor texture filter.

Truncated three-sigma filter; orientation is in image axes, not map azimuth. Complete patch required.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/impulse.tif",
  "input_unit": "normalized_intensity",
  "frequency_cycles_per_pixel": 0.25,
  "orientation_degrees": 0,
  "sigma_pixels": 1
}
```

Upstream: [skimage.filters.gabor](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/filters/_gabor.py), scikit-image==0.26.0.

## GeoRemoteCanny

Detect thin image boundaries using Gaussian smoothing, nonmaximum suppression and hysteresis.

Input intensities must lie in [0,1]; upstream excludes the outer border and erodes support around quality gaps. An edge is not a mapped geological contact.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/step.tif",
  "input_unit": "normalized_intensity",
  "sigma_pixels": 0,
  "low_threshold": 0.1,
  "high_threshold": 0.2
}
```

Upstream: [skimage.feature.canny](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/feature/_canny.py), scikit-image==0.26.0.

## Constraints and error behavior

Finite values only. No spatial reprojection/resampling, imputed pixels or runtime networking. SensorBandResample alone changes spectral discretization under explicit full-coverage bandwidth constraints, not the spatial grid. Complete-patch kernels reject masked gaps; mask-aware/sample-wise kernels retain effective exclusions. ScientificToolError reports bounded native error codes. See the group's FILE_SCHEMAS.md and exact tool schema.

## Expected outputs and provenance

CSV measurements accompany every result. Mapped operations also produce a float64 GeoTIFF with CRS/affine and effective mask preserved plus a PNG preview. Noise covariance, GLCM, region measurements and estimated registration shifts are tables. The input NoData declaration is retained in JSON; output sentinel is retained when finite and noncolliding, otherwise explicitly replaced. Hashes come from the native collection contract.

## Source interface and delivery

Fixed module: geological_agent.geology.github_expansion_remote. source_interface.kind: github_expansion_remote. No arbitrary module, function, or code input is accepted. Central whitelist/worker integration belongs to the parent.

## Current availability

NOT TESTED / NOT DEPLOYED / NOT SUBMITTED for r2. Historical r1 CPU reports are preserved and are not r2 acceptance evidence. Source authored only. Contract, CPU, model-workflow and platform acceptance for r2: not_run. Receiving lab approval and adapter license: pending. Existing deployed 229-tool catalog is unchanged by this contribution.

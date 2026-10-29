---
id: github_remote_radiometry
name: "Image registration, sensor-band harmonization and restoration"
description: "Choose among six bounded offline operations for image registration, sensor-band harmonization and restoration."
when_to_use: "Use when supplied calibrated imagery requires image registration, sensor-band harmonization and restoration"
tools:
- GeoRemotePhaseRegistration
- GeoRemoteSSIMChange
- GeoRemoteSensorBandResample
- GeoRemoteTVDenoise
- GeoRemoteRichardsonLucy
- GeoRemoteRollingBall
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

# Image registration, sensor-band harmonization and restoration

## When to use

Use this workflow only with supplied image evidence and an explicit scientific question. Load the individual tool schema after selecting the needed operation.

## Required inputs

Each operation takes args as a dictionary or JSON object string plus a new or empty output_dir. Input paths are local task assets. The caller declares physical units and reference provenance. Raster values must already be calibrated; nonidentity stored scales/offsets are rejected.

## Workflow

1. Establish band order, units, image registration and valid support.
2. Select the operation below whose scientific assumptions match the question.
3. Inspect numeric results, preserved georeferencing and artifact hashes.
4. Retain limitations and uncertainty; use independent observations for geological interpretation.

## GeoRemotePhaseRegistration

Estimate translational alignment between two same-grid image patches using Fourier cross-correlation.

Returns the shift to apply to the moving image; no resampling. Fourier shift is periodic/ambiguous for repetitive patterns; no rotation, deformation, or sensor-model correction.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/registration-moving.tif",
  "input_unit": "normalized_intensity",
  "reference_path": "assets/github-expansion-remote/registration-reference.tif",
  "upsample_factor": 1
}
```

Upstream: [skimage.registration.phase_cross_correlation](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/registration/_phase_cross_correlation.py), scikit-image==0.26.0.

## GeoRemoteSSIMChange

Map structural-similarity change between aligned acquisitions using an explicit intensity range and window.

Complete co-registered patches required; full map has reflected borders while scalar SSIM excludes a window rim. Range/illumination affect interpretation.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/flat.tif",
  "input_unit": "normalized_intensity",
  "reference_path": "assets/github-expansion-remote/quarter.tif",
  "data_range": 1,
  "window_pixels": 7
}
```

Upstream: [skimage.metrics.structural_similarity](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/metrics/_structural_similarity.py), scikit-image==0.26.0.

## GeoRemoteSensorBandResample

Resample calibrated hyperspectral reflectance to explicit target sensor bands using Gaussian response-overlap integration.

Approximate Gaussian target response integrated only inside its FWHM; source values are constant across their FWHMs. Complete target coverage and nonoverlapping source intervals are required; no inferred widths, extrapolation or partial-coverage renormalization. All FWHM bounds must lie within 100..30000 nm. Reflectance profile [0,1] only. Preserves spatial CRS/affine and all-band/quality-mask exclusions; exports target-band tags and resampling-weights.csv. Not exact sensor RSR calibration, spectral super-resolution or mineral identification.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/spectral-resample.tif",
  "input_unit": "reflectance",
  "wavelength_nm": [
    1000,
    1100
  ],
  "source_fwhm_nm": [
    100,
    100
  ],
  "target_wavelength_nm": [
    1050
  ],
  "target_fwhm_nm": [
    200
  ],
  "bandpass_source": "SYNTHETIC adjoining source intervals and symmetric Gaussian target; not a measured sensor response"
}
```

Upstream: [spectral.algorithms.resampling.BandResampler](https://github.com/spectralpython/spectral/blob/bd91dc47377028683ef5c97bc7c1cc2dff14012c/spectral/algorithms/resampling.py), spectral==0.25.

## GeoRemoteTVDenoise

Denoise image radiometry with Chambolle total-variation regularization.

Can suppress fine geologic texture and create staircase effects; complete patch, explicit weight, bounded iterations. Reject binary/label codes and negative radiometry; reflectance/normalized_intensity profile is [0,1]. Output is continuous in the declared input unit, including fractional DN, not a classification.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/flat.tif",
  "input_unit": "normalized_intensity",
  "weight": 0.1,
  "iterations": 20
}
```

Upstream: [skimage.restoration.denoise_tv_chambolle](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/restoration/_denoise.py), scikit-image==0.26.0.

## GeoRemoteRichardsonLucy

Restore spatial blur by Richardson-Lucy iterations with an explicitly supplied normalized point-spread function.

Nonnegative intensity/PSF only; caller PSF is not estimated or normalized silently. Noise amplification and boundary effects remain possible.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/rl.tif",
  "input_unit": "normalized_intensity",
  "psf": [
    [
      0,
      0,
      0
    ],
    [
      0,
      1,
      0
    ],
    [
      0,
      0,
      0
    ]
  ],
  "psf_source": "SYNTHETIC identity PSF",
  "iterations": 4
}
```

Upstream: [skimage.restoration.richardson_lucy](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/restoration/deconvolution.py), scikit-image==0.26.0.

## GeoRemoteRollingBall

Estimate a smooth image background with a rolling-ball intensity surface and export background plus residual.

Assumes bright features above background. Ball height and spatial radius share a numerical scale, so intensity calibration materially affects behavior.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/background.tif",
  "input_unit": "DN",
  "radius_pixels": 3
}
```

Upstream: [skimage.restoration.rolling_ball](https://github.com/scikit-image/scikit-image/blob/ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8/src/skimage/restoration/_rolling_ball.py), scikit-image==0.26.0.

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
| `GeoRemotePhaseRegistration` | `geological_agent.geology.github_expansion_remote:phase_registration` |
| `GeoRemoteSSIMChange` | `geological_agent.geology.github_expansion_remote:structural_similarity_change` |
| `GeoRemoteSensorBandResample` | `geological_agent.geology.github_expansion_remote:sensor_band_resample` |
| `GeoRemoteTVDenoise` | `geological_agent.geology.github_expansion_remote:total_variation_denoise` |
| `GeoRemoteRichardsonLucy` | `geological_agent.geology.github_expansion_remote:richardson_lucy_deconvolution` |
| `GeoRemoteRollingBall` | `geological_agent.geology.github_expansion_remote:rolling_ball_background` |

Parameter constraints, units, result schema, artifact references and structured error semantics are defined by each tool in the registry. Pure numeric operations return their declared JSON result; operations with output files must preserve their artifact paths, sizes and hashes. Missing dependencies must remain explicit errors. Do not install packages or alter shared environments during execution.

### Current availability

tool_candidates_available_workflow_unverified

The native references resolve in the deployed OreSage registry. This documentation repair adds the missing handoff sections; it does not certify full Skill workflows, external data services or AI Lab acceptance. `workflow_validation=not_run` and `platform_validation=not_run` remain unchanged.

Earlier status statements in this source document are historical source-authoring records. Current deployment evidence is recorded in docs/releases/xiaoyu-skills-20261029.md; historical NOT DEPLOYED statements must not be read as the current runtime status. Upstream licenses, scientific limitations and prior failed records remain unchanged.

---
id: github_remote_spectral
name: "Spectral noise, dimensional reduction and detection"
description: "Choose among six bounded offline operations for spectral noise, dimensional reduction and detection."
when_to_use: "Use when supplied calibrated imagery requires spectral noise, dimensional reduction and detection"
tools:
- GeoRemotePCA
- GeoRemoteNoiseCovariance
- GeoRemoteMNF
- GeoRemoteRX
- GeoRemoteMatchedFilter
- GeoRemoteACE
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

# Spectral noise, dimensional reduction and detection

## When to use

Use this workflow only with supplied image evidence and an explicit scientific question. Load the individual tool schema after selecting the needed operation.

## Required inputs

Each operation takes args as a dictionary or JSON object string plus a new or empty output_dir. Input paths are local task assets. The caller declares physical units and reference provenance. Raster values must already be calibrated; nonidentity stored scales/offsets are rejected.

## Workflow

1. Establish band order, units, image registration and valid support.
2. Select the operation below whose scientific assumptions match the question.
3. Inspect numeric results, preserved georeferencing and artifact hashes.
4. Retain limitations and uncertainty; use independent observations for geological interpretation.

## GeoRemotePCA

Reduce calibrated multispectral imagery to principal components with eigenvalues and band loadings.

Axes maximize variance, not mineral separability; sign and repeated-eigenvalue bases are not unique.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/spectral-pca.tif",
  "input_unit": "DN",
  "wavelength_nm": [
    1000,
    1500
  ],
  "components": 1
}
```

Upstream: [spectral.algorithms.algorithms.principal_components](https://github.com/spectralpython/spectral/blob/bd91dc47377028683ef5c97bc7c1cc2dff14012c/spectral/algorithms/algorithms.py), spectral==0.25.

## GeoRemoteNoiseCovariance

Estimate spectral noise covariance from horizontal adjacent-pixel differences in a declared homogeneous patch.

Spatial texture can bias the estimate; independence and local stationarity are assumptions, not certified sensor noise.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/spectral-noise.tif",
  "input_unit": "DN",
  "wavelength_nm": [
    1000,
    1500
  ],
  "homogeneous_patch_source": "SYNTHETIC repeated differences; stationarity assumed for oracle"
}
```

Upstream: [spectral.algorithms.algorithms.noise_from_diffs](https://github.com/spectralpython/spectral/blob/bd91dc47377028683ef5c97bc7c1cc2dff14012c/spectral/algorithms/algorithms.py), spectral==0.25.

## GeoRemoteMNF

Reduce spectral dimensions after whitening by an explicitly supplied noise covariance.

Requires physically justified positive-definite noise covariance; retained scores are not abundances.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/spectral-pca.tif",
  "input_unit": "DN",
  "wavelength_nm": [
    1000,
    1500
  ],
  "components": 1,
  "noise_covariance": [
    [
      1,
      0
    ],
    [
      0,
      2
    ]
  ],
  "noise_source": "SYNTHETIC diagonal noise covariance"
}
```

Upstream: [spectral.algorithms.algorithms.mnf](https://github.com/spectralpython/spectral/blob/bd91dc47377028683ef5c97bc7c1cc2dff14012c/spectral/algorithms/algorithms.py), spectral==0.25.

## GeoRemoteRX

Detect multivariate spectral anomalies relative to supplied background statistics.

Background stationarity and band calibration must be justified; scores are neither probabilities of mineral presence nor ore grade. ACE at the exact background mean is rejected.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/spectral-targets.tif",
  "input_unit": "DN",
  "wavelength_nm": [
    1000,
    1500
  ],
  "background_mean": [
    0,
    0
  ],
  "background_covariance": [
    [
      4,
      0
    ],
    [
      0,
      1
    ]
  ],
  "background_source": "SYNTHETIC analytic diagonal covariance; not measured"
}
```

Upstream: [spectral.algorithms.detectors.rx](https://github.com/spectralpython/spectral/blob/bd91dc47377028683ef5c97bc7c1cc2dff14012c/spectral/algorithms/detectors.py), spectral==0.25.

## GeoRemoteMatchedFilter

Map covariance-weighted linear responses to a supplied spectral target.

Background stationarity and band calibration must be justified; scores are neither probabilities of mineral presence nor ore grade. ACE at the exact background mean is rejected.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/spectral-targets.tif",
  "input_unit": "DN",
  "wavelength_nm": [
    1000,
    1500
  ],
  "background_mean": [
    0,
    0
  ],
  "background_covariance": [
    [
      4,
      0
    ],
    [
      0,
      1
    ]
  ],
  "background_source": "SYNTHETIC analytic diagonal covariance; not measured",
  "target": [
    2,
    0
  ],
  "target_source": "SYNTHETIC target; not a mineral spectrum"
}
```

Upstream: [spectral.algorithms.detectors.matched_filter](https://github.com/spectralpython/spectral/blob/bd91dc47377028683ef5c97bc7c1cc2dff14012c/spectral/algorithms/detectors.py), spectral==0.25.

## GeoRemoteACE

Map adaptive coherence scores for a supplied target in background-whitened spectral space.

Background stationarity and band calibration must be justified; scores are neither probabilities of mineral presence nor ore grade. ACE at the exact background mean is rejected.

Synthetic example:

```json
{
  "raster_path": "assets/github-expansion-remote/spectral-targets.tif",
  "input_unit": "DN",
  "wavelength_nm": [
    1000,
    1500
  ],
  "background_mean": [
    0,
    0
  ],
  "background_covariance": [
    [
      4,
      0
    ],
    [
      0,
      1
    ]
  ],
  "background_source": "SYNTHETIC analytic diagonal covariance; not measured",
  "target": [
    2,
    0
  ],
  "target_source": "SYNTHETIC target; not a mineral spectrum"
}
```

Upstream: [spectral.algorithms.detectors.ace](https://github.com/spectralpython/spectral/blob/bd91dc47377028683ef5c97bc7c1cc2dff14012c/spectral/algorithms/detectors.py), spectral==0.25.

## Constraints and error behavior

Finite values only. No spatial reprojection/resampling, imputed pixels or runtime networking. SensorBandResample alone changes spectral discretization under explicit full-coverage bandwidth constraints, not the spatial grid. Complete-patch kernels reject masked gaps; mask-aware/sample-wise kernels retain effective exclusions. ScientificToolError reports bounded native error codes. See the group's FILE_SCHEMAS.md and exact tool schema.

## Expected outputs and provenance

CSV measurements accompany every result. Mapped operations also produce a float64 GeoTIFF with CRS/affine and effective mask preserved plus a PNG preview. Noise covariance, GLCM, region measurements and estimated registration shifts are tables. The input NoData declaration is retained in JSON; output sentinel is retained when finite and noncolliding, otherwise explicitly replaced. Hashes come from the native collection contract.

## Source interface and delivery

Fixed module: geological_agent.geology.github_expansion_remote. source_interface.kind: github_expansion_remote. No arbitrary module, function, or code input is accepted. Central whitelist/worker integration belongs to the parent.

## Current availability

NOT TESTED / NOT DEPLOYED / NOT SUBMITTED for r2. Historical r1 CPU reports are preserved and are not r2 acceptance evidence. Source authored only. Contract, CPU, model-workflow and platform acceptance for r2: not_run. Receiving lab approval and adapter license: pending. Existing deployed 229-tool catalog is unchanged by this contribution.

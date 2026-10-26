---
name: expansion501-remote-hyperspectral
description: "Source-only hyperspectral workflow for bounded remote sensing arrays; use only after parent integration and independent CPU acceptance."
id: expansion501_remote_hyperspectral
tools:
  - GeoRemoteGaussianClassify
  - GeoRemoteEndmemberDiscovery
  - GeoRemoteClassSeparability
  - GeoRemoteWaveletPyramid
---

# hyperspectral

## When to use

- `GeoRemoteGaussianClassify`: Supervised Gaussian spectral classification.
- `GeoRemoteEndmemberDiscovery`: SMACC data-derived endmember discovery.
- `GeoRemoteClassSeparability`: Gaussian training-class separability.
- `GeoRemoteWaveletPyramid`: Multiscale Haar directional image decomposition.

## Required inputs

Use the tool-specific closed schema. Synthetic examples illustrate the interface, not sensor observations. Numeric arrays must be finite with declared physical units. Raster arrays share one explicit EPSG CRS, affine transform, mask and finite-or-null nodata. Establish co-registration before packaging; no implicit filling or reprojection.

SAR/InSAR requires actual complex co-registered SLCs or processed unwrapped interferograms, as appropriate, with acquisition metadata and provenance. Sentinel-2 RGB or intensity alone cannot satisfy these requirements. Dates, wavelength, LOS sign and reference state are required where specified.

## Workflow

1. Confirm that the selected tool has been staged and independently accepted in its exact dependency profile. Source-written does not establish availability.
2. Select the scientific task and establish calibration, units, CRS, acquisition state and reference assumptions.
3. Extract a bounded already-aligned tile or a validated point/network table. Do not invent sensor metadata, fill missing observations or infer ore grade.
4. Call the named function with `args` and a new or empty `output_dir`. Shared contracts register hashes and artifacts.
5. Inspect output units, masks and scientific limitations. Hand off artifacts/provenance without labeling image evidence as confirmed mineral identity.

## Constraints

- Offline CPU only; no runtime downloads or dependency installs.
- No arbitrary shell, Python, executable, module or upstream-function parameters.
- Native OTB needs the separate fixed Linux prefix and reviewed identity manifest; accepted shared bridge profiles are untouched.
- MintPy requires parent invocation inside a private CPU profile. Full transitive/native ABI acceptance remains pending.
- Never suppress ScientificToolError or interpret partial files as success.
- All contribution entries conservatively use `pure=false`.

## Expected outputs and provenance

Strict summary JSON with units, statistics, artifacts and shared input/implementation/contract/output hashes. Raster outputs are GeoTIFF; tables are CSV. Hough/wavelet coefficient spaces are not falsely georeferenced. Independent model/workflow validation remains necessary.

## Source interface and delivery

Kind `expansion501_remote`; module `geological_agent.geology.expansion501_remote`; argument `args`; artifact directory `output_dir`. Parent owns catalog staging, shared allowlist and dispatch. Existing Skill discovery/loading is unchanged.

## Current availability and handoff

- Source: `source_revised_unverified`.
- Review: `acceptance_pending`; `formal_eligible=false`.
- Deployment: `not_deployed`.
- Submission: `not_submitted`.
- Scientific tests and model/workflow/platform validation: `not_run`.
- Receiving AI Lab certification: not established by internal schemas.

Synthetic examples and independent numeric-oracle specifications are under `assets/expansion501-remote/`. No executed acceptance results are supplied. Parent CPU acceptance is required before availability claims.

---
id: mineral_spectral_analysis
name: "Mineral spectral analysis / 矿物高光谱分析"
description: "Match measured spectra to a supplied mineral reference library by Spectral Python spectral angle; export angle table and heatmap. Remove the convex upper spectral continuum and report absorption depth, using Spectral Python; export spectral curves. Unmix measured spectra using supplied independent endmembers and Spectral Python unconstrained least squares; export coefficients and residuals. Map supplied spectral references onto a calibrated GeoTIFF with Spectral Python; preserve CRS, quality exclusions, class and angle GeoTIFFs, statistics and PNG/SVG previews."
when_to_use: "Mineral spectral analysis / 矿物高光谱分析 using declared measurements and supplied reference data"
tools:
- GeoSpectralAngleMatch
- GeoSpectralContinuumRemoval
- GeoSpectralLinearUnmix
- GeoSpectralAngleMap
required_inputs:
- Declared measured inputs with units and source
constraints:
- Select only the operation required for the question.
- Preserve units, wavelengths, quality masks, file provenance and uncertainty.
- Never infer mineral grade or reserves from a spectral match.
expected_outputs:
- Numeric evidence and downloadable PNG, SVG, CSV or GeoTIFF artifacts
---

# Mineral spectral analysis / 矿物高光谱分析

## GeoSpectralAngleMatch
Match measured spectra to a supplied mineral reference library by Spectral Python spectral angle; export angle table and heatmap.
Example (synthetic acceptance only): `{"data_path": "assets/github-minerals/spectra.json", "max_angle_degrees": 10}`

## GeoSpectralContinuumRemoval
Remove the convex upper spectral continuum and report absorption depth, using Spectral Python; export spectral curves.
Example (synthetic acceptance only): `{"data_path": "assets/github-minerals/continuum.json"}`

## GeoSpectralLinearUnmix
Unmix measured spectra using supplied independent endmembers and Spectral Python unconstrained least squares; export coefficients and residuals.
Example (synthetic acceptance only): `{"data_path": "assets/github-minerals/spectra.json"}`

## GeoSpectralAngleMap
Map supplied spectral references onto a calibrated GeoTIFF with Spectral Python; preserve CRS, quality exclusions, class and angle GeoTIFFs, statistics and PNG/SVG previews.
Example (synthetic acceptance only): `{"raster_path": "assets/github-minerals/synthetic-spectra.tif", "library_path": "assets/github-minerals/library.json", "quality_mask_path": "assets/github-minerals/synthetic-mask.tif", "raster_wavelength_nm": [1000, 1500, 2000], "reflectance_scale": 1, "reflectance_offset": 0, "max_angle_degrees": 10}`

## Source interface and delivery

Each named function in geological_agent.geology.github_minerals accepts args=dict or args=JSON-object-string. File-producing functions require a new or empty output_dir. Native execution authorizes workspace-relative input paths and returns ArtifactRef outputs. See catalog/source_delivery/github-minerals/FILE_SCHEMAS.md for the exact file fields, units, limits, error behavior and interpretation. Preserve output hashes and do not replace professional numerical kernels with generated code.

### Current availability

tool_candidates_available_workflow_unverified

Source registration is available; exact test execution is recorded in acceptance receipts. Model workflow validation: not_run. Platform validation: not_run. Deployment status: not_deployed. Submission status: not_submitted. Receiving lab approval: pending.

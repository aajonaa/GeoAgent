---
id: geochemical_composition_analysis
name: "Geochemical composition / 地球化学组成分析"
description: "Transform strictly positive same-unit geological compositions with pyrolite centered log ratios; preserve components and export a heatmap. Convert supported whole-rock oxide wt_percent to mol/100g and normalized oxide mol percent with pyrolite; no inferred iron redox split. Normalize rare-earth element ppm to an explicitly supplied reference composition using pyrolite; export log-scale REE patterns and Eu anomaly where Sm, Eu, Gd are present."
when_to_use: "Geochemical composition / 地球化学组成分析 using declared measurements and supplied reference data"
tools:
- GeoGeochemCLR
- GeoGeochemOxideMoles
- GeoGeochemREEPattern
required_inputs:
- Declared measured inputs with units and source
constraints:
- Select only the operation required for the question.
- Preserve units, wavelengths, quality masks, file provenance and uncertainty.
- Never infer mineral grade or reserves from a spectral match.
expected_outputs:
- Numeric evidence and downloadable PNG, SVG, CSV or GeoTIFF artifacts
---

# Geochemical composition / 地球化学组成分析

## GeoGeochemCLR
Transform strictly positive same-unit geological compositions with pyrolite centered log ratios; preserve components and export a heatmap.
Example (synthetic acceptance only): `{"data_path": "assets/github-minerals/clr.json"}`

## GeoGeochemOxideMoles
Convert supported whole-rock oxide wt_percent to mol/100g and normalized oxide mol percent with pyrolite; no inferred iron redox split.
Example (synthetic acceptance only): `{"data_path": "assets/github-minerals/oxides.json"}`

## GeoGeochemREEPattern
Normalize rare-earth element ppm to an explicitly supplied reference composition using pyrolite; export log-scale REE patterns and Eu anomaly where Sm, Eu, Gd are present.
Example (synthetic acceptance only): `{"data_path": "assets/github-minerals/ree.json"}`

## Source interface and delivery

Each named function in geological_agent.geology.github_minerals accepts args=dict or args=JSON-object-string. File-producing functions require a new or empty output_dir. Native execution authorizes workspace-relative input paths and returns ArtifactRef outputs. See catalog/source_delivery/github-minerals/FILE_SCHEMAS.md for the exact file fields, units, limits, error behavior and interpretation. Preserve output hashes and do not replace professional numerical kernels with generated code.

### Current availability

tool_candidates_available_workflow_unverified

Source registration is available; exact test execution is recorded in acceptance receipts. Model workflow validation: not_run. Platform validation: not_run. Deployment status: not_deployed. Submission status: not_submitted. Receiving lab approval: pending.

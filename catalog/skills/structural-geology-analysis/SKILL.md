---
id: structural_geology_analysis
name: "Structural geology / 构造地质分析"
description: "Plot lower-hemisphere equal-area structural planes and poles with mplstereonet; fit the dominant plane only when eigenvalues define a unique pole. Compute the line of intersection of two right-hand-rule geological planes using mplstereonet; reject parallel planes and return null bearing for vertical lines."
when_to_use: "Structural geology / 构造地质分析 using declared measurements and supplied reference data"
tools:
- GeoStereonetAnalysis
- GeoStructuralPlaneIntersection
required_inputs:
- Declared measured inputs with units and source
constraints:
- Select only the operation required for the question.
- Preserve units, wavelengths, quality masks, file provenance and uncertainty.
- Never infer mineral grade or reserves from a spectral match.
expected_outputs:
- Numeric evidence and downloadable PNG, SVG, CSV or GeoTIFF artifacts
---

# Structural geology / 构造地质分析

## GeoStereonetAnalysis
Plot lower-hemisphere equal-area structural planes and poles with mplstereonet; fit the dominant plane only when eigenvalues define a unique pole.
Example (synthetic acceptance only): `{"data_path": "assets/github-minerals/structures.json"}`

## GeoStructuralPlaneIntersection
Compute the line of intersection of two right-hand-rule geological planes using mplstereonet; reject parallel planes and return null bearing for vertical lines.
Example (synthetic acceptance only): `{"strike1_degrees": 0, "dip1_degrees": 90, "strike2_degrees": 90, "dip2_degrees": 90}`

## Source interface and delivery

Each named function in geological_agent.geology.github_minerals accepts args=dict or args=JSON-object-string. File-producing functions require a new or empty output_dir. Native execution authorizes workspace-relative input paths and returns ArtifactRef outputs. See catalog/source_delivery/github-minerals/FILE_SCHEMAS.md for the exact file fields, units, limits, error behavior and interpretation. Preserve output hashes and do not replace professional numerical kernels with generated code.

### Current availability

tool_candidates_available_workflow_unverified

Source registration is available; exact test execution is recorded in acceptance receipts. Model workflow validation: not_run. Platform validation: not_run. Deployment status: not_deployed. Submission status: not_submitted. Receiving lab approval: pending.

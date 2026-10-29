---
id: github_spatial_site_association
name: "Spatial association of site observations"
description: "Calculate per-site univariate local Moran association and descriptive PySAL quadrants. Measure local association between a focal site variable and a different variable at its neighbors. Compute self-excluding local Getis-Ord Gi concentration ratios for strictly positive site observations. Measure whole-region spatial dissimilarity using squared neighbor differences in global Geary C. Count like-class and unlike-class spatial joins in a binary site-presence map. Locate site-level neighbor dissimilarity using standardized local Geary squared differences."
when_to_use: "Spatial association of site observations for declared spatial data and a concrete scientific task"
tools:
- GeoSpatialLocalMoran
- GeoSpatialBivariateLocalMoran
- GeoSpatialLocalGetisOrd
- GeoSpatialGlobalGeary
- GeoSpatialBinaryJoinCounts
- GeoSpatialLocalGeary
required_inputs:
- Task-relative JSON matching the exact per-tool data schema
- Explicit source citation, CRS, units, grid mask or valid geometries
constraints:
- Select the scientific task first; never load or call every tool merely because it is present.
- No implicit CRS changes, nodata filling, geometry repair, rescaling or dependency installation.
- Synthetic fixtures are analytic examples, not field observations.
expected_outputs:
- Numeric or WKT evidence with explicit units and SHA-256 provenance
---

# Spatial association of site observations

## When to use

Calculate per-site univariate local Moran association and descriptive PySAL quadrants. Measure local association between a focal site variable and a different variable at its neighbors. Compute self-excluding local Getis-Ord Gi concentration ratios for strictly positive site observations. Measure whole-region spatial dissimilarity using squared neighbor differences in global Geary C. Count like-class and unlike-class spatial joins in a binary site-presence map. Locate site-level neighbor dissimilarity using standardized local Geary squared differences.

## Required inputs

Use the exact `metadata.scientific_contract.data_schema` in `catalog-additions.json`. Every object forbids extra fields. Coordinates use x/y or longitude/latitude ordering; grid indices use row/column. A grid origin is its top-left corner; cell size is square and in metres. Each false mask cell must be JSON null, and each true cell must be finite. Files are bounded to 256 KiB and grids to 4096 cells. Source declarations do not authenticate measurements.

## Workflow

1. Select one operation matching the requested scientific result.
2. Establish units, CRS, source citation and the operation-specific topology or mask policy.
3. Use its explicit named function with `args` as a dictionary or JSON-object string.
4. Preserve returned units, masks, geometry ordering, null semantics and provenance in downstream work.
5. Hand off unresolved input/domain failures; do not silently select another model or install a package.

## Tool contracts

### GeoSpatialLocalMoran

Calculate per-site univariate local Moran association and descriptive PySAL quadrants.

Scientific conditions: At most 256 distinct points; islands and constant observations rejected. No permutations, significance labels, inferred causation, kriging, or interpolation.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:local_moran`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/local_moran.json"}`.

Independent numeric oracle: Four square-corner observations [1,2,3,4] with edge-only neighbors yield local I [-0.45,0.15,0.15,-0.45].

Distinctness: SpatialMoranI produces one global univariate cross-product statistic using KNN weights; this uses explicit metric distance-band weights and returns a different statistic.

Upstream: `esda.moran.Moran_Local`; [official API/source](https://pysal.org/esda/stable/api.html).

### GeoSpatialBivariateLocalMoran

Measure local association between a focal site variable and a different variable at its neighbors.

Scientific conditions: At most 256 distinct points; islands and constant observations rejected. No permutations, significance labels, inferred causation, kriging, or interpolation.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:bivariate_local_moran`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/bivariate_local_moran.json"}`.

Independent numeric oracle: Oppositely ordered second variable [4,3,2,1] gives [0.45,-0.15,-0.15,0.45] by independent standardized cross-products.

Distinctness: SpatialMoranI produces one global univariate cross-product statistic using KNN weights; this uses explicit metric distance-band weights and returns a different statistic. The cross-variable association cannot be obtained by changing a coordinate component or univariate threshold.

Upstream: `esda.moran.Moran_Local_BV`; [official API/source](https://pysal.org/esda/stable/api.html).

### GeoSpatialLocalGetisOrd

Compute self-excluding local Getis-Ord Gi concentration ratios for strictly positive site observations.

Scientific conditions: At most 256 distinct points; islands and constant observations rejected. No permutations, significance labels, inferred causation, kriging, or interpolation. Fixed Gi (not Gi-star), binary weights; descriptive ratios only.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:local_getis_ord`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/local_getis_ord.json"}`.

Independent numeric oracle: Binary edge weights and values [1,2,3,4] give neighbor-sum / nonself-total ratios [6/9,4/8,6/7,4/6].

Distinctness: SpatialMoranI produces one global univariate cross-product statistic using KNN weights; this uses explicit metric distance-band weights and returns a different statistic.

Upstream: `esda.getisord.G_Local`; [official API/source](https://pysal.org/esda/stable/api.html).

### GeoSpatialGlobalGeary

Measure whole-region spatial dissimilarity using squared neighbor differences in global Geary C.

Scientific conditions: At most 256 distinct points; islands and constant observations rejected. No permutations, significance labels, inferred causation, kriging, or interpolation.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:global_geary`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/global_geary.json"}`.

Independent numeric oracle: Four-square rook graph has directed row-weighted squared-difference sum 12, centered sum squares 5 and C=(3/8)*(12/5)=0.9.

Distinctness: SpatialMoranI produces one global univariate cross-product statistic using KNN weights; this uses explicit metric distance-band weights and returns a different statistic.

Upstream: `esda.geary.Geary`; [official API/source](https://pysal.org/esda/stable/api.html).

### GeoSpatialBinaryJoinCounts

Count like-class and unlike-class spatial joins in a binary site-presence map.

Scientific conditions: At most 256 distinct points; islands and constant observations rejected. No permutations, significance labels, inferred causation, kriging, or interpolation. Both binary classes must occur.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:binary_join_counts`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/binary_join_counts.json"}`.

Independent numeric oracle: The square's four undirected edges contain one 1-1 join, one 0-0 join, and two mixed joins.

Distinctness: SpatialMoranI produces one global univariate cross-product statistic using KNN weights; this uses explicit metric distance-band weights and returns a different statistic.

Upstream: `esda.join_counts.Join_Counts`; [official API/source](https://pysal.org/esda/stable/api.html).

### GeoSpatialLocalGeary

Locate site-level neighbor dissimilarity using standardized local Geary squared differences.

Scientific conditions: At most 256 distinct points; islands and constant observations rejected. No permutations, significance labels, inferred causation, kriging, or interpolation.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:local_geary`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/local_geary.json"}`.

Independent numeric oracle: Population variance is 1.25; local mean squared neighbor differences / 1.25 equal [4,0.8,0.8,4].

Distinctness: SpatialMoranI produces one global univariate cross-product statistic using KNN weights; this uses explicit metric distance-band weights and returns a different statistic.

Upstream: `esda.geary_local.Geary_Local.fit`; [official API/source](https://pysal.org/esda/stable/api.html).

## Outputs and interpretation

Results are bounded JSON evidence with explicit `data`, `crs`, `source`, `units`, `artifacts` and `provenance` fields. These operations return numeric arrays and WKT directly; `artifacts` is empty. They do not certify mineral occurrence, resource estimates, site engineering safety, causation, or statistical significance. No output directory is required. Grid/path results include data.origin_xy, cell_size_m, shape and affine in Rasterio [a,b,c,d,e,f] order. The origin is an upper-left pixel corner; pixel centers add 0.5 to row/column. For reprojection, crs is the destination and source_crs is preserved separately.

## Errors

The shared `ScientificToolError` envelope contains `code`, `message`, and `retryable`. Schema, unit, CRS, topology and source failures are `invalid_arguments`; missing or incompatible pinned packages, resource limits, unreadable paths, empty data, unsupported connectivity and upstream failures have separate codes. Correct deterministic causes before retry. Do not conceal an error with substitute data.

## Sources and reproducibility

See the group `sources.json`, verbatim upstream notices in `licenses/`, and `requirements-spatial.txt`. The shared decorator records exact installed pins, canonical input-file content hashes, adapter/contract hashes, and the release commit. No runtime network or arbitrary user-selected callable is supported. Adapter license and receiving-lab approval remain pending.

## Handoff and availability

NOT TESTED / NOT DEPLOYED / NOT SUBMITTED.

availability_status: tool_candidates_available_workflow_unverified

workflow_validation: not_run; model_workflow_validation: not_run; platform_validation: not_run; deployment_status: not_deployed; submission_status: not_submitted; receiving_lab_approval: pending.

Parent must merge the additive catalog/examples, register the fixed module and worker kind, run the authored CPU tests against the pinned environment, and record fresh acceptance evidence. Existing skill_find/skill_load remains unchanged.

## Source interface and delivery

Use the registered native operation with its declared JSON input schema. The following bindings come from catalog/registry.json; use catalog/source_delivery/examples.json for exact accepted argument examples. Do not substitute guessed arguments, units or scientific algorithms.

| Native tool | Source callable |
| --- | --- |
| `GeoSpatialLocalMoran` | `geological_agent.geology.github_expansion_spatial:local_moran` |
| `GeoSpatialBivariateLocalMoran` | `geological_agent.geology.github_expansion_spatial:bivariate_local_moran` |
| `GeoSpatialLocalGetisOrd` | `geological_agent.geology.github_expansion_spatial:local_getis_ord` |
| `GeoSpatialGlobalGeary` | `geological_agent.geology.github_expansion_spatial:global_geary` |
| `GeoSpatialBinaryJoinCounts` | `geological_agent.geology.github_expansion_spatial:binary_join_counts` |
| `GeoSpatialLocalGeary` | `geological_agent.geology.github_expansion_spatial:local_geary` |

Parameter constraints, units, result schema, artifact references and structured error semantics are defined by each tool in the registry. Pure numeric operations return their declared JSON result; operations with output files must preserve their artifact paths, sizes and hashes. Missing dependencies must remain explicit errors. Do not install packages or alter shared environments during execution.

### Current availability

tool_candidates_available_workflow_unverified

The native references resolve in the deployed OreSage registry. This documentation repair adds the missing handoff sections; it does not certify full Skill workflows, external data services or AI Lab acceptance. `workflow_validation=not_run` and `platform_validation=not_run` remain unchanged.

Earlier status statements in this source document are historical source-authoring records. Current deployment evidence is recorded in docs/releases/xiaoyu-skills-20261029.md; historical NOT DEPLOYED statements must not be read as the current runtime status. Upstream licenses, scientific limitations and prior failed records remain unchanged.

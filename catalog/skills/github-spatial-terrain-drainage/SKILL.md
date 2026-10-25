---
id: github_spatial_terrain_drainage
name: "Terrain conditioning and drainage diagnostics"
description: "Condition a complete DEM with priority-flood depression filling and quantify fill depth and storage volume. Compute flow-connected height above a supplied drainage-channel mask using declared D8 directions and elevations. Calculate downstream topological D8 travel distance to a specified interior outlet. Calculate the longest upstream D8 path from each routed cell to an originating divide. Assign Strahler stream order to an explicitly selected, downstream-connected D8 channel network. Extract elevation isolines from a metric DEM using marching squares with explicit levels and nodata mask."
when_to_use: "Terrain conditioning and drainage diagnostics for declared spatial data and a concrete scientific task"
tools:
- GeoSpatialDepressionFill
- GeoSpatialHeightAboveDrainage
- GeoSpatialDistanceToOutlet
- GeoSpatialDistanceToRidge
- GeoSpatialStrahlerOrder
- GeoSpatialTerrainContours
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

# Terrain conditioning and drainage diagnostics

## When to use

Condition a complete DEM with priority-flood depression filling and quantify fill depth and storage volume. Compute flow-connected height above a supplied drainage-channel mask using declared D8 directions and elevations. Calculate downstream topological D8 travel distance to a specified interior outlet. Calculate the longest upstream D8 path from each routed cell to an originating divide. Assign Strahler stream order to an explicitly selected, downstream-connected D8 channel network. Extract elevation isolines from a metric DEM using marching squares with explicit levels and nodata mask.

## Required inputs

Use the exact `metadata.scientific_contract.data_schema` in `catalog-additions.json`. Every object forbids extra fields. Coordinates use x/y or longitude/latitude ordering; grid indices use row/column. A grid origin is its top-left corner; cell size is square and in metres. Each false mask cell must be JSON null, and each true cell must be finite. Files are bounded to 256 KiB and grids to 4096 cells. Source declarations do not authenticate measurements.

## Workflow

1. Select one operation matching the requested scientific result.
2. Establish units, CRS, source citation and the operation-specific topology or mask policy.
3. Use its explicit named function with `args` as a dictionary or JSON-object string.
4. Preserve returned units, masks, geometry ordering, null semantics and provenance in downstream work.
5. Hand off unresolved input/domain failures; do not silently select another model or install a package.

## Tool contracts

## Strahler r2 regression handoff

Use PyFlwDir 0.5.12 at commit 4e598e77611232bbf5fc620919d914de5bfd2cdb. Keep the original terminal order 2; never increase the oracle to match the Pysheds defect. Additional synthetic inputs are assets/github-expansion-spatial/strahler_order_multi_221.json and strahler_order_multi_112.json in the same directory. Expected confluence/terminal orders are 3 and 2. No artificial outlets, tributary-count restriction, or local Strahler recurrence is applied.

### GeoSpatialDepressionFill

Condition a complete DEM with priority-flood depression filling and quantify fill depth and storage volume.

Scientific conditions: Complete finite DEM only; no flat resolution, flow accumulation, slope calculation, or water-volume forecast. Output includes origin_xy, cell_size_m, Rasterio affine and shape; retain them with arrays or row/column paths.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:depression_fill`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/depression_fill.json"}`.

Independent numeric oracle: A 3x3 grid with rim elevation 5 m and center 1 m fills its center by 4 m; at 1-m cells the volume is 4 m3.

Distinctness: GeoPyshedsFlowAccumulation may condition terrain internally, but does not expose an independently usable filled DEM, per-cell fill depths, or depression-storage volume.

Upstream: `pysheds.grid.Grid.fill_depressions`; [official API/source](https://github.com/pysheds/pysheds/tree/0.5).

### GeoSpatialHeightAboveDrainage

Compute flow-connected height above a supplied drainage-channel mask using declared D8 directions and elevations.

Scientific conditions: Complete DEM, acyclic interior D8 graph, nonascending downstream elevation, explicit channels; HAND is not modeled flood depth. Output includes origin_xy, cell_size_m, Rasterio affine and shape; retain them with arrays or row/column paths.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:height_above_drainage`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/height_above_drainage.json"}`.

Independent numeric oracle: Interior east-flow chain elevations 5,4,2 m ending at a channel gives HAND 3,2,0 m; unrelated cells are null.

Distinctness: GeoPyshedsFlowAccumulation returns flow directions and contributing-cell counts; EarthLandlabFlowDirections selects receivers. Neither returns this drainage diagnostic from an explicitly supplied graph.

Upstream: `pysheds.grid.Grid.compute_hand`; [official API/source](https://github.com/pysheds/pysheds/tree/0.5).

### GeoSpatialDistanceToOutlet

Calculate downstream topological D8 travel distance to a specified interior outlet.

Scientific conditions: Steps are not metres or travel times; terminal direction is zero. Output includes origin_xy, cell_size_m, Rasterio affine and shape; retain them with arrays or row/column paths.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:distance_to_outlet`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/distance_to_outlet.json"}`.

Independent numeric oracle: Three-cell east-flow chain gives downstream distances 2,1,0 D8 steps; noncontributing cells remain null.

Distinctness: GeoPyshedsFlowAccumulation returns flow directions and contributing-cell counts; EarthLandlabFlowDirections selects receivers. Neither returns this drainage diagnostic from an explicitly supplied graph. Existing catchment delineation returns membership, not per-cell outlet path lengths.

Upstream: `pysheds.grid.Grid.distance_to_outlet`; [official API/source](https://github.com/pysheds/pysheds/tree/0.5).

### GeoSpatialDistanceToRidge

Calculate the longest upstream D8 path from each routed cell to an originating divide.

Scientific conditions: Longest upstream topological path, not the shortest distance to an outlet or Euclidean ridge proximity. Output includes origin_xy, cell_size_m, Rasterio affine and shape; retain them with arrays or row/column paths.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:distance_to_ridge`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/distance_to_ridge.json"}`.

Independent numeric oracle: Three-cell east-flow chain gives longest upstream path lengths 0,1,2 D8 steps; a branched oracle uses the longest parent.

Distinctness: GeoPyshedsFlowAccumulation returns flow directions and contributing-cell counts; EarthLandlabFlowDirections selects receivers. Neither returns this drainage diagnostic from an explicitly supplied graph.

Upstream: `pysheds.grid.Grid.distance_to_ridge`; [official API/source](https://github.com/pysheds/pysheds/tree/0.5).

### GeoSpatialStrahlerOrder

Assign Strahler stream order to an explicitly selected, downstream-connected D8 channel network.

Scientific conditions: PyFlwDir 0.5.12 original upstream algorithm, not Pysheds stream_order or a local correction. Zero-direction terminals and multi-tributary junctions are supported. Nonchannel cells are null; the selected network is supplied, not inferred by a flow-accumulation threshold. Output includes origin_xy, cell_size_m, Rasterio affine and shape; retain them with arrays or row/column paths.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:strahler_order`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/strahler_order.json"}`.

Independent numeric oracle: Original oracle retained: two first-order tributaries give order 2 at [2,2] and zero-direction terminal [3,2]. Supplemental independent confluences [2,2,1] give 3, while [1,1,2] give 2; the downstream terminals retain those orders.

Distinctness: GeoPyshedsFlowAccumulation returns flow directions and contributing-cell counts; EarthLandlabFlowDirections selects receivers. Neither returns this drainage diagnostic from an explicitly supplied graph.

Upstream: `pyflwdir.FlwdirRaster.stream_order`; [official API/source](https://github.com/Deltares/pyflwdir/blob/4e598e77611232bbf5fc620919d914de5bfd2cdb/pyflwdir/flwdir.py#L508).

### GeoSpatialTerrainContours

Extract elevation isolines from a metric DEM using marching squares with explicit levels and nodata mask.

Scientific conditions: Sample centers use half-cell offsets. Low-valued cells are fully connected in saddle ambiguities; no nodata interpolation.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:terrain_contours`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/terrain_contours.json"}`.

Independent numeric oracle: For columns 0,1,2 m at 1-m spacing, the 0.5-m contour lies at x=1 m and extends 2 m between outer sample centers.

Distinctness: HydroModelsPyDEMTerrainDerivatives returns slope/direction; EarthSimRasterCrossSection samples an existing line. This constructs elevation isolines and does not segment imagery.

Upstream: `skimage.measure.find_contours`; [official API/source](https://scikit-image.org/docs/0.26.x/api/).

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

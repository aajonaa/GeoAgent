---
id: github_spatial_raster_access
name: "Raster access, corridors and throughput"
description: "Find an explicit minimum-cost four-neighbor route across a masked site-access raster. Allocate reachable raster cells to supplied service sites by network cost, with deterministic first-site tie handling. Calculate exact raster-cell-center Euclidean distances to declared target cells at metric resolution. Compute effective resistance between access cells by the pseudoinverse of the graph conductance Laplacian. Map all cells within an explicit excess-cost budget of the optimum source-destination access route. Solve maximum haul-throughput flow on a four-neighbor raster with integer edge capacities derived from endpoint minima."
when_to_use: "Raster access, corridors and throughput for declared spatial data and a concrete scientific task"
tools:
- GeoSpatialLeastCostPath
- GeoSpatialCostAllocation
- GeoSpatialEuclideanProximity
- GeoSpatialResistanceDistance
- GeoSpatialCostCorridor
- GeoSpatialCapacityMaxFlow
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

# Raster access, corridors and throughput

## When to use

Find an explicit minimum-cost four-neighbor route across a masked site-access raster. Allocate reachable raster cells to supplied service sites by network cost, with deterministic first-site tie handling. Calculate exact raster-cell-center Euclidean distances to declared target cells at metric resolution. Compute effective resistance between access cells by the pseudoinverse of the graph conductance Laplacian. Map all cells within an explicit excess-cost budget of the optimum source-destination access route. Solve maximum haul-throughput flow on a four-neighbor raster with integer edge capacities derived from endpoint minima.

## Required inputs

Use the exact `metadata.scientific_contract.data_schema` in `catalog-additions.json`. Every object forbids extra fields. Coordinates use x/y or longitude/latitude ordering; grid indices use row/column. A grid origin is its top-left corner; cell size is square and in metres. Each false mask cell must be JSON null, and each true cell must be finite. Files are bounded to 256 KiB and grids to 4096 cells. Source declarations do not authenticate measurements.

## Workflow

1. Select one operation matching the requested scientific result.
2. Establish units, CRS, source citation and the operation-specific topology or mask policy.
3. Use its explicit named function with `args` as a dictionary or JSON-object string.
4. Preserve returned units, masks, geometry ordering, null semantics and provenance in downstream work.
5. Hand off unresolved input/domain failures; do not silently select another model or install a package.

## Tool contracts

### GeoSpatialLeastCostPath

Find an explicit minimum-cost four-neighbor route across a masked site-access raster.

Scientific conditions: Four-neighbor movement only. Edge cost is mean endpoint seconds/metre times cell side; invalid cells are impassable. Results describe a declared planning model, not observed travel times. Output includes origin_xy, cell_size_m, Rasterio affine and shape; retain them with arrays or row/column paths.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:least_cost_path`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/least_cost_path.json"}`.

Independent numeric oracle: A single row of three unit-cost cells has path [[0,0],[0,1],[0,2]] and total edge cost 2 seconds.

Distinctness: DeepTimeNearestNeighbor/CCSNearestNeighbor and EnergyNearestFacility measure point separation; they do not solve masked raster access networks.

Upstream: `skimage.graph.route_through_array`; [official API/source](https://scikit-image.org/docs/0.26.x/api/).

### GeoSpatialCostAllocation

Allocate reachable raster cells to supplied service sites by network cost, with deterministic first-site tie handling.

Scientific conditions: Four-neighbor movement only. Edge cost is mean endpoint seconds/metre times cell side; invalid cells are impassable. Results describe a declared planning model, not observed travel times. Output includes origin_xy, cell_size_m, Rasterio affine and shape; retain them with arrays or row/column paths.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:cost_allocation`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/cost_allocation.json"}`.

Independent numeric oracle: Sites at both ends of a three-cell row yield costs [0,1,0] and owner indices [0,0,1]; a separate oracle includes barriers.

Distinctness: DeepTimeNearestNeighbor/CCSNearestNeighbor and EnergyNearestFacility measure point separation; they do not solve masked raster access networks.

Upstream: `scipy.sparse.csgraph.dijkstra`; [official API/source](https://docs.scipy.org/doc/scipy-1.15.3/reference/).

### GeoSpatialEuclideanProximity

Calculate exact raster-cell-center Euclidean distances to declared target cells at metric resolution.

Scientific conditions: Mask excludes output cells but does not form a travel barrier for straight-line distance; not a point nearest-neighbor query. Output includes origin_xy, cell_size_m, Rasterio affine and shape; retain them with arrays or row/column paths.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:euclidean_proximity`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/euclidean_proximity.json"}`.

Independent numeric oracle: One target at the upper-left of a 2x2 unit grid produces [[0,1],[1,sqrt(2)]] metres.

Distinctness: DeepTimeNearestNeighbor/CCSNearestNeighbor and EnergyNearestFacility measure point separation; they do not solve masked raster access networks.

Upstream: `scipy.ndimage.distance_transform_edt`; [official API/source](https://docs.scipy.org/doc/scipy-1.15.3/reference/).

### GeoSpatialResistanceDistance

Compute effective resistance between access cells by the pseudoinverse of the graph conductance Laplacian.

Scientific conditions: Four-neighbor movement only. Edge cost is mean endpoint seconds/metre times cell side; invalid cells are impassable. Results describe a declared planning model, not observed travel times. Maximum 256 total cells. Reciprocal edge costs are conductances; output is a connectivity diagnostic, not shortest travel time or geophysical resistivity.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:resistance_distance`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/resistance_distance.json"}`.

Independent numeric oracle: Opposite corners of a unit-resistance 2x2 square have two 2-unit series routes in parallel: effective resistance 1.

Distinctness: DeepTimeNearestNeighbor/CCSNearestNeighbor and EnergyNearestFacility measure point separation; they do not solve masked raster access networks.

Upstream: `scipy.linalg.pinvh`; [official API/source](https://docs.scipy.org/doc/scipy-1.15.3/reference/).

### GeoSpatialCostCorridor

Map all cells within an explicit excess-cost budget of the optimum source-destination access route.

Scientific conditions: Four-neighbor movement only. Edge cost is mean endpoint seconds/metre times cell side; invalid cells are impassable. Results describe a declared planning model, not observed travel times. A corridor is the set of feasible detours, not a second parameterization of the single returned path. Output includes origin_xy, cell_size_m, Rasterio affine and shape; retain them with arrays or row/column paths.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:cost_corridor`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/cost_corridor.json"}`.

Independent numeric oracle: Across the top row of a 2x3 unit grid, optimum cost is 2; excess-cost rows are [0,0,0] and [2,2,2].

Distinctness: DeepTimeNearestNeighbor/CCSNearestNeighbor and EnergyNearestFacility measure point separation; they do not solve masked raster access networks.

Upstream: `scipy.sparse.csgraph.dijkstra`; [official API/source](https://docs.scipy.org/doc/scipy-1.15.3/reference/).

### GeoSpatialCapacityMaxFlow

Solve maximum haul-throughput flow on a four-neighbor raster with integer edge capacities derived from endpoint minima.

Scientific conditions: A planning-network edge-capacity model, not a hydraulic flow model. Node throughput is not separately constrained. Each valid integer capacity is <=1000000.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:capacity_max_flow`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/capacity_max_flow.json"}`.

Independent numeric oracle: A series corridor with endpoint capacities [5,3,4] has edge capacities [3,3], so the maximum throughput is 3 tonnes/day.

Distinctness: DeepTimeNearestNeighbor/CCSNearestNeighbor and EnergyNearestFacility measure point separation; they do not solve masked raster access networks.

Upstream: `scipy.sparse.csgraph.maximum_flow`; [official API/source](https://docs.scipy.org/doc/scipy-1.15.3/reference/).

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

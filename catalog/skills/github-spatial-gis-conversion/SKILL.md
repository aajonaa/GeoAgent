---
id: github_spatial_gis_conversion
name: "GIS conversion and site topology"
description: "Reproject a bounded metric raster onto an explicit WGS84-based target grid using nearest resampling and explicit NoData propagation. Burn ordered site polygons and explicit class IDs into a declared raster grid; later polygons win overlaps. Convert connected integer raster classes into georeferenced polygons while excluding explicitly invalid cells. Construct the exact intersection geometry of two projected site or exclusion-zone polygons. Dissolve a valid edge-matched polygon coverage into its combined site footprint. Triangulate site polygons while preserving parcel and hole boundaries for terrain-mesh preparation."
when_to_use: "GIS conversion and site topology for declared spatial data and a concrete scientific task"
tools:
- GeoSpatialRasterReproject
- GeoSpatialPolygonRasterize
- GeoSpatialRasterPolygonize
- GeoSpatialPolygonIntersection
- GeoSpatialCoverageUnion
- GeoSpatialConstrainedTriangulation
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

# GIS conversion and site topology

## When to use

Reproject a bounded metric raster onto an explicit WGS84-based target grid using nearest resampling and explicit NoData propagation. Burn ordered site polygons and explicit class IDs into a declared raster grid; later polygons win overlaps. Convert connected integer raster classes into georeferenced polygons while excluding explicitly invalid cells. Construct the exact intersection geometry of two projected site or exclusion-zone polygons. Dissolve a valid edge-matched polygon coverage into its combined site footprint. Triangulate site polygons while preserving parcel and hole boundaries for terrain-mesh preparation.

## Required inputs

Use the exact `metadata.scientific_contract.data_schema` in `catalog-additions.json`. Every object forbids extra fields. Coordinates use x/y or longitude/latitude ordering; grid indices use row/column. A grid origin is its top-left corner; cell size is square and in metres. Each false mask cell must be JSON null, and each true cell must be finite. Files are bounded to 256 KiB and grids to 4096 cells. Source declarations do not authenticate measurements.

## Workflow

1. Select one operation matching the requested scientific result.
2. Establish units, CRS, source citation and the operation-specific topology or mask policy.
3. Use its explicit named function with `args` as a dictionary or JSON-object string.
4. Preserve returned units, masks, geometry ordering, null semantics and provenance in downstream work.
5. Hand off unresolved input/domain failures; do not silently select another model or install a package.

## Tool contracts

## Reprojection r2 regression handoff

Top-level crs is the destination; source_crs is the original source CRS. Keep destination origin, cell size, affine and shape with the returned raster. assets/github-expansion-spatial/raster_reproject_cross_crs.json maps a one-cell UTM31N equatorial patch to Web Mercator; its value remains 17.

### GeoSpatialRasterReproject

Reproject a bounded metric raster onto an explicit WGS84-based target grid using nearest resampling and explicit NoData propagation.

Scientific conditions: Nearest resampling is explicit. Source and destination must be projected WGS84-based CRSs in metres; no datum-shift grids. Top-level crs describes the destination; source_crs retains the source CRS. The supplemental cross-CRS fixture uses the analytic equatorial UTM-to-Web-Mercator coordinate. Output includes origin_xy, cell_size_m, Rasterio affine and shape; retain them with arrays or row/column paths.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:raster_reproject`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/raster_reproject.json"}`.

Independent numeric oracle: An explicit one-cell east target-grid shift produces [[null,null],[4,null]] and exactly one valid cell.

Distinctness: GeoRasterioWindow only crops integer windows without resampling; GeoSalemProjectCoordinates transforms point coordinates, not a masked raster grid.

Upstream: `rasterio.warp.reproject`; [official API/source](https://rasterio.readthedocs.io/en/stable/topics/features.html).

### GeoSpatialPolygonRasterize

Burn ordered site polygons and explicit class IDs into a declared raster grid; later polygons win overlaps.

Scientific conditions: Explicit all_touched and last-input-polygon-wins rules; zero denotes unburned valid background. Output includes origin_xy, cell_size_m, Rasterio affine and shape; retain them with arrays or row/column paths.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:polygon_rasterize`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/polygon_rasterize.json"}`.

Independent numeric oracle: A 1x2-m rectangle occupies the left column of a 2x2 one-metre grid: [[7,0],[7,0]].

Distinctness: EarthGeoNotebookPolygonSubset masks an existing raster; this constructs a new classified raster from vector site polygons.

Upstream: `rasterio.features.rasterize`; [official API/source](https://rasterio.readthedocs.io/en/stable/topics/features.html).

### GeoSpatialRasterPolygonize

Convert connected integer raster classes into georeferenced polygons while excluding explicitly invalid cells.

Scientific conditions: Fixed four-cell connectivity; int32 classes only.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:raster_polygonize`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/raster_polygonize.json"}`.

Independent numeric oracle: Three one-square-metre cells of class 2 produce one polygon of area 3; the invalid fourth cell is excluded.

Distinctness: GeoMapColorExtract first detects colors and regions in a map; this polygonizes supplied scientific class IDs without segmentation or color detection.

Upstream: `rasterio.features.shapes`; [official API/source](https://rasterio.readthedocs.io/en/stable/topics/features.html).

### GeoSpatialPolygonIntersection

Construct the exact intersection geometry of two projected site or exclusion-zone polygons.

Scientific conditions: Valid projected metre geometries; no repair or reprojection.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:polygon_intersection`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/polygon_intersection.json"}`.

Independent numeric oracle: Overlapping 2x2-m squares offset by 1 m have an intersection area of 2 m2.

Distinctness: GeoShapelyGeometry measures an existing geometry; it does not construct this topology. GeoPandasSpatialJoin returns matching feature indices without creating new geometry.

Upstream: `shapely.intersection`; [official API/source](https://shapely.readthedocs.io/en/2.1.2/manual.html).

### GeoSpatialCoverageUnion

Dissolve a valid edge-matched polygon coverage into its combined site footprint.

Scientific conditions: GEOS >=3.12 is required for coverage validation. Gaps remain gaps; no snapping or repair.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:coverage_union`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/coverage_union.json"}`.

Independent numeric oracle: Two edge-matched 1x2-m rectangles dissolve to area 4 m2 and perimeter 8 m; overlapping coverages are rejected.

Distinctness: GeoShapelyGeometry measures an existing geometry; it does not construct this topology. GeoPandasSpatialJoin returns matching feature indices without creating new geometry.

Upstream: `shapely.coverage_union_all`; [official API/source](https://shapely.readthedocs.io/en/2.1.2/manual.html).

### GeoSpatialConstrainedTriangulation

Triangulate site polygons while preserving parcel and hole boundaries for terrain-mesh preparation.

Scientific conditions: No elevation interpolation. Input polygon topology remains authoritative; GEOS >=3.12 gate.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:constrained_triangulation`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/constrained_triangulation.json"}`.

Independent numeric oracle: A 2x2-m square has exactly two triangles of area 2 m2 each; their union is the original polygon.

Distinctness: GeoShapelyGeometry measures an existing geometry; it does not construct this topology. GeoPandasSpatialJoin returns matching feature indices without creating new geometry.

Upstream: `shapely.constrained_delaunay_triangles`; [official API/source](https://shapely.readthedocs.io/en/2.1.2/manual.html).

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

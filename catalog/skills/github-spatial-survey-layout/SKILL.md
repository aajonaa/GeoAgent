---
id: github_spatial_survey_layout
name: "Ellipsoidal survey and site layout"
description: "Measure oriented area and perimeter of a WGS84 geodesic polygon on the reference ellipsoid. Construct equal-distance survey stations along a shortest WGS84 ellipsoidal geodesic transect. Assess metric projection scale, area, angular distortion, and convergence at declared WGS84 survey locations. Find the pole of inaccessibility and largest contained circular footprint in a site polygon within an explicit tolerance. Partition a site region into clipped Voronoi service polygons in original site-point order. Split site parcels along a declared infrastructure alignment while retaining all resulting polygon pieces."
when_to_use: "Ellipsoidal survey and site layout for declared spatial data and a concrete scientific task"
tools:
- GeoSpatialEllipsoidalPolygonArea
- GeoSpatialGeodesicTransect
- GeoSpatialProjectionDistortion
- GeoSpatialMaximumInscribedCircle
- GeoSpatialSiteVoronoi
- GeoSpatialSiteParcelSplit
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

# Ellipsoidal survey and site layout

## When to use

Measure oriented area and perimeter of a WGS84 geodesic polygon on the reference ellipsoid. Construct equal-distance survey stations along a shortest WGS84 ellipsoidal geodesic transect. Assess metric projection scale, area, angular distortion, and convergence at declared WGS84 survey locations. Find the pole of inaccessibility and largest contained circular footprint in a site polygon within an explicit tolerance. Partition a site region into clipped Voronoi service polygons in original site-point order. Split site parcels along a declared infrastructure alignment while retaining all resulting polygon pieces.

## Required inputs

Use the exact `metadata.scientific_contract.data_schema` in `catalog-additions.json`. Every object forbids extra fields. Coordinates use x/y or longitude/latitude ordering; grid indices use row/column. A grid origin is its top-left corner; cell size is square and in metres. Each false mask cell must be JSON null, and each true cell must be finite. Files are bounded to 256 KiB and grids to 4096 cells. Source declarations do not authenticate measurements.

## Workflow

1. Select one operation matching the requested scientific result.
2. Establish units, CRS, source citation and the operation-specific topology or mask policy.
3. Use its explicit named function with `args` as a dictionary or JSON-object string.
4. Preserve returned units, masks, geometry ordering, null semantics and provenance in downstream work.
5. Hand off unresolved input/domain failures; do not silently select another model or install a package.

## Tool contracts

### GeoSpatialEllipsoidalPolygonArea

Measure oriented area and perimeter of a WGS84 geodesic polygon on the reference ellipsoid.

Scientific conditions: Single valid exterior without holes; longitude span <180 degrees; signed orientation is retained.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:ellipsoidal_polygon_area`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/ellipsoidal_polygon_area.json"}`.

Independent numeric oracle: The equator/meridian/pole triangle is one eighth of the oblate WGS84 spheroid surface; compare the closed-form spheroid-area expression.

Distinctness: GeoWGS84BBoxAreaKm2 estimates spherical bounding-box area; GeoShapelyGeometry uses planar geometry. This integrates ellipsoidal geodesic polygon edges.

Upstream: `pyproj.Geod.polygon_area_perimeter`; [official API/source](https://pyproj4.github.io/pyproj/stable/api/geod.html).

### GeoSpatialGeodesicTransect

Construct equal-distance survey stations along a shortest WGS84 ellipsoidal geodesic transect.

Scientific conditions: Reject coincident and antipodal endpoints; longitudes may wrap in returned WGS84 coordinates.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:geodesic_transect`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/geodesic_transect.json"}`.

Independent numeric oracle: On the equator from 0 to 4 degrees, stations are at longitudes 0,1,2,3,4; length is 6378137*pi*4/180 metres.

Distinctness: GeoHaversineDistance and GeoBearing return scalar spherical measurements; this produces actual equal-spacing ellipsoidal survey coordinates.

Upstream: `pyproj.Geod.npts`; [official API/source](https://pyproj4.github.io/pyproj/stable/api/geod.html).

### GeoSpatialProjectionDistortion

Assess metric projection scale, area, angular distortion, and convergence at declared WGS84 survey locations.

Scientific conditions: WGS84-based projected CRS only; factors are local and are not a correction of source observations.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:projection_distortion`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/projection_distortion.json"}`.

Independent numeric oracle: UTM zone 31 at its equatorial central meridian has linear scales 0.9996, area scale 0.9996^2, and zero convergence/angular distortion within numerical tolerance.

Distinctness: GeoCheckCRSConsistency compares identifier text and GeoSalemProjectCoordinates transforms coordinates; neither quantifies projection distortion.

Upstream: `pyproj.Proj.get_factors`; [official API/source](https://pyproj4.github.io/pyproj/stable/api/geod.html).

### GeoSpatialMaximumInscribedCircle

Find the pole of inaccessibility and largest contained circular footprint in a site polygon within an explicit tolerance.

Scientific conditions: GEOS >=3.12 gate; explicit geometric tolerance, not a claim of safe infrastructure siting.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:maximum_inscribed_circle`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/maximum_inscribed_circle.json"}`.

Independent numeric oracle: A 2x2-m square has a largest contained circle centered at [1,1] with radius 1 m.

Distinctness: GeoShapelyGeometry returns centroids and bounds; generic buffers expand a supplied center. This optimizes a feasible center and radius within the actual boundary.

Upstream: `shapely.maximum_inscribed_circle`; [official API/source](https://shapely.readthedocs.io/en/2.1.2/manual.html).

### GeoSpatialSiteVoronoi

Partition a site region into clipped Voronoi service polygons in original site-point order.

Scientific conditions: GEOS >=3.12 ordered Voronoi output required; distinct sites must lie within the region; no coordinate snapping.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:site_voronoi`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/site_voronoi.json"}`.

Independent numeric oracle: Two symmetric sites in a 2x2-m square split it at x=1 into two polygons of area 2 m2.

Distinctness: Generic nearest-neighbor entries return a point match; this constructs and clips the complete planar service-area partition.

Upstream: `shapely.voronoi_polygons`; [official API/source](https://shapely.readthedocs.io/en/2.1.2/manual.html).

### GeoSpatialSiteParcelSplit

Split site parcels along a declared infrastructure alignment while retaining all resulting polygon pieces.

Scientific conditions: A valid simple 2D LineString is required; no snapping. Nonintersecting alignments legitimately return the unchanged parcel.

Exact entrypoint: `geological_agent.geology.github_expansion_spatial:site_parcel_split`.

Synthetic example: `{"data_path": "assets/github-expansion-spatial/site_parcel_split.json"}`.

Independent numeric oracle: A vertical line x=1 splits a 2x2-m square into exactly two parcels of area 2 m2, conserving total area 4 m2.

Distinctness: GeoShapelyGeometry measures an existing geometry; it does not construct this topology. GeoPandasSpatialJoin returns matching feature indices without creating new geometry.

Upstream: `shapely.ops.split`; [official API/source](https://shapely.readthedocs.io/en/2.1.2/manual.html).

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

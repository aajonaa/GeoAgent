---
name: fractional-zonal-statistics
description: Raster statistics using polygon fractional-pixel coverage, with explicit masks, CRS and units.
---

# Fractional-Coverage Zonal Statistics

## When to use

Use when a task asks for raster summaries within mineral districts, study
areas or other polygon zones and boundary coverage matters. This method is
distinct from the existing pixel-centre tools; do not claim they are identical.

## Inputs

Require a local real-valued GeoTIFF, a UTF-8 GeoJSON-like FeatureCollection
containing valid closed 2-D Polygon/MultiPolygon geometry, a unique zone_id
property (or explicit zone_field), and the raster value unit. Both inputs must
already share a projected CRS in metres. zones_crs explicitly declares the
polygon coordinate system and must not contradict file metadata.

Projected-coordinate JSON here is an explicitly declared geometry interchange
profile, not a claim that projected coordinates satisfy RFC 7946.
Do not infer a CRS from coordinate magnitudes, invent boundaries, relabel
coordinates, or silently repair invalid geometry.

## Tool

Load this skill to expose GeoExactZonalStatistics. Supply raster_path,
zones_path, zones_crs and value_unit, optionally zone_field and one-based band.
Agent paths are workspace-relative. Trusted standalone Python calls use the
same exact_zonal_statistics(args) function under
legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools.

The operation reads the supplied band and applies its scale/offset, excluding
NoData and masks. It returns all inexpensive summary statistics in one call;
do not issue a separate identical call for each statistic.

## Interpretation

- mean is weighted by the fraction of each valid pixel covered by the polygon.
- coverage_count is the sum of fractions, not an integer count.
- valid_area_m2 is planar valid coverage area in the supplied projection.
- coverage_weighted_sum is sum(value * fraction), not automatically mass,
  volume, reserve tonnage or a physical area integral.
- minimum and maximum refer to valid overlapping cells.
- A zone with no valid cells has status no_valid_cells and null statistics.
- Zones may overlap; their sums and areas are not necessarily additive.

State the CRS, units, masking and coverage method with the answer. Do not
present projected area as geodesic area. Do not interpret missing coverage as
zero concentration. Respect the distinction between intensive and extensive
raster quantities before interpreting a sum.

## Composition

For sampling-to-zone tasks, discover spatial_kriging_interpolation first.
Use the observed prediction_path returned by GeoOrdinaryKrigingGrid as this
tool's raster_path. The output variance raster is a different quantity;
averaging its cells is not the variance of an area-average prediction.

Reuse existing usable rasters; interpolation is optional, not a fixed first
step. If CSV or maps are requested, create them from the returned zone rows
using the normal workspace tools without rerunning successful statistics.

## Acceptance and errors

Verify zone identity/count, no-valid-cell states, physical units and the
requested deliverables. Correct CRS/band/geometry errors from actual feedback.
Local synthetic tests do not certify the user's data or scientific conclusions.

## Source

exactextract 0.3.0, Apache-2.0:
https://github.com/isciences/exactextract
Rasterio supplies raster access; Shapely validates geometry.
Dependency definitions: requirements-source-tools.txt.
Formal asset packaging is deferred; the runtime loads this same skill.

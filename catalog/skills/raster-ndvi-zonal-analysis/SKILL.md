---
name: "raster-ndvi-zonal-analysis"
description: "Derive NDVI from compatible NIR/red bands, optionally apply supported QA and summarize explicit analysis zones."
---

# NDVI and Polygon-Zone Summary

## Procedure

1. Identify the actual research question and use only the relevant operations below.
2. Inspect supplied data and provenance. Confirm release, observation date, columns, units, CRS, masks and scientific coverage where applicable. Missing data must be requested or retrieved from an authorized source, never invented.
3. Call the disclosed native functions with named object arguments. The current input and output schemas are authoritative; do not pass question IDs, prose or assume server-private file paths.
4. Use observed values and generated artifacts. State method limitations and uncovered areas; label synthetic inputs as tests.

## RemoteSensingCloudMask

Apply Landsat 8/9 Collection 2 QA_PIXEL mask, rejecting fill, dilated cloud, cirrus, cloud, shadow and snow bits 0..5.

- Not Sentinel-2 SCL or Landsat 4-7 QA. Does not inspect QA_RADSAT; saturation/aerosol screening must be handled separately.

## RemoteSensingNDVI

NDVI: (first named band - second named band)/(first + second); undefined pixels excluded.

- Single-band, georeferenced GeoTIFF profile; aligned grids, finite valid pixels; no automatic reprojection.
- Caller must supply scientifically appropriate bands and units. Passing tests is not scientific certification.

## DeepTimeZonalStatistics

Aggregate a CSV by zone, or a GeoTIFF by WGS84 polygons using pixel centers; no area weighting.

- Portable WGS84 profile only. No inferred reprojection, no implicit private dataset.
- Buffer is approximate; overlay is point-in-polygon, not arbitrary polygon intersection.

## CCSZonalStatistics

Aggregate a CSV by zone, or a GeoTIFF by WGS84 polygons using pixel centers; no area weighting.

- Portable WGS84 profile only. No inferred reprojection, no implicit private dataset.
- Buffer is approximate; overlay is point-in-polygon, not arbitrary polygon intersection.

## Source interface and delivery

The canonical catalog contains native entrypoints, named input/output schemas, units, constraints, error behavior and synthetic call examples. Input files remain unchanged. Runtime paths must be relative to the current task; direct Python callers provide their explicit output directory.
Data-dependent queries require a supplied versioned snapshot. No data license, global model coverage or scientific certification is implied. Independent source-call validation and whole-Skill end-to-end validation are separate.

### Current availability

tool_candidates_available_workflow_unverified

All referenced tool implementations have native contracts. Runtime registration and acceptance are checked by the merge release tests; the complete Skill workflow has not been certified. Official lab registration metadata and platform validation remain pending.

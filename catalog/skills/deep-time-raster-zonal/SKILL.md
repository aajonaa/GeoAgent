---
name: "deep-time-raster-zonal"
description: "Interpolate explicit measurements, perform aligned raster arithmetic and summarize selected zones for deep-time studies."
---

# Deep-Time Raster and Zonal Analysis

## Procedure

1. Identify the actual research question and use only the relevant operations below.
2. Inspect supplied data and provenance. Confirm release, observation date, columns, units, CRS, masks and scientific coverage where applicable. Missing data must be requested or retrieved from an authorized source, never invented.
3. Call the disclosed native functions with named object arguments. The current input and output schemas are authoritative; do not pass question IDs, prose or assume server-private file paths.
4. Use observed values and generated artifacts. State method limitations and uncovered areas; label synthetic inputs as tests.

## DeepTimeInterpolateIDW

Interpolate an explicit measured field using spherical-distance IDW into a georeferenced GeoTIFF.

- Not a resource/reserve estimate. Requires observations with compatible units, dates and measurement definitions. Duplicate coordinates are averaged.

Required dataset fields: latitude, longitude, <value_field>.

## DeepTimeRasterAlgebra

Compute explicit pixelwise arithmetic on physical raster values. Supports two aligned rasters or one scalar.

- No arbitrary Python expressions. Division by zero becomes NoData; all-invalid outputs fail. Caller must supply scientifically compatible units.

## DeepTimeZonalStatistics

Aggregate a CSV by zone, or a GeoTIFF by WGS84 polygons using pixel centers; no area weighting.

- Portable WGS84 profile only. No inferred reprojection, no implicit private dataset.
- Buffer is approximate; overlay is point-in-polygon, not arbitrary polygon intersection.

## DeepTimeRenderMap

Render caller-supplied WGS84 vector layers or one georeferenced raster as a static PNG and HTML.

- Portable WGS84 profile only. No inferred reprojection, no implicit private dataset.
- Buffer is approximate; overlay is point-in-polygon, not arbitrary polygon intersection.

## Source interface and delivery

The canonical catalog contains native entrypoints, named input/output schemas, units, constraints, error behavior and synthetic call examples. Input files remain unchanged. Runtime paths must be relative to the current task; direct Python callers provide their explicit output directory.
Data-dependent queries require a supplied versioned snapshot. No data license, global model coverage or scientific certification is implied. Independent source-call validation and whole-Skill end-to-end validation are separate.

### Current availability

tool_candidates_available_workflow_unverified

All referenced tool implementations have native contracts. Runtime registration and acceptance are checked by the merge release tests; the complete Skill workflow has not been certified. Official lab registration metadata and platform validation remain pending.

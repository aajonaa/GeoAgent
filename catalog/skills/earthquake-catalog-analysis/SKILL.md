---
name: "earthquake-catalog-analysis"
description: "Fetch official USGS events when requested, or clean, query and plot an explicitly supplied earthquake catalog."
---

# Earthquake Catalog Analysis

## Procedure

1. Identify the actual research question and use only the relevant operations below.
2. Inspect supplied data and provenance. Confirm release, observation date, columns, units, CRS, masks and scientific coverage where applicable. Missing data must be requested or retrieved from an authorized source, never invented.
3. Call the disclosed native functions with named object arguments. The current input and output schemas are authoritative; do not pass question IDs, prose or assume server-private file paths.
4. Use observed values and generated artifacts. State method limitations and uncovered areas; label synthetic inputs as tests.

## geo_tool_00aa9bcef908cc86fc7b

Clean a USGS-style CSV, deduplicate events, and assign magnitude classes.

- Required columns: time, latitude, longitude, depth, mag. Depth [-10,1000] km and magnitude [-2,10] are the legacy cleaning policy.
- This cleans supplied records, not a live earthquake-catalog acquisition.

## DeepEarthQueryUSGSCatalog

DeepEarthQueryUSGSCatalog on an explicitly supplied versioned dataset. id, time, mag, depth, latitude, longitude columns required.

- Energy uses approximate log10(E/J)=1.5M+4.8. Reported magnitude types may not all be Mw. Frozen input catalog scope only.

Required dataset fields: id, time, mag, depth, latitude, longitude.

## USGSEarthquakeCatalogFetch

Fetch earthquake records from the fixed official USGS FDSN endpoint and save a CSV; report retrieval time and possible result truncation.

- Requires external USGS availability. limit may make results incomplete; possibly_limited=true must be disclosed.

## GeoEarthquakeEventMap

Render supplied earthquake observations as a static PNG and self-contained HTML image; no external tiles, scripts or CDN.

- Coordinate scatter, not a projected basemap. Mixed magnitude scales must not be treated as a homogeneous intensity measurement.

Required dataset fields: latitude, longitude, mag.

## Source interface and delivery

The canonical catalog contains native entrypoints, named input/output schemas, units, constraints, error behavior and synthetic call examples. Input files remain unchanged. Runtime paths must be relative to the current task; direct Python callers provide their explicit output directory.
Data-dependent queries require a supplied versioned snapshot. No data license, global model coverage or scientific certification is implied. Independent source-call validation and whole-Skill end-to-end validation are separate.

### Current availability

tool_candidates_available_workflow_unverified

All referenced tool implementations have native contracts. Runtime registration and acceptance are checked by the merge release tests; the complete Skill workflow has not been certified. Official lab registration metadata and platform validation remain pending.

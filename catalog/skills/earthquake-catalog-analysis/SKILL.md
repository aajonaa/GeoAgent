---
name: "Earthquake catalogs and seismic trace calculations"
description: "Fetch, clean, query and plot USGS or supplied earthquake catalogs; summarize SEG-Y seismic traces with segyio; compute acoustic impedance reflection coefficients (reflectivity) with Bruges. \u5730\u9707\u76ee\u5f55\u3001\u5730\u9707\u9053\u6458\u8981\u3001\u53cd\u5c04\u7cfb\u6570\u3002"
when_to_use: "Use supplied event catalogs for event analysis, a local SEG-Y file for read-only trace summaries, or positive velocity and density arrays for acoustic reflectivity. SEG-Y and reflectivity calculations do not require an earthquake event catalog."
required_inputs: [Requested event or seismic trace operation, Actual catalog OR SEG-Y file OR velocity and density arrays with consistent units]
---
# Earthquake Catalog Analysis

## Procedure

Choose event analysis, a seismic file summary or an acoustic calculation.
Catalog columns and USGS retrieval prerequisites apply only to event tools.
The trace and reflectivity operations use their own file or array inputs and
do not infer event magnitudes or geology from a waveform summary.

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

## SeismicReflectivity

Compute adjacent-sample acoustic reflection coefficients from positive `vp` and
density arrays with Bruges. This is a zero-offset acoustic calculation; it is
not a full angle-dependent Zoeppritz gather.

## SeismicSegySummary

Read a task-relative SEG-Y file and return a bounded trace/sample summary with a
small trace-mean preview. The adapter is read-only, rejects path traversal and
does not repair, resample or reinterpret SEG-Y geometry.

## Source interface and delivery

The canonical catalog contains native entrypoints, named input/output schemas, units, constraints, error behavior and synthetic call examples. Input files remain unchanged. Runtime paths must be relative to the current task; direct Python callers provide their explicit output directory.
Data-dependent queries require a supplied versioned snapshot. No data license, global model coverage or scientific certification is implied. Independent source-call validation and whole-Skill end-to-end validation are separate.

### Current availability

tool_candidates_available_workflow_unverified

All referenced tool implementations have native contracts. Runtime registration and acceptance are checked by the merge release tests; the complete Skill workflow has not been certified. Official lab registration metadata and platform validation remain pending.

## Preserved source-specific scientific constraints

The following original guidance applies to the original operations only, not to unrelated array-based calculations.

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

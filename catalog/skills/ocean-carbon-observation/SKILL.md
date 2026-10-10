---
name: "ocean-carbon-observation"
description: "Query supplied monthly grids and profiles or summarize observations; distinguish sample means from ocean-wide estimates."
---

# Ocean Carbon Observation

## Procedure

1. Identify the actual research question and use only the relevant operations below.
2. Inspect supplied data and provenance. Confirm release, observation date, columns, units, CRS, masks and scientific coverage where applicable. Missing data must be requested or retrieved from an authorized source, never invented.
3. Call the disclosed native functions with named object arguments. The current input and output schemas are authoritative; do not pass question IDs, prose or assume server-private file paths.
4. Use observed values and generated artifacts. State method limitations and uncovered areas; label synthetic inputs as tests.

## OceanMonthlyGridValue

OceanMonthlyGridValue on an explicitly supplied versioned dataset. month, latitude, longitude, <value_field> columns required.


Required dataset fields: month, latitude, longitude, <value_field>.

## OceanProfileValue

OceanProfileValue on an explicitly supplied versioned dataset. expocode, station, depth_m, <value_field> columns required.


Required dataset fields: expocode, station, depth_m, <value_field>.

## OceanAnnualCarbonSummary

OceanAnnualCarbonSummary on an explicitly supplied versioned dataset. time, latitude, longitude, <value_field> columns required.


Required dataset fields: time, latitude, longitude, <value_field>.

## Source interface and delivery

The canonical catalog contains native entrypoints, named input/output schemas, units, constraints, error behavior and synthetic call examples. Input files remain unchanged. Runtime paths must be relative to the current task; direct Python callers provide their explicit output directory.
Data-dependent queries require a supplied versioned snapshot. No data license, global model coverage or scientific certification is implied. Independent source-call validation and whole-Skill end-to-end validation are separate.

### Current availability

tool_candidates_available_workflow_unverified

All referenced tool implementations have native contracts. Runtime registration and acceptance are checked by the merge release tests; the complete Skill workflow has not been certified. Official lab registration metadata and platform validation remain pending.

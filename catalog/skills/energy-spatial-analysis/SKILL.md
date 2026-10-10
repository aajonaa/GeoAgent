---
name: "energy-spatial-analysis"
description: "Measure facility/site separation, find nearest records and summarize explicit regions in supplied energy and mineral tables."
---

# Energy and Mineral Spatial Analysis

## Procedure

1. Identify the actual research question and use only the relevant operations below.
2. Inspect supplied data and provenance. Confirm release, observation date, columns, units, CRS, masks and scientific coverage where applicable. Missing data must be requested or retrieved from an authorized source, never invented.
3. Call the disclosed native functions with named object arguments. The current input and output schemas are authoritative; do not pass question IDs, prose or assume server-private file paths.
4. Use observed values and generated artifacts. State method limitations and uncovered areas; label synthetic inputs as tests.

## EnergyFacilityDistance

EnergyFacilityDistance on an explicitly supplied versioned dataset. id, latitude, longitude columns required.


Required dataset fields: id, latitude, longitude.

## EnergyMineralSiteDistance

EnergyMineralSiteDistance on an explicitly supplied versioned dataset. id, latitude, longitude columns required.


Required dataset fields: id, latitude, longitude.

## EnergyBBoxArea

Spherical WGS84 bounding-box area, square kilometers; explicit coordinates only.


## EnergyNearestFacility

EnergyNearestFacility on an explicitly supplied versioned dataset. id, latitude, longitude columns required.


Required dataset fields: id, latitude, longitude.

## EnergyNearestMineralSite

EnergyNearestMineralSite on an explicitly supplied versioned dataset. id, latitude, longitude columns required.


Required dataset fields: id, latitude, longitude.

## EnergyRegionalOverlaySummary

EnergyRegionalOverlaySummary on an explicitly supplied versioned dataset. id, country, energy_source, capacity_mw, latitude, longitude columns required.


Required dataset fields: id, country, energy_source, capacity_mw, latitude, longitude.

## Source interface and delivery

The canonical catalog contains native entrypoints, named input/output schemas, units, constraints, error behavior and synthetic call examples. Input files remain unchanged. Runtime paths must be relative to the current task; direct Python callers provide their explicit output directory.
Data-dependent queries require a supplied versioned snapshot. No data license, global model coverage or scientific certification is implied. Independent source-call validation and whole-Skill end-to-end validation are separate.

### Current availability

tool_candidates_available_workflow_unverified

All referenced tool implementations have native contracts. Runtime registration and acceptance are checked by the merge release tests; the complete Skill workflow has not been certified. Official lab registration metadata and platform validation remain pending.

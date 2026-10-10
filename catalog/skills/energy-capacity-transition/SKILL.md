---
name: "energy-capacity-transition"
description: "Compute capacity, growth and renewable indicators from supplied tables with explicit units and classification."
---

# Energy Capacity and Transition Analysis

## Procedure

1. Identify the actual research question and use only the relevant operations below.
2. Inspect supplied data and provenance. Confirm release, observation date, columns, units, CRS, masks and scientific coverage where applicable. Missing data must be requested or retrieved from an authorized source, never invented.
3. Call the disclosed native functions with named object arguments. The current input and output schemas are authoritative; do not pass question IDs, prose or assume server-private file paths.
4. Use observed values and generated artifacts. State method limitations and uncovered areas; label synthetic inputs as tests.

## EnergyCapacityValue

EnergyCapacityValue on an explicitly supplied versioned dataset. series, year, capacity_mw columns required.


Required dataset fields: series, year, capacity_mw.

## EnergyCapacityGrowth

EnergyCapacityGrowth on an explicitly supplied versioned dataset. series, year, capacity_mw columns required.


Required dataset fields: series, year, capacity_mw.

## EnergyCountryRenewableSummary

EnergyCountryRenewableSummary on an explicitly supplied versioned dataset. id, country, energy_source, capacity_mw, latitude, longitude columns required.


Required dataset fields: id, country, energy_source, capacity_mw, latitude, longitude.

## EnergyTransitionMetrics

EnergyTransitionMetrics on an explicitly supplied versioned dataset. country, year, renewable_capacity_mw, total_capacity_mw, population columns required.


Required dataset fields: country, year, renewable_capacity_mw, total_capacity_mw, population.

## Source interface and delivery

The canonical catalog contains native entrypoints, named input/output schemas, units, constraints, error behavior and synthetic call examples. Input files remain unchanged. Runtime paths must be relative to the current task; direct Python callers provide their explicit output directory.
Data-dependent queries require a supplied versioned snapshot. No data license, global model coverage or scientific certification is implied. Independent source-call validation and whole-Skill end-to-end validation are separate.

### Current availability

tool_candidates_available_workflow_unverified

All referenced tool implementations have native contracts. Runtime registration and acceptance are checked by the merge release tests; the complete Skill workflow has not been certified. Official lab registration metadata and platform validation remain pending.

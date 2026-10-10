---
name: "deep-earth-model-query"
description: "Look up LITHO boundary depths or SEMUCB velocity samples in explicit versioned node tables; no full-model execution."
---

# Deep-Earth Model Query

## Procedure

1. Identify the actual research question and use only the relevant operations below.
2. Inspect supplied data and provenance. Confirm release, observation date, columns, units, CRS, masks and scientific coverage where applicable. Missing data must be requested or retrieved from an authorized source, never invented.
3. Call the disclosed native functions with named object arguments. The current input and output schemas are authoritative; do not pass question IDs, prose or assume server-private file paths.
4. Use observed values and generated artifacts. State method limitations and uncovered areas; label synthetic inputs as tests.

## DeepEarthQueryLITHO1

DeepEarthQueryLITHO1 on an explicitly supplied versioned dataset. node_index, latitude, longitude, moho_depth_km (CRUST3-BOTTOM) or lab_depth_km (LAB) columns required.

- Nearest node among supplied nodes only. Requires complete relevant model coverage for a global nearest-node claim. No model download or interpolation.

Required dataset fields: node_index, latitude, longitude, moho_depth_km (CRUST3-BOTTOM) or lab_depth_km (LAB).

## DeepEarthQuerySEMUCB

DeepEarthQuerySEMUCB on an explicitly supplied versioned dataset. latitude, longitude, depth_km, dlnvs_percent columns required.

- Queries supplied precomputed samples only; does not evaluate the original SEMUCB spline model.

Required dataset fields: latitude, longitude, depth_km, dlnvs_percent.

## Source interface and delivery

The canonical catalog contains native entrypoints, named input/output schemas, units, constraints, error behavior and synthetic call examples. Input files remain unchanged. Runtime paths must be relative to the current task; direct Python callers provide their explicit output directory.
Data-dependent queries require a supplied versioned snapshot. No data license, global model coverage or scientific certification is implied. Independent source-call validation and whole-Skill end-to-end validation are separate.

### Current availability

tool_candidates_available_workflow_unverified

All referenced tool implementations have native contracts. Runtime registration and acceptance are checked by the merge release tests; the complete Skill workflow has not been certified. Official lab registration metadata and platform validation remain pending.

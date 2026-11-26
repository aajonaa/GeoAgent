---
name: "Climate scenarios and meteorological calculations"
description: "Query supplied paleoclimate, annual anomaly or SSP scenario tables; convert wind speed and direction to u/v components with MetPy; compute daily FAO-56 Penman-Monteith reference evapotranspiration (ET0). \u6c14\u5019\u60c5\u666f\u3001\u98ce\u5206\u91cf\u3001\u53c2\u8003\u84b8\u6563\u53d1\u3002"
when_to_use: "Query a versioned climate table OR calculate wind components from speed and direction arrays OR daily ET0 from supplied weather and site inputs. Meteorological calculations do not require an SSP or paleoclimate dataset."
required_inputs: [Requested climate or meteorological operation, Versioned table for queries OR measured weather inputs with units for calculations]
---
# Climate Timescale and Scenario Analysis

## Procedure

Choose a table query or a meteorological calculation. Only table queries need
climate snapshots and baseline/SSP columns; wind components and ET0 use the
supplied physical inputs listed in their schemas.

1. Identify the actual research question and use only the relevant operations below.
2. Inspect supplied data and provenance. Confirm release, observation date, columns, units, CRS, masks and scientific coverage where applicable. Missing data must be requested or retrieved from an authorized source, never invented.
3. Call the disclosed native functions with named object arguments. The current input and output schemas are authoritative; do not pass question IDs, prose or assume server-private file paths.
4. Use observed values and generated artifacts. State method limitations and uncovered areas; label synthetic inputs as tests.

## ClimateQueryDeepTime

ClimateQueryDeepTime on an explicitly supplied versioned dataset. age_kyr_bp, temp_anomaly_C columns required.


Required dataset fields: age_kyr_bp, temp_anomaly_C.

## ClimateQueryPresentMean

ClimateQueryPresentMean on an explicitly supplied versioned dataset. year, temp_anomaly_C columns required.


Required dataset fields: year, temp_anomaly_C.

## ClimateQueryFutureSSP

ClimateQueryFutureSSP on an explicitly supplied versioned dataset. scenario, horizon_year, estimate_c, lower_c, upper_c columns required.


Required dataset fields: scenario, horizon_year, estimate_c, lower_c, upper_c.

## ClimateCompareEpochs

Subtract the first supplied epoch value from each supplied value. No climate data lookup.

## MetPyWindComponents

Convert supplied wind speed and meteorological-from direction arrays to `u` and
`v` components. Confirm the speed unit; direction is degrees where 0 means wind
from north. The adapter returns components in m/s and does not infer missing
units.

## HydroReferenceET0

Compute daily FAO-56 reference ET0 from supplied temperature, humidity, wind,
radiation, latitude, day-of-year and optional altitude. The adapter derives net
radiation from measured incoming shortwave using FAO-56 albedo and longwave
terms, and returns that intermediate value. State the input units and treat the
result as a calculation requiring independent scientific review for production
studies.
Use wind speed at 2 m. Polar-night conditions with zero clear-sky radiation are
unsupported. Rs up to 5% above computed Rso is limited to Rso in the longwave
term (FAO-56 Eq. 39) and reported as `rs_rso_limited`; mention it in the
answer. Larger excesses are rejected; check the observations or units before
submitting corrected inputs.


## Source interface and delivery

The canonical catalog contains native entrypoints, named input/output schemas, units, constraints, error behavior and synthetic call examples. Input files remain unchanged. Runtime paths must be relative to the current task; direct Python callers provide their explicit output directory.
Data-dependent queries require a supplied versioned snapshot. No data license, global model coverage or scientific certification is implied. Independent source-call validation and whole-Skill end-to-end validation are separate.

### Current availability

tool_candidates_available_workflow_unverified

All referenced tool implementations have native contracts. Runtime registration and acceptance are checked by the merge release tests; the complete Skill workflow has not been certified. Official lab registration metadata and platform validation remain pending.

## Preserved source-specific scientific constraints

The following original guidance applies to the original operations only, not to unrelated array-based calculations.

# Climate Timescale and Scenario Analysis

## Procedure

1. Identify the actual research question and use only the relevant operations below.
2. Inspect supplied data and provenance. Confirm release, observation date, columns, units, CRS, masks and scientific coverage where applicable. Missing data must be requested or retrieved from an authorized source, never invented.
3. Call the disclosed native functions with named object arguments. The current input and output schemas are authoritative; do not pass question IDs, prose or assume server-private file paths.
4. Use observed values and generated artifacts. State method limitations and uncovered areas; label synthetic inputs as tests.

## ClimateQueryDeepTime

ClimateQueryDeepTime on an explicitly supplied versioned dataset. age_kyr_bp, temp_anomaly_C columns required.


Required dataset fields: age_kyr_bp, temp_anomaly_C.

## ClimateQueryPresentMean

ClimateQueryPresentMean on an explicitly supplied versioned dataset. year, temp_anomaly_C columns required.


Required dataset fields: year, temp_anomaly_C.

## ClimateQueryFutureSSP

ClimateQueryFutureSSP on an explicitly supplied versioned dataset. scenario, horizon_year, estimate_c, lower_c, upper_c columns required.


Required dataset fields: scenario, horizon_year, estimate_c, lower_c, upper_c.

## ClimateCompareEpochs

Subtract the first supplied epoch value from each supplied value. No climate data lookup.


## Source interface and delivery

The canonical catalog contains native entrypoints, named input/output schemas, units, constraints, error behavior and synthetic call examples. Input files remain unchanged. Runtime paths must be relative to the current task; direct Python callers provide their explicit output directory.
Data-dependent queries require a supplied versioned snapshot. No data license, global model coverage or scientific certification is implied. Independent source-call validation and whole-Skill end-to-end validation are separate.

### Current availability

tool_candidates_available_workflow_unverified

All referenced tool implementations have native contracts. Runtime registration and acceptance are checked by the merge release tests; the complete Skill workflow has not been certified. Official lab registration metadata and platform validation remain pending.

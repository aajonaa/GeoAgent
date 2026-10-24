---
id: approved_functional_hydrology_replacements
name: Explicit groundwater spectral response and seasonal flow forecasting
description: Two limited, separately labelled SciPy/statsmodels alternatives; not the original HydroGeoSines or PyForecast applications.
when_to_use: Use only for regular pressure-head/groundwater-head spectral response or matrix-based seasonal flow forecasting with uncertainty.
tools: [ScipyGroundwaterFrequencyResponse, StatsmodelsSeasonalFlowForecast]
required_inputs: ["Regular finite time and head arrays in seconds/metres for spectral response, or finite flow/design arrays with annual phases and dimensionless predictors for OLS."]
constraints: ["Select only the operation needed; never call both just to increase tool counts.", "These are explicit limited replacements, not implementations of the original projects.", "Do not invent observations, API evidence, tidal corrections, GUI features or nonnegative hydrological simulation."]
expected_outputs: ["Observed library results with units, source provenance and explicit method limitations."]
coverage_kind: explicit_functional_replacement
coverage_target_project_ids: [72, 82]
---

# Scope

ScipyGroundwaterFrequencyResponse uses actual SciPy Welch/CSD/coherence on
regular series. Pressure-head and groundwater-head must already be metres;
frequency is Hz, gain is dimensionless and phase is radians. A groundwater
lag has negative phase. Invalid/low-power and DC bins remain explicit rather
than fabricated ratios. This is not HydroGeoSines, tidal correction or aquifer
parameter estimation.

StatsmodelsSeasonalFlowForecast uses actual matrix-based statsmodels OLS with
intercept, annual sine/cosine and supplied dimensionless predictors. Flow,
forecast and confidence/prediction interval outputs are m3/s. Require a full-
rank, conditioned design; no formula strings, user code or data acquisition.
Unconstrained negative outputs are labelled and never silently clipped. This
is not the PyForecast GUI, automatic model selection or a runoff simulator.

Never treat the bundled synthetic acceptance examples as observed data.

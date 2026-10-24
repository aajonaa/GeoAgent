---
id: "earth_collection_hydro_data_opt"
name: "Earth collection hydro data opt"
description: "Bounded upstream hydro data opt operations with explicit schemas, physical units, evidence and artifact outputs."
when_to_use: "Bounded upstream hydro data opt operations with explicit schemas, physical units, evidence and artifact outputs."
tools: ["EarthHydroHyRiverFlowExceedance", "EarthHydroWetterdienstElevationAdjustment", "EarthHydroUlmoWaterMLValues", "EarthHydroFewsPiTimeSeries", "EarthHydroOpenradarRainRate", "EarthHydroCamelsStationSeries", "EarthHydroBomWaterMLObservations", "EarthHydroPastasExponentialImpulse", "EarthHydroHydropyChapmanBaseflow", "EarthHydroHydrostatsDailyClimatology", "EarthHydroHtimeseriesReadRecords", "EarthHydroEftsForecastEnsemble", "EarthHydroSpotpyNashSutcliffe", "EarthHydroClimateAccumulation", "EarthHydroPyemuExponentialCovariance", "EarthHydroHydrolmRegularizeDaily"]
required_inputs: ["Arguments and datasets declared by the selected tool's input schema"]
constraints: ["Choose only operations relevant to the current task; do not load the entire collection.", "Use supplied data and declared units; never fabricate measurements or execution evidence.", "Never install dependencies, download data, execute arbitrary scripts or load untrusted serialized models during a tool call.", "Report missing prerequisites honestly. Missing runtime dependencies are not missing user research intent.", "Use only returned artifact paths and preserve source provenance and scientific limitations."]
expected_outputs: ["Observed schema-valid results with explicit units and provenance", "Real registered previews/data files only where the tool declares outputs"]
---

# Earth collection hydro data opt

Bounded upstream hydro data opt operations with explicit schemas, physical units, evidence and artifact outputs.

## Source interface and delivery

Direct calls accept args=dict or args=a_JSON_object_string. Artifact-producing standalone calls require output_dir set to a new or empty directory. Native execution snapshots task-relative inputs and registers generated result files.

- EarthHydroHyRiverFlowExceedance: `geological_agent.geology.collection_hydro_data_opt:hyriver_flow_exceedance`. Compute daily-discharge exceedance probabilities using the archived HyRiver hydrosignatures child function, excluding values at or below an explicit threshold.
- EarthHydroWetterdienstElevationAdjustment: `geological_agent.geology.collection_hydro_data_opt:wetterdienst_elevation_adjustment`. Apply Wetterdienst archived lapse-rate reduction to a bounded temperature vector and explicitly supplied station and target elevations.
- EarthHydroUlmoWaterMLValues: `geological_agent.geology.collection_hydro_data_opt:ulmo_waterml_values`. Parse a local WaterML 1.1 time series with the real Ulmo parser, preserving timestamps, qualifiers and declared NoData as JSON null.
- EarthHydroFewsPiTimeSeries: `geological_agent.geology.collection_hydro_data_opt:fews_pi_time_series`. Parse observed local Delft-FEWS PI XML events with the archived HKVFEWSPY parser, returning values, timestamps and quality flags.
- EarthHydroOpenradarRainRate: `geological_agent.geology.collection_hydro_data_opt:openradar_rain_rate`. Convert radar reflectivity to rain rate using the exact Openradar Rain class and Marshall-Palmer Z-R relation, including upstream noise rejection and hail clipping.
- EarthHydroCamelsStationSeries: `geological_agent.geology.collection_hydro_data_opt:camels_station_series`. Load a bounded local CAMELS-AUS-format station CSV using the real loader and optional upstream negative-sentinel missing-value mask.
- EarthHydroBomWaterMLObservations: `geological_agent.geology.collection_hydro_data_opt:bom_waterml_observations`. Parse a local BOM-style SOS WaterML 2.0 observation with upstream BomWater.parse_data and its original quality/time parsing helpers.
- EarthHydroPastasExponentialImpulse: `geological_agent.geology.collection_hydro_data_opt:pastas_exponential_impulse`. Evaluate the exact archived Pastas Exponential.impulse groundwater-response kernel for explicitly dimensionless gain and decay time in days.
- EarthHydroHydropyChapmanBaseflow: `geological_agent.geology.collection_hydro_data_opt:hydropy_chapman_baseflow`. Separate a bounded streamflow series with the exact archived Hydropy Chapman recursive baseflow function.
- EarthHydroHydrostatsDailyClimatology: `geological_agent.geology.collection_hydro_data_opt:hydrostats_daily_climatology`. Compute daily seasonal means across years using archived Hydrostats daily_average with rolling disabled.
- EarthHydroHtimeseriesReadRecords: `geological_agent.geology.collection_hydro_data_opt:htimeseries_read_records`. Parse local HTimeseries three-column records with upstream CSV/date/duplicate-check methods, preserving flags and empty measurements as null.
- EarthHydroEftsForecastEnsemble: `geological_agent.geology.collection_hydro_data_opt:efts_forecast_ensemble`. Extract an ensemble forecast for one station and initialization from a bounded local JSON array using the actual archived EftsDataSet forecast selector.
- EarthHydroSpotpyNashSutcliffe: `geological_agent.geology.collection_hydro_data_opt:spotpy_nash_sutcliffe`. Score paired observed and simulated hydrological series with SPOTpy archived Nash-Sutcliffe efficiency.
- EarthHydroClimateAccumulation: `geological_agent.geology.collection_hydro_data_opt:climate_accumulation`. Compute sliding precipitation totals using the exact climate_indices sum_to_scale convolution and serialize its initial NaN pad as null.
- EarthHydroPyemuExponentialCovariance: `geological_agent.geology.collection_hydro_data_opt:pyemu_exponential_covariance`. Evaluate the unchanged pyEMU ExpVario covariance kernel at supplied separation distances for groundwater-head variance in m2.
- EarthHydroHydrolmRegularizeDaily: `geological_agent.geology.collection_hydro_data_opt:hydrolm_regularize_daily`. Regularize increasing calendar samples to daily spacing and interpolate bounded internal gaps with the original HydroLM tsreg utility.

### Current availability

tool_candidates_available_workflow_unverified

All listed entries have concrete source operations; this is not execution proof. Workflow validation: not_run. Platform validation: not_run. Original archive revisions and separately pinned published releases are not assumed byte-identical. Formal receiving AI Lab approval remains pending.

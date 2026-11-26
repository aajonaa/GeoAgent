---
id: "earth_collection_weather_climate_seismic"
name: "Earth collection weather climate seismic"
description: "Bounded upstream weather climate seismic operations with explicit schemas, physical units, evidence and artifact outputs."
when_to_use: "Bounded upstream weather climate seismic operations with explicit schemas, physical units, evidence and artifact outputs."
tools: ["WrfDestaggerGrid", "RainymotionPrecipitationScores", "MetSimPotentialEvapotranspiration", "MelodistDailyPrecipitationToHourly", "ImproverRescaleForecastField", "SkdownscaleQuantileBiasCorrection", "JamsDewPoint", "XgcmStaggeredGridDiagnostics", "ClimpredEnsembleCrps", "ClimlabLayerHeatCapacity", "AospyHybridPressure", "OocgcmSurfaceSpiciness", "OcgisHeatIndex", "PyrockoDoubleCoupleTensor", "RsudpWindowAmplitude", "SeismicZfpCompressCube"]
required_inputs: ["Arguments and datasets declared by the selected tool's input schema"]
constraints: ["Choose only operations relevant to the current task; do not load the entire collection.", "Use supplied data and declared units; never fabricate measurements or execution evidence.", "Never install dependencies, download data, execute arbitrary scripts or load untrusted serialized models during a tool call.", "Report missing prerequisites honestly. Missing runtime dependencies are not missing user research intent.", "Use only returned artifact paths and preserve source provenance and scientific limitations."]
expected_outputs: ["Observed schema-valid results with explicit units and provenance", "Real registered previews/data files only where the tool declares outputs"]
---

# Earth collection weather climate seismic

Bounded upstream weather climate seismic operations with explicit schemas, physical units, evidence and artifact outputs.

## Source interface and delivery

Direct calls accept args=dict or args=a_JSON_object_string. Artifact-producing standalone calls require output_dir set to a new or empty directory. Native execution snapshots task-relative inputs and registers generated result files.

- WrfDestaggerGrid: `geological_agent.geology.collection_weather_climate_seismic:wrf_destagger_grid`. Destagger a bounded 1D/2D/3D WRF-style field by upstream adjacent-cell averaging along one declared axis.
- RainymotionPrecipitationScores: `geological_agent.geology.collection_weather_climate_seismic:rainymotion_precipitation_scores`. Compute real rainymotion precipitation RMSE/MAE and threshold contingency skill scores for paired samples.
- MetSimPotentialEvapotranspiration: `geological_agent.geology.collection_weather_climate_seismic:metsim_potential_evapotranspiration`. Calculate upstream MetSim daylight potential evapotranspiration with the Priestley-Taylor aridity-correction approximation.
- MelodistDailyPrecipitationToHourly: `geological_agent.geology.collection_weather_climate_seismic:melodist_daily_precipitation_to_hourly`. Disaggregate contiguous daily precipitation totals into hourly interval totals with the upstream mass-conserving uniform method.
- ImproverRescaleForecastField: `geological_agent.geology.collection_weather_climate_seismic:improver_rescale_forecast_field`. Apply upstream IMPROVER linear rescaling and optional clipping of a bounded forecast field into dimensionless scores.
- SkdownscaleQuantileBiasCorrection: `geological_agent.geology.collection_weather_climate_seismic:skdownscale_quantile_bias_correction`. Apply archived scikit-downscale empirical Cunnane quantile mapping to one finite scalar climate variable.
- JamsDewPoint: `geological_agent.geology.collection_weather_climate_seismic:jams_dew_point`. Calculate upstream JAMS Buck-original dew point from actual ambient vapour pressure, with explicit Celsius or Kelvin output.
- XgcmStaggeredGridDiagnostics: `geological_agent.geology.collection_weather_climate_seismic:xgcm_staggered_grid_diagnostics`. Use xgcm finite-volume center-to-inner interpolation and differencing on a bounded uniform 1D field.
- ClimpredEnsembleCrps: `geological_agent.geology.collection_weather_climate_seismic:climpred_ensemble_crps`. Compute climpred ensemble CRPS per supplied sample and its mean without hindcast alignment or remote datasets.
- ClimlabLayerHeatCapacity: `geological_agent.geology.collection_weather_climate_seismic:climlab_layer_heat_capacity`. Compute upstream climlab areal heat capacities for atmospheric pressure layers or liquid-water layers.
- AospyHybridPressure: `geological_agent.geology.collection_weather_climate_seismic:aospy_hybrid_pressure`. Construct bounded hybrid sigma-pressure half-level arrays from supplied coefficients and surface pressures using aospy.
- OocgcmSurfaceSpiciness: `geological_agent.geology.collection_weather_climate_seismic:oocgcm_surface_spiciness`. Evaluate the actual oocgcm Flament 2002 near-surface water-mass spiciness polynomial.
- OcgisHeatIndex: `geological_agent.geology.collection_weather_climate_seismic:ocgis_heat_index`. Evaluate the exact OpenClimateGIS heat-index polynomial and retain its original out-of-domain masks.
- PyrockoDoubleCoupleTensor: `geological_agent.geology.collection_weather_climate_seismic:pyrocko_double_couple_tensor`. Construct a real Pyrocko double-couple moment tensor in north-east-down coordinates from strike, dip, rake, and scalar moment.
- RsudpWindowAmplitude: `geological_agent.geology.collection_weather_climate_seismic:rsudp_window_amplitude`. Compute the exact rsudp RSAM mean/median/min/max absolute amplitude on a bounded supplied waveform window.
- SeismicZfpCompressCube: `geological_agent.geology.collection_weather_climate_seismic:seismic_zfp_compress_cube`. Compress a bounded supplied 3D seismic float32 cube into SGZ with the real seismic-zfp engine and report measured CPU round-trip errors.

### Current availability

tool_candidates_available_workflow_unverified

All listed entries have concrete source operations; this is not execution proof. Workflow validation: not_run. Platform validation: not_run. Original archive revisions and separately pinned published releases are not assumed byte-identical. Formal receiving AI Lab approval remains pending.

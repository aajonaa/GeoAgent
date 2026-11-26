---
id: "earth_collection_offline_originals"
name: "Offline Earth data and fixed hydrological evaluation"
description: "Select bounded offline raster, land-grid, climate, wind and fixed ABC hydrological operations for supplied research inputs."
when_to_use: "Select bounded offline raster, land-grid, climate, wind and fixed ABC hydrological operations for supplied research inputs."
tools: ["EarthPyOWMBeaufortWind", "EarthSimRasterCrossSection", "EarthERA5LocalMonthlyClimate", "EarthPangaeaGeographicGrid", "EarthGeoNotebookPolygonSubset", "EarthHydroShareRasterBandRanges", "EarthPyGLUEABCEnsemble"]
required_inputs: ["Task-specific schema arguments, local files and exact units declared by the selected tool"]
constraints: ["Choose only task-relevant tools, not the entire collection.", "Use supplied local data, explicit physical units and actual execution evidence; never fabricate measurements or artifacts.", "Do not install packages, access external services, accept callbacks, execute arbitrary scripts or load pickle objects.", "Runtime files are bounded to 2 MiB; the larger source-only notebook limit is not an input allowance.", "HydroShare requires its verified fixed GDAL file-worker profile; do not route it through a scalar-only bridge or silently use the host interpreter.", "PyGLUE here uses a fixed original ABC model and NSE objective; no full sampler, posterior probability or confidence-interval support is claimed."]
expected_outputs: ["Observed finite schema-valid JSON results, physical units, original-source provenance and input hashes", "No image or file artifact is claimed by these seven JSON-output operations"]
---

# Offline Earth data and fixed hydrological evaluation

Select bounded offline raster, land-grid, climate, wind and fixed ABC hydrological operations for supplied research inputs.

## Source interface and delivery

Direct calls accept args=dict or args=a_JSON_object_string. Native ToolExecutor execution snapshots task-relative inputs. Never substitute web search for an available relevant local scientific operation.

- EarthPyOWMBeaufortWind: `geological_agent.geology.collection_offline_originals.adapters:pyowm_beaufort_wind`. Classify measured wind speeds using the original PyOWM Beaufort thresholds, offline.
- EarthSimRasterCrossSection: `geological_agent.geology.collection_offline_originals.adapters:earthsim_raster_cross_section`. Extract an offline projected-raster profile along a line using EarthSim's original path-interpolation kernel.
- EarthERA5LocalMonthlyClimate: `geological_agent.geology.collection_offline_originals.adapters:era5_local_monthly_climate`. Compute original ERA5-tools monthly climatological means and nearest-node time series from a local NetCDF3 source.
- EarthPangaeaGeographicGrid: `geological_agent.geology.collection_offline_originals.adapters:pangaea_geographic_grid`. Normalize geographic land-model array row alignment and longitude using the original Pangaea grid accessor kernels.
- EarthGeoNotebookPolygonSubset: `geological_agent.geology.collection_offline_originals.adapters:geonotebook_polygon_subset`. Apply GeoNotebook's original all-touched polygon raster mask to a bounded WGS84 single-band raster.
- EarthHydroShareRasterBandRanges: `geological_agent.geology.collection_offline_originals.adapters:hydroshare_raster_band_ranges`. Compute native raster-band min/max using HydroShare's original statistics extractor in an isolated CPU subprocess.
- EarthPyGLUEABCEnsemble: `geological_agent.geology.collection_offline_originals.pyglue_fixed.adapters:pyglue_abc_ensemble`. Evaluate supplied fixed ABC rainfall-runoff parameter sets using the original PyGLUE evaluator and original RRMPG/SPOTPY kernels, without user callbacks.

### Current availability

tool_candidates_available_workflow_unverified

Independent schema, direct, numeric and native CPU validation passed. Model workflow validation: not_run. Platform validation: not_run. Source hashes and licenses are retained. Formal receiving AI Lab approval and parent global merge remain pending.

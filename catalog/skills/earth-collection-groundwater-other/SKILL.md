---
id: "earth_collection_groundwater_other"
name: "Earth collection groundwater other"
description: "Bounded upstream groundwater other operations with explicit schemas, physical units, evidence and artifact outputs."
when_to_use: "Bounded upstream groundwater other operations with explicit schemas, physical units, evidence and artifact outputs."
tools: ["EarthFlopyWaterTable", "EarthTimmlSteadyWellHeads", "EarthTtimTransientWellDrawdown", "EarthPyhelpStationDistances", "EarthImodFreshwaterHead", "EarthIdfMaskedRasterAggregate", "EarthWellapplicationBaseflow", "EarthWelltestBourdetDerivative", "EarthPytesmoMeanStdScale", "EarthPhydrusReadTlevel", "EarthLandlabFlowDirections", "EarthIrisCubeCorrelation", "EarthPyhspfReachTable", "EarthSphyCropEvapotranspiration", "EarthXsboringenLithology", "EarthEflowMagnitudeIndices", "EarthHydroboxFlashiness"]
required_inputs: ["Arguments and datasets declared by the selected tool's input schema"]
constraints: ["Choose only operations relevant to the current task; do not load the entire collection.", "Use supplied data and declared units; never fabricate measurements or execution evidence.", "Never install dependencies, download data, execute arbitrary scripts or load untrusted serialized models during a tool call.", "Report missing prerequisites honestly. Missing runtime dependencies are not missing user research intent.", "Use only returned artifact paths and preserve source provenance and scientific limitations."]
expected_outputs: ["Observed schema-valid results with explicit units and provenance", "Real registered previews/data files only where the tool declares outputs"]
---

# Earth collection groundwater other

Bounded upstream groundwater other operations with explicit schemas, physical units, evidence and artifact outputs.

## Source interface and delivery

Direct calls accept args=dict or args=a_JSON_object_string. Artifact-producing standalone calls require output_dir set to a new or empty directory. Native execution snapshots task-relative inputs and registers generated result files.

- EarthFlopyWaterTable: `geological_agent.geology.collection_groundwater_other:flopy_water_table`. Extract the uppermost active groundwater head from a bounded layered grid using FloPy, preserving dry/no-flow/custom masks and returning null where the entire column is inactive.
- EarthTimmlSteadyWellHeads: `geological_agent.geology.collection_groundwater_other:timml_steady_well_heads`. Solve one homogeneous confined aquifer with up to 16 specified-discharge wells and one reference head; evaluate heads at up to 64 observation points with the real TimML analytic-element model.
- EarthTtimTransientWellDrawdown: `geological_agent.geology.collection_groundwater_other:ttim_transient_well_drawdown`. Evaluate transient drawdown after one constant-rate pumping step in a homogeneous confined aquifer using the TTim Laplace-domain well solution and numerical inversion.
- EarthPyhelpStationDistances: `geological_agent.geology.collection_groundwater_other:pyhelp_station_distances`. Compute PyHELP spherical horizontal distances from one location to a bounded set of meteorological or groundwater locations using its original haversine kernel.
- EarthImodFreshwaterHead: `geological_agent.geology.collection_groundwater_other:imod_freshwater_head`. Convert saturated point-water heads to equivalent freshwater heads with the exact iMOD function, retaining its original density correction and real grid-type guards.
- EarthIdfMaskedRasterAggregate: `geological_agent.geology.collection_groundwater_other:idf_masked_raster_aggregate`. Apply the actual Idfpy masked-array reducer or first-raster-priority merge to bounded aligned raster values; JSON null explicitly denotes missing cells.
- EarthWellapplicationBaseflow: `geological_agent.geology.collection_groundwater_other:wellapplication_baseflow`. Separate a regularly sampled discharge series with the original WellApplication Chapman, Boughton or IHACRES recursive baseflow filter.
- EarthWelltestBourdetDerivative: `geological_agent.geology.collection_groundwater_other:welltest_bourdet_derivative`. Compute the original WellTestPy Bourdet derivative of drawdown with respect to natural logarithmic time for pumping-test diagnostics.
- EarthPytesmoMeanStdScale: `geological_agent.geology.collection_groundwater_other:pytesmo_mean_std_scale`. Match a volumetric soil-moisture series to the reference distribution using the exact Pytesmo population-mean/standard-deviation scaling function.
- EarthPhydrusReadTlevel: `geological_agent.geology.collection_groundwater_other:phydrus_read_tlevel`. Read a bounded HYDRUS T_LEVEL.OUT snapshot with the real Phydrus text reader and return explicit day/metre flux and head series with a pre-call byte hash.
- EarthLandlabFlowDirections: `geological_agent.geology.collection_groundwater_other:landlab_flow_directions`. Route a bounded regular or irregular node-link terrain graph to steepest downhill neighbours using the actual compiled Landlab single-flow-direction kernel.
- EarthIrisCubeCorrelation: `geological_agent.geology.collection_groundwater_other:iris_cube_correlation`. Compute weighted Pearson correlations between matched sample-by-site air-temperature cubes through the real Iris cube statistics API.
- EarthPyhspfReachTable: `geological_agent.geology.collection_groundwater_other:pyhspf_reach_table`. Generate the original PyHSPF 15-row reach FTABLE from average flow, velocity, reach length, slope and bounded trapezoidal floodplain assumptions.
- EarthSphyCropEvapotranspiration: `geological_agent.geology.collection_groundwater_other:sphy_crop_evapotranspiration`. Apply the original SPHY potential crop evapotranspiration calculation to bounded reference-ET and crop-coefficient series.
- EarthXsboringenLithology: `geological_agent.geology.collection_groundwater_other:xsboringen_lithology`. Classify bounded CPT friction-ratio/cone-resistance samples with the original xsboringen exponential lithology rules and explicit caller-supplied thresholds.
- EarthEflowMagnitudeIndices: `geological_agent.geology.collection_groundwater_other:eflow_magnitude_indices`. Compute five EFlowCalc daily-flow magnitude descriptors: mean, median, mean/median and 90/10 plus 80/20 percentile ratios using the real upstream functions.
- EarthHydroboxFlashiness: `geological_agent.geology.collection_groundwater_other:hydrobox_flashiness`. Compute the archived Hydrobox Richards-Baker flashiness variant from bounded regularly sampled discharge using its original implementation.

### Current availability

tool_candidates_available_workflow_unverified

All listed entries have concrete source operations; this is not execution proof. Workflow validation: not_run. Platform validation: not_run. Original archive revisions and separately pinned published releases are not assumed byte-identical. Formal receiving AI Lab approval remains pending.

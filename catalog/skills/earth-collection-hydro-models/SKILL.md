---
id: "earth_collection_hydro_models"
name: "Earth collection hydro models"
description: "Bounded upstream hydro models operations with explicit schemas, physical units, evidence and artifact outputs."
when_to_use: "Bounded upstream hydro models operations with explicit schemas, physical units, evidence and artifact outputs."
tools: ["HydroModelsXanthosMonthlyPET", "HydroModelsRRMPGABCRunoff", "HydroModelsNeuralHydrologyFlowScores", "HydroModelsHydroFunctionsFlowDuration", "HydroModelsCMFSoilConductivity", "HydroModelsTopoFlowSolarFlux", "HydroModelsEXPHydroBucketWaterBalance", "HydroModelsPyTOPKAPIGreenAmpt", "HydroModelsHidroCompEnsembleRMSE"]
required_inputs: ["Arguments and datasets declared by the selected tool's input schema"]
constraints: ["Choose only operations relevant to the current task; do not load the entire collection.", "Use supplied data and declared units; never fabricate measurements or execution evidence.", "Never install dependencies, download data, execute arbitrary scripts or load untrusted serialized models during a tool call.", "Report missing prerequisites honestly. Missing runtime dependencies are not missing user research intent.", "Use only returned artifact paths and preserve source provenance and scientific limitations."]
expected_outputs: ["Observed schema-valid results with explicit units and provenance", "Real registered previews/data files only where the tool declares outputs"]
---

# Earth collection hydro models

Bounded upstream hydro models operations with explicit schemas, physical units, evidence and artifact outputs.

## Source interface and delivery

Direct calls accept args=dict or args=a_JSON_object_string. Artifact-producing standalone calls require output_dir set to a new or empty directory. Native execution snapshots task-relative inputs and registers generated result files.

- HydroModelsXanthosMonthlyPET: `geological_agent.geology.collection_hydro_models:xanthos_monthly_pet`. Monthly Hargreaves PET for bounded independent cells using the archived NumPy kernel.
- HydroModelsRRMPGABCRunoff: `geological_agent.geology.collection_hydro_models:rrmpg_abc_runoff`. Original ABC conceptual rainfall-runoff model with one parameter set and explicit initial storage.
- HydroModelsNeuralHydrologyFlowScores: `geological_agent.geology.collection_hydro_models:neuralhydrology_flow_scores`. Offline hydrologic evaluation of existing observed/simulated discharge, with no neural inference.
- HydroModelsHydroFunctionsFlowDuration: `geological_agent.geology.collection_hydro_models:hydrofunctions_flow_duration`. Offline empirical flow-duration probabilities using the real HydroFunctions flow_duration implementation.
- HydroModelsCMFSoilConductivity: `geological_agent.geology.collection_hydro_models:cmf_soil_conductivity`. Van Genuchten-Mualem unsaturated hydraulic conductivity at supplied pore-volume wetness values.
- HydroModelsTopoFlowSolarFlux: `geological_agent.geology.collection_hydro_models:topoflow_solar_flux`. Instantaneous top-of-atmosphere horizontal shortwave flux from the original TopoFlow solar routines.
- HydroModelsEXPHydroBucketWaterBalance: `geological_agent.geology.collection_hydro_models:exphydro_bucket_water_balance`. Original EXP-HYDRO bucket water-balance right-hand side at supplied independent snow/soil states.
- HydroModelsPyTOPKAPIGreenAmpt: `geological_agent.geology.collection_hydro_models:pytopkapi_green_ampt`. Green-Ampt cumulative infiltration and rainfall excess over bounded constant-rate rainfall intervals.
- HydroModelsHidroCompEnsembleRMSE: `geological_agent.geology.collection_hydro_models:hidrocomp_ensemble_rmse`. Per-position ensemble discharge RMSE against a supplied reference using the archived HidroComp comparison class.

### Current availability

tool_candidates_available_workflow_unverified

All listed entries have concrete source operations; this is not execution proof. Workflow validation: not_run. Platform validation: not_run. Original archive revisions and separately pinned published releases are not assumed byte-identical. Formal receiving AI Lab approval remains pending.

---
id: earth_collection_hydro_cpu_profiles
name: Fixed CPU hydrology and terrain analysis
description: Six bounded original hydrology operations using separately pinned CPU
  dependency profiles.
when_to_use: Six bounded original hydrology operations using separately pinned CPU
  dependency profiles.
required_inputs:
- A task-relative bounded UTF-8 JSON file with explicit units
tools:
- HydroModelsPyFloCurveNumberRunoff
- HydroModelsPySTEPSPrecipitationAdvection
- EarthCatchmodLinearStoreStep
- HydroModelsSuperflexUnitHydrograph
- HydroModelsHydPyFlowScores
- HydroModelsPyDEMTerrainDerivatives
constraints:
- Use only the task-required operations and declared units.
- No network, callbacks, user scripts, pickle, arbitrary executables or package installation.
- Examples are explicitly synthetic acceptance data, not field observations.
expected_outputs:
- Observed numeric JSON with exact units, source and installed-worker provenance
---
# Six fixed CPU hydrology operations

Each operation uses its reviewed original upstream library in a fixed private CPU dependency profile.
The parent does not claim these scientific packages are installed in its Python. All examples are synthetic.
A dependency profile is not a user isolation sandbox. Workspace authorization is enforced by the shared SDK.

## HydroModelsPyFloCurveNumberRunoff
SCS curve-number event runoff depth and volume for explicit rainfall depths, curve number and catchment area.
Example: `{"data_path": "assets/earth-collection/hydro_cpu_profiles/pyflo_curve_number_runoff.json", "curve_number": 80, "area_acres": 1}`
Limits: ['Rainfall is inches and area is acres; returned volume is cubic feet. This upstream API uses US customary units.', 'Uses the original Basin.runoff_depth and runoff_volume, with fixed unused hydrograph-construction parameters. No user-supplied distribution, equation, simpleeval expression or script is exposed.', 'Curve number is 1..100, area is 0.001..1000000 acres and there are at most 1000 independent event depths.', 'Archive setup.py strips historical == pins from requirements/production.txt. Common NumPy/SciPy/matplotlib pins are retained, rather than adopting that old reference requirements file. Archive/release byte identity is not asserted.', 'Independent acceptance does not establish model-workflow, receiving-platform, or formal AI Lab approval.']

## HydroModelsPySTEPSPrecipitationAdvection
Semi-Lagrangian deterministic precipitation advection of a bounded local rain grid with supplied velocity.
Example: `{"data_path": "assets/earth-collection/hydro_cpu_profiles/pysteps_precipitation_advection.json", "lead_steps": 2}`
Limits: ['All three grids share a 2..128 by 2..128 shape; no optical-flow estimation, stochastic ensemble, model weights, radar downloads or external forecast.', 'Velocity components are east and south pixels per input step. Lead times are integer multiples of that same step.', 'Uses one integration iteration, linear spatial interpolation and zero outside the domain. Loss at boundaries is expected.', 'The reference check uses uniform velocity fixtures with an independent exact transport solution.', 'Independent acceptance does not establish model-workflow, receiving-platform, or formal AI Lab approval.']

## EarthCatchmodLinearStoreStep
Route parallel scenarios for one daily step through the original archived CATCHMOD linear reservoir, returning mean flow, end flow, storage and water-balance residuals.
Example: `{"data_path": "assets/earth-collection/hydro_cpu_profiles/catchmod_linear_store_step.json", "linear_storage_days": 0.5}`
Limits: ['One fixed daily timestep over independent scenarios, not a calibrated catchment forecast.', 'Initial flow is at least 0.000001 mm/day, explicitly excluding the upstream very-small-flow clamp branch; zero-initial-flow simulation is not claimed.', 'Water depths and flows are normalized per catchment area; no area or discharge-unit conversion is performed.', 'Never downloads, builds, installs or loads executable user configuration at tool execution time.']

## HydroModelsSuperflexUnitHydrograph
Mass-preserving GR4J UnitHydrograph1 routing of effective rainfall using the actual SuperflexPy LagElement.
Example: `{"data_path": "assets/earth-collection/hydro_cpu_profiles/superflex_unit_hydrograph.json", "lag_steps": 2}`
Limits: ['UnitHydrograph1 uses its upstream 2.5-power cumulative S-curve; lag is 1..30 input time steps.', 'Adds ceil(lag)+1 zero-forcing tail steps so the complete response is reported and terminal state shifting cannot erase a nonzero last output.', 'Outputs remain mm/step, not volumetric river discharge. No arbitrary framework topology, code, state pickle or model configuration is accepted.', 'Numba uses the confirmed common version 0.68.0; it is not downgraded to the historical minimum in package metadata.', 'Independent acceptance does not establish model-workflow, receiving-platform, or formal AI Lab approval.']

## HydroModelsHydPyFlowScores
Modified Kling-Gupta efficiency, Nash-Sutcliffe efficiency and RMSE of paired discharge series.
Example: `{"data_path": "assets/earth-collection/hydro_cpu_profiles/hydpy_flow_scores.json"}`
Limits: ['Both nonconstant series have positive means, finite nonnegative discharge in m3/s, and the same 2..10000 sample count.', 'HydPy KGE uses the coefficient-of-variation ratio (modified KGE); it differs from NeuralHydrology KGE.', 'Pinned installed release is 6.4.0; the archive is 7.0dev0 at the recorded commit. No archive HEAD execution is claimed.', 'Independent acceptance does not establish model-workflow, receiving-platform, or formal AI Lab approval.']

## HydroModelsPyDEMTerrainDerivatives
Tarboton D-infinity slope magnitude and downslope direction from a small elevation grid with explicit metric spacing.
Example: `{"data_path": "assets/earth-collection/hydro_cpu_profiles/pydem_terrain_derivatives.json", "east_spacing_m": 2, "north_spacing_m": 3}`
Limits: ['Requires a rectangular 3..128 by 3..128 local metric grid. Horizontal spacings and elevation are metres; no CRS is guessed.', 'Disables flat filling, pit drainage and path construction. Only the interior (without the one-cell boundary) is returned.', 'Undefined/flat/pit cells use paired JSON nulls, not an invented flow direction. No contributing area, TWI, GDAL subprocess or external TauDEM engine is called.', 'The published binary targets CPython 3.11 and glibc 2.41; the common CPython 3.12 profile needs a separately accepted source build. No binary compatibility is assumed.', 'Independent acceptance does not establish model-workflow, receiving-platform, or formal AI Lab approval.']

## Source interface and delivery

Standalone source calls accept args=dict or args=a_JSON_object_string through each declared fixed callable.
These six operations return bounded numeric JSON, not output files. No output_dir is required for their standalone calls.
Native ToolExecutor execution authorizes task-relative inputs and preserves immutable input snapshots.
Fixed CPU entrypoints verify exact worker dependency pins, source, wheel, kernel and receipt hashes; scientific worker packages are not claimed installed in the host Python.
No runtime installation or compilation, network, GPU, user callbacks, shell commands or untrusted serialization is exposed.

### Current availability

tool_candidates_available_workflow_unverified

Prior independent numerical and native evidence is retained in immutable receipts, not recounted as new execution.
Shared SDK acceptance is recorded separately in the current candidate receipt; source availability alone is not execution proof.
Workflow validation: not_run. Model workflow validation: not_run. Platform validation: not_run.
Deployment status: not_deployed. Submission status: not_submitted. This candidate has not been deployed or submitted to the receiving AI Lab.
Registration status: candidate_pending_acceptance. Receiving lab approval: pending.
The new Skill document license and formal protocol version remain pending confirmation; no other Skill license is borrowed and no original project license or lab acceptance is asserted.
Original upstream source and license evidence remains separately bound to each operation.


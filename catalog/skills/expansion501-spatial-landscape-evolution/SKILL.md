---
id: expansion501_spatial_landscape_evolution
name: "Landscape material production and evolution"
description: "Choose one dimensioned terrain, carbonate, regolith, plate-flexure or passive-tracer operation; do not chain incompatible boundary/time conventions."
when_to_use: "Choose one dimensioned terrain, carbonate, regolith, plate-flexure or passive-tracer operation; do not chain incompatible boundary/time conventions."
tools:
  - GeoSpatialHillslopeDiffusionStep
  - GeoSpatialStreamPowerErosionStep
  - GeoMarineCarbonateAccretion
  - GeoRegolithProductionRate
  - GeoLithosphereFlexure
  - GeoSedimentTracerDiffusion
required_inputs:
  - Complete finite data and explicit declared units
  - Appropriate projected metric CRS unless the RPC contract specifies WGS84 output
constraints:
  - Source candidates only; no deployment or model workflow acceptance
  - No arbitrary modules, commands, functions, downloads or runtime installation
expected_outputs:
  - Closed JSON scientific results, units, empty artifacts and shared provenance
---

## When to use

Choose one dimensioned terrain, carbonate, regolith, plate-flexure or passive-tracer operation; do not chain incompatible boundary/time conventions.

## Required inputs

Load only the selected tool's closed schema. Use its synthetic asset as an input-shape example, not a real observation. Units are mandatory literal dictionaries. Raster origin is the upper-left outer corner; rows run north to south. Landlab guard nodes are boundaries, not extra model cells. Geometry is 2D and metric; no silent reprojection or repair.

## Workflow

1. Establish the scientific task, input units, CRS, physical domain and boundary conditions.
2. Choose one matching entry below, rather than running the entire tool list.
3. Check private-environment availability and stage the catalog before invoking the shared decorator.
4. Inspect output masks, units and provenance. For modelling steps, assess the explicitly described stability and mass-balance limits.
5. Hand off to independent CPU acceptance before scientific use or registration. Model/lab/platform acceptance is not established.

## Tool contracts

### GeoSpatialHillslopeDiffusionStep

Advance a gridded hillslope by one linear soil-creep diffusion step.

Fixed upstream: `landlab.components.LinearDiffuser.run_one_step` (landlab==2.11.0).

Input example: `assets/expansion501-spatial/GeoSpatialHillslopeDiffusionStep.json` (synthetic).

Constraints: One explicit method=simple/deposit=True step; dt*K/dx^2<=.2; all boundary nodes fixed to input, finite complete grid, at most 1024 nodes.

Independent numeric acceptance plan: Synthetic z=x^2+y^2 on 1 m grid: central 2D Laplacian=4; K=.1 m2/s,dt=.1 s -> centre elevation increase .04 m. Fixed guard nodes unchanged.

Distinctness: Terrain slope/curvature are diagnostics; this advances a PDE governing hillslope mass redistribution, not a derivative alias.

Source: https://github.com/landlab/landlab/blob/575b4b7b424e9c74c55fc5cf334fbec6bea92723/src/landlab/components/diffusion/diffusion.py

### GeoSpatialStreamPowerErosionStep

Advance detachment-limited stream-power incision with implicit Fastscape on fixed D8 drainage.

Fixed upstream: `landlab.components.FastscapeEroder.run_one_step` (landlab==2.11.0).

Input example: `assets/expansion501-spatial/GeoSpatialStreamPowerErosionStep.json` (synthetic).

Constraints: Fixed m=.5,n=1,threshold=0, K s^-1; D8 FlowAccumulator runoff_rate=1; no pit filling, uplift, transport or calibration; fixed boundaries.

Independent numeric acceptance plan: Synthetic one-core-node 3x3 DEM: centre z=1, west fixed outlet z=0, all other neighbors z=2, dx=1,A=1,K=.1,dt=1 -> implicit z_new=1/(1+.1)=10/11 m. Guard nodes unchanged.

Distinctness: Existing flow direction/accumulation produce routing only; fixed routing is a prerequisite here for a physically dimensioned fluvial-incision time step.

Source: https://github.com/landlab/landlab/blob/575b4b7b424e9c74c55fc5cf334fbec6bea92723/src/landlab/components/stream_power/fastscape_stream_power.py

### GeoMarineCarbonateAccretion

Advance spatial biogenic carbonate accretion under light attenuation in a fully submerged environment.

Fixed upstream: `landlab.components.CarbonateProducer.run_one_step` (landlab==2.11.0).

Input example: `assets/expansion501-spatial/GeoMarineCarbonateAccretion.json` (synthetic).

Constraints: m/year and years, light in microEinstein/m2/s; tidal_range=0 fixed; fully submerged throughout step; empirical ecology not a field-calibrated forecast.

Independent numeric acceptance plan: Uniform 10 m water depth: rate=.01*tanh(5*exp(-1)) m/year; dt=1 gives that thickness at each core. Surface light=0 gives exactly zero accretion. Outer nodes unchanged.

Distinctness: Biogenic sediment production is neither equilibrium mineral chemistry nor mechanical sediment erosion; this is a spatial depositional-evolution law.

Source: https://github.com/landlab/landlab/blob/575b4b7b424e9c74c55fc5cf334fbec6bea92723/src/landlab/components/carbonate/carbonate_producer.py

### GeoRegolithProductionRate

Compute soil-thickness-shielded bedrock-to-regolith production rates.

Fixed upstream: `landlab.components.ExponentialWeatherer.calc_soil_prod_rate` (landlab==2.11.0).

Input example: `assets/expansion501-spatial/GeoRegolithProductionRate.json` (synthetic).

Constraints: Landlab ExponentialWeatherer exact law, scalar calibration; output rate not timestep evolution; boundary values explicitly masked as undefined model rates.

Independent numeric acceptance plan: At H=0, H=Hstar and H=2Hstar, rates W0, W0/e and W0/e^2; e.g. W0=.01 m/year, Hstar=1 m gives .0036787944117 at H=1.

Distinctness: Terrain metrics and empirical chemical weathering indices do not calculate a thickness-dependent regolith-production field used by landscape models.

Source: https://github.com/landlab/landlab/blob/575b4b7b424e9c74c55fc5cf334fbec6bea92723/src/landlab/components/weathering/exponential_weathering.py

### GeoLithosphereFlexure

Calculate two-dimensional elastic lithospheric flexure from a gridded pressure increment.

Fixed upstream: `landlab.components.Flexure.update` (landlab==2.11.0).

Input example: `assets/expansion501-spatial/GeoLithosphereFlexure.json` (synthetic).

Constraints: Fixed method=flexure, n_procs=1, positive-down deflection, positive pressure loads, infinite elastic plate with zero loads beyond sampled rectangle; at most 256 nodes; no Airy mode alias.

Independent numeric acceptance plan: Zero load produces exactly zero deflection. For a single point-cell force F=p*dx^2: centre w(0)=F/(8*rho*g*alpha^2), alpha=(D/(rho*g))^(1/4), D=E*Te^3/[12*(1-.25^2)]; verify alpha definition against pinned component and isotropic symmetry.

Distinctness: Gravity forward modeling calculates acceleration from density; elastic flexure calculates mechanical plate displacement from applied load, not a gravity alias or slope-stability solver.

Source: https://github.com/landlab/landlab/blob/575b4b7b424e9c74c55fc5cf334fbec6bea92723/src/landlab/components/flexure/flexure.py

### GeoSedimentTracerDiffusion

Advect a passive soil property with depth-dependent hillslope sediment diffusion and prescribed bedrock production.

Fixed upstream: `landlab.components.ConcentrationTrackerForDiffusion.start_tracking + landlab.components.DepthDependentDiffuser.run_one_step + landlab.components.ConcentrationTrackerForDiffusion.stop_tracking` (landlab==2.11.0).

Input example: `assets/expansion501-spatial/GeoSedimentTracerDiffusion.json` (synthetic).

Constraints: Actual start_tracking -> diffuser.run_one_step -> stop_tracking sequence; no tracker.run_one_step call; closed guard ring, zero guard production, timestep bounds prevent clipping negative soil; no chemical reactions.

Independent numeric acceptance plan: Flat terrain gives zero sediment flux. H=1,C=2,Cbed=3,R=.01 m/year,dt=.1 year: Hnew=1.001,Cnew=2.003/1.001; nine 1 m2 core cells mass increases by .027 kg. Nonflat closed domain must conserve tracer except prescribed source.

Distinctness: Not a geochemical mixing/speciation wrapper: follows passive material concentration under spatially coupled hillslope flux and soil production.

Source: https://github.com/landlab/landlab/blob/575b4b7b424e9c74c55fc5cf334fbec6bea92723/src/landlab/components/concentration_tracker/concentration_tracker_for_diffusion.py

## Outputs and interpretation

JSON-only bounded results. `artifacts` is intentionally empty; shared `collection_contracts.operation` generates canonical input, implementation and output provenance hashes. No native artifact bridge is used. A returned diagnostic is not a calibrated model, a significance test or a receiving-AI-Lab certification.

## Errors

The shared ScientificToolError envelope is retained. Missing or mismatched pinned dependencies fail explicitly. Invalid units, CRS, dimensions, topology or physical state are rejected; missing values are not filled. Upstream numerical failures are errors rather than substituted algorithms. No arbitrary callback, shell or expression field exists.

## Sources and reproducibility

See `catalog/source_delivery/expansion501-20261026/groups/spatial/sources.json`, `license-evidence.json`, `requirements.txt` and per-project requirements. Direct pins are exact; the full transitive/native lock is still pending and must be built privately without downgrading the shared environment. Reviewed source commits and published distribution identity are recorded separately.

## Handoff and availability

- Source: source_revised_unverified; formal_eligible=false; acceptance_pending.
- Deployment: not_deployed.
- Submission: not_submitted.
- Contract/unit/numeric/workflow/platform validation: not_run.
- Model workflow: not_run.
- Receiving lab approval: pending; certification: not_established.
- Parent owns shared kind allowlist, staging, private CPU acceptance, integration and any later deployment.


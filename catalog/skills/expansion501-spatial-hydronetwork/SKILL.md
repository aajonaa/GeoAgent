---
id: expansion501_spatial_hydronetwork
name: "Hydrologic networks and surface-water steps"
description: "Choose hydrographic upscaling, HAND stage-storage, chi integration or a wet-grid overland-flow step; these are not interchangeable routing outputs."
when_to_use: "Choose hydrographic upscaling, HAND stage-storage, chi integration or a wet-grid overland-flow step; these are not interchangeable routing outputs."
tools:
  - GeoSpatialFlowNetworkUpscaleIHU
  - GeoSpatialFloodplainStageStorage
  - GeoSpatialChannelChiCoordinate
  - GeoSpatialOverlandFlowStep
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

Choose hydrographic upscaling, HAND stage-storage, chi integration or a wet-grid overland-flow step; these are not interchangeable routing outputs.

## Required inputs

Load only the selected tool's closed schema. Use its synthetic asset as an input-shape example, not a real observation. Units are mandatory literal dictionaries. Raster origin is the upper-left outer corner; rows run north to south. Landlab guard nodes are boundaries, not extra model cells. Geometry is 2D and metric; no silent reprojection or repair.

## Workflow

1. Establish the scientific task, input units, CRS, physical domain and boundary conditions.
2. Choose one matching entry below, rather than running the entire tool list.
3. Check private-environment availability and stage the catalog before invoking the shared decorator.
4. Inspect output masks, units and provenance. For modelling steps, assess the explicitly described stability and mass-balance limits.
5. Hand off to independent CPU acceptance before scientific use or registration. Model/lab/platform acceptance is not established.

## Tool contracts

### GeoSpatialFlowNetworkUpscaleIHU

Upscale a D8 drainage network using iterative hydrography-preserving IHU.

Fixed upstream: `pyflwdir.pyflwdir.FlwdirRaster.upscale` (pyflwdir==0.5.12).

Input example: `assets/expansion501-spatial/GeoSpatialFlowNetworkUpscaleIHU.json` (synthetic).

Constraints: Complete acyclic D8 only; 0 is a real terminal; no off-grid link coercion; square metric cells; dimensions divisible by scale; NumPy/Numba private-cache gate.

Independent numeric acceptance plan: Synthetic 4x4 all-east-then-south network, scale 2: coarse east-then-south topology [[1,4],[1,0]], cell side 2 m; final outlet source index 15. Check routing to one terminal independently of upstream outlet choices.

Distinctness: Existing D8 accumulation/delineation/Strahler tools retain grid resolution; IHU constructs a topologically consistent coarser network.

Source: https://github.com/Deltares/pyflwdir/blob/4e598e77611232bbf5fc620919d914de5bfd2cdb/pyflwdir/pyflwdir.py

### GeoSpatialFloodplainStageStorage

Calculate subcatchment flood storage-volume curves from prescribed HAND and stages.

Fixed upstream: `pyflwdir.pyflwdir.FlwdirRaster.ucat_volume` (pyflwdir==0.5.12).

Input example: `assets/expansion501-spatial/GeoSpatialFloodplainStageStorage.json` (synthetic).

Constraints: HAND/outlets supplied, not recomputed; all cells covered; stage elevations relative to each outlet; independent subcatchments, no backwater or flood connectivity solution.

Independent numeric acceptance plan: Synthetic cells with areas 4 m2 and HAND [3,1,0] draining to index 2: stages [1,2,4] give [4,12,32] m3 by sum(area*max(stage-HAND,0)).

Distinctness: HAND terrain metric and catchment delineation do not provide a stage-dependent storage-volume relation; no hydrodynamic inundation claim.

Source: https://github.com/Deltares/pyflwdir/blob/4e598e77611232bbf5fc620919d914de5bfd2cdb/pyflwdir/pyflwdir.py

### GeoSpatialChannelChiCoordinate

Integrate the channel chi coordinate using true D8 link lengths and a fixed reference concavity.

Fixed upstream: `landlab.components.ChiFinder.calculate_chi` (landlab==2.11.0).

Input example: `assets/expansion501-spatial/GeoSpatialChannelChiCoordinate.json` (synthetic).

Constraints: Reference concavity=.5; use_true_dx=True; output null exactly at upstream hillslope mask, distinct from input NoData; routing unchanged and no depressions filled.

Independent numeric acceptance plan: Independent path integral: when all contributing path nodes have A=A0, chi increments equal physical path lengths; a two-link 1 m path is chi=2 m. Also chi scales as sqrt(A0) with fixed area/routing. Masks must exclude nonchannels rather than report them as valid zero.

Distinctness: Drainage distance is unweighted path length; chi integrates (A0/A)^.5 and normalizes longitudinal profiles by drainage area.

Source: https://github.com/landlab/landlab/blob/575b4b7b424e9c74c55fc5cf334fbec6bea92723/src/landlab/components/chi_index/channel_chi.py

### GeoSpatialOverlandFlowStep

Advance shallow surface water with the de Almeida local-inertial overland-flow solver.

Fixed upstream: `landlab.components.OverlandFlow.run_one_step` (landlab==2.11.0).

Input example: `assets/expansion501-spatial/GeoSpatialOverlandFlowStep.json` (synthetic).

Constraints: Initially wet, zero initial discharge, h_init=0, steep_slopes=False, alpha=.7,theta=.8; CFL capped; Manning n units s/m^(1/3); links include coordinate endpoints, not a misleading cell raster.

Independent numeric acceptance plan: Flat closed wet grid h=.1 m, rainfall 1e-5 m/s, dt=.1 s: every core depth=.100001 m and every link q=0. Boundary guard values retained. Initial h_init=0 prevents hidden added water.

Distinctness: Least-cost/drainage routing follows topography without momentum or storage; this solves dynamic shallow-water flux/depth for one bounded physical step.

Source: https://github.com/landlab/landlab/blob/575b4b7b424e9c74c55fc5cf334fbec6bea92723/src/landlab/components/overland_flow/generate_overland_flow_deAlmeida.py

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


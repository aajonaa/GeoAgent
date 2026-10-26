---
id: expansion501_spatial_groundwater
name: "Groundwater budgets and aquifer analysis"
description: "Read a bounded MODFLOW budget, calculate geometry-aware discharge/transmissivity, or advance a closed shallow aquifer with an explicit physical state."
when_to_use: "Read a bounded MODFLOW budget, calculate geometry-aware discharge/transmissivity, or advance a closed shallow aquifer with an explicit physical state."
tools:
  - GeoSpatialGroundwaterZoneBudget
  - GeoSpatialDarcySpecificDischarge
  - GeoSpatialScreenedTransmissivity
  - GeoSpatialUnconfinedGroundwaterStep
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

Read a bounded MODFLOW budget, calculate geometry-aware discharge/transmissivity, or advance a closed shallow aquifer with an explicit physical state.

## Required inputs

Load only the selected tool's closed schema. Use its synthetic asset as an input-shape example, not a real observation. Units are mandatory literal dictionaries. Raster origin is the upper-left outer corner; rows run north to south. Landlab guard nodes are boundaries, not extra model cells. Geometry is 2D and metric; no silent reprojection or repair.

## Workflow

1. Establish the scientific task, input units, CRS, physical domain and boundary conditions.
2. Choose one matching entry below, rather than running the entire tool list.
3. Check private-environment availability and stage the catalog before invoking the shared decorator.
4. Inspect output masks, units and provenance. For modelling steps, assess the explicitly described stability and mass-balance limits.
5. Hand off to independent CPU acceptance before scientific use or registration. Model/lab/platform acceptance is not established.

## Tool contracts

### GeoSpatialGroundwaterZoneBudget

Aggregate cell-by-cell MODFLOW flux records into inter-zone groundwater water budgets.

Fixed upstream: `flopy.utils.ZoneBudget.get_budget` (flopy==3.11.0).

Input example: `assets/expansion501-spatial/GeoSpatialGroundwaterZoneBudget.json` (synthetic).

Constraints: Read-only CBC <=2 MiB/128 records; positive NLAY full-array single precision little endian only, fixed terms; caller declares m3/s because classic CBC lacks unit metadata; no compact/MF6 records.

Independent numeric acceptance plan: Synthetic two-cell budget: WELLS [+3,-3] m3/s and right-face flux [3,0]. Zone1 FROM_WELLS=3, TO_ZONE_2=3; Zone2 FROM_ZONE_1=3, TO_WELLS=3; both residuals 0.

Distinctness: Not MODFLOW execution, hydraulic interpolation or polygon zonal statistics; conserves signed intercell and source/sink fluxes across model zones.

Source: https://github.com/modflowpy/flopy/blob/a43f79127d0383e5328a602e72faf9a9730c7d61/flopy/utils/zonbud.py

### GeoSpatialDarcySpecificDischarge

Convert fully saturated model face volumetric fluxes to Darcy specific discharge on each staggered face.

Fixed upstream: `flopy.utils.postprocessing.get_specific_discharge` (flopy==3.11.0).

Input example: `assets/expansion501-spatial/GeoSpatialDarcySpecificDischarge.json` (synthetic).

Constraints: Fully saturated active cells only; explicit extended face arrays; rows north-to-south, layers top-to-bottom; no implicit south/down sign conversion; no MODFLOW executable.

Independent numeric acceptance plan: dx=2 m, thickness=5 m: side areas 10 m2 and horizontal area 4 m2; Qeast=20,Qnorth=30,Qup=16 m3/s yield q=(2,3,4) m/s on all faces.

Distinctness: Hydraulic-gradient/flow solvers do not convert existing cell-budget face fluxes using saturated cross-sectional geometry; this is postprocessing, not generic vector decomposition.

Source: https://github.com/modflowpy/flopy/blob/a43f79127d0383e5328a602e72faf9a9730c7d61/flopy/utils/postprocessing.py

### GeoSpatialScreenedTransmissivity

Calculate layer-specific saturated transmissivity intersecting screened well intervals.

Fixed upstream: `flopy.utils.postprocessing.get_transmissivities` (flopy==3.11.0).

Input example: `assets/expansion501-spatial/GeoSpatialScreenedTransmissivity.json` (synthetic).

Constraints: Screens entirely inside model; reject dry layers and nonintersecting screens to avoid upstream closest-layer fallback; no well-loss or pumping-test inversion.

Independent numeric acceptance plan: Two 5 m saturated screened layers, K=[.01,.002] m/s: transmissivities [.05,.01] m2/s and total .06 m2/s; shortened 3 m first-layer interval gives .03 m2/s.

Distinctness: Not scalar transmissivity multiplication alone: intersects multilayer geology, well screen and saturation heads at explicit model cells.

Source: https://github.com/modflowpy/flopy/blob/a43f79127d0383e5328a602e72faf9a9730c7d61/flopy/utils/postprocessing.py

### GeoSpatialUnconfinedGroundwaterStep

Advance shallow unconfined groundwater storage with the Dupuit-percolator approximation.

Fixed upstream: `landlab.components.GroundwaterDupuitPercolator.run_one_step` (landlab==2.11.0).

Input example: `assets/expansion501-spatial/GeoSpatialUnconfinedGroundwaterStep.json` (synthetic).

Constraints: base<head<top; closed edges; regularization_f=.01; one bounded dt with diffusion/advection/recharge bounds; shallow Dupuit approximation, not 3D Richards/MODFLOW.

Independent numeric acceptance plan: Flat closed aquifer with uniform 2 m head, base 0, land 10 and no recharge remains head=2 m and thickness=2 m exactly; no lateral gradient gives zero transport.

Distinctness: Darcy postprocessing and well transmissivity are static analyses; this evolves distributed unconfined storage with recharge and nonlinear saturated thickness.

Source: https://github.com/landlab/landlab/blob/575b4b7b424e9c74c55fc5cf334fbec6bea92723/src/landlab/components/groundwater/dupuit_percolator.py

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


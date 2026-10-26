---
id: expansion501_spatial_landscape_evolution
name: "Landscape material production and evolution"
description: "CPU-accepted scientific operations for Landscape material production and evolution"
tools:
  - GeoSpatialHillslopeDiffusionStep
  - GeoSpatialStreamPowerErosionStep
  - GeoMarineCarbonateAccretion
  - GeoRegolithProductionRate
  - GeoLithosphereFlexure
  - GeoSedimentTracerDiffusion
---

# Landscape material production and evolution

## When to use

Select only an available operation whose scientific assumptions match the task.

## Required inputs

Use the closed native input schema, explicit units, source data, coordinate system and time conventions.

## Workflow

1. Inspect source provenance and scientific applicability.
2. Call the selected native operation with its exact schema.
3. Inspect numerical results, units, errors and source/input/output hashes.
4. Deliver only actual validated results and their scientific limitations.

## Available operations

- `GeoSpatialHillslopeDiffusionStep`: Advance a gridded hillslope by one linear soil-creep diffusion step.
- `GeoSpatialStreamPowerErosionStep`: Advance detachment-limited stream-power incision with implicit Fastscape on fixed D8 drainage.
- `GeoMarineCarbonateAccretion`: Advance spatial biogenic carbonate accretion under light attenuation in a fully submerged environment.
- `GeoRegolithProductionRate`: Compute soil-thickness-shielded bedrock-to-regolith production rates.
- `GeoLithosphereFlexure`: Calculate two-dimensional elastic lithospheric flexure from a gridded pressure increment.
- `GeoSedimentTracerDiffusion`: Advect a passive soil property with depth-dependent hillslope sediment diffusion and prescribed bedrock production.

## Constraints

Offline CPU-only execution. Never install packages, download data or substitute generated algorithms during a call.
Fixed dependency environments retain the original upstream algorithms, exact versions and license notices.
Do not infer mineral presence, grade or reserves from indirect imagery indices.

## Expected outputs

Schema-validated numerical JSON, declared units, original evidence and declared artifacts with content hashes.

## Source interface and delivery

Use the native function input object. Standalone examples are in catalog/source_delivery/examples.json.
Runtime profiles bind the source, interpreter, exact dependency lock and CPU execution evidence.

### Current availability

`tool_candidates_available_workflow_unverified`

The listed operations passed internal CPU acceptance; this is not model-driven workflow acceptance or AI Lab approval.
Scientific platform validation: `not_run`. Lab submission: `not_submitted`.
Deployment, Git and browser acceptance are recorded separately in release receipts.

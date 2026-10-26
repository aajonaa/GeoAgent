---
id: expansion501_spatial_hydronetwork
name: "Hydrologic networks and surface-water steps"
description: "CPU-accepted scientific operations for Hydrologic networks and surface-water steps"
tools:
  - GeoSpatialFlowNetworkUpscaleIHU
  - GeoSpatialFloodplainStageStorage
  - GeoSpatialChannelChiCoordinate
  - GeoSpatialOverlandFlowStep
---

# Hydrologic networks and surface-water steps

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

- `GeoSpatialFlowNetworkUpscaleIHU`: Upscale a D8 drainage network using iterative hydrography-preserving IHU.
- `GeoSpatialFloodplainStageStorage`: Calculate subcatchment flood storage-volume curves from prescribed HAND and stages.
- `GeoSpatialChannelChiCoordinate`: Integrate the channel chi coordinate using true D8 link lengths and a fixed reference concavity.
- `GeoSpatialOverlandFlowStep`: Advance shallow surface water with the de Almeida local-inertial overland-flow solver.

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

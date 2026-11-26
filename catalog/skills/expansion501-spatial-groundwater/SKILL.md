---
id: expansion501_spatial_groundwater
name: "Groundwater budgets and aquifer analysis"
description: "CPU-accepted scientific operations for Groundwater budgets and aquifer analysis"
tools:
  - GeoSpatialGroundwaterZoneBudget
  - GeoSpatialDarcySpecificDischarge
  - GeoSpatialScreenedTransmissivity
  - GeoSpatialUnconfinedGroundwaterStep
---

# Groundwater budgets and aquifer analysis

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

- `GeoSpatialGroundwaterZoneBudget`: Aggregate cell-by-cell MODFLOW flux records into inter-zone groundwater water budgets.
- `GeoSpatialDarcySpecificDischarge`: Convert fully saturated model face volumetric fluxes to Darcy specific discharge on each staggered face.
- `GeoSpatialScreenedTransmissivity`: Calculate layer-specific saturated transmissivity intersecting screened well intervals.
- `GeoSpatialUnconfinedGroundwaterStep`: Advance shallow unconfined groundwater storage with the Dupuit-percolator approximation.

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

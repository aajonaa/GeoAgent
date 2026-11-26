---
id: expansion501_geophysics_gravity_reference
name: "Gravity reference reduction and density interpretation"
description: "CPU-accepted scientific operations for Gravity reference reduction and density interpretation"
tools:
  - GeoGravityTesseroid
  - GeoGravityNormalEllipsoid
  - GeoGravityBouguerSlab
  - GeoCrustAiryMoho
  - GeoGravityDensityInversion
---

# Gravity reference reduction and density interpretation

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

- `GeoGravityTesseroid`: Forward-model finite spherical density-contrast volumes with potential and radial-down acceleration bundled.
- `GeoGravityNormalEllipsoid`: Calculate normal gravity including centrifugal acceleration at WGS84 geodetic positions and ellipsoidal heights.
- `GeoGravityBouguerSlab`: Calculate explicit-density land and bathymetric infinite-slab gravity corrections.
- `GeoCrustAiryMoho`: Estimate Airy-compensated Moho depth from basement relief and explicitly supplied surface layers.
- `GeoGravityDensityInversion`: Recover bounded density contrast from upward-positive gravity anomalies on a supplied subsurface tensor mesh.

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

---
id: expansion501_geophysics_potential_interpretation
name: "Potential-field continuation and source interpretation"
description: "CPU-accepted scientific operations for Potential-field continuation and source interpretation"
tools:
  - GeoPotentialEulerSourceLocation
  - GeoPotentialEquivalentSources
  - GeoPotentialUpwardContinuation
  - GeoMagneticReductionToPole
  - GeoPotentialEdgeAttributes
  - GeoMagneticSusceptibilityInversion
---

# Potential-field continuation and source interpretation

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

- `GeoPotentialEulerSourceLocation`: Estimate one ideal-source location and constant base level from field values and all three measured spatial derivatives.
- `GeoPotentialEquivalentSources`: Fit damped equivalent sources to irregular-altitude harmonic field measurements and predict specified positions.
- `GeoPotentialUpwardContinuation`: Continue a regular planar potential-field grid upward with the harmonic spectral transfer.
- `GeoMagneticReductionToPole`: Transform a planar magnetic anomaly to pole-equivalent inducing-field and magnetization directions.
- `GeoPotentialEdgeAttributes`: Compute bundled total-gradient amplitude and tilt of a complete planar potential-field anomaly grid.
- `GeoMagneticSusceptibilityInversion`: Recover bounded induced-only scalar susceptibility from TMI anomalies using a supplied inducing field.

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

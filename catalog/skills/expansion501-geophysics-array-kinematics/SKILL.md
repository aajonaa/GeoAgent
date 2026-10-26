---
id: expansion501_geophysics_array_kinematics
name: "Seismic array kinematics and waveform interpretation"
description: "CPU-accepted scientific operations for Seismic array kinematics and waveform interpretation"
tools:
  - GeoSeismicArrayBeamforming
  - GeoSeismicNMO
  - GeoSeismicComplexAttributes
  - GeoSeismicWindowCoherence
  - GeoSeismicArrayStrainRotation
  - GeoSeismicRadiationPattern
---

# Seismic array kinematics and waveform interpretation

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

- `GeoSeismicArrayBeamforming`: Estimate apparent horizontal slowness, backazimuth and beam coherence from a synchronized local station array.
- `GeoSeismicNMO`: Correct CMP hyperbolic normal moveout with supplied time-dependent NMO velocity and explicit interpolation support.
- `GeoSeismicComplexAttributes`: Return trace envelope, phase and a support-masked Scheuer-Oldenburg interval-frequency attribute.
- `GeoSeismicWindowCoherence`: Measure direct Marfurt coherence inside a supplied 3-D survey window, without the defective high-level wrapper.
- `GeoSeismicArrayStrainRotation`: Estimate small dynamic ground strain/rotation from synchronized 3C array displacement and supplied measurement error.
- `GeoSeismicRadiationPattern`: Calculate normalized P/S radiation vectors of a general symmetric Cartesian seismic moment tensor.

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

---
id: expansion501_geology_crystal_interfaces
name: "Crystal habit, surfaces and coherent interfaces"
description: "CPU-accepted scientific operations for Crystal habit, surfaces and coherent interfaces"
tools:
  - Geo500WulffCrystalHabit
  - Geo500CoherentMineralInterfaceMatch
  - Geo500MineralSurfaceTerminations
---

# Crystal habit, surfaces and coherent interfaces

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

- `Geo500WulffCrystalHabit`: Construct equilibrium crystal habit from indexed relative surface energies.
- `Geo500CoherentMineralInterfaceMatch`: Find the lowest-area coherent superlattice match between two mineral surface nets.
- `Geo500MineralSurfaceTerminations`: Generate distinct unrelaxed crystal slab terminations for a Miller plane.

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

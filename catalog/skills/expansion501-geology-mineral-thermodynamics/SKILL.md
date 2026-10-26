---
id: expansion501_geology_mineral_thermodynamics
name: "Mineral formula, reactions and thermodynamic evidence"
description: "CPU-accepted operations for Mineral formula, reactions and thermodynamic evidence; use only the listed available subset."
tools:
  - Geo500MineralOxygenBasisFormula
  - Geo500MineralNeutronContrast
---

# Mineral formula, reactions and thermodynamic evidence

## When to use

Select one of the available scientific operations below. Do not substitute an unavailable operation.

## Required inputs

Use each operation's closed input schema, declared units, source data and explicit spatial/temporal conventions.

## Workflow

1. Check the scientific assumptions, units and input provenance.
2. Select the listed native tool and use its exact parameter schema.
3. Inspect numeric outputs, uncertainty, artifact hashes and error state.
4. Report only executed results; do not infer mineral presence, grade or reserves from image proxies.

## Available operations

- `Geo500MineralOxygenBasisFormula`: Recalculate measured simple-oxide mineral analyses to an explicit fixed oxygen basis.
- `Geo500MineralNeutronContrast`: Compute tabulated neutron scattering contrast and macroscopic attenuation of mineral compositions.

## Constraints

Offline CPU execution only. No downloads, package installation, arbitrary commands or generated algorithms during a tool call.
Retain input/output schemas, upstream algorithms, dependency pins and explicit error handling.

## Expected outputs

Schema-validated numeric JSON, declared units, file artifacts where applicable and source/input/output provenance.

## Source interface and delivery

Call the native function with its declared input object. Standalone examples are in catalog/source_delivery/examples.json.
The implementation and dependency lock remain bound to the recorded upstream source.

### Current availability

`tool_candidates_available_workflow_unverified`

Only the operations listed above passed this release's internal CPU acceptance. This does not establish complete model-driven workflow validation or AI Lab approval.
Scientific platform validation: `not_run`. Lab submission: `not_submitted`.
Deployment and Git status are recorded separately in the release receipt.

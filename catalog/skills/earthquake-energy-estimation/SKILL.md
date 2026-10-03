---
name: "earthquake-energy-estimation"
description: "Convert earthquake moment magnitude to an approximate radiated-energy estimate with explicit units and limitations."
---

# Earthquake Energy Estimation

## Goal

{'capability': 'earthquake-energy-estimation', 'description': 'Convert earthquake moment magnitude to an approximate radiated-energy estimate with explicit units and limitations.', 'target_state': ['validated-earthquake-energy-estimation-result']}

## Inputs

~~~json
[
  {
    "id": "magnitude",
    "semantic_type": "Parameter",
    "data_type": "moment magnitude Mw",
    "required": true,
    "description": "Earthquake moment magnitude."
  }
]
~~~

## Outputs

~~~json
[
  {
    "id": "result",
    "semantic_type": "Scalar|Table",
    "data_type": "validated geoscience result",
    "description": "A numeric or structured result with provenance.",
    "expected_format": "JSON"
  }
]
~~~

## Method

Choose steps from observations and the actual goal; this is guidance, not a mandatory fixed chain.
After loading this skill, use the exposed native tool schemas, sourced directly from catalog/registry.json. Do not try to read repository files in the user task directory.
Call the original structured implementation. Do not use the retired asset_catalog execution route.

~~~json
{
  "type": "sequential",
  "steps": [
    {
      "id": "step_1",
      "operation": "Validate magnitude and estimate radiated energy",
      "required": true,
      "depends_on": [],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Parameter",
        "Scalar|Parameter"
      ],
      "outputs": [
        "Scalar"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "GeoMagnitudeToEnergy"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "GeoMagnitudeToEnergy"
      ],
      "method_notes": [
        "Validate magnitude input and estimate earthquake radiated energy."
      ]
    }
  ]
}
~~~

## Dependencies

~~~json
{
  "tools": [
    "GeoMagnitudeToEnergy"
  ],
  "unavailable": [],
  "tool_references": [
    "GeoMagnitudeToEnergy"
  ],
  "method_notes": [
    "Validate magnitude input and estimate earthquake radiated energy."
  ]
}
~~~

Environment: Python 3.12 with requirements-source-tools.txt. Caller supplies licensed input data.
A tool reference is not proof that its implementation is available. Consult every referenced tool's source_interface status.

## Success criteria

Required tool calls return valid structured results; output files exist; units and reported values match those results.
Check the requested goal, not merely process completion. No source-revision or agent end-to-end tests have run.

## Failure handling

Correct parameters or missing data from the error, then retry only after changing the cause.
Never invent unavailable algorithms, datasets or scientific results. Ask for missing prerequisites if no supported path remains.

## Publication

Draft only. Provider ownership, license, official schema validation and version-locked protocol repository remain unresolved.

## Direct tool references

These are suggestions, not an execution order or permission to run unavailable tools.

- GeoMagnitudeToEnergy

<!-- source-delivery:start -->
## Source interface and delivery

This is the same skill document loaded by the project agent. Tool references are alternatives or supporting operations, not an enforced execution order.

### Calling contract

Inspect the selected tool's input_schema, output_schema, limitations and source_interface before calling it. Supply an object with the documented units and coordinate system. Do not replace missing data with invented values or treat a failed call as evidence.

Inside the agent, call the disclosed native function names directly with schema-valid object arguments. Outside the agent, use the original callable and bound arguments recorded in source_interface.entrypoint. Both execute the same source implementation; no retired execution adapter is required.

File-producing source calls require a caller-selected output directory; inputs may be absolute paths in trusted direct Python use. The agent transport instead requires workspace-relative input paths. Neither direct Python execution nor the standalone transport is an OS security sandbox.

### Dependency status

Source-interface candidates (consult the acceptance report, not this list, for tested availability):
- `GeoMagnitudeToEnergy`

Unresolved or unavailable references:
- None recorded.

### Current availability

Status: `tool_candidates_available_workflow_unverified`.

All recorded tool references have source-interface candidates. This does not mean the complete skill workflow has passed acceptance.

A reference is not proof that every operation in this skill is available. Choose a supported method, request the missing input, or state the limitation; do not silently skip a scientifically necessary operation.

### Result acceptance

Check the actual result against the chosen tool's output contract, input provenance, units, scientific limitations and requested deliverables. Confirm that referenced output files exist. Report failed or unsupported operations explicitly. Synthetic tool checks do not constitute scientific certification or an end-to-end acceptance test of this skill.

<!-- source-delivery:end -->

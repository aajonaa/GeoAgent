---
name: "earthquake-event-model-sampling"
description: "Retrieve a frozen USGS event and look up its precomputed LITHO1.0/SEMUCB-WM1 join. No live or arbitrary-coordinate sampling."
---

# Earthquake Event and Pinned Model Lookup

## Goal

{'capability': 'earthquake-event-model-sampling', 'description': 'Join a selected USGS event with nearest pinned Earth structure model samples.', 'target_state': ['validated-earthquake-event-model-sampling-result']}

## Inputs

~~~json
[
  {
    "id": "query_or_resource",
    "semantic_type": "Table|Parameter",
    "data_type": "authoritative resource locator",
    "required": true,
    "description": "The benchmark locator or structured task parameters."
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
      "operation": "Retrieve the selected earthquake event",
      "required": true,
      "depends_on": [],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Parameter"
      ],
      "outputs": [
        "Record|Table"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "DeepEarthGetUSGSEvent"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "DeepEarthGetUSGSEvent"
      ],
      "method_notes": [
        "Retrieve one earthquake catalog record by event identifier."
      ]
    },
    {
      "id": "step_2",
      "operation": "Sample nearby Earth structure model nodes",
      "required": true,
      "depends_on": [
        "step_1"
      ],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Record|Parameter"
      ],
      "outputs": [
        "Table"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "DeepEarthSampleEventModels"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "DeepEarthSampleEventModels"
      ],
      "method_notes": [
        "Compatibility discovery group only; candidates are NOT substitutes. Sample Earth structure models at an earthquake location and depth."
      ]
    }
  ]
}
~~~

## Dependencies

~~~json
{
  "tools": [
    "DeepEarthGetUSGSEvent",
    "DeepEarthSampleEventModels"
  ],
  "unavailable": [
    "DeepEarthGetUSGSEvent",
    "DeepEarthSampleEventModels"
  ],
  "tool_references": [
    "DeepEarthGetUSGSEvent",
    "DeepEarthSampleEventModels"
  ],
  "method_notes": [
    "Retrieve one earthquake catalog record by event identifier.",
    "Look up a precomputed event/model join by event ID; not arbitrary-coordinate sampling."
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

- DeepEarthGetUSGSEvent
- DeepEarthSampleEventModels

<!-- source-delivery:start -->
## Source interface and delivery

This is the same skill document loaded by the project agent. Tool references are alternatives or supporting operations, not an enforced execution order.

### Calling contract

Inspect the selected tool's input_schema, output_schema, limitations and source_interface before calling it. Supply an object with the documented units and coordinate system. Do not replace missing data with invented values or treat a failed call as evidence.

Inside the agent, call the disclosed native function names directly with schema-valid object arguments. Outside the agent, use the original callable and bound arguments recorded in source_interface.entrypoint. Both execute the same source implementation; no retired execution adapter is required.

File-producing source calls require a caller-selected output directory; inputs may be absolute paths in trusted direct Python use. The agent transport instead requires workspace-relative input paths. Neither direct Python execution nor the standalone transport is an OS security sandbox.

### Dependency status

Source-interface candidates (consult the acceptance report, not this list, for tested availability):
- None recorded.

Unresolved or unavailable references:
- `DeepEarthGetUSGSEvent`: 实现绑定特定数据快照，尚无可交付的数据路径、版本、字段和授权约定。
- `DeepEarthSampleEventModels`: 实现绑定特定数据快照，尚无可交付的数据路径、版本、字段和授权约定。

### Current availability

Status: `blocked_no_source_candidates`.

No recorded tool reference currently has an available source-interface candidate. Treat this skill as method documentation, not an executable workflow.

A reference is not proof that every operation in this skill is available. Choose a supported method, request the missing input, or state the limitation; do not silently skip a scientifically necessary operation.

### Result acceptance

Check the actual result against the chosen tool's output contract, input provenance, units, scientific limitations and requested deliverables. Confirm that referenced output files exist. Report failed or unsupported operations explicitly. Synthetic tool checks do not constitute scientific certification or an end-to-end acceptance test of this skill.

<!-- source-delivery:end -->

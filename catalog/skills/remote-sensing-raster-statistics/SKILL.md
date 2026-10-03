---
name: "remote-sensing-raster-statistics"
description: "Aggregate, compare, and transform raster values across scenes, bands, and regions."
---

# Remote-Sensing Raster Statistics

## Goal

{'capability': 'remote-sensing-raster-statistics', 'description': 'Aggregate, compare, and transform raster values across scenes, bands, and regions.', 'target_state': ['validated-remote-sensing-raster-statistics-result']}

## Inputs

~~~json
[
  {
    "id": "raster_inputs",
    "semantic_type": "Raster|Parameter",
    "data_type": "GeoTIFF or raster resource group",
    "required": true,
    "description": "Raster assets and their band/variable metadata."
  }
]
~~~

## Outputs

~~~json
[
  {
    "id": "artifact",
    "semantic_type": "Raster|Vector|Table",
    "data_type": "validated spatial artifact or summary",
    "description": "Spatial output, summary, or rendered artifact.",
    "expected_format": "JSON or registered artifact"
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
      "operation": "Aggregate compatible scenes or bands",
      "required": true,
      "depends_on": [],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Raster|Table"
      ],
      "outputs": [
        "Scalar|Raster|Table"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "RemoteSensingBatchImageMean",
          "RemoteSensingBatchImageSum",
          "RemoteSensingMean",
          "RemoteSensingTiffAverage"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "RemoteSensingBatchImageMean",
        "RemoteSensingBatchImageSum",
        "RemoteSensingMean",
        "RemoteSensingTiffAverage"
      ],
      "method_notes": [
        "Aggregate finite raster values or aligned scenes with a statistic."
      ]
    },
    {
      "id": "step_2",
      "operation": "Calculate differences, ratios, or other raster arithmetic",
      "required": false,
      "depends_on": [
        "step_1"
      ],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Raster",
        "Raster|Scalar"
      ],
      "outputs": [
        "Raster",
        "Raster|Scalar"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "RemoteSensingTiffDifference",
          "RemoteSensingDifference",
          "RemoteSensingDivision",
          "RemoteSensingSubtract"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "DeepTimeRasterAlgebra",
        "CCSRasterAlgebra",
        "RemoteSensingTiffDifference",
        "RemoteSensingDifference",
        "RemoteSensingSubtract",
        "RemoteSensingDivision"
      ],
      "method_notes": [
        "Apply reusable arithmetic or mask operations to raster or scalar inputs."
      ]
    }
  ]
}
~~~

## Dependencies

~~~json
{
  "tools": [
    "RemoteSensingBatchImageMean",
    "RemoteSensingBatchImageSum",
    "RemoteSensingMean",
    "RemoteSensingTiffAverage",
    "RemoteSensingTiffDifference",
    "RemoteSensingDifference",
    "RemoteSensingDivision",
    "RemoteSensingSubtract"
  ],
  "unavailable": [],
  "tool_references": [
    "RemoteSensingBatchImageMean",
    "RemoteSensingBatchImageSum",
    "RemoteSensingMean",
    "RemoteSensingTiffAverage",
    "DeepTimeRasterAlgebra",
    "CCSRasterAlgebra",
    "RemoteSensingTiffDifference",
    "RemoteSensingDifference",
    "RemoteSensingSubtract",
    "RemoteSensingDivision"
  ],
  "method_notes": [
    "Aggregate finite raster values or aligned scenes with a statistic.",
    "Apply reusable arithmetic or mask operations to raster or scalar inputs."
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

- RemoteSensingBatchImageMean
- RemoteSensingBatchImageSum
- RemoteSensingMean
- RemoteSensingTiffAverage
- RemoteSensingTiffDifference
- RemoteSensingDifference
- RemoteSensingDivision
- RemoteSensingSubtract

<!-- source-delivery:start -->
## Source interface and delivery

This is the same skill document loaded by the project agent. Tool references are alternatives or supporting operations, not an enforced execution order.

### Calling contract

Inspect the selected tool's input_schema, output_schema, limitations and source_interface before calling it. Supply an object with the documented units and coordinate system. Do not replace missing data with invented values or treat a failed call as evidence.

Inside the agent, call the disclosed native function names directly with schema-valid object arguments. Outside the agent, use the original callable and bound arguments recorded in source_interface.entrypoint. Both execute the same source implementation; no retired execution adapter is required.

File-producing source calls require a caller-selected output directory; inputs may be absolute paths in trusted direct Python use. The agent transport instead requires workspace-relative input paths. Neither direct Python execution nor the standalone transport is an OS security sandbox.

### Dependency status

Source-interface candidates (consult the acceptance report, not this list, for tested availability):
- `RemoteSensingBatchImageMean`
- `RemoteSensingBatchImageSum`
- `RemoteSensingMean`
- `RemoteSensingTiffAverage`
- `RemoteSensingTiffDifference`
- `RemoteSensingDifference`
- `RemoteSensingDivision`
- `RemoteSensingSubtract`

Unresolved or unavailable references:
- None recorded.

### Current availability

Status: `tool_candidates_available_workflow_unverified`.

All recorded tool references have source-interface candidates. This does not mean the complete skill workflow has passed acceptance.

A reference is not proof that every operation in this skill is available. Choose a supported method, request the missing input, or state the limitation; do not silently skip a scientifically necessary operation.

### Result acceptance

Check the actual result against the chosen tool's output contract, input provenance, units, scientific limitations and requested deliverables. Confirm that referenced output files exist. Report failed or unsupported operations explicitly. Synthetic tool checks do not constitute scientific certification or an end-to-end acceptance test of this skill.

<!-- source-delivery:end -->

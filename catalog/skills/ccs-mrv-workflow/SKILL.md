---
name: "ccs-mrv-workflow"
description: "Check, standardize, validate, relate, overlay, and render synthetic CCS MRV spatial assets."
---

# CCS MRV Spatial Workflow

## Goal

{'capability': 'ccs-mrv-workflow', 'description': 'Check, standardize, validate, relate, overlay, and render synthetic CCS MRV spatial assets.', 'target_state': ['validated-ccs-mrv-workflow-result']}

## Inputs

~~~json
[
  {
    "id": "spatial_inputs",
    "semantic_type": "Vector|Raster|Parameter",
    "data_type": "geospatial assets or coordinates",
    "required": true,
    "description": "Spatial data, ROI, coordinates, or a resource locator."
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
      "operation": "Check and normalize CCS coordinate reference semantics",
      "required": true,
      "depends_on": [],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Parameter",
        "Vector|Raster|Parameter"
      ],
      "outputs": [
        "Scalar|Text",
        "Boolean|Table"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "CCSCheckCRSConsistency"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "GeoDecimalToDMS",
        "DeepTimeDecimalToDMS",
        "CCSDecimalToDMS",
        "GeoCheckCRSConsistency",
        "CCSCheckCRSConsistency"
      ],
      "method_notes": [
        "Normalize coordinate representation and validate CRS consistency."
      ]
    },
    {
      "id": "step_2",
      "operation": "Standardize and batch-copy CCS vector assets",
      "required": true,
      "depends_on": [
        "step_1"
      ],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Vector|Table"
      ],
      "outputs": [
        "Vector|Table"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "CCSStandardizeSpatialData",
          "CCSBatchVector"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "DeepTimeStandardizeSpatialData",
        "CCSStandardizeSpatialData",
        "DeepTimeBatchVector",
        "CCSBatchVector"
      ],
      "method_notes": [
        "Standardize and batch-copy vector layers into a reusable spatial representation."
      ]
    },
    {
      "id": "step_3",
      "operation": "Validate CCS geometries",
      "required": true,
      "depends_on": [
        "step_2"
      ],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Vector|Table"
      ],
      "outputs": [
        "Boolean|Table"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "CCSValidateSpatialData"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "DeepTimeValidateSpatialData",
        "CCSValidateSpatialData"
      ],
      "method_notes": [
        "Validate coordinate ranges, empty geometries, and duplicate features."
      ]
    },
    {
      "id": "step_4",
      "operation": "Select nearest CCS facilities",
      "required": false,
      "depends_on": [
        "step_3"
      ],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Vector|Parameter",
        "Vector"
      ],
      "outputs": [
        "Record|Table",
        "Vector|Table",
        "Table|Record"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "CCSNearestNeighbor"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "EnergyNearestFacility",
        "EnergyNearestMineralSite",
        "DeepTimeNearestNeighbor",
        "CCSNearestNeighbor"
      ],
      "method_notes": [
        "Select the nearest facility, feature, or related mineral site."
      ]
    },
    {
      "id": "step_5",
      "operation": "Generate CCS monitoring buffers",
      "required": false,
      "depends_on": [
        "step_3"
      ],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Vector|Parameter"
      ],
      "outputs": [
        "Vector"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "CCSBuffer"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "DeepTimeBuffer",
        "CCSBuffer"
      ],
      "method_notes": [
        "Generate point-buffer envelope features."
      ]
    },
    {
      "id": "step_6",
      "operation": "Overlay CCS assets and zones",
      "required": false,
      "depends_on": [
        "step_3"
      ],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Vector"
      ],
      "outputs": [
        "Vector|Table"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "CCSOverlay"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "DeepTimeOverlay",
        "CCSOverlay"
      ],
      "method_notes": [
        "Perform point-in-polygon or facility-zone overlay."
      ]
    },
    {
      "id": "step_7",
      "operation": "Render a CCS inspection map",
      "required": false,
      "depends_on": [],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Raster|Vector|Table"
      ],
      "outputs": [
        "Raster|Text"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "CCSRenderMap"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "DeepTimeRenderMap",
        "CCSRenderMap"
      ],
      "method_notes": [
        "Render a reproducible PNG and HTML inspection map."
      ]
    }
  ]
}
~~~

## Dependencies

Select from the direct tool references below. Use the current schemas and environment requirements; a list of tools is not an executable workflow.

Environment: Python 3.12 with requirements-source-tools.txt. Caller supplies licensed input data.
A tool reference is not proof that its implementation is available. Consult every referenced tool's source_interface status.

## Success criteria

Required tool calls return valid structured results; output files exist; units and reported values match those results.
Check the requested goal, not merely process completion. Consult the current acceptance report for individual tool tests; whole-Skill validation remains a separate requirement.

## Failure handling

Correct parameters or missing data from the error, then retry only after changing the cause.
Never invent unavailable algorithms, datasets or scientific results. Ask for missing prerequisites if no supported path remains.

## Publication

Draft only. Provider ownership, license, official schema validation and version-locked protocol repository remain unresolved.

## Direct tool references

These are suggestions, not an execution order or permission to run unavailable tools.

- CCSCheckCRSConsistency
- CCSStandardizeSpatialData
- CCSBatchVector
- CCSValidateSpatialData
- CCSNearestNeighbor
- CCSBuffer
- CCSOverlay
- CCSRenderMap

<!-- source-delivery:start -->
## Source interface and delivery

This is the same skill document loaded by the project agent. Tool references are alternatives or supporting operations, not an enforced execution order.

### Calling contract

Inspect the selected tool's input_schema, output_schema, limitations and source_interface before calling it. Supply an object with the documented units and coordinate system. Do not replace missing data with invented values or treat a failed call as evidence.

Inside the agent, call the disclosed native function names directly with schema-valid object arguments. Outside the agent, use the original callable and bound arguments recorded in source_interface.entrypoint. Both execute the same source implementation; no retired execution adapter is required.

File-producing source calls require a caller-selected output directory; inputs may be absolute paths in trusted direct Python use. The agent transport instead requires workspace-relative input paths. Neither direct Python execution nor the standalone transport is an OS security sandbox.

### Dependency status

Source-interface candidates (consult the acceptance report, not this list, for tested availability):
- `CCSCheckCRSConsistency`
- `CCSStandardizeSpatialData`
- `CCSBatchVector`
- `CCSValidateSpatialData`
- `CCSNearestNeighbor`
- `CCSBuffer`
- `CCSOverlay`
- `CCSRenderMap`

Unresolved or unavailable references:
- None recorded.

### Current availability

Status: `tool_candidates_available_workflow_unverified`.

All recorded tool references have source-interface candidates. This does not mean the complete skill workflow has passed acceptance.

A reference is not proof that every operation in this skill is available. Choose a supported method, request the missing input, or state the limitation; do not silently skip a scientifically necessary operation.

### Result acceptance

Check the actual result against the chosen tool's output contract, input provenance, units, scientific limitations and requested deliverables. Confirm that referenced output files exist. Report failed or unsupported operations explicitly. Synthetic tool checks do not constitute scientific certification or an end-to-end acceptance test of this skill.

<!-- source-delivery:end -->

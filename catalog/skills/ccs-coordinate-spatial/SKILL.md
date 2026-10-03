---
name: "ccs-coordinate-spatial"
description: "Compute coordinate conversions, distances, bearings, and extents for CCS assets."
---

# CCS Coordinate and Spatial Analysis

## Goal

{'capability': 'ccs-coordinate-spatial', 'description': 'Compute coordinate conversions, distances, bearings, and extents for CCS assets.', 'target_state': ['validated-ccs-coordinate-spatial-result']}

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
      "operation": "Normalize CCS coordinate representation and CRS semantics",
      "required": false,
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
          "CCSDecimalToDMS"
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
      "operation": "Compute CCS facility distance",
      "required": false,
      "depends_on": [],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Parameter"
      ],
      "outputs": [
        "Scalar"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "CCSHaversineDistance"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "GeoHaversineDistance",
        "DeepTimeHaversineDistance",
        "CCSHaversineDistance"
      ],
      "method_notes": [
        "Calculate WGS84 great-circle distance."
      ]
    },
    {
      "id": "step_3",
      "operation": "Compute CCS facility bearing",
      "required": false,
      "depends_on": [],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Parameter"
      ],
      "outputs": [
        "Scalar"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "CCSBearing"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "GeoBearing",
        "DeepTimeBearing",
        "CCSBearing"
      ],
      "method_notes": [
        "Calculate initial bearing between two coordinates."
      ]
    },
    {
      "id": "step_4",
      "operation": "Calculate a CCS bounding-box area",
      "required": false,
      "depends_on": [],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Parameter"
      ],
      "outputs": [
        "Scalar"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "CCSBBoxArea"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "EnergyBBoxArea",
        "OceanBBoxArea",
        "DeepTimeBBoxArea",
        "CCSBBoxArea",
        "GeoWGS84BBoxAreaKm2"
      ],
      "method_notes": [
        "Calculate spherical area of a WGS84 bounding box."
      ]
    }
  ]
}
~~~

## Dependencies

~~~json
{
  "tools": [
    "CCSDecimalToDMS",
    "CCSHaversineDistance",
    "CCSBearing",
    "CCSBBoxArea"
  ],
  "unavailable": [],
  "tool_references": [
    "GeoDecimalToDMS",
    "DeepTimeDecimalToDMS",
    "CCSDecimalToDMS",
    "GeoCheckCRSConsistency",
    "CCSCheckCRSConsistency",
    "GeoHaversineDistance",
    "DeepTimeHaversineDistance",
    "CCSHaversineDistance",
    "GeoBearing",
    "DeepTimeBearing",
    "CCSBearing",
    "EnergyBBoxArea",
    "OceanBBoxArea",
    "DeepTimeBBoxArea",
    "CCSBBoxArea",
    "GeoWGS84BBoxAreaKm2"
  ],
  "method_notes": [
    "Normalize coordinate representation and validate CRS consistency.",
    "Calculate WGS84 great-circle distance.",
    "Calculate initial bearing between two coordinates.",
    "Calculate spherical area of a WGS84 bounding box."
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

- CCSDecimalToDMS
- CCSHaversineDistance
- CCSBearing
- CCSBBoxArea

<!-- source-delivery:start -->
## Source interface and delivery

This is the same skill document loaded by the project agent. Tool references are alternatives or supporting operations, not an enforced execution order.

### Calling contract

Inspect the selected tool's input_schema, output_schema, limitations and source_interface before calling it. Supply an object with the documented units and coordinate system. Do not replace missing data with invented values or treat a failed call as evidence.

Inside the agent, call the disclosed native function names directly with schema-valid object arguments. Outside the agent, use the original callable and bound arguments recorded in source_interface.entrypoint. Both execute the same source implementation; no retired execution adapter is required.

File-producing source calls require a caller-selected output directory; inputs may be absolute paths in trusted direct Python use. The agent transport instead requires workspace-relative input paths. Neither direct Python execution nor the standalone transport is an OS security sandbox.

### Dependency status

Source-interface candidates (consult the acceptance report, not this list, for tested availability):
- `CCSDecimalToDMS`
- `CCSHaversineDistance`
- `CCSBearing`
- `CCSBBoxArea`

Unresolved or unavailable references:
- None recorded.

### Current availability

Status: `tool_candidates_available_workflow_unverified`.

All recorded tool references have source-interface candidates. This does not mean the complete skill workflow has passed acceptance.

A reference is not proof that every operation in this skill is available. Choose a supported method, request the missing input, or state the limitation; do not silently skip a scientifically necessary operation.

### Result acceptance

Check the actual result against the chosen tool's output contract, input provenance, units, scientific limitations and requested deliverables. Confirm that referenced output files exist. Report failed or unsupported operations explicitly. Synthetic tool checks do not constitute scientific certification or an end-to-end acceptance test of this skill.

<!-- source-delivery:end -->

---
name: "remote-sensing-data-discovery"
description: "Discover and select spatially, temporally, and semantically compatible raster assets."
---

# Remote-Sensing Data Discovery

## Goal

{'capability': 'remote-sensing-data-discovery', 'description': 'Discover and select spatially, temporally, and semantically compatible raster assets.', 'target_state': ['validated-remote-sensing-data-discovery-result']}

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
      "operation": "List candidate files and select compatible scenes",
      "required": true,
      "depends_on": [],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Parameter"
      ],
      "outputs": [
        "Table|Vector"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "RemoteSensingListFiles"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "RemoteSensingListFiles"
      ],
      "method_notes": [
        "List candidate remote-sensing assets for downstream selection."
      ]
    }
  ]
}
~~~

## Dependencies

~~~json
{
  "tools": [
    "RemoteSensingListFiles"
  ],
  "unavailable": [],
  "tool_references": [
    "RemoteSensingListFiles"
  ],
  "method_notes": [
    "List candidate remote-sensing assets for downstream selection."
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

- RemoteSensingListFiles

<!-- source-delivery:start -->
## Source interface and delivery

This is the same skill document loaded by the project agent. Tool references are alternatives or supporting operations, not an enforced execution order.

### Calling contract

Inspect the selected tool's input_schema, output_schema, limitations and source_interface before calling it. Supply an object with the documented units and coordinate system. Do not replace missing data with invented values or treat a failed call as evidence.

Inside the agent, call the disclosed native function names directly with schema-valid object arguments. Outside the agent, use the original callable and bound arguments recorded in source_interface.entrypoint. Both execute the same source implementation; no retired execution adapter is required.

File-producing source calls require a caller-selected output directory; inputs may be absolute paths in trusted direct Python use. The agent transport instead requires workspace-relative input paths. Neither direct Python execution nor the standalone transport is an OS security sandbox.

### Dependency status

Source-interface candidates (consult the acceptance report, not this list, for tested availability):
- `RemoteSensingListFiles`

Unresolved or unavailable references:
- None recorded.

### Current availability

Status: `tool_candidates_available_workflow_unverified`.

All recorded tool references have source-interface candidates. This does not mean the complete skill workflow has passed acceptance.

A reference is not proof that every operation in this skill is available. Choose a supported method, request the missing input, or state the limitation; do not silently skip a scientifically necessary operation.

### Result acceptance

Check the actual result against the chosen tool's output contract, input provenance, units, scientific limitations and requested deliverables. Confirm that referenced output files exist. Report failed or unsupported operations explicitly. Synthetic tool checks do not constitute scientific certification or an end-to-end acceptance test of this skill.

<!-- source-delivery:end -->

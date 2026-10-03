---
name: "remote-sensing-preprocessing"
description: "Select the requested spectral index and compatible bands; different indices are not interchangeable. See raster-ndvi-zonal-analysis for explicit NDVI data handoffs."
---

# Remote-Sensing Preprocessing and Indices

## Goal

{'capability': 'remote-sensing-preprocessing', 'description': 'Prepare compatible raster inputs, mask clouds, calculate spectral indices, and convert units.', 'target_state': ['validated-remote-sensing-preprocessing-result']}

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
      "operation": "Mask, align, and normalize raster inputs",
      "required": true,
      "depends_on": [],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Raster|Parameter"
      ],
      "outputs": [
        "Raster"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "RemoteSensingCloudMask",
          "RemoteSensingKelvinToCelsius"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "RemoteSensingCloudMask",
        "RemoteSensingKelvinToCelsius"
      ],
      "method_notes": [
        "Compatibility discovery group only; candidates are NOT substitutes. Prepare and align raster bands, masks, CRS and NoData."
      ]
    },
    {
      "id": "step_2",
      "operation": "Derive the requested spectral index",
      "required": false,
      "depends_on": [
        "step_1"
      ],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Raster"
      ],
      "outputs": [
        "Raster"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "RemoteSensingNDVI",
          "RemoteSensingNDWI",
          "RemoteSensingNBR",
          "RemoteSensingBatchNDSI",
          "RemoteSensingNDTI"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "RemoteSensingNDVI",
        "RemoteSensingNDWI",
        "RemoteSensingNBR",
        "RemoteSensingBatchNDSI",
        "RemoteSensingNDTI"
      ],
      "method_notes": [
        "Compatibility discovery group only; candidates are NOT substitutes. Derive a normalized spectral index from compatible bands."
      ]
    }
  ]
}
~~~

## Dependencies

~~~json
{
  "tools": [
    "RemoteSensingCloudMask",
    "RemoteSensingNDVI",
    "RemoteSensingNDWI",
    "RemoteSensingNBR",
    "RemoteSensingBatchNDSI",
    "RemoteSensingNDTI",
    "RemoteSensingKelvinToCelsius"
  ],
  "unavailable": [
    "RemoteSensingCloudMask",
    "RemoteSensingNDTI"
  ],
  "tool_references": [
    "RemoteSensingCloudMask",
    "RemoteSensingNDVI",
    "RemoteSensingNDWI",
    "RemoteSensingNBR",
    "RemoteSensingBatchNDSI",
    "RemoteSensingNDTI"
  ],
  "method_notes": [
    "Mask Landsat Collection 2 QA_PIXEL cloud/shadow bits 3 and 4 on an aligned band.",
    "Compute dimensionless (NIR-red)/(NIR+red) on compatible physical band values.",
    "Compute NDWI using this tool's documented green/NIR band convention.",
    "Compute normalized burn ratio from NIR and SWIR, not NDVI.",
    "Compute normalized snow index from green and SWIR bands.",
    "Compute this implementation's turbidity index from green/red pairs."
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

- RemoteSensingCloudMask
- RemoteSensingKelvinToCelsius
- RemoteSensingNDVI
- RemoteSensingNDWI
- RemoteSensingNBR
- RemoteSensingBatchNDSI
- RemoteSensingNDTI

<!-- source-delivery:start -->
## Source interface and delivery

This is the same skill document loaded by the project agent. Tool references are alternatives or supporting operations, not an enforced execution order.

### Calling contract

Inspect the selected tool's input_schema, output_schema, limitations and source_interface before calling it. Supply an object with the documented units and coordinate system. Do not replace missing data with invented values or treat a failed call as evidence.

Inside the agent, call the disclosed native function names directly with schema-valid object arguments. Outside the agent, use the original callable and bound arguments recorded in source_interface.entrypoint. Both execute the same source implementation; no retired execution adapter is required.

File-producing source calls require a caller-selected output directory; inputs may be absolute paths in trusted direct Python use. The agent transport instead requires workspace-relative input paths. Neither direct Python execution nor the standalone transport is an OS security sandbox.

### Dependency status

Source-interface candidates (consult the acceptance report, not this list, for tested availability):
- `RemoteSensingKelvinToCelsius`
- `RemoteSensingNDVI`
- `RemoteSensingNDWI`
- `RemoteSensingNBR`
- `RemoteSensingBatchNDSI`

Unresolved or unavailable references:
- `RemoteSensingCloudMask`: QA 位规则与传感器约定不完整，存在网格和 NoData 风险。
- `RemoteSensingNDTI`: 输入配对的波段、时相和指数定义未形成明确契约。

### Current availability

Status: `partially_blocked`.

Only part of the recorded tool set is available. A supported subset may be usable, but the full method must not be claimed executable without checking which operations are necessary.

A reference is not proof that every operation in this skill is available. Choose a supported method, request the missing input, or state the limitation; do not silently skip a scientifically necessary operation.

### Result acceptance

Check the actual result against the chosen tool's output contract, input provenance, units, scientific limitations and requested deliverables. Confirm that referenced output files exist. Report failed or unsupported operations explicitly. Synthetic tool checks do not constitute scientific certification or an end-to-end acceptance test of this skill.

<!-- source-delivery:end -->

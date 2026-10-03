---
name: "raster-ndvi-zonal-analysis"
description: "Derive NDVI from supplied NIR/red rasters and summarize explicit polygon zones; optional aligned Landsat cloud/shadow masking."
---

# NDVI and Polygon-Zone Summary

## Goal

Derive NDVI from supplied NIR/red rasters and summarize explicit polygon zones; optional aligned Landsat cloud/shadow masking.

## Inputs

~~~json
[]
~~~

## Outputs

~~~json
[]
~~~

## Method

Choose steps from observations and the actual goal; this is guidance, not a mandatory fixed chain.
After loading this skill, use the exposed native tool schemas, sourced directly from catalog/registry.json. Do not try to read repository files in the user task directory.
Call the original structured implementation. Do not use the retired asset_catalog execution route.

~~~json
{
  "tool_references": [
    "RemoteSensingCloudMask",
    "RemoteSensingNDVI",
    "DeepTimeZonalStatistics",
    "CCSZonalStatistics"
  ],
  "method_notes": [
    "Mask Landsat Collection 2 QA_PIXEL cloud/shadow bits 3 and 4 on an aligned band.",
    "Compute dimensionless (NIR-red)/(NIR+red) on compatible physical band values.",
    "Calculate raster or tabular summary statistics by analysis zone."
  ]
}
~~~

## Dependencies

~~~json
{
  "tools": [],
  "unavailable": [],
  "tool_references": [
    "RemoteSensingCloudMask",
    "RemoteSensingNDVI",
    "DeepTimeZonalStatistics",
    "CCSZonalStatistics"
  ],
  "method_notes": [
    "Mask Landsat Collection 2 QA_PIXEL cloud/shadow bits 3 and 4 on an aligned band.",
    "Compute dimensionless (NIR-red)/(NIR+red) on compatible physical band values.",
    "Calculate raster or tabular summary statistics by analysis zone."
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
- RemoteSensingNDVI
- DeepTimeZonalStatistics
- CCSZonalStatistics

<!-- source-delivery:start -->
## Source interface and delivery

This is the same skill document loaded by the project agent. Tool references are alternatives or supporting operations, not an enforced execution order.

### Calling contract

Inspect the selected tool's input_schema, output_schema, limitations and source_interface before calling it. Supply an object with the documented units and coordinate system. Do not replace missing data with invented values or treat a failed call as evidence.

Inside the agent, call the disclosed native function names directly with schema-valid object arguments. Outside the agent, use the original callable and bound arguments recorded in source_interface.entrypoint. Both execute the same source implementation; no retired execution adapter is required.

File-producing source calls require a caller-selected output directory; inputs may be absolute paths in trusted direct Python use. The agent transport instead requires workspace-relative input paths. Neither direct Python execution nor the standalone transport is an OS security sandbox.

### Dependency status

Source-interface candidates (consult the acceptance report, not this list, for tested availability):
- `RemoteSensingNDVI`
- `DeepTimeZonalStatistics`
- `CCSZonalStatistics`

Unresolved or unavailable references:
- `RemoteSensingCloudMask`: QA 位规则与传感器约定不完整，存在网格和 NoData 风险。

### Current availability

Status: `partially_blocked`.

Only part of the recorded tool set is available. A supported subset may be usable, but the full method must not be claimed executable without checking which operations are necessary.

A reference is not proof that every operation in this skill is available. Choose a supported method, request the missing input, or state the limitation; do not silently skip a scientifically necessary operation.

### Result acceptance

Check the actual result against the chosen tool's output contract, input provenance, units, scientific limitations and requested deliverables. Confirm that referenced output files exist. Report failed or unsupported operations explicitly. Synthetic tool checks do not constitute scientific certification or an end-to-end acceptance test of this skill.

<!-- source-delivery:end -->

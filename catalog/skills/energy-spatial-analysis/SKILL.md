---
name: "energy-spatial-analysis"
description: "Measure distances, nearest facilities, bounding-box areas, and overlays among energy and mineral assets."
---

# Energy and Mineral Spatial Analysis

## Goal

{'capability': 'energy-spatial-analysis', 'description': 'Measure distances, nearest facilities, bounding-box areas, and overlays among energy and mineral assets.', 'target_state': ['validated-energy-spatial-analysis-result']}

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
      "operation": "Compute facility or site distance",
      "required": false,
      "depends_on": [],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Vector|Parameter"
      ],
      "outputs": [
        "Scalar"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "EnergyFacilityDistance",
          "EnergyMineralSiteDistance"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "EnergyFacilityDistance",
        "EnergyMineralSiteDistance",
        "OceanStationDistance",
        "GeoHaversineDistance",
        "DeepTimeHaversineDistance",
        "CCSHaversineDistance"
      ],
      "method_notes": [
        "Compute great-circle distance between two spatial facilities or sites."
      ]
    },
    {
      "id": "step_2",
      "operation": "Calculate an energy-resource bounding-box area",
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
          "EnergyBBoxArea"
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
    },
    {
      "id": "step_3",
      "operation": "Select the nearest energy facility or mineral site",
      "required": false,
      "depends_on": [],
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
          "EnergyNearestFacility",
          "EnergyNearestMineralSite"
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
      "id": "step_4",
      "operation": "Summarize regional energy and mineral overlays",
      "required": false,
      "depends_on": [],
      "input_refs": [],
      "output_refs": [],
      "inputs": [
        "Vector|Parameter"
      ],
      "outputs": [
        "Table|Raster"
      ],
      "preconditions": [],
      "postconditions": [],
      "tool_selection": {
        "mode": "dynamic",
        "candidates": [
          "EnergyRegionalOverlaySummary"
        ],
        "selection_criteria": [
          "input_compatibility",
          "tool_availability",
          "geo_constraint_satisfaction",
          "execution_feedback"
        ]
      },
      "tool_references": [
        "EnergyRegionalOverlaySummary",
        "OceanRegionalMapSummary"
      ],
      "method_notes": [
        "Summarize facilities or sites within a named region and extent."
      ]
    }
  ]
}
~~~

## Dependencies

~~~json
{
  "tools": [
    "EnergyFacilityDistance",
    "EnergyMineralSiteDistance",
    "EnergyBBoxArea",
    "EnergyNearestFacility",
    "EnergyNearestMineralSite",
    "EnergyRegionalOverlaySummary"
  ],
  "unavailable": [
    "EnergyFacilityDistance",
    "EnergyMineralSiteDistance",
    "EnergyNearestFacility",
    "EnergyNearestMineralSite",
    "EnergyRegionalOverlaySummary"
  ],
  "tool_references": [
    "EnergyFacilityDistance",
    "EnergyMineralSiteDistance",
    "OceanStationDistance",
    "GeoHaversineDistance",
    "DeepTimeHaversineDistance",
    "CCSHaversineDistance",
    "EnergyBBoxArea",
    "OceanBBoxArea",
    "DeepTimeBBoxArea",
    "CCSBBoxArea",
    "GeoWGS84BBoxAreaKm2",
    "EnergyNearestFacility",
    "EnergyNearestMineralSite",
    "DeepTimeNearestNeighbor",
    "CCSNearestNeighbor",
    "EnergyRegionalOverlaySummary",
    "OceanRegionalMapSummary"
  ],
  "method_notes": [
    "Compute great-circle distance between two spatial facilities or sites.",
    "Calculate spherical area of a WGS84 bounding box.",
    "Select the nearest facility, feature, or related mineral site.",
    "Summarize facilities or sites within a named region and extent."
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

- EnergyFacilityDistance
- EnergyMineralSiteDistance
- EnergyBBoxArea
- EnergyNearestFacility
- EnergyNearestMineralSite
- EnergyRegionalOverlaySummary

<!-- source-delivery:start -->
## Source interface and delivery

This is the same skill document loaded by the project agent. Tool references are alternatives or supporting operations, not an enforced execution order.

### Calling contract

Inspect the selected tool's input_schema, output_schema, limitations and source_interface before calling it. Supply an object with the documented units and coordinate system. Do not replace missing data with invented values or treat a failed call as evidence.

Inside the agent, call the disclosed native function names directly with schema-valid object arguments. Outside the agent, use the original callable and bound arguments recorded in source_interface.entrypoint. Both execute the same source implementation; no retired execution adapter is required.

File-producing source calls require a caller-selected output directory; inputs may be absolute paths in trusted direct Python use. The agent transport instead requires workspace-relative input paths. Neither direct Python execution nor the standalone transport is an OS security sandbox.

### Dependency status

Source-interface candidates (consult the acceptance report, not this list, for tested availability):
- `EnergyBBoxArea`

Unresolved or unavailable references:
- `EnergyFacilityDistance`: 实现绑定特定数据快照，尚无可交付的数据路径、版本、字段和授权约定。
- `EnergyMineralSiteDistance`: 实现绑定特定数据快照，尚无可交付的数据路径、版本、字段和授权约定。
- `EnergyNearestFacility`: 实现绑定特定数据快照，尚无可交付的数据路径、版本、字段和授权约定。
- `EnergyNearestMineralSite`: 实现绑定特定数据快照，尚无可交付的数据路径、版本、字段和授权约定。
- `EnergyRegionalOverlaySummary`: 实现绑定特定数据快照，尚无可交付的数据路径、版本、字段和授权约定。

### Current availability

Status: `partially_blocked`.

Only part of the recorded tool set is available. A supported subset may be usable, but the full method must not be claimed executable without checking which operations are necessary.

A reference is not proof that every operation in this skill is available. Choose a supported method, request the missing input, or state the limitation; do not silently skip a scientifically necessary operation.

### Result acceptance

Check the actual result against the chosen tool's output contract, input provenance, units, scientific limitations and requested deliverables. Confirm that referenced output files exist. Report failed or unsupported operations explicitly. Synthetic tool checks do not constitute scientific certification or an end-to-end acceptance test of this skill.

<!-- source-delivery:end -->

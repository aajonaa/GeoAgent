---
id: earth_python_groundwater
name: Earth Python groundwater
description: "Analytical Theis drawdown for a confined homogeneous aquifer; explicit SI units and assumptions, CSV and PNG. Not aquifer calibration or site-specific inference."
when_to_use: "Analytical Theis drawdown for a confined homogeneous aquifer; explicit SI units and assumptions, CSV and PNG. Not aquifer calibration or site-specific inference."
tools: ["HydroAnaFlowTheis"]
constraints: ["Use only the requested bounded operation.", "Inputs and units must be supplied; do not fabricate reference observations.", "Never install packages or download basemaps during a tool call.", "A dependency or file error is not successful execution evidence."]
expected_outputs: ["Observed JSON results with units and provenance", "Real generated artifacts where declared"]
---

# Earth Python groundwater

Analytical Theis drawdown for a confined homogeneous aquifer; explicit SI units and assumptions, CSV and PNG. Not aquifer calibration or site-specific inference.

Choose only necessary operations. An existing tool result is evidence; this guidance is not.
Direct calls accept args=object or a JSON-object string. File-producing standalone calls also require output_dir=an_empty_directory.
Native execution supplies task-relative paths, private snapshots and an automatically generated results directory.
The source collection contains development checkouts. Runtime uses the separately pinned releases and records this distinction.
Examples are explicitly synthetic contract fixtures, not scientific measurements.

## Source interface and delivery

Use the registered native tools after loading this Skill. The source functions implement the same bounded input_schema and output_schema contracts.
Direct calls accept args=dict or args=a_JSON_object_string. File-producing calls also need output_dir pointing to a new or empty directory.
The native runtime resolves task-relative inputs, snapshots files and supplies the private result directory. Generated files are registered as artifacts.

- HydroAnaFlowTheis: `geological_agent.geology.earth_python_wave1:anaflow_theis`; input and result schemas are declared in catalog/registry.json.

### Current availability

tool_candidates_available_workflow_unverified

These are concrete callable source candidates, not placeholders. Independent interface tests do not establish end-to-end model-workflow or receiving-platform approval.
Workflow validation: not_run. Platform validation: not_run. Preserve observed units, provenance, physical assumptions and errors; never treat this Skill text as execution evidence.

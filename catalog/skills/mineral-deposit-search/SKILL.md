---
name: "mineral-deposit-search"
description: "Search and retrieve mineral deposit records by commodity, country, identifier, and location."
---

# Mineral Deposit Search

## Goal

Find a mineral deposit that matches the requested country and commodity, and report its observed identifier, location and source. Distinguish catalog records from current reserves, resources or production.

## Inputs

~~~json
[
  {
    "id": "query_or_resource",
    "semantic_type": "Table|Parameter",
    "data_type": "authoritative resource locator",
    "required": true,
    "description": "Country/commodity or another stated search objective; optionally an existing licensed table or an accessible public source. A local dataset is not assumed to be installed."
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

Choose the route from the user's objective and observed resources, not from tool availability alone.

### Existing table route

Use MineralResourcesSearchDeposits only when a real compatible input table exists in the workspace.
The tool is a local file query, not an online MRDS client and not a bundled dataset.
Supply the observed workspace-relative filename, country and commodity. Inspect returned rows before
choosing a dep_id and calling MineralResourcesGetDeposit when details are needed. Do not invent
paths, identifiers, rows or field values. A successful query does not authenticate its input source.

### Public source route

If the user asks about public deposits without providing a dataset, use web_search and web_fetch
when those tools are exposed. Search for a relevant primary catalog record, inspect the returned
page, and verify the country and commodity before choosing a deposit. Search results may be
irrelevant: do not return a Canadian deposit for a China query. Refine the search from actual
observations when needed.

Extract the record's actual dep_id and location from the observed source. Check longitude/latitude
order and the stated coordinate system. A record URL can supply an identifier only when it was
actually returned by a source or supplied by the user. Do not fabricate a source URL from memory
and call it retrieved evidence.

For a single-record factual question, the observed public record may directly answer the task.
A generated CSV and subsequent local lookup are NOT required. Do not manufacture a local snapshot
to make file-query tools usable. If the user explicitly requires a downloadable dataset or a
particular algorithm, acquire that real input and satisfy that additional requirement; a web
excerpt does not silently replace it.

### Missing or inaccessible resources

Inspect actual error results and available acquisition methods. A missing local filename does not
prove that public data is unavailable. Ask the user for private data, access or a genuine decision
only when it is necessary; explain the attempted sources and exact unresolved gap. Do not send
private files, credentials or full conversations to a public search provider.

Native tool calls and their returned observations are the evidence. Narrating several searches,
reads or writes in a single response does not execute them. Wait for each needed result before
selecting a dependent action. These routes are guidance, not a fixed execution plan.

## Dependencies

Select from the direct tool references below. Use the current schemas and environment requirements; a list of tools is not an executable workflow.

Environment: Python 3.12 with requirements-source-tools.txt. Caller supplies licensed input data.
A tool reference is not proof that its implementation is available. Consult every referenced tool's source_interface status.

## Success criteria

Verify the selected record's country, commodity, name, dep_id, location and source against actual tool observations. State missing fields rather than infer them. Report the coordinate system and location limitations supplied by the source; catalog coordinates do not establish current operating status or reserves.
Use a natural-language answer with the source link unless the user asks for another format. Only create files when requested or genuinely needed. If files are requested, verify their actual contents. A schema-valid tool response or search hit alone is not scientific validation.
The skill's operational availability and end-to-end behavior require acceptance evidence; this document does not certify them.

## Failure handling

Correct parameters or missing data from the error, then retry only after changing the cause.
Never invent unavailable algorithms, datasets or scientific results. Ask for missing prerequisites if no supported path remains.

## Publication

Draft only. Provider ownership, license, official schema validation and version-locked protocol repository remain unresolved.

## Direct tool references

These are suggestions, not an execution order or permission to run unavailable tools.

- MineralResourcesSearchDeposits
- MineralResourcesGetDeposit

<!-- source-delivery:start -->
## Source interface and delivery

This is the same skill document loaded by the project agent. Tool references are alternatives or supporting operations, not an enforced execution order.

### Calling contract

Inspect the selected tool's input_schema, output_schema, limitations and source_interface before calling it. Supply an object with the documented units and coordinate system. Do not replace missing data with invented values or treat a failed call as evidence.

Inside the agent, call the disclosed native function names directly with schema-valid object arguments. Outside the agent, use the original callable and bound arguments recorded in source_interface.entrypoint. Both execute the same source implementation; no retired execution adapter is required.

File-producing source calls require a caller-selected output directory; inputs may be absolute paths in trusted direct Python use. The agent transport instead requires workspace-relative input paths. Neither direct Python execution nor the standalone transport is an OS security sandbox.

### Dependency status

Source-interface candidates (consult the acceptance report, not this list, for tested availability):
- `MineralResourcesSearchDeposits`
- `MineralResourcesGetDeposit`

Unresolved or unavailable references:
- None recorded.

### Current availability

Status: `tool_candidates_available_workflow_unverified`.

All recorded tool references have source-interface candidates. This does not mean the complete skill workflow has passed acceptance.

A reference is not proof that every operation in this skill is available. Choose a supported method, request the missing input, or state the limitation; do not silently skip a scientifically necessary operation.

### Result acceptance

Check the actual result against the chosen tool's output contract, input provenance, units, scientific limitations and requested deliverables. Confirm that referenced output files exist. Report failed or unsupported operations explicitly. Synthetic tool checks do not constitute scientific certification or an end-to-end acceptance test of this skill.

<!-- source-delivery:end -->

---
id: geological_table_analysis
name: Geological table analysis
description: Inspect and analyze local geological, mineral or geochemical CSV files. 地质矿石地球化学表格清洗与计算。
when_to_use: The user supplies tabular observations and requests calculations, cleaning, reports or repaired analysis code.
required_inputs: [Local file or supplied table, Column meanings and units, Requested analysis]
tools: [read_file, write_file, execute_python]
constraints:
  - Do not assume missing scientific units or invent observations.
  - Preserve original input files unless editing is explicitly requested.
  - Keep excluded rows and reasons; never silently treat missing data as zero.
expected_outputs: [Computed results, Exclusions with reasons when applicable, Requested report files]
---
# Geological table analysis

Inspect the supplied columns, representative rows, data types and units before
choosing an analysis. Ask if an essential unit or scientific assumption is absent.
Use Python's standard library for the initial demo; csv, json, math and statistics
are available without installing extra packages.

For ore mass in tonnes and a grade expressed as a percentage number, contained
metal tonnes = ore_tonnes * grade_pct / 100. A tonne-weighted grade is
100 * total_metal_tonnes / total_valid_ore_tonnes, not an unweighted average.
Contained metal is not recoverable metal: recovery requires a separate factor.

Reject negative masses, non-finite values and missing required measurements from
the aggregation; retain their identifiers and explain the exclusions. Check for
an empty valid set or a zero denominator. Produce requested machine-readable
outputs and derive narrative values from the same computed result.

When repairing code, reproduce the problem, make a targeted change and actually
run suitable checks. Tool errors are observations: change the failing input or
program, rather than blindly repeating it. The model chooses the next useful
step; this skill is not an execution plan.

## Source interface and delivery

This catalog document is the runtime instruction source. Use the actual native
ToolDefinition input/output schemas and the registered implementation. File
paths are workspace-relative; preserve originals, units and provenance.
File and Python tools require the workspace execution environment. Visual
analysis additionally requires an available vision-capable model; errors are
not evidence and must never be replaced with invented results.

### Current availability

tool_candidates_available_workflow_unverified. Registered dependencies are
callable candidates, not complete-workflow or receiving-platform certification.
Redistribution metadata and independent platform acceptance remain pending.

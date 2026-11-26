---
id: geological_table_analysis
name: Geological table analysis
description: "Inspect, clean and analyze supplied geological, mineral or geochemical tables; evaluate hydrological streamflow simulations with HydroErr (Nash-Sutcliffe efficiency, RMSE, KGE); fit linear or exponential decay curves with LMFIT; test spatial autocorrelation with PySAL Moran's I. \u5730\u8d28\u8868\u683c\u3001\u6c34\u6587\u6a21\u578b\u8bc4\u4f30\u3001\u66f2\u7ebf\u62df\u5408\u3001\u7a7a\u95f4\u81ea\u76f8\u5173\u3002"
when_to_use: Use supplied tables or in-memory observation arrays for cleaning, hydrological model metrics, linear or exponential curve fitting, or KNN spatial autocorrelation. Confirm alignment, units and coordinates; CSV files are optional when arrays are supplied.
required_inputs: [Supplied table or aligned observation arrays, Column meanings and units, Requested analysis and coordinates for spatial statistics]
tools: ["read_file", "write_file", "execute_python", "HydroErrorMetrics", "ScientificCurveFit", "SpatialMoranI"]
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

For aligned observed and simulated series, HydroErrorMetrics computes only the
requested HydroErr metrics and preserves non-finite metric results as `null`.
ScientificCurveFit exposes bounded linear or exponential LMFIT models; provide
units and a scientifically justified model before interpreting parameters.
SpatialMoranI uses KNN weights on supplied coordinates. Confirm CRS and distance
meaning, and record `k`, permutation count and `random_seed` when interpreting
the result. A constant value series returns `moran_i: null`.

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

## Preserved source-specific scientific constraints

The following original guidance applies to the original operations only, not to unrelated array-based calculations.

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

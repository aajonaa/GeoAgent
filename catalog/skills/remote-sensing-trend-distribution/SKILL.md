---
name: remote-sensing-trend-distribution
description: Choose justified trend, slope and distribution statistics for ordered numeric observations.
---

# Trend and Distribution Analysis

## Goal and inputs

Analyze the requested temporal trend or distribution, rather than executing
every listed tool. Numeric observations must have known order, spacing,
physical units, missing-data meaning and, where applicable, seasonal period.
These tools accept numeric series, not raw raster files. Extract a scientifically
defined, aligned time series from rasters first if the input is imagery.
Never invent missing observations or silently collapse gaps.

## Choose the required operation

- RemoteSensingLinearTrend: least-squares trend for the stated regular series.
- RemoteSensingSensSlope: existing median pairwise slope per sample interval.
- RemoteSensingMannKendallTest: original or seasonal MK significance, including
  ties, with Sen slope scaled to the declared physical time unit.
- RemoteSensingKurtosis: distribution shape when defined.
- RemoteSensingCoefficientOfVariation: relative variability; check the meaning
  and nonzero mean before interpretation.

These are alternatives or complementary operations, not a fixed execution
plan. Do not call the standalone slope tool again when the MK result already
provides exactly the requested slope and units.

## Mann-Kendall parameters and limits

Use x for finite, regularly spaced observations; alpha defaults to 0.05.
method=original is the default. method=seasonal additionally requires period
(samples per cycle), complete cycles and at least three cycles in this initial
profile. A period must not be supplied for original mode.

sample_interval is the spacing in time_unit (default 1 sample_interval).
value_unit identifies the measured quantity. The returned slope is explicitly
value_unit/time_unit; seasonal slope is converted from per-cycle to this unit.
Do not silently label an unspecified unit as year, month or concentration.

The upstream pyMannKendall implementation includes tie variance correction.
Its p-value uses an asymptotic normal approximation and continuity correction,
not an exact small-sample test. Small samples are flagged. Neither available
method corrects serial dependence. If this matters, explain the limitation or
choose a separately supported method; do not claim automatic correction.
Statistical significance is not causality, and nonsignificance does not prove
that no trend exists.

## Execution and result handling

Load this skill, then invoke only the native tools required by the goal.
Schemas from catalog/registry.json are authoritative. The existing
RemoteSensingMannKendallTest identifier now calls the same mann_kendall(args)
source implementation for both direct Python and Agent execution. The older
dispatch(name, args) entry delegates to this implementation too; there is no
delivery-only algorithm.

Report method, actual observations, units, significance threshold, statistic,
p-value and relevant warnings. Keep unrounded results for subsequent
calculations; round only for presentation. Do not retry a successful call merely
to change prose. If a call fails, correct the cause before retrying.

## Availability and provenance

All five listed operations have source-interface candidates. Consult runtime
execution results and acceptance records before claiming environment
availability or scientific validation. No new dataset is supplied.

MK backend: pymannkendall 1.4.3 (MIT),
https://github.com/mmhs013/pyMannKendall
Install dependencies from requirements-source-tools.txt.
Formal packaging and institutional registration are deferred.

## Source interface and delivery

Use the native parameter dictionaries and source entrypoints in catalog/registry.json. The five referenced operations now have source-interface candidates, including RemoteSensingMannKendallTest. Choose only operations required by the task and retain the statistical limitations documented above.

### Current availability

Availability: tool_candidates_available_workflow_unverified.
The referenced tools have callable source-interface candidates. This is not
complete skill-workflow validation, scientific certification or receiving-platform
acceptance. Workflow and platform validation remain not_run. Institutional
provider, asset version, licensing confirmation and official protocol version
remain pending; no formal delivery package has been issued.

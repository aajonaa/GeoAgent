---
id: github_geology_drillhole_logs
name: "Drillhole survey and interval-log analysis"
description: "Parse and audit a local LAS drillhole log with explicit depth/curve units and preserved missing-value masks. Reconstruct a drillhole trajectory and normalized dogleg severity from a measured deviation survey. Resample a measured drillhole log onto a declared regular depth basis using bounded linear interpolation. Attenuate isolated drillhole-log spikes using an explicit median window and global standard-deviation threshold, retaining original values. Segment a measured drillhole log at caller-specified value cutoffs and compute mean values within contiguous blocks. Intersect two measured interval logs in one drillhole to expose co-occurring geological units and their shared measured-depth support."
when_to_use: "Drillhole survey and interval-log analysis from explicit supplied geological measurements"
tools:
- GeoLasioLogAudit
- GeoWellyMinimumCurvature
- GeoWellyLogResample
- GeoWellyLogDespike
- GeoWellyLogFaciesBlock
- GeoStriplogIntervalIntersection
required_inputs:
- Explicit measured data, units, source and scientific assumptions
constraints:
- Use only the operation needed for the question
- Preserve missingness, units, source hashes and uncertainty
- Do not infer ore grade, reserves or mineral identity
- No installation, online fetch or arbitrary Python at call time
expected_outputs:
- Numeric scientific evidence and native provenance
---

# Drillhole survey and interval-log analysis

## When to use

Parse and audit a local LAS drillhole log with explicit depth/curve units and preserved missing-value masks. Reconstruct a drillhole trajectory and normalized dogleg severity from a measured deviation survey. Resample a measured drillhole log onto a declared regular depth basis using bounded linear interpolation. Attenuate isolated drillhole-log spikes using an explicit median window and global standard-deviation threshold, retaining original values. Segment a measured drillhole log at caller-specified value cutoffs and compute mean values within contiguous blocks. Intersect two measured interval logs in one drillhole to expose co-occurring geological units and their shared measured-depth support.

## Required inputs

Use the exact strict input schema and supplied example for the selected operation. Every call needs a caller-declared data_source. Explicit units, structural conventions, sample alignment and stated geological assumptions are mandatory; the source declaration is not independent authentication.

## Procedure

1. Select the operation matching the scientific question and read its limitations.
2. Obtain the declared measurements, units, reference compositions or model parameters.
3. Check scientific scope and missingness; never replace unavailable measurements with synthetic values.
4. Invoke the named native function with args as a dictionary or JSON object string.
5. Preserve result units and all native provenance hashes. Explain the result within its assumptions.

## Tools and synthetic examples

### GeoLasioLogAudit

Parse and audit a local LAS drillhole log with explicit depth/curve units and preserved missing-value masks.

Entrypoint: `geological_agent.geology.github_expansion_geology:las_log_audit`. Example: `assets/github-expansion-geology/GeoLasioLogAudit.json`. All examples are explicitly SYNTHETIC.

Local UTF-8 LAS only, declared metre depths, no repair substitutions, no unit guessing, no interpolation or null filling. Numeric null masks are preserved; every measurement curve must state units.

Upstream source: [pinned implementation](https://github.com/kinverarity1/lasio/blob/aef25d50b9b36c08a9bde8c53181ed244ee2a035/lasio/las.py).

### GeoWellyMinimumCurvature

Reconstruct a drillhole trajectory and normalized dogleg severity from a measured deviation survey.

Entrypoint: `geological_agent.geology.github_expansion_geology:drillhole_minimum_curvature`. Example: `assets/github-expansion-geology/GeoWellyMinimumCurvature.json`. All examples are explicitly SYNTHETIC.

Minimum-curvature trajectory, not geodesy. Requires a measured collar station at MD zero; no automatic surface/TD station, azimuth correction or extrapolation. Welly delegates numerical integration to wellpathpy.

Upstream source: [pinned implementation](https://github.com/agilescientific/welly/blob/1c028a44b11e7148aaedfd3689630e356c5bcf80/welly/tools.py).

### GeoWellyLogResample

Resample a measured drillhole log onto a declared regular depth basis using bounded linear interpolation.

Entrypoint: `geological_agent.geology.github_expansion_geology:log_depth_resample`. Example: `assets/github-expansion-geology/GeoWellyLogResample.json`. All examples are explicitly SYNTHETIC.

Interpolation is declared, bounded to observed endpoints and does not fill missing values. No inferred assay/ore grade; input arrays must already be complete.

Upstream source: [pinned implementation](https://github.com/agilescientific/welly/blob/1c028a44b11e7148aaedfd3689630e356c5bcf80/welly/curve.py).

### GeoWellyLogDespike

Attenuate isolated drillhole-log spikes using an explicit median window and global standard-deviation threshold, retaining original values.

Entrypoint: `geological_agent.geology.github_expansion_geology:log_median_despike`. Example: `assets/github-expansion-geology/GeoWellyLogDespike.json`. All examples are explicitly SYNTHETIC.

A signal-processing edit, not geological truth. Uses the upstream global standard deviation, not a robust local MAD. Regular sampling required; preserve raw values for audit.

Upstream source: [pinned implementation](https://github.com/agilescientific/welly/blob/1c028a44b11e7148aaedfd3689630e356c5bcf80/welly/curve.py).

### GeoWellyLogFaciesBlock

Segment a measured drillhole log at caller-specified value cutoffs and compute mean values within contiguous blocks.

Entrypoint: `geological_agent.geology.github_expansion_geology:log_facies_block`. Example: `assets/github-expansion-geology/GeoWellyLogFaciesBlock.json`. All examples are explicitly SYNTHETIC.

Classes and cutoffs are user declarations, not inferred lithology or mineralization. Requires at least two contiguous zones because the pinned upstream reducer has a single-zone defect; no local replacement formula is used.

Upstream source: [pinned implementation](https://github.com/agilescientific/welly/blob/1c028a44b11e7148aaedfd3689630e356c5bcf80/welly/curve.py).

### GeoStriplogIntervalIntersection

Intersect two measured interval logs in one drillhole to expose co-occurring geological units and their shared measured-depth support.

Entrypoint: `geological_agent.geology.github_expansion_geology:drillhole_interval_intersection`. Example: `assets/github-expansion-geology/GeoStriplogIntervalIntersection.json`. All examples are explicitly SYNTHETIC.

Same drillhole and MD datum are mandatory caller declarations. Along-hole thickness is not true stratigraphic thickness; boundary-only contacts contribute zero support. No ore or grade inference.

Upstream source: [pinned implementation](https://github.com/agilescientific/striplog/blob/314fed40a2df1d4b20bb2d108cca3f8c652a35bf/striplog/interval.py).

## Interpretation and constraints

These calls use named upstream scientific kernels. A numerical result does not authenticate input data or establish geological representativeness. No tool infers ore grade, reserves or mineral presence. Synthetic examples are numerical oracles only. Units and structural/depth conventions are part of the measurement model.

## Native errors

ScientificToolError exposes code, message and retryable. Correct invalid arguments or unsupported assumptions before retrying. missing_dependency and incompatible_dependency require the parent-controlled private worker; the tool never changes the environment. A failed scientific kernel returns an error, never a local substitute formula or placeholder value.

## Source interface and delivery

Kind: github_expansion_geology. Module: geological_agent.geology.github_expansion_geology. Functions accept args=dict or args=JSON-object-string through collection_contracts.operation. No operation in this Skill requires output_dir or writes artifacts; the LAS reader alone reads one declared local file. Native provenance records pinned dependencies, source commit, input hash, implementation hash, contract hash, and empty artifact hashes.

## Acceptance evidence

Positive independent analytic oracles, per-operation negative constraints and provenance assertions are authored in `tests_local/test_github_expansion_geology.py` and `catalog/source_delivery/github-expansion-20261025/groups/geology/oracle-cases.json`. They have NOT BEEN RUN. Package import/ABI compatibility has NOT BEEN TESTED.

## Current availability

Source authored and generated metadata only. NOT TESTED / NOT DEPLOYED / NOT SUBMITTED. Unit, workflow, model-workflow and platform validation: not_run. Receiving-lab approval and adapter license: pending. Parent owns fixed module whitelist, worker dispatch, registry integration and CPU acceptance. Existing online229 is unchanged.

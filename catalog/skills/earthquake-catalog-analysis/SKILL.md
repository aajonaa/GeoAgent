---
name: "earthquake-catalog-analysis"
description: "Clean and classify a supplied earthquake CSV; distinguish this supported operation from unavailable frozen-catalog queries."
---

# Earthquake Catalog Analysis

## Goal

Clean a caller-supplied earthquake catalog and classify magnitudes when requested.
Do not substitute cleaning for filtering, ranking or a missing reference-data query.

## Inputs

An existing task-relative UTF-8 CSV with time, latitude, longitude, depth and mag
columns. Optional id, type and place columns are preserved and used by the source.
Coordinates are decimal degrees and depth is kilometres. Confirm the magnitude
scale; never invent earthquake observations or input paths.

## Outputs

A cleaned CSV plus input_rows, clean_rows and dropped_rows. Classification is a
magnitude category, not an intensity, damage or hazard prediction.

## Method

This is guidance, not a fixed execution plan. Select only the requested action.
After loading, use the disclosed native schemas, not repository file reads.
The source asset `地震数据清洗与分级` has native function name
`geo_tool_00aa9bcef908cc86fc7b`. Call it with `{"source":"events.csv"}`.
It validates/coerces required columns, removes invalid observations and duplicates,
and adds magnitude class fields. Inspect the actual counts and returned artifact.
Do not run Python merely to reimplement this existing source algorithm.

`DeepEarthQueryUSGSCatalog` remains unavailable: its data snapshot, version, fields
and rights do not have a delivery contract. Cleaning does not enable that separate
query. Ask for missing data or choose another grounded method, stating limitations.

## Dependencies

- 地震数据清洗与分级: structured original callable with explicit output directory.
- DeepEarthQueryUSGSCatalog: blocked data-dependent query, not exposed for execution.
- Python professional dependency set, including pandas.

## Success criteria

The native call succeeds, the output exists, and counts and classification claims
agree with its actual contents. Do not claim an unperformed query was completed.

## Failure handling

Correct inputs from actual schema, column or path errors; ask for missing data
rather than repeating unchanged calls or inventing results.

## Direct tool references

- 地震数据清洗与分级
- DeepEarthQueryUSGSCatalog

## Source interface and delivery

### Calling contract

Inside the agent, call the disclosed native function with schema-valid object
arguments and task-relative paths. Outside, call the original
clean_and_classify_earthquake_data function with an explicit output_dir.
Both execute the same source algorithm; no retired execution adapter is used.

### Dependency status

The cleaning source is callable. Frozen USGS catalog queries remain unavailable.

### Current availability

Status: `partially_blocked`.

### Result acceptance

Check requested files, counts, provenance and limitations. Synthetic checks do not
establish scientific certification, full skill acceptance, data licensing or
acceptance by the external asset platform.
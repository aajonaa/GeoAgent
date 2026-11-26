---
id: expansion501_spatial_gis_georeferencing
name: "GIS coverage and image georeferencing"
description: "CPU-accepted scientific operations for GIS coverage and image georeferencing"
tools:
  - GeoSpatialCoverageSimplification
  - GeoSpatialConservativeArealTransfer
  - GeoSpatialRPCGeolocation
  - GeoSpatialGCPGeoreferencing
  - GeoSpatialLineworkPolygonTopology
  - GeoSpatialChannelFrechetDeviation
---

# GIS coverage and image georeferencing

## When to use

Select only an available operation whose scientific assumptions match the task.

## Required inputs

Use the closed native input schema, explicit units, source data, coordinate system and time conventions.

## Workflow

1. Inspect source provenance and scientific applicability.
2. Call the selected native operation with its exact schema.
3. Inspect numerical results, units, errors and source/input/output hashes.
4. Deliver only actual validated results and their scientific limitations.

## Available operations

- `GeoSpatialCoverageSimplification`: Simplify internal boundaries of an edge-matched polygon coverage without simplifying its outer boundary.
- `GeoSpatialConservativeArealTransfer`: Transfer extensive totals between complete polygon partitions by intersection-area allocation.
- `GeoSpatialRPCGeolocation`: Geolocate image pixel centres using a rational polynomial camera and explicit ellipsoidal heights.
- `GeoSpatialGCPGeoreferencing`: Fit a thin-plate-spline ground-control transformation and locate in-hull image coordinates.
- `GeoSpatialLineworkPolygonTopology`: Extract polygons and diagnose cut edges, dangles and invalid rings from noded linework.
- `GeoSpatialChannelFrechetDeviation`: Measure ordered centreline deviation using the discrete Frechet distance.

## Constraints

Offline CPU-only execution. Never install packages, download data or substitute generated algorithms during a call.
Fixed dependency environments retain the original upstream algorithms, exact versions and license notices.
Do not infer mineral presence, grade or reserves from indirect imagery indices.

## Expected outputs

Schema-validated numerical JSON, declared units, original evidence and declared artifacts with content hashes.

## Source interface and delivery

Use the native function input object. Standalone examples are in catalog/source_delivery/examples.json.
Runtime profiles bind the source, interpreter, exact dependency lock and CPU execution evidence.

### Current availability

`tool_candidates_available_workflow_unverified`

The listed operations passed internal CPU acceptance; this is not model-driven workflow acceptance or AI Lab approval.
Scientific platform validation: `not_run`. Lab submission: `not_submitted`.
Deployment, Git and browser acceptance are recorded separately in release receipts.

---
id: expansion501_spatial_gis_georeferencing
name: "GIS coverage and image georeferencing"
description: "CPU-accepted operations for GIS coverage and image georeferencing; use only the listed available subset."
tools:
  - GeoSpatialCoverageSimplification
  - GeoSpatialRPCGeolocation
  - GeoSpatialGCPGeoreferencing
  - GeoSpatialLineworkPolygonTopology
  - GeoSpatialChannelFrechetDeviation
---

# GIS coverage and image georeferencing

## When to use

Select one of the available scientific operations below. Do not substitute an unavailable operation.

## Required inputs

Use each operation's closed input schema, declared units, source data and explicit spatial/temporal conventions.

## Workflow

1. Check the scientific assumptions, units and input provenance.
2. Select the listed native tool and use its exact parameter schema.
3. Inspect numeric outputs, uncertainty, artifact hashes and error state.
4. Report only executed results; do not infer mineral presence, grade or reserves from image proxies.

## Available operations

- `GeoSpatialCoverageSimplification`: Simplify internal boundaries of an edge-matched polygon coverage without simplifying its outer boundary.
- `GeoSpatialRPCGeolocation`: Geolocate image pixel centres using a rational polynomial camera and explicit ellipsoidal heights.
- `GeoSpatialGCPGeoreferencing`: Fit a thin-plate-spline ground-control transformation and locate in-hull image coordinates.
- `GeoSpatialLineworkPolygonTopology`: Extract polygons and diagnose cut edges, dangles and invalid rings from noded linework.
- `GeoSpatialChannelFrechetDeviation`: Measure ordered centreline deviation using the discrete Frechet distance.

## Constraints

Offline CPU execution only. No downloads, package installation, arbitrary commands or generated algorithms during a tool call.
Retain input/output schemas, upstream algorithms, dependency pins and explicit error handling.

## Expected outputs

Schema-validated numeric JSON, declared units, file artifacts where applicable and source/input/output provenance.

## Source interface and delivery

Call the native function with its declared input object. Standalone examples are in catalog/source_delivery/examples.json.
The implementation and dependency lock remain bound to the recorded upstream source.

### Current availability

`tool_candidates_available_workflow_unverified`

Only the operations listed above passed this release's internal CPU acceptance. This does not establish complete model-driven workflow validation or AI Lab approval.
Scientific platform validation: `not_run`. Lab submission: `not_submitted`.
Deployment and Git status are recorded separately in the release receipt.

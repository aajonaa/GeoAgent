---
name: spatial-kriging-interpolation
description: Ordinary kriging of point measurements with prediction and conditional-variance rasters.
---

# Spatial Kriging Interpolation

## When to use

Use for a requested continuous spatial prediction from geochemical samples or
other point measurements. This is not IDW, a reserve estimate, a deposit
discovery claim, or a substitute for a requested authoritative dataset.

## Required inputs

- A caller-supplied UTF-8 CSV with distinct easting, northing and value columns.
- The actual projected CRS in metres, and the physical value unit.
- Target outer bounds and grid width/height. Use scientifically justified
  resolution; explain a proposed resolution rather than inventing one as fact.
- A variogram family. If parameters are supplied, retain their provenance.
  If omitted, the tool fits them and records this explicitly.

If coordinates are longitude/latitude, obtain a justified metric reprojection
first. Do not label degree coordinates with a projected CRS. If no registered
transformation can do this, use a supported workspace operation or ask for
projected input. Never invent observations or coordinates.

## Tool and method

Load this skill to expose GeoOrdinaryKrigingGrid. Its native object schema is
authoritative. Direct Python callers use the same source function:
legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools.ordinary_kriging_grid(args,
output_dir=...).

Call only when spatial interpolation is required. Confirm files/columns/CRS,
then supply points_path, crs, value_unit and grid. Optional x_field, y_field and
value_field select columns. Variograms are linear, spherical, exponential or
gaussian. Linear parameters are slope+nugget; the others require full
sill+range+nugget, not partial sill. Omitted parameters trigger upstream fitting.

The source rejects duplicate or collinear observations, missing/nonfinite
values and incompatible CRS. Do not repair these by deleting data silently.
The calculation is isotropic, uses exact values at sample coordinates, and has
dense-matrix memory cost. These are method limits, not permissions to
silently simplify the requested analysis.

## Results and continuation

Read the returned prediction_path and variance_path, not guessed filenames.
Both are georeferenced north-up single-band GeoTIFFs. Predictions retain the
input unit; variance has its square. Report the variogram, fitted/supplied
status, grid and extrapolation warnings. Conditional kriging variance is not
measured error or a full uncertainty budget.

For requested mineral-zone summaries, discover and load
fractional_zonal_statistics, then pass the actual prediction artifact and
caller-supplied matching polygons to GeoExactZonalStatistics. Do not repeat
interpolation merely to format the answer. Do not aggregate variance into a
confidence interval without a justified covariance model.

## Acceptance and failure handling

Check successful tool observations, output artifacts, units and requested
deliverables. Local synthetic tests are interface/numerical checks, not
scientific certification. Preserve warnings. Correct explicit failures before
retrying; ask for genuinely missing user data, not information already returned
by the tool. Never deliver a failed calculation as a prediction.

## Source

PyKrige 1.7.3, BSD-3-Clause:
https://github.com/GeoStat-Framework/PyKrige
Dependency definitions: requirements-source-tools.txt.
This skill is used directly by the runtime; formal asset packaging is deferred.

## Source interface and delivery

Call legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools.ordinary_kriging_grid(args, output_dir=...) with a parameter dictionary. The source and runtime use the same implementation; prediction and conditional-variance units and CRS must remain explicit.

### Current availability

Availability: tool_candidates_available_workflow_unverified.
The referenced tools have callable source-interface candidates. This is not
complete skill-workflow validation, scientific certification or receiving-platform
acceptance. Workflow and platform validation remain not_run. Institutional
provider, asset version, licensing confirmation and official protocol version
remain pending; no formal delivery package has been issued.

---
id: scientific_raster_analysis
name: Scientific raster and spatial point analysis
description: "Calculate NDVI, NDWI or NBR indices and change from calibrated multispectral rasters; grid scattered points with a Verde spline or hydrointerp station interpolation; find SREX region membership of points with regionmask. \u9065\u611f\u5f71\u50cf\u3001\u690d\u88ab\u6307\u6570\u3001\u6563\u70b9\u63d2\u503c\u3001\u533a\u57df\u63a9\u819c\u3002"
when_to_use: For raster indices supply calibrated GeoTIFFs and band provenance. For Verde or hydrointerp provide coordinate and value arrays with units and CRS. For SREX point membership provide paired longitude and latitude; raster files are not required for point operations.
required_inputs: [Requested raster or point operation, Real raster files and calibration for indices OR aligned point arrays and units for point operations]
tools: ["GeoRasterIndexAnalysis", "GeoRasterChangeAnalysis", "GeoImageInspect", "GeoExactZonalStatistics", "read_file", "GeoVerdeGrid", "GeoRegionMask", "HydroInterpolationGrid"]
constraints:
  - Do not compute NDVI from ordinary RGB pictures or invent NIR bands.
  - GeoTIFF scale and offset must convert source values to reflectance; preserve that metadata during subsetting.
  - Explicit masks must be QA-derived and grid-aligned. Without a mask disclose clouds and shadows were not removed.
  - Numerical bins are not land-cover classes. Index change does not prove a causal event.
  - New output directories only. Preserve source files and all scientific raster values.
expected_outputs: [Raster operations return scientific GeoTIFF and display layers with provenance, Point operations return structured grids or region IDs with units and limitations]
---
# Raster analysis

Choose a raster or point operation first. The GeoTIFF calibration and band
requirements below apply to raster indices only. Point gridding and SREX
membership accept supplied arrays and do not require satellite imagery.

Read source metadata/provenance to identify spectral roles and calibration.
NDVI=(NIR-red)/(NIR+red); NDWI=(green-NIR)/(green+NIR), not MNDWI;
NBR=(NIR-SWIR2)/(NIR+SWIR2). GeoRasterIndexAnalysis applies each band's
stored scale/offset first. Negative reflectance, masks and zero denominators are
excluded explicitly. Calibrate upstream if the dataset stores calibration only
in a sidecar; do not merely write a convincing calibration_source string.

Pass optional real RGB bands for a true-color reference layer. Preview stretches
are display-only. Read scientific values from values.tif, not PNG colors.
For two dates run index analysis separately, then GeoRasterChangeAnalysis on
their values.tif outputs. It computes after minus before on an exactly shared
grid and rejects mismatches rather than silently reprojecting.

For explicit polygon zones use GeoExactZonalStatistics on values.tif and the
actual supplied polygon file, with documented CRS and dimensionless units.
Use actual result paths and computed numbers in the answer. The frontend reads
analysis.geoanalysis.json for a synchronized layer viewer; do not emit UI JSON
or hand-written HTML. Explain NoData, calibration, QA and area limitations.

For scattered point interpolation, GeoVerdeGrid provides a bounded Verde spline
operation and HydroInterpolationGrid provides hydrointerp grid interpolation.
Both require equal-length coordinates and values; HydroInterpolationGrid also
requires an explicit CRS. For point membership checks, GeoRegionMask pairs each
longitude with the latitude at the same index and returns upstream region IDs;
it does not repair geometries or reproject coordinates.

## Source interface and delivery

Call the canonical `geological_agent.scientific_imaging.operate(name, args,
workspace=Path(...))` with a Python dictionary matching the registered JSON
schema. `name` is GeoRasterIndexAnalysis or GeoRasterChangeAnalysis. Paths stay
relative to workspace; outputs use a new directory. No model or UI is required
for direct calls. Runtime helpers are optional; GeoExactZonalStatistics remains
a separately registered professional tool for explicit polygon-zone requests.
See catalog/source_delivery/SCIENTIFIC_IMAGING.md for dependencies and examples.

### Current availability

tool_candidates_available_workflow_unverified. The tool candidates are native
and callable, but this is not an official platform or complete-workflow
acceptance claim. Retain source hashes, calibration, mask and grid metadata.

## Preserved source-specific scientific constraints

The following original guidance applies to the original operations only, not to unrelated array-based calculations.

# Raster analysis

Read source metadata/provenance to identify spectral roles and calibration.
NDVI=(NIR-red)/(NIR+red); NDWI=(green-NIR)/(green+NIR), not MNDWI;
NBR=(NIR-SWIR2)/(NIR+SWIR2). GeoRasterIndexAnalysis applies each band's
stored scale/offset first. Negative reflectance, masks and zero denominators are
excluded explicitly. Calibrate upstream if the dataset stores calibration only
in a sidecar; do not merely write a convincing calibration_source string.

Pass optional real RGB bands for a true-color reference layer. Preview stretches
are display-only. Read scientific values from values.tif, not PNG colors.
For two dates run index analysis separately, then GeoRasterChangeAnalysis on
their values.tif outputs. It computes after minus before on an exactly shared
grid and rejects mismatches rather than silently reprojecting.

For explicit polygon zones use GeoExactZonalStatistics on values.tif and the
actual supplied polygon file, with documented CRS and dimensionless units.
Use actual result paths and computed numbers in the answer. The frontend reads
analysis.geoanalysis.json for a synchronized layer viewer; do not emit UI JSON
or hand-written HTML. Explain NoData, calibration, QA and area limitations.

## Source interface and delivery

Call the canonical `geological_agent.scientific_imaging.operate(name, args,
workspace=Path(...))` with a Python dictionary matching the registered JSON
schema. `name` is GeoRasterIndexAnalysis or GeoRasterChangeAnalysis. Paths stay
relative to workspace; outputs use a new directory. No model or UI is required
for direct calls. Runtime helpers are optional; GeoExactZonalStatistics remains
a separately registered professional tool for explicit polygon-zone requests.
See catalog/source_delivery/SCIENTIFIC_IMAGING.md for dependencies and examples.

### Current availability

tool_candidates_available_workflow_unverified. The tool candidates are native
and callable, but this is not an official platform or complete-workflow
acceptance claim. Retain source hashes, calibration, mask and grid metadata.

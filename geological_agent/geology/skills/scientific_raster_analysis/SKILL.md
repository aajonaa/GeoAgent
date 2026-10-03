---
id: scientific_raster_analysis
name: Scientific raster indices and change analysis
description: NDVI NDWI NBR multispectral satellite remote sensing raster change and interactive layers. 遥感影像 植被指数 水体 烧毁指数 多期变化 专题图。
when_to_use: Actual calibrated multispectral GeoTIFFs or comparable single-band rasters are available and the user wants spatial analysis, statistics and visual layers.
required_inputs: [Actual GeoTIFF files, Verified spectral band mapping and calibration source, Requested index or change threshold]
tools: [GeoRasterIndexAnalysis, GeoRasterChangeAnalysis, GeoImageInspect, GeoExactZonalStatistics, read_file]
constraints:
  - Do not compute NDVI from ordinary RGB pictures or invent NIR bands.
  - GeoTIFF scale and offset must convert source values to reflectance; preserve that metadata during subsetting.
  - Explicit masks must be QA-derived and grid-aligned. Without a mask disclose clouds and shadows were not removed.
  - Numerical bins are not land-cover classes. Index change does not prove a causal event.
  - New output directories only. Preserve source files and all scientific raster values.
expected_outputs: [Scientific GeoTIFF, Aligned display layers, Class statistics CSV, Hashed provenance manifest]
---
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

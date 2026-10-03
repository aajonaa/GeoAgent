---
id: map_color_digitization
name: Map legend-color region extraction
description: Digitize explicit colored map regions into masks and candidate polygons. 地质图 图例 地层 色块 提取 候选边界 矢量化。
when_to_use: A map image and explicit legend colors or an inspectable legend are available; the user requests candidate colored-region extraction rather than automatic geological identification.
required_inputs: [Map image, Legend labels and RGB samples, Map-only pixel ROI]
tools: [GeoMapColorExtract, GeoImageInspect, GeoImageAnalyze, read_file]
constraints:
  - Labels are user/source descriptions, not a newly inferred rock or age classification.
  - Exclude the legend and margins using an explicit pixel ROI.
  - No geographic coordinates or physical area without a genuinely aligned reference raster.
  - Nearest-color segmentation is a candidate method; hatching and text can interrupt regions.
expected_outputs: [Class mask, Transparent overlay, Candidate vectors, Class statistics, Provenance manifest]
---
# Map color digitization

Inspect the actual image and legend. Use GeoImageAnalyze for visual reading only
when needed; do not mistake its descriptions for exact pixel samples. If labels,
colors or ROI cannot be established, ask the user for those specific inputs.
GeoMapColorExtract uses explicit RGB distances and 4-connected components.
Exact color-distance ties are excluded; small components are counted and removed.

Without georeferencing the vector output is regions.pixel.json in image pixel
coordinates, deliberately not a geographic GeoJSON. An optional reference raster
must actually be aligned with the EXIF-oriented image. Matching dimensions alone
are insufficient. With a valid reference, geographic vectors use EPSG:4326.

Show the original/overlay and label all extracted units as candidates requiring
inspection. This method cannot identify faults, lithology or geologic age from
color alone. Do not promise universal map segmentation.

## Source interface and delivery

Call `geological_agent.scientific_imaging.operate("GeoMapColorExtract", args,
workspace=Path(...))` with the registered object schema and task-relative paths.
No model is required when legend labels, RGB samples and ROI are supplied.
Visual inspection helpers are optional and must not invent map semantics.
See catalog/source_delivery/SCIENTIFIC_IMAGING.md for dependencies and examples.

### Current availability

tool_candidates_available_workflow_unverified. Native color-region extraction
is available; complete workflows and the receiving platform are not certified.
All extracted regions remain candidates, not inferred geological units.

---
id: plot_curve_digitization
name: Calibrated scientific curve digitization
description: Extract one colored curve from a figure using known axis ticks; produce data CSV and a reconstructed plot. 论文 图片 图表 曲线 数字化 数据提取 坐标轴。
when_to_use: A single identifiable colored curve and legible linear/logarithmic axis calibration are available.
required_inputs: [Figure image, Plot-only ROI, Curve RGB and tolerance, Two known anchors per axis with units]
tools: [GeoPlotDigitize, GeoImageInspect, GeoImageAnalyze, read_file]
constraints:
  - Do not guess tick values or units; request readable axes or user calibration.
  - This is colored-curve extraction, not arbitrary chart understanding or multi-curve disentanglement.
  - Ambiguous columns remain missing; no interpolation or silent repair.
  - Pixel thickness is not a statistical confidence interval.
expected_outputs: [Digitized CSV, Selected-pixel overlay, Reconstructed plot, Calibration and provenance manifest]
---
# Curve digitization

Use EXIF-oriented pixel coordinates. The X axis uses image columns and the Y axis
uses image rows increasing downward. Provide actual tick positions and values;
descending Y anchors are valid. Log10 axes require positive numeric values.
Anchor positions must bracket the requested ROI to prevent extrapolation.

Choose one curve's RGB color and a tolerance, excluding axes, labels and legends
from the ROI. The tool reports a median row per unambiguous matched column,
retaining the observed vertical pixel span in physical Y units. Disconnected
matches and overly thick columns are omitted and counted. The reconstructed
plot shows extracted points without joining gaps or fabricating samples.

Report units, extraction coverage and missing columns. Distinguish digitized
approximations from the paper's original numerical data.

## Source interface and delivery

Call `geological_agent.scientific_imaging.operate("GeoPlotDigitize", args,
workspace=Path(...))` with the registered object schema and task-relative paths.
No model is required for supplied curve colors, ROI and axis calibration.
See catalog/source_delivery/SCIENTIFIC_IMAGING.md for dependencies and examples.

### Current availability

tool_candidates_available_workflow_unverified. Native curve extraction is
available, but complete workflows and official platform validation remain
unverified. Preserve missing columns, calibration units and pixel uncertainty.

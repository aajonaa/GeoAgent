---
id: expansion501_geophysics_waveform_quality
name: "Calibrated waveform quality and event detection"
description: "CPU-accepted scientific operations for Calibrated waveform quality and event detection"
tools:
  - GeoSeismicInstrumentDeconvolution
  - GeoSeismicSTALTADetection
  - GeoSeismicTemplateDetection
  - GeoSeismicProbabilisticNoise
  - GeoSeismicWaveformTFMisfit
---

# Calibrated waveform quality and event detection

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

- `GeoSeismicInstrumentDeconvolution`: Recover calibrated velocity from counts using a supplied single-stage, stable PZ response covering the entire record epoch.
- `GeoSeismicSTALTADetection`: Detect transient windows using classic energy STA/LTA and explicit hysteresis thresholds.
- `GeoSeismicTemplateDetection`: Detect repeat events using a supplied multichannel waveform template and normalized similarity.
- `GeoSeismicProbabilisticNoise`: Accumulate calibrated acceleration PSD segments and bounded histogram counts for one stationary instrument epoch.
- `GeoSeismicWaveformTFMisfit`: Separate amplitude-envelope and phase discrepancies of aligned seismic waveforms using a fixed Morlet time-frequency transform.

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

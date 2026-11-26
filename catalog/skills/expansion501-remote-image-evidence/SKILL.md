---
id: expansion501_remote_image_evidence
name: "expansion501-remote-image-evidence"
description: "CPU-accepted operations for expansion501-remote-image-evidence; use only the listed available subset."
tools:
  - GeoRemotePhaseUnwrap
  - GeoRemoteDenseOpticalFlow
  - GeoRemoteProjectiveTiePoints
  - GeoRemoteTemplateLocate
  - GeoRemoteScaleSpaceBlobs
  - GeoRemoteHoughLineEvidence
---

# expansion501-remote-image-evidence

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

- `GeoRemotePhaseUnwrap`: Two-dimensional wrapped-phase recovery
- `GeoRemoteDenseOpticalFlow`: Dense spatially varying optical image motion
- `GeoRemoteProjectiveTiePoints`: Projective tie-point camera registration
- `GeoRemoteTemplateLocate`: Normalized spatial-template localization
- `GeoRemoteScaleSpaceBlobs`: LoG scale-space bright-feature detection
- `GeoRemoteHoughLineEvidence`: Hough voting evidence for straight image lineaments

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

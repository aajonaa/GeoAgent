---
id: expansion501_geophysics_potential_interpretation
name: "Potential-field continuation and source interpretation"
description: "Distinguish field interpolation/continuation from ideal-source location and material-property inversion. Preserve spatial sampling, field/gradient units and magnetic directions. Compare diagnostic outputs and conditioning before interpreting any anomaly as a geological contact or body."
when_to_use: "Potential-field continuation and source interpretation with supplied measurements/models and explicit units"
tools:
- GeoPotentialEulerSourceLocation
- GeoPotentialEquivalentSources
- GeoPotentialUpwardContinuation
- GeoMagneticReductionToPole
- GeoPotentialEdgeAttributes
- GeoMagneticSusceptibilityInversion
required_inputs:
- Strict tool JSON, explicit units, coordinate/component conventions and input_source
constraints:
- No invented calibration, uncertainty, grade or reserves
- Preserve physical assumptions, support masks and convergence diagnostics
- Private CPU environment only, no GPU or runtime installation
expected_outputs:
- Numeric JSON with units and shared provenance; artifacts is empty
---

# Potential-field continuation and source interpretation

## When to use

Distinguish field interpolation/continuation from ideal-source location and material-property inversion. Preserve spatial sampling, field/gradient units and magnetic directions. Compare diagnostic outputs and conditioning before interpreting any anomaly as a geological contact or body.

## Required inputs

Each tool has a closed schema. Field names encode physical units and ordered axes. All bundled examples are SYNTHETIC and unexecuted; they are not geological observations or passing receipts.

## Workflow

Distinguish field interpolation/continuation from ideal-source location and material-property inversion. Preserve spatial sampling, field/gradient units and magnetic directions. Compare diagnostic outputs and conditioning before interpreting any anomaly as a geological contact or body.

## Tools and examples

### GeoPotentialEulerSourceLocation

Estimate one ideal-source location and constant base level from field values and all three measured spatial derivatives.

Example: `assets/expansion501-geophysics/GeoPotentialEulerSourceLocation.json`. Limitations: Single ideal homogeneous source per window; structural index conditions depth; no calibrated position uncertainty.

### GeoPotentialEquivalentSources

Fit damped equivalent sources to irregular-altitude harmonic field measurements and predict specified positions.

Example: `assets/expansion501-geophysics/GeoPotentialEquivalentSources.json`. Limitations: <=128 observations/predictions and 64 sources; below-plane restriction; no geological interpretation of source coefficients.

### GeoPotentialUpwardContinuation

Continue a regular planar potential-field grid upward with the harmonic spectral transfer.

Example: `assets/expansion501-geophysics/GeoPotentialUpwardContinuation.json`. Limitations: No padding, terrain-following geometry or downward continuation.

### GeoMagneticReductionToPole

Transform a planar magnetic anomaly to pole-equivalent inducing-field and magnetization directions.

Example: `assets/expansion501-geophysics/GeoMagneticReductionToPole.json`. Limitations: Ill-conditioned equatorial RTP explicitly unsupported; no invented stabilization.

### GeoPotentialEdgeAttributes

Compute bundled total-gradient amplitude and tilt of a complete planar potential-field anomaly grid.

Example: `assets/expansion501-geophysics/GeoPotentialEdgeAttributes.json`. Limitations: Periodic grid and spectral edge effects; gradients do not establish geological contacts.

### GeoMagneticSusceptibilityInversion

Recover bounded induced-only scalar susceptibility from TMI anomalies using a supplied inducing field.

Example: `assets/expansion501-geophysics/GeoMagneticSusceptibilityInversion.json`. Limitations: Fixed CPU SimPEG ProjectedGNCG, bounded mesh and iterations; no caller solver/callback/code. Convergence may be iteration_limit or uncertified stop. Conditional regularized estimate, not unique geology or posterior uncertainty. Private pinned environment and parent worker registration required; not run, deployed, submitted or AI-Lab certified.

## Source interface and delivery

Fixed named functions in `geological_agent.geology.expansion501_geophysics` accept `args` dict or JSON-object string through `collection_contracts.operation`. Parent stages the catalog and fixed module allowlist. No `output_dir` or file artifacts; shared contracts add input/source hashes, installed pins, provenance and `artifacts=[]`. No arbitrary shell, module, function, callback or dependency installation.

## Expected outputs and interpretation

Read `values`, `units` and `diagnostics` together. Null means explicitly unsupported/undefined support, not a measured zero. A returned model or zero residual is not proof of uniqueness or convergence. Report the actual upstream stop/independent stationarity result and conditional uncertainty.

## Dependencies and licensing

Use the exact per-package requirements in `catalog/source_delivery/expansion501-20261026/groups/geophysics/requirements-*.txt` in a private CPU environment, retaining baseline pins. Native wheel/build identity and the full transitive distribution lock remain parent acceptance prerequisites. ObsPy/PyLops LGPL terms and all other upstream licenses remain in force; adapter redistribution license review is pending.

## Failure and handoff

Return native ScientificToolError failures, do not replace upstream kernels or silently fill missing physics. Parent owns scientific tests, shared dispatch/registry, transport approval and release. See adaptation-status.json for blocked assignments, which are not registered.

## Validation and availability

source_revised_unverified; formal_eligible=false; acceptance_pending. NOT TESTED / NOT DEPLOYED / NOT SUBMITTED. Availability: source_candidates_authored_acceptance_pending. Deployment status: not_deployed. Submission status: not_submitted. Workflow validation: not_run. Model workflow validation: not_run. Platform validation: not_run. Receiving AI Lab approval: pending. Internal schema conformance is NOT receiving AI Lab certification.

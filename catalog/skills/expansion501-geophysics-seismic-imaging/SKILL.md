---
id: expansion501_geophysics_seismic_imaging
name: "Bounded seismic imaging and elastic inversion"
description: "Confirm geometry, wavelet normalization and the supplied low-frequency/background model. Use Kirchhoff LSM for reflectivity imaging, post/prestack inverse operators for conditional property estimation, and pressure/velocity wavefield operators for supported marine data. Inspect stop/residual/stationarity diagnostics before any interpretation."
when_to_use: "Bounded seismic imaging and elastic inversion with supplied measurements/models and explicit units"
tools:
- GeoSeismicLeastSquaresMigration
- GeoSeismicPoststackImpedanceInversion
- GeoSeismicPrestackElasticInversion
- GeoSeismicReceiverDeghosting
- GeoSeismicUpDownWavefieldSeparation
- GeoSeismicMultidimensionalDeconvolution
required_inputs:
- Strict tool JSON, explicit units, coordinate/component conventions and input_source
constraints:
- No invented calibration, uncertainty, grade or reserves
- Preserve physical assumptions, support masks and convergence diagnostics
- Private CPU environment only, no GPU or runtime installation
expected_outputs:
- Numeric JSON with units and shared provenance; artifacts is empty
---

# Bounded seismic imaging and elastic inversion

## When to use

Confirm geometry, wavelet normalization and the supplied low-frequency/background model. Use Kirchhoff LSM for reflectivity imaging, post/prestack inverse operators for conditional property estimation, and pressure/velocity wavefield operators for supported marine data. Inspect stop/residual/stationarity diagnostics before any interpretation.

## Required inputs

Each tool has a closed schema. Field names encode physical units and ordered axes. All bundled examples are SYNTHETIC and unexecuted; they are not geological observations or passing receipts.

## Workflow

Confirm geometry, wavelet normalization and the supplied low-frequency/background model. Use Kirchhoff LSM for reflectivity imaging, post/prestack inverse operators for conditional property estimation, and pressure/velocity wavefield operators for supported marine data. Inspect stop/residual/stationarity diagnostics before any interpretation.

## Tools and examples

### GeoSeismicLeastSquaresMigration

Recover a regularized reflectivity image with fixed NumPy Kirchhoff LSM and constant-background analytic travel times.

Example: `assets/expansion501-geophysics/GeoSeismicLeastSquaresMigration.json`. Limitations: Constant-background analytic rays only, no Devito/GPU/full-waveform velocity inversion. Fixed internal LSQR callback captures real stop code, iterations and residual; image amplitude is not absolute impedance.

### GeoSeismicPoststackImpedanceInversion

Recover absolute acoustic impedance conditional on a supplied positive background and known wavelet using the upstream log-impedance inverse operator.

Example: `assets/expansion501-geophysics/GeoSeismicPoststackImpedanceInversion.json`. Limitations: Explicit half-factor in wavelet; upstream iteration count unavailable, actual forward/adjoint stationarity reported.

### GeoSeismicPrestackElasticInversion

Jointly estimate Vp, Vs and density from angular seismic gathers with a fixed weak-contrast Aki-Richards inverse operator.

Example: `assets/expansion501-geophysics/GeoSeismicPrestackElasticInversion.json`. Limitations: Upstream fixed Aki-Richards, no arbitrary linearization callable; no invented low-frequency properties.

### GeoSeismicReceiverDeghosting

Recover upgoing/downgoing pressure using a fixed flat-receiver water-surface ghost operator and explicit direct-arrival pressure.

Example: `assets/expansion501-geophysics/GeoSeismicReceiverDeghosting.json`. Limitations: Fixed pressure kind, pad4,taper3; direct wave must be supplied, including explicit zeros if already removed. Real LSQR stop diagnostics retained.

### GeoSeismicUpDownWavefieldSeparation

Separate directional acoustic pressure wavefields using synchronized pressure and positive-down vertical particle velocity.

Example: `assets/expansion501-geophysics/GeoSeismicUpDownWavefieldSeparation.json`. Limitations: Fixed analytical decomposition, critical95%, taper3; no iterative solver or arbitrary transform.

### GeoSeismicMultidimensionalDeconvolution

Recover a virtual-source pressure response from a calibrated multidimensional seismic convolution kernel with explicit temporal/spatial quadrature.

Example: `assets/expansion501-geophysics/GeoSeismicMultidimensionalDeconvolution.json`. Limitations: Kernel units fixed1/(m*s), wavefield Pa; two-sided response time origin explicit; LSQR count not exposed upstream, forward/adjoint stationarity reported.

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

---
id: github_geology_structural_fabrics
name: "Structural fabrics and field inference"
description: "Estimate Lisle joint foliation-lineation fabric from orthogonal measured pairs. Estimate the unique cylindrical-fold axis from the girdle of measured plane poles. Estimate a Fisher population mean and confidence cone for directed structural measurements. Estimate an antipodally invariant confidence ellipse for the major axis of an anisotropic fabric. Infer planar strain from measured elliptical markers using Rf/phi, with Robin log-tensor comparison. Derive fault-slip kinematic compression/extension bisector axes from measured plane and directed slip pairs."
when_to_use: "Structural fabrics and field inference from explicit supplied geological measurements"
tools:
- GeoAPSGPairFabricTensor
- GeoAPSGFoldAxis
- GeoAPSGFisherDirectionalConfidence
- GeoAPSGBinghamAxialConfidence
- GeoAPSGMarkerStrainEstimate
- GeoAPSGFaultKinematicAxes
required_inputs:
- Explicit measured data, units, source and scientific assumptions
constraints:
- Use only the operation needed for the question
- Preserve missingness, units, source hashes and uncertainty
- Do not infer ore grade, reserves or mineral identity
- No installation, online fetch or arbitrary Python at call time
expected_outputs:
- Numeric scientific evidence and native provenance
---

# Structural fabrics and field inference

## When to use

Estimate Lisle joint foliation-lineation fabric from orthogonal measured pairs. Estimate the unique cylindrical-fold axis from the girdle of measured plane poles. Estimate a Fisher population mean and confidence cone for directed structural measurements. Estimate an antipodally invariant confidence ellipse for the major axis of an anisotropic fabric. Infer planar strain from measured elliptical markers using Rf/phi, with Robin log-tensor comparison. Derive fault-slip kinematic compression/extension bisector axes from measured plane and directed slip pairs.

## Required inputs

Use the exact strict input schema and supplied example for the selected operation. Every call needs a caller-declared data_source. Explicit units, structural conventions, sample alignment and stated geological assumptions are mandatory; the source declaration is not independent authentication.

## Procedure

1. Select the operation matching the scientific question and read its limitations.
2. Obtain the declared measurements, units, reference compositions or model parameters.
3. Check scientific scope and missingness; never replace unavailable measurements with synthetic values.
4. Invoke the named native function with args as a dictionary or JSON object string.
5. Preserve result units and all native provenance hashes. Explain the result within its assumptions.

## Tools and synthetic examples

### GeoAPSGPairFabricTensor

Estimate Lisle joint foliation-lineation fabric from orthogonal measured pairs.

Entrypoint: `geological_agent.geology.github_expansion_geology:paired_fabric_tensor`. Example: `assets/github-expansion-geology/GeoAPSGPairFabricTensor.json`. All examples are explicitly SYNTHETIC.

Vectors must be orthogonal within 1e-8 cosine. No automatic adjustment of field measurements. The shifted tensor is a fabric descriptor, not strain magnitude.

Upstream source: [pinned implementation](https://github.com/ondrolexa/apsg/blob/f9f45a52d60521ba37f326a85645df3dee74272e/src/apsg/feature/_tensor3.py).

### GeoAPSGFoldAxis

Estimate the unique cylindrical-fold axis from the girdle of measured plane poles.

Entrypoint: `geological_agent.geology.github_expansion_geology:cylindrical_fold_axis`. Example: `assets/github-expansion-geology/GeoAPSGFoldAxis.json`. All examples are explicitly SYNTHETIC.

Assumes approximately cylindrical folding. A unique mathematical axis is not evidence that the outcrop satisfies this geological assumption.

Upstream source: [pinned implementation](https://github.com/ondrolexa/apsg/blob/f9f45a52d60521ba37f326a85645df3dee74272e/src/apsg/feature/_tensor3.py).

### GeoAPSGFisherDirectionalConfidence

Estimate a Fisher population mean and confidence cone for directed structural measurements.

Entrypoint: `geological_agent.geology.github_expansion_geology:fisher_directional_confidence`. Example: `assets/github-expansion-geology/GeoAPSGFisherDirectionalConfidence.json`. All examples are explicitly SYNTHETIC.

Independent Fisher-distributed directed measurements are assumed. Rejects zero resultant and perfect alignment, where this release gives undefined or infinite statistics.

Upstream source: [pinned implementation](https://github.com/ondrolexa/apsg/blob/f9f45a52d60521ba37f326a85645df3dee74272e/src/apsg/feature/_container.py).

### GeoAPSGBinghamAxialConfidence

Estimate an antipodally invariant confidence ellipse for the major axis of an anisotropic fabric.

Entrypoint: `geological_agent.geology.github_expansion_geology:bingham_axial_confidence`. Example: `assets/github-expansion-geology/GeoAPSGBinghamAxialConfidence.json`. All examples are explicitly SYNTHETIC.

Uses upstream large-sample Bingham confidence statistic. Small samples and anisotropy can yield counterintuitive semi-axis ordering; full rank and distinct eigenvalues are required.

Upstream source: [pinned implementation](https://github.com/ondrolexa/apsg/blob/f9f45a52d60521ba37f326a85645df3dee74272e/src/apsg/feature/_container.py).

### GeoAPSGMarkerStrainEstimate

Infer planar strain from measured elliptical markers using Rf/phi, with Robin log-tensor comparison.

Entrypoint: `geological_agent.geology.github_expansion_geology:marker_strain_estimate`. Example: `assets/github-expansion-geology/GeoAPSGMarkerStrainEstimate.json`. All examples are explicitly SYNTHETIC.

Strain interpretation assumes suitable passive markers and an initially unpreferred population; Rf/phi and Robin are reported together as one task, not counted as separate methods.

Upstream source: [pinned implementation](https://github.com/ondrolexa/apsg/blob/f9f45a52d60521ba37f326a85645df3dee74272e/src/apsg/feature/_container.py).

### GeoAPSGFaultKinematicAxes

Derive fault-slip kinematic compression/extension bisector axes from measured plane and directed slip pairs.

Entrypoint: `geological_agent.geology.github_expansion_geology:fault_kinematic_axes`. Example: `assets/github-expansion-geology/GeoAPSGFaultKinematicAxes.json`. All examples are explicitly SYNTHETIC.

Normal and slip are supplied as an oriented compatible pair. P/T axes are kinematic bisectors and do not determine stress magnitudes or a unique regional paleostress.

Upstream source: [pinned implementation](https://github.com/ondrolexa/apsg/blob/f9f45a52d60521ba37f326a85645df3dee74272e/src/apsg/feature/_geodata.py).

## Interpretation and constraints

These calls use named upstream scientific kernels. A numerical result does not authenticate input data or establish geological representativeness. No tool infers ore grade, reserves or mineral presence. Synthetic examples are numerical oracles only. Units and structural/depth conventions are part of the measurement model.

## Native errors

ScientificToolError exposes code, message and retryable. Correct invalid arguments or unsupported assumptions before retrying. missing_dependency and incompatible_dependency require the parent-controlled private worker; the tool never changes the environment. A failed scientific kernel returns an error, never a local substitute formula or placeholder value.

## Source interface and delivery

Kind: github_expansion_geology. Module: geological_agent.geology.github_expansion_geology. Functions accept args=dict or args=JSON-object-string through collection_contracts.operation. No operation in this Skill requires output_dir or writes artifacts; the LAS reader alone reads one declared local file. Native provenance records pinned dependencies, source commit, input hash, implementation hash, contract hash, and empty artifact hashes.

## Acceptance evidence

Positive independent analytic oracles, per-operation negative constraints and provenance assertions are authored in `tests_local/test_github_expansion_geology.py` and `catalog/source_delivery/github-expansion-20261025/groups/geology/oracle-cases.json`. They have NOT BEEN RUN. Package import/ABI compatibility has NOT BEEN TESTED.

## Current availability

Source authored and generated metadata only. NOT TESTED / NOT DEPLOYED / NOT SUBMITTED. Unit, workflow, model-workflow and platform validation: not_run. Receiving-lab approval and adapter license: pending. Parent owns fixed module whitelist, worker dispatch, registry integration and CPU acceptance. Existing online229 is unchanged.

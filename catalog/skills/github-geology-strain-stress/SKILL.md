---
id: github_geology_strain_stress
name: "Finite strain, flow and fracture stress"
description: "Recover principal stretches, Hencky strains and Flinn shape from a measured finite deformation gradient. Separate rigid rotation from finite material stretch in a structural deformation gradient. Integrate a constant tectonic velocity gradient over an explicit duration using the upstream matrix exponential. Quantify noncoaxial deformation through strain rate, spin and the kinematic vorticity number. Resolve measured stress onto fracture planes, retaining normal compression, shear magnitude and physical traction. Assess frictional reactivation of closed fractures under declared pore pressure and Mohr-Coulomb parameters."
when_to_use: "Finite strain, flow and fracture stress from explicit supplied geological measurements"
tools:
- GeoAPSGFiniteStrainEllipsoid
- GeoAPSGDeformationPolarSplit
- GeoAPSGVelocityGradientEvolution
- GeoAPSGKinematicVorticity
- GeoAPSGFractureTraction
- GeoAPSGFaultReactivation
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

# Finite strain, flow and fracture stress

## When to use

Recover principal stretches, Hencky strains and Flinn shape from a measured finite deformation gradient. Separate rigid rotation from finite material stretch in a structural deformation gradient. Integrate a constant tectonic velocity gradient over an explicit duration using the upstream matrix exponential. Quantify noncoaxial deformation through strain rate, spin and the kinematic vorticity number. Resolve measured stress onto fracture planes, retaining normal compression, shear magnitude and physical traction. Assess frictional reactivation of closed fractures under declared pore pressure and Mohr-Coulomb parameters.

## Required inputs

Use the exact strict input schema and supplied example for the selected operation. Every call needs a caller-declared data_source. Explicit units, structural conventions, sample alignment and stated geological assumptions are mandatory; the source declaration is not independent authentication.

## Procedure

1. Select the operation matching the scientific question and read its limitations.
2. Obtain the declared measurements, units, reference compositions or model parameters.
3. Check scientific scope and missingness; never replace unavailable measurements with synthetic values.
4. Invoke the named native function with args as a dictionary or JSON object string.
5. Preserve result units and all native provenance hashes. Explain the result within its assumptions.

## Tools and synthetic examples

### GeoAPSGFiniteStrainEllipsoid

Recover principal stretches, Hencky strains and Flinn shape from a measured finite deformation gradient.

Entrypoint: `geological_agent.geology.github_expansion_geology:finite_strain_ellipsoid`. Example: `assets/github-expansion-geology/GeoAPSGFiniteStrainEllipsoid.json`. All examples are explicitly SYNTHETIC.

The deformation gradient must be externally measured/derived. No inversion from orientation alone; singular/reflection gradients rejected. Flinn k is null where its denominator vanishes.

Upstream source: [pinned implementation](https://github.com/ondrolexa/apsg/blob/f9f45a52d60521ba37f326a85645df3dee74272e/src/apsg/feature/_tensor3.py).

### GeoAPSGDeformationPolarSplit

Separate rigid rotation from finite material stretch in a structural deformation gradient.

Entrypoint: `geological_agent.geology.github_expansion_geology:deformation_polar_split`. Example: `assets/github-expansion-geology/GeoAPSGDeformationPolarSplit.json`. All examples are explicitly SYNTHETIC.

Polar rotation describes the supplied finite mapping, not the entire tectonic rotation history; requires a nonsingular orientation-preserving gradient.

Upstream source: [pinned implementation](https://github.com/ondrolexa/apsg/blob/f9f45a52d60521ba37f326a85645df3dee74272e/src/apsg/feature/_tensor3.py).

### GeoAPSGVelocityGradientEvolution

Integrate a constant tectonic velocity gradient over an explicit duration using the upstream matrix exponential.

Entrypoint: `geological_agent.geology.github_expansion_geology:velocity_gradient_evolution`. Example: `assets/github-expansion-geology/GeoAPSGVelocityGradientEvolution.json`. All examples are explicitly SYNTHETIC.

Constant homogeneous velocity gradient is assumed; variable tectonic histories are unsupported. Frobenius norm times duration is bounded by 20.

Upstream source: [pinned implementation](https://github.com/ondrolexa/apsg/blob/f9f45a52d60521ba37f326a85645df3dee74272e/src/apsg/feature/_tensor3.py).

### GeoAPSGKinematicVorticity

Quantify noncoaxial deformation through strain rate, spin and the kinematic vorticity number.

Entrypoint: `geological_agent.geology.github_expansion_geology:kinematic_vorticity`. Example: `assets/github-expansion-geology/GeoAPSGKinematicVorticity.json`. All examples are explicitly SYNTHETIC.

Requires nonzero symmetric strain rate. Pure rigid rotation has infinite Wk and is explicitly rejected rather than clipped.

Upstream source: [pinned implementation](https://github.com/ondrolexa/apsg/blob/f9f45a52d60521ba37f326a85645df3dee74272e/src/apsg/feature/_tensor3.py).

### GeoAPSGFractureTraction

Resolve measured stress onto fracture planes, retaining normal compression, shear magnitude and physical traction.

Entrypoint: `geological_agent.geology.github_expansion_geology:fracture_traction`. Example: `assets/github-expansion-geology/GeoAPSGFractureTraction.json`. All examples are explicitly SYNTHETIC.

APSG must already use its default geological compression-positive convention. Physical traction vectors remain tension-positive; the adapter never changes process-global settings.

Upstream source: [pinned implementation](https://github.com/ondrolexa/apsg/blob/f9f45a52d60521ba37f326a85645df3dee74272e/src/apsg/feature/_tensor3.py).

### GeoAPSGFaultReactivation

Assess frictional reactivation of closed fractures under declared pore pressure and Mohr-Coulomb parameters.

Entrypoint: `geological_agent.geology.github_expansion_geology:fault_reactivation`. Example: `assets/github-expansion-geology/GeoAPSGFaultReactivation.json`. All examples are explicitly SYNTHETIC.

Assumes isotropic pressure, Biot/Terzaghi coefficient one and a closed frictional plane. Rejects hydrostatic stress and tensile/open-fracture cases; not a site-specific stability certification.

Upstream source: [pinned implementation](https://github.com/ondrolexa/apsg/blob/f9f45a52d60521ba37f326a85645df3dee74272e/src/apsg/feature/_tensor3.py).

## Interpretation and constraints

These calls use named upstream scientific kernels. A numerical result does not authenticate input data or establish geological representativeness. No tool infers ore grade, reserves or mineral presence. Synthetic examples are numerical oracles only. Units and structural/depth conventions are part of the measurement model.

## Native errors

ScientificToolError exposes code, message and retryable. Correct invalid arguments or unsupported assumptions before retrying. missing_dependency and incompatible_dependency require the parent-controlled private worker; the tool never changes the environment. A failed scientific kernel returns an error, never a local substitute formula or placeholder value.

## Source interface and delivery

Kind: github_expansion_geology. Module: geological_agent.geology.github_expansion_geology. Functions accept args=dict or args=JSON-object-string through collection_contracts.operation. No operation in this Skill requires output_dir or writes artifacts; the LAS reader alone reads one declared local file. Native provenance records pinned dependencies, source commit, input hash, implementation hash, contract hash, and empty artifact hashes.

## Acceptance evidence

Positive independent analytic oracles, per-operation negative constraints and provenance assertions are authored in `tests_local/test_github_expansion_geology.py` and `catalog/source_delivery/github-expansion-20261025/groups/geology/oracle-cases.json`. They have NOT BEEN RUN. This r2 source has NOT BEEN TESTED. Parent reports a separate successful SQLAlchemy 1.4.54 / APSG 2.0.6 / ObsPy 1.4.2 joint import; that is not scientific acceptance of these operations.

## Current availability

Source authored and generated metadata only. NOT TESTED / NOT DEPLOYED / NOT SUBMITTED. Unit, workflow, model-workflow and platform validation: not_run. Receiving-lab approval and adapter license: pending. Bingham axial confidence and CIPW normative mineralogy are blocked and excluded from all five active Skills; see the group blocked-operations.json. Parent owns fixed module whitelist, worker dispatch, registry integration and CPU acceptance. Existing online229 is unchanged.

### Native call bindings

Use the registered native operation with its declared JSON input schema. The following bindings come from catalog/registry.json; use catalog/source_delivery/examples.json for exact accepted argument examples. Do not substitute guessed arguments, units or scientific algorithms.

| Native tool | Source callable |
| --- | --- |
| `GeoAPSGFiniteStrainEllipsoid` | `geological_agent.geology.github_expansion_geology:finite_strain_ellipsoid` |
| `GeoAPSGDeformationPolarSplit` | `geological_agent.geology.github_expansion_geology:deformation_polar_split` |
| `GeoAPSGVelocityGradientEvolution` | `geological_agent.geology.github_expansion_geology:velocity_gradient_evolution` |
| `GeoAPSGKinematicVorticity` | `geological_agent.geology.github_expansion_geology:kinematic_vorticity` |
| `GeoAPSGFractureTraction` | `geological_agent.geology.github_expansion_geology:fracture_traction` |
| `GeoAPSGFaultReactivation` | `geological_agent.geology.github_expansion_geology:fault_reactivation` |

Parameter constraints, units, result schema, artifact references and structured error semantics are defined by each tool in the registry. Pure numeric operations return their declared JSON result; operations with output files must preserve their artifact paths, sizes and hashes. Missing dependencies must remain explicit errors. Do not install packages or alter shared environments during execution.

### Current availability

tool_candidates_available_workflow_unverified

The native references resolve in the deployed OreSage registry. This documentation repair adds the missing handoff sections; it does not certify full Skill workflows, external data services or AI Lab acceptance. `workflow_validation=not_run` and `platform_validation=not_run` remain unchanged.

Earlier status statements in this source document are historical source-authoring records. Current deployment evidence is recorded in docs/releases/xiaoyu-skills-20261029.md; historical NOT DEPLOYED statements must not be read as the current runtime status. Upstream licenses, scientific limitations and prior failed records remain unchanged.

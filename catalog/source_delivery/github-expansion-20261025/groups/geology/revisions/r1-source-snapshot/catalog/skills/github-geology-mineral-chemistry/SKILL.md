---
id: github_geology_mineral_chemistry
name: "Compositional and normative mineral chemistry"
description: "Express positive geochemical compositions as additive log ratios to an explicitly selected reference component. Map chemical compositions into explicitly defined orthonormal log-ratio balances for valid Euclidean analysis. Estimate the Aitchison center of a population of positive geological compositions. Represent closed mineral-chemical compositions as positive-orthant spherical angles and reconstruct their fractions. Fit supplied chemical compositions to an explicit independent mineral endmember mass-fraction model. Calculate a CIPW normative mineral assemblage from explicitly supplied oxide and trace chemistry."
when_to_use: "Compositional and normative mineral chemistry from explicit supplied geological measurements"
tools:
- GeoPyroliteALR
- GeoPyroliteILR
- GeoPyroliteCompositionalCenter
- GeoPyroliteSphericalComposition
- GeoPyroliteMineralEndmemberUnmix
- GeoPyroliteCIPWNorm
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

# Compositional and normative mineral chemistry

## When to use

Express positive geochemical compositions as additive log ratios to an explicitly selected reference component. Map chemical compositions into explicitly defined orthonormal log-ratio balances for valid Euclidean analysis. Estimate the Aitchison center of a population of positive geological compositions. Represent closed mineral-chemical compositions as positive-orthant spherical angles and reconstruct their fractions. Fit supplied chemical compositions to an explicit independent mineral endmember mass-fraction model. Calculate a CIPW normative mineral assemblage from explicitly supplied oxide and trace chemistry.

## Required inputs

Use the exact strict input schema and supplied example for the selected operation. Every call needs a caller-declared data_source. Explicit units, structural conventions, sample alignment and stated geological assumptions are mandatory; the source declaration is not independent authentication.

## Procedure

1. Select the operation matching the scientific question and read its limitations.
2. Obtain the declared measurements, units, reference compositions or model parameters.
3. Check scientific scope and missingness; never replace unavailable measurements with synthetic values.
4. Invoke the named native function with args as a dictionary or JSON object string.
5. Preserve result units and all native provenance hashes. Explain the result within its assumptions.

## Tools and synthetic examples

### GeoPyroliteALR

Express positive geochemical compositions as additive log ratios to an explicitly selected reference component.

Entrypoint: `geological_agent.geology.github_expansion_geology:additive_logratio`. Example: `assets/github-expansion-geology/GeoPyroliteALR.json`. All examples are explicitly SYNTHETIC.

Reference choice matters. All components must be positive and share one concentration unit; censored/zero data require an independently justified treatment outside this tool.

Upstream source: [pinned implementation](https://github.com/morganjwilliams/pyrolite/blob/ab651b448ecd2ce1bc22d752b80a977a1f4dd1ca/pyrolite/comp/codata.py).

### GeoPyroliteILR

Map chemical compositions into explicitly defined orthonormal log-ratio balances for valid Euclidean analysis.

Entrypoint: `geological_agent.geology.github_expansion_geology:isometric_logratio`. Example: `assets/github-expansion-geology/GeoPyroliteILR.json`. All examples are explicitly SYNTHETIC.

The scientifically appropriate balance basis is supplied by the caller. The adapter checks orthonormality and zero-sum contrasts and does not invent element groups.

Upstream source: [pinned implementation](https://github.com/morganjwilliams/pyrolite/blob/ab651b448ecd2ce1bc22d752b80a977a1f4dd1ca/pyrolite/comp/codata.py).

### GeoPyroliteCompositionalCenter

Estimate the Aitchison center of a population of positive geological compositions.

Entrypoint: `geological_agent.geology.github_expansion_geology:compositional_center`. Example: `assets/github-expansion-geology/GeoPyroliteCompositionalCenter.json`. All examples are explicitly SYNTHETIC.

Equal sample weights are assumed. The center describes relative composition, not mean assay grade or mass-weighted material composition.

Upstream source: [pinned implementation](https://github.com/morganjwilliams/pyrolite/blob/ab651b448ecd2ce1bc22d752b80a977a1f4dd1ca/pyrolite/comp/codata.py).

### GeoPyroliteSphericalComposition

Represent closed mineral-chemical compositions as positive-orthant spherical angles and reconstruct their fractions.

Entrypoint: `geological_agent.geology.github_expansion_geology:spherical_composition`. Example: `assets/github-expansion-geology/GeoPyroliteSphericalComposition.json`. All examples are explicitly SYNTHETIC.

Angular results depend on component order and are not geographic bearings or an Aitchison distance. Positive inputs only; no zero replacement.

Upstream source: [pinned implementation](https://github.com/morganjwilliams/pyrolite/blob/ab651b448ecd2ce1bc22d752b80a977a1f4dd1ca/pyrolite/comp/codata.py).

### GeoPyroliteMineralEndmemberUnmix

Fit supplied chemical compositions to an explicit independent mineral endmember mass-fraction model.

Entrypoint: `geological_agent.geology.github_expansion_geology:mineral_endmember_unmix`. Example: `assets/github-expansion-geology/GeoPyroliteMineralEndmemberUnmix.json`. All examples are explicitly SYNTHETIC.

One sample is passed to upstream unmix at a time because its multi-row closure constraint is global. Solver success is not exposed upstream; returned fits must pass explicit residual bounds. Coefficients do not establish ore grade or verified mineral modes.

Upstream source: [pinned implementation](https://github.com/morganjwilliams/pyrolite/blob/ab651b448ecd2ce1bc22d752b80a977a1f4dd1ca/pyrolite/mineral/normative.py).

### GeoPyroliteCIPWNorm

Calculate a CIPW normative mineral assemblage from explicitly supplied oxide and trace chemistry.

Entrypoint: `geological_agent.geology.github_expansion_geology:cipw_normative_mineralogy`. Example: `assets/github-expansion-geology/GeoPyroliteCIPWNorm.json`. All examples are explicitly SYNTHETIC.

Normative, not observed modal mineralogy. Complete explicit chemistry is mandatory; no missing-value imputation. Both iron species must be positive or both zero to prevent upstream redox inference. Upstream renormalizes totals and includes aggregate and component mineral columns; do not sum overlapping columns.

Upstream source: [pinned implementation](https://github.com/morganjwilliams/pyrolite/blob/ab651b448ecd2ce1bc22d752b80a977a1f4dd1ca/pyrolite/mineral/normative.py).

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

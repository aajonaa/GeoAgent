---
id: github_geophysics_effective_media
name: "Effective rock moduli and mixture bounds"
description: "Use for mineral mixtures, pores and randomly oriented cracks with known phase properties. Begin with VRH or Hashin-Shtrikman bounds. Select the pore/inclusion theory justified by the physical question. Different constitutive models are alternative assumptions, not repeated measurements."
when_to_use: "Use for mineral mixtures, pores and randomly oriented cracks with known phase properties."
tools:
- GeoRockVRHBounds
- GeoRockHashinShtrikman
- GeoRockCriticalPorosity
- GeoRockSphericalPores
- GeoRockSelfConsistent
- GeoRockRandomCracks
- GeoRockMoriTanaka
required_inputs:
- Supplied finite model properties with explicit units and input_source provenance
constraints:
- Select the physical model justified by inputs and its limitations.
- Never infer mineral presence, grade or reserves.
- No online retrieval or automatic installation.
expected_outputs:
- Numeric JSON with units, pinned source release and input/implementation hashes
---

# Effective rock moduli and mixture bounds

## When to use

Use for mineral mixtures, pores and randomly oriented cracks with known phase properties.

## Required inputs

Use each strict JSON schema. Every example is SYNTHETIC and is not a field observation.

## Workflow

Begin with VRH or Hashin-Shtrikman bounds. Select the pore/inclusion theory justified by the physical question. Different constitutive models are alternative assumptions, not repeated measurements.

## Tools and examples

### GeoRockVRHBounds

Compute Voigt, Reuss and Hill bulk/shear estimates for a multiphase mineral aggregate.

Synthetic fixture: assets/github-expansion-geophysics/GeoRockVRHBounds.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "fractions": [
    0.5,
    0.5
  ],
  "bulk_gpa": [
    20,
    40
  ],
  "shear_gpa": [
    10,
    20
  ]
}
```

Limitations: Isotropic phases; supplied volume fractions sum to one.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/EM.py

### GeoRockHashinShtrikman

Compute both Hashin-Shtrikman elastic bounds for a two-phase composite.

Synthetic fixture: assets/github-expansion-geophysics/GeoRockHashinShtrikman.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "stiff_fraction": 0.5,
  "stiff_bulk_gpa": 40,
  "soft_bulk_gpa": 20,
  "stiff_shear_gpa": 20,
  "soft_shear_gpa": 10
}
```

Limitations: Strictly ordered stiff/soft bulk and shear moduli; no automatic sorting.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/EM.py

### GeoRockCriticalPorosity

Predict load-bearing dry-frame moduli below critical porosity.

Synthetic fixture: assets/github-expansion-geophysics/GeoRockCriticalPorosity.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "bulk_gpa": 40,
  "shear_gpa": 30,
  "porosity": 0.1,
  "critical_porosity": 0.4
}
```

Limitations: Only phi<phi_c; critical porosity must be supplied; no suspension branch.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/EM.py

### GeoRockSphericalPores

Estimate elastic compliance added by dilute spherical dry pores.

Synthetic fixture: assets/github-expansion-geophysics/GeoRockSphericalPores.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "bulk_gpa": 20,
  "shear_gpa": 15,
  "porosity": 0.1
}
```

Limitations: Noninteracting spherical cavities; porosity<=0.15; not a crack/high-porosity model.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/EM.py

### GeoRockSelfConsistent

Solve Berryman multiphase spheroidal self-consistency with unmodified Equinor geometry and dual constitutive convergence checks.

Synthetic fixture: assets/github-expansion-geophysics/GeoRockSelfConsistent.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "fractions": [
    0.5,
    0.5
  ],
  "bulk_gpa": [
    4,
    16
  ],
  "shear_gpa": [
    3,
    12
  ],
  "aspect_ratios": [
    1,
    1
  ],
  "density_kg_m3": [
    2400,
    2800
  ]
}
```

Limitations: Explicit phase densities, GPa->Pa conversion; exact spheres and prolates retained, with no equal-phase restriction. Upstream iteration stops on bulk change only and caps at 3000. Adapter checks BOTH weighted residuals <=1e-8 times their phase modulus scale and rejects nonconvergence without altering the kernel. Fractions must sum to 1 within 1e-12. No imputed densities; LGPL-3.0 dependency. R2 NOT TESTED.

Upstream: https://github.com/equinor/rock-physics-open/blob/68cd21b6a581e591d78ef90003292444cb81fe81/src/rock_physics_open/shale_models/multi_sca.py

### GeoRockRandomCracks

Predict isotropic elastic weakening by randomly oriented dry penny-shaped cracks.

Synthetic fixture: assets/github-expansion-geophysics/GeoRockRandomCracks.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "bulk_gpa": 20,
  "shear_gpa": 15,
  "crack_density": 0.05
}
```

Limitations: Dry thin-crack approximation; crack density<=0.1; not an inversion.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/EM.py

### GeoRockMoriTanaka

Estimate composite moduli using a virtual matrix and modified Mori-Tanaka localization.

Synthetic fixture: assets/github-expansion-geophysics/GeoRockMoriTanaka.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "phase1_fraction": 0.3,
  "matrix_bulk_gpa": 30,
  "matrix_shear_gpa": 20,
  "phase1_bulk_gpa": 20,
  "phase1_shear_gpa": 10,
  "phase2_bulk_gpa": 20,
  "phase2_shear_gpa": 10
}
```

Limitations: Virtual matrix is a supplied physical modeling assumption, not fitted from data.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/EM.py

## Source interface

Named entrypoints in geological_agent.geology.github_expansion_geophysics accept args=dict or JSON-object-string through @operation. Pure numeric calls need no output_dir and return artifacts=[]. Errors use ScientificToolError. Preserve units and provenance.

## Expected outputs and interpretation

A forward response does not establish that the modeled geological body exists. No measured validation or uncertainty calibration is supplied.

## Dependencies and licensing

Pins: numpy==2.1.3, scipy==1.15.3, jsonschema==4.25.1, pandas==2.3.0, matplotlib==3.10.7, KDE-diffusion==1.0.5, scikit-learn==1.7.2, tmatrix==1.2.0, typing-extensions==4.16.0, numba==0.68.0, rock-physics-open==1.0.1, choclo==0.3.2, rockphypy==0.0.2, bruges==0.5.4. Missing packages belong in a private CPU worker. Bruges: Apache-2.0; Choclo: BSD-3-Clause; rockphypy: GPLv3; rock-physics-open: LGPLv3. R2 retains shared pins, including typing-extensions4.16.0; never downgrade pydantic/langgraph. Adapter licensing and redistribution review remain pending.

## Validation and availability

R2 NOT TESTED / NOT DEPLOYED / NOT SUBMITTED. source_authored_unverified. R1 basic30 passed according to parent, but counterexamples block promotion and that result is not r2 acceptance. Historical reports remain unchanged. GeoRockStressAnisotropy is blocked, not registered or counted. Unit, workflow, model and platform acceptance not_run; receiving lab pending. Existing online229 unchanged. Test source: tests_local/test_github_expansion_geophysics.py. Parent owns additive registry merge, fixed dispatch and CPU acceptance.

## Source interface and delivery

Use the registered native operation with its declared JSON input schema. The following bindings come from catalog/registry.json; use catalog/source_delivery/examples.json for exact accepted argument examples. Do not substitute guessed arguments, units or scientific algorithms.

| Native tool | Source callable |
| --- | --- |
| `GeoRockVRHBounds` | `geological_agent.geology.github_expansion_geophysics:rock_vrh_bounds` |
| `GeoRockHashinShtrikman` | `geological_agent.geology.github_expansion_geophysics:rock_hashin_shtrikman` |
| `GeoRockCriticalPorosity` | `geological_agent.geology.github_expansion_geophysics:rock_critical_porosity` |
| `GeoRockSphericalPores` | `geological_agent.geology.github_expansion_geophysics:rock_spherical_pores` |
| `GeoRockSelfConsistent` | `geological_agent.geology.github_expansion_geophysics:rock_self_consistent` |
| `GeoRockRandomCracks` | `geological_agent.geology.github_expansion_geophysics:rock_random_cracks` |
| `GeoRockMoriTanaka` | `geological_agent.geology.github_expansion_geophysics:rock_mori_tanaka` |

Parameter constraints, units, result schema, artifact references and structured error semantics are defined by each tool in the registry. Pure numeric operations return their declared JSON result; operations with output files must preserve their artifact paths, sizes and hashes. Missing dependencies must remain explicit errors. Do not install packages or alter shared environments during execution.

### Current availability

tool_candidates_available_workflow_unverified

The native references resolve in the deployed OreSage registry. This documentation repair adds the missing handoff sections; it does not certify full Skill workflows, external data services or AI Lab acceptance. `workflow_validation=not_run` and `platform_validation=not_run` remain unchanged.

Earlier status statements in this source document are historical source-authoring records. Current deployment evidence is recorded in docs/releases/xiaoyu-skills-20261029.md; historical NOT DEPLOYED statements must not be read as the current runtime status. Upstream licenses, scientific limitations and prior failed records remain unchanged.

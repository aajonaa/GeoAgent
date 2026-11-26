---
id: github_geophysics_fluid_effects
name: "Pore-fluid substitution and seismic dispersion"
description: "Use for supplied pore fluids and rock frames, including static saturation and dynamic flow. Apply PVT/Brie only within the empirical assumptions. Choose Gassmann for isotropic equilibrium, Brown-Korringa for anisotropic compliance, or Biot/squirt/patch models for their distinct relaxation scales."
when_to_use: "Use for supplied pore fluids and rock frames, including static saturation and dynamic flow."
tools:
- GeoRockGassmannSubstitution
- GeoRockBrownKorringa
- GeoRockBiotDispersion
- GeoRockSquirtFlow
- GeoRockPatchySaturation
- GeoRockBrieMixing
- GeoRockFluidPVT
required_inputs:
- Supplied finite model properties with explicit units and input_source provenance
constraints:
- Select the physical model justified by inputs and its limitations.
- Never infer mineral presence, grade or reserves.
- No online retrieval or automatic installation.
expected_outputs:
- Numeric JSON with units, pinned source release and input/implementation hashes
---

# Pore-fluid substitution and seismic dispersion

## When to use

Use for supplied pore fluids and rock frames, including static saturation and dynamic flow.

## Required inputs

Use each strict JSON schema. Every example is SYNTHETIC and is not a field observation.

## Workflow

Apply PVT/Brie only within the empirical assumptions. Choose Gassmann for isotropic equilibrium, Brown-Korringa for anisotropic compliance, or Biot/squirt/patch models for their distinct relaxation scales.

## Tools and examples

### GeoRockGassmannSubstitution

Replace pore fluid in an isotropic low-frequency frame and report both saturated bulk moduli.

Synthetic fixture: assets/github-expansion-geophysics/GeoRockGassmannSubstitution.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "dry_bulk_gpa": 10,
  "dry_shear_gpa": 8,
  "mineral_bulk_gpa": 40,
  "porosity": 0.25,
  "initial_fluid_bulk_gpa": 4,
  "replacement_fluid_bulk_gpa": 8
}
```

Limitations: Connected equilibrated pores; unchanged dry frame and shear; no saturation inference.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/Fluid.py

### GeoRockBrownKorringa

Saturate supplied anisotropic dry compliance using Brown-Korringa poroelasticity.

Synthetic fixture: assets/github-expansion-geophysics/GeoRockBrownKorringa.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "dry_stiffness_gpa": [
    [
      20.666666666666668,
      4.666666666666667,
      4.666666666666667,
      0,
      0,
      0
    ],
    [
      4.666666666666667,
      20.666666666666668,
      4.666666666666667,
      0,
      0,
      0
    ],
    [
      4.666666666666667,
      4.666666666666667,
      20.666666666666668,
      0,
      0,
      0
    ],
    [
      0,
      0,
      0,
      8,
      0,
      0
    ],
    [
      0,
      0,
      0,
      0,
      8,
      0
    ],
    [
      0,
      0,
      0,
      0,
      0,
      8
    ]
  ],
  "mineral_bulk_gpa": 40,
  "mineral_shear_gpa": 30,
  "fluid_bulk_gpa": 4,
  "porosity": 0.25
}
```

Limitations: Isotropic mineral assumption; engineering Voigt order; positive definite tensors.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/Fluid.py

### GeoRockBiotDispersion

Compute frequency-dependent fast/slow P waves, shear waves and Biot attenuation.

Synthetic fixture: assets/github-expansion-geophysics/GeoRockBiotDispersion.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "dry_bulk_gpa": 10,
  "dry_shear_gpa": 8,
  "mineral_bulk_gpa": 40,
  "porosity": 0.25,
  "fluid_bulk_gpa": 4,
  "mineral_density_kg_m3": 2650,
  "fluid_density_kg_m3": 1000,
  "permeability_m2": 1e-12,
  "viscosity_pa_s": 0.001,
  "pore_radius_m": 1e-05,
  "tortuosity": 2,
  "frequencies_hz": [
    0.01
  ]
}
```

Limitations: Consistent SI kernel inputs yield m/s despite ambiguous upstream km/s prose. Homogeneous isotropic medium; viscodynamic argument<=200; upstream complex loss convention.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/Fluid.py

### GeoRockSquirtFlow

Predict high-frequency saturated properties from pressure-dependent dry velocities via squirt flow.

Synthetic fixture: assets/github-expansion-geophysics/GeoRockSquirtFlow.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "high_pressure_vp_m_s": 3214.550253664318,
  "high_pressure_vs_m_s": 2000,
  "dry_vp_m_s": [
    2549.5097567963926
  ],
  "dry_vs_m_s": [
    1732.0508075688772
  ],
  "mineral_bulk_gpa": 40,
  "dry_density_kg_m3": 2000,
  "fluid_density_kg_m3": 1000,
  "fluid_bulk_gpa": 4,
  "porosity": 0.25
}
```

Limitations: Require 0<Kdry<=Khigh<Kmineral, 0<Gdry<=Ghigh, and 1/Gdry-(4/15)*(1/Kdry-1/Khigh)>=1/Ghigh>0; velocity bounds alone are insufficient. Explicit kg/m3 to upstream g/cm3 conversion.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/Fluid.py

### GeoRockPatchySaturation

Compute P-wave dispersion and attenuation for concentric patches of two pore fluids.

Synthetic fixture: assets/github-expansion-geophysics/GeoRockPatchySaturation.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "dry_bulk_gpa": 10,
  "dry_shear_gpa": 8,
  "mineral_bulk_gpa": 40,
  "porosity": 0.25,
  "mineral_density_kg_m3": 2650,
  "inner_fluid_bulk_gpa": 4,
  "outer_fluid_bulk_gpa": 4,
  "inner_density_kg_m3": 1000,
  "outer_density_kg_m3": 1000,
  "inner_viscosity_pa_s": 0.001,
  "outer_viscosity_pa_s": 0.001,
  "permeability_m2": 1e-10,
  "inner_radius_m": 0.01,
  "inner_saturation": 0.5,
  "frequencies_hz": [
    1,
    10
  ]
}
```

Limitations: Concentric patches; supplied fluids/geometry; unstable exponential regimes rejected; no patch-size inversion.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/Fluid.py

### GeoRockBrieMixing

Predict effective liquid-gas bulk modulus versus saturation using the Brie mixing law.

Synthetic fixture: assets/github-expansion-geophysics/GeoRockBrieMixing.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "liquid_bulk_gpa": 2.5,
  "gas_bulk_gpa": 0.1,
  "liquid_saturation": [
    0,
    0.5,
    1
  ],
  "exponent": 2
}
```

Limitations: Empirical exponent supplied, not fitted; no saturation inference.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/Fluid.py

### GeoRockFluidPVT

Evaluate Batzle-Wang water, brine, oil and gas density and acoustic bulk moduli.

Synthetic fixture: assets/github-expansion-geophysics/GeoRockFluidPVT.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "temperature_c": 0,
  "pressure_mpa": 10,
  "salinity_mass_fraction": 0.1,
  "reference_oil_density_kg_m3": 850,
  "gas_specific_gravity": 0.7
}
```

Limitations: Empirical PVT, not phase-equilibrium calculation; conservative pressure/temperature limits; no gas/oil identification.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/BW.py

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
| `GeoRockGassmannSubstitution` | `geological_agent.geology.github_expansion_geophysics:rock_gassmann_substitution` |
| `GeoRockBrownKorringa` | `geological_agent.geology.github_expansion_geophysics:rock_brown_korringa` |
| `GeoRockBiotDispersion` | `geological_agent.geology.github_expansion_geophysics:rock_biot_dispersion` |
| `GeoRockSquirtFlow` | `geological_agent.geology.github_expansion_geophysics:rock_squirt_flow` |
| `GeoRockPatchySaturation` | `geological_agent.geology.github_expansion_geophysics:rock_patchy_saturation` |
| `GeoRockBrieMixing` | `geological_agent.geology.github_expansion_geophysics:rock_brie_mixing` |
| `GeoRockFluidPVT` | `geological_agent.geology.github_expansion_geophysics:rock_fluid_pvt` |

Parameter constraints, units, result schema, artifact references and structured error semantics are defined by each tool in the registry. Pure numeric operations return their declared JSON result; operations with output files must preserve their artifact paths, sizes and hashes. Missing dependencies must remain explicit errors. Do not install packages or alter shared environments during execution.

### Current availability

tool_candidates_available_workflow_unverified

The native references resolve in the deployed OreSage registry. This documentation repair adds the missing handoff sections; it does not certify full Skill workflows, external data services or AI Lab acceptance. `workflow_validation=not_run` and `platform_validation=not_run` remain unchanged.

Earlier status statements in this source document are historical source-authoring records. Current deployment evidence is recorded in docs/releases/xiaoyu-skills-20261029.md; historical NOT DEPLOYED statements must not be read as the current runtime status. Upstream licenses, scientific limitations and prior failed records remain unchanged.

---
id: github_geophysics_seismic_interpretation
name: "Layered and anisotropic seismic interpretation"
description: "Use for fine layering, anisotropic propagation, azimuthal AVO, elastic scattering or impedance. Backus requires subwavelength layers. Verify tensor symmetry before VTI/HTI use. Choose exact isotropic Zoeppritz or weak-HTI Ruger for the stated medium. Elastic impedance requires an explicit reference ratio."
when_to_use: "Use for fine layering, anisotropic propagation, azimuthal AVO, elastic scattering or impedance."
tools:
- GeoSeismicBackus
- GeoSeismicVTIPhase
- GeoSeismicOrthorhombicParameters
- GeoSeismicHTIReflectivity
- GeoSeismicZoeppritzScattering
- GeoSeismicElasticImpedance
required_inputs:
- Supplied finite model properties with explicit units and input_source provenance
constraints:
- Select the physical model justified by inputs and its limitations.
- Never infer mineral presence, grade or reserves.
- No online retrieval or automatic installation.
expected_outputs:
- Numeric JSON with units, pinned source release and input/implementation hashes
---

# Layered and anisotropic seismic interpretation

## When to use

Use for fine layering, anisotropic propagation, azimuthal AVO, elastic scattering or impedance.

## Required inputs

Use each strict JSON schema. Every example is SYNTHETIC and is not a field observation.

## Workflow

Backus requires subwavelength layers. Verify tensor symmetry before VTI/HTI use. Choose exact isotropic Zoeppritz or weak-HTI Ruger for the stated medium. Elastic impedance requires an explicit reference ratio.

## Tools and examples

### GeoSeismicBackus

Upscale fine isotropic layering to five long-wavelength VTI stiffnesses.

Synthetic fixture: assets/github-expansion-geophysics/GeoSeismicBackus.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "fractions": [
    0.5,
    0.5
  ],
  "lame_lambda_gpa": [
    10,
    20
  ],
  "shear_gpa": [
    10,
    20
  ]
}
```

Limitations: Layers must be thin relative to wavelength; supplied fractions sum to one; no inferred wavelength validity.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/Anisotropy.py

### GeoSeismicVTIPhase

Compute quasi-P, quasi-SV and SH phase velocities versus inclination in a VTI rock.

Synthetic fixture: assets/github-expansion-geophysics/GeoSeismicVTIPhase.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "stiffness_gpa": [
    [
      44,
      14,
      10.0,
      0,
      0,
      0
    ],
    [
      14,
      44,
      10.0,
      0,
      0,
      0
    ],
    [
      10.0,
      10.0,
      40.0,
      0,
      0,
      0
    ],
    [
      0,
      0,
      0,
      15,
      0,
      0
    ],
    [
      0,
      0,
      0,
      0,
      15,
      0
    ],
    [
      0,
      0,
      0,
      0,
      0,
      15
    ]
  ],
  "density_kg_m3": 2500,
  "inclination_degrees": [
    0,
    90
  ]
}
```

Limitations: Phase speeds, not group speeds; upstream azimuth argument physically denotes inclination in this VTI formula.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/Anisotropy.py

### GeoSeismicOrthorhombicParameters

Extract seven Thomsen-Tsvankin anisotropy parameters from a supplied orthorhombic stiffness tensor.

Synthetic fixture: assets/github-expansion-geophysics/GeoSeismicOrthorhombicParameters.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "stiffness_gpa": [
    [
      48,
      16,
      14,
      0,
      0,
      0
    ],
    [
      16,
      44,
      12,
      0,
      0,
      0
    ],
    [
      14,
      12,
      40,
      0,
      0,
      0
    ],
    [
      0,
      0,
      0,
      10,
      0,
      0
    ],
    [
      0,
      0,
      0,
      0,
      12,
      0
    ],
    [
      0,
      0,
      0,
      0,
      0,
      14
    ]
  ]
}
```

Limitations: Symmetry-aligned tensor; no rotation; extracting parameters does not guarantee weak anisotropy.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/Anisotropy.py

### GeoSeismicHTIReflectivity

Compute Ruger PP reflectivity versus incidence and azimuth for two weakly anisotropic HTI layers.

Synthetic fixture: assets/github-expansion-geophysics/GeoSeismicHTIReflectivity.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "upper_stiffness_gpa": [
    [
      40.0,
      10.0,
      10.0,
      0,
      0,
      0
    ],
    [
      10.0,
      40.0,
      10.0,
      0,
      0,
      0
    ],
    [
      10.0,
      10.0,
      40.0,
      0,
      0,
      0
    ],
    [
      0,
      0,
      0,
      15,
      0,
      0
    ],
    [
      0,
      0,
      0,
      0,
      15,
      0
    ],
    [
      0,
      0,
      0,
      0,
      0,
      15
    ]
  ],
  "lower_stiffness_gpa": [
    [
      48.4,
      12.1,
      12.1,
      0,
      0,
      0
    ],
    [
      12.1,
      48.4,
      12.1,
      0,
      0,
      0
    ],
    [
      12.1,
      12.1,
      48.4,
      0,
      0,
      0
    ],
    [
      0,
      0,
      0,
      18.15,
      0,
      0
    ],
    [
      0,
      0,
      0,
      0,
      18.15,
      0
    ],
    [
      0,
      0,
      0,
      0,
      0,
      18.15
    ]
  ],
  "upper_density_kg_m3": 2500,
  "lower_density_kg_m3": 2500,
  "incidence_degrees": [
    0,
    20
  ],
  "azimuth_degrees": [
    0,
    90
  ]
}
```

Limitations: Ruger approximation; incidence<=35deg AND actual anisotropic transmission must be strictly propagating. Christoffel vertical-slowness domain gate rejects critical/evanescent modes at each supplied azimuth; it does not replace upstream amplitudes. Weak anisotropy<=.2; aligned HTI axes; not fracture inversion.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/AVO.py

### GeoSeismicZoeppritzScattering

Compute complete complex P/S reflection and transmission matrices at an elastic interface.

Synthetic fixture: assets/github-expansion-geophysics/GeoSeismicZoeppritzScattering.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "upper_vp_m_s": 2000,
  "upper_vs_m_s": 1000,
  "upper_density_kg_m3": 2000,
  "lower_vp_m_s": 3000,
  "lower_vs_m_s": 1500,
  "lower_density_kg_m3": 2000,
  "incidence_degrees": [
    0,
    30,
    60
  ]
}
```

Limitations: Lossless isotropic elastic halfspaces; no fluid halfspace; incident rows Pd,Sd,Pu,Su and outgoing columns Pu,Su,Pd,Sd.

Upstream: https://github.com/agilescientific/bruges/blob/24e2e7912f49089465dd622363fd2788029266b1/bruges/reflection/reflection.py

### GeoSeismicElasticImpedance

Construct normalized PP, PSV, SVP, SVSV and SHSH angle-dependent elastic impedance logs.

Synthetic fixture: assets/github-expansion-geophysics/GeoSeismicElasticImpedance.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "vp_m_s": [
    2000,
    3000
  ],
  "vs_m_s": [
    1000,
    1500
  ],
  "density_kg_m3": [
    2000,
    2200
  ],
  "incidence_degrees": [
    0,
    20
  ],
  "shear_p_ratio": 0.5
}
```

Limitations: Mean normalization is specific to supplied logs; explicit Vs/Vp reference; no inversion or geological classification.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/AVO.py

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
| `GeoSeismicBackus` | `geological_agent.geology.github_expansion_geophysics:seismic_backus` |
| `GeoSeismicVTIPhase` | `geological_agent.geology.github_expansion_geophysics:seismic_vti_phase` |
| `GeoSeismicOrthorhombicParameters` | `geological_agent.geology.github_expansion_geophysics:seismic_orthorhombic_parameters` |
| `GeoSeismicHTIReflectivity` | `geological_agent.geology.github_expansion_geophysics:seismic_hti_reflectivity` |
| `GeoSeismicZoeppritzScattering` | `geological_agent.geology.github_expansion_geophysics:seismic_zoeppritz_scattering` |
| `GeoSeismicElasticImpedance` | `geological_agent.geology.github_expansion_geophysics:seismic_elastic_impedance` |

Parameter constraints, units, result schema, artifact references and structured error semantics are defined by each tool in the registry. Pure numeric operations return their declared JSON result; operations with output files must preserve their artifact paths, sizes and hashes. Missing dependencies must remain explicit errors. Do not install packages or alter shared environments during execution.

### Current availability

tool_candidates_available_workflow_unverified

The native references resolve in the deployed OreSage registry. This documentation repair adds the missing handoff sections; it does not certify full Skill workflows, external data services or AI Lab acceptance. `workflow_validation=not_run` and `platform_validation=not_run` remain unchanged.

Earlier status statements in this source document are historical source-authoring records. Current deployment evidence is recorded in docs/releases/xiaoyu-skills-20261029.md; historical NOT DEPLOYED statements must not be read as the current runtime status. Upstream licenses, scientific limitations and prior failed records remain unchanged.

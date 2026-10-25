---
id: github_geophysics_potential_fields
name: "Gravity and magnetic source modeling"
description: "Use for gravity or magnetic forward responses from explicit sources in local Cartesian coordinates. Choose point or finite-prism geometry from physical source scale. Confirm ENU axes and signed contrasts. Reject singular/interior observations. Inspect full vector/tensor fields together."
when_to_use: "Use for gravity or magnetic forward responses from explicit sources in local Cartesian coordinates."
tools:
- GeoPointMassGravity
- GeoPrismGravity
- GeoDipoleMagnetic
- GeoPrismMagnetic
required_inputs:
- Supplied finite model properties with explicit units and input_source provenance
constraints:
- Select the physical model justified by inputs and its limitations.
- Never infer mineral presence, grade or reserves.
- No online retrieval or automatic installation.
expected_outputs:
- Numeric JSON with units, pinned source release and input/implementation hashes
---

# Gravity and magnetic source modeling

## When to use

Use for gravity or magnetic forward responses from explicit sources in local Cartesian coordinates.

## Required inputs

Use each strict JSON schema. Every example is SYNTHETIC and is not a field observation.

## Workflow

Choose point or finite-prism geometry from physical source scale. Confirm ENU axes and signed contrasts. Reject singular/interior observations. Inspect full vector/tensor fields together.

## Tools and examples

### GeoPointMassGravity

Forward-model potential, acceleration and full gravity-gradient tensor of point mass contrasts.

Synthetic fixture: assets/github-expansion-geophysics/GeoPointMassGravity.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "observations_enu_m": [
    [
      0,
      0,
      10
    ]
  ],
  "sources_enu_m": [
    [
      0,
      0,
      0
    ]
  ],
  "masses_kg": [
    1000000000.0
  ]
}
```

Limitations: Point-source idealization; >=1mm separation; all components bundled; no density inversion.

Upstream: https://github.com/fatiando/choclo/blob/6b4171701a6c8d7ffff88efc83c6bab5655233c3/choclo/point/_forward.py

### GeoPrismGravity

Forward-model gravity and its full gradient tensor for finite rectangular density-contrast bodies.

Synthetic fixture: assets/github-expansion-geophysics/GeoPrismGravity.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "observations_enu_m": [
    [
      0,
      0,
      3
    ]
  ],
  "prisms_wesnbt_m": [
    [
      -1,
      1,
      -1,
      1,
      -1,
      1
    ]
  ],
  "density_contrast_kg_m3": [
    1000
  ]
}
```

Limitations: Uniform density per prism; reject observations inside or on any closed prism; no inversion or inferred ore volume.

Upstream: https://github.com/fatiando/choclo/blob/6b4171701a6c8d7ffff88efc83c6bab5655233c3/choclo/prism/_gravity.py

### GeoDipoleMagnetic

Forward-model all magnetic induction components from explicit dipole moments.

Synthetic fixture: assets/github-expansion-geophysics/GeoDipoleMagnetic.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "observations_enu_m": [
    [
      0,
      0,
      10
    ]
  ],
  "sources_enu_m": [
    [
      0,
      0,
      0
    ]
  ],
  "moments_enu_a_m2": [
    [
      0,
      0,
      1000
    ]
  ]
}
```

Limitations: Dipole idealization; supplied moments; tesla, not nT; no susceptibility inference.

Upstream: https://github.com/fatiando/choclo/blob/6b4171701a6c8d7ffff88efc83c6bab5655233c3/choclo/dipole/_forward.py

### GeoPrismMagnetic

Forward-model magnetic induction vectors from uniformly magnetized finite prisms.

Synthetic fixture: assets/github-expansion-geophysics/GeoPrismMagnetic.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "observations_enu_m": [
    [
      0,
      0,
      3
    ]
  ],
  "prisms_wesnbt_m": [
    [
      -1,
      1,
      -1,
      1,
      -1,
      1
    ]
  ],
  "magnetization_enu_a_m": [
    [
      0,
      0,
      1
    ]
  ]
}
```

Limitations: Uniform supplied magnetization; reject interior/boundary observations; no geomagnetic retrieval or inversion.

Upstream: https://github.com/fatiando/choclo/blob/6b4171701a6c8d7ffff88efc83c6bab5655233c3/choclo/prism/_magnetic.py

## Source interface

Named entrypoints in geological_agent.geology.github_expansion_geophysics accept args=dict or JSON-object-string through @operation. Pure numeric calls need no output_dir and return artifacts=[]. Errors use ScientificToolError. Preserve units and provenance.

## Expected outputs and interpretation

A forward response does not establish that the modeled geological body exists. No measured validation or uncertainty calibration is supplied.

## Dependencies and licensing

Pins: numpy==2.1.3, scipy==1.15.3, jsonschema==4.25.1, pandas==2.3.0, matplotlib==3.10.7, KDE-diffusion==1.0.5, scikit-learn==1.7.2, tmatrix==1.2.0, typing-extensions==4.16.0, numba==0.68.0, rock-physics-open==1.0.1, choclo==0.3.2, rockphypy==0.0.2, bruges==0.5.4. Missing packages belong in a private CPU worker. Bruges: Apache-2.0; Choclo: BSD-3-Clause; rockphypy: GPLv3; rock-physics-open: LGPLv3. R2 retains shared pins, including typing-extensions4.16.0; never downgrade pydantic/langgraph. Adapter licensing and redistribution review remain pending.

## Validation and availability

R2 NOT TESTED / NOT DEPLOYED / NOT SUBMITTED. source_authored_unverified. R1 basic30 passed according to parent, but counterexamples block promotion and that result is not r2 acceptance. Historical reports remain unchanged. GeoRockStressAnisotropy is blocked, not registered or counted. Unit, workflow, model and platform acceptance not_run; receiving lab pending. Existing online229 unchanged. Test source: tests_local/test_github_expansion_geophysics.py. Parent owns additive registry merge, fixed dispatch and CPU acceptance.

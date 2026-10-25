---
id: github_geophysics_grain_fracture
name: "Grain contacts, cement and fracture mechanics"
description: "Use for dry-frame predictions controlled by contacts, cement, loading, cracks or sand-shale texture. Select the observed mechanism: aligned cracks, unbonded grains, deposited cement, prebonded contacts or shale packing. Johnson stress anisotropy is blocked and unavailable. Supply measured/calibrated parameters."
when_to_use: "Use for dry-frame predictions controlled by contacts, cement, loading, cracks or sand-shale texture."
tools:
- GeoRockHudsonCracks
- GeoRockHertzMindlin
- GeoRockContactCement
- GeoRockDigbyContacts
- GeoRockSandShalePorosity
required_inputs:
- Supplied finite model properties with explicit units and input_source provenance
constraints:
- Select the physical model justified by inputs and its limitations.
- Never infer mineral presence, grade or reserves.
- No online retrieval or automatic installation.
expected_outputs:
- Numeric JSON with units, pinned source release and input/implementation hashes
---

# Grain contacts, cement and fracture mechanics

## When to use

Use for dry-frame predictions controlled by contacts, cement, loading, cracks or sand-shale texture.

## Required inputs

Use each strict JSON schema. Every example is SYNTHETIC and is not a field observation.

## Workflow

Select the observed mechanism: aligned cracks, unbonded grains, deposited cement, prebonded contacts or shale packing. Johnson stress anisotropy is blocked and unavailable. Supply measured/calibrated parameters.

## Tools and examples

### GeoRockHudsonCracks

Predict first-order VTI stiffness for aligned penny-shaped cracks.

Synthetic fixture: assets/github-expansion-geophysics/GeoRockHudsonCracks.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "bulk_gpa": 20,
  "shear_gpa": 15,
  "inclusion_bulk_gpa": 0,
  "inclusion_shear_gpa": 0,
  "aspect_ratio": 0.01,
  "crack_density": 0.02
}
```

Limitations: Fixed first order and axis3; thin weak cracks; reject unstable tensors.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/EM.py

### GeoRockHertzMindlin

Predict confining-stress-dependent stiffness of an uncemented granular packing.

Synthetic fixture: assets/github-expansion-geophysics/GeoRockHertzMindlin.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "bulk_gpa": 20,
  "shear_gpa": 15,
  "porosity": 0.4,
  "coordination": 6,
  "effective_stress_mpa": 100,
  "shear_factor": 0
}
```

Limitations: Effective pressure in MPa; shear factor follows numeric upstream convention; no recovered stress.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/GM.py

### GeoRockContactCement

Estimate sandstone stiffness from cement deposited at grain contacts.

Synthetic fixture: assets/github-expansion-geophysics/GeoRockContactCement.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "bulk_gpa": 20,
  "shear_gpa": 15,
  "porosity": 0.36,
  "critical_porosity": 0.4,
  "coordination": 6,
  "cement_bulk_gpa": 20,
  "cement_shear_gpa": 15
}
```

Limitations: Fixed contact-deposition scheme1; 0<phi_c-phi<=0.1; empirical contact polynomial.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/GM.py

### GeoRockDigbyContacts

Predict granular moduli from pre-existing bonded contacts under stress.

Synthetic fixture: assets/github-expansion-geophysics/GeoRockDigbyContacts.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "bulk_gpa": 20,
  "shear_gpa": 15,
  "porosity": 0.4,
  "coordination": 6,
  "effective_stress_mpa": 35.809862195676445,
  "bond_radius_ratio": 0.1
}
```

Limitations: Positive pressure avoids upstream zero-pressure complex-root ambiguity; bounded bond radius.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/GM.py

### GeoRockSandShalePorosity

Predict dispersed and laminated sand-shale porosity envelopes.

Synthetic fixture: assets/github-expansion-geophysics/GeoRockSandShalePorosity.json

```json
{
  "input_source": "SYNTHETIC analytic fixture; not geological observations",
  "sand_porosity": 0.4,
  "shale_porosity": 0.1,
  "shale_fraction": [
    0,
    0.2,
    0.6,
    1
  ]
}
```

Limitations: Volume fractions only; no shale-volume inference from logs or chemical composition.

Upstream: https://github.com/yujiaxin666/rockphypy/blob/54c89027fb99e00b53761a05fcd7c20bc796ce7e/rockphypy/GM.py

## Source interface

Named entrypoints in geological_agent.geology.github_expansion_geophysics accept args=dict or JSON-object-string through @operation. Pure numeric calls need no output_dir and return artifacts=[]. Errors use ScientificToolError. Preserve units and provenance.

## Expected outputs and interpretation

A forward response does not establish that the modeled geological body exists. No measured validation or uncertainty calibration is supplied.

## Dependencies and licensing

Pins: numpy==2.1.3, scipy==1.15.3, jsonschema==4.25.1, pandas==2.3.0, matplotlib==3.10.7, KDE-diffusion==1.0.5, scikit-learn==1.7.2, tmatrix==1.2.0, typing-extensions==4.16.0, numba==0.68.0, rock-physics-open==1.0.1, choclo==0.3.2, rockphypy==0.0.2, bruges==0.5.4. Missing packages belong in a private CPU worker. Bruges: Apache-2.0; Choclo: BSD-3-Clause; rockphypy: GPLv3; rock-physics-open: LGPLv3. R2 retains shared pins, including typing-extensions4.16.0; never downgrade pydantic/langgraph. Adapter licensing and redistribution review remain pending.

## Validation and availability

R2 NOT TESTED / NOT DEPLOYED / NOT SUBMITTED. source_authored_unverified. R1 basic30 passed according to parent, but counterexamples block promotion and that result is not r2 acceptance. Historical reports remain unchanged. GeoRockStressAnisotropy is blocked, not registered or counted. Unit, workflow, model and platform acceptance not_run; receiving lab pending. Existing online229 unchanged. Test source: tests_local/test_github_expansion_geophysics.py. Parent owns additive registry merge, fixed dispatch and CPU acceptance.

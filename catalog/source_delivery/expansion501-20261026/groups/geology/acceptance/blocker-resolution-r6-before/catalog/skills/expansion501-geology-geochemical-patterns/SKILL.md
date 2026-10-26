---
id: expansion501-geology-geochemical-patterns
name: "Geochemical pattern interpretation and sampling bias"
description: "Fit fixed O'Neill orthogonal shape coefficients to positive reference-normalized REE patterns. Classify anhydrous volcanic compositions in the fixed Middlemost TAS diagram. Estimate sampling-density cell-declustering weights with explicit offset and scale search."
when_to_use: "Use only for this documented scientific task."
tools:
- Geo500REEOrthogonalShape
- Geo500VolcanicTASClass
- Geo500SpatialCellDeclustering
required_inputs:
- Explicit data, units, assumptions and data_source
constraints:
- No imputed grade, arbitrary code, network fetch or runtime installation
- Preserve uncertainty and native provenance
expected_outputs:
- Finite scientific JSON with units and hashes
---

# Geochemical pattern interpretation and sampling bias

## When to use

Fit fixed O'Neill orthogonal shape coefficients to positive reference-normalized REE patterns. Classify anhydrous volcanic compositions in the fixed Middlemost TAS diagram. Estimate sampling-density cell-declustering weights with explicit offset and scale search.

## Required inputs

Read the chosen complete schema and limitations. Supply measurements or explicitly identified model inputs, units, source and assumptions. Never fill missing field observations from synthetic examples.

## Procedure

1. Choose the operation matching the scientific question.
2. Confirm physical domain, component order, units and provenance.
3. Have the parent bind its fixed private CPU environment; never install or fetch at call time.
4. Invoke the named function with args as a dictionary or JSON-object string after staging.
5. Preserve units/hashes and interpret within the declared assumptions.

## Tools and synthetic examples

### Geo500REEOrthogonalShape

Fit fixed O'Neill orthogonal shape coefficients to positive reference-normalized REE patterns.

Entrypoint: geological_agent.geology.expansion501_geology:ree_orthogonal_shape. Example: assets/expansion501-geology/Geo500REEOrthogonalShape.json (SYNTHETIC).

Fixed element order La Ce Pr Nd Sm Gd Tb Dy Ho Er Tm Yb Lu; no missing-value filling, tetrad fits or reference downloads.

[Reviewed upstream implementation](https://github.com/morganjwilliams/pyrolite/blob/ab651b448ecd2ce1bc22d752b80a977a1f4dd1ca/pyrolite/util/lambdas/__init__.py).

### Geo500VolcanicTASClass

Classify anhydrous volcanic compositions in the fixed Middlemost TAS diagram.

Entrypoint: geological_agent.geology.expansion501_geology:volcanic_tas_class. Example: assets/expansion501-geology/Geo500VolcanicTASClass.json (SYNTHETIC).

Only declared anhydrous volcanic chemistry; boundary/outside samples receive no forced class; not tectonic provenance or ore identification.

[Reviewed upstream implementation](https://github.com/morganjwilliams/pyrolite/blob/ab651b448ecd2ce1bc22d752b80a977a1f4dd1ca/pyrolite/util/classification.py).

### Geo500SpatialCellDeclustering

Estimate sampling-density cell-declustering weights with explicit offset and scale search.

Entrypoint: geological_agent.geology.expansion501_geology:spatial_cell_declustering. Example: assets/expansion501-geology/Geo500SpatialCellDeclustering.json (SYNTHETIC).

Immutable archive required; source iminmax=1 selects minimum despite contradictory docstring; 2D isotropic cells; no ore grade imputation.

[Reviewed upstream implementation](https://github.com/GeostatsGuy/GeostatsPy/blob/45b2032a1e3f05de6cd0cb7f32ed43203399dbfa/geostatspy/geostats.py).

## Interpretation and constraints

No result certifies ore grade, reserves, mineral identity, engineering safety or real-event prediction. No GPU, arbitrary callable, serialized class, shell command, database fetch or hidden missing-value replacement is exposed. Failures return errors, never local substitute kernels.

## Native errors

ScientificToolError carries code, message and retryable through collection_contracts.operation. Missing/incompatible dependencies need parent-controlled preparation. Do not invent data to bypass a rejected domain.

## Source interface and delivery

Kind: expansion501_geology. Module: geological_agent.geology.expansion501_geology. Explicit decorated functions accept args and return JSON only. No output_dir or generated artifact. Shared contracts provide input, implementation and contract hashes plus empty artifact hashes. Existing native bridge profiles are unchanged. Full paths are in catalog/source_delivery/expansion501-20261026/groups/geology/delivery-files.json.

## Availability and handoff

source_revised_unverified; acceptance_pending; formal_eligible=false. NOT TESTED. Deployment: not_deployed. Submission: not_submitted. Unit, model workflow, Skill workflow and platform validation: not_run. Receiving AI Lab certification is not established. Parent owns registry/kind allowlisting, private CPU binding, tests, acceptance and release.

## Acceptance evidence

Source and proposed independent oracle cases only; no scientific tool/test executed. Complete transitive/native identities, outstanding absolute reference benchmarks, license/distribution review and lab approval remain pending. Blocked assignments are excluded from this Skill and catalog-additions.json; see adaptation-status.json and blocked-evidence.json.

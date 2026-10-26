---
id: expansion501-geology-crystal-symmetry
name: "Atomic symmetry, diffraction and coordination"
description: "Audit crystal space-group symmetry and atomic equivalence. Reduce a Gamma-centred reciprocal mesh by atomic symmetry and time reversal. Calculate kinematic powder X-ray diffraction from supplied ordered atomic structures. Determine geometric periodic coordination environments with fixed CrystalNN settings. Infer charge-neutral ordered-site oxidation states from bond valence. Match periodic crystal structures under origin shift and site permutation."
when_to_use: "Use only for this documented scientific task."
tools:
- Geo500CrystalSpaceGroupAudit
- Geo500IrreducibleReciprocalMesh
- Geo500PowderXRDPattern
- Geo500CrystalCoordination
- Geo500BondValenceOxidation
- Geo500CrystalStructureEquivalence
required_inputs:
- Explicit data, units, assumptions and data_source
constraints:
- No imputed grade, arbitrary code, network fetch or runtime installation
- Preserve uncertainty and native provenance
expected_outputs:
- Finite scientific JSON with units and hashes
---

# Atomic symmetry, diffraction and coordination

## When to use

Audit crystal space-group symmetry and atomic equivalence. Reduce a Gamma-centred reciprocal mesh by atomic symmetry and time reversal. Calculate kinematic powder X-ray diffraction from supplied ordered atomic structures. Determine geometric periodic coordination environments with fixed CrystalNN settings. Infer charge-neutral ordered-site oxidation states from bond valence. Match periodic crystal structures under origin shift and site permutation.

## Required inputs

Read the chosen complete schema and limitations. Supply measurements or explicitly identified model inputs, units, source and assumptions. Never fill missing field observations from synthetic examples.

## Procedure

1. Choose the operation matching the scientific question.
2. Confirm physical domain, component order, units and provenance.
3. Have the parent bind its fixed private CPU environment; never install or fetch at call time.
4. Invoke the named function with args as a dictionary or JSON-object string after staging.
5. Preserve units/hashes and interpret within the declared assumptions.

## Tools and synthetic examples

### Geo500CrystalSpaceGroupAudit

Audit crystal space-group symmetry and atomic equivalence.

Entrypoint: geological_agent.geology.expansion501_geology:crystal_space_group. Example: assets/expansion501-geology/Geo500CrystalSpaceGroupAudit.json (SYNTHETIC).

Ordered periodic atomic sites only; tolerance-dependent crystallographic classification.

[Reviewed upstream implementation](https://github.com/spglib/spglib/blob/3ebd8ac3318793932baeee90b44f453a7c35b5b4/python/spglib/spg.py).

### Geo500IrreducibleReciprocalMesh

Reduce a Gamma-centred reciprocal mesh by atomic symmetry and time reversal.

Entrypoint: geological_agent.geology.expansion501_geology:irreducible_reciprocal_mesh. Example: assets/expansion501-geology/Geo500IrreducibleReciprocalMesh.json (SYNTHETIC).

No magnetic symmetry or electronic-structure solver; time reversal fixed on.

[Reviewed upstream implementation](https://github.com/spglib/spglib/blob/3ebd8ac3318793932baeee90b44f453a7c35b5b4/python/spglib/kpoints.py).

### Geo500PowderXRDPattern

Calculate kinematic powder X-ray diffraction from supplied ordered atomic structures.

Entrypoint: geological_agent.geology.expansion501_geology:powder_xrd_pattern. Example: assets/expansion501-geology/Geo500PowderXRDPattern.json (SYNTHETIC).

No texture, instrument broadening, extinction corrections or measured mineral identification.

[Reviewed upstream implementation](https://github.com/materialsproject/pymatgen/blob/e3fdb6d4bb2a3bc1622f4c133e088d660f0c3c26/src/pymatgen/analysis/diffraction/xrd.py).

### Geo500CrystalCoordination

Determine geometric periodic coordination environments with fixed CrystalNN settings.

Entrypoint: geological_agent.geology.expansion501_geology:crystal_coordination. Example: assets/expansion501-geology/Geo500CrystalCoordination.json (SYNTHETIC).

Geometric-only CrystalNN weights; no oxidation-state constraints or inferred bond orders.

[Reviewed upstream implementation](https://github.com/materialsproject/pymatgen-core/blob/cddebfb21ed5acaee3987948b6704a2790d4e056/src/pymatgen/core/local_env.py).

### Geo500BondValenceOxidation

Infer charge-neutral ordered-site oxidation states from bond valence.

Entrypoint: geological_agent.geology.expansion501_geology:bond_valence_oxidation. Example: assets/expansion501-geology/Geo500BondValenceOxidation.json (SYNTHETIC).

Finite search budget 10000; unsupported elements/ambiguous fits fail, not fabricated charges; no measured redox claim.

[Reviewed upstream implementation](https://github.com/materialsproject/pymatgen-core/blob/cddebfb21ed5acaee3987948b6704a2790d4e056/src/pymatgen/core/bond_valence.py).

### Geo500CrystalStructureEquivalence

Match periodic crystal structures under origin shift and site permutation.

Entrypoint: geological_agent.geology.expansion501_geology:crystal_structure_equivalence. Example: assets/expansion501-geology/Geo500CrystalStructureEquivalence.json (SYNTHETIC).

Fixed matching tolerances; no scaling, anonymous chemical substitution or supercell search; nonmatches return explicit null distances.

[Reviewed upstream implementation](https://github.com/materialsproject/pymatgen-core/blob/cddebfb21ed5acaee3987948b6704a2790d4e056/src/pymatgen/core/structure_matcher.py).

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

---
id: expansion501_geology_crystal_interfaces
name: "Crystal habit, surfaces and coherent interfaces"
description: "Construct equilibrium crystal habit from indexed relative surface energies. Find the lowest-area coherent superlattice match between two mineral surface nets. Generate distinct unrelaxed crystal slab terminations for a Miller plane."
when_to_use: "Use only for this documented scientific task."
tools:
- Geo500WulffCrystalHabit
- Geo500CoherentMineralInterfaceMatch
- Geo500MineralSurfaceTerminations
required_inputs:
- Explicit data, units, assumptions and data_source
constraints:
- No imputed grade, arbitrary code, network fetch or runtime installation
- Preserve uncertainty and native provenance
expected_outputs:
- Finite scientific JSON with units and hashes
---

# Crystal habit, surfaces and coherent interfaces

## When to use

Construct equilibrium crystal habit from indexed relative surface energies. Find the lowest-area coherent superlattice match between two mineral surface nets. Generate distinct unrelaxed crystal slab terminations for a Miller plane.

## Required inputs

Read the chosen complete schema and limitations. Supply measurements or explicitly identified model inputs, units, source and assumptions. Never fill missing field observations from synthetic examples.

## Procedure

1. Choose the operation matching the scientific question.
2. Confirm physical domain, component order, units and provenance.
3. Have the parent bind its fixed private CPU environment; never install or fetch at call time.
4. Invoke the named function with args as a dictionary or JSON-object string after staging.
5. Preserve units/hashes and interpret within the declared assumptions.

## Tools and synthetic examples

### Geo500WulffCrystalHabit

Construct equilibrium crystal habit from indexed relative surface energies.

Entrypoint: geological_agent.geology.expansion501_geology:wulff_crystal_habit. Example: assets/expansion501-geology/Geo500WulffCrystalHabit.json (SYNTHETIC).

No absolute nanocrystal size or dimensional raw Wulff volume reported; nondegenerate indexed surface energies required.

[Reviewed upstream implementation](https://github.com/materialsproject/pymatgen/blob/e3fdb6d4bb2a3bc1622f4c133e088d660f0c3c26/src/pymatgen/analysis/wulff.py).

### Geo500CoherentMineralInterfaceMatch

Find the lowest-area coherent superlattice match between two mineral surface nets.

Entrypoint: geological_agent.geology.expansion501_geology:coherent_interface_match. Example: assets/expansion501-geology/Geo500CoherentMineralInterfaceMatch.json (SYNTHETIC).

At most 25 primitive-cell area multiples; fixed mismatch tolerances; no claim of favorable interface energy.

[Reviewed upstream implementation](https://github.com/materialsproject/pymatgen/blob/e3fdb6d4bb2a3bc1622f4c133e088d660f0c3c26/src/pymatgen/analysis/interfaces/zsl.py).

### Geo500MineralSurfaceTerminations

Generate distinct unrelaxed crystal slab terminations for a Miller plane.

Entrypoint: geological_agent.geology.expansion501_geology:mineral_surface_terminations. Example: assets/expansion501-geology/Geo500MineralSurfaceTerminations.json (SYNTHETIC).

Input <=32 sites; output <=8192 atoms; no reconstruction, relaxation, bond repair or invented surface energies.

[Reviewed upstream implementation](https://github.com/materialsproject/pymatgen-core/blob/cddebfb21ed5acaee3987948b6704a2790d4e056/src/pymatgen/core/surface.py).

## Interpretation and constraints

No result certifies ore grade, reserves, mineral identity, engineering safety or real-event prediction. No GPU, arbitrary callable, serialized class, shell command, database fetch or hidden missing-value replacement is exposed. Failures return errors, never local substitute kernels.

## Native errors

ScientificToolError carries code, message and retryable through collection_contracts.operation. Missing/incompatible dependencies need parent-controlled preparation. Do not invent data to bypass a rejected domain.

## Source interface and delivery

Kind: expansion501_geology. Module: geological_agent.geology.expansion501_geology. Explicit decorated functions accept args and return JSON only. No output_dir or generated artifact. Shared contracts provide input, implementation and contract hashes plus empty artifact hashes. Existing native bridge profiles are unchanged. Full paths are in catalog/source_delivery/expansion501-20261026/groups/geology/delivery-files.json.

## Availability and handoff

source_revised_unverified; acceptance_pending; formal_eligible=false. NOT TESTED. Deployment: not_deployed. Submission: not_submitted. Unit, model workflow, Skill workflow and platform validation: not_run. Receiving AI Lab certification is not established. Parent owns registry/kind allowlisting, private CPU binding, tests, acceptance and release.

## Acceptance evidence

This revised source has not completed upstream scientific acceptance. Historical CPU journals, including failures, remain under acceptance/ and do not certify this revision. Local reference/source checks are not upstream or main-runtime acceptance. Complete transitive/native identities, outstanding absolute benchmarks, license/distribution review and lab approval remain pending. Blocked assignments are excluded from this Skill and catalog-additions.json; see adaptation-status.json and blocked-evidence.json.

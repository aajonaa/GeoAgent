---
id: expansion501-geology-mineral-thermodynamics
name: "Mineral formula, reactions and thermodynamic evidence"
description: "Recalculate measured simple-oxide mineral analyses to an explicit fixed oxygen basis. Balance a unique mineral reaction without changing participant sides. Evaluate decomposition and energy above a composition-energy convex hull. Compute neutral three-dimensional periodic ionic Coulomb energy. Compute tabulated neutron scattering contrast and macroscopic attenuation of mineral compositions. Evaluate single-metal solid/ion stability at explicit pH and SHE potential."
when_to_use: "Use only for this documented scientific task."
tools:
- Geo500MineralOxygenBasisFormula
- Geo500MineralReactionBalance
- Geo500MineralPhaseHull
- Geo500PeriodicIonicLatticeEnergy
- Geo500MineralNeutronContrast
- Geo500MineralEhPHStability
required_inputs:
- Explicit data, units, assumptions and data_source
constraints:
- No imputed grade, arbitrary code, network fetch or runtime installation
- Preserve uncertainty and native provenance
expected_outputs:
- Finite scientific JSON with units and hashes
---

# Mineral formula, reactions and thermodynamic evidence

## When to use

Recalculate measured simple-oxide mineral analyses to an explicit fixed oxygen basis. Balance a unique mineral reaction without changing participant sides. Evaluate decomposition and energy above a composition-energy convex hull. Compute neutral three-dimensional periodic ionic Coulomb energy. Compute tabulated neutron scattering contrast and macroscopic attenuation of mineral compositions. Evaluate single-metal solid/ion stability at explicit pH and SHE potential.

## Required inputs

Read the chosen complete schema and limitations. Supply measurements or explicitly identified model inputs, units, source and assumptions. Never fill missing field observations from synthetic examples.

## Procedure

1. Choose the operation matching the scientific question.
2. Confirm physical domain, component order, units and provenance.
3. Have the parent bind its fixed private CPU environment; never install or fetch at call time.
4. Invoke the named function with args as a dictionary or JSON-object string after staging.
5. Preserve units/hashes and interpret within the declared assumptions.

## Tools and synthetic examples

### Geo500MineralOxygenBasisFormula

Recalculate measured simple-oxide mineral analyses to an explicit fixed oxygen basis.

Entrypoint: geological_agent.geology.expansion501_geology:mineral_oxygen_basis_formula. Example: assets/expansion501-geology/Geo500MineralOxygenBasisFormula.json (SYNTHETIC).

Total 90..102 wt%; supplied FeO/Fe2O3 retained; no redox inference or missing-component imputation.

[Reviewed upstream implementation](https://github.com/morganjwilliams/pyrolite/blob/ab651b448ecd2ce1bc22d752b80a977a1f4dd1ca/pyrolite/mineral/transform.py).

### Geo500MineralReactionBalance

Balance a unique mineral reaction without changing participant sides.

Entrypoint: geological_agent.geology.expansion501_geology:mineral_reaction_balance. Example: assets/expansion501-geology/Geo500MineralReactionBalance.json (SYNTHETIC).

Unique stoichiometric nullspace required; forbids omitted participants and upstream side swaps; no reaction kinetics or favorability inferred.

[Reviewed upstream implementation](https://github.com/materialsproject/pymatgen-core/blob/cddebfb21ed5acaee3987948b6704a2790d4e056/src/pymatgen/analysis/reaction_calculator.py).

### Geo500MineralPhaseHull

Evaluate decomposition and energy above a composition-energy convex hull.

Entrypoint: geological_agent.geology.expansion501_geology:mineral_phase_hull. Example: assets/expansion501-geology/Geo500MineralPhaseHull.json (SYNTHETIC).

At most four elements; all elemental terminal references required by upstream; mixing incompatible energy references is forbidden.

[Reviewed upstream implementation](https://github.com/materialsproject/pymatgen-core/blob/cddebfb21ed5acaee3987948b6704a2790d4e056/src/pymatgen/analysis/phase_diagram.py).

### Geo500PeriodicIonicLatticeEnergy

Compute neutral three-dimensional periodic ionic Coulomb energy.

Entrypoint: geological_agent.geology.expansion501_geology:ionic_lattice_energy. Example: assets/expansion501-geology/Geo500PeriodicIonicLatticeEnergy.json (SYNTHETIC).

Neutral ordered 3D cells only; no implicit charge compensation, metallic screening or full formation-energy claim.

[Reviewed upstream implementation](https://github.com/materialsproject/pymatgen-core/blob/cddebfb21ed5acaee3987948b6704a2790d4e056/src/pymatgen/core/ewald.py).

### Geo500MineralNeutronContrast

Compute tabulated neutron scattering contrast and macroscopic attenuation of mineral compositions.

Entrypoint: geological_agent.geology.expansion501_geology:mineral_neutron_contrast. Example: assets/expansion501-geology/Geo500MineralNeutronContrast.json (SYNTHETIC).

Natural-isotope elemental formulas only; tabulated bound-atom approximation, not magnetic/thermal material-specific scattering.

[Reviewed upstream implementation](https://github.com/python-periodictable/periodictable/blob/83b643f4ca4c7d8cf5202c13e32921b572da9896/periodictable/nsf.py).

### Geo500MineralEhPHStability

Evaluate single-metal solid/ion stability at explicit pH and SHE potential.

Entrypoint: geological_agent.geology.expansion501_geology:mineral_eh_ph_stability. Example: assets/expansion501-geology/Geo500MineralEhPHStability.json (SYNTHETIC).

Single-metal H/O systems only, room-temperature upstream PREFAC; no arbitrary temperature, database download, water-stability certification or kinetic persistence claim.

[Reviewed upstream implementation](https://github.com/materialsproject/pymatgen/blob/e3fdb6d4bb2a3bc1622f4c133e088d660f0c3c26/src/pymatgen/analysis/pourbaix_diagram.py).

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

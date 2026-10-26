---
id: expansion501_geology_porous_geometry
name: "Pore geometry and capillary accessibility"
description: "Measure edge-censored pore chord-length distributions. Measure maximal-sphere local pore radii and pore-volume radius distribution. Simulate inlet-accessible quasistatic drainage with explicit capillary pressure and defender trapping. Solve steady normalized pore diffusion and derive effective diffusivity, formation factor and tortuosity from a face-connected binary voxel geometry."
when_to_use: "Use only for this documented scientific task."
tools:
- Geo500PoreChordDistribution
- Geo500PoreBodyRadiusDistribution
- Geo500QuasistaticCapillaryDrainage
- Geo500PoreDiffusionTortuosity
required_inputs:
- Explicit data, units, assumptions and data_source
constraints:
- No imputed grade, arbitrary code, network fetch or runtime installation
- Preserve uncertainty and native provenance
expected_outputs:
- Finite scientific JSON with units and hashes
---

# Pore geometry and capillary accessibility

## When to use

Measure edge-censored pore chord-length distributions. Measure maximal-sphere local pore radii and pore-volume radius distribution. Simulate inlet-accessible quasistatic drainage with explicit capillary pressure and defender trapping. Solve steady normalized pore diffusion and derive effective diffusivity, formation factor and tortuosity from a face-connected binary voxel geometry.

## Required inputs

Read the chosen complete schema and limitations. Supply measurements or explicitly identified model inputs, units, source and assumptions. Never fill missing field observations from synthetic examples.

## Procedure

1. Choose the operation matching the scientific question.
2. Confirm physical domain, component order, units and provenance.
3. Have the parent bind its fixed private CPU environment; never install or fetch at call time.
4. Invoke the named function with args as a dictionary or JSON-object string after staging.
5. Preserve units/hashes and interpret within the declared assumptions.

## Tools and synthetic examples

### Geo500PoreChordDistribution

Measure edge-censored pore chord-length distributions.

Entrypoint: geological_agent.geology.expansion501_geology:pore_chord_distribution. Example: assets/expansion501-geology/Geo500PoreChordDistribution.json (SYNTHETIC).

Binary physical pore mask, no segmentation; sampled lines separated by one voxel; boundary-touching chords removed.

[Reviewed upstream implementation](https://github.com/PMEAL/porespy/blob/916fdc135bfb08d84b8d9173d6de9174ff217e5d/src/porespy/filters/_funcs.py).

### Geo500PoreBodyRadiusDistribution

Measure maximal-sphere local pore radii and pore-volume radius distribution.

Entrypoint: geological_agent.geology.expansion501_geology:pore_body_radius_distribution. Example: assets/expansion501-geology/Geo500PoreBodyRadiusDistribution.json (SYNTHETIC).

Solid exterior collar required; fixed integer radii, smooth=True, brute-force upstream method; radius not diameter.

[Reviewed upstream implementation](https://github.com/PMEAL/porespy/blob/916fdc135bfb08d84b8d9173d6de9174ff217e5d/src/porespy/filters/_lt_methods.py).

### Geo500QuasistaticCapillaryDrainage

Simulate inlet-accessible quasistatic drainage with explicit capillary pressure and defender trapping.

Entrypoint: geological_agent.geology.expansion501_geology:quasistatic_capillary_drainage. Example: assets/expansion501-geology/Geo500QuasistaticCapillaryDrainage.json (SYNTHETIC).

No generated Young-Laplace pressure or hidden surface tension; explicit pressure input. Infinity is represented by null plus masks, not silently replaced with a finite pressure.

[Reviewed upstream implementation](https://github.com/PMEAL/porespy/blob/916fdc135bfb08d84b8d9173d6de9174ff217e5d/src/porespy/simulations/_drainage.py).

### Geo500PoreDiffusionTortuosity

Solve steady normalized pore diffusion and derive effective diffusivity, formation factor and tortuosity from a face-connected binary voxel geometry.

Entrypoint: geological_agent.geology.expansion501_geology:pore_diffusion_tortuosity. Example: assets/expansion501-geology/Geo500PoreDiffusionTortuosity.json (SYNTHETIC).

PoreSpy 3.2.0 calls OpenPNM 3.6.1 and its fixed PyAMG solver; no local replacement diffusion solver. Dedicated profile requires SciPy 1.16.2 and pandas 2.3.2. Never install this profile over the existing pores or main environment. 2D means unit out-of-plane thickness; isotropic voxel spacing cancels from the relative diffusivity. Boundary distance is (shape[axis]-1)*spacing. Both solid and void required; face-connected spanning pores required. Nonspanning pores are removed by upstream and both original/effective porosities are returned. Fixed residual tolerance 1e-10 and relative inlet/outlet flux-balance tolerance 1e-6. No arbitrary solver, executable, convergence loosening or GPU. Concentration is meaningful only where retained_pore_mask is true; zeros elsewhere are upstream solid/dropped-void sentinels, not measurements. Full binary lock, including OpenPNM's Linux x86_64 pypardiso dependency, remains pending. Only CPU PyAMG is explicitly selected.

[Reviewed upstream implementation](https://github.com/PMEAL/porespy/blob/916fdc135bfb08d84b8d9173d6de9174ff217e5d/src/porespy/simulations/_dns.py).

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

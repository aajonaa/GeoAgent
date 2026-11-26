---
id: expansion501-geology-mantle-processes
name: "Anhydrous mantle decompression melting"
description: "Integrate anhydrous two-lithology decompression melting with fixed published lithology laws."
when_to_use: "Use only for this documented scientific task."
tools:
- GeoMantleMeltingPath
required_inputs:
- Explicit data, units, assumptions and data_source
constraints:
- No imputed grade, arbitrary code, network fetch or runtime installation
- Preserve uncertainty and native provenance
expected_outputs:
- Finite scientific JSON with units and hashes
---

# Anhydrous mantle decompression melting

## When to use

Integrate anhydrous two-lithology decompression melting with fixed published lithology laws.

## Required inputs

Read the chosen complete schema and limitations. Supply measurements or explicitly identified model inputs, units, source and assumptions. Never fill missing field observations from synthetic examples.

## Procedure

1. Choose the operation matching the scientific question.
2. Confirm physical domain, component order, units and provenance.
3. Have the parent bind its fixed private CPU environment; never install or fetch at call time.
4. Invoke the named function with args as a dictionary or JSON-object string after staging.
5. Preserve units/hashes and interpret within the declared assumptions.

## Tools and synthetic examples

### GeoMantleMeltingPath

Integrate anhydrous two-lithology decompression melting with fixed published lithology laws.

Entrypoint: geological_agent.geology.expansion501_geology:mantle_melting_path. Example: assets/expansion501-geology/GeoMantleMeltingPath.json (SYNTHETIC).

Fixed dry Katz2003 lherzolite plus Shorttle2014 harzburgite; no model/callback parameters; freezing allowed and pressure endpoints not shifted. GPL LICENSE conflicts with MIT packaging classifier; redistribution review pending.

[Reviewed upstream implementation](https://github.com/simonwmatthews/pyMelt/blob/53246591d796275b4d3c7e6102897a886b76d63a/pyMelt/mantle_class.py).

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

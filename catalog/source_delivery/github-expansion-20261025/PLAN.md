# Additional GitHub scientific-tool intake

## User requirement and baseline

The user requested at least 100-plus ADDITIONAL useful scientific tools, not
100 repositories or a list of proposed packages. The minimum acceptance target
is 101 new, nonduplicate professional operations; the planning target is 120.
Baseline: 229 professional operations, 12 runtime tools, 50 Skills. The previous
nine mineral operations are part of that baseline and cannot be counted again.

## Parallel source-authoring groups

| Group | Planning allocation | Scientific scope |
| --- | ---: | --- |
| geophysics | 30 | Gravity/magnetics, seismic exploration, elastic/rock physics |
| remote | 30 | Spectral analysis, imagery, segmentation, texture and change |
| geology | 30 | Structure, mineral chemistry, geostatistics and geological logs |
| spatial | 30 | GIS, terrain, hydrogeomorphology and local spatial statistics |

These allocations are targets, not implemented or verified counts. Cross-group
semantic review must remove duplicate scientific capabilities even when names,
packages or parameter presets differ. Incompatible or unlicensed operations
remain explicitly blocked and do not contribute to the accepted count.

## Admission and acceptance

1. Read the actual upstream API/source, record its repository, version, commit,
   license and scientific restrictions. No invented APIs or implementation.
2. State the useful scientific task and how it differs from existing tools.
   Aliases, coordinate components and parameter-only variations do not count.
3. Supply complete input/output schemas, units, bounds, structured errors,
   provenance, exact dependencies, standalone examples and a coherent Skill.
4. Preserve CRS, masks, NoData, coordinates and the original measurements.
   Never infer ore grade/reserves from spectral similarity or a synthetic test.
5. Use an independent numerical oracle, not the same upstream call as its own
   expected result; retain invalid-input, units, source and artifact checks.
6. Exercise standalone dict/JSON, native registration/transport and applicable
   artifacts in an isolated CPU environment. No GPU use or shared dependency
   downgrade. Runtime dependency installation is prohibited.
7. Test the complete merged candidate and preserve the exact original 229-tool
   catalog, examples, source implementations and unrelated application changes.
8. Release/deployment/browser acceptance have separate evidence. Source-only
   candidates, passing tests, deployed operations and AI Lab acceptance are not
   interchangeable states.

## Current execution boundary

Four disjoint source-authoring tasks are in progress. The running 229-tool
application is not modified by this intake. No deployment, browser acceptance or
laboratory submission is claimed. GPU 0 and all other GPUs remain unused.

Candidate fragments live under `groups/<group>/`. The parent integration runner
builds a fresh candidate from an explicit baseline and the fragments; it does not
overwrite the live application or silently change failed test expectations.

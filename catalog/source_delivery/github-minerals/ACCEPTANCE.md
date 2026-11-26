# GitHub mineral, remote-sensing and structural tools

## Scope

Nine operations from three upstream MIT-licensed projects are added to the
existing 220 professional operations. They add three Skills, taking the Skill
catalog from 47 to 50. This does not claim completion of every project in the
separate original 101-project intake.

- Spectral Python 0.25: spectral angle matching, continuum removal,
  unconstrained linear unmixing, and georeferenced spectral angle maps.
- pyrolite 0.3.7: centred log-ratio transformation, oxide mass-to-mole
  conversion, and explicit-reference rare-earth element patterns.
- mplstereonet 0.6.3: structural orientation analysis and plane intersections.

The exact upstream commits, licenses, schemas, units, limitations, examples and
dependency hashes are retained alongside these records. Upstream numerical
algorithms are not replaced with demonstration implementations.

## Fresh independent acceptance

Run: `github-minerals-20261025-r3` on A100, with all GPUs disabled.

- 292 passed, zero failed, zero skipped; 131.43 seconds.
- All 229 professional operations exercised through the native tool runtime.
- All nine additions exercised through dict/JSON, native runtime and transport
  interfaces with independent numerical expectations.
- Original 220 catalog entries, 47 Skills and examples checked for preservation.
- Artifact hashes, input immutability, CRS, calibration, masks, NoData,
  undeclared arguments, workspace escape and missing dependencies checked.
- Synthetic fixtures are explicitly marked and were not added to knowledge data.
- No paid model, chat model or GPU used.

This run uses the latest literature-fix application baseline and its private
dependencies. The earlier `r2` run also passed 292 tests but is not substituted
for this latest-baseline run. Earlier import failures remain in the private
acceptance archive. pyrolite 0.3.8.post1 was not enabled: its import was
incompatible with the installed Matplotlib API; 0.3.7 was pinned and retested.

## Release boundaries

Source integration and CPU acceptance are complete. Deployment has a separate
receipt and preserves the live application changes not belonging to this intake.
Browser acceptance remains pending because the browser tool denies the saved
origin permission for `http://127.0.0.1:18015/`. No HTTP client, alternate origin
or alternate browser is used to bypass that denial. Neither these tests nor a
listening service port establish browser acceptance or model-workflow quality.

The package has not been submitted to the AI Lab. All scientific limitations in
the Skills and schemas remain in force; spectral similarity is not evidence of
ore grade, reserves or a verified mineral deposit.

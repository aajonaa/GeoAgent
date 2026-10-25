# Geological source contribution

R2: 28 active source candidates in five workflow Skills (5/6/5/6/6); two blocked exclusions, a deficit of two against the assigned target of 30. Status: **NOT TESTED / NOT DEPLOYED / NOT SUBMITTED**. Authored count is not a verified acceptance count. No scientific calls, tests, installations, GPU jobs, remote changes, commits, deployment or browser operations were performed.

## Files and regeneration

- `geological_agent/geology/github_expansion_geology.py`: 28 explicit decorated native entrypoints and two undecorated fail-closed exclusions; scientific imports are lazy.
- `catalog/source_delivery/github-expansion-20261025/groups/geology/build_contribution.py`: standard-library-only metadata/fixture generator, restricted to this contribution's paths.
- `catalog-additions.json`: additive `{tools: [], skills: []}` payload, complete input/output schemas and AI Lab metadata.
- `candidate-operations.json`: exact requested geology group schema; one row per tool, scientific deduplication rationale and analytic oracle.
- `examples-additions.json`: tool-ID to native-argument mapping, matching existing integration convention.
- `oracle-cases.json`: numeric expected values, explicit analytic derivations, per-operation negative arguments and errors. No upstream outputs were used to produce the expected values.
- `sources.json` and `licenses/`: exact release metadata, public repository/commit/API evidence and unmodified upstream license texts.
- `requirements.txt`: pinned direct/scientific private-worker profile. It is not a fully resolved wheel or transitive-utility lock.
- `tests_local/test_github_expansion_geology.py`: unexecuted CPU test source. It injects the contribution into process-local catalog lookup and never modifies the baseline registry. Missing packages cause failures, not skipped success.
- `assets/github-expansion-geology/`: 28 active explicitly synthetic argument files, one positive synthetic LAS and one nonmonotone negative LAS.
- `catalog/skills/github-geology-*/SKILL.md`: structural fabrics, strain/stress, mineral chemistry, geostatistical validation, drillhole logs.

Regenerate only this contribution's source metadata and fixtures with:

```text
python catalog/source_delivery/github-expansion-20261025/groups/geology/build_contribution.py
```

This command writes source artifacts only. It does not import numerical kernels, run tests, install dependencies or change global registry/dispatch files. License/source evidence is intentionally an input, not refetched online.

## Integration boundary

The parent owns whitelist, worker dispatch, central registry, source registry, shared SDK, global examples, deployment, and the original229-preservation checks. This contribution changes none of them. Use `source_interface.kind=github_expansion_geology` and callable module `geological_agent.geology.github_expansion_geology`. Every active catalog entrypoint has a fixed scientific function name and accepts `args` as dict/JSON through `@operation`. No operation produces files or needs `output_dir`; LAS uses one explicit `las_path`. A zero-length artifacts list and output-hash object are intentional.

The native decoder requires `source_interface.status=source_revised_unverified`; candidate rows and registration lifecycle truthfully use `source_authored_unverified`. These are different existing-contract fields, not an assertion that tests passed.

## Private CPU dependency plan

Retain Python3.12, NumPy2.1.3, SciPy1.15.3, pandas2.3.0, Matplotlib3.10.7, jsonschema4.25.1, scikit-learn1.7.2 and numba0.68.0. Pyrolite0.3.7 is retained. Additional primary packages: APSG2.0.6, scikit-gstat1.0.24, GSTools1.7.0, lasio0.32, welly0.5.2, striplog0.9.2, wellpathpy0.5.2. Scientific transitive pins are in requirements.txt, including gstools-cython1.2.0 and SQLAlchemy1.4.54. All 11 active APSG operations retain APSG2.0.6. The blocked Bingham source profile is separate and MUST NOT be installed into this environment. No NumPy downgrade is requested or permitted by this plan.

Published package metadata is consistent with these Python/numeric versions: APSG requires Python>=3.12 and Matplotlib>=3.9; scikit-gstat requires SciPy<1.17; GSTools-Cython requires Python>=3.10 and NumPy>=1.20. This is metadata evidence only. Parent reports successful joint imports of SQLAlchemy1.4.54, APSG2.0.6 and ObsPy1.4.2 in its private r2 environment, preserving typing-extensions4.16.0, pydantic2.13.5 and langgraph1.2.12. That evidence is not a scientific pass. This worker has not tested imports, ABI compatibility, execution behavior, remaining transitive utilities or complete dependency resolution. Parent must prepare an isolated private CPU worker, retain baseline constraints, resolve/freeze remaining utilities there and decide whether any incompatible kernel is blocked. Never silently alter the shared runtime.

## Scientific boundaries found in source review

- APSG2.0.6 is identified by `src/apsg/__init__.py` at commit `f9f45a52d60521ba37f326a85645df3dee74272e`, matching the 2026-10-16 PyPI publication. Older GitHub tags stop at0.4 and were not mistaken for the maintained API. Distribution/source byte correspondence remains unverified.
- APSG stress inputs use its default compression-positive geological convention. Physical traction vectors use the upstream tension-positive convention. A changed process convention is rejected, never overwritten.
- Directed Fisher statistics remain active. Bingham confidence is BLOCKED and absent from all active manifests, examples, Skills and oracle cases. The r1 degenerate-axis result and copied angle oracle are not scientifically acceptable. Rejecting tied eigenvalues is not a repair. Fold axes remain least-eigenvalue girdle axes, not baseline dominant-plane fits.
- Paired fabric refuses nonorthogonal field pairs instead of letting APSG adjust the observations. Rf/phi and Robin marker estimates are reported together as one tool, avoiding method-count padding.
- Pyrolite unmixing has a global multi-row closure constraint. Each sample is passed separately. Its optimizer does not expose success through the returned API; solutions must satisfy an explicit reconstruction tolerance. No local optimization formula replaces the kernel.
- CIPW is BLOCKED and absent from the active manifests, examples, Skills and oracle cases. The unregistered adapter draft now constructs a float DataFrame to address integer casting, but the upstream fluorapatite string-versus-list branch defect remains. Reviewed pyrolite0.3.8post1 and develop sources retain it. No F=0 restriction or silica-only fixture is offered as scientific clearance.
- SpaceTimeVariogram includes only one joint ordering of station/time pairs. The adapter calls it for forward and reversed time arrays and averages the two semivariances with doubled pair counts. It excludes zero-space and zero-time pairs; equally spaced complete repeat observations are mandatory. Constructor marginal fits can fail on unsuitable data and are not presented as validated results.
- Robust estimators are compared within one tool, not counted as three operations. Empty lag bins are null with zero counts. Kriging LOO uses a supplied fixed model, excludes the held-out observation, requires all neighbors in range and rejects any failed fold.
- Block covariance uses the upstream exponential covariance kernel at explicit quadrature nodes. It is exact for equal-weight discrete support and only an approximation to a continuous physical block; it produces no mineral grades or reserves.
- Mahalanobis chemical departure uses a declared independent ILR background, full-rank empirical covariance, no automatic probability threshold and no mineralization label.
- Welly's single-zone block reducer has an upstream uninitialized-boundary defect. That configuration is rejected explicitly; supported multi-zone calculations use the original reducer. Depth resampling is bounded to observations and missing log values are not imputed.
- LAS parse uses local file streams, disabled repair substitutions and declared metre depth units. Missing curve entries remain JSON null, never zero-filled. Striplog intersections use one caller-declared borehole MD datum; along-hole interval support is not true stratigraphic thickness.

## Evidence and blockers

Every active candidate has positive analytic expected values, an operation-specific negative example and native provenance checks in authored test source. Expected values use standard-library arithmetic, exact geometry, stoichiometry or hand-enumerated sample pairs. No test was run and no passing acceptance receipt exists.

Outstanding blockers: parent integration/whitelisting; private package installation and complete runtime freeze; CPU analytic/negative/schema/provenance acceptance; exact distribution/source correspondence if required; real-data and model-workflow validation; receiving-lab approval and adapter licensing. The baseline online229 remains unchanged.

Upstream licensing is recorded accurately: APSG, lasio and scikit-gstat MIT; GSTools and wellpathpy LGPL3; welly and striplog Apache2; scikit-learn BSD3; pyrolite the CSIRO BSD/MIT variation, not a generic MIT label. These records describe upstream notices, not legal approval of downstream distribution.

## R2 exclusions, procurement and preserved evidence

- `blocked-operations.json`: exact reasons for excluding GeoAPSGBinghamAxialConfidence and GeoPyroliteCIPWNorm; neither contributes to the active count.
- `private-workers/bingham/requirements-source.txt`: direct immutable APSG source URL plus retained scientific pins. It is a procurement profile, not an installed or fully hashed wheel lock.
- `private-workers/bingham/worker-profile.json`: disabled single-tool CPU worker binding specification, with no main-runtime fallback and no user-controlled interpreter or callable.
- `private-workers/bingham/README.md`: fixed environment location, source identity/provenance requirements and remaining activation gates.
- `revisions/r1-source-snapshot/`: write-once pre-r2 source, generated manifests, Skills and examples. Original r1 execution/failure reports elsewhere are untouched; this snapshot is not claimed to be an execution report.

The LAS hash expectation now uses a scalar content descriptor for scalar las_path, matching the real contract. No production provenance contract was changed. No r2 test has been run here. The standard-library generator only regenerates this group's source artifacts.

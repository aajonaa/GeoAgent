# Remote blocked-r6 source preparation

This additive revision preserves the original 26 source-adapted entries, the eight
blocked IDs, existing failures, and the original main entry module.

Authored: bounded SAFE inventory/hash/reference validation; explicit Sentinel-1
acquisition/coregistration/polarization/time contracts; mask/affine/NoData checks;
offline ERA5 descriptor contracts; conservative PySolid leap-table gate; two
concrete unregistered upstream compositions (S1A/B pixelwise range bias and
PROSPECT-D/4SAIL canopy-soil reflectance).

The input preflight deliberately does NOT claim complete XML sensor semantics,
GRIB content/vertical coverage, real-world observations, native build validity or
scientific acceptance. Synthetic preflight fixtures are not valid sensor products.
The canopy alternative is labelled pypro4sail / radiative-transfer-models 1.6.2,
not passed off as the original unlicensed-candidate repository.

Source counts: 26 existing registered-in-contribution adapters; 2 new internal
kernel compositions; 0 new public registrations; all 8 pending candidates blocked.
Test results, when executed, are recorded in local-contract-report-r1.json.
That report separates stdlib preflight tests from scientific tests (not run).
The two ScientificOracleTests are source-authored only and are not selected by
the local Flow runner.

All new source is not_deployed / not_submitted / formal_eligible=false;
model workflow and platform certification remain not_run. The prior SSH policy
denial is not retried or bypassed. Requirements-pending.txt is a direct-source pin
plan, NOT a complete solved/accepted environment lock. Do not install it into any
shared environment. Shared IPC request is in shared-interface-request.md.

# expansion501 remote source contribution

## Status

26 source-adapted candidates; 8 blocked; all 34 assigned IDs accounted for. Six workflow Skills. Source-only, not tested, not integrated, not deployed, not submitted, and not AI Lab certified. Old research and accepted runtime are unchanged.

## Integration contract

- Module `geological_agent.geology.expansion501_remote`; kind `expansion501_remote`.
- Explicit named `@operation(ID)` functions take `args` and `output_dir`.
- Closed top-level input/output schemas; output requires units, artifacts, provenance.
- Parent stages catalog before decorated calls and owns shared kind/module allowlist and dispatch.
- adaptation-status.json accounts for every assignment; blocked IDs are absent from catalog additions.
- delivery-files.json is the explicit repository-relative staging/hash inventory.
- No generator or scientific/test execution was performed; delivery consists of materialized source files.

## Bounded input/artifact semantics

Closed inline array inputs avoid unrestricted paths. Tiles have one explicit CRS/affine/mask/nodata and at most128x128 pixels. All values are bounded/finite. Neighborhood/global kernels reject incomplete tiles rather than impute. Output grids are preserved except documented template-placement crop/full-window exclusion. Parameter/coefficient CSVs are not assigned a false CRS.

SAR inputs must already be processed and co-registered, with complex/unwrapped state appropriate to the operation. Metadata declarations do not independently authenticate the sensor. No RGB-to-SAR path, mineral identification, ore-grade imputation or silent calibration is offered.

## Exact direct pins and environment gates

- Shared baseline: numpy2.1.3, scipy1.15.3, rasterio1.4.3, jsonschema4.25.1.
- Optical: scikit-image0.26.0, spectral0.25, PyWavelets1.10.0, pyspectral0.14.3.
- SarPy: source commit19a6ca3b8cc2e268b58ecf2523bd25c327a0a58c declaring2.1.1; no inferred release tag. Private transitive resolution/source correspondence pending.
- MintPy1.6.4, h5py3.16.0, pyproj3.7.2, matplotlib3.10.7, pandas2.3.0, scikit-image0.26.0. Parent must invoke the adapter in a private CPU environment with EXPANSION501_REMOTE_PROFILE=mintpy-1.6.4-cpu and CUDA_VISIBLE_DEVICES empty or -1.
- OTB9.1.1 is a non-pip native Linux prerequisite, not a main-environment replacement.

The MintPy adapter does not start/install a Python worker. Parent transport/invocation inside the private environment is still an integration prerequisite. The accepted JSON-only native bridge is not reused for artifacts.

OTB uses administrator-owned EXPANSION501_OTB_ROOT, fixed bin/otbApplicationLauncherCommandLine and fixed lib/otb/applications/otbapp_APPLICATION.so. The prefix requires expansion501-identity.json with version9.1.1, source_commit154726b379fdb39b481ee8fd793fbd3d584884e6, and files mapping relative paths to reviewed64hex SHA256. Launcher and selected application are mandatory; parent must include every runtime dependency. No binary hashes are invented.

The native adapter uses private generated input copies, allowlisted argv, bounded64KiB stdout/stderr,120s deadline, process-group termination, actual exit status and raster format/shape/finite/CRS/affine checks. CPU/thread and no-network environment settings are supplied. OS memory/disk/network containment, full dependency identity completeness and cancellation acceptance remain parent gates. No native process ran during authoring.

Direct requirements are exact pins, NOT a finished transitive resolver lock. GPL/Apache/MIT/BSD redistribution, transitive/native licenses, ABI compatibility and binary identity require independent review. Do not install profiles over the shared main environment.

## Exact blocked candidates

- `GeoSARSigma0Calibration`: OTB SARCalibration requires original sensor calibration/noise LUTs and product metadata not preserved by the bounded array interface. A closed SAFE/product dependency manifest, safe copied sidecars, and independently calibrated sigma0 fixture remain unauthored; DN-only scaling would substitute an invented kernel.
- `GeoInSARClosureAmbiguityCorrection`: MintPy mutates an interferogram HDF stack and solves integer ambiguities with cvxopt/connected-component sampling. Safe operation-specific mutable HDF/component transport, cvxopt ABI lock and an independently identifiable multi-triangle ambiguity fixture are not authored.
- `GeoInSARTroposphericDelay`: MintPy tropo_pyaps3 CLI includes weather acquisition; offline use needs calc_delay_timeseries plus validated local ERA5 GRIB. PyAPS3/GRIB native identity and local pressure-level temperature/humidity/geopotential product coverage for every acquisition UTC are unresolved; no downloads authorized.
- `GeoInSARSolidEarthTideCorrection`: Compiled PySolid kernel is required. Located v0.3.4 release does not yet close reviewed source/build/license identity. Need pinned licensed Fortran CPU build, acquisition UTC/tide references and independent nonzero tide oracle; no local replacement formula.
- `GeoInSARMultilookClosureBias`: MintPy closure_phase_bias estimate path calls ISCE2/SNAPHU unwrapping; it is not a standalone Python kernel. No reviewed private ISCE2/SNAPHU identity/license/fixed nested-process transport, sequential-network contract or independent closure-bias fixture.
- `GeoInSARSentinelInterplatformRangeBias`: Data-estimation path reads inputs/geometryRadar.h5, derives IW masks from nonzero height and maps SAFE acquisition identity to A/B dates. Need closed three-IW-swath/SAFE-date/radar-geometry transport and independent recoverable bias fixture; genuine zero elevation must not silently become missing swath evidence.
- `GeoRemoteAtmosphericRadiativeTransfer`: Py6S wraps an external 6S engine; reviewed matching native version/source/license/identity is not established. Confirm Py6S source/release correspondence and independently license/pin CPU 6S binary before fixed transport and oracle authoring.
- `GeoRemoteCanopySoilRadiativeTransfer`: Inspected jgomezdans/prosail root and setup.py do not establish redistribution license. Explicit authoritative PROSAIL license and reviewed release/source identity are required; no invented license or replacement canopy formula.

## Acceptance handoff

Remote r1 source checkpoint: the user-approved CCD magnitude correction is authored and its upstream phase is preserved. Independent executable unittest sources are in test_expansion501_remote.py; execution is still not_run. acceptance-plan-r1.json specifies the fresh CPU root, private catalog scope, frozen source-hash prerequisite, confirmed base Python and isolated transport. No generator is running. Parent may freeze this revision for staging. Other adapters and blockers remain unchanged.

numeric-oracles.json gives independent positive analytic expectations; negative-cases.json is a future-test source specification. No tests were run. Approximate optical-flow/LoG/MAD tolerances are proposed and unverified. Parent must check actual upstream conventions, schemas, artifacts, negative inputs and baseline regressions. Source-written does not imply usable; previous reports are not reused.

# Tools121 remediation acceptance

Professional tools: 457; Skills: 97.
This release adds 81 operations; 111/121 cohort operations passed.
All published cohort operations were replayed through the protected production parent runtime.
No GPU or model calls were used. Deployment, push, and browser acceptance are separate gates.
Original failed attempts are retained. Internal acceptance is not AI Lab certification.

## Excluded operations

| Tool | Status | Reason |
| --- | --- | --- |
| `GeoDCResistivityInversion` | not_passed | Independent nodal Robin-boundary inversion reference not yet complete. |
| `GeoEMConductiveSphere` | not_passed | Geoana 0.9.0 exterior electric-field radial scaling disagrees with analytic conducting-sphere equation. |
| `GeoFDEMConductivityInversion` | not_passed | Independent Maxwell/Hankel quadrature forward reference agrees to 2.02e-8 relative; nonlinear inversion acceptance pending. |
| `GeoIPChargeabilityInversion` | not_passed | Independent linearized DC/IP inversion reference not yet complete. |
| `GeoSeismicARPhasePick` | not_passed | Corrected field mapping; cropped external benchmark retains P but upstream S=0, wrapper S=null. Full 12000-sample benchmark exceeds 4096 cap. |
| `GeoSeismicPolarization` | not_passed | Rank-one Flinn rectilinearity error 2.17e-8 exceeds unchanged 1e-8 gate. |
| `GeoSeismicPrestackElasticInversion` | not_passed | Finite LSQR iterations do not match converged independent dense Aki-Richards inversion; damping/conditioning unresolved. |
| `GeoSeismicTauPRays` | private_replay_passed_production_integration_pending | Correct Java path reference binding passed 46 private direct/ToolExecutor checks with unchanged adapter and tolerance; production CPUv2 profile and merged-release acceptance are not yet performed. Excluded from this release. |
| `GeoSurfaceWaveEigenfunctions` | not_passed | Disba 0.7.0 Love eigenfunction halfspace initialization is zero rather than the analytic nonzero interface amplitude. |
| `GeoTDEMConductivityInversion` | not_passed | Independent absolute-amplitude loop-decay and heterogeneous inversion reference pending. |

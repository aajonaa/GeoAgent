# Tools 121: production deployment, 2026-10-26

## Release identity

- Branch: `codex/tools121-remediation-20261026`.
- Application source commit: `8f9a58d5076390675313223cbe7c5dea57c65e7f`.
- Latest live changes preserved by commit: `a4cd668f029581f944d5b628599eb122bcbfe7b3`.
- Release directory: `/data/wangjian/github-tools121-remediation-20261026-r3`.
- Service: `geotoolagent-hitl-candidate.service`.
- Deployment state: `deployed_backend_accepted`; application PID at acceptance: `471959`.
- Deployment receipt: `deployment/DEPLOYMENT-RESULT.json` under the release directory.
- Receipt SHA-256: `ce8f6c5659ed8c0106c2930f7101477b2a038b4a33a6082c4442f8a149c0d029`.

## Actual deployed counts

| Category | Count |
| --- | ---: |
| Professional tools | 457 |
| Runtime tools | 12 |
| Total registered tools | 469 |
| Skills | 97 |
| Accepted tools in the 121-tool cohort | 111 |
| Excluded tools in that cohort | 10 |
| Additional professional tools versus the previous live release | 81 |

The previous live release already contained 30 accepted members of this cohort.
Therefore, 111 cohort acceptances are not 111 additional tools. Neither candidates
nor excluded tools are included in the deployed counts.

## Acceptance evidence

| Evidence category | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| Spatial tool execution records | 612 | 0 | 0 |
| Remote-sensing tool execution records | 566 | 0 | 0 |
| Geology tool execution records | 916 | 0 | 0 |
| Geophysics tool execution records | 800 | 0 | 0 |
| Registry and CPU-policy controls | 190 | 0 | 0 |
| Release-evidence controls | 235 | 0 | 0 |

The first four rows represent 2,894 actual call records. Control checks are a
separate measure, not additional distinct scientific operations. Historical
failures and 20 historical Skill documentation diagnostics remain available;
they are not reclassified as passing evidence.

The release gate checked actual source, the frozen manifest and execution
configuration hashes, including the additional cold-cache evidence fields.
The original `stage-receipt.json` remains immutable. Publication used the
derived `stage-receipt-sealed.json`. Git blob bytes were verified for all
6,907 release files and 11 release-gate snapshot files before committing.

Only these three approved formal tests were admitted under `tests_local`:

- `tests_local/test_catalog_metadata.py`
- `tests_local/test_professional_catalog.py`
- `tests_local/test_unified_skills.py`

No other local remediation scripts, temporary evidence or unrelated backlog
changes were staged in this release. Release-gate sources and reports are
preserved in `docs/releases/tools121-release-gates-20261026/` as an audit
snapshot, not a claim that they are a standalone portable test runner.

## Preservation and operational scope

All eight approved latest-live citation, presentation, server and frontend
changes were retained. Saved account state, model configurations,
conversations and files passed the deployment preservation check. Other
services were unchanged. Tests and release operations used no GPU, including
GPU 0. Only the GeoAgent application service was switched.

The CPU-cache fix separates the existing JSON/artifact restrictions from the
OS per-file size limit needed by JIT caches. The 64 MiB `RLIMIT_FSIZE` setting
is a per-file limit, not a total cache-size limit. Artifact rules, scientific
algorithms and numerical tolerances were not relaxed.

## Ten tools still excluded from production

| Tool | Remaining blocker or bounded progress |
| --- | --- |
| `GeoDCResistivityInversion` | Shared DC/IP forward and Jacobian reference probe passed 4 checks; independent constrained-inversion acceptance remains incomplete. |
| `GeoIPChargeabilityInversion` | Same shared 4-check probe, not another four independent checks; inverse and full execution-mode acceptance remain incomplete. |
| `GeoEMConductiveSphere` | Upstream Geoana 0.9.0 exterior radial electric-field result disagrees with the independent analytic reference. |
| `GeoSeismicPolarization` | Rank-one Flinn rectilinearity error is about 2.17e-8, above the unchanged 1e-8 tolerance. |
| `GeoSeismicPrestackElasticInversion` | The 50-iteration LSQR result has not matched the independent dense Aki-Richards inverse; conditioning and damping remain unresolved. |
| `GeoSurfaceWaveEigenfunctions` | Original Love-wave half-space interface amplitude is zero. A private analytic prototype passed 7 checks, but a missing `input_source` in its new harness blocks full adapter acceptance. |
| `GeoFDEMConductivityInversion` | Shared EM forward/reference work passed 7 checks, with zero ToolExecutor acceptance calls; inversion acceptance is incomplete. |
| `GeoTDEMConductivityInversion` | Same shared EM reference work, not another seven independent checks. A private comparison draft also needs correction before execution; the original tolerance rule remains binding. |
| `GeoSeismicARPhasePick` | Private run: 46 passed, 4 failed. The valid 12,000-sample reference exceeds the unchanged 4,096-sample input cap; the 4,000-sample crop has no valid S pick. |
| `GeoSeismicTauPRays` | Private numerical and adapter run passed 46/46 after reference binding was corrected. A production CPU-v2 profile and unified release acceptance are still required. Not deployed. |

Private probes and partial checks are progress evidence only. They do not
authorize counting these tools as production-ready or lowering existing
assertions.

## Browser and external handoff status

Backend deployment acceptance passed. Browser acceptance is **not complete**:
the controlled browser has a saved access denial for `http://127.0.0.1:18015/`.
No alternate origin, HTTP/CDP route or browser surface was used to bypass that
restriction. A permitted browser session is still required for UI acceptance.

Internal interface and release checks are not an AI Lab certification. No
official laboratory acceptance is claimed by this release.

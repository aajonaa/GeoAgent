# Geophysics r2 source contribution

Status: **R2 NOT TESTED / NOT DEPLOYED / NOT SUBMITTED**.
29 candidate operations, 5 workflow Skills, 1 excluded blocked operation.
Parent reported r1 basic30 passing; later counterexamples invalidate promotion.
Historical r1 reports and the blocked synthetic fixture remain unchanged.

## Delivery

- geological_agent/geology/github_expansion_geophysics.py
- tests_local/test_github_expansion_geophysics.py
- catalog/source_delivery/github-expansion-20261025/groups/geophysics/build_contribution.py
- catalog/source_delivery/github-expansion-20261025/groups/geophysics/catalog-additions.json
- catalog/source_delivery/github-expansion-20261025/groups/geophysics/examples-additions.json
- catalog/source_delivery/github-expansion-20261025/groups/geophysics/candidate-operations.json
- catalog/source_delivery/github-expansion-20261025/groups/geophysics/sources.json
- catalog/source_delivery/github-expansion-20261025/groups/geophysics/blocked-operations.json
- catalog/source_delivery/github-expansion-20261025/groups/geophysics/r2-status.json
- catalog/source_delivery/github-expansion-20261025/groups/geophysics/independent-oracles.md
- catalog/source_delivery/github-expansion-20261025/groups/geophysics/requirements-geophysics.txt
- catalog/source_delivery/github-expansion-20261025/groups/geophysics/requirements-r2-additions.txt
- catalog/source_delivery/github-expansion-20261025/groups/geophysics/licenses/rock-physics-open.txt
- catalog/source_delivery/github-expansion-20261025/groups/geophysics/diagnostics/r1-stress-anisotropy-source.txt
- assets/github-expansion-geophysics/r2-oracles.json
- assets/github-expansion-geophysics/GeoRockSelfConsistent.json
- assets/github-expansion-geophysics/GeoRockSquirtFlow.json
- assets/github-expansion-geophysics/GeoSeismicHTIReflectivity.json
- catalog/skills/github-geophysics-potential-fields/SKILL.md
- catalog/skills/github-geophysics-effective-media/SKILL.md
- catalog/skills/github-geophysics-grain-fracture/SKILL.md
- catalog/skills/github-geophysics-fluid-effects/SKILL.md
- catalog/skills/github-geophysics-seismic-interpretation/SKILL.md

The stdlib generator refreshes all active candidate assets and owned Skills.
It never imports scientific packages or edits shared catalogs, SDKs or workers.
Candidate rows correspond one-to-one to the 29 emitted tools.
Skill sizes are 4,7,5,7,6. No components, aliases or blocked cases inflate counts.

## R2 changes

GeoRockSelfConsistent now calls the unmodified maintained Equinor
rock_physics_open.shale_models.multi_sca.multi_sca from rock-physics-open1.0.1,
SHA 68cd21b6a581e591d78ef90003292444cb81fe81. Caller moduli are GPa and densities
kg/m3; upstream moduli are converted to Pa. Exact sphere, oblate and prolate
geometries are retained. Both bulk and shear weighted constitutive residuals
must be <=1e-8 of their phase modulus scale. This is an acceptance gate, not
a replacement iteration or a corrected upstream kernel.

GeoSeismicHTIReflectivity now checks actual tensor/density transmission using
the Christoffel vertical-slowness quadratic for each supplied angle and azimuth.
Critical and evanescent modes reject even when incidence satisfies <=35 degrees.
The upstream Ruger amplitude calculation is unchanged.

GeoRockSquirtFlow enforces positive bulk/shear crack-closure bounds and wet
shear compliance at least as large as the supplied crack-free compliance.
The physical inequality is 1/Gwet >= 1/Ghigh > 0; its implied Gwet must also
be >= Gdry. Velocity monotonicity alone is not accepted. Upstream unchanged.

GeoRockStressAnisotropy is BLOCKED, absent from additions/candidates/active
Skill references. Its direct historical function only raises unsupported_conditions.
No equal-strain restriction or local logarithm repair is used to claim success.
The original fixture and source fragment remain diagnostic history.

## Independent numerical evidence

The exact heterogeneous sphere oracle predicts K=8,G=6 GPa and rho=2600 kg/m3.
Nonzero three-phase prolate and mixed-shape fixtures prescribe K=8,G=6 GPa;
positive fractions are constructed by independent Hill/Kelvin tensor angular
moments and linear balance, not upstream PQ or SCA calls. See
independent-oracles.md and assets/github-expansion-geophysics/r2-oracles.json.

Test source includes both residuals, density/Pa units, provenance, caller
nonmutation, sphere/prolate oracles, HTI postcritical cases, squirt physical
negative cases, and native bulk-only premature convergence rejection.
The unequal-strain stress diagnostic is an explicit expected failure, not one
of the 29 successful tools. Parent must report it separately from acceptance.

No scientific tests or validation commands were run by this author.
The shared source_interface literal source_revised_unverified is preserved;
candidate status is source_authored_unverified. Runtime dispatch is fixed to
named functions with no arbitrary user-selected module/function/code.

## Dependencies and licenses

Exact additional private roots: rock-physics-open==1.0.1, tmatrix==1.2.0.
Parent reports their source SHA, wheel ABI and requirements were checked and
installed in r2. This author did not install, download or run those packages.

Complete direct profile:
numpy==2.1.3, scipy==1.15.3, jsonschema==4.25.1, pandas==2.3.0,
matplotlib==3.10.7, KDE-diffusion==1.0.5, scikit-learn==1.7.2,
tmatrix==1.2.0, typing-extensions==4.16.0, numba==0.68.0,
rock-physics-open==1.0.1, choclo==0.3.2, rockphypy==0.0.2, bruges==0.5.4.

SQLAlchemy==1.4.54, pydantic==2.13.5 and langgraph==1.2.12 are untouched;
they are not new adapter dependencies. No shared pin is downgraded.

Equinor is LGPL-3.0, rockphypy GPL-3.0, Choclo BSD-3-Clause, Bruges Apache-2.0.
Verbatim upstream license evidence is retained under licenses/.
These are dependency licenses, not a relicensing claim for our adapter.
Redistribution, adapter licensing and receiving-lab approval remain pending.

## Remaining limitations and acceptance ownership

Parent owns additive integration, fixed dispatch and joint CPU acceptance.
Existing online229 is untouched. No GPU, network access during operations,
installation, SSH, deployment, commits or pushes are performed.

Equinor's native iteration stops on bulk update alone and has an iteration cap.
The dual-residual gate rejects valid inputs when that solver has not converged;
the negative fixture preserves this known upstream limitation. No local fix
is supplied. Stress anisotropy remains excluded without a trustworthy upstream
repair. Berryman_DEM remains excluded for its independently recorded defects.

All fixtures are SYNTHETIC, not observations. Outputs do not establish mineral
presence, grade, resources, reserves or calibrated field accuracy.

# Remote r2 source handoff

Status: NOT TESTED / NOT DEPLOYED / NOT SUBMITTED.

## Counts and historical evidence

30 current source operations, 5 workflow Skills with 6 tools each, 30 examples,
30 candidate-operation records and 30 independent positive numeric oracles.
These are authored candidates, not 30 CPU-verified r2 operations.

GeoRemoteHistogramMatch is excluded as a semantic duplicate of original
SkdownscaleQuantileBiasCorrection. It is not registered or counted. Its original
candidate text, example, oracle, adapter source and upstream commit/license
record are retained in excluded-candidates.json. Historical r1 CPU reports are
not modified. The parent's reported 29 passing r1 numeric subcases and matched-
filter failure are historical evidence only, not evidence that r2 passes.

## Approved changes

- MatchedFilter accepts only upstream shapes (n,) or (n,1), with n exactly the
  effective valid-pixel count; only the trailing singleton axis is removed.
  Real/finite results are required. The independent expected response stays 1.0,
  with 63 valid pixels in the original fixture.
- TVDenoise input/output schemas reject binary and label units. Runtime checks
  require nonnegative continuous radiometry and bound the declared reflectance/
  normalized-intensity profiles to [0,1]. Output retains continuous input units.
- SensorBandResample replaces the excluded histogram operation. It calls SPy's
  BandResampler with explicit centers/FWHMs, requires fully covered target
  intervals and nonoverlapping source intervals, and preserves spatial CRS,
  affine, joint band masks and quality exclusions.
- New target-band GeoTIFF metadata, resampling-weights.csv, JSON weight matrix
  and native artifact/provenance hashing accompany the new operation.
- New synthetic fixture: source intervals [950,1050] and [1050,1150] nm,
  target center 1050 nm/FWHM 200 nm, reflectances .2/.6. Gaussian symmetry gives
  weights .5/.5 and expected reflectance .4. This oracle is independent.
- Test SOURCE covers missing/mismatched CRS and shifted affine for auxiliary
  rasters, missing CRS/nonfinite samples for all operations, real numeric
  nonfinite parameters, unit/domain failures, malformed matched-filter results,
  full-coverage rejection, output units, CSV weights, and masks/georeferencing.
  No scientific tests have been run by this revision's author.

## Exact paths

The machine-readable r2-delivery.json enumerates every generated artifact and
authored source path. All paths are relative to the existing repository root:
C:/Users/jona/github/GeoAgent-tools220-release.

- geological_agent/geology/github_expansion_remote.py
- tests_local/test_github_expansion_remote.py
- catalog/source_delivery/github-expansion-20261025/groups/remote/build_contribution.py
- catalog/source_delivery/github-expansion-20261025/groups/remote/FILE_SCHEMAS.md
- catalog/source_delivery/github-expansion-20261025/groups/remote/R2_HANDOFF.md
- catalog/source_delivery/github-expansion-20261025/groups/remote/catalog-additions.json
- catalog/source_delivery/github-expansion-20261025/groups/remote/candidate-operations.json
- catalog/source_delivery/github-expansion-20261025/groups/remote/examples-additions.json
- catalog/source_delivery/github-expansion-20261025/groups/remote/sources.json
- catalog/source_delivery/github-expansion-20261025/groups/remote/excluded-candidates.json
- catalog/source_delivery/github-expansion-20261025/groups/remote/requirements.txt
- catalog/source_delivery/github-expansion-20261025/groups/remote/r2-delivery.json
- assets/github-expansion-remote/oracles.json
- assets/github-expansion-remote/README.md
- assets/github-expansion-remote/spectral-resample.tif
- assets/github-expansion-remote/quality-spectral.tif
- catalog/skills/github-remote-spectral/SKILL.md
- catalog/skills/github-remote-morphology/SKILL.md
- catalog/skills/github-remote-texture/SKILL.md
- catalog/skills/github-remote-segmentation/SKILL.md
- catalog/skills/github-remote-radiometry/SKILL.md

The stdlib generator also deterministically reauthors the unchanged original
synthetic TIFF fixtures listed in r2-delivery.json. No test report, shared SDK,
registry, worker, baseline catalog or another group's files are write targets.

## Dependency pins and primary upstream evidence

Target scientific Python: 3.12. No new package or NumPy downgrade is requested.

numpy==2.1.3
scipy==1.15.3
rasterio==1.4.3
matplotlib==3.10.7
jsonschema==4.25.1
spectral==0.25
scikit-image==0.26.0

The new kernel is spectral.algorithms.resampling.BandResampler.
Spectral 0.25 commit: bd91dc47377028683ef5c97bc7c1cc2dff14012c; MIT.
Primary source:
https://github.com/spectralpython/spectral/blob/bd91dc47377028683ef5c97bc7c1cc2dff14012c/spectral/algorithms/resampling.py
License evidence:
https://github.com/spectralpython/spectral/blob/bd91dc47377028683ef5c97bc7c1cc2dff14012c/LICENSE.txt

Existing scikit-image 0.26.0 commit:
ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8.
Existing release/license evidence remains in sources.json and licenses/.
No dependency installation or binary compatibility check was performed here.

## Remaining parent work

Parent owns CPU acceptance, fixed module dispatch/whitelist and strictly additive
global integration. Receiving-lab approval, adapter license and workflow
acceptance remain pending. No r2 scientific operation is represented as verified,
deployed or submitted. Do not count upstream failures or semantic duplicates as
usable net-new operations. There is no known new direct-dependency blocker;
actual pinned CPU compatibility remains untested in this revision.

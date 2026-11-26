# Remote expansion500 research inventory

Status: `research_only_not_integrated_not_counted`

Delivered: **20 proposed operations**, not 45. The remaining **25 slots are unfilled**. Research stopped at the user's explicit cutoff; partially assembled leads are not represented as completed candidates.

No adapters, Skills, tests or registry entries are authored here. No scientific execution, installation, GPU use, release modification, deployment or push was performed. The accepted117 and reported deployed346 tools/70Skills remain outside this contribution.

## Files

- `inventory.json`:20 named candidate records, exact upstream callables, release/source pins, license evidence, scope, units, masks/grid constraints, independent synthetic numeric oracles, nearest-capability comparisons, dependency plans and risks.
- `README.md`:this handoff summary.

## Top five for parent review

1. `GeoSARSigma0Calibration`:metadata-LUT Sentinel-1 linear backscatter calibration; independent |DN|^2/LUT^2 oracle=1. Requires an isolated OTB runtime and a synthetic supported metadata fixture.
2. `GeoRemoteBrightnessTemperature`:monochromatic Planck inversion; independently constructed300K blackbody oracle. Brightness temperature is not land-surface temperature.
3. `GeoRemotePhaseUnwrap`:2D phase-cycle recovery; relative phase-difference oracle=7*pi/2. Already-installed scikit-image.
4. `GeoRemoteMADChange`:canonical-correlation multispectral temporal change; independent covariance oracle gives correlations0.25/0.5 and change variances1.5/1.
5. `GeoRemotePansharpenFusion`:registered PAN/multispectral fusion; constant-field preservation oracle=0.2. Not equivalent to reprojection or spectral-band resampling.

## Exact primary dependency proposals

- Reuse `scikit-image==0.26.0`, commit `ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8`.
- Reuse `spectral==0.25`, commit `bd91dc47377028683ef5c97bc7c1cc2dff14012c`.
- Private candidate `PyWavelets==1.10.0`, commit `4bd3a5f935ce53a06a531af6fbb0ab941e753adc`.
- Private candidate `pyspectral==0.14.3`, commit `14c8dfd01c3fa705af3a9e70d5d0a3d0b06333e0`.
- Private SarPy source snapshot `19a6ca3b8cc2e268b58ecf2523bd25c327a0a58c`, declaring2.1.1. Published-wheel correspondence is not established; exact source reference is in JSON.
- Standalone CPU `OTB9.1.1`, commit `154726b379fdb39b481ee8fd793fbd3d584884e6`. This is not a pip-package requirement and must not replace shared GDAL/PROJ/NumPy libraries.

Preserve Python3.12, NumPy2.1.3, SciPy1.15.3 and all shared baseline pins. New transitive packages are **not fully locked**; this is research, not an install-ready requirements file. SarPy/sarkit and OTB native-runtime compatibility are explicit private-worker gates.

## Evidence and distinctness

Primary evidence comes from pinned upstream source plus official release/docs links in JSON. OTB's current Cookbook indexes mixed9.1/10.0 material; the official GitHub mirror exposed9.1.1 and10.0.0-rc1, not a final10.0.0 tag. These candidates therefore use inspected9.1.1 source rather than assuming a10.0 release pin.

The original registry and all four previous github-expansion-20261025 group catalogs were read once for manual semantic comparison. This is not an automated proof of net-new acceptance; parent review must also resolve duplicates against other expansion500 research groups.

Excluded: histogram/quantile mapping, supplied-endmember unmixing variants, extra RX/segmentation/denoising variants, alternative polarization bases, axes and display variants. OTB deburst is deferred because of an apparent row/column metadata inconsistency in inspected source, not counted as a supported operation.

## Outstanding gates

- Parent scientific distinctness review before implementation.
- Private CPU dependency resolution and upstream-license notice retention.
- Adapter/schema/artifact authoring, supported sensor-metadata fixture construction, negative cases, and independent CPU acceptance.
- Every numeric value is an **analytic proposed expectation**, not an observed passing result. Optical-flow and scale-space tolerances still need actual CPU acceptance.
- No ore identification, grade inference, silent nodata filling or automatic calibration constants are authorized by these proposals.


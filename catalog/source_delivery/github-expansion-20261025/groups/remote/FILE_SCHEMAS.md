# Remote contribution: scientific file and runtime contracts

Status: **r2 SOURCE AUTHORED / NOT TESTED / NOT DEPLOYED / NOT SUBMITTED**.

Historical r1 CPU reports remain untouched. The parent reported 29 passing numeric
subcases and a matched-filter shape failure in r1; these are not r2 verification.
The excluded HistogramMatch operation is not counted as a new capability.

The standalone generator produces 30 tools, five Skills of six tools, 30 examples,
30 candidate-operation rows, direct dependency pins, source evidence and synthetic
fixtures. It writes only the assigned remote paths. It does not read or modify the
global registry, examples, worker, SDK or deployed baseline. Generation uses only
the host Python standard library when source-artifact generation is authorized;
it is not a scientific test. The target scientific runtime remains Python 3.12.

## Input transport

Every named function in geological_agent.geology.github_expansion_remote takes
args as a dictionary or JSON object string, through the existing operation
decorator, plus an explicit new/empty output_dir. Parameters are enumerated in
each tool schema with additionalProperties:false. There is no user-selectable
module, function or code field. No call installs dependencies or accesses a network.

Every operation requires raster_path and input_unit. Optional quality_mask_path
is an aligned one-band 0/1 GeoTIFF; 1 means valid, 0 and NoData mean excluded.
Auxiliary seed_path, markers_path and reference_path are declared file inputs and
therefore included in the native content-hash provenance. Supplied mean,
covariance, target, wavelength and PSF values are bounded JSON parameters.

## Raster profile

Local single-file GeoTIFF only; no VRT, sidecars, symlinks, remote URLs or implicit
reprojection. A raster must have an explicit CRS and finite nonsingular affine,
2..512 rows/columns, at most 65536 pixels, 1..64 bands and at most 1048576 values.
The collection contract additionally bounds file and argument sizes. Stored
scale/offset must be identity; supply already calibrated numeric values and
declare their unit. Unmasked NaN/infinity is an error, never silently removed.
Valid magnitudes are bounded at 1e12. Binary and labeled images require exact
integer values in their documented ranges. Quantized texture tools require
caller-supplied DN levels and perform no automatic normalization or binning.

Spectral statistics/detectors require at least two bands and more valid pixels
than bands. This sample-count restriction does not apply to SensorBandResample. Declare
one strictly increasing wavelength center in nm per band. Background and noise
covariances use the same band order and squared input units, must be symmetric
positive definite and have condition number <=1e10. No diagonal loading,
shrinkage, pseudo-inverse fallback, ore abundance or grade estimation is added by
this adapter. SPy's upstream kernels are invoked directly after these checks.

Radiance is a declared common-band radiance scale; the caller must document the
actual physical convention in the associated reference/source metadata. The
adapter does not infer sensor response, wavelength-dependent conversion factors,
atmospheric correction, or absolute radiometric calibration.

## Sensor-band resampling and radiometric domains

GeoRemoteSensorBandResample directly invokes spectral.algorithms.resampling.BandResampler
from spectral==0.25. It uses supplied source/target centers and positive FWHMs in
nm. Each full FWHM interval must lie within 100..30000 nm. Centers increase
strictly; vector lengths must match their raster/target band counts. Source FWHM
intervals must not overlap. Every target interval must be fully covered by the
union of source intervals without gaps. Unsupported coverage is rejected before
calling SPy, rather than accepting its partial-support renormalization. No
bandwidth inference, extrapolation, source overlap double counting or spatial
reprojection is permitted. Bounds are checked in the supplied numeric precision.

This conservative profile accepts only calibrated reflectance in [0,1], with at
least two source bands, 1..64 target bands, and at most 1048576 output values.
SPy assumes source values constant across source FWHMs and integrates a Gaussian
target response over FWHM overlap. This is approximate spectral harmonization,
not exact measured sensor RSR integration, super-resolution or mineral evidence.
Target GeoTIFF bands carry wavelength_nm/fwhm_nm/wavelength_unit/radiometric_unit
and response_model tags. resampling-weights.csv records every target/source band
pair, centers, widths and the dimensionless upstream weight. JSON also records
the complete response matrix and units. Spatial grid and effective masks remain
unchanged. NoData in even one source band excludes that pixel from every target
band; quality exclusions are intersected, never imputed.

GeoRemoteTVDenoise rejects categorical binary/label units in both the input
schema and adapter. It accepts nonnegative continuous DN, radiance, Kelvin
brightness temperature, reflectance and normalized_intensity; the latter two
are restricted to [0,1]. This is a declared conservative data profile, not a
claim that every reflectance convention is intrinsically bounded by one.
Results retain the declared continuous unit, including fractional DN; they are
not classifications. Its output schema excludes categorical units as well.

## Missing support

PCA, MNF, RX, matched filtering and ACE operate on valid spectra and put results
back on the original grid. Entropy uses the upstream rank-filter mask; Otsu fits
the valid histogram; region properties exclude invalid cells; sensor-band
resampling uses joint valid spectral/quality support. Watershed uses an upstream
domain mask and requires a seed in every connected valid domain. Canny uses the
upstream mask, which erodes support near gaps and excludes the outer border;
zeros in those valid border cells mean no evaluated detection, not clear evidence
that no geological boundary exists. The original effective exclusion mask remains
recorded in its output artifact.

All other neighborhood kernels require a fully valid rectangular patch and
reject gaps. In particular, noise differences, reconstruction, morphology,
GLCM/LBP, Gabor/tensor filters, SLIC/graph segmentation, random walker, registration,
SSIM and restoration do not fill NoData. Random walker additionally caps the
direct sparse problem at 4096 pixels and 2..8 seeded labels.

## Artifact and unit conventions

Every operation writes measurements.csv. Mapped results write result.tif in
float64 and preview.png. The GeoTIFF preserves the original CRS/affine and
effective input mask. Its original NoData sentinel is retained when finite and
noncolliding; otherwise the adapter uses the explicit finite sentinel
-1.7976931348623157e308 and records output_nodata in JSON. Original per-band
NoData declarations remain in grid.input_nodata. Output descriptions identify
component bands; input spectral wavelengths must not be attached to transformed
component bands. PNGs are pixel-coordinate previews, not map deliverables.

Noise covariance, GLCM and registration return tables rather than a fictitious
spatial result. Region measurement also writes regions.csv. Random walker writes
class-labels.tif in addition to per-class probability bands in result.tif.
Structure tensor bands are Arr, Arc, Acc, lambda_max, lambda_min; Gabor bands are
real and imaginary responses; rolling-ball bands are background and residual.
Every numeric measurement has an explicit unit entry; raster band statistics
also carry units. Spatial algorithm scales are pixels. Region area is pixel
count, not projected area. Registration's map offsets use the affine basis and
CRS coordinate units. It estimates a translation without warping the image.

## Source and release evidence

Sources.json and the per-tool upstream.api_source_url point to reviewed immutable
upstream source. Spectral Python 0.25 annotated tag resolves to
bd91dc47377028683ef5c97bc7c1cc2dff14012c. scikit-image v0.26.0 annotated tag resolves
to ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8. License evidence is preserved under
licenses/. Spectral is MIT; scikit-image's distribution contains BSD-3-Clause,
BSD-2-Clause and MIT notices, with thresholding specifically BSD-2-Clause.
Adapter licensing remains pending rather than assuming upstream licenses grant
a license for new project code. Installed distribution/source identity has not
been hashed or executed here.

The scikit-image 0.26 source declares Python >=3.11, numpy>=1.24 and scipy>=1.11.4;
the user-confirmed Python3.12/numpy2.1.3/scipy1.15.3 baseline meets these declared
constraints. Direct pins preserve installed versions. No new package or NumPy
downgrade is proposed. A full transitive environment lock and actual binary
compatibility acceptance belong to the parent; no compatibility test was run.

## Scientific limits and independent oracle source

Every candidate has a scientific comparison with the nearest existing baseline
tool; none is an alias, vegetation-index rename, arbitrary callback or generic
vector-math wrapper. Actual numerical operations use imported upstream kernels.
Formatting, grid handling, finite checks, analytic test expectations and artifact
summaries are adapter code. Histogram matching was excluded as a semantic
duplicate of original SkdownscaleQuantileBiasCorrection; its source, example and
oracle are retained in excluded-candidates.json, not registered or counted.
Image texture, segmentation and detector responses do not identify
minerals, geological contacts, grade, reserves or economic viability.

All fixtures under assets/github-expansion-remote are explicitly SYNTHETIC and
use an arbitrary UTM grid. Oracles.json records a positive numeric expectation
for each operation derived from arithmetic, covariance identities, neighborhood
counts, fixed points or a Dirichlet boundary solution. The unittest source calls
the real decorated entrypoints with catalog lookups patched only in memory,
checks specific invalid cases for all 30 tools, artifact/input/implementation
hashes, units, output schemas, grid preservation and additional mask/error cases.
It does not derive expected answers by calling the library under test. The new
band-resampling oracle uses Gaussian symmetry: equal response weights 0.5/0.5
on reflectances 0.2/0.6 give 0.4. The matched-filter oracle remains 1.0 for the
63 valid pixels, with only exact (63,1) to (63,) adaptation permitted. Test source
also covers missing/mismatched CRS, shifted affine, declared-unit violations,
actual nonfinite raster/parameter values, malformed matched-filter outputs,
unsupported bandpass coverage and joint NoData/quality-mask preservation.

## Acceptance blockers and handoff

For r2, no scientific call, test, installation, remote operation, GPU task,
commit, push, deployment or browser operation was performed. Only approved local
source/asset authoring and the standard-library generator are authorized. The r2
numeric and negative acceptance sources remain unexecuted here. The parent must integrate the fixed module whitelist
and worker dispatch, preserve the original 229-tool baseline, review additive
metadata, run authorized CPU acceptance and record real evidence before marking
any operation verified. Receiving lab approval, adapter license and workflow
validation remain pending.

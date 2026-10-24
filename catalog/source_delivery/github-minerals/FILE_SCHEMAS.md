# GitHub minerals: standalone scientific interfaces

Nine operations use Spectral Python 0.25, pyrolite 0.3.7 and mplstereonet
0.6.3. Source commits, distribution URLs and SHA-256 digests are in
`upstream-lock.json`; original licenses are in `licenses/`. Scientific dependency
versions are pinned in `requirements-github-minerals.txt`. Install these before
runtime invocation. Each operation calls the original package API; no package
installation, external service, arbitrary expression or model call is exposed.

pyrolite 0.3.8.post1 failed the isolated import probe because it annotates a
nonexistent matplotlib.colors.Norm type. Version 0.3.7 is selected for compatibility
with the reviewed Matplotlib 3.10.7 profile; the original failed probe is retained.

All file inputs at the agent boundary are task-relative paths. Standalone Python
calls accept `args=dict` or `args=JSON-object-string`; file-producing operations
also require a new or empty `output_dir`. Native ToolExecutor authorizes paths,
snapshots inputs and returns ArtifactRef outputs. Errors use ScientificToolError
with code/message/retryable, mapped to the existing ToolFailure protocol.

## Spectral JSON

`GeoSpectralContinuumRemoval` requires exactly:

```json
{"wavelength_nm":[1000,1500,2000],"sample_ids":["SYNTHETIC"],"spectra":[[1,0.5,1]]}
```

This is explicitly synthetic acceptance data. Wavelengths must strictly increase
over 100..30,000 nm, with 3..2,048 bands and up to 128 spectra. Values are calibrated
dimensionless reflectance in [0,1.5]. NoData must be removed or masked before a
spectral-table call; NaN/Infinity and duplicate IDs are rejected. The convex upper
hull must be positive. The deepest sampled band is not a fitted absorption center.

`GeoSpectralAngleMatch` and `GeoSpectralLinearUnmix` additionally require
`reference_wavelength_nm`, `reference_spectra`, `reference_labels` and
`reference_source`. Reference wavelengths must match to 1e-6 nm; there is no
implicit interpolation or sensor-response correction. At most 32 reference
spectra are accepted. Zero spectra are invalid for angle matching. Unmixing
requires independent endmembers and a condition number <=1e8. Coefficients are
unconstrained, may be negative and need not sum to one; they are not mineral mass
fractions, ore grade or reserves. Reference sources are caller declarations.

Outputs include full numeric JSON, CSV, PNG and SVG. Heatmaps show at most 32
samples, curve previews show at most 8, and full numeric results remain in CSV/JSON.

## GeoTIFF spectral mapping

`GeoSpectralAngleMap` takes `raster_path`, `library_path`, `raster_wavelength_nm`,
`reflectance_scale`, `reflectance_offset`, optional `quality_mask_path`, and
`max_angle_degrees` (default 10). The library JSON has the four `reference_*`
fields described above. Every band must have a declared matching wavelength.
Calibration is `raw * scale + offset`. Only local single-file GeoTIFF is accepted.
CRS must be present. The bounded profile allows 262,144 pixels, 8,388,608 total
band values and the shared 64 MiB per-input file limit. Split larger rasters
explicitly; results never silently crop or downsample.

Quality-mask values are 1=valid, 0=excluded; mask NoData is excluded. CRS, shape and
affine transform must exactly match. Any band NoData excludes that pixel. A valid
zero spectrum or out-of-range reflectance is rejected. Class IDs are one-based in
reference order; 0 denotes excluded or unmatched. The angle GeoTIFF separates these
cases: excluded pixels have NoData=-9999, valid unmatched pixels retain their best
angle. Counts separately report valid, excluded and unmatched pixels. Class and
angle GeoTIFFs preserve CRS and transform. CSV, PNG and SVG are also produced.

## Geochemical JSON

All three operations require `sample_ids`, `components`, rectangular `values`, and
`unit`. Sample IDs and component names must be unique, with at most 128 samples
and 2..32 components. No implicit missing-value imputation, detection-limit
replacement or mixed-unit conversion is performed.

- `GeoGeochemCLR`: unit `ppm` or `wt_percent`, all values strictly positive.
  Calls pyrolite CLR using natural logarithms; closed-data log ratios are
  dimensionless. A statistical anomaly is not an economic mineral deposit.
- `GeoGeochemOxideMoles`: unit `wt_percent`. Supported columns are SiO2, TiO2,
  Al2O3, FeO, Fe2O3, MnO, MgO, CaO, Na2O, K2O, P2O5, Cr2O3, NiO. Each value is
  0..100; sample totals must be >0 and <=105. pyrolite returns mol/100g and
  normalized mol percent among supplied components. FeO/Fe2O3 are never inferred.
- `GeoGeochemREEPattern`: unit `ppm`, strictly positive values. Ordered columns
  follow La, Ce, Pr, Nd, Sm, Eu, Gd, Tb, Dy, Ho, Er, Tm, Yb, Lu. Also requires
  positive `reference_values` aligned to those columns and `reference_source`.
  pyrolite normalizes to those explicit values. Eu anomaly is
  Eu_N/sqrt(Sm_N*Gd_N), or null if one component is absent. No chondrite reference
  is invented. Full tables and preview curves are exported.

## Structural geology

`GeoStereonetAnalysis` JSON requires exactly `strike_degrees`, `dip_degrees`,
`measurement_ids`, `convention="right_hand_rule"`. It accepts 3..500 paired
strikes [0,360) and dips [0,90]. mplstereonet projects lower-hemisphere equal-area
planes/poles and calculates bidirectional covariance eigenvalues. A fitted
dominant plane is returned only if its leading eigenvalue is distinguishable;
otherwise `fit_plane=null`. This is orientation analysis, not a slope-stability
or failure-probability calculation. CSV, PNG and SVG are exported.

`GeoStructuralPlaneIntersection` takes four JSON numbers: `strike1_degrees`,
`dip1_degrees`, `strike2_degrees`, `dip2_degrees`, using the same convention.
Parallel/coincident planes are rejected; the bearing of a vertical intersection
is undefined and returned as null. Outputs are JSON only.

## Acceptance and delivery status

Original 220 tool definitions, 47 Skill definitions and examples are retained;
their canonical hashes are in `baseline-preservation.json`. Exact new tests and
executed native operations are recorded separately. Registration is not a claim
of completed model workflows, live deployment, formal packaging, or receiving
AI Lab approval. All fixtures in assets/github-minerals are synthetic and are not
ingested into the knowledge base.

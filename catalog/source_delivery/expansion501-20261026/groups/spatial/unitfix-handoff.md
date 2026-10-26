# Approved mixed-column unit repair and source freeze

Status: source_revised_unverified; formal_eligible=false. not_deployed;
not_submitted; model workflow not_run. Receiving AI Lab certification is not
established. This document does not claim native numerical acceptance.

## Narrow approved change

`native.py::_pdal_result` now uses `_pdal_column_units(fields)` instead of a
single `args["feature_unit"]` value. Each X/Y/Z/HeightAboveGround column is m;
Classification and ClusterID are dimensionless_label; PointId is
input_zero_based; covariance ratios are dimensionless. The generator emits
closed per-column unit schemas for the four PDAL kernels. Legacy inputs,
numerical methods, tolerances, pins and numeric oracles are unchanged.

`acceptance/flow_units_r2.py` snapshots the non-unit contracts before the
stdlib generator, then runs `acceptance/test_units_r2.py`. The test has nine
unit/source-contract checks, no external dependencies, no scientific engine
execution and no dependency-skip-as-pass mechanism. Fresh timestamped local
evidence is retained and explicitly added to delivery-files.json. Historical
r1 logs/tests remain unchanged. Consult the actual report, not this document,
for execution results.

## Counts at this freeze

- Existing catalog contribution remains unchanged: 27 source-authored tools.
- Pending resolution kernels: 11, all still blocked/unregistered.
- Newly implemented from the remaining eight in this pass: 0.
- Incomplete source kernels remaining: 8.
- Newly registered, accepted, certified or deployed by this repair: 0.

## Remaining eight: exact unfinished work

1. GeoSpatialRigidPointCloudRegistration: fixed/moving ICP API and composed
   matrix metadata confirmed; identity restoration, convergence checks and
   transform replay validation are not authored. Native build receipt and
   independent registration oracle execution also remain pending.
2. GeoSpatialNavigationBasedLidarGeoreference: source confirms trajectory
   X/Y radians, Azimuth rather than a guessed Yaw field, and supported time
   interval (first,last]. CSV transport, explicit degree/radian conversion,
   NED calibration and EPSG:4979 output schema are not authored. Input-time
   rejection must precede execution; batch and streaming handling differ.
3. GeoSpatialSurveyPoissonSurface: explicit supplied normals and PLY faces
   are confirmed. Normal-domain checks, bounded mesh validation and typed
   area/volume accounting are not authored. Vendored Poisson license/build
   closure and reconstruction-specific independent acceptance remain open.
4. GeoSpatialTerrainSolarIrradiance: r.sun instantaneous mode uses W/m2,
   unlike daily irradiation. Explicit solar time, slope/aspect conventions,
   native float precision, four aligned output rasters and component
   accounting are not authored. No new solar kernel is claimed.
5. GeoSpatialLidarSensorTrajectoryRecovery: the trajectory plugin requires
   Ceres; its pinned PulseCollection::Solve discards the solver summary.
   A reviewed native plugin/Ceres closure and a trustworthy convergence
   certificate or independently approved acceptance criterion are needed.
   Output-time extrapolation and a nondegenerate multi-return oracle remain
   unresolved. A zero native exit is not an optimization certificate.
6. GeoSpatialSIMWESedimentTransport: the official manual labels concentration
   particle/m3 but flux kg/(m*s). No undocumented mass conversion is allowed.
   A reviewed concentration definition and nonzero-flux reference with
   terminal time/boundary mass accounting are still needed; walker/state
   transport is not authored. This is not merely a remote availability gap.
7. GeoSpatialAquiferSoluteTransport: the pinned 2D callback has -q/nf on the
   diagonal and +q/nf*cin on the right. Source/sink sign conventions and a
   uniform-concentration nonzero-source oracle need resolution before a
   conventional conservative mass claim. Source computes velocities from
   K/nf, so they must not be mislabeled Darcy flux. Full adapter remains
   incomplete; no upstream equation has been changed or restricted silently.
8. GeoSpatialRainfallErosivityFactor: input mm/year and output
   MJ*mm/(ha*hour*year) are confirmed. The selected empirical relation's
   authoritative formula, regional applicability and independent numeric
   oracle have not been established. No guessed equation is implemented.

The first four are implementation gaps at this requested consolidation
boundary, not purported external blockers. No denied remote action was retried.

## Primary evidence retained for continuation

- PDAL 2.9.1 source commit: fceafbd400639f8376e3d4cd21230175d5b314d9;
  [ICP](https://github.com/PDAL/PDAL/blob/fceafbd400639f8376e3d4cd21230175d5b314d9/doc/stages/filters.icp.md),
  [georeference](https://github.com/PDAL/PDAL/blob/fceafbd400639f8376e3d4cd21230175d5b314d9/filters/GeoreferenceFilter.cpp),
  [trajectory reader](https://github.com/PDAL/PDAL/blob/fceafbd400639f8376e3d4cd21230175d5b314d9/filters/private/georeference/Trajectory.cpp),
  [Poisson](https://github.com/PDAL/PDAL/blob/fceafbd400639f8376e3d4cd21230175d5b314d9/doc/stages/filters.poisson.md),
  [Ceres solve](https://github.com/PDAL/PDAL/blob/fceafbd400639f8376e3d4cd21230175d5b314d9/plugins/trajectory/filters/PulseCollection.cpp#L438).
- GRASS 8.5.0 source commit: 8d6ceba290a2f0059a7301b9d4944455f313da72;
  [solar manual](https://grass.osgeo.org/grass85/manuals/r.sun.html),
  [SIMWE manual](https://grass.osgeo.org/grass85/manuals/r.sim.sediment.html),
  [solute coefficients](https://github.com/OSGeo/grass/blob/8d6ceba290a2f0059a7301b9d4944455f313da72/lib/gpde/n_solute_transport.c#L303),
  [erosivity entry](https://github.com/OSGeo/grass/blob/8d6ceba290a2f0059a7301b9d4944455f313da72/raster/r.usler/main.c).

## Parent fixed bridge needs, not a competing IPC implementation

Use parent-owned profile names and fixed ID-to-private-kernel bindings from
pending-contracts.json. All eleven inputs are bounded JSON arrays, not caller
file paths. Snapshot canonical input bytes plus SHA256 (maximum 4,000,000
bytes); compare exact Python requirements in the actual private interpreter.
Do not bypass the shared dependency guard or claim missing packages installed.

- Landlab profile: Python3.12, numpy==2.1.3, scipy==1.15.3,
  pyproj==3.7.2, jsonschema==4.25.1, landlab==2.11.0, pandas==2.3.0,
  matplotlib==3.10.7, xarray==2026.9.0. Three fixed stateful kernels;
  JSON-only results, no native artifacts.
- PDAL profile: numpy==2.1.3, scipy==1.15.3, pyproj==3.7.2,
  jsonschema==4.25.1 plus reviewed PDAL2.9.1 native closure. Four fixed
  kernels; exactly points.csv (text/csv) and frame.json (application/json).
- GRASS profile: same four Python pins plus reviewed GRASS8.5.0 closure.
  Two fixed kernels; exactly result.asc (text/x-grass-ascii-grid) and
  frame.json (application/json). Preserve CRS, affine, shape and native nulls.
- MILP profile: same four base pins plus spopt==0.8.0, PuLP==3.3.0,
  libpysal==4.15.0, geopandas==1.1.2, shapely==2.1.2, pandas==2.3.0;
  CBC2.10.12 reviewed native closure. Two fixed kernels; exactly
  cbc.stdout.txt, cbc.stderr.txt, cbc.solution.txt (text/plain).

Artifact descriptor shape is a closed object with required name (fixed
basename), bytes (nonnegative integer), sha256 (64 lowercase hex characters),
media_type (fixed media type above). Results use artifact_manifest; final
artifacts/provenance belong to shared contracts after bounded copied transport.
Worker response maximum is 4,000,000 JSON bytes; each stream is bounded to
262144 bytes, each file at most 64 MiB and aggregate workspace at most 128 MiB.
Copy only declared regular files, reject links/path escape, verify size/hash
before and after copying, retain real process status and identity attestation.

Existing native.py is an internal fixed CPU launcher, not main-to-worker IPC.
No reviewed native-profile.json, binary hash, plugin receipt or complete native
license closure is shipped. Parent must bind trusted operator configuration,
never expose executable/profile/pipeline selection to callers. Only the four
approved helper paths are delivered; no fifth helper or competing bridge was
added. Shared stage/guard/worker files were not changed by this repair.

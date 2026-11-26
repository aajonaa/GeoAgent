# Geology contribution proposal

Status: R2 SOURCE REPAIR; NOT TESTED; NOT DEPLOYED; NOT SUBMITTED.

Target: 30 operations; r2 active contribution: 28, with a deficit of two. Five coherent workflow Skills contain 5/6/5/6/6 operations. Bingham and CIPW below are blocked exclusions, not active candidate IDs. Existing 229-tool catalog remains untouched. This file is the coordination handoff because the app disallows sending a message to the native parent chat.

Direct package pins: apsg==2.0.6, pyrolite==0.3.7, scikit-gstat==1.0.24, gstools==1.7.0, lasio==0.32, welly==0.5.2, striplog==0.9.2, wellpathpy==0.5.2, scikit-learn==1.7.2. GSTools binary dependency: gstools-cython==1.2.0. APSG SQL dependency: SQLAlchemy==1.4.54. The Bingham immutable-source procurement profile is separate; all 11 active APSG operations retain 2.0.6.

Preserve Python 3.12, numpy==2.1.3, scipy==1.15.3, pandas==2.3.0, matplotlib==3.10.7, numba==0.68.0 and existing other shared pins. Missing packages require private CPU acceptance. No runtime installation or online calls.

- `GeoAPSGPairFabricTensor`: Lisle paired foliation/lineation tensor.
- `GeoAPSGFoldAxis`: girdle fold axis and uniqueness diagnostic.
- `GeoAPSGFisherDirectionalConfidence`: Fisher mean-direction confidence for directed structural vectors.
- BLOCKED / NOT COUNTED: `GeoAPSGBinghamAxialConfidence`; immutable upstream fix requires a dedicated worker binding and independent acceptance.
- `GeoAPSGMarkerStrainEstimate`: Rf/phi marker strain with Robin tensor comparison.
- `GeoAPSGFaultKinematicAxes`: fault-slip P/T axes, not stress inversion.
- `GeoAPSGFiniteStrainEllipsoid`: finite stretches and strain-shape invariants.
- `GeoAPSGDeformationPolarSplit`: rigid rotation versus finite stretch.
- `GeoAPSGVelocityGradientEvolution`: constant-flow finite deformation evolution.
- `GeoAPSGKinematicVorticity`: coaxial/noncoaxial deformation diagnostic.
- `GeoAPSGFractureTraction`: resolved normal and shear fracture traction.
- `GeoAPSGFaultReactivation`: effective-stress slip/dilation tendencies.
- `GeoPyroliteALR`: reference-component additive log-ratio coordinates.
- `GeoPyroliteILR`: orthonormal compositional balances.
- `GeoPyroliteCompositionalCenter`: Aitchison compositional sample center.
- `GeoPyroliteSphericalComposition`: simplex-to-sphere angular coordinates.
- `GeoPyroliteMineralEndmemberUnmix`: bounded chemical endmember mixture fit.
- BLOCKED / NOT COUNTED: `GeoPyroliteCIPWNorm`; float adapter repair does not resolve the upstream fluorapatite scientific defect.
- `GeoSKGstatRobustVariogram`: compare classical and robust empirical estimators.
- `GeoSKGstatSpaceTimeVariogram`: joint spatial/temporal semivariance.
- `GeoGSToolsVariogramFit`: fit measured exponential variogram parameters.
- `GeoGSToolsBlockSupportCovariance`: discrete block-support variance/covariance.
- `GeoSKGstatKrigingLOO`: held-out residual validation for supplied covariance model.
- `GeoGeochemBackgroundDistance`: ILR-background Mahalanobis anomaly distance.
- `GeoLasioLogAudit`: LAS curves, null masks, units and depth integrity.
- `GeoWellyMinimumCurvature`: survey trajectory and dogleg severity.
- `GeoWellyLogResample`: bounded depth-basis resampling.
- `GeoWellyLogDespike`: explicit median-window log spike attenuation.
- `GeoWellyLogFaciesBlock`: threshold-based log facies with stated cutoffs.
- `GeoStriplogIntervalIntersection`: intersect measured lithology intervals.

APSG release commit: f9f45a52d60521ba37f326a85645df3dee74272e, whose src/apsg/__init__.py declares 2.0.6. Pyrolite license: CSIRO BSD/MIT variation; welly and striplog: Apache-2.0; GSTools: LGPL-3.0; APSG, lasio, scikit-gstat: MIT. Full source/license records follow in sources.json.

R1 source/evidence is preserved. Exact procurement and fixed CPU binding requirements: `private-workers/bingham/requirements-source.txt`, `private-workers/bingham/worker-profile.json`, and `private-workers/bingham/README.md`. No installation, scientific execution, SDK/registry change or deployment was performed.

# Geophysics research-only roadmap

Status: **research_only_not_integrated_not_counted**

**30 research candidates: first20 prioritized, then10 additional distinct tasks.**
The requested45 is a maximum, not a quota. The remaining15 slots are unfilled.
**Zero operations implemented, tested, integrated, registered or newly accepted.**

## Files

- research-inventory.json: all30 candidates, exact upstream entrypoints, pins and
  source commits, authoritative URLs, licenses, units, constraints, proposed
  independent numeric oracles, semantic comparisons, dependencies and risks.
- README.md: this concise handoff.

## Current release is not this research

Parent reports346 professional tools/70Skills deployed,751 regression cases
passed, and pushes7466cfa +241c5d8. These facts were not reverified here.
Nothing in accepted117, existing adapters/Skills, shared registries, SDKs,
deployment scripts or backlog was modified.

The read-only dedup scope was catalog/registry.json (229 tools) plus all four
github-expansion-20261025 groups: geology28, geophysics29, remote30, spatial30.
The inventory retains the complete346-ID snapshot and a specific nearest-tool
scientific comparison for every candidate. Cross-group dedup of other future500
research inventories remains the parent's responsibility.

## Top5

1. **GeoSeismicInstrumentDeconvolution**: physical ground motion from counts and
   local epoch-matched instrument response; obspy==1.4.2.
   [Pinned API source](https://github.com/obspy/obspy/blob/a629e8c021052904b6b8d62699d03f2a3721ae63/obspy/core/trace.py)
2. **GeoEMLayeredBipoleResponse**: controlled-source EM in layered VTI media;
   empymod==2.6.0. Highest scientific breadth, but layered-oracle/transform
   acceptance needs more work.
   [Pinned API source](https://github.com/emsig/empymod/blob/7a7c221da5940a8e0d8f60478b929e2690806521/empymod/model.py)
3. **GeoGravityTesseroid**: finite spherical-volume gravity/potential;
   harmonica==0.7.0.
   [Pinned API source](https://github.com/fatiando/harmonica/blob/b9f9c00b0999f470dcae971b19add28b055633c9/harmonica/_forward/tesseroid.py)
4. **GeoPotentialEulerSourceLocation**: ideal-source location/base level from
   potential field and derivatives; harmonica==0.7.0.
   [Pinned API source](https://github.com/fatiando/harmonica/blob/b9f9c00b0999f470dcae971b19add28b055633c9/harmonica/_euler_deconvolution.py)
5. **GeoSurfaceWaveDispersion**: bundled Rayleigh/Love phase/group curves;
   disba==0.7.0. Includes independent homogeneous Rayleigh and genuinely
   layered Love oracle constructions.
   [Pinned API source](https://github.com/keurfonluu/disba/blob/18b7d023288f2bf22d2f128e8ca6a10d15b5913a/disba/_dispersion.py)

## All candidates in priority order

1. GeoSeismicInstrumentDeconvolution: Recover physical ground motion from instrument counts using explicit, epoch-matched response metadata.
2. GeoEMLayeredBipoleResponse: Compute frequency/time-domain controlled-source electromagnetic responses in horizontally layered VTI media, including finite source integration.
3. GeoGravityTesseroid: Forward-model potential and radial gravity of finite spherical tesseroids for regional/global density-contrast bodies.
4. GeoPotentialEulerSourceLocation: Estimate one ideal potential-field source location and regional base level from field observations and all three measured derivatives.
5. GeoSurfaceWaveDispersion: Compute Rayleigh/Love phase and group dispersion curves for a layered elastic halfspace as one modal-dispersion operation.
6. GeoPotentialEquivalentSources: Fit damped equivalent sources to irregular-altitude potential-field observations and predict a supplied survey-level grid.
7. GeoPotentialUpwardContinuation: Continue a complete planar potential-field grid to a higher observation plane using the harmonic spectral transfer.
8. GeoMagneticReductionToPole: Rephase a planar total-field magnetic anomaly to pole-equivalent field and magnetization directions.
9. GeoDCFourElectrodeResponse: Compute four-electrode voltage responses in a homogeneous resistive halfspace with explicit source/sink and potential electrodes.
10. GeoGravityNormalEllipsoid: Evaluate reference-ellipsoid normal gravity at measured geodetic heights for gravity-disturbance reduction.
11. GeoSeismicArrayBeamforming: Estimate seismic wavefront backazimuth, horizontal slowness and coherence from a synchronized station array.
12. GeoSeismicSTALTADetection: Detect transient seismic event windows using a fixed classic STA/LTA energy detector and explicit on/off thresholds.
13. GeoSeismicTemplateDetection: Detect repeating seismic events with explicit multichannel waveform templates, retaining match times and similarity.
14. GeoSeismicPolarization: Estimate three-component seismic particle-motion azimuth, incidence, rectilinearity and planarity.
15. GeoSeismicTauPRays: Predict seismic phase travel times, ray parameters and ray paths in a supplied local1D spherical velocity model.
16. GeoSeismicNMO: Apply hyperbolic normal-moveout correction to a supplied CMP gather using declared NMO velocities.
17. GeoSeismicComplexAttributes: Extract a bundled seismic trace envelope, phase and instantaneous-frequency attribute set with explicit valid support.
18. GeoSeismicWindowCoherence: Measure Marfurt seismic trace coherence within an explicitly supplied3D survey-analysis window.
19. GeoPotentialEdgeAttributes: Compute bundled total-gradient amplitude and tilt of a potential-field anomaly grid for edge interpretation.
20. GeoSeismicArrayStrainRotation: Infer time-varying small ground strains and rigid rotations from synchronized3C surface-array displacements and stated noise.
21. GeoGravityBouguerSlab: Calculate land/bathymetric infinite-slab gravity correction with explicit crust and water density contrast.
22. GeoCrustAiryMoho: Predict crust-mantle boundary depth from basement relief and explicit surface-load layers using Airy mass balance.
23. GeoEMConductiveSphere: Compute internal/external DC electric fields and current-density contrasts of a conducting sphere in a uniform applied field.
24. GeoMagneticWirePath: Forward-model the magnetic induction of an explicit closed piecewise-linear current loop for survey source/calibration geometry.
25. GeoSeismicARPhasePick: Estimate P and S onset times from3C records using the fixed AR-AIC/STA-LTA phase picker.
26. GeoSeismicProbabilisticNoise: Compile calibrated seismic station noise PSD distributions over bounded local waveform segments.
27. GeoSeismicWaveformTFMisfit: Separate time-frequency envelope and phase discrepancies between aligned synthetic and observed seismic waveforms.
28. GeoSeismicRadiationPattern: Compute bundled normalized P and S far-field radiation vectors for a supplied general symmetric seismic moment tensor.
29. GeoSurfaceWaveEigenfunctions: Compute depth-indexed normalized modal displacement shapes for layered Rayleigh/Love surface waves.
30. GeoSurfaceWaveSensitivity: Quantify layer-resolved surface-wave phase-speed sensitivity to thickness, Vp, Vs and density for inversion design.

## Dependency plan, not an install request

Reuse parent-reported obspy==1.4.2 and bruges==0.5.4. Keep SQLAlchemy==1.4.54.
New direct research pins are harmonica==0.7.0, empymod==2.6.0,
geoana==0.9.0, boule==0.6.0 and disba==0.7.0. Exact release commits and
dependency/license evidence are in the JSON.

Preserve numpy2.1.3/scipy1.15.3/pandas2.3.0/matplotlib3.10.7,
numba0.68.0/xarray2026.9.0/scikit-learn1.7.2 and
typing-extensions4.16.0/pydantic2.13.5/langgraph1.2.12.
Additional transitive pins remain unresolved, explicitly not invented:
Verde/xrft, libdlf/scooby, attrs and importlib_metadata where required.

Licenses: Harmonica/Boule/disba BSD-3-Clause; Geoana MIT; empymod/Bruges
Apache-2.0; ObsPy LGPL-3.0. Bruges NMO has its own BSD-3-Clause attribution.
No upstream or adapter license is silently replaced.

## Independent evidence and gates

Oracles are proposed analytic identities, independently constructed signals or
physical boundary-value examples. No scientific implementation was executed
to generate expected values. Examples include a complete spherical shell,
nonpolar RTP harmonic projection, a four-electrode Wenner response, nontrivial
Euler source recovery, homogeneous Rayleigh secular roots and a layered Love
traction-continuity construction.

Research priority is not acceptance readiness. Layered EM needs an independent
heterogeneous numeric case; AR picking needs demonstrated timing/false-pick
bounds; PPSD needs independently derived finite-window/bin statistics; modal
sensitivities need layered derivative and perturbation-convergence checks.
Every candidate still needs authorized bounded schemas, adapters, provenance,
negative cases and CPU acceptance. No wrapper code was authored here.

## Why not45

Already accepted point/prism gravity, dipole/prism magnetics, elastic/poroelastic
and AVO operations were not repeated. Wavelet families, axes, transform modes,
generic mathematical helpers and synonymous APIs were not counted.
Previously blocked StressAnisotropy and Berryman_DEM remain excluded.

New source concerns are recorded, not patched: Bruges time-weighted RMS and
time/depth conversion, MoPaD mixed-tensor eigenvector ordering, and DipSteer's
multi-neighbor windows/correlation output. The high-level Bruges discontinuity
wrapper is excluded; the actual direct Marfurt analysis-window kernel is a
candidate. Disba's high-level eigenfunction depth labeling is excluded; the
public swegn96 kernel is proposed with explicit physical interface mapping
and relative-displacement normalization. No modified scientific kernels or
easy equal-parameter restrictions are proposed.

## Work performed

Read-only official GitHub/docs research and one-pass local catalog comparison.
Only the two new files in this research group are delivered. No tests,
installations, remote commands, GPU, git operations or deployment were run.

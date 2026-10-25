# Geology research roadmap toward 500+

Status: **research_only_not_integrated_not_counted**.

22 source-supported research entries: 20 prioritized tasks and 2 conditional follow-ups. Zero wrappers, tests, integrations or newly accepted tools. The upper bound of 45 was not filled with variants. This inventory does not change the reported 346 professional tools / 70 Skills or claim that 500 has been reached.

Parent reports source push `7466cfa`, 751/751 acceptance and deployment in progress. Those release facts were not independently checked here. No accepted117 adapters, Skills, registries, deployment scripts or backlog files were changed.

## Files

- `candidate-inventory.json`: exact upstream callables, primary evidence, scope, units, bounded input plans, independent synthetic numeric oracles, nearest existing tasks, risks and exclusions.
- `sources.json`: exact release/commit pins, license evidence, expected dependencies and explicit compatibility gaps.

The semantic screen read the baseline catalog (229) and all four earlier group catalogs (28 geology + 29 geophysics + 30 remote + 30 spatial = 117). It compared tool IDs and descriptions, not only names. Full parent implementation/dedup review is still pending.

## Top five

1. `Geo500CrystalSpaceGroupAudit`: atomic space-group/Wyckoff symmetry. [Pinned spglib API](https://github.com/spglib/spglib/blob/3ebd8ac3318793932baeee90b44f453a7c35b5b4/python/spglib/spg.py).
2. `Geo500PowderXRDPattern`: crystal-to-powder diffraction prediction. [Pinned XRD API](https://github.com/materialsproject/pymatgen/blob/e3fdb6d4bb2a3bc1622f4c133e088d660f0c3c26/src/pymatgen/analysis/diffraction/xrd.py).
3. `Geo500MineralOxygenBasisFormula`: measured oxides to explicit oxygen-basis mineral formula. [Pinned pyrolite API](https://github.com/morganjwilliams/pyrolite/blob/ab651b448ecd2ce1bc22d752b80a977a1f4dd1ca/pyrolite/mineral/transform.py).
4. `Geo500MineralReactionBalance`: mineral reaction stoichiometry. [Pinned reaction API](https://github.com/materialsproject/pymatgen-core/blob/cddebfb21ed5acaee3987948b6704a2790d4e056/src/pymatgen/analysis/reaction_calculator.py).
5. `Geo500MineralPhaseHull`: energetic phase decomposition. [Pinned hull API](https://github.com/materialsproject/pymatgen-core/blob/cddebfb21ed5acaee3987948b6704a2790d4e056/src/pymatgen/analysis/phase_diagram.py).

## Remaining priority tasks

- `Geo500CrystalCoordination`: Determine periodic atomic coordination environments and neighbor identities in a mineral structural model.
- `Geo500BondValenceOxidation`: Infer charge-balanced oxidation-state assignments using bond-valence evidence from a supplied mineral structure.
- `Geo500CrystalStructureEquivalence`: Match periodic mineral structures across site permutations, origin shifts and alternative cells.
- `Geo500WulffCrystalHabit`: Construct an equilibrium crystal habit from supplied Miller-plane surface energies.
- `Geo500PeriodicIonicLatticeEnergy`: Evaluate neutral 3D-periodic ionic electrostatic energy by Ewald summation.
- `Geo500CoherentMineralInterfaceMatch`: Search bounded coincidence superlattices for two declared mineral surface nets.
- `Geo500MineralSurfaceTerminations`: Enumerate symmetry-distinct crystallographic slab terminations for a supplied mineral Miller plane.
- `Geo500IrreducibleReciprocalMesh`: Reduce a crystal reciprocal-space integration grid to symmetry-inequivalent points and multiplicity weights.
- `Geo500REEOrthogonalShape`: Fit orthogonal rare-earth pattern shape coefficients to explicit normalized log-REE data.
- `Geo500VolcanicTASClass`: Classify declared anhydrous volcanic whole-rock chemistry in the fixed Middlemost TAS fields.
- `Geo500MineralNeutronContrast`: Calculate mineral neutron scattering-length density, macroscopic cross sections and attenuation from explicit composition and density.
- `Geo500PoreChordDistribution`: Measure boundary-aware pore chord-length distributions from segmented rock microstructure.
- `Geo500PoreBodyRadiusDistribution`: Estimate voxel-center local pore-body radii by maximal inscribed spheres and summarize pore-volume radius distribution.
- `Geo500QuasistaticCapillaryDrainage`: Simulate access-limited capillary invasion and pressure-saturation response in a segmented pore volume.
- `Geo500MineralEhPHStability`: Evaluate mineral/ion thermodynamic stability and decomposition energy over explicit Eh-pH conditions.

## Conditional follow-ups, not main-runtime-ready

- `Geo500SpatialCellDeclustering`: exact source commit 45b2032a1e3f05de6cd0cb7f32ed43203399dbfa. The source declares 0.0.46 while PyPI0.0.79 is published; the inventory does NOT equate them. Underdeclared imports and reversed objective documentation require review.
- `Geo500PoreDiffusionTortuosity`: porespy==3.2.0 with openpnm==3.6.1. OpenPNM requires scipy>=1.16.2 and pandas>=2.3.2, incompatible with the fixed accepted scipy1.15.3/pandas2.3.0 environment. A separate fixed CPU environment is a prerequisite, not an approved shared upgrade.

## Pins and effort

Retain pyrolite==0.3.7 and periodictable==2.1.0. New primary release pins are spglib==2.8.0, pymatgen-core==2026.10.16, pymatgen==2026.10.24 and porespy==3.2.0. Exact companion requirements and commits are in sources.json. The recent pymatgen package split requires the actual core-module names listed in the inventory. PoreSpy's mandatory PyVista/VTK increases package size even though these calls are CPU-only and need no rendering.

No complete transitive wheel lock or artifact hashes are claimed. All numeric oracles are proposals, not run results. Most priority tasks have no declared conflict with the preserved numerical pins; that is metadata evidence, not import/ABI/scientific acceptance.

## Conservative exclusions

Bingham and CIPW remain excluded. The inspected scikit-gstat cross-variogram loses sign and squares the product of absolute increments; a positive-only fixture would hide the issue. GSTools CondSRF's pointwise variance scaling is not a general exact joint conditional covariance. Binary pore two-point correlation was conservatively omitted for overlap with existing co-occurrence texture. No crystal-axis, method, classifier-field or parameter variants were counted separately.

## Roadmap boundary

Parent should review the 20 prioritized scientific tasks before any adapter source is authored, then separately decide whether the two conditional follow-ups merit isolation work. Every task still needs complete dependency/source identity, independent numeric and negative tests, provenance/schema acceptance and receiving-lab review. Research entries contribute **zero** to the accepted production count.

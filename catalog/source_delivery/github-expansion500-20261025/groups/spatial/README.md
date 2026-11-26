# Spatial research inventory

Status: `research_only_not_integrated_not_counted`

30 proposed operations; 0 integrated or counted by this delivery. Every row in
[research-inventory.json](research-inventory.json) has the same research-only status.

This is a concise consolidation of already obtained official source evidence.
No further browsing, source reads, tests, installation or deployment were performed
for this write. Accepted117, adapters, Skills and shared files were not modified.

## First five candidates

1. `GeoSpatialFlowNetworkUpscaleIHU`: drainage-network coarsening.
2. `GeoSpatialFloodplainStageStorage`: catchment stage/storage curves.
3. `GeoSpatialCoverageSimplification`: shared-boundary polygon simplification.
4. `GeoSpatialConservativeArealTransfer`: overlap-weighted transfer of extensive totals.
5. `GeoSpatialGroundwaterZoneBudget`: interzonal groundwater flux accounting.

## Evidence and limits

The JSON records each proposed ID, task, exact callable, previously seen official
source URL, known version/commit/license, short distinctness note and unresolved
risks. Comparison used the previously read 346-tool baseline plus accepted groups;
parent dedup approval is still required. Unknown locks and CPU acceptance are null.

Candidate upstream releases: PyFlwDir 0.5.12; Shapely 2.1.2; Tobler 0.14.0;
FloPy 3.11.0; Rasterio 1.4.3; ESDA 2.10.0; Pointpats 2.6.0; Spopt 0.8.0;
Landlab 2.11.0; scikit-learn 1.7.2; PDAL 2.9.1; GRASS 8.5.0.
These versions are source identifiers, not a complete requirements lock.

Main gates: parent semantic dedup; independent numeric/negative/unit/CRS oracles;
native GDAL/PDAL/GRASS and Landlab compatibility; exact MILP solver locks;
explicit handling of upstream HAG fallback, RPC failure and numerical-state side
effects. PDAL entries identify C++ algorithm methods and fixed stages, not
unverified Python binding APIs. GRASS entries permit only the named fixed module,
not generic command dispatch.

No claim of completion toward 500 tools is made.

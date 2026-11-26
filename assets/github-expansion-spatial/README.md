# Synthetic spatial fixtures

All 30 primary and three supplemental JSON inputs are explicitly synthetic analytic constructions. They are not geological observations, mineral evidence, training data or acceptance receipts. Projected examples use arbitrary metre coordinates in EPSG:32631 solely for deterministic numerical examples. No external data files, downloads, raster sidecars or generated binary fixtures are required.

r2 retains the original Strahler terminal=2 fixture and the original shifted-raster NoData fixture. strahler_order_multi_221.json has incoming branch orders 2,2,1 and confluence/terminal order 3; strahler_order_multi_112.json has incoming 1,1,2 and confluence/terminal order 2. raster_reproject_cross_crs.json uses UTM31N (500000,0) and Web Mercator (6378137*pi/60,0), the same equatorial longitude 3-degree pixel center, with expected value 17. The cross-CRS fixture is not a same-CRS identity warp and its expected coordinate does not call PROJ.

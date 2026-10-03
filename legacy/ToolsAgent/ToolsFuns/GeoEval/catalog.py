"""Single source of truth for GeoToolEval tool registration and GeoToolKG."""

from __future__ import annotations


CATEGORY_LABELS = {
    "DeepEarthTools": "Deep Earth 3D structure",
    "GeoBigDataTools": "Geospatial big data and GeoSPARQL",
    "MineralResourcesTools": "Critical mineral resources",
    "ClimateChangeTools": "Past, present, and future climate",
    "EnergyResourcesTools": "Energy resources",
    "OceanCarbonTools": "Global ocean carbon cycle",
    "DeepTimeBiosphereTools": "Origins of life and deep-time biosphere",
    "CCSTools": "Carbon capture and storage",
    "RemoteSensingTools": "Remote sensing and raster analytics",
    "NaturalHazardTools": "Natural hazards and extreme events",
}


_TOOLS = {
    "DeepEarthTools": {
        "DeepEarthQueryLITHO1": "Query nearest-node Moho or lithospheric-lid depth from the pinned LITHO1.0 sample table.",
        "DeepEarthQuerySEMUCB": "Query SEMUCB-WM1 dlnVs at a named location and model depth.",
        "DeepEarthQueryUSGSCatalog": "Filter, rank, count, or aggregate the frozen USGS M7+ earthquake catalog.",
        "DeepEarthGetUSGSEvent": "Retrieve one earthquake by event identifier from the frozen USGS catalog.",
        "DeepEarthSampleEventModels": "Join a USGS event to its nearest LITHO1.0 node and SEMUCB-WM1 sample.",
    },
    "GeoBigDataTools": {
        "GeoBigDataExecuteGeoSPARQL": "Execute a caller-supplied GeoSPARQL query against an HTTP endpoint or a pinned YAGO2geo materialized-query snapshot. The Tool never resolves an evaluation question or answer by lookup.",
    },
    "MineralResourcesTools": {
        "MineralResourcesSearchDeposits": "Filter USGS MRDS deposits by country and primary commodity.",
        "MineralResourcesGetDeposit": "Retrieve a USGS MRDS deposit by dep_id.",
        "MineralResourcesCountrySummary": "Count a country's MRDS records and rank its primary commodities.",
        "MineralResourcesRankCommodityCountries": "Rank countries by records related to a critical commodity.",
    },
    "ClimateChangeTools": {
        "ClimateQueryDeepTime": "Select the nearest Friedrich2016 or Bintanja2005 deep-time climate observation.",
        "ClimateQueryPresentMean": "Calculate a NASA GISTEMP mean over an inclusive year interval.",
        "ClimateQueryFutureSSP": "Retrieve IPCC AR6 SSP warming estimates for a scenario and horizon (SSP1-1.9/1-2.6/2-4.5/3-7.0/5-8.5; default endpoint 2100).",
        "ClimateCompareEpochs": "Compare numeric climate values returned by earlier climate tools; accepts values/x arrays or upstream result objects.",
    },
    "EnergyResourcesTools": {
        "EnergyFacilityDistance": "Compute great-circle distance between selected OPSD facilities.",
        "EnergyMineralSiteDistance": "Compute distance between two MRDS critical-mineral sites.",
        "EnergyBBoxArea": "Compute spherical area for an energy-resource WGS84 bounding box.",
        "EnergyNearestFacility": "Retrieve the nearest OPSD facility to a national capital.",
        "EnergyCapacityValue": "Read a year-end installed-capacity time-series value.",
        "EnergyNearestMineralSite": "Join an energy facility to its nearest critical-mineral site.",
        "EnergyCountryRenewableSummary": "Aggregate operating renewable capacity by technology.",
        "EnergyCapacityGrowth": "Calculate absolute and percentage capacity growth between two years.",
        "EnergyTransitionMetrics": "Join population, renewable capacity, and energy-consumption indicators.",
        "EnergyRegionalOverlaySummary": "Return a reproducible regional facility/mineral overlay summary.",
    },
    "OceanCarbonTools": {
        "OceanMonthlyGridValue": "Read a SOCAT monthly grid-cell fCO2 observation.",
        "OceanProfileValue": "Read a deep GLODAP profile carbon value.",
        "OceanCruiseQC": "Summarize SNAPO cruise carbon quality flags.",
        "OceanStationDistance": "Compute distance between GLODAP and SNAPO stations.",
        "OceanBBoxArea": "Compute spherical area of an ocean WGS84 bounding box.",
        "OceanAnnualCarbonSummary": "Read a quality-controlled North Pacific annual SOCAT summary.",
        "OceanVerticalProfileDifference": "Calculate surface-to-deep GLODAP carbon difference.",
        "OceanRegionalMapSummary": "Read a reproducible SOCAT regional mapping summary.",
        "OceanSurfaceDeepMatch": "Join nearest SOCAT surface and GLODAP deep observations.",
        "OceanProfileDeduplication": "Return SNAPO profile deduplication counts.",
    },
    "DeepTimeBiosphereTools": {
        "DeepTimeDecimalToDMS": "Convert a deep-time site coordinate from decimal degrees to DMS.",
        "DeepTimeHaversineDistance": "Compute WGS84 great-circle/haversine distance between deep-time sites using coordinates or BioDeepTime series IDs.",
        "DeepTimeBearing": "Compute initial bearing between deep-time sites.",
        "DeepTimeBBoxArea": "Compute spherical area of a deep-time study bounding box.",
        "DeepTimeStandardizeSpatialData": "Read CSV/GeoJSON assets and emit standardized GeoJSON metadata.",
        "DeepTimeValidateSpatialData": "Validate coordinate ranges, empty geometries, and duplicate features.",
        "DeepTimeNearestNeighbor": "Calculate nearest neighbours for point features.",
        "DeepTimeBuffer": "Generate reproducible point-buffer envelope features.",
        "DeepTimeOverlay": "Perform point-in-polygon overlay for GeoJSON layers.",
        "DeepTimeBatchVector": "Standardize and batch-copy vector layers.",
        "DeepTimeInterpolateIDW": "Interpolate point values to a NumPy grid using IDW.",
        "DeepTimeRasterAlgebra": "Apply a mask or arithmetic expression to a raster grid.",
        "DeepTimeZonalStatistics": "Calculate raster summary statistics by analysis zone.",
        "DeepTimeRenderMap": "Render a PNG and HTML inspection map from geospatial outputs.",
    },
    "CCSTools": {
        "CCSDecimalToDMS": "Convert a CCS facility coordinate from decimal degrees to DMS.",
        "CCSHaversineDistance": "Compute WGS84 great-circle/haversine distance between CCS facilities using coordinates or CCS case IDs.",
        "CCSBearing": "Compute initial bearing between CCS facilities.",
        "CCSBBoxArea": "Compute spherical area of a CCS study bounding box.",
        "CCSCheckCRSConsistency": "Check whether CCS input layers use a consistent CRS.",
        "CCSStandardizeSpatialData": "Read CCS CSV/GeoJSON assets and emit standardized GeoJSON metadata.",
        "CCSValidateSpatialData": "Validate CCS coordinates, geometries, and identifiers.",
        "CCSNearestNeighbor": "Calculate nearest CCS facilities.",
        "CCSBuffer": "Generate point-buffer envelope features for CCS monitoring.",
        "CCSOverlay": "Perform CCS facility/analysis-zone overlay.",
        "CCSBatchVector": "Standardize and batch-copy CCS vector layers.",
        "CCSInterpolateIDW": "Interpolate CCS measurements to a NumPy grid using IDW.",
        "CCSRasterAlgebra": "Apply a mask or arithmetic expression to a CCS raster grid.",
        "CCSZonalStatistics": "Calculate CCS raster or tabular zone statistics.",
        "CCSRenderMap": "Render a PNG and HTML inspection map from CCS outputs.",
    },
    "RemoteSensingTools": {
        "RemoteSensingListFiles": "List files in a bundled EarthBench asset directory.",
        "RemoteSensingBatchImageMean": "Calculate finite-pixel means for a batch of GeoTIFF/raster assets; accepts an EarthBench question directory or explicit file_list.",
        "RemoteSensingBatchHotspotPercentage": "Calculate per-image percentage above a threshold.",
        "RemoteSensingTiffAverage": "Create a pixelwise average GeoTIFF from an image batch.",
        "RemoteSensingBatchNDSI": "Calculate NDSI rasters from green and SWIR bands.",
        "RemoteSensingNDWI": "Calculate normalized-difference water index rasters from one green/NIR pair or aligned multi-date path arrays.",
        "RemoteSensingNBR": "Calculate normalized burn ratio rasters from one NIR/SWIR pair or aligned multi-date path arrays.",
        "RemoteSensingCloudMask": "Apply Landsat QA cloud and shadow bit masks to one raster pair or aligned multi-date path arrays.",
        "RemoteSensingBatchHotspotRaster": "Create threshold binary rasters from input rasters.",
        "RemoteSensingNDVI": "Calculate NDVI rasters from one NIR/red pair or aligned multi-date path arrays.",
        "RemoteSensingNDTI": "Calculate NDTI rasters from scene/date-paired green and red band inputs.",
        "RemoteSensingCountAboveThreshold": "Count finite raster pixels above a threshold.",
        "RemoteSensingBatchImageSum": "Calculate finite-pixel sums for a batch of GeoTIFFs.",
        "RemoteSensingTiffDifference": "Create one pixelwise difference GeoTIFF or a batch of aligned adjacent-date difference rasters.",
        "RemoteSensingExtremeSnowLossPercentage": "Calculate snow-loss percentage from a binary map.",
        "RemoteSensingSubtract": "Subtract one raster from another and write the result.",
        "RemoteSensingFireIncreaseMap": "Create a fire-increase binary map from a change raster.",
        "RemoteSensingMean": "Calculate an arithmetic mean.",
        "RemoteSensingPercentageChange": "Calculate percentage change from a to b.",
        "RemoteSensingDifference": "Subtract b from a.",
        "RemoteSensingDivision": "Divide scalar a by b or calculate an aligned time-series ratio from numeric arrays.",
        "RemoteSensingLinearTrend": "Fit a least-squares linear trend.",
        "RemoteSensingMaxValueAndIndex": "Return the maximum value and zero-based index.",
        "RemoteSensingKelvinToCelsius": "Convert kelvin to degrees Celsius.",
        "RemoteSensingMinValueAndIndex": "Return the minimum value and zero-based index.",
        "RemoteSensingSensSlope": "Calculate the median pairwise Sen slope.",
        "RemoteSensingCoefficientOfVariation": "Calculate standard deviation divided by mean.",
        "RemoteSensingKurtosis": "Calculate population Pearson kurtosis and excess kurtosis.",
        "RemoteSensingMannKendallTest": "Calculate a Mann-Kendall trend statistic and p-value.",
        "RemoteSensingArgmax": "Return the zero-based index of the maximum value.",
    },
    "NaturalHazardTools": {
        "NaturalHazardLoadEventTable": "Load and describe the EM-DAT-compatible event workbook.",
        "NaturalHazardFilterRecords": "Filter natural-hazard records with exact field predicates.",
        "NaturalHazardCountRecords": "Count filtered natural-hazard records.",
        "NaturalHazardSumField": "Sum a numeric field over filtered records.",
        "NaturalHazardGroupAggregate": "Group filtered EM-DAT-compatible disaster records and calculate count or sum rankings; group_by/grouping_fields may be a field name or one-item list.",
        "NaturalHazardSelectMaxRecord": "Return the event identifier with the maximum measure.",
        "NaturalHazardBuildStartDate": "Build valid ISO dates from Start Year/Month/Day fields.",
        "NaturalHazardSelectLatest": "Return the latest complete start date after filtering.",
    },
}


TOOLS_MAPPING = {category: list(tools) for category, tools in _TOOLS.items()}


TOOL_NEXT = {
    "DeepEarthGetUSGSEvent": ["DeepEarthSampleEventModels"],
    "MineralResourcesSearchDeposits": ["MineralResourcesGetDeposit"],
    "MineralResourcesCountrySummary": ["MineralResourcesSearchDeposits"],
    "MineralResourcesRankCommodityCountries": ["ClimateQueryFutureSSP"],
    "ClimateQueryDeepTime": ["ClimateCompareEpochs"],
    "ClimateQueryPresentMean": ["ClimateQueryFutureSSP", "ClimateCompareEpochs"],
    "ClimateQueryFutureSSP": ["ClimateCompareEpochs"],
    "DeepTimeStandardizeSpatialData": ["DeepTimeValidateSpatialData", "DeepTimeBatchVector"],
    "DeepTimeValidateSpatialData": ["DeepTimeNearestNeighbor", "DeepTimeBuffer", "DeepTimeOverlay", "DeepTimeInterpolateIDW"],
    "DeepTimeNearestNeighbor": ["DeepTimeRenderMap"],
    "DeepTimeBuffer": ["DeepTimeOverlay", "DeepTimeRenderMap"],
    "DeepTimeOverlay": ["DeepTimeInterpolateIDW", "DeepTimeZonalStatistics", "DeepTimeRenderMap"],
    "DeepTimeBatchVector": ["DeepTimeValidateSpatialData", "DeepTimeOverlay"],
    "DeepTimeInterpolateIDW": ["DeepTimeRasterAlgebra", "DeepTimeZonalStatistics", "DeepTimeRenderMap"],
    "DeepTimeRasterAlgebra": ["DeepTimeZonalStatistics", "DeepTimeRenderMap"],
    "DeepTimeZonalStatistics": ["DeepTimeRenderMap"],
    "CCSStandardizeSpatialData": ["CCSValidateSpatialData", "CCSBatchVector"],
    "CCSValidateSpatialData": ["CCSNearestNeighbor", "CCSBuffer", "CCSOverlay", "CCSInterpolateIDW"],
    "CCSNearestNeighbor": ["CCSRenderMap"],
    "CCSBuffer": ["CCSOverlay", "CCSRenderMap"],
    "CCSOverlay": ["CCSInterpolateIDW", "CCSZonalStatistics", "CCSRenderMap"],
    "CCSBatchVector": ["CCSValidateSpatialData", "CCSOverlay"],
    "CCSInterpolateIDW": ["CCSRasterAlgebra", "CCSZonalStatistics", "CCSRenderMap"],
    "CCSRasterAlgebra": ["CCSZonalStatistics", "CCSRenderMap"],
    "CCSZonalStatistics": ["CCSRenderMap"],
    "RemoteSensingListFiles": [
        "RemoteSensingBatchImageMean",
        "RemoteSensingTiffAverage",
        "RemoteSensingBatchNDSI",
        "RemoteSensingNDWI",
        "RemoteSensingNBR",
        "RemoteSensingCloudMask",
        "RemoteSensingNDVI",
        "RemoteSensingNDTI",
        "RemoteSensingTiffDifference",
    ],
    "RemoteSensingBatchImageMean": [
        "RemoteSensingMean",
        "RemoteSensingDifference",
        "RemoteSensingPercentageChange",
        "RemoteSensingLinearTrend",
        "RemoteSensingMaxValueAndIndex",
        "RemoteSensingMinValueAndIndex",
        "RemoteSensingKurtosis",
        "RemoteSensingKelvinToCelsius",
    ],
    "RemoteSensingTiffAverage": ["RemoteSensingBatchImageSum", "RemoteSensingBatchHotspotPercentage"],
    "RemoteSensingBatchNDSI": ["RemoteSensingBatchImageMean", "RemoteSensingTiffAverage"],
    "RemoteSensingNDTI": ["RemoteSensingBatchImageMean", "RemoteSensingArgmax"],
    "RemoteSensingTiffDifference": ["RemoteSensingCountAboveThreshold", "RemoteSensingFireIncreaseMap"],
    "NaturalHazardLoadEventTable": ["NaturalHazardFilterRecords"],
    "NaturalHazardFilterRecords": [
        "NaturalHazardCountRecords",
        "NaturalHazardSumField",
        "NaturalHazardGroupAggregate",
        "NaturalHazardSelectMaxRecord",
        "NaturalHazardBuildStartDate",
    ],
    "NaturalHazardBuildStartDate": ["NaturalHazardSelectLatest"],
}


_INPUT_OVERRIDES = {
    "DeepEarthQueryLITHO1": 'JSON object: required location_key; optional node_index and layer ("moho" or "lid"). Example: {"location_key":"beijing","node_index":14010,"layer":"moho"}',
    "DeepEarthQuerySEMUCB": 'JSON object: required location_key and depth_km; optional parameter="S". Example: {"location_key":"beijing","depth_km":100,"parameter":"S"}',
    "DeepEarthQueryUSGSCatalog": 'JSON object with operation and its filters. Supported operations: count, largest, deepest, total_energy, event. Optional fields: minimum_magnitude, year, start, end_exclusive, event_id, event_count, formula',
    "DeepEarthGetUSGSEvent": 'JSON object with required event_id. Copy event_id from the authoritative source_locator when present',
    "DeepEarthSampleEventModels": 'JSON object with required event_id; optional litho_node_index and semucb_depth_km',
    "GeoBigDataExecuteGeoSPARQL": (
        'JSON object with required executable SPARQL field "query" (or a numeric source_id supplied by the user). '
        'For a pinned semantic dataset, do not invent an endpoint and do not return the question as a parameter. '
        'Compile the natural-language request to YAGO2geo GeoSPARQL using: named entities yago:Name_With_Underscores; '
        'feature classes y2geoo:OSM_park/forest/lake/stream/beach/island/lagoon/nature_reserve/locality/village/canal, '
        'administrative classes y2geoo:OS_County/OS_District/OSI_County_Council/OSI_City_and_County_Council/'
        'OSI_Rural_Area/OSI_Townland/GAG_Municipality; geometry pattern '
        '?feature geo:hasGeometry ?geometry . ?geometry geo:asWKT ?wkt; spatial functions '
        'geof:sfWithin/sfContains/sfIntersects/sfTouches/sfCrosses/distance and '
        'strdf:area/above/below/left. Use SELECT, aggregates, GROUP BY, ORDER BY and LIMIT as requested. '
        'Prefixes may be omitted. Optional dataset is provenance only.'
    ),
    "MineralResourcesSearchDeposits": 'JSON object with optional country and commodity filters and integer limit (default 3)',
    "MineralResourcesGetDeposit": 'JSON object with required integer dep_id',
    "MineralResourcesCountrySummary": 'JSON object with required country and optional integer limit',
    "MineralResourcesRankCommodityCountries": 'JSON object with required commodity and optional integer limit',
    "ClimateQueryDeepTime": 'JSON object with dataset and either age_kyr_bp or find="min_temp_friedrich"',
    "ClimateQueryPresentMean": 'JSON object with required inclusive year_start and year_end integers',
    "ClimateQueryFutureSSP": 'JSON object with scenario/ssp and horizon_year/ssp_horizon; if the locator omits the year, use the standard 2100 endpoint',
    "ClimateCompareEpochs": 'JSON object with numeric values/x array (upstream result objects are accepted) and optional operation',
    "EnergyFacilityDistance": 'JSON object with country, solar_municipality and wind_municipality; preserve null municipality values from source_locator and include question_id if available',
    "EnergyMineralSiteDistance": 'JSON object with required integer dep_id_1 and dep_id_2; optional question_id',
    "EnergyBBoxArea": 'JSON object with required bbox=[min_lon,min_lat,max_lon,max_lat]; optional plant_name and question_id',
    "EnergyNearestFacility": 'JSON object with required country and energy_source; optional capital and question_id',
    "EnergyCapacityValue": 'JSON object with required series and year; optional question_id',
    "EnergyNearestMineralSite": 'JSON object with required plant_name; optional mrds_dep_id and question_id',
    "EnergyCountryRenewableSummary": 'JSON object with required country; optional renewable_types array, status and question_id',
    "EnergyCapacityGrowth": 'JSON object with required series, start_year and end_year; optional question_id',
    "EnergyTransitionMetrics": 'JSON object with required country; optional population_year, consumption_year and question_id',
    "EnergyRegionalOverlaySummary": 'JSON object with required region and bbox; optional question_id',
    "OceanMonthlyGridValue": 'JSON object with required date, latitude and longitude; optional question_id',
    "OceanProfileValue": 'JSON object with required expocode and station; optional depth_m and question_id',
    "OceanCruiseQC": 'JSON object with required cruise; optional required_flags and question_id',
    "OceanStationDistance": 'JSON object with required glodap_expocode, glodap_station and snapo_cruise; optional question_id',
    "OceanBBoxArea": 'JSON object with required bbox=[min_lon,min_lat,max_lon,max_lat]; optional region and question_id',
    "OceanAnnualCarbonSummary": 'JSON object with required year; optional fCO2rec_flag and question_id',
    "OceanVerticalProfileDifference": 'JSON object with required expocode and station; optional question_id',
    "OceanRegionalMapSummary": 'JSON object with required region and bbox; optional year and question_id',
    "OceanSurfaceDeepMatch": 'JSON object with required glodap_expocode and glodap_station; optional socat_date and question_id',
    "OceanProfileDeduplication": 'JSON object with required cruise; optional deduplication_key and question_id',
    "DeepTimeDecimalToDMS": 'JSON object with numeric value and axis field (field="lat" or "lon"), or compact input_text="value,lat|lon"',
    "DeepTimeHaversineDistance": 'JSON object with lat1, lon1, lat2, lon2, or series_ids=[id1,id2] plus input_assets; compact input_text="lat1,lon1;lat2,lon2" is also accepted',
    "DeepTimeBearing": 'JSON object with lat1, lon1, lat2, lon2, or series_ids=[from_id,to_id] plus input_assets, or compact input_text="lat1,lon1;lat2,lon2"',
    "DeepTimeBBoxArea": 'JSON object with bbox=[min_lon,min_lat,max_lon,max_lat], or compact input_text with the four values',
    "CCSDecimalToDMS": 'JSON object with numeric value and axis field (field="lat" or "lon"), or case_id/facility_id plus input_assets, or compact input_text="value,lat|lon"',
    "CCSHaversineDistance": 'JSON object with lat1, lon1, lat2, lon2, or case_ids=[id1,id2] plus input_assets; compact input_text="lat1,lon1;lat2,lon2" is also accepted',
    "CCSBearing": 'JSON object with lat1, lon1, lat2, lon2, or case_ids=[from_id,to_id] plus input_assets, or compact input_text="lat1,lon1;lat2,lon2"',
    "CCSBBoxArea": 'JSON object with bbox=[min_lon,min_lat,max_lon,max_lat], or compact input_text with the four values',
    "CCSCheckCRSConsistency": 'JSON object with crs_values array, input_assets pointing to a CRS inventory, or compact input_text containing CRS identifiers',
    "DeepTimeStandardizeSpatialData": 'JSON object with paths/input_assets array and optional lon_field, lat_field and _output_keys. Accepts CSV or GeoJSON and emits concrete standardized layer paths',
    "DeepTimeValidateSpatialData": 'JSON object with paths/input_assets array or an upstream standardized layer path and optional _output_keys',
    "DeepTimeNearestNeighbor": 'JSON object with paths containing an upstream point layer and optional neighbor_count and _output_keys',
    "DeepTimeBuffer": 'JSON object with paths containing an upstream point layer, optional distance_km, and _output_keys',
    "DeepTimeOverlay": 'JSON object with paths containing point/buffer and polygon layers and optional _output_keys',
    "DeepTimeBatchVector": 'JSON object with paths/input_assets array and optional _output_keys',
    "DeepTimeInterpolateIDW": 'JSON object with paths containing a point CSV plus optional lon_field, lat_field, value_field, grid_size and _output_keys',
    "DeepTimeRasterAlgebra": 'JSON object with paths containing an upstream .npy/GeoTIFF, optional minimum and _output_keys',
    "DeepTimeZonalStatistics": 'JSON object with paths containing an upstream .npy/GeoTIFF and optional _output_keys',
    "DeepTimeRenderMap": 'JSON object with optional paths, title and _output_keys; emits map_png and map_html',
    "CCSStandardizeSpatialData": 'JSON object with paths/input_assets array and optional lon_field, lat_field and _output_keys. Accepts CSV or GeoJSON and emits concrete standardized layer paths',
    "CCSValidateSpatialData": 'JSON object with paths/input_assets array or an upstream standardized layer path and optional _output_keys',
    "CCSNearestNeighbor": 'JSON object with paths containing an upstream point layer and optional neighbor_count and _output_keys',
    "CCSBuffer": 'JSON object with paths containing an upstream point layer, optional distance_km, and _output_keys',
    "CCSOverlay": 'JSON object with paths containing point/buffer and polygon layers and optional _output_keys',
    "CCSBatchVector": 'JSON object with paths/input_assets array and optional _output_keys',
    "CCSInterpolateIDW": 'JSON object with paths containing a point CSV plus optional lon_field, lat_field, value_field, grid_size and _output_keys',
    "CCSRasterAlgebra": 'JSON object with paths containing an upstream .npy/GeoTIFF, optional minimum and _output_keys',
    "CCSZonalStatistics": 'JSON object with paths containing an upstream .npy/GeoTIFF and optional _output_keys',
    "CCSRenderMap": 'JSON object with optional paths, title and _output_keys; emits map_png and map_html',
    "RemoteSensingListFiles": 'JSON object with required string field: {"dir_path":"EarthBench asset directory"}',
    "RemoteSensingBatchImageMean": 'JSON object with required non-empty array: {"file_list":["GeoTIFF path", ...]}; after RemoteSensingListFiles, copy its complete "files" array into "file_list"',
    "RemoteSensingBatchHotspotPercentage": 'JSON object with required file_list array and numeric threshold',
    "RemoteSensingBatchImageSum": 'JSON object with required non-empty array: {"file_list":["GeoTIFF path", ...]}',
    "RemoteSensingTiffAverage": 'JSON object with required file_list array and optional output_path',
    "RemoteSensingBatchNDSI": 'JSON object with required green_file_list and swir_file_list arrays; optional output_path_list',
    "RemoteSensingNDWI": 'JSON object with input_swir_path (green band) and input_nir_path, or equal-length input_swir_paths/input_nir_paths arrays for multi-date batch execution; optional output_path',
    "RemoteSensingNBR": 'JSON object with input_nir_path and input_swir_path, or equal-length input_nir_paths/input_swir_paths arrays for multi-date batch execution; optional output_path',
    "RemoteSensingCloudMask": 'JSON object with sr_band_path and qa_pixel_path, or equal-length sr_band_paths/qa_pixel_paths arrays for multi-date batch execution; optional output_path',
    "RemoteSensingBatchHotspotRaster": 'JSON object with required file_list and numeric threshold; optional output_path_list',
    "RemoteSensingNDVI": 'JSON object with nir_band_file/red_band_file, or equal-length nir_band_files/red_band_files arrays for multi-date batch execution; optional output_file',
    "RemoteSensingNDTI": 'JSON object with required input_pairs array of input_green_path/input_red_path objects',
    "RemoteSensingCountAboveThreshold": 'JSON object with required file_path and optional numeric threshold',
    "RemoteSensingTiffDifference": 'JSON object with image_a_path/image_b_path, or equal-length image_a_paths/image_b_paths arrays; optional output_path',
    "RemoteSensingExtremeSnowLossPercentage": 'JSON object with required binary_map_path and optional threshold',
    "RemoteSensingSubtract": 'JSON object with required img1_path and img2_path; optional output_path and nodata_as_zero for sparse event rasters',
    "RemoteSensingFireIncreaseMap": 'JSON object with required change_image_path and threshold; optional output_path',
    "RemoteSensingMean": 'JSON object with required numeric array: {"x":[number, ...]}',
    "RemoteSensingPercentageChange": 'JSON object with required numeric fields: {"a":number,"b":number}',
    "RemoteSensingDifference": 'JSON object with required numeric fields: {"a":number,"b":number}',
    "RemoteSensingDivision": 'JSON object with numeric a and b, or equal-length numeric a_values and b_values arrays for time-series ratios',
    "RemoteSensingLinearTrend": 'JSON object with required numeric y array and optional x array: {"y":[number, ...],"x":[number, ...]}',
    "RemoteSensingMaxValueAndIndex": 'JSON object with required numeric array: {"x":[number, ...]}',
    "RemoteSensingKelvinToCelsius": 'JSON object with required numeric field: {"kelvin":number}',
    "RemoteSensingMinValueAndIndex": 'JSON object with required numeric array: {"x":[number, ...]}',
    "RemoteSensingSensSlope": 'JSON object with required numeric array: {"x":[number, ...]}',
    "RemoteSensingCoefficientOfVariation": 'JSON object with required numeric array: {"x":[number, ...]}',
    "RemoteSensingKurtosis": 'JSON object with required numeric array: {"x":[number, ...]}',
    "RemoteSensingMannKendallTest": 'JSON object with required numeric array: {"x":[number, ...]}',
    "RemoteSensingArgmax": 'JSON object with required numeric array: {"x":[number, ...]}',
    "NaturalHazardLoadEventTable": 'JSON object with required source workbook path and sheet name: {"source":".xlsx path","sheet":"Sheet1"}',
    "NaturalHazardFilterRecords": 'JSON object with source workbook path, sheet name, and required non-empty exact-match filters object',
    "NaturalHazardCountRecords": 'JSON object with filtered_records_path, or with source/sheet and filters',
    "NaturalHazardSumField": 'JSON object with filters and required measure; optional filtered_records_path, source and sheet',
    "NaturalHazardGroupAggregate": 'JSON object with filters and required group_by; optional measure for sum ranking and filtered_records_path',
    "NaturalHazardSelectMaxRecord": 'JSON object with filters and required measure; optional filtered_records_path',
    "NaturalHazardBuildStartDate": 'JSON object with filters and optional date_fields array and filtered_records_path',
    "NaturalHazardSelectLatest": 'JSON object with filters and optional date_fields array and filtered_records_path',
}


def _default_io(name: str) -> tuple[str, str]:
    if name in {"CCSZonalStatistics", "DeepTimeZonalStatistics"}:
        return "JSON paths containing one georeferenced GeoTIFF and one WGS84 polygon GeoJSON zone layer, with unique zone_field identifiers (default zone_id); explicit band required for multiband rasters. Every source must be an exact existing file; missing files are not omitted or replaced by filename searches. Optional raster_path/zones_path must match these roles; operation is mean, sum, minimum, maximum or count. Explicit variable/time/year/region must match raster metadata. Or one CSV with explicit zone_field/value_field. Missing zones is unsupported.", "JSON per-zone statistics with stable zone_id, selected value/operation, count, mean, minimum, maximum, sum, sources, band and CRS"
    if name in {"CCSRenderMap", "DeepTimeRenderMap"}:
        return "JSON paths containing WGS84 GeoJSON geometries or one georeferenced GeoTIFF; optional title. Classification fields and title-only inputs are unsupported.", "JSON actual PNG/HTML spatial rendering, extent, CRS and feature/pixel evidence"
    if name in {"CCSBuffer", "DeepTimeBuffer"}:
        return "JSON paths containing one WGS84 point layer and distance_km or buffer_distances_km; radius positive and <=100 km; abs(latitude)<=75 degrees.", "JSON 128-segment spherical buffer GeoJSON, radius and approximation scope"
    if name in {"CCSOverlay", "DeepTimeOverlay"}:
        return "JSON paths containing exactly one WGS84 point layer and one Polygon/MultiPolygon GeoJSON; polygon-polygon intersection is unsupported.", "JSON point-in-polygon memberships, including holes and boundaries, plus GeoJSON artifact"
    if name in _INPUT_OVERRIDES:
        return _INPUT_OVERRIDES[name], "JSON result"
    if name.startswith("RemoteSensing"):
        return "JSON arguments containing raster paths, arrays, or thresholds", "JSON result and optional GeoTIFF/PNG artifact"
    if name.startswith("NaturalHazard"):
        return "JSON filters, grouping fields, measures, and source workbook", "JSON records, aggregate, or output path"
    if any(token in name for token in ("Spatial", "Overlay", "Buffer", "Vector", "Interpolate", "Raster", "Map")):
        return "JSON arguments containing concrete input paths and operation parameters", "JSON metadata and concrete output artifact paths"
    return "JSON object or the documented compact text form", "JSON result"


def _ndvi_input_schema():
    """Role/type contract; cross-array length equality is checked by NDVI itself."""
    path = {"type": "string", "minLength": 1, "pattern": r"\S"}
    paths = {"type": "array", "items": path, "minItems": 1}
    scalar_nir, scalar_red = ("nir_band_file", "input_nir_path"), ("red_band_file", "input_red_path")
    batch_nir, batch_red = ("nir_band_files", "input_nir_paths"), ("red_band_files", "input_red_paths")

    def required_role(names):
        return {"anyOf": [{"required": [name]} for name in names]}

    return {
        "type": "object",
        "description": "Explicit NIR and red input roles, as a single pair or nonempty aligned path arrays. Batch arrays must have equal length; the tool checks this before opening files.",
        "properties": {**{name: path for name in (*scalar_nir, *scalar_red)},
                       **{name: paths for name in (*batch_nir, *batch_red)}},
        "anyOf": [
            {"allOf": [required_role(scalar_nir), required_role(scalar_red)],
             "properties": {name: False for name in (*batch_nir, *batch_red)}},
            {"allOf": [required_role(batch_nir), required_role(batch_red)]},
        ],
    }


TOOL_SPECS = []
from .scientific_contracts import tool_scientific_contract
for category, tools in _TOOLS.items():
    for name, function in tools.items():
        tool_input, tool_output = _default_io(name)
        TOOL_SPECS.append(
            {
                "Name": name,
                "Category": category,
                "Function": function,
                "Input": tool_input,
                **({"InputSchema": _ndvi_input_schema()} if name == "RemoteSensingNDVI" else {}),
                "Output": tool_output,
                "Source": "GeoToolEval pinned datasets and open-source Python geospatial stack",
                "Safety": "Yes",
                "ScientificContract": tool_scientific_contract(name),
                "Next": ",".join(TOOL_NEXT.get(name, [])),
            }
        )


TOOL_SPEC_BY_NAME = {item["Name"]: item for item in TOOL_SPECS}


def get_tool_spec(name: str):
    """Return the live registry schema so runtime planning cannot use stale KG I/O text."""

    item = TOOL_SPEC_BY_NAME.get(name)
    return dict(item) if item else None

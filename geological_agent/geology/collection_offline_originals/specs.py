"""Interface proposals; registration and parent regression remain separate gates."""

def text(description, limit=256):
    return {"type": "string", "minLength": 1, "maxLength": limit, "description": description}


def num(description, low=-1e12, high=1e12):
    return {"type": "number", "minimum": low, "maximum": high, "description": description}


def array(items, low=1, high=10000):
    return {"type": "array", "minItems": low, "maxItems": high, "items": items}


def make(project_id, project, name, function, description, properties, example, required_result, paths=(), requirements=(), limitations=()):
    output = dict(required_result, units={"type": "object"})
    return {"project_id": project_id, "project_directory_name": project, "name": name, "function": function, "description": description,
            "source_mode": "vendored_source", "package": None, "version": None, "requirements": list(requirements),
            "input_schema": {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False},
            "output_schema": {"type": "object", "properties": output, "required": list(output), "additionalProperties": True},
            "example_arguments": example, "path_fields": list(paths), "produces_files": False, "network_required": False,
            "validation": "not_run", "activation": "parent_integration_and_contract_acceptance_pending", "tags": ["earth-collection", "offline-originals"],
            "limitations": ["Bounded original-source operation, not full upstream application compatibility.", *limitations]}


PAIR = array(num("Coordinate in declared CRS units"), 2, 2)
MATRIX = {"type": "array", "items": {"type": "array", "items": {"type": ["number", "null"]}}}
NUMBERS = array({"type": "number"})
CORE = ["numpy==2.1.3"]
RASTER = [*CORE, "rasterio==1.4.3", "shapely==2.1.2"]
CLIMATE = [*CORE, "xarray==2026.9.0", "pandas==2.3.0", "scipy==1.15.3"]

DEFINITIONS = [
    make(126, "pyowm", "EarthPyOWMBeaufortWind", "pyowm_beaufort_wind", "Classify measured wind speeds using the original PyOWM Beaufort thresholds, offline.",
         {"wind_speed_m_s": array(num("Measured wind speed, m/s", 0, 200))}, {"wind_speed_m_s": [0, 0.2, 0.21, 1.5, 1.51, 5.4, 5.41, 32.6, 32.61]},
         {"beaufort": array({"type": "integer", "minimum": 0, "maximum": 12}), "wind_speed_m_s": NUMBERS}),
    make(26, "EarthSim", "EarthSimRasterCrossSection", "earthsim_raster_cross_section", "Extract an offline projected-raster profile along a line using EarthSim's original path-interpolation kernel.",
         {"raster_path": text("Local single-band metre-projected GeoTIFF"), "line_coordinates_m": array(PAIR, 2, 4096), "resolution_m": num("Upstream sample-count resolution in metres", 0.001, 1e8), "value_unit": text("Native raster measurement unit", 32)},
         {"raster_path": "assets/offline-originals/projected.tif", "line_coordinates_m": [[0.5, 4.5], [4.5, 0.5]], "resolution_m": 1.4, "value_unit": "m"},
         {"x": NUMBERS, "y": NUMBERS, "distance": NUMBERS, "values": NUMBERS}, ["raster_path"], RASTER,
         ["Uses original inclusive endpoint linspace and int(length/resolution) sample count, not a promised constant step."]),
    make(31, "ERA5-tools", "EarthERA5LocalMonthlyClimate", "era5_local_monthly_climate", "Compute original ERA5-tools monthly climatological means and nearest-node time series from a local NetCDF3 source.",
         {"netcdf_path": text("Local bounded monthly NetCDF3 file"), "variable": text("Native monthly variable name", 64), "longitude": num("Requested longitude, degrees_east", -180, 360), "latitude": num("Requested latitude, degrees_north", -90, 90), "value_unit": text("Exact native NetCDF variable unit", 32)},
         {"netcdf_path": "assets/offline-originals/monthly.nc", "variable": "t2m", "longitude": 116.4, "latitude": 39.9, "value_unit": "K"},
         {"months": array({"type": "integer", "minimum": 1, "maximum": 12}, 12, 12), "monthly_mean": {"type": "array"}, "point_series": NUMBERS}, ["netcdf_path"], CLIMATE,
         ["Preserves original nearest-node tolerance 0.051 degrees; inputs must already be monthly values with native units.", "Does not invoke CDS, download data, convert accumulated fluxes, annualize values or claim full notebook execution."]),
    make(124, "pangaea", "EarthPangaeaGeographicGrid", "pangaea_geographic_grid", "Normalize geographic land-model array row alignment and longitude using the original Pangaea grid accessor kernels.",
         {"netcdf_path": text("Local NetCDF3 file with lat(y),lon(x) and a two-dimensional y,x variable"), "variable": text("Original y,x data variable", 64), "wrap_longitude": {"type": "boolean", "description": "Apply original longitude conversion to [-180,180)"}, "value_unit": text("Exact native variable unit", 32)},
         {"netcdf_path": "assets/offline-originals/land-grid.nc", "variable": "height", "wrap_longitude": True, "value_unit": "m"},
         {"latitude": MATRIX, "longitude": MATRIX, "values": MATRIX, "rows_reversed": {"type": "boolean"}}, ["netcdf_path"], CLIMATE,
         ["Two-dimensional geographic grids only; no WRF, GDAL, reprojection or 4D accessor compatibility is claimed."]),
    make(10, "geonotebook", "EarthGeoNotebookPolygonSubset", "geonotebook_polygon_subset", "Apply GeoNotebook's original all-touched polygon raster mask to a bounded WGS84 single-band raster.",
         {"raster_path": text("Local unrotated north-up single-band WGS84 GeoTIFF with explicit nodata"), "polygon_ring": array(PAIR, 4, 4096), "value_unit": text("Native measurement unit", 32)},
         {"raster_path": "assets/offline-originals/geographic.tif", "polygon_ring": [[1, 4], [4, 4], [4, 1], [1, 1], [1, 4]], "value_unit": "m"},
         {"values": MATRIX, "valid_cells": {"type": "integer", "minimum": 1}, "mean": {"type": "number"}, "minimum": {"type": "number"}, "maximum": {"type": "number"}}, ["raster_path"], RASTER,
         ["One fully contained exterior ring, no holes, multiband or out-of-bounds behavior; no Jupyter/server stack is imported."]),
    make(100, "hydroshare", "EarthHydroShareRasterBandRanges", "hydroshare_raster_band_ranges", "Compute native raster-band min/max using HydroShare's original statistics extractor in an isolated CPU subprocess.",
         {"raster_path": text("Local GeoTIFF with native band units"), "value_unit": text("Exact native band unit", 32)},
         {"raster_path": "assets/offline-originals/projected.tif", "value_unit": "m"},
         {"bands": {"type": "object", "minProperties": 1}}, ["raster_path"], [*CORE, "rasterio==1.4.3"],
         ["Activation blocked until parent pins and validates an exact native GDAL profile; no full Django/HydroShare deployment is claimed.", "Upstream changes cwd and can request GDAL statistics, so it runs only in a subprocess on a temporary input copy."]),
]


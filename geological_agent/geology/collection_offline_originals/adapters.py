"""Bounded offline interfaces, not replacements for complete upstream apps."""
from pathlib import Path
from types import SimpleNamespace
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

from ..collection_contracts import operation, reject


def _path(value, suffixes):
    path = Path(value)
    if path.is_symlink() or not path.is_file() or path.suffix.lower() not in suffixes:
        reject("An existing local input of the declared format is required", "invalid_input")
    if path.stat().st_size > 2 * 1024 * 1024:
        reject("Runtime input exceeds the 2 MiB bound", "resource_limit")
    return path.resolve()


def _finite(value):
    import numpy as np
    array = np.asarray(value, dtype=float)
    if not array.size or array.size > 262144 or not np.isfinite(array).all():
        reject("Scientific input must be finite and contain at most 262144 values")
    return array


@operation("EarthPyOWMBeaufortWind")
def pyowm_beaufort_wind(args):
    from .vendor.pyowm_kernel import metric_wind_dict_to_beaufort
    speeds = args["wind_speed_m_s"]
    if not 1 <= len(speeds) <= 10000:
        reject("Supply between 1 and 10000 wind measurements")
    for value in speeds:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 200:
            reject("Wind speeds must be finite measurements between 0 and 200 m/s")
    encoded = {str(i): value for i, value in enumerate(speeds)}
    levels = metric_wind_dict_to_beaufort(encoded)
    return {"beaufort": [levels[str(i)] for i in range(len(speeds))],
            "wind_speed_m_s": list(speeds), "units": {"wind_speed_m_s": "m/s", "beaufort": "Beaufort scale 0-12"},
            "scope": "Offline classification only; no OpenWeather API observation was requested."}


@operation("EarthSimRasterCrossSection")
def earthsim_raster_cross_section(args):
    import numpy as np
    import rasterio
    from shapely.geometry import LineString
    from .vendor.earthsim_kernel import LineCrossSectionKernel
    path = _path(args["raster_path"], {".tif", ".tiff"})
    coordinates = _finite(args["line_coordinates_m"])
    if coordinates.ndim != 2 or coordinates.shape[1] != 2 or not 2 <= len(coordinates) <= 4096:
        reject("The cross-section requires 2 to 4096 two-dimensional coordinates")
    resolution = args["resolution_m"]
    if isinstance(resolution, bool) or not isinstance(resolution, (int, float)) or not math.isfinite(resolution) or resolution <= 0:
        reject("resolution_m must be a positive finite number")
    line = LineString(coordinates)
    count = int(line.length / resolution)
    if not line.is_valid or not 2 <= count <= 10000:
        reject("Upstream interpolation must generate between 2 and 10000 samples")
    xs, ys, distances = LineCrossSectionKernel._gen_samples(SimpleNamespace(resolution=resolution), line)
    with rasterio.open(path) as source:
        if source.count != 1 or source.crs is None or not source.crs.is_projected or source.crs.linear_units != "metre":
            reject("A single-band raster in a metre-based projected CRS is required")
        if source.width * source.height > 262144:
            reject("Raster exceeds the cell budget", "resource_limit")
        if any(not (source.bounds.left <= x < source.bounds.right and source.bounds.bottom < y <= source.bounds.top) for x, y in zip(xs, ys)):
            reject("All interpolated sample locations must lie within the raster")
        if source.units[0] and source.units[0] != args["value_unit"]:
            reject("Declared measurement unit conflicts with the raster band unit")
        sampled = list(source.sample(list(zip(xs, ys)), indexes=1, masked=True))
        if any(np.ma.is_masked(value) for value in sampled):
            reject("The cross-section intersects nodata cells")
        values = _finite([value[0] for value in sampled]).tolist()
    return {"x": xs, "y": ys, "distance": distances, "values": values,
            "units": {"x": "m", "y": "m", "distance": "m", "values": args["value_unit"]},
            "sampling": "Original EarthSim int(length/resolution) sample count with inclusive linspace endpoints; spacing can differ from requested resolution."}


@operation("EarthERA5LocalMonthlyClimate")
def era5_local_monthly_climate(args):
    import numpy as np
    import pandas as pd
    import xarray as xr
    from .vendor.era5_kernel import monthly_climate
    path = _path(args["netcdf_path"], {".nc"})
    with xr.open_dataset(path, engine="scipy") as source:
        variable = args["variable"]
        if variable not in source or set(source[variable].dims) != {"time", "latitude", "longitude"}:
            reject("The selected variable must have only time, latitude and longitude dimensions")
        if source[variable].attrs.get("units") != args["value_unit"]:
            reject("Explicit value_unit must match the original NetCDF variable unit")
        if source[variable].size > 262144 or not 12 <= source.sizes["time"] <= 1200:
            reject("Monthly source exceeds the bounded dimensions", "resource_limit")
        times = pd.DatetimeIndex(source.time.values)
        periods = times.to_period("M")
        if times.hasnans or not times.is_monotonic_increasing or periods.has_duplicates:
            reject("Monthly source times must be unique and increasing")
        if len(periods) > 1 and not np.all(np.diff(periods.asi8) == 1):
            reject("Monthly source must not have missing months")
        for name, lower, upper in [("latitude", -90, 90), ("longitude", -180, 360)]:
            axis = _finite(source[name].values)
            if axis.ndim != 1 or not ((np.diff(axis) > 0).all() or (np.diff(axis) < 0).all()) or axis.min() < lower or axis.max() > upper:
                reject("Latitude/longitude must be finite unique monotonic one-dimensional geographic axes")
        _finite(source[variable].values)
        data = source[[variable]].load()
        climate, series = monthly_climate(data, variable, args["longitude"], args["latitude"])
        month_values = climate[variable].transpose("month", "latitude", "longitude")
        return {"months": climate.month.values.astype(int).tolist(), "monthly_mean": _finite(month_values.values).tolist(),
                "point_series": _finite(series.values).tolist(), "time": [str(t) for t in series.time.values.astype("datetime64[D]")],
                "selected_longitude": float(series.longitude), "selected_latitude": float(series.latitude),
                "units": {"monthly_mean": args["value_unit"], "point_series": args["value_unit"], "latitude": "degrees_north", "longitude": "degrees_east"},
                "scope": "Original local monthly climatological means and nearest grid-node extraction; values are not converted or annualized."}


@operation("EarthPangaeaGeographicGrid")
def pangaea_geographic_grid(args):
    import numpy as np
    import xarray as xr
    from .vendor.pangaea_kernel import LSMGridKernel
    path = _path(args["netcdf_path"], {".nc"})
    with xr.open_dataset(path, engine="scipy") as source:
        name = args["variable"]
        if "MAP_PROJ" in source.attrs or source.attrs.get("grid_mapping"):
            reject("This bounded operation accepts geographic grids only, not WRF/projected model grids")
        if name not in source or source[name].dims != ("y", "x") or "grid_mapping" in source[name].attrs:
            reject("Variable must be a two-dimensional geographic y,x grid without a projected grid mapping")
        if source[name].attrs.get("units") != args["value_unit"]:
            reject("Declared unit must match the original variable unit")
        lat, lon = _finite(source["lat"].values), _finite(source["lon"].values)
        if lat.ndim != 1 or lon.ndim != 1 or len(lat) < 2 or len(lon) < 2 or lat.min() < -90 or lat.max() > 90 or lon.min() < -180 or lon.max() > 360:
            reject("Expected bounded one-dimensional latitude and longitude coordinates")
        if not ((np.diff(lat) > 0).all() or (np.diff(lat) < 0).all()) or not (np.diff(lon) > 0).all():
            reject("Latitude must be strictly monotonic and longitude strictly increasing")
        _finite(source[name].values)
        grid = LSMGridKernel(source.load())
        grid.lon_to_180 = args["wrap_longitude"]
        lat_out, lon_out = grid.latlon
        values = grid._getvar(name, slice(None), slice(None))
        return {"latitude": _finite(lat_out).tolist(), "longitude": _finite(lon_out).tolist(), "values": _finite(values.values).tolist(),
                "center_longitude": grid.center[0], "center_latitude": grid.center[1], "rows_reversed": bool(grid.y_inverted),
                "units": {"latitude": "degrees_north", "longitude": "degrees_east", "values": args["value_unit"]},
                "scope": "Original Pangaea north-up grid alignment and optional longitude wrapping, not reprojection or interpolation."}


class _PolygonProxy:
    def __init__(self, geom):
        self.geom = geom

    @property
    def bounds(self):
        return self.geom.bounds

    def intersection(self, other):
        return self.geom.intersection(other)

    def get_data_window(self, *values):
        from .vendor.geonotebook_kernel import AnnotationWindowKernel
        return AnnotationWindowKernel.get_data_window(self, *values)


class _RasterProxy:
    def __init__(self, source):
        from shapely.geometry import box
        self.source = source
        self.crs = source.crs
        self.shape = box(*source.bounds)
        self.band_indexes = [1]
        self.nodata = source.nodata

    def index(self, x, y):
        return self.source.index(x, y)

    def get_data(self, window, **kwargs):
        from rasterio.windows import Window
        (row0, col0), (row1, col1) = window
        return self.source.read(1, window=Window.from_slices((row0, row1), (col0, col1)), masked=False)


@operation("EarthGeoNotebookPolygonSubset")
def geonotebook_polygon_subset(args):
    import numpy as np
    import rasterio
    from shapely.geometry import Polygon, box
    from .vendor.geonotebook_kernel import PolygonSubsetKernel
    path = _path(args["raster_path"], {".tif", ".tiff"})
    ring = _finite(args["polygon_ring"])
    if ring.ndim != 2 or ring.shape[1] != 2 or not 4 <= len(ring) <= 4096 or not np.array_equal(ring[0], ring[-1]):
        reject("Supply one closed WGS84 polygon exterior ring, without holes")
    polygon = Polygon(ring)
    if not polygon.is_valid or polygon.is_empty or polygon.area <= 0:
        reject("The polygon exterior must be valid with positive area")
    with rasterio.open(path) as source:
        if source.count != 1 or source.crs is None or source.crs.to_epsg() != 4326 or source.transform.b != 0 or source.transform.d != 0 or source.transform.a <= 0 or source.transform.e >= 0:
            reject("A single-band, north-up, unrotated WGS84 raster is required")
        if source.width * source.height > 262144 or source.nodata is None or not math.isfinite(source.nodata):
            reject("A bounded raster with finite explicit nodata is required")
        if not box(*source.bounds).contains(polygon):
            reject("The polygon must be fully inside the raster footprint")
        if source.units[0] and source.units[0] != args["value_unit"]:
            reject("Declared value unit conflicts with the raster band unit")
        subset = PolygonSubsetKernel.subset(_PolygonProxy(polygon), _RasterProxy(source))
        if subset.size > 262144 or subset.count() == 0:
            reject("Polygon subset contains no valid cells")
        _finite(subset.compressed())
        plain = subset.astype(float).filled(np.nan)
        values = [[None if not math.isfinite(float(value)) else float(value) for value in row] for row in plain]
        return {"values": values, "valid_cells": int(subset.count()), "mean": float(subset.mean()), "minimum": float(subset.min()), "maximum": float(subset.max()),
                "units": {"values": args["value_unit"], "mean": args["value_unit"], "minimum": args["value_unit"], "maximum": args["value_unit"]},
                "scope": "Original GeoNotebook all-touched polygon mask, single band and exterior ring only; no reprojection or hole support claimed."}


@operation("EarthHydroShareRasterBandRanges")
def hydroshare_raster_band_ranges(args):
    import hashlib
    path = _path(args["raster_path"], {".tif", ".tiff"})
    import rasterio
    with rasterio.open(path) as source:
        if source.width * source.height * source.count > 262144 or source.count > 16:
            reject("Raster exceeds the CPU acceptance bound", "resource_limit")
    fixed_profile = Path("/data/wangjian/earth-python-coverage101-offline-originals-20261022/revision-r3/hydroshare-profile.json")
    if not fixed_profile.is_file():
        reject("The fixed pre-provisioned HydroShare CPU profile is missing", "missing_dependency")
    profile = json.loads(fixed_profile.read_text())
    python = Path(profile["python"])
    expected_python = fixed_profile.parent / "hydroshare-venv" / "bin" / "python"
    worker = Path(__file__).with_name("hydroshare_worker.py")
    kernel = Path(__file__).with_name("vendor") / "hydroshare_kernel.py"
    def digest(file):
        return hashlib.sha256(file.read_bytes()).hexdigest()
    if python != expected_python or not python.is_file() or digest(python) != profile["python_sha256"]:
        reject("The fixed native CPU interpreter identity changed", "invalid_result")
    if profile["packages"] != {"GDAL": "3.13.3", "numpy": "2.2.6"}:
        reject("Native GDAL/NumPy pins differ from the reviewed profile", "missing_dependency")
    if digest(worker) != profile["worker_sha256"] or digest(kernel) != profile["kernel_sha256"]:
        reject("The fixed worker or original source-kernel identity changed", "invalid_result")
    if digest(Path(profile["proj_data"]) / "proj.db") != profile["proj_database_sha256"]:
        reject("The reviewed native PROJ database identity changed", "invalid_result")
    with tempfile.TemporaryDirectory(prefix="hydroshare-raster-") as directory:
        snapshot = Path(directory) / "input.tif"
        shutil.copyfile(path, snapshot)
        private = Path(directory) / "cache"
        for folder in ["matplotlib", "numba", "xdg", "home", "tmp"]:
            (private / folder).mkdir(parents=True)
        environment = {"PATH": str(python.parent) + ":/usr/bin:/bin", "LANG": "C.UTF-8", "MPLCONFIGDIR": str(private / "matplotlib"),
                       "NUMBA_CACHE_DIR": str(private / "numba"), "XDG_CACHE_HOME": str(private / "xdg"), "HOME": str(private / "home"), "TMPDIR": str(private / "tmp"),
                       "CUDA_VISIBLE_DEVICES": "", "NVIDIA_VISIBLE_DEVICES": "none", "PROJ_NETWORK": "OFF", "GDAL_PAM_ENABLED": "NO", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
                       "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false", "GEOTOOL_LANGSMITH_ENABLED": "0", "PYTHONIOENCODING": "utf-8",
                       "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1", "GDAL_NUM_THREADS": "1", "NUMBA_NUM_THREADS": "1",
                       "PROJ_DATA": profile["proj_data"], "PROJ_LIB": profile["proj_data"], "GDAL_DATA": profile["gdal_data"]}
        completed = subprocess.run([str(python), str(worker), str(snapshot)], cwd=directory, env=environment, capture_output=True, text=True, timeout=90, check=False)
        if completed.returncode:
            reject("The isolated original HydroShare statistics worker failed; exit=" + str(completed.returncode), "upstream_failure")
        receipt = json.loads(completed.stdout)
        if receipt["native_environment"]["packages"] != profile["packages"] or receipt["native_environment"]["kernel_sha256"] != profile["kernel_sha256"]:
            reject("Native result evidence does not match the fixed source/profile", "invalid_result")
        if receipt["input_sha256_before"] != receipt["input_sha256_after"] or receipt["input_sha256_before"] != digest(path):
            reject("Native statistics changed its source snapshot", "invalid_result")
        bands = receipt["bands"]
    for band in bands.values():
        if band["minimumValue"] is None or band["maximumValue"] is None or not math.isfinite(band["minimumValue"]) or not math.isfinite(band["maximumValue"]):
            reject("All bands must produce finite original GDAL statistics", "invalid_result")
        if band["variableUnit"] != args["value_unit"]:
            reject("Declared value unit must equal the preserved native band unit")
    return {"bands": bands, "native_environment": receipt["native_environment"], "units": {"minimumValue": args["value_unit"], "maximumValue": args["value_unit"]},
            "scope": "Original HydroShare GDAL band min/max on an isolated input snapshot; no service, database, or cloud resource is contacted."}


"""Bounded CPU adapters. Source-ready only until independent coordinator acceptance."""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
from types import SimpleNamespace

from .collection_contracts import operation, reject

_MAX_BYTES = 8 * 1024 * 1024
_DATA_UNITS = ("1", "K", "degC", "Pa", "hPa", "m", "m/s", "m/s2", "mm/h", "mm/day", "counts")


def _fail(message):
    reject(message, code="invalid_arguments")


def _number(value, label, lower=-1e12, upper=1e12):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(label + " must be a finite number.")
    try:
        valid = math.isfinite(value) and lower <= value <= upper
    except (OverflowError, TypeError):
        valid = False
    if not valid:
        _fail(label + " is outside its finite permitted range.")
    return float(value)


def _integer(value, label, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        _fail(label + " must be an integer in the permitted range.")
    return value


def _vector(value, label, minimum=1, maximum=4096, lower=-1e6, upper=1e6):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        _fail(label + " has an invalid number of entries.")
    return [_number(v, label, lower, upper) for v in value]


def _same(*vectors):
    if len({len(v) for v in vectors}) != 1:
        _fail("Related input arrays must have identical lengths.")


def _unit(args):
    value = args.get("data_unit")
    if value not in _DATA_UNITS:
        _fail("data_unit must be an explicitly supported physical unit.")
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonfinite JSON constant")


def _load(args, required):
    raw_path = args.get("data_path")
    if not isinstance(raw_path, str) or not raw_path:
        _fail("data_path must identify a JSON input snapshot.")
    source = Path(raw_path)
    try:
        if source.suffix.lower() != ".json" or not source.is_file():
            _fail("data_path must be an existing JSON input file.")
        with source.open("rb") as handle:
            data = handle.read(_MAX_BYTES + 1)
        if len(data) > _MAX_BYTES:
            _fail("JSON input exceeds the 8 MiB limit.")
        value = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_pairs,
                           parse_constant=_constant)
    except (OSError, UnicodeError, ValueError, RecursionError):
        _fail("Input must be readable finite UTF-8 JSON with unique object keys.")
    if not isinstance(value, dict):
        _fail("JSON input must be an object.")
    allowed = set(required) | {"synthetic", "fixture_id"}
    if set(value) - allowed or not set(required) <= set(value):
        _fail("JSON input has missing or unsupported fields.")
    if "synthetic" in value and type(value["synthetic"]) is not bool:
        _fail("synthetic must be a boolean.")
    if "fixture_id" in value and (not isinstance(value["fixture_id"], str) or len(value["fixture_id"]) > 80):
        _fail("fixture_id must be a short label.")
    return value


def _flat_grid(value, rank_min=1, rank_max=3, limit=262144, axis_min=1, axis_max=512):
    shape = value["shape"]
    if not isinstance(shape, list) or not rank_min <= len(shape) <= rank_max:
        _fail("shape has an unsupported rank.")
    shape = [_integer(n, "shape extent", axis_min, axis_max) for n in shape]
    size = math.prod(shape)
    if size > limit:
        _fail("shape exceeds the cell limit.")
    flat = _vector(value["values"], "values", minimum=size, maximum=size)
    return shape, flat


@operation("WrfDestaggerGrid")
def wrf_destagger_grid(args, output_dir=None):
    payload = _load(args, ("shape", "values"))
    shape, flat = _flat_grid(payload)
    axis = _integer(args.get("stagger_dim"), "stagger_dim", -len(shape), len(shape) - 1)
    axis %= len(shape)
    if shape[axis] < 2:
        _fail("The staggered axis must contain at least two cells.")
    unit = _unit(args)
    import numpy as np
    from .collection_vendor.weather_climate_seismic.wrf_destag import destagger
    result = destagger(np.asarray(flat, dtype=np.float64).reshape(shape), axis, meta=False)
    return {"shape": list(result.shape), "values": result.ravel().tolist(),
            "units": {"shape": "count", "values": unit}}


@operation("RainymotionPrecipitationScores")
def rainymotion_precipitation_scores(args, output_dir=None):
    p = _load(args, ("observed_mm_h", "forecast_mm_h"))
    observed = _vector(p["observed_mm_h"], "observed_mm_h", maximum=65536, lower=0, upper=10000)
    forecast = _vector(p["forecast_mm_h"], "forecast_mm_h", maximum=65536, lower=0, upper=10000)
    _same(observed, forecast)
    threshold = _number(args.get("threshold_mm_h", 0.1), "threshold_mm_h", 0.000001, 10000)
    import numpy as np
    from .collection_vendor.weather_climate_seismic import rainymotion_metrics as m
    observed, forecast = np.asarray(observed), np.asarray(forecast)
    hits, misses, false_alarms, correct_negatives = map(
        int, m.prep_clf(observed, forecast, threshold))
    hss_den = (misses ** 2 + false_alarms ** 2 + 2 * hits * correct_negatives
               + (misses + false_alarms) * (hits + correct_negatives))
    return {
        "rmse": float(m.RMSE(observed, forecast)),
        "mae": float(m.MAE(observed, forecast)),
        "csi": float(m.CSI(observed, forecast, threshold)) if hits + misses + false_alarms else None,
        "false_alarm_ratio": float(m.FAR(observed, forecast, threshold)) if hits + false_alarms else None,
        "probability_of_detection": float(m.POD(observed, forecast, threshold)) if hits + misses else None,
        "heidke_skill_score": float(m.HSS(observed, forecast, threshold)) if hss_den else None,
        "contingency": {"hits": hits, "misses": misses, "false_alarms": false_alarms,
                        "correct_negatives": correct_negatives},
        "units": {"rmse": "mm/h", "mae": "mm/h", "csi": "1",
                  "false_alarm_ratio": "1", "probability_of_detection": "1",
                  "heidke_skill_score": "1", "contingency": "count"}}


@operation("MetSimPotentialEvapotranspiration")
def metsim_potential_evapotranspiration(args, output_dir=None):
    p = _load(args, ("shortwave_w_m2", "temperature_degC", "daylength_s"))
    rad = _vector(p["shortwave_w_m2"], "shortwave_w_m2", lower=0, upper=1500)
    temp = _vector(p["temperature_degC"], "temperature_degC", lower=-50, upper=60)
    dayl = _vector(p["daylength_s"], "daylength_s", lower=0, upper=86400)
    _same(rad, temp, dayl)
    pressure = _number(args.get("pressure_pa"), "pressure_pa", 30000, 110000)
    import numpy as np
    from .collection_vendor.weather_climate_seismic.metsim_pet import calc_pet
    result = calc_pet(np.asarray(rad), np.asarray(temp), np.asarray(dayl), pressure)
    return {"potential_evapotranspiration": result.tolist(),
            "units": {"potential_evapotranspiration": "cm/day"}}


@operation("MelodistDailyPrecipitationToHourly")
def melodist_daily_precipitation_to_hourly(args, output_dir=None):
    p = _load(args, ("daily_precipitation_mm",))
    daily = _vector(p["daily_precipitation_mm"], "daily_precipitation_mm",
                    maximum=366, lower=0, upper=5000)
    start = args.get("start_date")
    try:
        date = dt.date.fromisoformat(start)
        if date.isoformat() != start or not 1900 <= date.year <= 2100:
            raise ValueError()
    except (ValueError, TypeError):
        _fail("start_date must be a calendar date YYYY-MM-DD in 1900..2100.")
    import pandas as pd
    from .collection_vendor.weather_climate_seismic.melodist_equal import distribute_equally
    data = pd.Series(daily, index=pd.date_range(date.isoformat(), periods=len(daily), freq="D"))
    result = distribute_equally(data, divide=True)
    return {"timestamps": [t.isoformat() for t in result.index],
            "hourly_precipitation": result.tolist(),
            "units": {"timestamps": "ISO8601; naive fixed 24-hour calendar day",
                      "hourly_precipitation": "mm per 1-hour interval"}}


@operation("ImproverRescaleForecastField")
def improver_rescale_forecast_field(args, output_dir=None):
    p = _load(args, ("values",))
    values = _vector(p["values"], "values", maximum=65536)
    source_range = _vector(args.get("data_range"), "data_range", minimum=2, maximum=2)
    target_range = _vector(args.get("scale_range", [0, 1]), "scale_range", minimum=2, maximum=2)
    if source_range[1] - source_range[0] < 0.000001 or target_range[0] == target_range[1]:
        _fail("data_range must increase by at least 1e-6 and scale_range endpoints must differ.")
    clip = args.get("clip", False)
    if type(clip) is not bool:
        _fail("clip must be a boolean.")
    import numpy as np
    from .collection_vendor.weather_climate_seismic.improver_rescale import rescale
    result = rescale(np.asarray(values), data_range=source_range, scale_range=target_range, clip=clip)
    return {"scaled_values": result.tolist(), "units": {"scaled_values": "1"}}


@operation("SkdownscaleQuantileBiasCorrection")
def skdownscale_quantile_bias_correction(args, output_dir=None):
    p = _load(args, ("historical_model", "historical_observed", "future_model"))
    model = _vector(p["historical_model"], "historical_model", minimum=5)
    observed = _vector(p["historical_observed"], "historical_observed", minimum=5)
    future = _vector(p["future_model"], "future_model")
    _same(model, observed)
    if len(set(model)) < 2 or len(set(observed)) < 2:
        _fail("Both calibration series must contain at least two distinct values.")
    unit = _unit(args)
    import numpy as np
    from .collection_vendor.weather_climate_seismic.skdownscale_quantile import QuantileMappingReressor
    estimator = QuantileMappingReressor(extrapolate=None, n_endpoints=2)
    estimator.fit(np.asarray(model).reshape(-1, 1), np.asarray(observed))
    corrected = estimator.predict(np.asarray(future).reshape(-1, 1))
    return {"corrected_values": corrected.tolist(),
            "units": {"corrected_values": unit}}


@operation("JamsDewPoint")
def jams_dew_point(args, output_dir=None):
    p = _load(args, ("vapour_pressure_pa",))
    pressure = _vector(p["vapour_pressure_pa"], "vapour_pressure_pa", lower=0.01, upper=100000)
    unit = args.get("output_unit", "degC")
    if unit not in ("degC", "K"):
        _fail("output_unit must be degC or K.")
    import numpy as np
    from .collection_vendor.weather_climate_seismic.jams_dewpoint import dewpoint
    result = dewpoint(np.asarray(pressure), Celsius=True)
    if unit == "K":
        result = result + 273.15
    return {"dew_point": result.tolist(), "units": {"dew_point": unit}}


@operation("XgcmStaggeredGridDiagnostics")
def xgcm_staggered_grid_diagnostics(args, output_dir=None):
    p = _load(args, ("values",))
    values = _vector(p["values"], "values", minimum=2, maximum=65536)
    spacing = _number(args.get("spacing_m"), "spacing_m", 0.000001, 1e7)
    unit = _unit(args)
    import numpy as np
    import xarray as xr
    from xgcm import Grid
    data = xr.Dataset({"field": ("x", np.asarray(values))},
                      coords={"x": np.arange(len(values)) * spacing,
                              "x_inner": (np.arange(len(values) - 1) + 0.5) * spacing})
    grid = Grid(data, coords={"X": {"center": "x", "inner": "x_inner"}},
                periodic=False, autoparse_metadata=False)
    midpoint = grid.interp(data["field"], "X", to="inner")
    gradient = grid.diff(data["field"], "X", to="inner") / spacing
    return {"interpolated_values": midpoint.values.tolist(),
            "gradient": gradient.values.tolist(),
            "units": {"interpolated_values": unit, "gradient": "(" + unit + ")/m"}}


@operation("ClimpredEnsembleCrps")
def climpred_ensemble_crps(args, output_dir=None):
    p = _load(args, ("forecast", "observed"))
    rows = p["forecast"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 4096:
        _fail("forecast must contain 1..4096 sample rows.")
    if not isinstance(rows[0], list):
        _fail("Each forecast row must be an ensemble-member array.")
    members = len(rows[0])
    if not 1 <= members <= 64 or len(rows) * members > 65536:
        _fail("The ensemble exceeds its member or total-value limit.")
    forecast = [_vector(row, "forecast row", minimum=members, maximum=members) for row in rows]
    observed = _vector(p["observed"], "observed", minimum=len(rows), maximum=len(rows))
    unit = _unit(args)
    import numpy as np
    import xarray as xr
    from climpred.metrics import _crps
    prediction = xr.DataArray(np.asarray(forecast), dims=("sample", "member"))
    verification = xr.DataArray(np.asarray(observed), dims=("sample",))
    sample_scores = _crps(prediction, verification, dim=["member"])
    mean_score = _crps(prediction, verification, dim=["member", "sample"])
    return {"sample_crps": sample_scores.values.tolist(), "mean_crps": float(mean_score),
            "units": {"sample_crps": unit, "mean_crps": unit}}


@operation("ClimlabLayerHeatCapacity")
def climlab_layer_heat_capacity(args, output_dir=None):
    p = _load(args, ("thickness",))
    thickness = _vector(p["thickness"], "thickness", lower=0.000001, upper=12000)
    medium = args.get("medium")
    unit = args.get("thickness_unit")
    if (medium, unit) not in (("atmosphere", "hPa"), ("ocean", "m")):
        _fail("Use atmosphere with hPa, or ocean with m.")
    if medium == "atmosphere" and max(thickness) > 1100:
        _fail("Atmospheric pressure thickness cannot exceed 1100 hPa.")
    import numpy as np
    from .collection_vendor.weather_climate_seismic import climlab_capacity
    result = getattr(climlab_capacity, medium)(np.asarray(thickness))
    return {"areal_heat_capacity": result.tolist(),
            "units": {"areal_heat_capacity": "J/(m2 K)"}}


@operation("AospyHybridPressure")
def aospy_hybrid_pressure(args, output_dir=None):
    p = _load(args, ("sigma_b", "pressure_a_pa", "surface_pressure_pa"))
    sigma = _vector(p["sigma_b"], "sigma_b", minimum=2, maximum=256, lower=0, upper=1)
    offset = _vector(p["pressure_a_pa"], "pressure_a_pa", minimum=2, maximum=256, lower=0, upper=110000)
    surface = _vector(p["surface_pressure_pa"], "surface_pressure_pa", maximum=256, lower=10000, upper=110000)
    _same(sigma, offset)
    for ps in surface:
        pressure = [ps * b + a for a, b in zip(offset, sigma)]
        if max(pressure) > ps + 1e-6 or any(b <= a for a, b in zip(pressure, pressure[1:])):
            _fail("Hybrid half-levels must increase from top to surface and not exceed surface pressure.")
    import numpy as np
    from .collection_vendor.weather_climate_seismic.aospy_hybrid import phalf_from_ps
    result = phalf_from_ps(np.asarray(sigma)[None, :], np.asarray(offset)[None, :],
                          np.asarray(surface)[:, None])
    return {"half_level_pressure": result.tolist(), "units": {"half_level_pressure": "Pa"}}


@operation("OocgcmSurfaceSpiciness")
def oocgcm_surface_spiciness(args, output_dir=None):
    p = _load(args, ("potential_temperature_degC", "salinity_psu"))
    temp = _vector(p["potential_temperature_degC"], "potential_temperature_degC", lower=-2, upper=40)
    salinity = _vector(p["salinity_psu"], "salinity_psu", lower=0, upper=42)
    _same(temp, salinity)
    import numpy as np
    from .collection_vendor.weather_climate_seismic.oocgcm_spice import _spice
    result = _spice(np.asarray(temp), np.asarray(salinity))
    return {"spiciness": result.tolist(), "units": {"spiciness": "kg/m3"}}


@operation("OcgisHeatIndex")
def ocgis_heat_index(args, output_dir=None):
    p = _load(args, ("temperature_degF", "relative_humidity_percent"))
    temp = _vector(p["temperature_degF"], "temperature_degF", lower=-100, upper=150)
    humidity = _vector(p["relative_humidity_percent"], "relative_humidity_percent", lower=0, upper=100)
    _same(temp, humidity)
    import numpy as np
    from .collection_vendor.weather_climate_seismic.ocgis_heat_index import HeatIndexKernel
    result = HeatIndexKernel().calculate(np.ma.array(temp, mask=False, copy=True),
                                        np.ma.array(humidity, mask=False, copy=True))
    return {"heat_index": result.tolist(), "valid": (~np.ma.getmaskarray(result)).tolist(),
            "units": {"heat_index": "degF", "valid": "1"}}


@operation("PyrockoDoubleCoupleTensor")
def pyrocko_double_couple_tensor(args, output_dir=None):
    p = _load(args, ("strike_deg", "dip_deg", "rake_deg", "scalar_moment_nm"))
    strike = _number(p["strike_deg"], "strike_deg", 0, 360)
    dip = _number(p["dip_deg"], "dip_deg", 0, 90)
    rake = _number(p["rake_deg"], "rake_deg", -180, 180)
    scalar = _number(p["scalar_moment_nm"], "scalar_moment_nm", 1e3, 1e25)
    from pyrocko.moment_tensor import MomentTensor, moment_to_magnitude
    tensor = MomentTensor(strike=strike, dip=dip, rake=rake, scalar_moment=scalar)
    return {"tensor_ned": tensor.m().tolist(), "scalar_moment": float(tensor.scalar_moment()),
            "moment_magnitude": float(moment_to_magnitude(scalar)),
            "units": {"tensor_ned": "N m; axes north,east,down", "scalar_moment": "N m",
                      "moment_magnitude": "Mw (Hanks-Kanamori 1979; offset 10.7)"}}


@operation("RsudpWindowAmplitude")
def rsudp_window_amplitude(args, output_dir=None):
    p = _load(args, ("samples",))
    samples = _vector(p["samples"], "samples", maximum=65536)
    unit = _unit(args)
    if unit not in ("counts", "m", "m/s", "m/s2", "Pa"):
        _fail("RSAM units must be counts, m, m/s, m/s2, or Pa.")
    sample_rate = _number(args.get("sample_rate_hz"), "sample_rate_hz", 0.001, 10000)
    from .collection_vendor.weather_climate_seismic.rsudp_rsam import RSAMKernel
    kernel = RSAMKernel()
    kernel.stream = [SimpleNamespace(data=samples)]
    kernel._rsam()
    mean, median, minimum, maximum = map(float, kernel.rsam)
    return {"mean_absolute_amplitude": mean, "median_absolute_amplitude": median,
            "minimum_absolute_amplitude": minimum, "maximum_absolute_amplitude": maximum,
            "duration": len(samples) / sample_rate,
            "units": {"mean_absolute_amplitude": unit, "median_absolute_amplitude": unit,
                      "minimum_absolute_amplitude": unit, "maximum_absolute_amplitude": unit,
                      "duration": "s"}}


@operation("SeismicZfpCompressCube")
def seismic_zfp_compress_cube(args, output_dir=None):
    p = _load(args, ("shape", "values"))
    shape, flat = _flat_grid(p, rank_min=3, rank_max=3, limit=32768, axis_min=4, axis_max=512)
    if shape[0] > 64 or shape[1] > 64:
        _fail("Inline and crossline dimensions cannot exceed 64.")
    unit = _unit(args)
    interval = _integer(args.get("sample_interval_ms"), "sample_interval_ms", 1, 100)
    if output_dir is None:
        _fail("A managed output directory is required.")
    directory = Path(output_dir)
    if not directory.is_dir():
        _fail("The managed output directory must already exist.")
    destination = directory / "cube.sgz"
    if destination.exists():
        _fail("The managed cube output must not already exist.")
    import numpy as np
    from seismic_zfp.conversion import NumpyConverter
    from seismic_zfp.read import SgzReader
    data = np.asarray(flat, dtype=np.float32).reshape(shape)
    samples = np.arange(shape[2], dtype=np.float32) * interval
    with NumpyConverter(data, samples=samples, trace_headers={}) as converter:
        converter.run(str(destination), bits_per_voxel=16, blockshape=(4, 4, -1))
    with SgzReader(str(destination)) as reader:
        decoded = reader.read_subvolume(0, shape[0], 0, shape[1], 0, shape[2], multithreading=False)
    if decoded.shape != tuple(shape) or not np.isfinite(decoded).all():
        raise ValueError("SGZ engine returned invalid decoded values.")
    error = decoded.astype(np.float64) - data.astype(np.float64)
    return {"relative_path": "cube.sgz", "shape": shape,
            "decoded_values": decoded.ravel().tolist(),
            "max_absolute_error": float(np.max(np.abs(error))),
            "rms_error": float(np.sqrt(np.mean(error * error))),
            "compressed_bytes": destination.stat().st_size, "sample_interval": interval,
            "units": {"relative_path": "1", "shape": "count", "decoded_values": unit,
                      "max_absolute_error": unit, "rms_error": unit,
                      "compressed_bytes": "byte", "sample_interval": "ms"}}

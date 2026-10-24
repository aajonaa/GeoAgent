"""Small, deterministic adapters for the first GitHub tool intake batch.

Each function deliberately exposes one bounded operation from an upstream
package.  Catalog registration owns the public JSON schemas; this module only
normalizes inputs, calls the pinned package API, and returns JSON values.
"""
from __future__ import annotations

import math
from pathlib import Path
from legacy.ToolsAgent.ToolsFuns.source_contracts import decode
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError

# Largest measured Rs/Rso accepted by HydroReferenceET0 before rejection.
RS_RSO_TOLERANCE = 1.05


def _arguments(value):
    """Accept the source entrypoint's object form and JSON-object form."""
    value = decode(value)
    if not isinstance(value, dict):
        raise TypeError("Tool arguments must be a JSON object")
    return value


def _numbers(args, names):
    values = []
    for name in names:
        value = args[name]
        if not isinstance(value, list) or not value:
            raise ValueError(f"{name} must be a nonempty array")
        if not all(isinstance(x, (int, float)) and math.isfinite(float(x)) for x in value):
            raise ValueError(f"{name} must contain finite numbers")
        values.append(value)
    if len({len(value) for value in values}) != 1:
        raise ValueError("Input arrays must have equal lengths")
    return values


def verde_grid(args):
    args = _arguments(args)
    import numpy as np
    import verde as vd

    east, north, value = _numbers(args, ("easting", "northing", "values"))
    xmin, xmax, ymin, ymax = args["region"]
    nx, ny = args["shape"]
    if not all(isinstance(item, (int, float)) and math.isfinite(float(item))
               for item in (xmin, xmax, ymin, ymax)):
        raise ValueError("region must contain finite numbers")
    if not all(isinstance(item, int) and not isinstance(item, bool) for item in (nx, ny)):
        raise ValueError("shape must contain integers")
    if not xmin < xmax or not ymin < ymax:
        raise ValueError("region must be ordered xmin,xmax,ymin,ymax")
    if nx < 2 or ny < 2:
        raise ValueError("shape must contain at least two cells per axis")
    damping = args.get("damping")
    if damping is not None and (not isinstance(damping, (int, float)) or not math.isfinite(float(damping)) or damping < 0):
        raise ValueError("damping must be a finite nonnegative number")
    model = vd.Spline(damping=damping)
    model.fit((np.asarray(east), np.asarray(north)), np.asarray(value))
    coordinates = vd.grid_coordinates((xmin, xmax, ymin, ymax), shape=(ny, nx))
    grid = np.asarray(model.predict(coordinates), dtype=float)
    return {"method": "verde_spline", "shape": [int(nx), int(ny)],
            "region": [float(xmin), float(xmax), float(ymin), float(ymax)],
            "grid": grid.tolist(), "min": float(np.nanmin(grid)),
            "max": float(np.nanmax(grid))}


def region_mask(args):
    args = _arguments(args)
    import numpy as np
    import xarray as xr
    import regionmask

    lon, lat = _numbers(args, ("longitude", "latitude"))
    region_name = args["region_set"]
    if region_name != "srex":
        raise ScientificToolError("invalid_arguments", "region_set must be srex; Natural Earth layers are not available in this offline adapter")
    regions = regionmask.defined_regions.srex
    # Plain arrays are interpreted by regionmask as independent longitude and
    # latitude axes.  Give both arrays the same xarray dimension so each input
    # longitude is paired with the latitude at the same index.
    masked = regions.mask(xr.DataArray(np.asarray(lon), dims=("point",)),
                          xr.DataArray(np.asarray(lat), dims=("point",)))
    result = []
    for value in np.asarray(masked):
        result.append(None if not np.isfinite(value) else int(value))
    return {"region_set": region_name, "region_ids": result,
            "inside_count": sum(value is not None for value in result)}


def hydro_error_metrics(args):
    args = _arguments(args)
    import HydroErr
    observed, simulated = _numbers(args, ("observed", "simulated"))
    available = {
        "nse": HydroErr.nse, "rmse": HydroErr.rmse, "mae": HydroErr.mae,
        "kge_2009": HydroErr.kge_2009, "pearson_r": HydroErr.pearson_r,
    }
    metrics = args.get("metrics", list(available))
    unknown = sorted(set(metrics) - set(available))
    if unknown:
        raise ValueError("Unsupported HydroErr metrics: " + ", ".join(unknown))
    result = {}
    for name in metrics:
        try:
            value = available[name](simulated, observed)
        except Exception as exc:
            raise ValueError(f"HydroErr {name} failed: {exc}") from exc
        result[name] = float(value) if math.isfinite(float(value)) else None
    return {"metrics": result, "sample_count": len(observed)}


def scientific_curve_fit(args):
    args = _arguments(args)
    import numpy as np
    from lmfit import Model

    x, y = _numbers(args, ("x", "y"))
    model_name = args["model"]
    if model_name == "linear":
        def function(x, slope, intercept):
            return slope * x + intercept
        params = {"slope": args.get("initial", {}).get("slope", 1.0),
                  "intercept": args.get("initial", {}).get("intercept", 0.0)}
    elif model_name == "exponential":
        def function(x, amplitude, decay):
            return amplitude * np.exp(decay * x)
        params = {"amplitude": args.get("initial", {}).get("amplitude", 1.0),
                  "decay": args.get("initial", {}).get("decay", 0.0)}
    else:
        raise ValueError("model must be linear or exponential")
    lm_model = Model(function)
    fit_params = lm_model.make_params(**params)
    for name, bounds in args.get("bounds", {}).items():
        if name in fit_params:
            if "min" in bounds:
                fit_params[name].min = bounds["min"]
            if "max" in bounds:
                fit_params[name].max = bounds["max"]
    result = lm_model.fit(np.asarray(y), fit_params, x=np.asarray(x), nan_policy="raise", max_nfev=args.get("max_nfev", 2000))
    return {"model": model_name, "parameters": {name: float(par.value) for name, par in result.params.items()},
            "rmse": float(np.sqrt(np.mean(np.square(result.residual)))),
            "aic": float(result.aic), "success": bool(result.success),
            "sample_count": len(x)}


def hydrointerp_grid(args):
    args = _arguments(args)
    import numpy as np
    import pandas as pd
    from hydrointerp import Interp

    east, north, value = _numbers(args, ("easting", "northing", "values"))
    if not args.get("crs"):
        raise ValueError("crs is required by hydrointerp; use an explicit CRS such as EPSG:4326")
    xmin, xmax, ymin, ymax = args["region"]
    if not all(isinstance(item, (int, float)) and math.isfinite(float(item))
               for item in (xmin, xmax, ymin, ymax)) or not xmin < xmax or not ymin < ymax:
        raise ValueError("region must contain finite ordered bounds")
    if not isinstance(args["resolution"], (int, float)) or not math.isfinite(float(args["resolution"])) or args["resolution"] <= 0:
        raise ValueError("resolution must be a finite positive number")
    frame = pd.DataFrame({"time": [args.get("time", "2000-01-01")] * len(east),
                         "x": east, "y": north,
                         # Hydrointerp allocates its result with this dtype;
                         # integer measurements must retain fractional results.
                         "value": np.asarray(value, dtype=float)})
    interp = Interp(point_data=frame, point_time_name="time", point_x_name="x",
                    point_y_name="y", point_data_name="value",
                    point_crs=args.get("crs"))
    dataset = interp.points_to_grid(args["resolution"], bbox=(xmin, xmax, ymin, ymax),
                                    method=args.get("method", "linear"),
                                    extrapolation=args.get("extrapolation", "nearest"),
                                    fill_val=float("nan"), digits=8)
    values = np.asarray(dataset["precip"].isel(time=0), dtype=float)
    return {"method": args.get("method", "linear"), "crs": args.get("crs"),
            "x": np.asarray(dataset.x).tolist(), "y": np.asarray(dataset.y).tolist(),
            "grid": np.where(np.isfinite(values), values, None).tolist(),
            "shape": [int(values.shape[1]), int(values.shape[0])]}


def metpy_wind_components(args):
    args = _arguments(args)
    import numpy as np
    from metpy.calc import wind_components
    from metpy.units import units

    speed_values, direction_values = _numbers(args, ("speed", "direction"))
    if any(value < 0 for value in speed_values):
        raise ValueError("speed must be nonnegative")
    speed = np.asarray(speed_values, dtype=float) * units(args.get("speed_unit", "m/s"))
    direction = np.asarray(direction_values, dtype=float) * units.deg
    u, v = wind_components(speed, direction)
    return {"u": u.to("m/s").magnitude.tolist(), "v": v.to("m/s").magnitude.tolist(),
            "coordinate_convention": "meteorological_from_direction", "count": int(speed.size)}


def seismic_reflectivity(args):
    args = _arguments(args)
    import numpy as np
    from bruges.reflection import acoustic_reflectivity

    vp, rho = _numbers(args, ("vp", "density"))
    if any(value <= 0 for value in vp + rho):
        raise ValueError("vp and density must be positive")
    values = acoustic_reflectivity(np.asarray(vp), np.asarray(rho), mode="valid")
    return {"method": "bruges_acoustic_reflectivity", "coefficients": np.asarray(values, dtype=float).tolist(),
            "count": len(values), "input_count": len(vp)}


def segy_summary(args):
    args = _arguments(args)
    import numpy as np
    import segyio

    preview_traces = args.get("preview_traces", 3)
    if not isinstance(preview_traces, int) or isinstance(preview_traces, bool) or not 1 <= preview_traces <= 20:
        raise ValueError("preview_traces must be an integer from 1 to 20")
    path = Path(args["segy_path"])
    if not path.is_file():
        raise FileNotFoundError(str(path))
    with segyio.open(str(path), "r", ignore_geometry=True) as handle:
        trace_count = len(handle.trace)
        sample_count = len(handle.samples)
        if sample_count * min(trace_count, preview_traces) > 1_000_000:
            raise ScientificToolError("resource_limit", "SEG-Y preview exceeds one million samples")
        preview = np.asarray(handle.trace.raw[: min(trace_count, preview_traces)], dtype=float)
        return {"trace_count": int(trace_count), "sample_count": int(sample_count),
                "sample_interval_us": float(handle.bin[segyio.BinField.Interval]),
                "trace_mean_preview": np.mean(preview, axis=1).tolist() if preview.size else []}


def reference_et0(args):
    args = _arguments(args)
    import pyeto

    required = ("tmin_c", "tmax_c", "rh_min", "rh_max", "wind_m_s", "solar_mj_m2", "latitude_deg", "day_of_year")
    values = {name: args[name] for name in required}
    finite = ("tmin_c", "tmax_c", "rh_min", "rh_max", "wind_m_s", "solar_mj_m2", "latitude_deg", "altitude_m")
    values["altitude_m"] = args.get("altitude_m", 0)
    if any(not isinstance(values[name], (int, float)) or not math.isfinite(float(values[name])) for name in finite):
        raise ValueError("ET0 inputs must be finite numbers")
    if not isinstance(values["day_of_year"], int) or isinstance(values["day_of_year"], bool):
        raise ValueError("day_of_year must be an integer")
    if values["tmin_c"] > values["tmax_c"]:
        raise ValueError("tmin_c must not exceed tmax_c")
    if not 0 <= values["rh_min"] <= values["rh_max"] <= 100:
        raise ValueError("rh_min and rh_max must satisfy 0 <= rh_min <= rh_max <= 100")
    if not 0 <= values["wind_m_s"] or not 0 <= values["solar_mj_m2"]:
        raise ValueError("wind_m_s and solar_mj_m2 must be nonnegative")
    if not -90 <= values["latitude_deg"] <= 90:
        raise ValueError("latitude_deg must be in [-90, 90]")
    if not 1 <= values["day_of_year"] <= 366:
        raise ValueError("day_of_year must be in 1..366")
    latitude = pyeto.deg2rad(values["latitude_deg"])
    sol_dec = pyeto.sol_dec(values["day_of_year"])
    sha = pyeto.sunset_hour_angle(latitude, sol_dec)
    ra = pyeto.et_rad(latitude, sol_dec, sha, pyeto.inv_rel_dist_earth_sun(values["day_of_year"]))
    tmean = (values["tmin_c"] + values["tmax_c"]) / 2
    avp = pyeto.avp_from_rhmin_rhmax(pyeto.svp_from_t(values["tmin_c"]),
                                     pyeto.svp_from_t(values["tmax_c"]),
                                     values["rh_min"], values["rh_max"])
    # FAO-56 net radiation: net shortwave after albedo minus estimated net
    # outgoing longwave radiation.  Rs is measured incoming shortwave radiation;
    # it is not itself net radiation.
    net_shortwave = pyeto.net_in_sol_rad(values["solar_mj_m2"])
    clear_sky = pyeto.cs_rad(values.get("altitude_m", 0), ra)
    if not math.isfinite(clear_sky) or clear_sky <= 1e-12:
        raise ScientificToolError("unsupported_conditions", "FAO-56 longwave estimation requires positive clear-sky radiation; polar night is unsupported")
    # FAO-56 Eq. 39 limits Rs/Rso to 1.0. Rso is itself an estimate, so clear
    # days can measure slightly above it: limit the ratio within a small
    # tolerance and report that, but reject larger excesses as likely unit or
    # observation errors.
    ratio = values["solar_mj_m2"] / clear_sky
    if ratio > RS_RSO_TOLERANCE:
        raise ScientificToolError("invalid_arguments", f"solar_mj_m2 exceeds FAO-56 clear-sky radiation (Rs/Rso > {RS_RSO_TOLERANCE}); check radiation units and observations")
    net_longwave = pyeto.net_out_lw_rad(values["tmin_c"] + 273.15,
                                        values["tmax_c"] + 273.15,
                                        min(values["solar_mj_m2"], clear_sky), clear_sky, avp)
    net_radiation = pyeto.net_rad(net_shortwave, net_longwave)
    et0 = pyeto.fao56_penman_monteith(
        net_radiation,
        tmean + 273.15, values["wind_m_s"], pyeto.mean_svp(values["tmin_c"], values["tmax_c"]),
        avp, pyeto.delta_svp(tmean), pyeto.psy_const(pyeto.atm_pressure(args.get("altitude_m", 0))),
    )
    return {"et0_mm_day": float(et0), "radiation_extra_terrestrial_mj_m2_day": float(ra),
            "net_radiation_mj_m2_day": float(net_radiation),
            "rs_rso_ratio": float(ratio), "rs_rso_limited": bool(ratio > 1),
            "method": "pyeto_fao56_penman_monteith"}


def spatial_moran(args):
    args = _arguments(args)
    import numpy as np
    from esda.moran import Moran
    from libpysal.weights import KNN

    x, y, values = _numbers(args, ("x", "y", "values"))
    k = int(args.get("k", 2))
    if len(values) <= k:
        raise ValueError("k must be smaller than the number of observations")
    if k < 1:
        raise ValueError("k must be positive")
    weights = KNN.from_array(np.column_stack([x, y]), k=k)
    permutations = int(args.get("permutations", 0))
    seed = int(args.get("random_seed", 0))
    if permutations < 0 or permutations > 9999 or seed < 0:
        raise ValueError("permutations must be in 0..9999 and random_seed must be nonnegative")
    if seed > 2 ** 32 - 1:
        raise ScientificToolError("invalid_arguments", "random_seed must be in 0..4294967295")
    if len(set(values)) == 1:
        return {"moran_i": None, "expected_i": -1 / (len(values) - 1), "p_sim": None,
                "k": k, "sample_count": len(values), "random_seed": seed}
    # esda.Moran 2.10 has no local RNG parameter. Obtain its observed statistic
    # without permutations, then apply the same permutation statistic and tail
    # convention using an independent RandomState. Never seed the process RNG.
    result = Moran(np.asarray(values), weights, permutations=0)
    statistic = float(result.I) if math.isfinite(float(result.I)) else None
    p_sim = None
    if permutations and statistic is not None:
        from libpysal.weights import lag_spatial
        rng = np.random.RandomState(seed)
        centered = np.asarray(values, dtype=float) - np.mean(values)
        denominator = np.sum(centered * centered)
        above = 0
        for _ in range(permutations):
            permuted = rng.permutation(centered)
            simulated = len(values) / weights.s0 * np.sum(permuted * lag_spatial(weights, permuted)) / denominator
            above += simulated >= statistic
        p_sim = float((min(above, permutations - above) + 1) / (permutations + 1))
    return {"moran_i": statistic, "expected_i": float(result.EI), "p_sim": p_sim,
            "k": k, "sample_count": len(values), "random_seed": seed}


# Public entrypoints enforce the catalog contract for direct and native calls.
from .github_contracts import bounded as _bounded
verde_grid = _bounded('GeoVerdeGrid', verde_grid)
region_mask = _bounded('GeoRegionMask', region_mask)
hydro_error_metrics = _bounded('HydroErrorMetrics', hydro_error_metrics)
scientific_curve_fit = _bounded('ScientificCurveFit', scientific_curve_fit)
hydrointerp_grid = _bounded('HydroInterpolationGrid', hydrointerp_grid)
metpy_wind_components = _bounded('MetPyWindComponents', metpy_wind_components)
seismic_reflectivity = _bounded('SeismicReflectivity', seismic_reflectivity)
segy_summary = _bounded('SeismicSegySummary', segy_summary)
reference_et0 = _bounded('HydroReferenceET0', reference_et0)
spatial_moran = _bounded('SpatialMoranI', spatial_moran)

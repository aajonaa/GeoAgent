"""Bounded, offline hydrology operations. Activation requires coordinator acceptance."""

import json
import math
from pathlib import Path
from types import SimpleNamespace

from .collection_contracts import operation, reject


MAX_BYTES = 2_097_152


def _number(value, name, low, high, *, open_low=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value > high
            or (value <= low if open_low else value < low)):
        reject(f"{name} is outside its finite numeric bounds.", code="invalid_arguments")
    return float(value)


def _integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        reject(f"{name} is outside its integer bounds.", code="invalid_arguments")
    return value


def _array(value, name, low, high, *, minimum=1, maximum=10_000):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        reject(f"{name} must be a bounded nonempty JSON array.", code="invalid_arguments")
    return [_number(v, name, low, high) for v in value]


def _matrix(value, name, low, high, *, minimum=1, maximum=128):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        reject(f"{name} has an invalid row count.", code="invalid_arguments")
    rows = [_array(r, name, low, high, minimum=minimum, maximum=maximum) for r in value]
    if len({len(r) for r in rows}) != 1:
        reject(f"{name} must be rectangular.", code="invalid_arguments")
    return rows


def _same_length(*arrays):
    if len({len(a) for a in arrays}) != 1:
        reject("Input arrays must have equal lengths.", code="invalid_arguments")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonfinite JSON constant")


def _load(args, fields):
    value = args.get("data_path")
    if not isinstance(value, str) or not value or len(value) > 4096:
        reject("data_path must identify a JSON input snapshot.", code="invalid_arguments")
    try:
        with Path(value).open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except (OSError, ValueError):
        reject("Cannot read the JSON input snapshot.", code="invalid_arguments")
    if len(raw) > MAX_BYTES:
        reject("JSON input exceeds 2097152 bytes.", code="invalid_arguments")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, UnicodeError, RecursionError):
        reject("Input must be finite UTF-8 JSON with unique object keys.", code="invalid_arguments")
    if (not isinstance(data, dict) or not set(fields) <= set(data)
            or set(data) - set(fields) - {"synthetic"}
            or ("synthetic" in data and not isinstance(data["synthetic"], bool))):
        reject("JSON input fields do not match the declared file schema.", code="invalid_arguments")
    return data


def _result(values, units):
    def finite(value):
        if isinstance(value, dict):
            return all(finite(v) for v in value.values())
        if isinstance(value, (tuple, list)):
            return all(finite(v) for v in value)
        return value is None or (isinstance(value, (int, float)) and math.isfinite(value))
    if not finite(values):
        reject("The scientific calculation produced a nonfinite result.", code="invalid_arguments")
    return {**values, "units": units}


def _flow_pair(args):
    data = _load(args, ("observed_m3_s", "simulated_m3_s"))
    obs = _array(data["observed_m3_s"], "observed_m3_s", 0, 1e8, minimum=2)
    sim = _array(data["simulated_m3_s"], "simulated_m3_s", 0, 1e8, minimum=2)
    _same_length(obs, sim)
    if max(obs) == min(obs) or max(sim) == min(sim) or sum(obs) <= 0 or sum(sim) <= 0:
        reject("Flow scores require positive means and nonconstant series.", code="invalid_arguments")
    return obs, sim


@operation("HydroModelsXanthosMonthlyPET")
def xanthos_monthly_pet(args, output_dir=None):
    data = _load(args, ("temperature_c", "temperature_range_c", "latitude_radians"))
    t = _array(data["temperature_c"], "temperature_c", -80, 60)
    dtr = _array(data["temperature_range_c"], "temperature_range_c", 0, 80)
    lat = _array(data["latitude_radians"], "latitude_radians", -math.pi / 2, math.pi / 2)
    _same_length(t, dtr, lat)
    declination = _number(args.get("declination_radians"), "declination_radians", -0.42, 0.42)
    distance = _number(args.get("inverse_earth_sun_distance"), "inverse_earth_sun_distance", 0.95, 1.05)
    days = _integer(args.get("days_in_month"), "days_in_month", 28, 31)
    import numpy as np
    from .collection_vendor.hydro_models.xanthos_hargreaves import calculate_pet
    pet = calculate_pet(np.array(t), np.array(dtr), np.array(lat), declination, distance, days)
    return _result({"pet_mm_month": np.atleast_1d(pet).tolist()}, {"pet_mm_month": "mm/month"})


@operation("HydroModelsHydPyFlowScores")
def hydpy_flow_scores(args, output_dir=None):
    obs, sim = _flow_pair(args)
    from hydpy.auxs import statstools
    return _result({"modified_kge": float(statstools.kge(obs=obs, sim=sim, subperiod=False)),
                    "nse": float(statstools.nse(obs=obs, sim=sim, subperiod=False)),
                    "rmse_m3_s": float(statstools.rmse(obs=obs, sim=sim, subperiod=False)),
                    "count": len(obs)},
                   {"modified_kge": "1", "nse": "1", "rmse_m3_s": "m3/s", "count": "samples"})


@operation("HydroModelsRRMPGABCRunoff")
def rrmpg_abc_runoff(args, output_dir=None):
    data = _load(args, ("precipitation_mm_step",))
    p = _array(data["precipitation_mm_step"], "precipitation_mm_step", 0, 10_000, minimum=2)
    a = _number(args.get("a"), "a", 0, 1)
    b = _number(args.get("b"), "b", 0, 1)
    c = _number(args.get("c"), "c", 0, 1)
    initial = _number(args.get("initial_storage_mm"), "initial_storage_mm", 0, 1e6)
    if a + b > 1:
        reject("ABC parameters require a + b <= 1.", code="invalid_arguments")
    import numpy as np
    from .collection_vendor.hydro_models.rrmpg_abc import run_abcmodel
    params = np.zeros(1, dtype=[("a", np.float64), ("b", np.float64), ("c", np.float64)])
    params[0] = (a, b, c)
    # Run the original dispatcher's Python implementation without compiling or caching JIT code.
    q, storage = run_abcmodel.py_func(np.array(p), initial, params[0])
    return _result({"runoff_mm_step": q.tolist(), "storage_mm": storage.tolist()},
                   {"runoff_mm_step": "mm/step", "storage_mm": "mm"})


@operation("HydroModelsNeuralHydrologyFlowScores")
def neuralhydrology_flow_scores(args, output_dir=None):
    obs, sim = _flow_pair(args)
    import xarray as xr
    from .neuralhydrology_metrics_loader import load_reviewed_metrics
    metrics = load_reviewed_metrics()
    observed = xr.DataArray(obs, dims=("time",))
    simulated = xr.DataArray(sim, dims=("time",))
    return _result({"kge": float(metrics.kge(observed, simulated)),
                    "nse": float(metrics.nse(observed, simulated)),
                    "rmse_m3_s": float(metrics.rmse(observed, simulated)), "count": len(obs)},
                   {"kge": "1", "nse": "1", "rmse_m3_s": "m3/s", "count": "samples"})


@operation("HydroModelsHydroFunctionsFlowDuration")
def hydrofunctions_flow_duration(args, output_dir=None):
    data = _load(args, ("discharge_m3_s",))
    discharge = _array(data["discharge_m3_s"], "discharge_m3_s", 0, 1e8)
    import pandas as pd
    from hydrofunctions.charts import flow_duration
    import matplotlib.pyplot as plt
    fig, ax = flow_duration(pd.DataFrame({"discharge": discharge}), xscale="linear", yscale="linear",
                            ylabel="Discharge (m3/s)", legend=False)
    try:
        probability = ax.lines[0].get_xdata().tolist()
        values = ax.lines[0].get_ydata().tolist()
    finally:
        plt.close(fig)
    return _result({"discharge_m3_s": values, "exceedance_probability": probability},
                   {"discharge_m3_s": "m3/s", "exceedance_probability": "1"})


@operation("HydroModelsPySTEPSPrecipitationAdvection")
def pysteps_precipitation_advection(args, output_dir=None):
    data = _load(args, ("precipitation_mm_hour", "east_velocity_pixels_step", "south_velocity_pixels_step"))
    rain = _matrix(data["precipitation_mm_hour"], "precipitation_mm_hour", 0, 1000, minimum=2)
    east = _matrix(data["east_velocity_pixels_step"], "east_velocity_pixels_step", -32, 32, minimum=2)
    south = _matrix(data["south_velocity_pixels_step"], "south_velocity_pixels_step", -32, 32, minimum=2)
    shape = (len(rain), len(rain[0]))
    if any((len(v), len(v[0])) != shape for v in (east, south)):
        reject("Rain and velocity grids must have the same shape.", code="invalid_arguments")
    steps = _integer(args.get("lead_steps"), "lead_steps", 1, 8)
    import numpy as np
    from pysteps.extrapolation.semilagrangian import extrapolate
    forecast = extrapolate(np.array(rain), np.array([east, south]), steps, outval=0.0,
                           n_iter=1, interp_order=1, map_coordinates_mode="constant", verbose=False)
    return _result({"forecast_mm_hour": forecast.tolist(), "lead_steps": list(range(1, steps + 1))},
                   {"forecast_mm_hour": "mm/hour", "lead_steps": "input velocity time steps"})


@operation("HydroModelsCMFSoilConductivity")
def cmf_soil_conductivity(args, output_dir=None):
    data = _load(args, ("wetness",))
    wetness = _array(data["wetness"], "wetness", 1e-6, 1, maximum=1000)
    ksat = _number(args.get("ksat_m_day"), "ksat_m_day", 0, 1000, open_low=True)
    phi = _number(args.get("porosity"), "porosity", 0.01, 0.9)
    alpha = _number(args.get("alpha_per_cm"), "alpha_per_cm", 1e-6, 2)
    n = _number(args.get("n"), "n", 1.01, 5)
    import cmf
    curve = cmf.VanGenuchtenMualem(Ksat=ksat, phi=phi, alpha=alpha, n=n, theta_r=0.0)
    conductivity = [float(curve.K(w)) for w in wetness]
    return _result({"conductivity_m_day": conductivity}, {"conductivity_m_day": "m/day"})


@operation("HydroModelsTopoFlowSolarFlux")
def topoflow_solar_flux(args, output_dir=None):
    data = _load(args, ("latitude_degrees", "julian_day", "hours_from_solar_noon"))
    lat = _array(data["latitude_degrees"], "latitude_degrees", -90, 90)
    day = _array(data["julian_day"], "julian_day", 1, 366)
    hour = _array(data["hours_from_solar_noon"], "hours_from_solar_noon", -12, 12)
    _same_length(lat, day, hour)
    import numpy as np
    from .collection_vendor.hydro_models.topoflow_solar import ET_Radiation_Flux
    flux = ET_Radiation_Flux(np.array(lat), np.array(day), np.array(hour))
    return _result({"extraterrestrial_flux_w_m2": flux.tolist()}, {"extraterrestrial_flux_w_m2": "W/m2"})


@operation("HydroModelsPyDEMTerrainDerivatives")
def pydem_terrain_derivatives(args, output_dir=None):
    data = _load(args, ("elevation_m",))
    elevation = _matrix(data["elevation_m"], "elevation_m", -12_000, 10_000, minimum=3)
    dx = _number(args.get("east_spacing_m"), "east_spacing_m", 0.01, 100_000)
    dy = _number(args.get("north_spacing_m"), "north_spacing_m", 0.01, 100_000)
    import numpy as np
    from pydem.dem_processing import DEMProcessor
    processor = DEMProcessor(elev=np.array(elevation), dX=dx, dY=dy, fill_flats=False,
                             drain_pits=False, drain_pits_path=False, maximum_pit_area=0)
    slope, direction = processor.calc_slopes_directions()
    slope, direction = slope[1:-1, 1:-1], direction[1:-1, 1:-1]
    invalid = (slope < 0) | (direction < 0)
    slopes = [[None if invalid[i, j] else float(slope[i, j]) for j in range(slope.shape[1])]
              for i in range(slope.shape[0])]
    angles = [[None if invalid[i, j] else float(direction[i, j]) for j in range(slope.shape[1])]
              for i in range(slope.shape[0])]
    return _result({"slope_m_m": slopes, "downslope_direction_radians": angles,
                    "undefined_cells": int(invalid.sum())},
                   {"slope_m_m": "m/m", "downslope_direction_radians": "radian counterclockwise from east",
                    "undefined_cells": "cells"})


@operation("HydroModelsEXPHydroBucketWaterBalance")
def exphydro_bucket_water_balance(args, output_dir=None):
    fields = ("precipitation_mm_day", "pet_mm_day", "temperature_c", "snow_storage_mm", "soil_storage_mm")
    data = _load(args, fields)
    arrays = [_array(data[k], k, -80 if k == "temperature_c" else 0,
                     60 if k == "temperature_c" else 1e6, maximum=3660) for k in fields]
    _same_length(*arrays)
    bounds = {"f_per_mm": (0, 0.1), "smax_mm": (1, 2000), "qmax_mm_day": (0, 100),
              "ddf_mm_day_c": (0, 20), "rain_snow_threshold_c": (-10, 10), "melt_threshold_c": (-10, 10)}
    p = {k: _number(args.get(k), k, *v) for k, v in bounds.items()}
    if p["rain_snow_threshold_c"] > p["melt_threshold_c"]:
        reject("Rain/snow threshold cannot exceed the melt threshold.", code="invalid_arguments")
    import numpy as np
    from .collection_vendor.hydro_models.exphydro_bucket import ExphydroModel
    model = ExphydroModel(*(np.array(a) for a in arrays[:3]))
    names = {"f": "f_per_mm", "smax": "smax_mm", "qmax": "qmax_mm_day", "ddf": "ddf_mm_day_c",
             "mint": "rain_snow_threshold_c", "maxt": "melt_threshold_c"}
    parameters = SimpleNamespace(**{k: SimpleNamespace(value=p[v]) for k, v in names.items()})
    derivatives = [model.waterbalance(float(i), np.array([arrays[3][i], arrays[4][i]]), parameters).tolist()
                   for i in range(len(arrays[0]))]
    return _result({"snow_storage_rate_mm_day": [d[0] for d in derivatives],
                    "soil_storage_rate_mm_day": [d[1] for d in derivatives],
                    "runoff_mm_day": model.qsim.tolist(), "actual_et_mm_day": model.et.tolist(),
                    "snowmelt_mm_day": model.melt.tolist()},
                   {key: "mm/day" for key in ("snow_storage_rate_mm_day", "soil_storage_rate_mm_day",
                                               "runoff_mm_day", "actual_et_mm_day", "snowmelt_mm_day")})


@operation("HydroModelsPyTOPKAPIGreenAmpt")
def pytopkapi_green_ampt(args, output_dir=None):
    data = _load(args, ("rainfall_mm_hour",))
    rain = _array(data["rainfall_mm_hour"], "rainfall_mm_hour", 0, 1000, maximum=366)
    psi = _number(args.get("suction_head_mm"), "suction_head_mm", 0.01, 10_000)
    theta = _number(args.get("effective_porosity"), "effective_porosity", 0.01, 0.9)
    saturation = _number(args.get("effective_saturation"), "effective_saturation", 0, 0.99)
    k = _number(args.get("conductivity_mm_hour"), "conductivity_mm_hour", 0.001, 1000)
    dt = _number(args.get("step_hours"), "step_hours", 0.001, 24)
    initial = _number(args.get("initial_infiltration_mm"), "initial_infiltration_mm", 0, 1e6)
    from .collection_vendor.hydro_models.topkapi_infiltration import green_ampt_cum_infiltration
    cumulative, increments, runoff = [], [], []
    for rate in rain:
        try:
            final = float(green_ampt_cum_infiltration(rate, psi, theta, saturation, k, dt, initial))
        except (ValueError, ArithmeticError):
            reject("The upstream Green-Ampt solver did not converge.", code="invalid_arguments")
        change = final - initial
        if not math.isfinite(final) or change < -1e-7 or change > rate * dt + 1e-6:
            reject("The upstream infiltration solution violates interval water bounds.", code="invalid_arguments")
        cumulative.append(final)
        increments.append(change)
        runoff.append(rate * dt - change)
        initial = final
    return _result({"cumulative_infiltration_mm": cumulative, "infiltration_mm_step": increments,
                    "rainfall_excess_mm_step": runoff},
                   {"cumulative_infiltration_mm": "mm", "infiltration_mm_step": "mm/step",
                    "rainfall_excess_mm_step": "mm/step"})


@operation("HydroModelsSuperflexUnitHydrograph")
def superflex_unit_hydrograph(args, output_dir=None):
    data = _load(args, ("effective_rainfall_mm_step",))
    rainfall = _array(data["effective_rainfall_mm_step"], "effective_rainfall_mm_step", 0, 1000,
                      maximum=3660)
    lag = _number(args.get("lag_steps"), "lag_steps", 1, 30)
    import numpy as np
    from superflexpy.implementation.elements.gr4j import UnitHydrograph1
    padding = math.ceil(lag) + 1
    forcing = np.array(rainfall + [0.0] * padding)
    element = UnitHydrograph1(parameters={"lag-time": lag}, states={"lag": None}, id="bounded_route")
    element.set_input([forcing])
    routed = element.get_output()[0]
    return _result({"routed_mm_step": routed.tolist(), "tail_padding_steps": padding},
                   {"routed_mm_step": "mm/step", "tail_padding_steps": "steps"})


@operation("HydroModelsHidroCompEnsembleRMSE")
def hidrocomp_ensemble_rmse(args, output_dir=None):
    data = _load(args, ("reference_m3_s", "ensemble_m3_s"))
    reference = _array(data["reference_m3_s"], "reference_m3_s", 0, 1e8, maximum=128)
    ensemble = _matrix(data["ensemble_m3_s"], "ensemble_m3_s", 0, 1e8, maximum=128)
    if len(ensemble[0]) != len(reference):
        reject("Ensemble columns must match reference positions.", code="invalid_arguments")
    import pandas as pd
    from .collection_vendor.hydro_models.hidro_rmse import RMSE
    result = RMSE(pd.Series(reference), pd.DataFrame(ensemble)).calculo_erro()
    return _result({"rmse_m3_s": result.tolist()}, {"rmse_m3_s": "m3/s"})


@operation("HydroModelsPyFloCurveNumberRunoff")
def pyflo_curve_number_runoff(args, output_dir=None):
    data = _load(args, ("rainfall_inches",))
    rainfall = _array(data["rainfall_inches"], "rainfall_inches", 0, 100, maximum=1000)
    cn = _number(args.get("curve_number"), "curve_number", 1, 100)
    area = _number(args.get("area_acres"), "area_acres", 0.001, 1e6)
    import numpy as np
    from pyflo.nrcs.hydrology import Basin
    basin = Basin(area=area, cn=cn, tc=1.0, runoff_dist=np.array([[0., 0.], [1., 1.], [2., 0.]]),
                  peak_factor=484.0)
    return _result({"runoff_inches": [float(basin.runoff_depth(v)) for v in rainfall],
                    "runoff_volume_ft3": [float(basin.runoff_volume(v)) for v in rainfall]},
                   {"runoff_inches": "inch", "runoff_volume_ft3": "ft3"})

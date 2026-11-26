"""Independent numerical/content acceptance, to be invoked by the coordinator only.

No upstream package is imported here. References use scalar arithmetic, analytic
identities, independent bisection, or finite triangular facets. Nothing runs on import.
"""

import copy
import hashlib
import json
import math
from pathlib import Path


PREFIX = "HydroModels"


def _close(actual, expected, *, tolerance=1e-8):
    if isinstance(expected, (list, tuple)):
        assert isinstance(actual, (list, tuple)) and len(actual) == len(expected)
        for a, b in zip(actual, expected):
            _close(a, b, tolerance=tolerance)
    elif expected is None:
        assert actual is None
    else:
        assert isinstance(actual, (int, float)) and not isinstance(actual, bool)
        assert math.isfinite(actual)
        assert math.isclose(actual, expected, rel_tol=tolerance, abs_tol=tolerance), (actual, expected)


def _units(result, expected):
    assert result["units"] == expected, result["units"]


def _scores(data, modified):
    observed, simulated = data["observed_m3_s"], data["simulated_m3_s"]
    n = len(observed)
    mo, ms = sum(observed) / n, sum(simulated) / n
    vo = sum((v - mo) ** 2 for v in observed) / n
    vs = sum((v - ms) ** 2 for v in simulated) / n
    correlation = sum((o - mo) * (s - ms) for o, s in zip(observed, simulated)) / (n * math.sqrt(vo * vs))
    ratio = math.sqrt(vs / vo)
    if modified:
        ratio /= ms / mo
    mse = sum((o - s) ** 2 for o, s in zip(observed, simulated)) / n
    return 1 - math.sqrt((correlation - 1) ** 2 + (ratio - 1) ** 2 + (ms / mo - 1) ** 2), 1 - mse / vo, math.sqrt(mse)


def _bilinear(grid, x, y):
    rows, cols = len(grid), len(grid[0])
    if not 0 <= x <= cols - 1 or not 0 <= y <= rows - 1:
        return 0.0
    ix, iy = int(math.floor(x)), int(math.floor(y))
    jx, jy = min(ix + 1, cols - 1), min(iy + 1, rows - 1)
    fx, fy = x - ix, y - iy
    return ((1 - fy) * ((1 - fx) * grid[iy][ix] + fx * grid[iy][jx])
            + fy * ((1 - fx) * grid[jy][ix] + fx * grid[jy][jx]))


def _terrain_reference(grid, dx, dy):
    # Descending gradients on the eight triangles around each interior cell.
    facets = [((0, 1), (-1, 1), 0, 1), ((-1, 0), (-1, 1), 1, -1),
              ((-1, 0), (-1, -1), 1, 1), ((0, -1), (-1, -1), 2, -1),
              ((0, -1), (1, -1), 2, 1), ((1, 0), (1, -1), 3, -1),
              ((1, 0), (1, 1), 3, 1), ((0, 1), (1, 1), 4, -1)]
    slopes, directions = [], []
    for row in range(1, len(grid) - 1):
        sr, dr = [], []
        for col in range(1, len(grid[0]) - 1):
            best, angle = 0., None
            for first, diagonal, quadrant, orientation in facets:
                d1 = dx if first[0] == 0 else dy
                d2 = dy if first[0] == 0 else dx
                z0 = grid[row][col]
                z1 = grid[row + first[0]][col + first[1]]
                z2 = grid[row + diagonal[0]][col + diagonal[1]]
                g1, g2 = (z0 - z1) / d1, (z1 - z2) / d2
                theta = math.atan2(d2, d1)
                r = math.atan2(g2, g1)
                r = min(theta, max(0., r))
                value = g1 * math.cos(r) + g2 * math.sin(r)
                if value > best:
                    best, angle = value, quadrant * math.pi / 2 + orientation * r
            sr.append(best if angle is not None else None)
            dr.append(angle)
        slopes.append(sr)
        directions.append(dr)
    return slopes, directions


def _green_ampt_reference(rain, initial, psi, theta, saturation, k, dt):
    if rain == 0:
        return initial
    deficit = psi * theta * (1 - saturation)
    supplied = initial + rain * dt
    if k * (1 + deficit / supplied) > rain:
        return supplied
    capacity = math.inf if initial == 0 else k * (1 + deficit / initial)
    if capacity <= rain:
        start, ponding_time = initial, 0.
    else:
        start = k * deficit / (rain - k)
        ponding_time = (start - initial) / rain
    low, high = start, supplied
    for _ in range(100):
        mid = (low + high) / 2
        residual = mid - start - deficit * math.log((mid + deficit) / (start + deficit)) - k * (dt - ponding_time)
        if residual > 0:
            high = mid
        else:
            low = mid
    return (low + high) / 2


def check(name: str, result: dict, args: dict, output_dir: Path | None):
    known = {PREFIX + suffix for suffix in (
        "XanthosMonthlyPET", "HydPyFlowScores", "RRMPGABCRunoff", "NeuralHydrologyFlowScores",
        "HydroFunctionsFlowDuration", "PySTEPSPrecipitationAdvection", "CMFSoilConductivity",
        "TopoFlowSolarFlux", "PyDEMTerrainDerivatives", "EXPHydroBucketWaterBalance",
        "PyTOPKAPIGreenAmpt", "SuperflexUnitHydrograph", "HidroCompEnsembleRMSE", "PyFloCurveNumberRunoff")}
    if name not in known:
        raise ValueError(f"Unknown hydro_models operation: {name}")
    data = json.loads(Path(args["data_path"]).read_text(encoding="utf-8"))
    if name == PREFIX + "XanthosMonthlyPET":
        expected = []
        dec, dr, days = args["declination_radians"], args["inverse_earth_sun_distance"], args["days_in_month"]
        for t, dtr, lat in zip(data["temperature_c"], data["temperature_range_c"], data["latitude_radians"]):
            sunset = math.acos(min(1., max(-1., -math.tan(lat) * math.tan(dec))))
            radiation = 15.392 * dr * (sunset * math.sin(lat) * math.sin(dec)
                                      + math.cos(lat) * math.cos(dec) * math.sin(sunset))
            expected.append(max(0., days * 0.0023 * radiation * (t + 17.8) * math.sqrt(dtr)))
        _close(result["pet_mm_month"], expected)
        _units(result, {"pet_mm_month": "mm/month"})
    elif name in (PREFIX + "HydPyFlowScores", PREFIX + "NeuralHydrologyFlowScores"):
        modified = name == PREFIX + "HydPyFlowScores"
        kge, nse, rmse = _scores(data, modified)
        key = "modified_kge" if modified else "kge"
        _close([result[key], result["nse"], result["rmse_m3_s"]], [kge, nse, rmse])
        assert result["count"] == len(data["observed_m3_s"])
        _units(result, {key: "1", "nse": "1", "rmse_m3_s": "m3/s", "count": "samples"})
        if data["observed_m3_s"] == [1., 2., 3., 4.] and data["simulated_m3_s"] == [2., 4., 6., 8.]:
            _close(result[key], 0. if modified else 1. - math.sqrt(2))
            _close(result["nse"], -5.)
            _close(result["rmse_m3_s"], math.sqrt(7.5))
    elif name == PREFIX + "RRMPGABCRunoff":
        p = data["precipitation_mm_step"]
        q, storage = [0.], [args["initial_storage_mm"]]
        for precipitation in p[1:]:
            q.append((1 - args["a"] - args["b"]) * precipitation + args["c"] * storage[-1])
            storage.append((1 - args["c"]) * storage[-1] + args["a"] * precipitation)
        _close(result["runoff_mm_step"], q)
        _close(result["storage_mm"], storage)
        _units(result, {"runoff_mm_step": "mm/step", "storage_mm": "mm"})
    elif name == PREFIX + "HydroFunctionsFlowDuration":
        q = data["discharge_m3_s"]
        expected = [(sum(x > v for x in q) + (sum(x == v for x in q) + 1) / 2) / len(q) for v in q]
        _close(result["discharge_m3_s"], q)
        _close(result["exceedance_probability"], expected)
        _units(result, {"discharge_m3_s": "m3/s", "exceedance_probability": "1"})
    elif name == PREFIX + "PySTEPSPrecipitationAdvection":
        rain = data["precipitation_mm_hour"]
        u = data["east_velocity_pixels_step"][0][0]
        v = data["south_velocity_pixels_step"][0][0]
        # Acceptance fixtures use uniform velocity, giving an exact transport solution.
        assert all(value == u for row in data["east_velocity_pixels_step"] for value in row)
        assert all(value == v for row in data["south_velocity_pixels_step"] for value in row)
        expected = [[[_bilinear(rain, col - u * t, row - v * t) for col in range(len(rain[0]))]
                     for row in range(len(rain))] for t in range(1, args["lead_steps"] + 1)]
        _close(result["forecast_mm_hour"], expected)
        assert result["lead_steps"] == list(range(1, args["lead_steps"] + 1))
        _units(result, {"forecast_mm_hour": "mm/hour", "lead_steps": "input velocity time steps"})
    elif name == PREFIX + "CMFSoilConductivity":
        m = 1 - 1 / args["n"]
        expected = [args["ksat_m_day"] * math.sqrt(w) * (1 - (1 - w ** (1 / m)) ** m) ** 2 for w in data["wetness"]]
        _close(result["conductivity_m_day"], expected, tolerance=1e-7)
        _units(result, {"conductivity_m_day": "m/day"})
    elif name == PREFIX + "TopoFlowSolarFlux":
        expected = []
        for lat, day, hour in zip(data["latitude_degrees"], data["julian_day"], data["hours_from_solar_noon"]):
            gamma = 2 * math.pi * (day - 1) / 365
            declination = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
                           - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
                           - 0.002697 * math.cos(3 * gamma) + 0.001480 * math.sin(3 * gamma))
            distance = (1.000110 + 0.034221 * math.cos(gamma) + 0.001280 * math.sin(gamma)
                        + 0.000719 * math.cos(2 * gamma) + 0.000077 * math.sin(2 * gamma))
            incidence = (math.cos(declination) * math.cos(math.radians(lat)) * math.cos(math.pi * hour / 12)
                         + math.sin(declination) * math.sin(math.radians(lat)))
            expected.append(max(0., 1367 * distance * incidence))
        _close(result["extraterrestrial_flux_w_m2"], expected)
        _units(result, {"extraterrestrial_flux_w_m2": "W/m2"})
    elif name == PREFIX + "PyDEMTerrainDerivatives":
        slopes, angles = _terrain_reference(data["elevation_m"], args["east_spacing_m"], args["north_spacing_m"])
        _close(result["slope_m_m"], slopes)
        count = 0
        for expected_row, actual_row in zip(angles, result["downslope_direction_radians"]):
            assert len(expected_row) == len(actual_row)
            for expected, actual in zip(expected_row, actual_row):
                if expected is None:
                    assert actual is None
                    count += 1
                else:
                    assert actual is not None and math.isfinite(actual)
                    _close(math.sin(actual), math.sin(expected))
                    _close(math.cos(actual), math.cos(expected))
        assert result["undefined_cells"] == count
        _units(result, {"slope_m_m": "m/m", "downslope_direction_radians": "radian counterclockwise from east",
                        "undefined_cells": "cells"})
    elif name == PREFIX + "EXPHydroBucketWaterBalance":
        expected = {k: [] for k in ("snow_storage_rate_mm_day", "soil_storage_rate_mm_day", "runoff_mm_day",
                                    "actual_et_mm_day", "snowmelt_mm_day")}
        for precipitation, pet, temperature, snow, soil in zip(*(data[k] for k in (
                "precipitation_mm_day", "pet_mm_day", "temperature_c", "snow_storage_mm", "soil_storage_mm"))):
            snowfall = precipitation if temperature < args["rain_snow_threshold_c"] else 0.
            melt = min(snow, args["ddf_mm_day_c"] * max(0., temperature - args["melt_threshold_c"]))
            runoff = (args["qmax_mm_day"] + soil - args["smax_mm"] if soil > args["smax_mm"]
                      else args["qmax_mm_day"] * math.exp(-args["f_per_mm"] * (args["smax_mm"] - soil)))
            et = pet * min(1., soil / args["smax_mm"])
            values = (snowfall - melt, precipitation - snowfall + melt - runoff - et, runoff, et, melt)
            for key, value in zip(expected, values):
                expected[key].append(value)
        for key, value in expected.items():
            _close(result[key], value)
        _units(result, {k: "mm/day" for k in expected})
    elif name == PREFIX + "PyTOPKAPIGreenAmpt":
        initial = args["initial_infiltration_mm"]
        expected, increments, excess = [], [], []
        for rain in data["rainfall_mm_hour"]:
            final = _green_ampt_reference(rain, initial, args["suction_head_mm"], args["effective_porosity"],
                                          args["effective_saturation"], args["conductivity_mm_hour"], args["step_hours"])
            expected.append(final)
            increments.append(final - initial)
            excess.append(rain * args["step_hours"] - final + initial)
            initial = final
        _close(result["cumulative_infiltration_mm"], expected, tolerance=1e-6)
        _close(result["infiltration_mm_step"], increments, tolerance=1e-6)
        _close(result["rainfall_excess_mm_step"], excess, tolerance=1e-6)
        _units(result, {"cumulative_infiltration_mm": "mm", "infiltration_mm_step": "mm/step",
                        "rainfall_excess_mm_step": "mm/step"})
    elif name == PREFIX + "SuperflexUnitHydrograph":
        rain, lag = data["effective_rainfall_mm_step"], args["lag_steps"]
        padding = math.ceil(lag) + 1
        weights = [min(1., ((i + 1) / lag) ** 2.5) - min(1., (i / lag) ** 2.5) for i in range(math.ceil(lag))]
        expected = [sum(rain[t - k] * weight for k, weight in enumerate(weights) if 0 <= t - k < len(rain))
                    for t in range(len(rain) + padding)]
        _close(result["routed_mm_step"], expected)
        _close(sum(result["routed_mm_step"]), sum(rain))
        assert result["tail_padding_steps"] == padding
        _units(result, {"routed_mm_step": "mm/step", "tail_padding_steps": "steps"})
    elif name == PREFIX + "HidroCompEnsembleRMSE":
        ensemble, ref = data["ensemble_m3_s"], data["reference_m3_s"]
        expected = [math.sqrt(sum((row[i] - value) ** 2 for row in ensemble) / len(ensemble))
                    for i, value in enumerate(ref)]
        _close(result["rmse_m3_s"], expected)
        _units(result, {"rmse_m3_s": "m3/s"})
    elif name == PREFIX + "PyFloCurveNumberRunoff":
        retention = 1000 / args["curve_number"] - 10
        initial = 0.2 * retention
        depth = [(rain - initial) ** 2 / (rain - initial + retention) if rain > initial else 0.
                 for rain in data["rainfall_inches"]]
        _close(result["runoff_inches"], depth)
        _close(result["runoff_volume_ft3"], [v * args["area_acres"] * 3630 for v in depth])
        _units(result, {"runoff_inches": "inch", "runoff_volume_ft3": "ft3"})


def check_immutable_case(invoke, name, args, output_dir=None):
    """Optional coordinator harness. invoke(name, args, output_dir) calls the native tool."""
    path = Path(args["data_path"])
    before = hashlib.sha256(path.read_bytes()).digest()
    original = copy.deepcopy(args)
    result = invoke(name, args, output_dir)
    assert args == original, "The tool mutated its arguments"
    assert hashlib.sha256(path.read_bytes()).digest() == before, "The tool mutated the input file"
    check(name, result, args, output_dir)
    return result


def check_rejection_case(invoke, name, args):
    """Run only in coordinator acceptance; repeat invalid calls to check stable errors."""
    path = Path(args["data_path"])
    before = hashlib.sha256(path.read_bytes()).digest() if path.is_file() else None
    errors = []
    for _ in range(2):
        try:
            invoke(name, copy.deepcopy(args), None)
        except Exception as exc:
            assert getattr(exc, "code", None) == "invalid_arguments", (type(exc).__name__, str(exc))
            errors.append((type(exc).__name__, str(exc)))
        else:
            raise AssertionError("Invalid arguments were accepted")
    assert errors[0] == errors[1], "Errors are nondeterministic"
    if before is not None:
        assert hashlib.sha256(path.read_bytes()).digest() == before, "Rejected input was mutated"

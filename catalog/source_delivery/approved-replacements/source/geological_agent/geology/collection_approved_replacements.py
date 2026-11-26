"""Explicit functional replacements, not implementations of the original apps.

Source-only staging. Nothing in this directory is registered in the parent.
The shared collection SDK must enforce each reviewed profile's exact pins.
"""
import datetime as dt
import math

from .collection_contracts import operation, reject


def _number(value, name, lower, upper):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        reject(name + " must be a finite JSON number")
    if not math.isfinite(value) or not lower <= value <= upper:
        reject(name + " is outside its finite physical/statistical bounds")
    return float(value)


def _vector(value, name, minimum, maximum, lower, upper):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        reject(name + " has an unsupported sample count")
    return [_number(item, name, lower, upper) for item in value]


def _matrix(value, name, minimum_rows, maximum_rows):
    if not isinstance(value, list) or not minimum_rows <= len(value) <= maximum_rows:
        reject(name + " has an unsupported row count")
    rows = [_vector(row, name, 1, 8, -1e6, 1e6) for row in value]
    if any(len(row) != len(rows[0]) for row in rows):
        reject(name + " must be rectangular")
    return rows


@operation("ScipyGroundwaterFrequencyResponse")
def groundwater_frequency_response(args, output_dir=None):
    """Limited spectral response, not HydroGeoSines or tidal correction."""
    times = _vector(args["times_seconds"], "times_seconds", 64, 65536, -1e12, 1e12)
    pressure = _vector(args["pressure_head_m"], "pressure_head_m", 64, 65536, -1e6, 1e6)
    head = _vector(args["groundwater_head_m"], "groundwater_head_m", 64, 65536, -1e6, 1e6)
    if not len(times) == len(pressure) == len(head):
        reject("Times, pressure-head and groundwater-head arrays must have equal length")
    segment = args.get("samples_per_segment", min(256, len(times) // 4))
    if isinstance(segment, bool) or not isinstance(segment, int) or not 16 <= segment <= min(4096, len(times) // 2):
        reject("samples_per_segment must leave at least three 50%-overlapping Welch segments")
    import numpy as np
    from scipy import signal
    intervals = np.diff(np.asarray(times, dtype=float))
    step = float(intervals[0])
    if step <= 0 or not np.allclose(intervals, step, rtol=1e-9, atol=1e-7):
        reject("Time samples must be strictly increasing and regularly spaced in seconds")
    x, y = np.asarray(pressure), np.asarray(head)
    if float(np.var(x)) <= 0 or float(np.var(y)) <= 0:
        reject("Both head signals must have nonzero variation")
    common = dict(fs=1.0 / step, window="hann", nperseg=segment,
                  noverlap=segment // 2, detrend="constant")
    frequency, pxx = signal.welch(x, scaling="density", **common)
    fy, pyy = signal.welch(y, scaling="density", **common)
    fc, pxy = signal.csd(x, y, scaling="density", **common)
    with np.errstate(divide="ignore", invalid="ignore"):
        fh, coherence = signal.coherence(x, y, **common)
    if not (np.array_equal(frequency, fy) and np.array_equal(frequency, fc) and np.array_equal(frequency, fh)):
        reject("The reviewed spectral APIs returned inconsistent frequency bins", "invalid_result")
    if not (np.isfinite(pxx).all() and np.isfinite(pyy).all() and np.isfinite(pxy).all()):
        reject("Spectral powers/cross-power are not finite", "invalid_result")
    relative_floor = 1e-12
    valid = ((frequency > 0) & (pxx > float(np.max(pxx)) * relative_floor)
             & (pyy > float(np.max(pyy)) * relative_floor) & np.isfinite(coherence))
    if not valid.any():
        reject("No non-DC bins have enough pressure-head and groundwater-head spectral power")
    if np.any((coherence[valid] < -1e-10) | (coherence[valid] > 1 + 1e-10)):
        reject("Coherence is outside its numerical range", "invalid_result")
    transfer = np.zeros_like(pxy)
    transfer[valid] = pxy[valid] / pxx[valid]
    gain = np.abs(transfer)
    phase = np.angle(transfer)
    masked = lambda values: [float(value) if keep else None for value, keep in zip(values, valid)]
    return {"frequency_Hz": frequency.tolist(), "gain_head_per_pressure_head": masked(gain),
            "phase_rad": masked(phase), "coherence": masked(coherence),
            "pressure_head_psd_m2_per_Hz": pxx.tolist(), "groundwater_head_psd_m2_per_Hz": pyy.tolist(),
            "valid_response": valid.tolist(), "samples": len(times), "samples_per_segment": segment,
            "sample_interval_seconds": step, "relative_spectral_power_floor": relative_floor,
            "phase_convention": "csd(pressure_head,groundwater_head); lagging head has negative phase",
            "units": {"frequency_Hz": "Hz", "gain_head_per_pressure_head": "1", "phase_rad": "rad",
                      "coherence": "1", "pressure_head_psd_m2_per_Hz": "m2/Hz",
                      "groundwater_head_psd_m2_per_Hz": "m2/Hz", "sample_interval_seconds": "s"}}


@operation("StatsmodelsSeasonalFlowForecast")
def seasonal_flow_forecast(args, output_dir=None):
    """Matrix-only OLS with supplied annual phase and dimensionless predictors."""
    observed = _vector(args["observed_flow_m3_s"], "observed_flow_m3_s", 8, 4096, 0, 1e7)
    phase = _vector(args["training_annual_phase"], "training_annual_phase", 8, 4096, 0, 1)
    future_phase = _vector(args["forecast_annual_phase"], "forecast_annual_phase", 1, 3660, 0, 1)
    train = _matrix(args["training_predictors_dimensionless"], "training_predictors_dimensionless", 8, 4096)
    future = _matrix(args["forecast_predictors_dimensionless"], "forecast_predictors_dimensionless", 1, 3660)
    if not len(observed) == len(phase) == len(train):
        reject("Training observations, annual phases and predictor rows must match")
    if len(future_phase) != len(future) or len(train[0]) != len(future[0]):
        reject("Forecast phases/predictors and training/forecast predictor widths must match")
    confidence = _number(args.get("confidence_level", 0.95), "confidence_level", 0.8, 0.99)
    parameters = len(train[0]) + 3
    if len(observed) < parameters + 3:
        reject("The bounded OLS design needs at least three residual degrees of freedom")
    import numpy as np
    from statsmodels.regression.linear_model import OLS
    def design(phases, predictors):
        angles = 2 * np.pi * np.asarray(phases, dtype=float)
        return np.column_stack((np.ones(len(phases)), np.sin(angles), np.cos(angles), np.asarray(predictors, dtype=float)))
    x = design(phase, train)
    xf = design(future_phase, future)
    rank = int(np.linalg.matrix_rank(x))
    condition = float(np.linalg.cond(x))
    if rank != parameters or not math.isfinite(condition) or condition > 1e10:
        reject("The supplied seasonal design must be full rank and numerically conditioned")
    fitted = OLS(np.asarray(observed), x, hasconst=True, missing="raise").fit()
    prediction = fitted.get_prediction(xf).summary_frame(alpha=1 - confidence)
    arrays = {"forecast_mean_m3_s": prediction["mean"].to_numpy(),
              "mean_ci_lower_m3_s": prediction["mean_ci_lower"].to_numpy(),
              "mean_ci_upper_m3_s": prediction["mean_ci_upper"].to_numpy(),
              "prediction_lower_m3_s": prediction["obs_ci_lower"].to_numpy(),
              "prediction_upper_m3_s": prediction["obs_ci_upper"].to_numpy()}
    if not all(np.isfinite(values).all() for values in arrays.values()) or not np.isfinite(fitted.params).all():
        reject("OLS returned nonfinite coefficients or intervals", "invalid_result")
    if np.any(arrays["prediction_lower_m3_s"] > arrays["prediction_upper_m3_s"]):
        reject("OLS prediction interval bounds are reversed", "invalid_result")
    result = {name: values.tolist() for name, values in arrays.items()}
    result.update(coefficient_names=["intercept", "annual_sin", "annual_cos"] + ["predictor_" + str(i + 1) for i in range(len(train[0]))],
                  coefficients_m3_s=fitted.params.tolist(), residual_df=int(fitted.df_resid),
                  confidence_level=confidence, training_samples=len(observed), forecast_samples=len(future),
                  design_rank=rank, design_condition_number=condition,
                  contains_negative_statistical_output=bool(any(np.any(values < 0) for values in arrays.values())),
                  negative_output_policy="Unconstrained OLS output and intervals are not clipped; no nonnegative physical flow model is claimed.",
                  units={name: "m3/s" for name in arrays})
    result["units"]["coefficients_m3_s"] = "m3/s"
    return result


def priestley_taylor_pet_source_draft(args, output_dir=None):
    """Unregistered until actual PyET source/version/license is bound and checked.

    This calls PyET, never PyETo or a copied Shyft formula. It is intentionally
    not decorated or put in the registrable operation list while review is pending.
    """
    temperature = _vector(args["temperature_degC"], "temperature_degC", 1, 3660, -40, 60)
    net_radiation = _vector(args["net_radiation_MJ_m2_day"], "net_radiation_MJ_m2_day", 1, 3660, 0, 60)
    pressure = _vector(args["pressure_kPa"], "pressure_kPa", 1, 3660, 30, 115)
    dates = args["dates"]
    if not isinstance(dates, list) or not len(dates) == len(temperature) == len(net_radiation) == len(pressure):
        reject("Daily dates, temperature, net radiation and pressure must have equal length")
    try:
        parsed = [dt.date.fromisoformat(value) for value in dates]
    except (ValueError, TypeError):
        reject("Dates must be ISO calendar date strings")
    if any((right - left).days != 1 for left, right in zip(parsed, parsed[1:])):
        reject("The limited PyET operation requires a strictly increasing daily series")
    import numpy as np
    import pandas as pd
    import pyet
    index = pd.DatetimeIndex(parsed)
    series = lambda values: pd.Series(values, index=index, dtype=float)
    values = pyet.priestley_taylor(tmean=series(temperature), rn=series(net_radiation),
                                  pressure=series(pressure), alpha=1.26, clip_zero=True)
    if not values.index.equals(index) or not np.isfinite(values.to_numpy()).all() or np.any(values.to_numpy() < 0):
        reject("PyET returned invalid daily PET values or date alignment", "invalid_result")
    return {"dates": list(dates), "pet_mm_day": values.tolist(), "alpha": 1.26,
            "units": {"pet_mm_day": "mm/day", "alpha": "1"}}


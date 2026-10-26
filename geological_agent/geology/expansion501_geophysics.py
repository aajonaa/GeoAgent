"""Bounded upstream geophysics adapters. SOURCE REVISED, NOT VERIFIED.

No installation, network, subprocess, arbitrary callable or GPU entrypoint.
All numerical dependencies are lazy and pinned by collection_contracts.
Stage the matching contribution catalog before calling decorated functions.
Native/JIT dependencies require the parent's private CPU environment; this
module neither configures nor changes accepted worker profiles.
"""
from contextlib import redirect_stdout, redirect_stderr
import math
import warnings

from .collection_contracts import operation, reject


class _E501R6SolverLog:
    """Bounded public solver output; never substitutes a solver."""
    def __init__(self):
        self.parts = []
        self.size = 0

    def write(self, value):
        size = len(value.encode("utf-8"))
        if self.size + size > 32768:
            reject("The fixed solver diagnostic budget was exceeded", "resource_limit")
        self.parts.append(value)
        self.size += size
        return len(value)

    def flush(self):
        return None

    def getvalue(self):
        return "".join(self.parts)


def _e501r6_lsqr_report(text, iteration_limit):
    """Parse only the final public SciPy 1.15.3 report, not rounded norms."""
    import re
    if len(text.encode("utf-8")) > 32768:
        reject("The solver report exceeds its reviewed bound", "invalid_result")
    stops = re.findall(r"(?m)^\s*istop\s*=\s*([0-7])\s+r1norm\s*=", text)
    counts = re.findall(r"(?m)^\s*itn\s*=\s*(\d+)\s+r2norm\s*=", text)
    if text.count("LSQR finished") != 1 or len(stops) != 1 or len(counts) != 1:
        reject("The pinned LSQR termination summary is not observable", "invalid_result")
    stop, iterations = int(stops[0]), int(counts[0])
    if not 1 <= iterations <= iteration_limit or stop == 0:
        reject("The LSQR report contradicts the nonzero coupled system", "invalid_result")
    return {"stop_code": stop, "iterations": iterations}


def _e501r6_scalar(value, name, low, high, integer=False):
    import math
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        reject(name + " must be numeric")
    if integer and not isinstance(value, int):
        reject(name + " must be an integer")
    if not math.isfinite(value) or not low <= value <= high:
        reject(name + " lies outside its finite physical/computational bounds")
    return int(value) if integer else float(value)


def _e501r6_array(value, name, ndim, max_size):
    import numpy as np
    result = np.asarray(value, dtype=float)
    if result.ndim != ndim or result.size == 0 or result.size > max_size:
        reject(name + " has an invalid shape or exceeds its CPU budget")
    if not np.all(np.isfinite(result)):
        reject(name + " must contain finite values")
    return result


@operation("GeoSeismicMarchenkoRedatuming")
def GeoSeismicMarchenkoRedatuming(args):
    """Pinned PyLops Marchenko kernel with public LSQR and coupled-system audit.

    Source authored, not registered: fixed CPU routing and independent scientific
    acceptance remain prerequisites. No upstream solver is patched or replaced.
    """
    import contextlib
    import hashlib
    import numpy as np
    from pylops import Block, BlockDiag, Diagonal, Identity, Roll
    from pylops.waveeqprocessing import Marchenko, MDC

    required = {"reflection_response", "direct_arrival", "traveltime_s", "dt_s",
                "receiver_spacing_m", "max_iterations", "reflection_convention"}
    if set(args) != required:
        reject("Marchenko requires exactly the declared acquisition fields")
    if args["reflection_convention"] != "twice_monopole_vertical_velocity_density":
        reject("The reflection response must use the declared upstream convention")
    dt = _e501r6_scalar(args["dt_s"], "dt_s", 1e-6, 1.0)
    dr = _e501r6_scalar(args["receiver_spacing_m"], "receiver_spacing_m", 0.01, 1000.0)
    limit = _e501r6_scalar(args["max_iterations"], "max_iterations", 1, 200, True)
    reflection = _e501r6_array(args["reflection_response"], "reflection_response", 3, 32768)
    ns, nr, nt = reflection.shape
    if ns != nr or not 1 <= nr <= 8 or not 8 <= nt <= 256:
        reject("Use a collocated square acquisition with 1..8 traces and 8..256 samples")
    direct = _e501r6_array(args["direct_arrival"], "direct_arrival", 2, 2048)
    trav = _e501r6_array(args["traveltime_s"], "traveltime_s", 1, 8)
    if direct.shape != (nr, nt) or trav.shape != (nr,):
        reject("Direct arrivals/traveltimes must share the reflection receiver/time axes")
    if np.any(np.max(np.abs(direct), axis=1) == 0):
        reject("Every receiver requires a nonzero independently supplied direct arrival")
    samples = np.rint(trav / dt).astype(int)
    if np.any(samples < 1) or np.any(samples > nt - 2):
        reject("Direct traveltimes must lie strictly inside the recorded positive-time range")
    if not np.all(np.abs(trav / dt - samples) <= 1e-8):
        reject("This fixed unsmoothed time-window acquisition requires sample-aligned arrivals")
    if np.max(np.abs(reflection)) > 1e9 or np.max(np.abs(direct)) > 1e9:
        reject("Normalized acquisition amplitudes exceed the finite scaling budget")

    kernel = Marchenko(reflection, dt=dt, dr=dr, nfmax=nt, toff=0.0,
                       nsmooth=0, saveRt=True, prescaled=False,
                       fftengine="numpy", dtype="float64")
    nt2 = 2 * nt - 1
    # Residual-only reconstruction of the documented/pinned public block system.
    # The inversion itself is exclusively Marchenko.apply_onepoint below.
    window = np.zeros((nr, nt), dtype=float)
    for receiver, arrival in enumerate(samples):
        window[receiver, :arrival] = 1.0
    window = np.hstack((np.fliplr(window), window[:, 1:]))
    wop = Diagonal(window.T.ravel())
    rop = MDC(kernel.Rtwosided_fft, nt2, nv=1, dt=dt, dr=dr,
              twosided=True, conj=False, fftengine="numpy", saveGt=True,
              prescaled=False, usematmul=False)
    r1op = MDC(kernel.Rtwosided_fft, nt2, nv=1, dt=dt, dr=dr,
               twosided=True, conj=True, fftengine="numpy", saveGt=True,
               prescaled=False, usematmul=False)
    roll = Roll((nt2, ns), axis=0, shift=-1, dtype="float64")
    identity = Identity(nr * nt2)
    mop = Block([[identity, -wop * rop],
                 [-wop * roll * r1op, identity]]) * BlockDiag([wop, wop])
    fd = np.concatenate((np.fliplr(direct).T, np.zeros((nt - 1, nr))))
    rhs_first = (wop * rop) @ fd.ravel()
    rhs = np.concatenate((rhs_first, np.zeros(nt2 * nr)))
    rhs_norm = float(np.linalg.norm(rhs))
    if not np.isfinite(rhs_norm) or rhs_norm <= np.finfo(float).tiny:
        reject("No illuminated coupled right-hand side: an inverse-solver termination audit is undefined")

    log = _E501R6SolverLog()
    with contextlib.redirect_stdout(log):
        returned = kernel.apply_onepoint(
            trav, G0=direct, rtm=False, greens=True, dottest=False,
            usematmul=False, atol=1e-10, btol=1e-10, conlim=1e8,
            damp=0.0, iter_lim=limit, show=True)
    if len(returned) != 4:
        reject("The pinned Marchenko return signature changed", "invalid_result")
    arrays = [np.asarray(item) for item in returned]
    if any(item.shape != (nr, nt2) or np.iscomplexobj(item) or
           not np.all(np.isfinite(item)) for item in arrays):
        reject("The upstream focusing/Green functions violate their real-valued axes", "invalid_result")
    fminus, fplus, gminus, gplus = arrays
    x = np.concatenate((fminus.T, fplus.T - fd)).ravel()
    residual = np.asarray(mop @ x - rhs)
    first = float(np.linalg.norm(residual[:nt2 * nr]) / rhs_norm)
    second = float(np.linalg.norm(residual[nt2 * nr:]) / rhs_norm)
    normal_rhs = float(np.linalg.norm(mop.H @ rhs))
    normal_residual = float(np.linalg.norm(mop.H @ residual))
    stationarity = normal_residual / max(normal_rhs, np.finfo(float).tiny)
    if not np.all(np.isfinite([first, second, stationarity])):
        reject("The coupled-system diagnostics are nonfinite", "invalid_result")
    report = log.getvalue()
    termination = _e501r6_lsqr_report(report, limit)
    converged = (termination["stop_code"] in (1, 2, 4, 5)
                 and max(first, second, stationarity) <= 1e-7)
    return {
        "values": {"time_s": (np.arange(-(nt - 1), nt) * dt).tolist(),
                   "focusing_upgoing": fminus.tolist(),
                   "focusing_downgoing": fplus.tolist(),
                   "green_upgoing": gminus.tolist(), "green_downgoing": gplus.tolist()},
        "units": {"time_s": "s", "focusing_upgoing": "normalized amplitude",
                  "focusing_downgoing": "normalized amplitude",
                  "green_upgoing": "normalized amplitude",
                  "green_downgoing": "normalized amplitude",
                  "coupled_relative_residuals": "1"},
        "diagnostics": {
            "method": "pylops.waveeqprocessing.Marchenko.apply_onepoint",
            "convergence": "coupled_residuals_satisfied" if converged else "not_converged",
            "iterations": termination["iterations"], "stop_code": termination["stop_code"],
            "equation_one_relative_residual": first,
            "equation_two_relative_residual": second,
            "normal_equation_relative_residual": stationarity,
            "relative_residual_limit": 1e-7,
            "solver_report": report,
            "solver_report_sha256": hashlib.sha256(report.encode("utf-8")).hexdigest(),
            "uncertainty": "Not estimated; aperture, direct-wave and calibration errors are not quantified.",
            "warnings": ["Fixed collocated 2-D line acquisition, unsmoothed sample-aligned window.",
                         "Response density must be calibrated for the upstream dt*dr quadrature and doubled monopole-to-vertical-velocity convention.",
                         "Numerical residual satisfaction is not physical inversion uniqueness or external certification."]},
        "artifacts": [], "provenance": {}}


@operation("GeoSeismicTraveltimeTomography")
def GeoSeismicTraveltimeTomography(args):
    """Pinned pyGIMLi Dijkstra tomography; private CPU/profile gate remains open."""
    import numpy as np
    import pygimli as pg
    from pygimli.physics.traveltime import TravelTimeManager

    required = {"x_nodes_m", "elevation_nodes_m", "sensors_x_elevation_m",
                "source_indices", "receiver_indices", "traveltime_s",
                "uncertainty_s", "initial_velocity_m_s", "velocity_bounds_m_s",
                "regularization", "max_iterations"}
    if set(args) != required:
        reject("Tomography requires exactly the declared mesh, survey and uncertainty fields")
    x = _e501r6_array(args["x_nodes_m"], "x_nodes_m", 1, 17)
    z = _e501r6_array(args["elevation_nodes_m"], "elevation_nodes_m", 1, 17)
    if min(len(x), len(z)) < 3 or np.any(np.diff(x) <= 0) or np.any(np.diff(z) <= 0):
        reject("Mesh axes must be strictly increasing with at least three nodes each")
    if (len(x) - 1) * (len(z) - 1) > 128:
        reject("The fixed CPU mesh is limited to 128 cells")
    if max(x[-1] - x[0], z[-1] - z[0]) > 10000 or min(np.diff(x).min(), np.diff(z).min()) < 0.1:
        reject("Mesh extent must be <=10 km and all cell widths >=0.1 m")
    sensors = _e501r6_array(args["sensors_x_elevation_m"], "sensors_x_elevation_m", 2, 64)
    if sensors.shape[1] != 2 or not 4 <= len(sensors) <= 32:
        reject("Provide 4..32 two-coordinate crosshole sensors")
    if len({tuple(row) for row in sensors.tolist()}) != len(sensors):
        reject("Sensor coordinates must be unique")
    for sx, sz in sensors:
        if sx not in (x[0], x[-1]) or not np.any(z == sz):
            reject("Sensors must occupy nodes on the two opposite vertical mesh boundaries")
    source_raw, receiver_raw = args["source_indices"], args["receiver_indices"]
    if not isinstance(source_raw, list) or not isinstance(receiver_raw, list):
        reject("Survey indices must be JSON arrays")
    if any(isinstance(v, bool) or not isinstance(v, int) for v in source_raw + receiver_raw):
        reject("Survey indices must be integers, not rounded coordinates")
    source = np.asarray(source_raw, dtype=int)
    receiver = np.asarray(receiver_raw, dtype=int)
    times = _e501r6_array(args["traveltime_s"], "traveltime_s", 1, 256)
    errors = _e501r6_array(args["uncertainty_s"], "uncertainty_s", 1, 256)
    if not 4 <= len(times) <= 256 or source.shape != times.shape or receiver.shape != times.shape or errors.shape != times.shape:
        reject("All survey arrays must contain the same 4..256 observations")
    if np.any(source < 0) or np.any(receiver < 0) or np.any(source >= len(sensors)) or np.any(receiver >= len(sensors)):
        reject("A survey index is outside the fixed sensor array")
    if np.any(sensors[source, 0] == sensors[receiver, 0]):
        reject("Each crosshole ray must connect opposite vertical boundaries")
    if len(set(zip(source_raw, receiver_raw))) != len(times):
        reject("Repeated directed source/receiver pairs are not accepted")
    if np.any(times <= 0) or np.any(times > 120) or np.any(errors <= 0) or np.any(errors > 0.5 * times):
        reject("Traveltimes must be in (0,120] s and explicit errors in (0,0.5*time]")
    bounds = _e501r6_array(args["velocity_bounds_m_s"], "velocity_bounds_m_s", 1, 2)
    if bounds.shape != (2,) or not 100 <= bounds[0] < bounds[1] <= 10000:
        reject("Velocity bounds must be ordered within 100..10000 m/s")
    initial = _e501r6_scalar(args["initial_velocity_m_s"], "initial_velocity_m_s", bounds[0], bounds[1])
    if not bounds[0] < initial < bounds[1]:
        reject("Initial velocity must lie strictly inside the physical bounds")
    regularization = _e501r6_scalar(args["regularization"], "regularization", 1e-6, 1e6)
    limit = _e501r6_scalar(args["max_iterations"], "max_iterations", 1, 30, True)
    distances = np.linalg.norm(sensors[source] - sensors[receiver], axis=1)
    if np.any(times + 3 * errors < distances / bounds[1]):
        reject("A traveltime is faster than the maximum-velocity straight-line lower bound")

    data = pg.DataContainer()
    data.registerSensorIndex("s")
    data.registerSensorIndex("g")
    for sx, sz in sensors:
        data.createSensor([float(sx), float(sz), 0.0])
    data.resize(len(times))
    data["s"], data["g"] = source, receiver
    data["t"], data["err"] = times, errors
    data["valid"] = np.ones(len(times))
    mesh = pg.meshtools.createGrid(x=x, y=z, marker=2)
    manager = TravelTimeManager(data=data, verbose=False)
    manager.fop.setThreadCount(2)
    history, final_state = [], {}

    def audit_step(iteration, inversion):
        # Public observer only. Never modifies the optimizer, model, or stopping.
        iteration = int(iteration)
        if len(history) >= limit + 1 or iteration != len(history):
            reject("Unexpected upstream iteration sequence", "invalid_result")
        predicted = np.asarray(inversion.response, dtype=float).copy()
        chi2, phi = float(inversion.chi2()), float(inversion.phi())
        if predicted.shape != times.shape or not np.all(np.isfinite(predicted)) or np.any(predicted <= 0):
            reject("Upstream traveltime response is invalid", "invalid_result")
        if not np.all(np.isfinite([chi2, phi])) or min(chi2, phi) < 0:
            reject("Upstream iteration objectives are invalid", "invalid_result")
        history.append({"iteration": iteration, "chi2": chi2, "objective": phi})
        final_state["predicted"] = predicted

    manager.inv.setPostStep(audit_step)
    # This manager accepts a slowness starting model, but returns mapped velocity.
    velocity = np.asarray(manager.invert(
        data=data, mesh=mesh, useGradient=False, secNodes=2,
        startModel=1.0 / initial, limits=bounds.tolist(),
        lam=regularization, lambdaFactor=1.0, maxIter=limit, dPhi=1.0,
        stopAtChi1=True, robustData=False, blockyModel=False,
        showProgress=False, verbose=False), dtype=float)
    centers = np.asarray(manager.paraDomain.cellCenters(), dtype=float)
    if velocity.ndim != 1 or not 1 <= len(velocity) <= 128 or centers.shape != (len(velocity), 3):
        reject("The mapped cell/velocity layout is invalid", "invalid_result")
    if not np.all(np.isfinite(centers)) or not np.all(np.isfinite(velocity)) or np.any(velocity < bounds[0]) or np.any(velocity > bounds[1]):
        reject("The inverted velocities violate their physical bounds", "invalid_result")
    if len(history) < 2:
        reject("The upstream inversion did not expose a completed iteration", "invalid_result")
    predicted = final_state["predicted"]
    residual = predicted - times
    weighted = residual / errors
    chi2 = float(np.mean(weighted ** 2))
    if not np.isfinite(chi2) or abs(chi2 - history[-1]["chi2"]) > 1e-8 * max(1.0, chi2):
        reject("Independent weighted residual and upstream chi2 disagree", "invalid_result")
    if history[-1]["chi2"] <= 1:
        observed = "noise_discrepancy_condition_observed"
    elif history[-1]["iteration"] > 2 and history[-2]["objective"] > 0 and history[-1]["objective"] / history[-2]["objective"] > 0.99:
        observed = "objective_stagnation_condition_observed"
    elif history[-1]["iteration"] == limit:
        observed = "iteration_budget_reached"
    else:
        observed = "unclassified_upstream_return"
    return {
        "values": {"cell_centers_x_elevation_m": centers[:, :2].tolist(),
                   "velocity_m_s": velocity.tolist(),
                   "predicted_traveltime_s": predicted.tolist(),
                   "residual_s": residual.tolist(),
                   "standardized_residual": weighted.tolist()},
        "units": {"cell_centers_x_elevation_m": "m", "velocity_m_s": "m/s",
                  "predicted_traveltime_s": "s", "residual_s": "s",
                  "standardized_residual": "1", "chi2": "1"},
        "diagnostics": {
            "method": "pygimli.physics.traveltime.TravelTimeManager.invert",
            "convergence": "not_certified", "termination_condition_observed": observed,
            "upstream_stop_code": None, "iterations": history[-1]["iteration"],
            "chi2": chi2, "iteration_history": history,
            "uncertainty": "Input observation errors only; posterior model covariance and resolution are not estimated.",
            "warnings": ["Fixed 2-D crosshole quadrilateral mesh and two Dijkstra secondary nodes.",
                         "Observed stopping conditions are not a fabricated upstream success code.",
                         "ClassicInversion can catch an internal step RuntimeError; numerical acceptance and diagnostic logs remain necessary.",
                         "Regularized velocity is nonunique where ray coverage is insufficient."]},
        "artifacts": [], "provenance": {}}


def _np():
    import numpy as np
    return np


def _array(value, ndim=None, shape=None):
    np = _np()
    x = np.asarray(value, dtype=float)
    if x.size > 131072 or not np.isfinite(x).all():
        reject("Finite arrays of at most 131072 elements are required")
    if ndim is not None and x.ndim != ndim:
        reject("Array dimensionality does not match the declared contract")
    if shape is not None and x.shape != tuple(shape):
        reject("Related arrays have inconsistent shapes")
    return x


def _real(value, shape=None):
    np = _np()
    x = np.asarray(value)
    if np.iscomplexobj(x):
        if not np.isfinite(x).all() or np.max(np.abs(x.imag), initial=0) > 1e-9 * max(1.0, float(np.max(np.abs(x.real), initial=0))):
            reject("Upstream returned a non-real physical result", "invalid_result")
        x = x.real
    if x.size > 262144 or not np.isfinite(x).all():
        reject("Upstream returned nonfinite or excessive output", "invalid_result")
    if shape is not None and x.shape != tuple(shape):
        reject("Upstream returned an unexpected shape", "invalid_result")
    return x.tolist()


def _result(values, units, method, **diagnostics):
    detail = dict(method=method, convergence="not_applicable", iterations=None,
                  weighted_rms=None, residual_l2=None, stationarity_inf=None,
                  warnings=[], uncertainty="Not estimated; supplied measurements and model assumptions remain conditional.")
    detail.update(diagnostics)
    return dict(values=values, units=units, diagnostics=detail)


def _ordered(value, minimum=2, uniform=False):
    np = _np()
    x = _array(value, 1)
    if len(x) < minimum or np.any(np.diff(x) <= 0):
        reject("Coordinates/times must be strictly increasing")
    if uniform and not np.allclose(np.diff(x), x[1] - x[0], rtol=1e-9, atol=1e-10):
        reject("This upstream operation requires uniform sampling")
    return x


def _same_points(value):
    x = _array(value, 2)
    if x.shape[1] != 3:
        reject("Coordinates must have three explicitly ordered components")
    return x


def _trace(values, dt, index=0, channel="BHZ", start=0):
    from obspy import Trace, UTCDateTime
    t = Trace(_array(values, 1).copy())
    t.stats.delta = dt
    t.stats.starttime = UTCDateTime(start)
    t.stats.network = "XX"
    t.stats.station = "S%03d" % index
    t.stats.location = "00"
    t.stats.channel = channel
    return t


def _paz(args):
    np = _np()
    def roots(name):
        raw = args[name]
        if not raw:
            return np.empty(0, dtype=complex)
        x = _array(raw, 2)
        if x.shape[1] != 2:
            reject("Pole/zero rows must be [real, imaginary] in rad/s")
        z = x[:, 0] + 1j * x[:, 1]
        remaining = list(z)
        while remaining:
            v = remaining.pop()
            if abs(v.imag) <= 1e-12:
                continue
            match = next((i for i, w in enumerate(remaining) if abs(w - v.conjugate()) <= 1e-9 * max(1.0, abs(v))), None)
            if match is None:
                reject("Real instrument responses require conjugate pole/zero pairs")
            remaining.pop(match)
        return z
    poles, zeros = roots("poles_rad_s"), roots("zeros_rad_s")
    if np.any(poles.real >= 0):
        reject("Instrument poles must be strictly stable")
    duration = (len(args["counts"]) - 1) * args["dt_s"]
    if args["epoch_start_s"] > args["record_start_s"] or args["epoch_end_s"] < args["record_start_s"] + duration:
        reject("One supplied response epoch must cover the complete waveform")
    return poles, zeros


@operation("GeoSeismicInstrumentDeconvolution")
def seismic_instrument_deconvolution(args):
    from obspy.core.inventory.response import Response
    np = _np()
    poles, zeros = _paz(args)
    pf = _ordered(args["prefilter_hz"], 4)
    if len(pf) != 4 or pf[0] <= 0 or pf[-1] >= 0.5 / args["dt_s"]:
        reject("Four ordered prefilter corners must lie strictly inside Nyquist")
    response = Response.from_paz(zeros.tolist(), poles.tolist(), args["sensitivity_counts_per_m_s"],
        stage_gain_frequency=args["reference_frequency_hz"], input_units="M/S", output_units="COUNTS",
        normalization_frequency=args["reference_frequency_hz"], normalization_factor=args["normalization_factor"])
    if not np.isclose(response.instrument_sensitivity.value, args["sensitivity_counts_per_m_s"], rtol=0.01):
        reject("Supplied PZ normalization and reference sensitivity disagree")
    tr = _trace(args["counts"], args["dt_s"], start=args["record_start_s"])
    tr.stats.response = response
    tr.remove_response(output="VEL", pre_filt=pf.tolist(), water_level=args["water_level_db"],
                       zero_mean=True, taper=True, taper_fraction=0.05, plot=False)
    return _result({"velocity_m_s": _real(tr.data, (len(args["counts"]),)), "dt_s": args["dt_s"]},
        {"velocity_m_s": "m/s", "dt_s": "s"}, "ObsPy single-stage stable PZ response removal",
        warnings=["Caller-declared epoch and calibration, not independently authenticated. Mean removal and 5% cosine taper are explicit; prefilter/water-level limit usable bandwidth."])


@operation("GeoEMLayeredBipoleResponse")
def em_layered_bipole_response(args):
    import empymod
    np = _np()
    depth = _ordered(args["interfaces_depth_m"], 1)
    res = _array(args["horizontal_resistivity_ohm_m"], 1, (len(depth) + 1,))
    aniso = _array(args["anisotropy_sqrt_rhov_rhoh"], 1, res.shape)
    src = _array(args["source_endpoints_end_m"], 2, (2, 3))
    rec = _array(args["receivers_end_azimuth_dip"], 2)
    f = _ordered(args["frequency_hz"], 1)
    if rec.shape[1] != 5 or np.any(res <= 0) or np.any(aniso <= 0):
        reject("Invalid VTI electrical model or receiver geometry")
    segment = src[1] - src[0]
    length2 = float(segment @ segment)
    if length2 < 1 or np.searchsorted(depth, src[0, 2]) != np.searchsorted(depth, src[1, 2]):
        reject("Finite source must be at least 1 m and stay in one layer")
    near = src[0] + np.clip((rec[:, :3] - src[0]) @ segment / length2, 0, 1)[:, None] * segment
    if np.any(np.linalg.norm(rec[:, :3] - near, axis=1) < 1):
        reject("Receivers must be at least 1 m from the finite source")
    if np.any(np.abs(np.r_[src[:, 2], rec[:, 2]][:, None] - depth) < 0.001):
        reject("Sources and receivers cannot lie on an electrical interface")
    field = empymod.bipole(src=[src[0, 0], src[1, 0], src[0, 1], src[1, 1], src[0, 2], src[1, 2]],
        rec=list(rec.T), depth=depth, res=res, freqtime=f, aniso=aniso,
        signal=None, msrc=False, mrec=False, srcpts=5, recpts=1, strength=args["current_a"],
        ht="dlf", verb=0, squeeze=False)
    field = np.asarray(field)
    if field.shape != (len(f), len(rec), 1) or not np.isfinite(field).all():
        reject("EM transform returned incomplete/nonfinite fields", "invalid_result")
    return _result({"electric_real_v_m": _real(field[:, :, 0].real), "electric_imag_v_m": _real(field[:, :, 0].imag)},
        {"electric_real_v_m": "V/m", "electric_imag_v_m": "V/m"}, "empymod finite electric bipole, frequency-domain VTI",
        warnings=["East-North-Depth coordinates, positive depth down; five-point finite-source quadrature. Transform/quadrature truncation uncertainty is not estimated."])


@operation("GeoGravityTesseroid")
def gravity_tesseroid(args):
    import harmonica as hm
    np = _np()
    obs = _same_points(args["observations_lon_lat_radius"])
    cells = _array(args["tesseroids_wesnbt"], 2)
    rho = _array(args["density_contrast_kg_m3"], 1, (len(cells),))
    if cells.shape[1] != 6 or np.any(obs[:, 2] <= 0):
        reject("Expected spherical coordinates and six tesseroid bounds")
    for w, e, s, n, b, t in cells:
        if not (-180 <= w < e <= 180 and -90 <= s < n <= 90 and 1e6 <= b < t <= 1e7):
            reject("Invalid non-wrapping spherical tesseroid")
        if e - w < .01 or n - s < .01 or t - b < 100:
            reject("Tesseroid dimensions fall below this bounded integration profile")
        inside = (obs[:, 0] >= w) & (obs[:, 0] <= e) & (obs[:, 1] >= s) & (obs[:, 1] <= n) & (obs[:, 2] >= b) & (obs[:, 2] <= t)
        if inside.any():
            reject("Observers cannot be inside or on a source tesseroid")
    pot = hm.tesseroid_gravity(tuple(obs.T), cells, rho, field="potential", parallel=False)
    down = hm.tesseroid_gravity(tuple(obs.T), cells, rho, field="g_z", parallel=False) * 1e-5
    return _result({"potential_j_kg": _real(pot, (len(obs),)), "gravity_radial_down_m_s2": _real(down, (len(obs),))},
        {"potential_j_kg": "J/kg", "gravity_radial_down_m_s2": "m/s^2"}, "Harmonica adaptive tesseroid quadrature",
        warnings=["Geocentric spherical latitude/radius, not geodetic height. Signed density contrast; no inferred geological body."])


@operation("GeoPotentialEulerSourceLocation")
def potential_euler_source_location(args):
    import harmonica as hm
    np = _np()
    xyz = _same_points(args["observations_enu_m"])
    field = _array(args["field"], 1, (len(xyz),))
    grad = _array(args["gradient_enu_per_m"], 2, xyz.shape)
    design = np.column_stack((grad, np.full(len(xyz), args["structural_index"])))
    scale = np.linalg.norm(design, axis=0)
    if len(xyz) <= 4 or np.any(scale == 0) or np.linalg.cond(design / scale) > 1e8:
        reject("Euler source recovery requires a full-rank, well-conditioned data window")
    fit = hm.EulerDeconvolution(structural_index=args["structural_index"]).fit(tuple(xyz.T), (field, *grad.T))
    residual = np.sum((xyz - fit.location_) * grad, axis=1) - args["structural_index"] * (fit.base_level_ - field)
    return _result({"source_enu_m": _real(fit.location_, (3,)), "base_level": float(fit.base_level_), "euler_residual": _real(residual)},
        {"source_enu_m": "m", "base_level": args["field_unit"], "euler_residual": args["field_unit"]},
        "Harmonica Euler homogeneity least squares", residual_l2=float(np.linalg.norm(residual)),
        uncertainty="Structural-index dependent ideal-source estimate; residual is not calibrated position uncertainty.")


def _layers(args):
    np = _np()
    x = _array(args["layers_h_vp_vs_rho_si"], 2)
    if x.shape[1] != 4 or len(x) < 2 or len(x) > 32:
        reject("Provide 2..32 solid layers: thickness m, Vp/Vs m/s, density kg/m^3")
    if np.any(x[:-1, 0] <= 0) or x[-1, 0] != 0 or np.any(x[:, 1:] <= 0):
        reject("Positive finite layers must end with a zero-thickness halfspace marker")
    if np.any(x[:, 1] ** 2 <= 4 * x[:, 2] ** 2 / 3):
        reject("Positive bulk and shear moduli are required; fluid layers are outside this profile")
    if np.max(x[:, 1]) > 15000 or np.max(x[:, 3]) > 15000 or np.sum(x[:, 0]) > 1e6:
        reject("Layered model exceeds the physical/resource profile")
    return x, x / 1000.0


@operation("GeoSurfaceWaveDispersion")
def surface_wave_dispersion(args):
    from disba import PhaseDispersion, GroupDispersion
    np = _np()
    _, model = _layers(args)
    periods = _ordered(args["period_s"], 1)
    phase = PhaseDispersion(*model.T, algorithm="dunkin", dc=0.001)(periods, mode=args["mode"], wave=args["wave"])
    group = GroupDispersion(*model.T, algorithm="dunkin", dc=0.001, dt=0.025)(periods, mode=args["mode"], wave=args["wave"])
    if not np.array_equal(phase.period, periods) or not np.array_equal(group.period, periods) or np.any(phase.velocity <= 0) or np.any(group.velocity <= 0):
        reject("Requested mode does not exist/converge at all requested periods", "unsupported_conditions")
    return _result({"phase_velocity_m_s": _real(1000 * phase.velocity), "group_velocity_m_s": _real(1000 * group.velocity)},
        {"phase_velocity_m_s": "m/s", "group_velocity_m_s": "m/s"}, "disba modal phase and group dispersion",
        warnings=["Mode continuity and finite-step group derivative require independent acceptance; absence of a mode is not filled/interpolated."])


@operation("GeoPotentialEquivalentSources")
def potential_equivalent_sources(args):
    import harmonica as hm
    np = _np()
    obs, src, pred = (_same_points(args[k]) for k in ("observations_enu_m", "source_points_enu_m", "prediction_points_enu_m"))
    data = _array(args["field"], 1, (len(obs),))
    error = _array(args["standard_deviation"], 1, data.shape)
    if np.any(error <= 0) or np.max(src[:, 2]) >= min(np.min(obs[:, 2]), np.min(pred[:, 2])) - 1:
        reject("Errors must be positive; equivalent sources must be >=1 m below all evaluation points")
    if len(np.unique(src, axis=0)) != len(src):
        reject("Equivalent source coordinates must be unique")
    fit = hm.EquivalentSources(points=tuple(src.T), damping=args["damping"], parallel=False, dtype="float64")
    fit.fit(tuple(obs.T), data, weights=1.0 / error ** 2)
    residual = fit.predict(tuple(obs.T)) - data
    output = fit.predict(tuple(pred.T))
    return _result({"predicted_field": _real(output, (len(pred),)), "observation_residual": _real(residual)},
        {"predicted_field": args["field_unit"], "observation_residual": args["field_unit"]},
        "Harmonica damped equivalent sources", weighted_rms=float(np.sqrt(np.mean((residual / error) ** 2))),
        uncertainty="Equivalent sources interpolate harmonic fields; coefficients are not subsurface density or susceptibility.")


def _grid(args):
    import xarray as xr
    x = _ordered(args["easting_m"], 4, True)
    y = _ordered(args["northing_m"], 4, True)
    data = _array(args["field_grid"], 2, (len(y), len(x)))
    if not args["periodic_grid_acknowledged"]:
        reject("Finite Fourier grids require explicit periodic-boundary acknowledgement")
    return xr.DataArray(data, coords={"northing": y, "easting": x}, dims=("northing", "easting"))


@operation("GeoPotentialUpwardContinuation")
def potential_upward_continuation(args):
    import harmonica as hm
    grid = _grid(args)
    value = hm.upward_continuation(grid, height_displacement=args["height_displacement_m"])
    return _result({"continued_field": _real(value.values, grid.shape)}, {"continued_field": args["field_unit"]},
        "Harmonica spectral upward continuation", warnings=["Periodic boundary, no padding or downward continuation; edge effects remain caller-visible."])


@operation("GeoMagneticReductionToPole")
def magnetic_reduction_to_pole(args):
    import harmonica as hm
    grid = _grid(args)
    if abs(args["field_inclination_deg"]) < 10 or abs(args["magnetization_inclination_deg"]) < 10:
        reject("Near-equatorial RTP is ill-conditioned; no unreviewed stabilization is substituted", "unsupported_conditions")
    value = hm.reduction_to_pole(grid, inclination=args["field_inclination_deg"], declination=args["field_declination_deg"],
        magnetization_inclination=args["magnetization_inclination_deg"], magnetization_declination=args["magnetization_declination_deg"])
    return _result({"pole_anomaly_nt": _real(value.values, grid.shape)}, {"pole_anomaly_nt": "nT"},
        "Harmonica reduction to pole", warnings=["Inclination positive down, declination clockwise from north; field and magnetization directions are supplied, not inferred."])


@operation("GeoDCFourElectrodeResponse")
def dc_four_electrode_response(args):
    from geoana.em.static import DipoleHalfSpace
    np = _np()
    ab = _array(args["current_electrodes_enu_m"], 2, (2, 3))
    mn = _array(args["potential_pairs_enu_m"], 3)
    if mn.shape[1:] != (2, 3) or np.any(ab[:, 2] > 0) or np.any(mn[:, :, 2] > 0):
        reject("Homogeneous halfspace occupies z<=0; provide paired potential electrodes")
    if np.linalg.norm(ab[0] - ab[1]) < .001 or np.any(np.linalg.norm(mn[:, 0] - mn[:, 1], axis=1) < .001):
        reject("Each electrode pair must be distinct")
    if np.any(np.linalg.norm(mn[:, :, None, :] - ab[None, None, :, :], axis=-1) < .001):
        reject("Potential electrodes must not coincide with current electrodes")
    model = DipoleHalfSpace(rho=args["resistivity_ohm_m"], current=args["current_a"], location_a=ab[0], location_b=ab[1])
    voltage = model.potential(mn[:, 0], mn[:, 1])
    return _result({"voltage_m_minus_n_v": _real(voltage, (len(mn),))}, {"voltage_m_minus_n_v": "V"},
        "Geoana four-electrode homogeneous halfspace", warnings=["Current enters A and exits B; signed voltage is M minus N. No apparent-resistivity inversion."])


@operation("GeoGravityNormalEllipsoid")
def gravity_normal_ellipsoid(args):
    from boule import WGS84
    xyz = _same_points(args["geodetic_lon_lat_height"])
    np = _np()
    if np.any(abs(xyz[:, 0]) > 180) or np.any(abs(xyz[:, 1]) > 90) or np.any(xyz[:, 2] < 0):
        reject("Use longitude/latitude degrees and nonnegative WGS84 ellipsoidal height m")
    value = WGS84.normal_gravity(tuple(xyz.T), coordinate_system="geodetic", si_units=True)
    return _result({"normal_gravity_m_s2": _real(value, (len(xyz),))}, {"normal_gravity_m_s2": "m/s^2"},
        "Boule WGS84 normal gravity including centrifugal acceleration",
        warnings=["Ellipsoidal height is not orthometric elevation; no geoid or terrain corrections are imputed."])


@operation("GeoSeismicArrayBeamforming")
def seismic_array_beamforming(args):
    from obspy import Stream
    from obspy.core.util import AttribDict
    from obspy.signal.array_analysis import array_processing
    np = _np()
    xyz = _same_points(args["station_enu_m"])
    data = _array(args["velocity_station_time_m_s"], 2)
    if data.shape[0] != len(xyz) or np.linalg.matrix_rank(xyz[:, :2] - xyz[0, :2]) < 2:
        reject("At least three noncollinear synchronized stations are required")
    dt = args["dt_s"]
    if not (0 < args["fmin_hz"] < args["fmax_hz"] < .5 / dt):
        reject("Beamforming frequency band must lie inside Nyquist")
    if args["window_s"] < 2 / args["fmin_hz"] or args["window_s"] > (data.shape[1] - 1) * dt:
        reject("Beamforming window must contain >=2 low-frequency cycles and fit the record")
    span = args["slowness_bound_s_km"]
    step = args["slowness_step_s_km"]
    if 2 * span / step > 40 or np.any(np.std(data, axis=1) == 0):
        reject("Slowness search exceeds 41x41 or contains a constant station")
    stream = Stream([_trace(row, dt, i) for i, row in enumerate(data)])
    for tr, coord in zip(stream, xyz / 1000):
        tr.stats.coordinates = AttribDict(x=coord[0], y=coord[1], elevation=coord[2])
    result = array_processing(stream, win_len=args["window_s"], win_frac=.5,
        sll_x=-span, slm_x=span, sll_y=-span, slm_y=span, sl_s=step,
        semb_thres=-1, vel_thres=-1e9, frqlow=args["fmin_hz"], frqhigh=args["fmax_hz"],
        stime=stream[0].stats.starttime, etime=stream[0].stats.endtime,
        prewhiten=0, verbose=False, coordsys="xy", timestamp="julsec", method=0)
    result = np.asarray(result)
    if result.size == 0:
        reject("No complete beamforming windows", "empty_input")
    if result.ndim != 2 or result.shape[1] != 5:
        reject("Unexpected beamformer output", "invalid_result")
    result[:, 3] %= 360
    return _result({"time_relpow_abspow_backaz_slowness": _real(result)},
        {"time_relpow_abspow_backaz_slowness": "s,1,unnormalized spectral (m/s)^2,degree,s/km"},
        "ObsPy conventional frequency-domain array beamforming", warnings=["Local ENU converted to km for ObsPy; synchronized/calibrated records required. Spatial aliasing and multiple arrivals remain ambiguous."])


@operation("GeoSeismicSTALTADetection")
def seismic_sta_lta_detection(args):
    from obspy.signal.trigger import classic_sta_lta, trigger_onset
    np = _np()
    data = _array(args["amplitude"], 1)
    if not (1 <= args["sta_samples"] < args["lta_samples"] < len(data)) or args["on_ratio"] <= args["off_ratio"]:
        reject("Require STA<LTA<record and on threshold > off threshold")
    ratio = classic_sta_lta(data, args["sta_samples"], args["lta_samples"])
    windows = np.asarray(trigger_onset(ratio, args["on_ratio"], args["off_ratio"]), dtype=int).reshape(-1, 2)
    return _result({"sta_lta_ratio": _real(ratio), "on_off_sample_inclusive": windows.tolist()},
        {"sta_lta_ratio": "1", "on_off_sample_inclusive": "sample index"}, "ObsPy classic energy STA/LTA and hysteretic onset",
        warnings=["Initial LTA warm-up is not usable detection support; thresholds are not calibrated event probabilities."])


@operation("GeoSeismicTemplateDetection")
def seismic_template_detection(args):
    from obspy import Stream
    from obspy.signal.cross_correlation import correlation_detector
    np = _np()
    data, template = _array(args["data_channel_time"], 2), _array(args["template_channel_time"], 2)
    if data.shape[0] != template.shape[0] or template.shape[1] >= data.shape[1] or np.any(np.std(template, axis=1) == 0):
        reject("Each template channel must vary and be shorter than its matching data channel")
    stream = Stream([_trace(row, args["dt_s"], i) for i, row in enumerate(data)])
    templates = Stream([_trace(row, args["dt_s"], i) for i, row in enumerate(template)])
    detections, similarity = correlation_detector(stream, templates, heights=args["minimum_similarity"],
        distance=args["minimum_separation_s"], details=False, plot=None, method="direct")
    if not similarity or similarity[0] is None:
        reject("Template correlation has no overlapping channels", "empty_input")
    rows = [[float(item["time"]), float(item["similarity"])] for item in detections]
    return _result({"time_s_similarity": rows, "similarity": _real(similarity[0].data)},
        {"time_s_similarity": "s,1", "similarity": "1"}, "ObsPy multichannel mean normalized correlation detector",
        warnings=["Detection time is template-start alignment relative to record start; no magnitude or event-type inference."])


@operation("GeoSeismicPolarization")
def seismic_polarization(args):
    from obspy import Stream
    from obspy.signal.polarization import flinn
    np = _np()
    data = _array(args["displacement_zne_m"], 2)
    if data.shape[1] != 3 or np.sum((data - data.mean(axis=0)) ** 2) == 0:
        reject("Three varying Z,N,E displacement components are required")
    stream = Stream([_trace(data[:, i], args["dt_s"], channel=c) for i, c in enumerate(("BHZ", "BHN", "BHE"))])
    az, inc, rect, plan = flinn(stream, noise_thres=0)
    if not (0 <= rect <= 1 + 1e-9 and 0 <= plan <= 1 + 1e-9):
        reject("Polarization shape metrics outside physical range", "invalid_result")
    return _result({"azimuth_deg": float(az), "incidence_deg": float(inc), "rectilinearity": float(rect), "planarity": float(plan)},
        {"azimuth_deg": "degree", "incidence_deg": "degree", "rectilinearity": "1", "planarity": "1"},
        "ObsPy Flinn particle-motion eigensystem", warnings=["Axis direction has a 180-degree ambiguity; one supplied signal window, not automatic phase identification."])


@operation("GeoSeismicTauPRays")
def seismic_taup_rays(args):
    from obspy.taup import TauPyModel
    np = _np()
    model = TauPyModel(model="iasp91")
    arrivals = model.get_ray_paths(source_depth_in_km=args["source_depth_km"], distance_in_degree=args["distance_deg"], phase_list=args["phases"])
    if len(arrivals) > 64:
        reject("Ray result exceeds 64 arrivals", "resource_limit")
    rows = []
    for arr in arrivals:
        if len(arr.path) > 4096:
            reject("Ray path exceeds 4096 samples", "resource_limit")
        rows.append(dict(phase=arr.name, time_s=float(arr.time), ray_parameter_s_degree=float(arr.ray_param_sec_degree),
            takeoff_deg=float(arr.takeoff_angle), incidence_deg=float(arr.incident_angle),
            path_time_distance_depth=_real(np.column_stack((arr.path["time"], np.rad2deg(arr.path["dist"]), arr.path["depth"])))))
    return _result({"arrivals": rows}, {"arrivals": "time s; ray parameter s/degree; angles degree; path depth km"},
        "ObsPy TauP rays in the bundled iasp91 model", warnings=["Fixed packaged iasp91 reference, no untrusted pickle/NPZ loading and no remote velocity-model retrieval. Empty arrivals means phase absence, not zero travel time."])


@operation("GeoSeismicNMO")
def seismic_nmo(args):
    from bruges.transform.nmo import nmo_correction
    np = _np()
    data = _array(args["cmp_time_offset"], 2)
    offsets = _array(args["offset_m"], 1, (data.shape[1],))
    velocity = _array(args["nmo_velocity_m_s"], 1, (data.shape[0],))
    if np.any(velocity <= 0):
        reject("NMO velocities must be strictly positive")
    nmo = nmo_correction(data, args["dt_s"], offsets, velocity)
    t0 = np.arange(len(data)) * args["dt_s"]
    travel = np.sqrt(t0[:, None] ** 2 + (offsets[None, :] / velocity[:, None]) ** 2)
    before = np.floor(travel / args["dt_s"]).astype(int)
    valid = (before >= 1) & (before + 2 < len(data))
    return _result({"nmo_amplitude": _real(nmo, data.shape), "valid_support": valid.tolist()},
        {"nmo_amplitude": "declared normalized seismic amplitude", "valid_support": "boolean"},
        "Bruges hyperbolic NMO with four-sample cubic interpolation",
        warnings=["Upstream zeros outside interpolation support are explicitly masked, not measured zero amplitude; no stretch mute or anisotropic moveout correction."])


@operation("GeoSeismicComplexAttributes")
def seismic_complex_attributes(args):
    from bruges.attribute.complex import instantaneous_amplitude, instantaneous_phase, instantaneous_frequency
    np = _np()
    data = _array(args["amplitude"], 1)
    amp = instantaneous_amplitude(data)
    phase = instantaneous_phase(data)
    with np.errstate(divide="ignore", invalid="ignore"):
        freq = instantaneous_frequency(data, args["dt_s"], kind="so", percentile_clip=100)
    valid = amp > args["amplitude_floor"]
    delta = np.angle(np.exp(1j * np.diff(phase)))
    valid_f = valid[:-1] & valid[1:] & (np.abs(delta) < math.pi / 2 - 1e-8) & np.isfinite(freq)
    return _result({"envelope": _real(amp), "phase_rad": [float(v) if ok else None for v, ok in zip(phase, valid)],
        "interval_frequency_hz": [float(v) if ok else None for v, ok in zip(freq, valid_f)], "frequency_valid": valid_f.tolist()},
        {"envelope": "declared normalized seismic amplitude", "phase_rad": "rad", "interval_frequency_hz": "Hz", "frequency_valid": "boolean"},
        "Bruges analytic trace and Scheuer-Oldenburg interval frequency",
        warnings=["Undefined low-amplitude phase and aliased >=pi/2 phase increments are null, not imputed. Frequency has N-1 interval values; FFT boundary effects remain."])


@operation("GeoSeismicWindowCoherence")
def seismic_window_coherence(args):
    from bruges.attribute.discontinuity import marfurt
    np = _np()
    data = _array(args["inline_crossline_time_window"], 3)
    if data.shape[0] * data.shape[1] < 2 or np.sum(data ** 2) <= 1e-10:
        reject("A nonzero multi-trace window above the upstream epsilon floor is required")
    c = float(marfurt(data))
    if not 0 <= c <= 1 + 1e-10:
        reject("Upstream coherence outside [0,1]", "invalid_result")
    return _result({"coherence": c}, {"coherence": "1"}, "Bruges direct Marfurt analysis-window kernel",
        warnings=["No high-level discontinuity wrapper or implicit spatial window padding; sensitive to alignment and the upstream 1e-12 denominator regularizer."])


@operation("GeoPotentialEdgeAttributes")
def potential_edge_attributes(args):
    import harmonica as hm
    np = _np()
    grid = _grid(args)
    amplitude = np.asarray(hm.total_gradient_amplitude(grid))
    with np.errstate(divide="ignore", invalid="ignore"):
        tilt = np.asarray(hm.tilt_angle(grid))
    valid = amplitude > args["gradient_floor_per_m"]
    if np.any(~np.isfinite(tilt[valid])):
        reject("Nonfinite tilt at nonzero gradient", "invalid_result")
    rows = [[float(v) if ok else None for v, ok in zip(row, mask)] for row, mask in zip(tilt, valid)]
    return _result({"total_gradient": _real(amplitude, grid.shape), "tilt_rad": rows, "tilt_valid": valid.tolist()},
        {"total_gradient": args["field_unit"] + "/m", "tilt_rad": "rad", "tilt_valid": "boolean"},
        "Harmonica total-gradient and tilt edge attributes", warnings=["Edges are interpretation aids, not identified lithological boundaries; zero-gradient tilt is null."])


@operation("GeoSeismicArrayStrainRotation")
def seismic_array_strain_rotation(args):
    from obspy.signal.array_analysis import array_rotation_strain
    np = _np()
    xyz = _same_points(args["station_enu_m"])
    disp = _array(args["displacement_time_station_enu_m"], 3)
    if disp.shape[1:] != xyz.shape or np.linalg.matrix_rank(xyz[:, :2] - xyz[0, :2]) < 2 or np.ptp(xyz[:, 2]) > .001:
        reject("Require a flat, noncollinear array with synchronized ENU displacement components")
    if args["vp_m_s"] ** 2 <= 4 * args["vs_m_s"] ** 2 / 3:
        reject("Elastic free-surface model requires positive bulk/shear moduli")
    with np.errstate(divide="ignore", invalid="ignore"):
        out = array_rotation_strain(np.arange(len(xyz)), disp[:, :, 0], disp[:, :, 1], disp[:, :, 2],
            args["vp_m_s"], args["vs_m_s"], xyz, args["displacement_error_m"])
    strain = np.asarray(out["ts_e"])
    rotation = np.column_stack((out["ts_w1"], out["ts_w2"], out["ts_w3"]))
    if np.max(abs(strain)) > .01 or np.max(abs(rotation)) > .01:
        reject("Recovered deformation exceeds the small-strain/rotation profile", "unsupported_conditions")
    motion = np.sum(np.linalg.norm(disp[:, 1:, :] - disp[:, :1, :], axis=2), axis=1)
    ratio = np.asarray(out["ts_m"])
    if np.any(~np.isfinite(ratio[motion > 0])):
        reject("Undefined array misfit for nonzero differential displacement", "invalid_result")
    return _result({"strain_tensor": _real(strain), "rotation_enu_rad": _real(rotation),
        "misfit_ratio": [float(v) if m > 0 else None for v, m in zip(ratio, motion)],
        "rotation_sigma_rad": _real([out["sigmaw1"], out["sigmaw2"], out["sigmaw3"]])},
        {"strain_tensor": "1", "rotation_enu_rad": "rad", "misfit_ratio": "1", "rotation_sigma_rad": "rad"},
        "ObsPy free-surface small-strain and rotation inference",
        uncertainty="Conditional linear covariance from supplied displacement noise; zero differential-motion misfit ratio is undefined/null.")


@operation("GeoGravityBouguerSlab")
def gravity_bouguer_slab(args):
    import harmonica as hm
    if args["water_density_kg_m3"] >= args["crust_density_kg_m3"]:
        reject("Water density must be below crust density")
    h = _array(args["topography_m"], 1)
    correction = (hm.bouguer_correction(h, density_crust=args["crust_density_kg_m3"], density_water=args["water_density_kg_m3"]) * 1e-5)
    return _result({"slab_correction_mgal": _real(correction, h.shape)}, {"slab_correction_mgal": "mGal"},
        "Harmonica land/bathymetric Bouguer slab", warnings=["Infinite horizontal slab approximation, not a terrain correction. Signed upstream correction is returned, not silently applied to observations."])


@operation("GeoCrustAiryMoho")
def crust_airy_moho(args):
    import harmonica as hm
    np = _np()
    base = _array(args["basement_height_m"], 1)
    if args["mantle_density_kg_m3"] <= args["crust_density_kg_m3"]:
        reject("Mantle density must exceed crust density")
    layers = {}
    for i, layer in enumerate(args["overlying_layers"]):
        thickness = _array(layer["thickness_m"], 1, base.shape)
        if np.any(thickness < 0):
            reject("Overlying layer thickness cannot be negative")
        layers[str(i)] = (thickness, layer["density_kg_m3"])
    depth = hm.isostatic_moho_airy(base, layers=layers, density_crust=args["crust_density_kg_m3"],
        density_mantle=args["mantle_density_kg_m3"], reference_depth=args["reference_depth_m"])
    if np.any(depth <= -base):
        reject("Airy result places Moho above crystalline basement", "unsupported_conditions")
    return _result({"moho_depth_m": _real(depth, base.shape)}, {"moho_depth_m": "m below reference level"},
        "Harmonica Airy mass balance with explicit surface layers", warnings=["Local compensation only; no flexural rigidity, dynamic topography or measured Moho claim."])


@operation("GeoEMConductiveSphere")
def em_conductive_sphere(args):
    from geoana.em.static import ElectrostaticSphere
    np = _np()
    xyz = _same_points(args["observations_enu_m"])
    center = _array(args["center_enu_m"], 1, (3,))
    primary = _array(args["primary_electric_enu_v_m"], 1, (3,))
    if np.linalg.norm(primary) == 0 or np.any(np.abs(np.linalg.norm(xyz - center, axis=1) - args["radius_m"]) < 1e-6):
        reject("Nonzero incident field and off-interface observations are required")
    sphere = ElectrostaticSphere(args["radius_m"], args["sphere_conductivity_s_m"], args["background_conductivity_s_m"], primary_field=primary, location=center)
    return _result({"total_electric_v_m": _real(sphere.electric_field(xyz, field="total"), xyz.shape),
        "secondary_electric_v_m": _real(sphere.electric_field(xyz, field="secondary"), xyz.shape),
        "total_current_a_m2": _real(sphere.current_density(xyz, field="total"), xyz.shape)},
        {"total_electric_v_m": "V/m", "secondary_electric_v_m": "V/m", "total_current_a_m2": "A/m^2"},
        "Geoana conducting sphere in a uniform DC field", warnings=["Wholespace electrostatic conduction, not inductive transient EM; interface-sided fields must be sampled off the boundary."])


@operation("GeoMagneticWirePath")
def magnetic_wire_path(args):
    from geoana.em.static import LineCurrentWholeSpace
    np = _np()
    nodes = _same_points(args["closed_loop_nodes_enu_m"])
    xyz = _same_points(args["observations_enu_m"])
    if not np.array_equal(nodes[0], nodes[-1]):
        reject("Inductive source path must be explicitly closed")
    for p, q in zip(nodes[:-1], nodes[1:]):
        d = q - p
        length2 = float(d @ d)
        if length2 < 1e-6:
            reject("Wire segments must be at least 1 mm long")
        perpendicular = np.linalg.norm(np.cross(xyz - p, d), axis=1) / math.sqrt(length2)
        if np.any(perpendicular < .001):
            reject("Geoana line kernel is singular on segment axes, including their extensions; use off-axis observations", "unsupported_conditions")
    source = LineCurrentWholeSpace(nodes=nodes, current=args["current_a"])
    return _result({"magnetic_enu_t": _real(source.magnetic_flux_density(xyz), xyz.shape)}, {"magnetic_enu_t": "T"},
        "Geoana closed piecewise-linear current-loop magnetic induction", warnings=["Filamentary static-current source; conductor thickness and induced subsurface currents are not modelled."])


@operation("GeoSeismicARPhasePick")
def seismic_ar_phase_pick(args):
    from obspy.signal.trigger import ar_pick
    np = _np()
    data = _array(args["velocity_zne_m_s"], 2)
    if data.shape[1] != 3 or not (0 < args["fmin_hz"] < args["fmax_hz"] < .5 / args["dt_s"]):
        reject("Expected ZNE data and a sub-Nyquist band")
    if np.any(np.std(data, axis=0) == 0) or len(data) * args["dt_s"] < 8:
        reject("AR picking needs three varying components and at least eight seconds")
    p, s = ar_pick(data[:, 0].copy(), data[:, 1].copy(), data[:, 2].copy(), 1 / args["dt_s"],
        args["fmin_hz"], args["fmax_hz"], 1.0, .1, 4.0, 1.0, 2, 8, .1, .2, s_pick=True)
    duration = (len(data) - 1) * args["dt_s"]
    valid_p = math.isfinite(p) and 0 < p <= duration
    valid_s = math.isfinite(s) and 0 < s <= duration and (not valid_p or s >= p)
    return _result({"p_onset_s": float(p) if valid_p else None, "s_onset_s": float(s) if valid_s else None},
        {"p_onset_s": "s from record start", "s_onset_s": "s from record start"}, "ObsPy AR-AIC/STA-LTA phase picker",
        warnings=["Fixed P windows LTA=1s,STA=.1s,order=2,l=.1s; S windows LTA=4s,STA=1s,order=8,l=.2s. Null denotes missing/invalid pick; uncertainty and phase classification are not calibrated."])


@operation("GeoSeismicProbabilisticNoise")
def seismic_probabilistic_noise(args):
    from obspy.signal import PPSD
    np = _np()
    poles, zeros = _paz(args)
    duration = len(args["counts"]) * args["dt_s"]
    if args["segment_s"] > duration or args["segment_s"] / args["dt_s"] < 256 or duration / args["segment_s"] > 16:
        reject("PPSD requires complete segments of >=256 samples, at most 16 non-overlapping segment lengths")
    if not (2 * args["dt_s"] < args["period_min_s"] < args["period_max_s"] < args["segment_s"] / 8):
        reject("PSD period band must be resolved by Nyquist and the segment FFT")
    tr = _trace(args["counts"], args["dt_s"], start=args["record_start_s"])
    if np.std(tr.data) == 0:
        reject("A constant record has no finite calibrated noise spectrum")
    paz = dict(poles=poles.tolist(), zeros=zeros.tolist(), gain=args["normalization_factor"], sensitivity=args["sensitivity_counts_per_m_s"])
    psd = PPSD(tr.stats, metadata=paz, skip_on_gaps=True, ppsd_length=args["segment_s"], overlap=.5,
        db_bins=(-220., -20., 2.), period_smoothing_width_octaves=1., period_step_octaves=.125,
        period_limits=(args["period_min_s"], args["period_max_s"]))
    if not psd.add(tr) or not psd.psd_values:
        reject("No complete calibrated PSD segments", "empty_input")
    psd.calculate_histogram()
    hist = np.asarray(psd.current_histogram, dtype=int)
    return _result({"period_center_s": _real(psd.period_bin_centers), "segment_psd_db": _real(psd.psd_values),
        "db_edges": _real(psd.db_bin_edges), "histogram_counts": hist.tolist(),
        "out_of_histogram_count": (len(psd.psd_values) - hist.sum(axis=1)).tolist()},
        {"period_center_s": "s", "segment_psd_db": "dB re (m/s^2)^2/Hz", "db_edges": "dB re (m/s^2)^2/Hz", "histogram_counts": "count", "out_of_histogram_count": "count"},
        "ObsPy calibrated acceleration PPSD, fixed velocity-sensor PZ epoch",
        warnings=["Overlapping segments are not independent probabilities. Values outside [-220,-20] dB are counted explicitly; one stationary response epoch is required."])


@operation("GeoSeismicWaveformTFMisfit")
def seismic_waveform_tf_misfit(args):
    from obspy.signal.tf_misfit import tfem, tfpm, cwt
    np = _np()
    syn = _array(args["synthetic"], 1)
    obs = _array(args["observed"], 1, syn.shape)
    if not (0 < args["fmin_hz"] < args["fmax_hz"] < .5 / args["dt_s"]) or np.max(abs(obs)) == 0:
        reject("A nonzero observed reference and sub-Nyquist band are required")
    common = dict(dt=args["dt_s"], fmin=args["fmin_hz"], fmax=args["fmax_hz"], nf=16, w0=6, norm="global", st2_isref=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        em, pm = tfem(syn, obs, **common), tfpm(syn, obs, **common)
    ws = cwt(syn, args["dt_s"], 6, args["fmin_hz"], args["fmax_hz"], 16)
    wo = cwt(obs, args["dt_s"], 6, args["fmin_hz"], args["fmax_hz"], 16)
    valid = (abs(ws) > 1e-12 * np.max(abs(ws))) & (abs(wo) > 1e-12 * np.max(abs(wo))) & np.isfinite(pm)
    phase = [[float(v) if ok else None for v, ok in zip(row, mask)] for row, mask in zip(pm, valid)]
    return _result({"frequency_hz": _real(np.logspace(np.log10(args["fmin_hz"]), np.log10(args["fmax_hz"]), 16)),
        "envelope_misfit": _real(em, (16, len(syn))), "phase_misfit": phase, "phase_valid": valid.tolist()},
        {"frequency_hz": "Hz", "envelope_misfit": "1", "phase_misfit": "pi-normalized, amplitude-weighted", "phase_valid": "boolean"},
        "ObsPy Morlet time-frequency envelope/phase misfit", warnings=["Observed waveform is the reference; unsupported low-energy phases are null. Finite-record wavelet edge effects are not corrected."])


@operation("GeoSeismicRadiationPattern")
def seismic_radiation_pattern(args):
    from obspy.core.event.source import farfield
    np = _np()
    mt = _array(args["moment_tensor_enu_nm"], 2, (3, 3))
    directions = _same_points(args["direction_enu"])
    if not np.allclose(mt, mt.T, rtol=1e-12, atol=0) or np.linalg.norm(mt) == 0:
        reject("A nonzero symmetric moment tensor is required")
    if np.any(np.linalg.norm(directions, axis=1) == 0):
        reject("Radiation directions must be nonzero")
    scale = float(np.linalg.norm(mt))
    six = np.array([mt[0, 0], mt[1, 1], mt[2, 2], mt[0, 1], mt[0, 2], mt[1, 2]]) / scale
    p, s = farfield(six, directions.T, "P").T, farfield(six, directions.T, "S").T
    return _result({"p_vector": _real(p, directions.shape), "s_vector": _real(s, directions.shape), "tensor_frobenius_nm": scale},
        {"p_vector": "1", "s_vector": "1", "tensor_frobenius_nm": "N*m"}, "ObsPy Cartesian farfield tensor contractions",
        warnings=["Normalized by tensor Frobenius norm, not scalar seismic moment. S sign follows ObsPy; no MoPaD eigensystem, geometric spreading, source-time function or absolute displacement."])


@operation("GeoSurfaceWaveEigenfunctions")
def surface_wave_eigenfunctions(args):
    from disba._cps import swegn96
    np = _np()
    si, model = _layers(args)
    e = swegn96(args["period_s"], *model.T, mode=args["mode"], ifunc=2 if args["wave"] == "rayleigh" else 1, dc=.001)
    displacement = np.asarray(e)[:, :2 if args["wave"] == "rayleigh" else 1]
    norm = float(np.max(abs(displacement)))
    if not math.isfinite(norm) or norm == 0:
        reject("Undefined modal displacement normalization", "invalid_result")
    return _result({"interface_depth_m": _real(np.r_[0., np.cumsum(si[:-1, 0])]), "relative_displacement": _real(displacement / norm)},
        {"interface_depth_m": "m", "relative_displacement": "1"}, "disba public CPS swegn96 modal displacement",
        warnings=["Rows are layer-top interfaces, not the defective high-level depth labels. Rayleigh columns radial/vertical; Love transverse. Peak-displacement normalization, no inferred absolute amplitude or dimensional traction."])


@operation("GeoSurfaceWaveSensitivity")
def surface_wave_sensitivity(args):
    from disba import PhaseSensitivity
    np = _np()
    si, model = _layers(args)
    kernel = PhaseSensitivity(*model.T, algorithm="dunkin", dc=.001, dp=.01)
    values = {}
    for parameter, key in (("thickness", "dc_dthickness_s_inv"), ("velocity_p", "dc_dvp"), ("velocity_s", "dc_dvs"), ("density", "dc_ddensity_m4_kg_s")):
        result = kernel(args["period_s"], mode=args["mode"], wave=args["wave"], parameter=parameter)
        values[key] = _real(result.kernel, (len(si),))
    values["dc_dthickness_s_inv"][-1] = None
    values["interface_depth_m"] = _real(np.r_[0., np.cumsum(si[:-1, 0])])
    return _result(values, {"dc_dthickness_s_inv": "1/s", "dc_dvp": "1", "dc_dvs": "1", "dc_ddensity_m4_kg_s": "m^4/(kg*s)", "interface_depth_m": "m"},
        "disba bundled phase-speed sensitivity kernels", warnings=["Native finite perturbation dp=.01; not posterior uncertainty. Halfspace thickness is not a free parameter and is null. SI derivative factors cancel the matched km/g-cm3 input/output conversions."])


class _DiscardLog:
    """No retained log buffer; cap accounting without permitting unbounded output."""
    def __init__(self):
        self.characters = 0
    def write(self, value):
        self.characters = min(65537, self.characters + len(value))
        return len(value)
    def flush(self):
        pass


def _tensor_mesh(args):
    from discretize import TensorMesh
    np = _np()
    edges = [_ordered(args[k], 3) for k in ("x_edges_m", "y_edges_m", "z_edges_m")]
    if np.prod([len(e) - 1 for e in edges]) > 216 or edges[2][-1] != 0:
        reject("Fixed tensor mesh must have <=216 cells and flat upper surface z=0")
    if any(np.min(np.diff(e)) < 1 or np.max(np.diff(e)) / np.min(np.diff(e)) > 20 for e in edges):
        reject("Cells must be >=1m with bounded within-axis aspect ratio")
    return TensorMesh([np.diff(e) for e in edges], origin=[e[0] for e in edges]), edges


def _inverse(simulation, mesh, observed, errors, start, lower, upper, args):
    from simpeg import data, data_misfit, regularization, optimization, inverse_problem, inversion
    np = _np()
    observed = _array(observed, 1)
    errors = _array(errors, 1, observed.shape)
    start = _array(start, 1, (mesh.n_cells,))
    if np.any(errors <= 0) or lower >= upper or np.any(start <= lower) or np.any(start >= upper):
        reject("Positive uncertainties and a starting model strictly inside bounds are required")
    survey_data = data.Data(simulation.survey, dobs=observed, standard_deviation=errors)
    misfit = data_misfit.L2DataMisfit(data=survey_data, simulation=simulation)
    reg = regularization.WeightedLeastSquares(mesh, reference_model=start, alpha_s=1.0, alpha_x=1.0)
    opt = optimization.ProjectedGNCG(maxIter=args["max_iterations"], lower=lower, upper=upper,
        maxIterCG=20, maxIterLS=10, tolF=1e-7, tolX=1e-7, tolG=1e-7)
    problem = inverse_problem.BaseInvProblem(misfit, reg, opt, beta=args["regularization_beta"])
    log = _DiscardLog()
    with redirect_stdout(log), redirect_stderr(log):
        recovered = inversion.BaseInversion(problem, directiveList=[]).run(start)
    recovered = _array(recovered, 1, start.shape)
    if np.any(recovered < lower - 1e-10) or np.any(recovered > upper + 1e-10):
        reject("Inverse solver violated model bounds", "invalid_result")
    predicted = _array(simulation.dpred(recovered), 1, observed.shape)
    residual = predicted - observed
    gradient = _array(misfit.deriv(recovered) + args["regularization_beta"] * reg.deriv(recovered), 1, recovered.shape)
    stationarity = float(np.max(abs(recovered - np.clip(recovered - gradient, lower, upper))))
    iterations = int(opt.iter)
    state = "projected_stationarity_met" if stationarity <= 1e-6 else ("iteration_limit" if iterations >= args["max_iterations"] else "stopped_without_stationarity_certificate")
    diagnostics = dict(convergence=state, iterations=iterations,
        weighted_rms=float(np.sqrt(np.mean((residual / errors) ** 2))), residual_l2=float(np.linalg.norm(residual)),
        stationarity_inf=stationarity,
        uncertainty="Conditional regularized estimate only; posterior covariance, depth of investigation and background-model uncertainty are not estimated.",
        warnings=["Fixed beta and reference model; fit is not a unique geological solution. Upstream progress text discarded with bounded accounting; no files or solver callback from user input."])
    return recovered, predicted, residual, diagnostics


def _dc_survey(args, edges, chargeability=False):
    from simpeg.electromagnetics.static import resistivity as dc
    np = _np()
    geometry = _array(args["electrode_abmn_enu_m"], 3)
    if geometry.shape[1:] != (4, 3):
        reject("Each datum needs A,B,M,N coordinates")
    points = geometry.reshape(-1, 3)
    if np.any(points[:, 2] != 0):
        reject("This fixed DC/IP profile uses surface electrodes z=0")
    for i in (0, 1):
        margin = min(np.diff(edges[i]))
        if np.any(points[:, i] <= edges[i][0] + margin) or np.any(points[:, i] >= edges[i][-1] - margin):
            reject("Electrodes require at least one outer-cell margin from side boundaries")
    currents = _array(args["source_current_a"], 1, (len(geometry),))
    sources = []
    for row, current in zip(geometry, currents):
        if current == 0 or min(np.linalg.norm(row[i] - row[j]) for i in range(4) for j in range(i)) < .001:
            reject("All four electrodes must be distinct and current nonzero")
        rx = dc.receivers.Dipole(row[2:3], row[3:4], data_type="apparent_chargeability" if chargeability else "volt")
        sources.append(dc.sources.Dipole([rx], location_a=row[0], location_b=row[1], current=float(current)))
    return dc.Survey(sources)


@operation("GeoDCResistivityInversion")
def dc_resistivity_inversion(args):
    from simpeg import maps
    from simpeg.electromagnetics.static import resistivity as dc
    from pymatsolver import SolverLU
    np = _np()
    mesh, edges = _tensor_mesh(args)
    survey = _dc_survey(args, edges)
    initial = _array(args["starting_conductivity_s_m"], 1, (mesh.n_cells,))
    simulation = dc.Simulation3DNodal(mesh, survey=survey, sigmaMap=maps.ExpMap(nP=mesh.n_cells), bc_type="Robin", solver=SolverLU)
    recovered, predicted, residual, diag = _inverse(simulation, mesh, args["voltage_v"], args["standard_deviation_v"],
        np.log(initial), math.log(args["conductivity_lower_s_m"]), math.log(args["conductivity_upper_s_m"]), args)
    return _result({"cell_centers_enu_m": _real(mesh.cell_centers), "resistivity_ohm_m": _real(np.exp(-recovered)),
        "predicted_voltage_v": _real(predicted), "residual_v": _real(residual)},
        {"cell_centers_enu_m": "m", "resistivity_ohm_m": "ohm*m", "predicted_voltage_v": "V", "residual_v": "V"},
        "SimPEG bounded nodal DC inversion; flat Robin tensor-mesh profile", **diag)


@operation("GeoIPChargeabilityInversion")
def ip_chargeability_inversion(args):
    from simpeg import maps
    from simpeg.electromagnetics.static import induced_polarization as ip, resistivity as dc
    from pymatsolver import SolverLU
    np = _np()
    mesh, edges = _tensor_mesh(args)
    sigma = _array(args["background_conductivity_s_m"], 1, (mesh.n_cells,))
    if np.any(sigma <= 0):
        reject("Positive supplied DC background conductivity is required")
    dc_sim = dc.Simulation3DNodal(mesh, survey=_dc_survey(args, edges), sigma=sigma, bc_type="Robin", solver=SolverLU)
    background_voltage = _array(dc_sim.dpred(), 1)
    if np.any(abs(background_voltage) < 1e-10):
        reject("Normalized chargeability is unstable at near-zero DC voltage", "unsupported_conditions")
    sim = ip.Simulation3DNodal(mesh, survey=_dc_survey(args, edges, True), sigma=sigma,
        etaMap=maps.IdentityMap(nP=mesh.n_cells), solver=SolverLU, bc_type="Robin", storeJ=True)
    recovered, predicted, residual, diag = _inverse(sim, mesh, args["apparent_chargeability_v_v"], args["standard_deviation_v_v"],
        args["starting_chargeability_v_v"], 0., args["chargeability_upper_v_v"], args)
    return _result({"cell_centers_enu_m": _real(mesh.cell_centers), "chargeability_v_v": _real(recovered),
        "predicted_chargeability_v_v": _real(predicted), "residual_v_v": _real(residual)},
        {"cell_centers_enu_m": "m", "chargeability_v_v": "V/V", "predicted_chargeability_v_v": "V/V", "residual_v_v": "V/V"},
        "SimPEG linearized IP inversion conditional on supplied DC conductivity", **diag)


def _layer_inverse_inputs(args):
    from discretize import TensorMesh
    np = _np()
    thickness = _array(args["finite_layer_thickness_m"], 1)
    if np.any(thickness <= 0):
        reject("Finite layers require positive thickness")
    mesh = TensorMesh([np.r_[thickness, args["halfspace_regularization_length_m"]]])
    initial = _array(args["starting_conductivity_s_m"], 1, (len(thickness) + 1,))
    if np.any(initial <= 0):
        reject("Starting conductivity must be positive")
    return mesh, thickness, np.log(initial)


@operation("GeoFDEMConductivityInversion")
def fdem_conductivity_inversion(args):
    from simpeg import maps
    from simpeg.electromagnetics import frequency_domain as fdem
    np = _np()
    mesh, thickness, initial = _layer_inverse_inputs(args)
    frequency = _ordered(args["frequency_hz"], 2)
    receiver = np.array([[args["offset_m"], 0., args["height_m"]]])
    sources = []
    for f in frequency:
        rx = [fdem.receivers.PointMagneticFieldSecondary(receiver, orientation="z", component=c) for c in ("real", "imag")]
        sources.append(fdem.sources.MagDipole(rx, frequency=float(f), location=[0., 0., args["height_m"]], orientation="z", moment=args["moment_a_m2"]))
    sim = fdem.Simulation1DLayered(survey=fdem.Survey(sources), thicknesses=thickness, sigmaMap=maps.ExpMap(nP=mesh.n_cells))
    observed = _array(args["secondary_h_real_imag_a_m"], 2, (len(frequency), 2)).ravel()
    error = _array(args["standard_deviation_a_m"], 2, (len(frequency), 2)).ravel()
    recovered, predicted, residual, diag = _inverse(sim, mesh, observed, error, initial,
        math.log(args["conductivity_lower_s_m"]), math.log(args["conductivity_upper_s_m"]), args)
    return _result({"conductivity_s_m": _real(np.exp(recovered)), "predicted_real_imag_a_m": _real(predicted.reshape(-1, 2)), "residual_real_imag_a_m": _real(residual.reshape(-1, 2))},
        {"conductivity_s_m": "S/m", "predicted_real_imag_a_m": "A/m", "residual_real_imag_a_m": "A/m"},
        "SimPEG layered secondary-H FDEM inversion, vertical magnetic dipole", **diag)


@operation("GeoTDEMConductivityInversion")
def tdem_conductivity_inversion(args):
    from simpeg import maps
    from simpeg.electromagnetics import time_domain as tdem
    np = _np()
    mesh, thickness, initial = _layer_inverse_inputs(args)
    times = _ordered(args["off_time_s"], 2)
    rx = tdem.receivers.PointMagneticFluxTimeDerivative(np.array([[0., 0., args["height_m"]]]), times, orientation="z")
    source = tdem.sources.CircularLoop([rx], location=[0., 0., args["height_m"]], orientation="z",
        radius=args["loop_radius_m"], current=args["current_a"], waveform=tdem.sources.StepOffWaveform())
    sim = tdem.Simulation1DLayered(survey=tdem.Survey([source]), thicknesses=thickness, sigmaMap=maps.ExpMap(nP=mesh.n_cells))
    recovered, predicted, residual, diag = _inverse(sim, mesh, args["dbdt_t_s"], args["standard_deviation_t_s"], initial,
        math.log(args["conductivity_lower_s_m"]), math.log(args["conductivity_upper_s_m"]), args)
    return _result({"conductivity_s_m": _real(np.exp(recovered)), "predicted_dbdt_t_s": _real(predicted, times.shape), "residual_t_s": _real(residual)},
        {"conductivity_s_m": "S/m", "predicted_dbdt_t_s": "T/s", "residual_t_s": "T/s"},
        "SimPEG layered central-loop ideal-step-off TDEM inversion", **diag)


@operation("GeoGravityDensityInversion")
def gravity_density_inversion(args):
    from simpeg import maps
    from simpeg.potential_fields import gravity
    np = _np()
    mesh, _ = _tensor_mesh(args)
    obs = _same_points(args["observations_enu_m"])
    if np.any(obs[:, 2] < 1):
        reject("Gravity observation height must be >=1 m above the source mesh")
    survey = gravity.Survey(gravity.sources.SourceField([gravity.receivers.Point(obs, components=["gz"])]))
    sim = gravity.Simulation3DIntegral(mesh, survey=survey, rhoMap=maps.IdentityMap(nP=mesh.n_cells),
        engine="geoana", numba_parallel=False, store_sensitivities="ram", n_processes=1, sensitivity_dtype=np.float64)
    recovered, predicted, residual, diag = _inverse(sim, mesh, args["gravity_up_mgal"], args["standard_deviation_mgal"],
        _array(args["starting_density_contrast_kg_m3"], 1) / 1000., args["density_lower_kg_m3"] / 1000., args["density_upper_kg_m3"] / 1000., args)
    return _result({"cell_centers_enu_m": _real(mesh.cell_centers), "density_contrast_kg_m3": _real(recovered * 1000.),
        "predicted_gravity_up_mgal": _real(predicted), "residual_mgal": _real(residual)},
        {"cell_centers_enu_m": "m", "density_contrast_kg_m3": "kg/m^3", "predicted_gravity_up_mgal": "mGal", "residual_mgal": "mGal"},
        "SimPEG gravity integral inversion; upstream g/cc converted explicitly, z positive up", **diag)


@operation("GeoMagneticSusceptibilityInversion")
def magnetic_susceptibility_inversion(args):
    from simpeg import maps
    from simpeg.potential_fields import magnetics
    np = _np()
    mesh, _ = _tensor_mesh(args)
    obs = _same_points(args["observations_enu_m"])
    if np.any(obs[:, 2] < 1):
        reject("Magnetic observation height must be >=1 m above the source mesh")
    source = magnetics.sources.UniformBackgroundField([magnetics.receivers.Point(obs, components=["tmi"])],
        amplitude=args["inducing_field_nt"], inclination=args["inclination_deg"], declination=args["declination_deg"])
    sim = magnetics.Simulation3DIntegral(mesh, survey=magnetics.Survey(source), chiMap=maps.IdentityMap(nP=mesh.n_cells),
        model_type="scalar", engine="geoana", numba_parallel=False, store_sensitivities="ram", n_processes=1, sensitivity_dtype=np.float64)
    recovered, predicted, residual, diag = _inverse(sim, mesh, args["tmi_nt"], args["standard_deviation_nt"],
        args["starting_susceptibility_si"], 0., args["susceptibility_upper_si"], args)
    return _result({"cell_centers_enu_m": _real(mesh.cell_centers), "susceptibility_si": _real(recovered),
        "predicted_tmi_nt": _real(predicted), "residual_nt": _real(residual)},
        {"cell_centers_enu_m": "m", "susceptibility_si": "1 (SI)", "predicted_tmi_nt": "nT", "residual_nt": "nT"},
        "SimPEG induced-only scalar susceptibility inversion; no remanence/self-demagnetization", **diag)


def _wavelet(args):
    np = _np()
    wav = _array(args["wavelet"], 1)
    if len(wav) % 2 != 1 or np.linalg.norm(wav) == 0:
        reject("Provide a nonzero odd-length wavelet centered on its middle sample")
    return wav


def _solver_capture(args, diagnostics):
    from scipy.sparse.linalg import lsqr
    def solve(operator, data, **unused):
        answer = lsqr(operator, data, damp=args["damping"], atol=1e-8, btol=1e-8,
                      conlim=1e8, iter_lim=args["max_iterations"], show=False)
        diagnostics.update(iterations=int(answer[2]), residual_l2=float(answer[3]),
            convergence="lsqr_stop_%d" % answer[1], stationarity_inf=None)
        return answer
    return solve


@operation("GeoSeismicLeastSquaresMigration")
def seismic_least_squares_migration(args):
    from pylops.waveeqprocessing import LSM
    np = _np()
    x, z, t = (_ordered(args[k], 3, True) for k in ("x_m", "depth_m", "time_s"))
    if t[0] != 0 or z[0] < 0 or len(x) * len(z) > 1024:
        reject("LSM needs t=0 start, nonnegative depths and <=1024 image cells")
    src, rec = _array(args["sources_x_depth_m"], 2), _array(args["receivers_x_depth_m"], 2)
    if src.shape[1] != 2 or rec.shape[1] != 2:
        reject("LSM coordinates are [x, positive depth] pairs")
    if np.any(src[:, 1] != 0) or np.any(rec[:, 1] != 0):
        reject("This fixed analytic-ray profile uses a surface acquisition")
    data = _array(args["shot_gather"], 3, (len(src), len(rec), len(t)))
    wav = _wavelet(args)
    lsm = LSM(z, x, t, src.T, rec.T, args["background_velocity_m_s"], wav, len(wav) // 2,
        kind="kirchhoff", mode="analytic", dynamic=False, wavfilter=False, engine="numpy", dottest=False)
    diag = {}
    model = lsm.solve(data, solver=_solver_capture(args, diag))
    predicted = np.asarray(lsm.Demop @ np.asarray(model).ravel()).reshape(data.shape)
    return _result({"reflectivity_image": _real(model, (len(x), len(z))), "predicted_gather": _real(predicted)},
        {"reflectivity_image": "upstream Kirchhoff image amplitude under supplied wavelet normalization", "predicted_gather": "declared normalized seismic amplitude"},
        "PyLops Kirchhoff least-squares migration, constant background analytic rays", **diag)


def _linear_diagnostics(operator, model, background, observed, damping):
    np = _np()
    residual = np.asarray(operator @ np.asarray(model).ravel()) - np.asarray(observed).ravel()
    delta = np.asarray(model).ravel() - np.asarray(background).ravel()
    gradient = np.asarray(operator.H @ residual) + damping ** 2 * delta
    g = float(np.max(abs(gradient)))
    scale = max(1., float(np.max(abs(operator.H @ np.asarray(observed).ravel()))))
    return residual, dict(convergence="stationarity_met" if g <= 1e-6 * scale else "stationarity_not_met",
        stationarity_inf=g, residual_l2=float(np.linalg.norm(residual)), iterations=None,
        warnings=["Upstream convenience routine does not expose iteration count; reported stationarity is evaluated using its actual forward/adjoint operator, not inferred from a returned model."])


@operation("GeoSeismicPoststackImpedanceInversion")
def seismic_poststack_impedance_inversion(args):
    from pylops.avo.poststack import PoststackInversion, PoststackLinearModelling
    np = _np()
    data = _array(args["poststack_trace"], 1)
    reference = _array(args["background_impedance_kg_m2_s"], 1, data.shape)
    if np.any(reference <= 0):
        reject("Absolute log-impedance inversion requires an explicit positive background")
    wav = _wavelet(args) * .5
    background = np.log(reference)
    model, _ = PoststackInversion(data, wav, m0=background, explicit=False, epsR=None, epsI=None,
        damp=args["damping"], iter_lim=args["max_iterations"], atol=1e-8, btol=1e-8, show=False)
    op = PoststackLinearModelling(wav, len(data), explicit=False)
    residual, diag = _linear_diagnostics(op, model, background, data, args["damping"])
    if np.any(model > math.log(1e10)) or np.any(model < math.log(1e3)):
        reject("Recovered impedance leaves the declared physical range", "unsupported_conditions")
    return _result({"impedance_kg_m2_s": _real(np.exp(model), data.shape), "residual": _real(residual)},
        {"impedance_kg_m2_s": "kg/(m^2*s)", "residual": "declared normalized seismic amplitude"},
        "PyLops poststack log-impedance inversion; wavelet explicitly scaled by 1/2", **diag)


@operation("GeoSeismicPrestackElasticInversion")
def seismic_prestack_elastic_inversion(args):
    from pylops.avo.prestack import PrestackInversion, PrestackLinearModelling
    np = _np()
    data = _array(args["angle_gather_time_angle"], 2)
    angles = _ordered(args["angle_deg"], 3)
    reference = _array(args["background_vp_vs_rho_si"], 2, (data.shape[0], 3))
    if data.shape[1] != len(angles) or angles[0] < 0 or angles[-1] > 35 or angles[-1] - angles[0] < 15:
        reject("Require >=3 increasing angles spanning >=15 degrees within [0,35]")
    if np.any(reference <= 0) or np.any(reference[:, 0] ** 2 <= 4 * reference[:, 1] ** 2 / 3):
        reject("Reference model must have positive density, bulk and shear moduli")
    if math.sin(math.radians(angles[-1])) * np.max(reference[:, 0]) / np.min(reference[:, 0]) >= .95:
        reject("Reference contrasts approach/exceed critical incidence", "unsupported_conditions")
    background = np.log(reference)
    ratio = reference[:, 1] / reference[:, 0]
    wav = _wavelet(args)
    model, _ = PrestackInversion(data, angles, wav, m0=background, linearization="akirich", explicit=False,
        returnres=True, epsI=None, epsR=None, vsvp=ratio, damp=args["damping"],
        iter_lim=args["max_iterations"], atol=1e-8, btol=1e-8, show=False)
    op = PrestackLinearModelling(wav, angles, vsvp=ratio, nt0=len(data), linearization="akirich", explicit=False)
    residual, diag = _linear_diagnostics(op, model, background, data, args["damping"])
    if np.max(abs(model - background)) > .25:
        reject("Elastic update exceeds the weak-contrast linearization profile", "unsupported_conditions")
    properties = np.exp(model)
    if np.any(properties[:, 0] ** 2 <= 4 * properties[:, 1] ** 2 / 3):
        reject("Recovered elastic model is not physically stable", "invalid_result")
    return _result({"vp_vs_rho_si": _real(properties, reference.shape), "residual_gather": _real(residual.reshape(data.shape))},
        {"vp_vs_rho_si": "m/s,m/s,kg/m^3", "residual_gather": "declared normalized seismic amplitude"},
        "PyLops Aki-Richards coupled elastic log-property inversion", **diag)


@operation("GeoSeismicReceiverDeghosting")
def seismic_receiver_deghosting(args):
    from pylops.waveeqprocessing import Deghosting
    np = _np()
    pressure = _array(args["pressure_receiver_time_pa"], 2)
    direct = _array(args["direct_pressure_receiver_time_pa"], 2, pressure.shape)
    if pressure.shape[0] < 8 or pressure.shape[1] < 32:
        reject("Deghosting requires >=8 receivers and >=32 time samples")
    diag = {}
    # PyLops 2.6.0 constructs dims=(nt, nr), despite the receiver-first docstring.
    # Keep our public receiver/time contract and convert only at the fixed call.
    pressure_tr = np.ascontiguousarray(pressure.T)
    direct_tr = np.ascontiguousarray(direct.T)
    up, down = Deghosting(pressure_tr, pressure.shape[1], pressure.shape[0], args["dt_s"], args["receiver_spacing_m"],
        args["water_velocity_m_s"], args["receiver_depth_m"], kind="p", pd=direct_tr, npad=4, ntaper=(3, 3),
        solver=_solver_capture(args, diag), dottest=False)
    up, down = np.asarray(up), np.asarray(down)
    if up.shape != pressure_tr.shape or down.shape != pressure_tr.shape:
        reject("Unexpected PyLops time/receiver deghosting layout", "invalid_result")
    return _result({"upgoing_pressure_pa": _real(up.T, pressure.shape), "downgoing_pressure_pa": _real(down.T, pressure.shape)},
        {"upgoing_pressure_pa": "Pa", "downgoing_pressure_pa": "Pa"},
        "PyLops flat-receiver pressure deghosting with explicit direct wave", **diag)


@operation("GeoSeismicUpDownWavefieldSeparation")
def seismic_up_down_wavefield_separation(args):
    from pylops.waveeqprocessing import WavefieldDecomposition
    np = _np()
    pressure = _array(args["pressure_receiver_time_pa"], 2)
    velocity = _array(args["vertical_velocity_receiver_time_m_s"], 2, pressure.shape)
    if pressure.shape[0] < 8 or pressure.shape[1] < 32:
        reject("Wavefield separation requires >=8 receivers and >=32 time samples")
    if np.max(abs(pressure.mean(axis=1))) > 1e-6 * max(1e-20, float(np.max(abs(pressure)))) or np.max(abs(velocity.mean(axis=1))) > 1e-6 * max(1e-20, float(np.max(abs(velocity)))):
        reject("Provide zero-mean calibrated pressure and positive-down particle velocity; DC is not separable")
    up, down = WavefieldDecomposition(pressure, velocity, pressure.shape[1], pressure.shape[0], args["dt_s"],
        args["receiver_spacing_m"], args["water_density_kg_m3"], args["water_velocity_m_s"], kind="analytical", critical=95., ntaper=3)
    return _result({"upgoing_pressure_pa": _real(up, pressure.shape), "downgoing_pressure_pa": _real(down, pressure.shape)},
        {"upgoing_pressure_pa": "Pa", "downgoing_pressure_pa": "Pa"},
        "PyLops analytical pressure/vertical-velocity wavefield separation",
        warnings=["Vertical particle velocity is positive downward, not ENU-up. Fixed 95% critical-wavenumber filter and three-sample taper; evanescent energy is not reconstructed."])


@operation("GeoSeismicMultidimensionalDeconvolution")
def seismic_multidimensional_deconvolution(args):
    from pylops.waveeqprocessing import MDD, MDC
    np = _np()
    kernel = _array(args["kernel_source_receiver_time_per_m_s"], 3)
    ns, nr, nt = kernel.shape
    observed = _array(args["data_source_time_pa"], 2, (ns, nt))
    if nr < 2 or ns < 2 or np.linalg.norm(kernel) == 0:
        reject("A nonzero multidimensional acquisition kernel is required")
    model = MDD(kernel, observed, dt=args["dt_s"], dr=args["receiver_spacing_m"], nfmax=nt,
        twosided=True, add_negative=True, adjoint=False, psf=False, causality_precond=False,
        dottest=False, fftengine="numpy", damp=args["damping"], iter_lim=args["max_iterations"], atol=1e-8, btol=1e-8, show=False)
    model = np.asarray(model)
    if model.shape != (nr, 2 * nt - 1):
        reject("Unexpected multidimensional deconvolution result shape", "invalid_result")
    padded_kernel = np.concatenate((np.zeros((ns, nr, nt - 1)), kernel), axis=2)
    padded_data = np.concatenate((np.zeros((ns, nt - 1)), observed), axis=1)
    op = MDC(np.fft.rfft(padded_kernel, axis=-1).transpose(2, 0, 1), 2 * nt - 1, nv=1,
        dt=args["dt_s"], dr=args["receiver_spacing_m"], twosided=True, fftengine="numpy")
    residual, diag = _linear_diagnostics(op, model.T, np.zeros_like(model.T), padded_data.T, args["damping"])
    return _result({"virtual_source_response_pa": _real(model), "time_s": _real(np.arange(-nt + 1, nt) * args["dt_s"]),
        "convolution_residual_pa": _real(residual.reshape(2 * nt - 1, ns).T)},
        {"virtual_source_response_pa": "Pa under the explicitly supplied kernel normalization", "time_s": "s", "convolution_residual_pa": "Pa"},
        "PyLops time-domain multidimensional deconvolution with physical dt*dr quadrature", **diag)

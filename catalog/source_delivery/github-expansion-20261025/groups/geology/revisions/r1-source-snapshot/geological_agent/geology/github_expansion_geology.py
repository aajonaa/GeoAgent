"""Thirty bounded upstream geological operations. SOURCE ONLY, NOT TESTED.

Public entrypoints use collection_contracts.operation; no runtime downloads,
installations, user-selected Python functions, or inferred mineral grades.
Upstream release/commit/license evidence is in the geology contribution folder.
"""
from pathlib import Path
import io

from .collection_contracts import operation, reject


def _np():
    import numpy as np
    return np


def _array(value, ndim=None):
    np = _np()
    result = np.asarray(value, dtype=float)
    if (ndim is not None and result.ndim != ndim) or not np.isfinite(result).all():
        reject("Expected a finite rectangular numeric array")
    return result


def _result(args, units, **values):
    return {**values, "input_source": args["data_source"], "units": units}


def _vectors(value, minimum=1):
    np = _np()
    a = _array(value, 2)
    if a.shape[1] != 3 or len(a) < minimum or np.any(np.linalg.norm(a, axis=1) < 1e-12):
        reject("Nonzero three-component NED vectors are required")
    return a


def _symmetric(value, dimension=3, positive=False):
    np = _np()
    a = _array(value, 2)
    if a.shape != (dimension, dimension) or not np.allclose(a, a.T, rtol=0, atol=1e-10):
        reject("Expected a symmetric tensor in the declared frame")
    if positive and np.linalg.eigvalsh(a)[0] <= 1e-10:
        reject("Marker/strain tensors must be positive definite")
    return a


def _gradient(value):
    np = _np()
    a = _array(value, 2)
    if a.shape != (3, 3) or np.linalg.det(a) <= 1e-10 or np.linalg.cond(a) > 1e8:
        reject("Finite deformation must preserve orientation and be nonsingular")
    return a


def _pairs(args):
    np = _np()
    normals, lines = _vectors(args["normal_vectors"]), _vectors(args["line_vectors"])
    if normals.shape != lines.shape:
        reject("Each measured plane requires one paired line")
    cosines = np.sum(normals * lines, axis=1) / (np.linalg.norm(normals, axis=1) * np.linalg.norm(lines, axis=1))
    if np.any(np.abs(cosines) > 1e-8):
        reject("Lines must lie in their measured planes; automatic adjustment is disabled")
    return normals, lines


@operation("GeoAPSGPairFabricTensor")
def paired_fabric_tensor(args):
    from apsg.feature import Pair, PairSet, OrientationTensor3
    from apsg.math import Vector3
    normals, lines = _pairs(args)
    pairs = PairSet([Pair(Vector3(n), Vector3(l)) for n, l in zip(normals, lines)])
    tensor = OrientationTensor3.from_pairs(pairs, shift=True)
    return _result(args, {"tensor": "1", "eigenvalues": "1"},
                   tensor=_np().asarray(tensor).tolist(), eigenvalues=list(map(float, tensor.eigenvalues())))


@operation("GeoAPSGFoldAxis")
def cylindrical_fold_axis(args):
    from apsg.feature import Vector3Set, OrientationTensor3
    from apsg.math import Vector3
    n = _vectors(args["normal_vectors"], 4)
    t = OrientationTensor3.from_features(Vector3Set([Vector3(v) for v in n]))
    eigenvalues = _array(t.eigenvalues(), 1)
    gap = float(eigenvalues[1] - eigenvalues[2])
    if gap <= 1e-8:
        reject("Plane poles do not define a unique least-eigenvalue fold axis", "unsupported_conditions")
    axis = _np().asarray(t.eigenvectors()[2], dtype=float)
    return _result(args, {"axis_ned": "1", "eigenvalues": "1", "girdle_gap": "1"},
                   axis_ned=axis.tolist(), eigenvalues=eigenvalues.tolist(), girdle_gap=gap)


@operation("GeoAPSGFisherDirectionalConfidence")
def fisher_directional_confidence(args):
    from apsg.feature import Vector3Set
    from apsg.math import Vector3
    np = _np()
    a = _vectors(args["directed_vectors"], 4)
    a = a / np.linalg.norm(a, axis=1)[:, None]
    rbar = float(np.linalg.norm(a.mean(axis=0)))
    if not 1e-5 < rbar < 0.99999:
        reject("Vanishing resultant or perfect alignment has no finite Fisher fit", "unsupported_conditions")
    stats = Vector3Set([Vector3(v) for v in a]).fisher_statistics(level=args["confidence_level"])
    return _result(args, {"mean_direction_ned": "1", "precision": "1", "confidence_half_angle": "degree", "resultant_length_per_sample": "1"},
                   mean_direction_ned=np.asarray(stats["mu"]).tolist(), precision=float(stats["k"]),
                   confidence_half_angle=float(stats["alpha"]), resultant_length_per_sample=rbar)


@operation("GeoAPSGBinghamAxialConfidence")
def bingham_axial_confidence(args):
    from apsg.feature import Vector3Set
    from apsg.math import Vector3
    np = _np()
    a = _vectors(args["axial_vectors"], 8)
    features = Vector3Set([Vector3(v) for v in a])
    e = _array(features.ortensor().eigenvalues(), 1)
    if e[2] <= 1e-10 or min(e[0] - e[1], e[1] - e[2]) <= 1e-8:
        reject("Bingham confidence requires a full-rank fabric with distinct principal axes", "unsupported_conditions")
    stats = features.bingham_statistics(level=args["confidence_level"], which=0)
    return _result(args, {"axis_ned": "1", "ellipse_axes_ned": "1", "semi_angles": "degree", "eigenvalues": "1"},
                   axis_ned=np.asarray(stats["mu"]).tolist(), ellipse_axes_ned=np.asarray(stats["axes"]).tolist(),
                   semi_angles=list(map(float, stats["gamma"])), eigenvalues=e.tolist())


@operation("GeoAPSGMarkerStrainEstimate")
def marker_strain_estimate(args):
    from apsg.feature import Ellipse, EllipseSet
    tensors = [_symmetric(v, 2, positive=True) for v in args["marker_tensors"]]
    markers = EllipseSet([Ellipse(v) for v in tensors])
    rf, robin = markers.rfphi(), markers.robin()
    if rf.ar <= 1 + 1e-8 or robin.ar <= 1 + 1e-8:
        reject("An isotropic marker population has no unique strain orientation", "unsupported_conditions")
    return _result(args, {"rfphi_axial_ratio": "1", "rfphi_orientation": "degree", "robin_axial_ratio": "1", "robin_orientation": "degree"},
                   rfphi_axial_ratio=float(rf.ar), rfphi_orientation=float(rf.orientation),
                   robin_axial_ratio=float(robin.ar), robin_orientation=float(robin.orientation))


@operation("GeoAPSGFaultKinematicAxes")
def fault_kinematic_axes(args):
    from apsg.feature import Fault
    from apsg.math import Vector3
    np = _np()
    normals, slips = _pairs(args)
    faults = [Fault(Vector3(n), Vector3(s)) for n, s in zip(normals, slips)]
    return _result(args, {"p_axes_ned": "1", "t_axes_ned": "1"},
                   p_axes_ned=[np.asarray(f.p_vector()).tolist() for f in faults],
                   t_axes_ned=[np.asarray(f.t_vector()).tolist() for f in faults])


@operation("GeoAPSGFiniteStrainEllipsoid")
def finite_strain_ellipsoid(args):
    from apsg.feature import DeformationGradient3, Ellipsoid
    np = _np()
    f = DeformationGradient3(_gradient(args["deformation_gradient"]))
    e = Ellipsoid.from_defgrad(f, form="left")
    k = float(e.k) if e.Ryz > 1 + 1e-10 else None
    return _result(args, {"left_cauchy_green": "1", "principal_stretches": "1", "hencky_strains": "1", "flinn_k": "1", "volume_ratio": "1"},
                   left_cauchy_green=np.asarray(e).tolist(), principal_stretches=[float(e.S1), float(e.S2), float(e.S3)],
                   hencky_strains=[float(e.e1), float(e.e2), float(e.e3)], flinn_k=k, volume_ratio=float(f.det))


@operation("GeoAPSGDeformationPolarSplit")
def deformation_polar_split(args):
    from apsg.feature import DeformationGradient3
    np = _np()
    f = DeformationGradient3(_gradient(args["deformation_gradient"]))
    return _result(args, {"rotation": "1", "right_stretch": "1", "left_stretch": "1", "rotation_angle": "degree"},
                   rotation=np.asarray(f.R).tolist(), right_stretch=np.asarray(f.U).tolist(),
                   left_stretch=np.asarray(f.V).tolist(), rotation_angle=float(abs(f.R.angle())))


@operation("GeoAPSGVelocityGradientEvolution")
def velocity_gradient_evolution(args):
    from apsg.feature import VelocityGradient3
    np = _np()
    l = _array(args["velocity_gradient_per_myr"], 2)
    if l.shape != (3, 3) or np.linalg.norm(l) * args["duration_myr"] > 20:
        reject("Flow-duration product exceeds the bounded deformation domain")
    f = VelocityGradient3(l).defgrad(time=args["duration_myr"])
    return _result(args, {"deformation_gradient": "1", "volume_ratio": "1", "duration_myr": "Myr"},
                   deformation_gradient=np.asarray(f).tolist(), volume_ratio=float(f.det), duration_myr=args["duration_myr"])


@operation("GeoAPSGKinematicVorticity")
def kinematic_vorticity(args):
    from apsg.feature import VelocityGradient3
    np = _np()
    a = _array(args["velocity_gradient_per_myr"], 2)
    if a.shape != (3, 3):
        reject("Velocity gradient must be 3 by 3")
    l = VelocityGradient3(a)
    if np.linalg.norm(np.asarray(l.rate())) < 1e-12:
        reject("Rigid rotation or zero flow has no finite kinematic vorticity number", "unsupported_conditions")
    return _result(args, {"kinematic_vorticity": "1", "vorticity_magnitude": "Myr^-1", "strain_rate": "Myr^-1", "spin": "Myr^-1"},
                   kinematic_vorticity=float(l.kinematic_vorticity), vorticity_magnitude=float(l.vorticity_scalar),
                   strain_rate=np.asarray(l.rate()).tolist(), spin=np.asarray(l.spin()).tolist())


def _stress(args):
    from apsg.config import apsg_conf
    from apsg.feature import Stress3
    from apsg.math import Vector3
    if apsg_conf.stress_convention != "geological":
        reject("APSG must already use its default compression-positive geological convention", "unsupported_conditions")
    s = Stress3(_symmetric(args["stress_mpa"]))
    normals = _vectors(args["normal_vectors"])
    return s, [Vector3(n).normalized() for n in normals]


@operation("GeoAPSGFractureTraction")
def fracture_traction(args):
    np = _np()
    s, normals = _stress(args)
    return _result(args, {"normal_compression": "MPa", "shear_magnitude": "MPa", "physical_traction_ned": "MPa"},
                   normal_compression=[float(s.normal_stress(n)) for n in normals],
                   shear_magnitude=[float(s.shear_stress(n)) for n in normals],
                   physical_traction_ned=[np.asarray(s.cauchy(n)).tolist() for n in normals])


@operation("GeoAPSGFaultReactivation")
def fault_reactivation(args):
    s, normals = _stress(args)
    pressure = args["pore_pressure_mpa"]
    effective = s.effective(pressure)
    if abs(s.sigma1 - s.sigma3) <= 1e-8:
        reject("Hydrostatic stress has no defined dilation tendency", "unsupported_conditions")
    sn = [float(effective.normal_stress(n)) for n in normals]
    if min(sn) <= 1e-8:
        reject("Open/tensile fractures are outside the frictional reactivation model", "unsupported_conditions")
    tau = [float(effective.shear_stress(n)) for n in normals]
    margin = [t - (args["cohesion_mpa"] + args["friction_coefficient"] * normal) for t, normal in zip(tau, sn)]
    return _result(args, {"effective_normal_compression": "MPa", "slip_tendency": "1", "dilation_tendency": "1", "coulomb_excess": "MPa"},
                   effective_normal_compression=sn, slip_tendency=[float(s.slip_tendency(n, fp=pressure)) for n in normals],
                   dilation_tendency=[float(s.dilation_tendency(n, fp=pressure)) for n in normals], coulomb_excess=margin)


def _chem(args, field="values"):
    np = _np()
    a = _array(args[field], 2)
    labels = args["components"]
    if len(labels) != len(set(labels)) or a.shape[1] != len(labels) or np.any(a <= 0):
        reject("Composition columns must be unique, aligned, strictly positive and in one declared unit")
    return a


def _basis(value, dimensions):
    np = _np()
    p = _array(value, 2)
    if p.shape != (dimensions - 1, dimensions) or not np.allclose(p @ p.T, np.eye(dimensions - 1), atol=1e-8, rtol=0) or not np.allclose(p.sum(axis=1), 0, atol=1e-8, rtol=0):
        reject("ILR basis must be orthonormal and span the zero-sum contrast subspace")
    return p


@operation("GeoPyroliteALR")
def additive_logratio(args):
    from pyrolite.comp.codata import ALR, inverse_ALR
    a = _chem(args)
    if args["denominator"] not in args["components"]:
        reject("ALR denominator must be a supplied component")
    index = args["components"].index(args["denominator"])
    transformed = ALR(a, ind=index)
    return _result(args, {"alr": "ln_ratio", "closed_compositions": "fraction"},
                   components=args["components"], denominator=args["denominator"], alr=transformed.tolist(),
                   closed_compositions=inverse_ALR(transformed, ind=index).tolist())


@operation("GeoPyroliteILR")
def isometric_logratio(args):
    from pyrolite.comp.codata import ILR, inverse_ILR
    a = _chem(args)
    p = _basis(args["basis"], a.shape[1])
    transformed = ILR(a, psi=p)
    return _result(args, {"ilr": "orthonormal_ln_ratio", "closed_compositions": "fraction", "basis": "1"},
                   components=args["components"], ilr=transformed.tolist(), basis=p.tolist(),
                   closed_compositions=inverse_ILR(transformed, psi=p).tolist())


@operation("GeoPyroliteCompositionalCenter")
def compositional_center(args):
    import pandas as pd
    from pyrolite.comp.codata import logratiomean
    a = _chem(args)
    if len(a) < 2:
        reject("A compositional population center needs at least two samples")
    center = logratiomean(pd.DataFrame(a, columns=args["components"]))
    return _result(args, {"center": "fraction"}, components=args["components"], center=center.to_numpy(dtype=float).tolist())


@operation("GeoPyroliteSphericalComposition")
def spherical_composition(args):
    from pyrolite.comp.codata import sphere, inverse_sphere
    a = _chem(args)
    angles = sphere(a)
    return _result(args, {"angles": "radian", "closed_compositions": "fraction"},
                   components=args["components"], angles=angles.tolist(), closed_compositions=inverse_sphere(angles).tolist())


@operation("GeoPyroliteMineralEndmemberUnmix")
def mineral_endmember_unmix(args):
    from pyrolite.mineral.normative import unmix
    np = _np()
    a, parts = _array(args["compositions"], 2), _array(args["endmembers"], 2)
    if a.shape[1] != parts.shape[1] or a.shape[1] != len(args["components"]) or len(parts) != len(args["endmember_labels"]):
        reject("Chemical components and endmembers must align")
    if len(set(args["components"])) != len(args["components"]) or len(set(args["endmember_labels"])) != len(parts):
        reject("Component and endmember labels must be unique")
    if np.any(a < 0) or np.any(parts < 0) or not np.allclose(a.sum(axis=1), 1, atol=1e-8, rtol=0) or not np.allclose(parts.sum(axis=1), 1, atol=1e-8, rtol=0):
        reject("Explicit complete mass-fraction compositions must each sum to one")
    if np.linalg.matrix_rank(parts) != len(parts):
        reject("Supplied endmembers are not linearly independent", "unsupported_conditions")
    # Upstream's multi-row constraint is global. Independent one-row fits avoid it.
    weights = np.vstack([unmix(row[None, :], parts, order=2, det_lim=0) for row in a])
    reconstructed = weights @ parts
    error = np.sqrt(np.mean((a - reconstructed) ** 2, axis=1))
    if not np.isfinite(weights).all() or np.any(weights < -1e-8) or np.any(error > args["maximum_rmse"]):
        reject("Upstream endmember solution fails the declared reconstruction tolerance", "invalid_result")
    return _result(args, {"weights": "endmember_model_fraction", "reconstructed": "mass_fraction", "rmse": "mass_fraction"},
                   endmember_labels=args["endmember_labels"], weights=weights.tolist(), reconstructed=reconstructed.tolist(), rmse=error.tolist())


@operation("GeoPyroliteCIPWNorm")
def cipw_normative_mineralogy(args):
    import pandas as pd
    import pyrolite.geochem  # Registers the upstream DataFrame accessor.
    from pyrolite.mineral.normative import CIPW_norm
    majors, minor = args["major_wt_percent"], args["minor_ppm"]
    if sum(majors.values()) <= 0 or sum(majors.values()) > 102:
        reject("Major oxide total must be positive and at most 102 wt percent")
    if (majors["FeO"] == 0) != (majors["Fe2O3"] == 0):
        reject("This release would infer redox when only one Fe species is positive; supply both positive or both zero", "unsupported_conditions")
    result = CIPW_norm(pd.DataFrame([{**majors, **minor}]), adjust_all_Fe=False, rounding=6)
    return _result(args, {"normative_wt_percent": "wt_percent", "input_major_total": "wt_percent"},
                   mineral_names=list(result.columns), normative_wt_percent=result.iloc[0].to_numpy(dtype=float).tolist(),
                   input_major_total=float(sum(majors.values())))


def _spatial(args, maximum=256):
    np = _np()
    coordinates = _array(args["coordinates_m"], 2)
    values = _array(args["values"], 1)
    if coordinates.shape != (len(values), 2) or not 4 <= len(values) <= maximum or len(np.unique(coordinates, axis=0)) != len(values):
        reject("Require distinct projected two-dimensional sample coordinates aligned to at least four values")
    return coordinates, values


@operation("GeoSKGstatRobustVariogram")
def robust_variogram_comparison(args):
    from skgstat import Variogram
    from skgstat.estimators import matheron, cressie, dowd
    np = _np()
    xy, z = _spatial(args)
    bins = _array(args["lag_upper_edges_m"], 1)
    if bins[0] <= 0 or np.any(np.diff(bins) <= 0):
        reject("Lag upper edges must be strictly increasing and positive")
    v = Variogram(xy, z, bin_func=bins, fit_method=None, normalize=False)
    groups = list(v.lag_classes())
    counts = [len(g) for g in groups]
    if not any(counts):
        reject("No pairs fall inside the declared lag bins", "empty_input")
    # One diagnostic tool compares estimators; each estimator is an upstream kernel.
    classical = [float(matheron(g)) if len(g) else None for g in groups]
    robust = [float(cressie(g)) if len(g) else None for g in groups]
    medians = [float(dowd(g)) if len(g) else None for g in groups]
    squared = args["value_unit"] + "^2"
    return _result(args, {"lag_upper_edges_m": "m", "matheron": squared, "cressie_hawkins": squared, "dowd": squared, "pair_counts": "count"},
                   lag_upper_edges_m=v.bins.tolist(), pair_counts=counts, matheron=classical, cressie_hawkins=robust, dowd=medians)


@operation("GeoSKGstatSpaceTimeVariogram")
def space_time_variogram(args):
    from skgstat import SpaceTimeVariogram
    np = _np()
    xy, z = _array(args["coordinates_m"], 2), _array(args["values_by_station_time"], 2)
    if xy.shape != (len(z), 2) or len(np.unique(xy, axis=0)) != len(xy) or len(z) > 32 or not 4 <= z.shape[1] <= 16:
        reject("Need distinct stations and 4-16 equally spaced times per station")
    if np.ptp(z) <= 0:
        reject("A constant space-time field is outside this release's fitting preconditions", "unsupported_conditions")
    options = dict(x_lags=args["spatial_lags"], t_lags=args["temporal_lags"], estimator="matheron", xbins="even", tbins="even")
    forward = SpaceTimeVariogram(xy, z, **options)
    reverse = SpaceTimeVariogram(xy, z[:, ::-1].copy(), **options)
    counts = np.array([len(g) for g in forward.lag_classes()], dtype=int)
    # Release kernel includes only xi<xj, ti<tj. Both time orderings include both
    # cross-time directions without substituting a locally implemented estimator.
    values = (forward.experimental + reverse.experimental) / 2
    if not np.isfinite(values[counts > 0]).all():
        reject("Nonempty upstream space-time bins returned nonfinite results", "invalid_result")
    width = args["temporal_lags"]
    rows = [[float(values[i + j]) if counts[i + j] else None for j in range(width)] for i in range(0, len(values), width)]
    return _result(args, {"spatial_upper_edges": "m", "temporal_upper_edges": "day", "semivariance": args["value_unit"] + "^2", "pair_counts": "count"},
                   spatial_upper_edges=forward.xbins.tolist(), temporal_upper_edges=(forward.tbins * args["time_step_days"]).tolist(),
                   semivariance=rows, pair_counts=(2 * counts).reshape(args["spatial_lags"], width).tolist())


@operation("GeoGSToolsVariogramFit")
def exponential_variogram_fit(args):
    import gstools as gs
    np = _np()
    lag, gamma = _array(args["lag_centers_m"], 1), _array(args["semivariance"], 1)
    if lag.shape != gamma.shape or len(lag) < 5 or np.any(np.diff(lag) <= 0) or lag[0] < 0 or np.any(gamma < 0) or np.ptp(gamma) <= 1e-12:
        reject("Fit requires five aligned increasing lags and nonconstant nonnegative semivariances")
    if np.max(gamma) <= args["fixed_nugget"]:
        reject("Fixed nugget must be below the observed variogram maximum")
    model = gs.Exponential(dim=3, nugget=args["fixed_nugget"])
    _, covariance, r2 = model.fit_variogram(lag, gamma, nugget=False, anis=False, loss="linear", max_eval=1000, return_r2=True)
    if not np.isfinite(covariance).all() or model.var <= 0 or model.len_scale <= 0:
        reject("Variogram parameters are not identifiable from these bins", "invalid_result")
    return _result(args, {"correlated_variance": args["value_unit"] + "^2", "length_scale_m": "m", "nugget": args["value_unit"] + "^2", "fitted_semivariance": args["value_unit"] + "^2", "r_squared": "1"},
                   correlated_variance=float(model.var), length_scale_m=float(model.len_scale), nugget=float(model.nugget),
                   fitted_semivariance=model.variogram(lag).tolist(), r_squared=float(r2))


@operation("GeoGSToolsBlockSupportCovariance")
def block_support_covariance(args):
    import gstools as gs
    from scipy.spatial.distance import cdist
    np = _np()
    a, b = _array(args["support_a_m"], 2), _array(args["support_b_m"], 2)
    if a.shape[1] != 3 or b.shape[1] != 3 or len(np.unique(a, axis=0)) != len(a) or len(np.unique(b, axis=0)) != len(b):
        reject("Each discrete support requires unique three-dimensional quadrature nodes")
    model = gs.Exponential(dim=3, var=args["point_variance"], len_scale=args["length_scale_m"], nugget=0)
    va = float(model.covariance(cdist(a, a)).mean())
    vb = float(model.covariance(cdist(b, b)).mean())
    cov = float(model.covariance(cdist(a, b)).mean())
    unit = args["value_unit"] + "^2"
    return _result(args, {"variance_a": unit, "variance_b": unit, "cross_covariance": unit, "difference_variance": unit},
                   variance_a=va, variance_b=vb, cross_covariance=cov, difference_variance=va + vb - 2 * cov)


@operation("GeoSKGstatKrigingLOO")
def kriging_leave_one_out(args):
    from skgstat import OrdinaryKriging
    from scipy.spatial.distance import pdist
    np = _np()
    xy, z = _spatial(args, maximum=32)
    if max(pdist(xy)) >= args["effective_range_m"]:
        reject("Every held-out fold must retain all samples inside the supplied model's effective range")
    if args["partial_sill"] + args["nugget"] <= 0:
        reject("The supplied variogram must have positive total sill")
    model = {"model": "spherical", "effective_range": args["effective_range_m"], "sill": args["partial_sill"], "nugget": args["nugget"], "dist_func": "euclidean"}
    predicted = []
    for i in range(len(z)):
        keep = np.arange(len(z)) != i
        fit = OrdinaryKriging(model, coordinates=xy[keep], values=z[keep], min_points=2,
                              max_points=int(keep.sum()), mode="exact", n_jobs=1)
        prediction = float(fit.transform([xy[i, 0]], [xy[i, 1]])[0])
        if not np.isfinite(prediction) or fit.singular_error or fit.no_points_error or fit.ill_matrix:
            reject("A held-out fold failed; no folds are silently omitted", "invalid_result")
        predicted.append(prediction)
    residuals = np.asarray(predicted) - z
    return _result(args, {"held_out_predictions": args["value_unit"], "residuals": args["value_unit"], "rmse": args["value_unit"], "mean_error": args["value_unit"]},
                   held_out_predictions=predicted, residuals=residuals.tolist(), rmse=float(np.sqrt(np.mean(residuals ** 2))), mean_error=float(residuals.mean()))


@operation("GeoGeochemBackgroundDistance")
def geochemical_background_distance(args):
    from pyrolite.comp.codata import ILR
    from sklearn.covariance import EmpiricalCovariance
    np = _np()
    samples, background = _chem(args, "samples"), _chem(args, "background")
    basis = _basis(args["basis"], samples.shape[1])
    if len(background) < samples.shape[1] + 1:
        reject("The declared background requires more samples than composition dimensions")
    bg, obs = ILR(background, psi=basis), ILR(samples, psi=basis)
    if np.linalg.matrix_rank(bg - bg.mean(axis=0)) < bg.shape[1] or np.linalg.cond(np.atleast_2d(np.cov(bg, rowvar=False))) > 1e8:
        reject("Background covariance is rank-deficient or ill-conditioned", "unsupported_conditions")
    model = EmpiricalCovariance(assume_centered=False).fit(bg)
    distances = model.mahalanobis(obs)
    return _result(args, {"squared_mahalanobis": "1", "background_ilr_mean": "orthonormal_ln_ratio", "background_ilr_covariance": "ln_ratio^2"},
                   squared_mahalanobis=distances.tolist(), background_ilr_mean=model.location_.tolist(),
                   background_ilr_covariance=model.covariance_.tolist())


@operation("GeoLasioLogAudit")
def las_log_audit(args):
    from lasio import LASFile
    np = _np()
    path = Path(args["las_path"])
    if path.suffix.lower() != ".las" or path.stat().st_size > 2_000_000:
        reject("This bounded LAS profile accepts local .las files up to 2 MB")
    text = path.read_text(encoding="utf-8-sig")
    las = LASFile(io.StringIO(text), engine="normal", read_policy=(), null_policy="strict", ignore_header_errors=False)
    data = np.asarray(las.data, dtype=float)
    if data.ndim != 2 or not 2 <= len(data) <= 10000 or not 2 <= data.shape[1] <= 32:
        reject("LAS needs 2-10000 depth rows and 1-31 measurement curves")
    depth = data[:, 0]
    if str(las.curves[0].unit).strip().upper() not in ("M", "METER", "METRE"):
        reject("The LAS depth curve must explicitly declare metres", "unsupported_conditions")
    if not np.isfinite(depth).all() or np.any(np.diff(depth) <= 0) or depth[0] < 0:
        reject("LAS depths must be finite, nonnegative and strictly increasing")
    if np.isinf(data).any():
        reject("Infinite LAS curve values are invalid")
    records = []
    for j, curve in enumerate(las.curves[1:], start=1):
        if not str(curve.unit).strip():
            reject("Every LAS measurement curve needs explicit units")
        values = data[:, j]
        records.append({"mnemonic": str(curve.mnemonic), "unit": str(curve.unit),
                        "values": [float(v) if np.isfinite(v) else None for v in values],
                        "valid_count": int(np.isfinite(values).sum()), "null_count": int(np.isnan(values).sum())})
    return _result(args, {"depth_m": "m", "row_count": "count", "curve_values": "per_curve_explicit_unit"},
                   depth_m=depth.tolist(), row_count=len(depth), curves=records)


@operation("GeoWellyMinimumCurvature")
def drillhole_minimum_curvature(args):
    from welly.tools import compute_position_log
    np = _np()
    survey = _array(args["survey_md_inc_azi"], 2)
    if survey.shape[1] != 3 or survey[0, 0] != 0 or np.any(np.diff(survey[:, 0]) <= 0):
        reject("Survey must start at measured depth zero and increase strictly")
    if np.any((survey[:, 1] < 0) | (survey[:, 1] >= 180)) or np.any((survey[:, 2] < 0) | (survey[:, 2] >= 360)):
        reject("Inclination is from downward vertical; azimuth must lie in [0,360)")
    _, position, dogleg = compute_position_log(survey.copy(), td=None, method="mc", azimuth_datum=0, course_length=30)
    if not np.isfinite(position).all() or not np.isfinite(dogleg).all():
        reject("Upstream trajectory returned a nonfinite station", "invalid_result")
    return _result(args, {"east_north_tvd": "m", "dogleg_severity": "degree/30m", "measured_depth": "m"},
                   east_north_tvd=position.tolist(), dogleg_severity=dogleg.tolist(), measured_depth=survey[:, 0].tolist())


def _log_curve(args):
    from welly import Curve
    np = _np()
    depth, values = _array(args["depth_m"], 1), _array(args["values"], 1)
    if depth.shape != values.shape or np.any(np.diff(depth) <= 0) or depth[0] < 0:
        reject("Log values require aligned strictly increasing nonnegative depths")
    return Curve(values, index=depth, index_name="MD", index_units="m", units=args["value_unit"], mnemonic="MEASURED"), depth, values


@operation("GeoWellyLogResample")
def log_depth_resample(args):
    np = _np()
    curve, depth, _ = _log_curve(args)
    start, stop, step = args["start_m"], args["stop_m"], args["step_m"]
    intervals = (stop - start) / step
    if start < depth[0] or stop > depth[-1] or stop <= start or intervals > 9999 or abs(intervals - round(intervals)) > 1e-8:
        reject("Requested basis must be within observed depths, contain an integer number of steps and at most 10000 samples")
    # Passing an explicit basis avoids upstream floor-division endpoint changes.
    basis = np.linspace(start, stop, int(round(intervals)) + 1)
    resampled = curve.to_basis(basis=basis, interp_kind="linear")
    return _result(args, {"depth_m": "m", "resampled_values": args["value_unit"]},
                   depth_m=resampled.df.index.to_numpy(dtype=float).tolist(), resampled_values=resampled.as_numpy().tolist())


@operation("GeoWellyLogDespike")
def log_median_despike(args):
    np = _np()
    curve, depth, original = _log_curve(args)
    window = args["window_samples"]
    if window > len(depth) or window % 2 != 1 or not np.allclose(np.diff(depth), depth[1] - depth[0], atol=1e-8, rtol=1e-8):
        reject("Despiking requires a regular depth basis and an odd window no longer than the log")
    filtered = _array(curve.despike(window_length=window, samples=True, z=args["standard_deviation_multiplier"]).as_numpy(), 1)
    return _result(args, {"depth_m": "m", "original_values": args["value_unit"], "filtered_values": args["value_unit"], "changed_indices": "zero_based_index"},
                   depth_m=depth.tolist(), original_values=original.tolist(), filtered_values=filtered.tolist(),
                   changed_indices=np.flatnonzero(np.abs(filtered - original) > 1e-10).tolist())


@operation("GeoWellyLogFaciesBlock")
def log_facies_block(args):
    np = _np()
    curve, depth, original = _log_curve(args)
    cutoffs = _array(args["cutoffs"], 1)
    if np.any(np.diff(cutoffs) <= 0) or len(args["class_labels"]) != len(cutoffs) + 1 or len(set(args["class_labels"])) != len(args["class_labels"]):
        reject("Ordered cutoffs require exactly one unique declared label per interval")
    classes = np.asarray(curve.block(cutoffs=cutoffs, right=False).as_numpy(), dtype=int)
    if not np.any(classes[1:] != classes[:-1]):
        reject("This upstream release cannot reduce a single uninterrupted block", "unsupported_conditions")
    blocked = _array(curve.block(cutoffs=cutoffs, right=False, function=np.mean).as_numpy(), 1)
    return _result(args, {"depth_m": "m", "class_indices": "zero_based_class", "block_mean_values": args["value_unit"], "original_values": args["value_unit"]},
                   depth_m=depth.tolist(), class_indices=classes.tolist(), class_labels=args["class_labels"],
                   block_mean_values=blocked.tolist(), original_values=original.tolist())


@operation("GeoStriplogIntervalIntersection")
def drillhole_interval_intersection(args):
    from striplog import Interval
    def intervals(rows):
        previous = -1.0
        result = []
        for row in rows:
            if row["base_m"] <= row["top_m"] or row["top_m"] < previous:
                reject("Each interval series must be depth ordered, nonoverlapping, and of positive thickness")
            previous = row["base_m"]
            result.append((row["label"], Interval(row["top_m"], row["base_m"], description=row["label"])))
        return result
    left, right = intervals(args["left_intervals"]), intervals(args["right_intervals"])
    intersections = []
    for ll, li in left:
        for rl, ri in right:
            if max(li.top.z, ri.top.z) >= min(li.base.z, ri.base.z):
                continue
            part = li.intersect(ri)
            intersections.append({"left_label": ll, "right_label": rl, "top_m": float(part.top.z),
                                  "base_m": float(part.base.z), "thickness_m": float(part.thickness)})
    return _result(args, {"interval_depths": "m", "total_overlap_m": "m"}, hole_id=args["hole_id"],
                   intersections=intersections, total_overlap_m=sum(r["thickness_m"] for r in intersections))

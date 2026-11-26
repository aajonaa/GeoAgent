"""Bounded upstream geophysical kernels. Source authored; NOT TESTED/DEPLOYED/SUBMITTED.

All imports of scientific dependencies are lazy. No network, installation, arbitrary
dispatch, generated code, file inputs, or inferred mineral grade is permitted.
Rockphypy 0.0.2 is GPLv3; Equinor rock-physics-open 1.0.1 is LGPLv3.
Dependency licenses are not relicensed by this adapter. R2 acceptance NOT RUN.
"""
import math
import warnings

from .collection_contracts import operation, reject


def _pack(args, units, **values):
    import numpy as np
    result = {"input_source": args["input_source"], "units": units}
    for key, value in values.items():
        array = np.asarray(value)
        if not np.isfinite(array).all():
            reject("Upstream returned nonfinite scientific results", "invalid_result")
        result[key] = array.tolist()
    return result


def _moduli(args, bulk, shear):
    import numpy as np
    if np.any(np.asarray(bulk) <= 0) or np.any(np.asarray(shear) <= 0):
        reject("Effective medium is not elastically stable", "unsupported_conditions")
    return _pack(args, {"bulk_gpa": "GPa", "shear_gpa": "GPa"},
                 bulk_gpa=float(np.asarray(bulk).item()),
                 shear_gpa=float(np.asarray(shear).item()))


def _aligned(*values):
    if len({len(value) for value in values}) != 1:
        reject("Paired scientific arrays must have identical lengths")


def _fractions(values):
    if not math.isclose(math.fsum(values), 1.0, rel_tol=0, abs_tol=1e-8):
        reject("Volume fractions must sum to one; no implicit normalization")


def _matrix(value, symmetry=None):
    import numpy as np
    c = np.asarray(value, dtype=float)
    if c.shape != (6, 6) or not np.isfinite(c).all():
        reject("Expected a finite 6 by 6 stiffness matrix")
    if not np.allclose(c, c.T, rtol=1e-9, atol=1e-10):
        reject("Stiffness must be symmetric")
    if np.linalg.eigvalsh(c).min() <= 1e-8:
        reject("Stiffness must be positive definite")
    if symmetry:
        expected = np.diag(np.diag(c))
        expected[:3, :3] = c[:3, :3]
        if not np.allclose(c, expected, rtol=1e-9, atol=1e-10):
            reject("Only symmetry-aligned orthorhombic/TI Voigt stiffness is accepted")
    if symmetry == "vti":
        pairs = [(c[0, 0], c[1, 1]), (c[0, 2], c[1, 2]),
                 (c[3, 3], c[4, 4]), (c[0, 1], c[0, 0] - 2*c[5, 5])]
        if any(not math.isclose(x, y, rel_tol=1e-8, abs_tol=1e-9) for x, y in pairs):
            reject("Matrix does not have VTI symmetry about upward axis 3")
    if symmetry == "hti":
        pairs = [(c[1, 1], c[2, 2]), (c[0, 1], c[0, 2]),
                 (c[4, 4], c[5, 5]), (c[1, 2], c[2, 2] - 2*c[3, 3])]
        if any(not math.isclose(x, y, rel_tol=1e-8, abs_tol=1e-9) for x, y in pairs):
            reject("Matrix does not have HTI symmetry about horizontal axis 1")
    return c


def _frame(a):
    if not a["dry_bulk_gpa"] < a["mineral_bulk_gpa"]:
        reject("Dry bulk modulus must be less than mineral bulk modulus")


def _observations(a, source_key):
    if len(a["observations_enu_m"]) * len(a[source_key]) > 8192:
        reject("At most 8192 observation-source pairs", "resource_limit")


def _prisms(a):
    _observations(a, "prisms_wesnbt_m")
    for b in a["prisms_wesnbt_m"]:
        if not all(b[i] < b[i+1] for i in (0, 2, 4)):
            reject("Prism bounds require west<east, south<north, bottom<top")
        for p in a["observations_enu_m"]:
            if all(b[2*i] <= p[i] <= b[2*i+1] for i in range(3)):
                reject("Observation points must be strictly outside every closed prism")


def _points(a):
    _observations(a, "sources_enu_m")
    for p in a["observations_enu_m"]:
        for q in a["sources_enu_m"]:
            if math.dist(p, q) < 1e-3:
                reject("Point-source observations require at least 1 mm separation")


def _gravity_result(a, potential, acceleration, tensor):
    return _pack(a, {"potential_j_kg": "J/kg", "acceleration_enu_m_s2": "m/s^2",
                     "gradient_enu_s2": "s^-2"},
                 potential_j_kg=potential, acceleration_enu_m_s2=acceleration,
                 gradient_enu_s2=tensor)


@operation("GeoPointMassGravity")
def point_mass_gravity(a):
    """Point-mass superposition; potential, all accelerations and full tensor."""
    import numpy as np
    from choclo import point
    _points(a)
    _aligned(a["sources_enu_m"], a["masses_kg"])
    v, g, t = [], [], []
    for p in a["observations_enu_m"]:
        pv, pg, pt = 0.0, np.zeros(3), np.zeros((3, 3))
        for q, mass in zip(a["sources_enu_m"], a["masses_kg"]):
            x = (*p, *q, mass)
            pv += point.gravity_pot(*x)
            pg += [point.gravity_e(*x), point.gravity_n(*x), point.gravity_u(*x)]
            ee, nn, uu = point.gravity_ee(*x), point.gravity_nn(*x), point.gravity_uu(*x)
            en, eu, nu = point.gravity_en(*x), point.gravity_eu(*x), point.gravity_nu(*x)
            pt += [[ee, en, eu], [en, nn, nu], [eu, nu, uu]]
        v.append(pv); g.append(pg); t.append(pt)
    return _gravity_result(a, v, g, t)


@operation("GeoPrismGravity")
def prism_gravity(a):
    """Uniform density-contrast prisms; the entire gravitational field bundle."""
    import numpy as np
    from choclo import prism
    _prisms(a)
    _aligned(a["prisms_wesnbt_m"], a["density_contrast_kg_m3"])
    v, g, t = [], [], []
    for p in a["observations_enu_m"]:
        pv, pg, pt = 0.0, np.zeros(3), np.zeros((3, 3))
        for b, density in zip(a["prisms_wesnbt_m"], a["density_contrast_kg_m3"]):
            x = (*p, *b, density)
            pv += prism.gravity_pot(*x)
            pg += [prism.gravity_e(*x), prism.gravity_n(*x), prism.gravity_u(*x)]
            ee, nn, uu = prism.gravity_ee(*x), prism.gravity_nn(*x), prism.gravity_uu(*x)
            en, eu, nu = prism.gravity_en(*x), prism.gravity_eu(*x), prism.gravity_nu(*x)
            pt += [[ee, en, eu], [en, nn, nu], [eu, nu, uu]]
        v.append(pv); g.append(pg); t.append(pt)
    return _gravity_result(a, v, g, t)


@operation("GeoDipoleMagnetic")
def dipole_magnetic(a):
    """Vector magnetic field in tesla from explicitly specified dipole moments."""
    import numpy as np
    from choclo.dipole import magnetic_field
    _points(a)
    _aligned(a["sources_enu_m"], a["moments_enu_a_m2"])
    values = []
    for p in a["observations_enu_m"]:
        value = np.zeros(3)
        for q, moment in zip(a["sources_enu_m"], a["moments_enu_a_m2"]):
            value += magnetic_field(*p, *q, *moment)
        values.append(value)
    return _pack(a, {"magnetic_enu_t": "T"}, magnetic_enu_t=values)


@operation("GeoPrismMagnetic")
def prism_magnetic(a):
    """Vector magnetic field from uniformly magnetized rectangular prisms."""
    import numpy as np
    from choclo.prism import magnetic_field
    _prisms(a)
    _aligned(a["prisms_wesnbt_m"], a["magnetization_enu_a_m"])
    values = []
    for p in a["observations_enu_m"]:
        value = np.zeros(3)
        for b, moment in zip(a["prisms_wesnbt_m"], a["magnetization_enu_a_m"]):
            value += magnetic_field(*p, *b, *moment)
        values.append(value)
    return _pack(a, {"magnetic_enu_t": "T"}, magnetic_enu_t=values)


@operation("GeoRockVRHBounds")
def rock_vrh_bounds(a):
    from rockphypy import EM
    _aligned(a["fractions"], a["bulk_gpa"], a["shear_gpa"])
    _fractions(a["fractions"])
    k = EM.VRH(a["fractions"], a["bulk_gpa"])
    g = EM.VRH(a["fractions"], a["shear_gpa"])
    return _pack(a, {"bulk_vrh_gpa": "GPa", "shear_vrh_gpa": "GPa"},
                 bulk_vrh_gpa=k, shear_vrh_gpa=g)


@operation("GeoRockHashinShtrikman")
def rock_hashin_shtrikman(a):
    from rockphypy import EM
    if not (a["stiff_bulk_gpa"] > a["soft_bulk_gpa"] and
            a["stiff_shear_gpa"] > a["soft_shear_gpa"]):
        reject("Strictly ordered stiff/soft bulk and shear moduli are required")
    x = (a["stiff_fraction"], a["stiff_bulk_gpa"], a["soft_bulk_gpa"],
         a["stiff_shear_gpa"], a["soft_shear_gpa"])
    lower = EM.HS(*x, bound="lower")
    upper = EM.HS(*x, bound="upper")
    return _pack(a, {"bulk_bounds_gpa": "GPa", "shear_bounds_gpa": "GPa"},
                 bulk_bounds_gpa=[lower[0], upper[0]],
                 shear_bounds_gpa=[lower[1], upper[1]])


@operation("GeoRockCriticalPorosity")
def rock_critical_porosity(a):
    from rockphypy import EM
    if a["porosity"] >= a["critical_porosity"]:
        reject("Load-bearing critical-porosity branch requires phi < phi_c")
    k, g = EM.cripor(a["bulk_gpa"], a["shear_gpa"], a["porosity"], a["critical_porosity"])
    return _moduli(a, k, g)


@operation("GeoRockSphericalPores")
def rock_spherical_pores(a):
    from rockphypy import EM
    k, g = EM.Swiss_cheese(a["bulk_gpa"], a["shear_gpa"], a["porosity"])
    return _moduli(a, k, g)


@operation("GeoRockSelfConsistent")
def rock_self_consistent(a):
    """Unmodified Equinor SCA kernel; Pa internally, both residuals checked."""
    import numpy as np
    from rock_physics_open.shale_models.multi_sca import multi_sca
    from rock_physics_open.shale_models.pq import p_q_fcn
    _aligned(a["fractions"], a["bulk_gpa"], a["shear_gpa"],
             a["aspect_ratios"], a["density_kg_m3"])
    _fractions(a["fractions"])
    if not math.isclose(math.fsum(a["fractions"]), 1.0, rel_tol=0, abs_tol=1e-12):
        reject("Fractions must close within roundoff; no physical renormalization")
    bulk = np.asarray(a["bulk_gpa"], dtype=float) * 1e9
    shear = np.asarray(a["shear_gpa"], dtype=float) * 1e9
    fractions = np.asarray(a["fractions"], dtype=float)
    aspects = np.asarray(a["aspect_ratios"], dtype=float)
    densities = np.asarray(a["density_kg_m3"], dtype=float)
    phases = []
    for k, g, rho, aspect, fraction in zip(bulk, shear, densities, aspects, fractions):
        phases.extend(np.array([v], dtype=float) for v in (k, g, rho, aspect, fraction))
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        try:
            k, g, rho = multi_sca(*phases, tol=1e-12)
            k, g, rho = float(k.item()), float(g.item()), float(rho.item())
            if not all(math.isfinite(v) and v > 0 for v in (k, g, rho)):
                reject("SCA returned nonfinite or unstable properties", "invalid_result")
            p, q = p_q_fcn(np.full_like(bulk, k), np.full_like(shear, g),
                          bulk, shear, aspects.copy())
        except RuntimeWarning:
            reject("SCA geometry or iteration failed numerically", "unsupported_conditions")
    # Upstream stops on bulk change alone and silently returns at its iteration cap.
    # These are acceptance residuals, not a replacement solver or corrected kernel.
    bulk_residual = float(np.sum(fractions * (bulk - k) * p))
    shear_residual = float(np.sum(fractions * (shear - g) * q))
    if (not np.isfinite(p).all() or not np.isfinite(q).all()
            or not math.isfinite(bulk_residual) or not math.isfinite(shear_residual)
            or abs(bulk_residual) > 1e-8 * max(float(bulk.max()), abs(k))
            or abs(shear_residual) > 1e-8 * max(float(shear.max()), abs(g))):
        reject("SCA has not converged in both bulk and shear constitutive equations",
               "invalid_result")
    return _pack(a, {"bulk_gpa": "GPa", "shear_gpa": "GPa",
                     "density_kg_m3": "kg/m^3", "bulk_residual_pa": "Pa",
                     "shear_residual_pa": "Pa"},
                 bulk_gpa=k/1e9, shear_gpa=g/1e9, density_kg_m3=rho,
                 bulk_residual_pa=bulk_residual, shear_residual_pa=shear_residual)


@operation("GeoRockRandomCracks")
def rock_random_cracks(a):
    from rockphypy import EM
    k, g = EM.OConnell_Budiansky(a["bulk_gpa"], a["shear_gpa"], a["crack_density"])
    return _moduli(a, k, g)


@operation("GeoRockMoriTanaka")
def rock_mori_tanaka(a):
    from rockphypy import EM
    k, g = EM.MT_average(a["phase1_fraction"], a["matrix_bulk_gpa"], a["matrix_shear_gpa"],
                         a["phase1_bulk_gpa"], a["phase1_shear_gpa"],
                         a["phase2_bulk_gpa"], a["phase2_shear_gpa"])
    return _moduli(a, k, g)


@operation("GeoRockHudsonCracks")
def rock_hudson_cracks(a):
    from rockphypy import EM
    c = EM.hudson(a["bulk_gpa"], a["shear_gpa"], a["inclusion_bulk_gpa"],
                  a["inclusion_shear_gpa"], a["aspect_ratio"], a["crack_density"],
                  order=1, axis=3)
    _matrix(c, "vti")
    return _pack(a, {"stiffness_gpa": "GPa"}, stiffness_gpa=c)


@operation("GeoRockHertzMindlin")
def rock_hertz_mindlin(a):
    from rockphypy import GM
    k, g = GM.hertzmindlin(a["bulk_gpa"], a["shear_gpa"], a["porosity"],
                           a["coordination"], a["effective_stress_mpa"], a["shear_factor"])
    return _moduli(a, k, g)


@operation("GeoRockContactCement")
def rock_contact_cement(a):
    from rockphypy import GM
    if not 0 < a["critical_porosity"] - a["porosity"] <= 0.1:
        reject("Contact-cement profile requires 0 < phi_c-phi <= 0.1")
    k, g = GM.contactcement(a["bulk_gpa"], a["shear_gpa"], a["cement_bulk_gpa"],
                            a["cement_shear_gpa"], a["porosity"], a["critical_porosity"],
                            a["coordination"], scheme=1)
    return _moduli(a, k, g)


@operation("GeoRockDigbyContacts")
def rock_digby_contacts(a):
    from rockphypy import GM
    k, g = GM.Digby(a["bulk_gpa"], a["shear_gpa"], a["porosity"],
                    a["coordination"], a["effective_stress_mpa"], a["bond_radius_ratio"])
    return _moduli(a, k, g)


def rock_stress_anisotropy(a):
    """Blocked historical entrypoint; deliberately not decorated or registered."""
    reject("GeoRockStressAnisotropy is blocked: upstream Johnson logarithm is "
           "incorrect for unequal strains; no accepted maintained replacement",
           "unsupported_conditions")


@operation("GeoRockSandShalePorosity")
def rock_sand_shale_porosity(a):
    import numpy as np
    from rockphypy import GM
    if a["shale_porosity"] >= a["sand_porosity"]:
        reject("Thomas-Stieber profile requires shale porosity below clean-sand porosity")
    dispersed, laminated = GM.ThomasStieber(a["sand_porosity"], a["shale_porosity"],
                                           np.asarray(a["shale_fraction"]))
    return _pack(a, {"dispersed_porosity": "1", "laminated_porosity": "1"},
                 dispersed_porosity=dispersed, laminated_porosity=laminated)


@operation("GeoRockGassmannSubstitution")
def rock_gassmann_substitution(a):
    from rockphypy import Fluid
    _frame(a)
    if max(a["initial_fluid_bulk_gpa"], a["replacement_fluid_bulk_gpa"]) >= a["mineral_bulk_gpa"]:
        reject("Fluid bulk moduli must be below mineral bulk modulus")
    k1, _ = Fluid.Gassmann(a["dry_bulk_gpa"], a["dry_shear_gpa"], a["mineral_bulk_gpa"],
                          a["initial_fluid_bulk_gpa"], a["porosity"])
    k2 = Fluid.Gassmann_sub(a["porosity"], a["mineral_bulk_gpa"], k1,
                           a["initial_fluid_bulk_gpa"], a["replacement_fluid_bulk_gpa"])
    if not a["dry_bulk_gpa"] <= k2 < a["mineral_bulk_gpa"]:
        reject("Substituted rock violates the physical bulk-modulus bounds", "invalid_result")
    return _pack(a, {"initial_bulk_gpa": "GPa", "replacement_bulk_gpa": "GPa", "shear_gpa": "GPa"},
                 initial_bulk_gpa=k1, replacement_bulk_gpa=k2, shear_gpa=a["dry_shear_gpa"])


@operation("GeoRockBrownKorringa")
def rock_brown_korringa(a):
    import numpy as np
    from rockphypy import Fluid
    c = _matrix(a["dry_stiffness_gpa"])
    s = np.linalg.inv(c)
    if np.sum(s[:3, :3]) <= 1/a["mineral_bulk_gpa"]:
        reject("Dry compressibility must exceed mineral compressibility")
    if a["fluid_bulk_gpa"] >= a["mineral_bulk_gpa"]:
        reject("Fluid bulk modulus must be below mineral bulk modulus")
    ss = Fluid.Brown_Korringa_dry2sat(s, a["mineral_bulk_gpa"], a["mineral_shear_gpa"],
                                     a["fluid_bulk_gpa"], a["porosity"])
    cc = np.linalg.inv(ss)
    _matrix(cc)
    return _pack(a, {"saturated_stiffness_gpa": "GPa", "saturated_compliance_inv_gpa": "GPa^-1"},
                 saturated_stiffness_gpa=cc, saturated_compliance_inv_gpa=ss)


@operation("GeoRockBiotDispersion")
def rock_biot_dispersion(a):
    import numpy as np
    from rockphypy import Fluid
    _frame(a)
    frequencies = np.asarray(a["frequencies_hz"])
    if a["fluid_bulk_gpa"] >= a["mineral_bulk_gpa"]:
        reject("Fluid bulk modulus must be below mineral bulk modulus")
    zeta = np.sqrt(2*np.pi*frequencies*a["pore_radius_m"]**2*
                   a["fluid_density_kg_m3"]/a["viscosity_pa_s"])
    if np.max(zeta) > 200:
        reject("Viscodynamic argument exceeds conservative numerical bound", "unsupported_conditions")
    values = Fluid.Biot(a["dry_bulk_gpa"]*1e9, a["dry_shear_gpa"]*1e9,
                        a["mineral_bulk_gpa"]*1e9, a["fluid_bulk_gpa"]*1e9,
                        a["mineral_density_kg_m3"], a["fluid_density_kg_m3"],
                        a["viscosity_pa_s"], a["porosity"], a["permeability_m2"],
                        a["pore_radius_m"], a["tortuosity"], frequencies)
    keys = ("fast_p_m_s", "slow_p_m_s", "shear_m_s", "fast_p_inverse_q",
            "slow_p_inverse_q", "shear_inverse_q")
    return _pack(a, {key: "m/s" if key.endswith("m_s") else "1" for key in keys},
                 **dict(zip(keys, values)))


@operation("GeoRockSquirtFlow")
def rock_squirt_flow(a):
    import numpy as np
    from rockphypy import Fluid
    _aligned(a["dry_vp_m_s"], a["dry_vs_m_s"])
    vp, vs = np.asarray(a["dry_vp_m_s"]), np.asarray(a["dry_vs_m_s"])
    density_scale = a["dry_density_kg_m3"] / 1e9
    dry_bulk = density_scale * (vp*vp - (4/3)*vs*vs)
    dry_shear = density_scale * vs*vs
    high_bulk = density_scale * (a["high_pressure_vp_m_s"]**2 -
                                (4/3)*a["high_pressure_vs_m_s"]**2)
    high_shear = density_scale * a["high_pressure_vs_m_s"]**2
    if np.any(dry_bulk <= 0) or high_bulk <= 0:
        reject("Dry velocities require positive bulk modulus")
    if np.any(vp > a["high_pressure_vp_m_s"]) or np.any(vs > a["high_pressure_vs_m_s"]):
        reject("High-pressure crack-free velocities must bound the dry series")
    if a["fluid_bulk_gpa"] >= a["mineral_bulk_gpa"] or high_bulk >= a["mineral_bulk_gpa"]:
        reject("Fluid and high-pressure dry bulk moduli must be below the mineral modulus")
    if (np.any(dry_bulk > high_bulk * (1 + 1e-10))
            or np.any(dry_shear > high_shear * (1 + 1e-10))):
        reject("Crack closure requires Kdry <= Khigh and Gdry <= Ghigh; velocity bounds alone are insufficient")
    wet_shear_compliance = 1/dry_shear - (4/15)*(1/dry_bulk - 1/high_bulk)
    if (np.any(wet_shear_compliance <= 0)
            or np.any(wet_shear_compliance < (1/high_shear) * (1 - 1e-10))):
        reject("Bulk/shear crack compliances imply unstable shear or a wet frame stiffer than the crack-free shear limit")
    k, g, p, s = Fluid.Mavko_Jizba(a["high_pressure_vp_m_s"], a["high_pressure_vs_m_s"],
                                 vp, vs, a["mineral_bulk_gpa"], a["dry_density_kg_m3"]/1000,
                                 a["fluid_density_kg_m3"]/1000, a["fluid_bulk_gpa"], a["porosity"])
    if (np.any(np.asarray(g) < dry_shear * (1 - 1e-9))
            or np.any(np.asarray(g) > high_shear * (1 + 1e-9))
            or not high_bulk * (1 - 1e-9) <= float(k) < a["mineral_bulk_gpa"]):
        reject("Upstream squirt-flow output violates the supplied crack-closure bounds", "invalid_result")
    return _pack(a, {"saturated_bulk_gpa": "GPa", "saturated_shear_gpa": "GPa",
                     "vp_m_s": "m/s", "vs_m_s": "m/s"},
                 saturated_bulk_gpa=k, saturated_shear_gpa=g, vp_m_s=p, vs_m_s=s)


@operation("GeoRockPatchySaturation")
def rock_patchy_saturation(a):
    import numpy as np
    from rockphypy import Fluid
    _frame(a)
    if max(a["inner_fluid_bulk_gpa"], a["outer_fluid_bulk_gpa"]) >= a["mineral_bulk_gpa"]:
        reject("Fluid moduli must be below mineral modulus")
    try:
        with np.errstate(over="raise", divide="raise", invalid="raise"):
            vp, attenuation, modulus = Fluid.White_Dutta_Ode(
                a["dry_bulk_gpa"]*1e9, a["dry_shear_gpa"]*1e9, a["mineral_bulk_gpa"]*1e9,
                a["porosity"], a["mineral_density_kg_m3"], a["inner_density_kg_m3"],
                a["outer_density_kg_m3"], a["inner_fluid_bulk_gpa"]*1e9,
                a["outer_fluid_bulk_gpa"]*1e9, a["inner_viscosity_pa_s"],
                a["outer_viscosity_pa_s"], a["permeability_m2"], a["inner_radius_m"],
                a["inner_saturation"], np.asarray(a["frequencies_hz"]))
    except FloatingPointError:
        reject("Patch-scale diffusion is outside the stable numerical regime", "unsupported_conditions")
    return _pack(a, {"vp_m_s": "m/s", "attenuation_inv_m": "m^-1",
                     "bulk_real_gpa": "GPa", "bulk_imag_gpa": "GPa"},
                 vp_m_s=vp, attenuation_inv_m=attenuation,
                 bulk_real_gpa=modulus.real/1e9, bulk_imag_gpa=modulus.imag/1e9)


@operation("GeoRockBrieMixing")
def rock_brie_mixing(a):
    import numpy as np
    from rockphypy import Fluid
    if a["liquid_bulk_gpa"] <= a["gas_bulk_gpa"]:
        reject("Liquid modulus must exceed gas modulus")
    k = Fluid.Brie(a["liquid_bulk_gpa"], a["gas_bulk_gpa"],
                   np.asarray(a["liquid_saturation"]), a["exponent"])
    return _pack(a, {"fluid_bulk_gpa": "GPa"}, fluid_bulk_gpa=k)


@operation("GeoRockFluidPVT")
def rock_fluid_pvt(a):
    from rockphypy import BW
    t, p = a["temperature_c"], a["pressure_mpa"]
    water = BW.rho_K_water(t, p)
    brine = BW.rho_K_brine(t, p, a["salinity_mass_fraction"])
    oil = BW.rho_K_oil(p, t, a["reference_oil_density_kg_m3"]/1000)
    gas = BW.rho_K_gas(p, t, a["gas_specific_gravity"])
    values = (water, brine, oil, gas)
    if any(d <= 0 or k <= 0 for d, k in values):
        reject("PVT correlation returned a nonphysical density or modulus", "unsupported_conditions")
    return _pack(a, {"density_water_brine_oil_gas_kg_m3": "kg/m^3",
                     "bulk_water_brine_oil_gas_gpa": "GPa"},
                 density_water_brine_oil_gas_kg_m3=[d*1000 for d, k in values],
                 bulk_water_brine_oil_gas_gpa=[k for d, k in values])


@operation("GeoSeismicBackus")
def seismic_backus(a):
    from rockphypy import Anisotropy
    _aligned(a["fractions"], a["lame_lambda_gpa"], a["shear_gpa"])
    _fractions(a["fractions"])
    values = Anisotropy.Backus(a["fractions"], a["lame_lambda_gpa"], a["shear_gpa"])
    return _pack(a, {"c11_c33_c13_c44_c66_gpa": "GPa"}, c11_c33_c13_c44_c66_gpa=values)


@operation("GeoSeismicVTIPhase")
def seismic_vti_phase(a):
    import numpy as np
    from rockphypy import Anisotropy
    c = _matrix(a["stiffness_gpa"], "vti")
    vp, sh, sv = Anisotropy.vel_azi_VTI(c, a["density_kg_m3"]/1000,
                                        np.asarray(a["inclination_degrees"]))
    return _pack(a, {"vp_m_s": "m/s", "vsh_m_s": "m/s", "vsv_m_s": "m/s"},
                 vp_m_s=vp*1000, vsh_m_s=sh*1000, vsv_m_s=sv*1000)


@operation("GeoSeismicOrthorhombicParameters")
def seismic_orthorhombic_parameters(a):
    from rockphypy import Anisotropy
    c = _matrix(a["stiffness_gpa"], "orthorhombic")
    if min(c[2, 2]-c[3, 3], c[2, 2]-c[4, 4], c[0, 0]-c[5, 5]) <= 1e-8:
        reject("Tsvankin denominators require longitudinal stiffness above shear")
    parameters = Anisotropy.Thomsen_Tsvankin(c[0, 0], c[1, 1], c[2, 2], c[0, 1],
                    c[0, 2], c[1, 2], c[3, 3], c[4, 4], c[5, 5])
    return _pack(a, {"epsilon1_delta1_gamma1_epsilon2_delta2_gamma2_delta3": "1"},
                 epsilon1_delta1_gamma1_epsilon2_delta2_gamma2_delta3=parameters)


def _hti_subcritical(a, upper, lower):
    """Domain gate only: Christoffel propagation, never reflection amplitudes."""
    import numpy as np
    from scipy.linalg import eigvals
    voigt = np.array([[0, 5, 4], [5, 1, 3], [4, 3, 2]])
    def tensor(c):
        return c[voigt[:, :, None, None], voigt[None, None, :, :]]
    c1 = tensor(upper * (1e9 / a["upper_density_kg_m3"]))
    # Dimensionless quadratic in vertical slowness avoids mixed SI matrix scales.
    reference_speed = math.sqrt(lower[2, 2] * 1e9 / a["lower_density_kg_m3"])
    c2 = tensor(lower / lower[2, 2])
    identity, zero = np.eye(3), np.zeros((3, 3))
    vertical = c2[:, 2, :, 2]
    for azimuth in a["azimuth_degrees"]:
        phi = math.radians(azimuth)
        for incidence in a["incidence_degrees"]:
            theta = math.radians(incidence)
            direction = np.array([math.sin(theta)*math.cos(phi),
                                  math.sin(theta)*math.sin(phi), math.cos(theta)])
            christoffel = np.einsum("ijkl,j,l->ik", c1, direction, direction)
            incident_vp = math.sqrt(float(np.linalg.eigvalsh(christoffel)[-1]))
            horizontal = direction[:2] * (reference_speed / incident_vp)
            linear = sum((c2[:, 2, :, h] + c2[:, h, :, 2]) * horizontal[h]
                         for h in range(2))
            constant = sum(c2[:, h, :, j] * horizontal[h] * horizontal[j]
                           for h in range(2) for j in range(2)) - identity
            roots = eigvals(np.block([[zero, identity], [-constant, -linear]]),
                            np.block([[identity, zero], [zero, vertical]]))
            if (not np.isfinite(roots).all()
                    or np.any(np.abs(roots.imag) > 1e-8 * (1 + np.abs(roots.real)))
                    or np.min(np.abs(roots.real)) <= 1e-7):
                reject("Critical/postcritical transmitted mode for the actual HTI stiffness, density and azimuth",
                       "unsupported_conditions")


@operation("GeoSeismicHTIReflectivity")
def seismic_hti_reflectivity(a):
    import numpy as np
    from rockphypy import AVO
    c1, c2 = _matrix(a["upper_stiffness_gpa"], "hti"), _matrix(a["lower_stiffness_gpa"], "hti")
    for c in (c1, c2):
        if c[2, 2] <= c[4, 4]:
            reject("HTI longitudinal stiffness must exceed shear stiffness")
        epsilon = (c[0, 0]-c[2, 2])/(2*c[2, 2])
        gamma = (c[3, 3]-c[5, 5])/(2*c[5, 5])
        delta = ((c[0, 2]+c[4, 4])**2-(c[2, 2]-c[4, 4])**2)/(2*c[2, 2]*(c[2, 2]-c[4, 4]))
        if max(abs(epsilon), abs(gamma), abs(delta)) > 0.2:
            reject("Ruger approximation requires weak anisotropy (absolute parameters <=0.2)")
    _hti_subcritical(a, c1, c2)
    r = AVO.AVO_HTI(a["upper_density_kg_m3"]/1000, a["lower_density_kg_m3"]/1000,
                    c1, c2, np.asarray(a["incidence_degrees"]), np.asarray(a["azimuth_degrees"]))
    return _pack(a, {"pp_reflectivity_azimuth_by_angle": "1"},
                 pp_reflectivity_azimuth_by_angle=r)


@operation("GeoSeismicZoeppritzScattering")
def seismic_zoeppritz_scattering(a):
    import numpy as np
    from bruges.reflection import scattering_matrix
    for prefix in ("upper", "lower"):
        if a[prefix+"_vp_m_s"]**2 <= (4/3)*a[prefix+"_vs_m_s"]**2:
            reject("Each isotropic medium requires positive bulk modulus")
    matrices = []
    for theta in a["incidence_degrees"]:
        matrices.append(scattering_matrix(
            a["upper_vp_m_s"], a["upper_vs_m_s"], a["upper_density_kg_m3"],
            a["lower_vp_m_s"], a["lower_vs_m_s"], a["lower_density_kg_m3"], theta))
    m = np.asarray(matrices).reshape((-1, 4, 4))
    return _pack(a, {"scattering_real": "1", "scattering_imag": "1"},
                 scattering_real=m.real, scattering_imag=m.imag)


@operation("GeoSeismicElasticImpedance")
def seismic_elastic_impedance(a):
    import numpy as np
    from rockphypy import AVO
    _aligned(a["vp_m_s"], a["vs_m_s"], a["density_kg_m3"])
    vp, vs, density = (np.asarray(a[k]) for k in ("vp_m_s", "vs_m_s", "density_kg_m3"))
    if np.any(vp*vp <= (4/3)*vs*vs):
        reject("Each layer requires positive isotropic bulk modulus")
    # A single supplied SP is part of the upstream approximation; reject its
    # SV-to-P critical singularity rather than silently clipping arcsin.
    angles = np.asarray(a["incidence_degrees"])
    if np.max((vs/vp)[:, None]*np.sin(np.radians(angles))[None, :]/a["shear_p_ratio"]) >= 0.95:
        reject("Reference ratio crosses the SV-to-P approximation domain")
    values = AVO.EI_ref(vp, vs, density, angles, a["shear_p_ratio"], norm=True)
    keys = ("pp", "psv", "svp", "svsv", "shsh")
    return _pack(a, {key: "kg/(m^2*s)" for key in keys}, **dict(zip(keys, values)))

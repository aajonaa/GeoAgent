"""Expansion501 geology source adapters. Unverified; no runtime registration here.

Only fixed upstream kernels are called. The parent must stage the contribution
and bind a dedicated CPU environment before invoking any decorated function.
No installs, network operations, shell dispatch, pickle, or artifacts.
"""
import contextlib
import io
import json
import math
import os
from importlib import metadata

from geological_agent.geology.collection_contracts import operation, reject

_ELEMENTS = set(("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
                 "Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba "
                 "La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb "
                 "Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs "
                 "Mt Ds Rg Cn Nh Fl Mc Lv Ts Og").split())
_OXIDES = {"SiO2", "TiO2", "Al2O3", "FeO", "Fe2O3", "MnO", "MgO", "CaO", "Na2O", "K2O", "Cr2O3", "NiO"}
_REE = ["La", "Ce", "Pr", "Nd", "Sm", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu"]
_CPU_ID = "expansion501-geology-cpu-v1"


def _np():
    if os.environ.get("GEOAGENT_EXPANSION501_GEOLOGY_CPU") != _CPU_ID:
        reject("Parent-bound private CPU environment is required; no accepted profile is changed.", "missing_dependency")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "":
        reject("The private CPU worker must explicitly hide CUDA devices.", "unsupported_conditions")
    import numpy as np
    return np


def _array(value, ndim=None, shape=None, lower=None, upper=None):
    np = _np()
    a = np.asarray(value, dtype=float)
    if a.size == 0 or a.size > 262144 or not np.isfinite(a).all():
        reject("Numeric arrays must be nonempty, finite and bounded.")
    if ndim is not None and a.ndim != ndim:
        reject("Incorrect array rank.")
    if shape is not None and a.shape != tuple(shape):
        reject("Array shapes do not agree.")
    if lower is not None and (a < lower).any():
        reject("Value below the declared domain.")
    if upper is not None and (a > upper).any():
        reject("Value above the declared domain.")
    return a


def _plain(value):
    if hasattr(value, "tolist"):
        return _plain(value.tolist())
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        reject("Upstream returned a nonfinite result.", "invalid_result")
    return value


def _result(args, units, **data):
    value = {**data, "input_source": args["data_source"], "units": units}
    value = _plain(value)
    if len(json.dumps(value, allow_nan=False).encode("utf-8")) > 8_000_000:
        reject("Result exceeds the bounded JSON delivery budget.", "resource_limit")
    return value


def _cell_arrays(data):
    np = _np()
    lattice = _array(data["lattice_angstrom"], shape=(3, 3))
    frac = _array(data["fractional_coords"], ndim=2, lower=0, upper=1)
    species = data["species"]
    if frac.shape != (len(species), 3) or not 1 <= len(species) <= 128:
        reject("One fractional coordinate is required per ordered atomic site.")
    if any(s not in _ELEMENTS for s in species) or (frac >= 1).any():
        reject("Only ordered elemental sites in the half-open fractional cell are supported.")
    volume = float(np.linalg.det(lattice))
    lengths = np.linalg.norm(lattice, axis=1)
    if not 0.01 <= volume <= 1e6 or np.linalg.cond(lattice) > 1e4:
        reject("Lattice must be right-handed, nonsingular and well conditioned.")
    if (lengths < 1).any() or (lengths > 100).any():
        reject("Lattice vector lengths must be between 1 and 100 angstrom.")
    if len({tuple(x) for x in frac.tolist()}) != len(frac):
        reject("Coincident fractional sites are not accepted.")
    types = {s: i + 1 for i, s in enumerate(sorted(set(species)))}
    return lattice, frac, [types[s] for s in species]


def _structure(data):
    np = _np()
    from pymatgen.core import Structure
    lattice, frac, _ = _cell_arrays(data)
    s = Structure(lattice, data["species"], frac, coords_are_cartesian=False)
    distances = s.distance_matrix + np.eye(len(s)) * 1e9
    if len(s) > 1 and float(distances.min()) < 0.25:
        reject("Atomic sites closer than 0.25 angstrom are not physically supported.")
    return s


def _formula(value):
    from pymatgen.core import Composition
    import re
    if not re.fullmatch(r"(?:[A-Z][a-z]?[0-9]*(?:\.[0-9]+)?){1,16}", value):
        reject("Use a bounded simple elemental formula, not an expression or serialized object.")
    c = Composition(value, strict=True)
    if c.num_atoms <= 0 or c.num_atoms > 1000 or any(e.symbol not in _ELEMENTS for e in c.elements):
        reject("Unsupported formula.")
    return c


def _miller(value):
    values = tuple(int(v) for v in value)
    if len(values) != 3 or not any(values) or math.gcd(*values) != 1:
        reject("A primitive nonzero three-index Miller vector is required.")
    return values


def _volume(args, field="pore_mask"):
    np = _np()
    shape = tuple(args["shape"])
    if not 2 <= len(shape) <= 3 or any(not 3 <= n <= 64 for n in shape) or math.prod(shape) > 32768:
        reject("Pore geometry must have 2 or 3 axes and at most 32768 voxels.", "resource_limit")
    a = np.asarray(args[field], dtype=bool)
    if a.ndim != 1 or a.size != math.prod(shape):
        reject("C-order flat mask does not match the explicit shape.")
    a = a.reshape(shape)
    if not a.any() or a.all():
        reject("A pore mask must contain both void and solid.")
    return a


def _edges(values):
    np = _np()
    e = _array(values, ndim=1, lower=0)
    if len(e) < 2 or not (np.diff(e) > 0).all():
        reject("Histogram edges must be strictly increasing.")
    return e


class _BoundedLog(io.TextIOBase):
    """Suppress upstream progress without storing unbounded output."""
    def __init__(self):
        self.characters = 0

    def write(self, value):
        self.characters += len(value)
        if self.characters > 65536:
            reject("Upstream diagnostic output exceeded 64K characters.", "resource_limit")
        return len(value)

    def flush(self):
        return None


@operation("Geo500CrystalSpaceGroupAudit")
def crystal_space_group(args):
    np = _np()
    import spglib
    cell = _cell_arrays(args["structure"])
    ds = spglib.get_symmetry_dataset(cell, symprec=args["symprec_angstrom"], angle_tolerance=-1.0)
    if ds is None:
        reject("spglib could not determine a symmetry dataset.", "invalid_result")
    return _result(args, {"space_group_number": "1", "rotation_count": "1", "equivalent_atoms": "site_index"},
                   space_group_number=int(ds.number), international_symbol=str(ds.international),
                   hall_symbol=str(ds.hall), rotation_count=len(ds.rotations),
                   wyckoff_letters=list(ds.wyckoffs), equivalent_atoms=np.asarray(ds.equivalent_atoms, dtype=int))


@operation("Geo500IrreducibleReciprocalMesh")
def irreducible_reciprocal_mesh(args):
    np = _np()
    import spglib
    mesh = args["mesh"]
    mapping, grid = spglib.get_ir_reciprocal_mesh(
        mesh, _cell_arrays(args["structure"]), is_shift=[0, 0, 0],
        is_time_reversal=True, symprec=args["symprec_angstrom"])
    ids, weights = np.unique(mapping, return_counts=True)
    if int(weights.sum()) != math.prod(mesh):
        reject("Reciprocal weights do not conserve the full mesh.", "invalid_result")
    return _result(args, {"representative_grid_addresses": "reciprocal_mesh_integer", "weights": "1",
                          "fractional_kpoints": "reciprocal_lattice_fraction"},
                   representative_grid_addresses=np.asarray(grid)[ids],
                   weights=weights, fractional_kpoints=np.asarray(grid)[ids] / np.asarray(mesh),
                   full_mesh_size=math.prod(mesh), time_reversal=True, gamma_centered=True)


@operation("Geo500PowderXRDPattern")
def powder_xrd_pattern(args):
    _np()
    from pymatgen.analysis.diffraction.xrd import XRDCalculator
    if args["two_theta_min_degrees"] >= args["two_theta_max_degrees"]:
        reject("The diffraction angle interval is empty.")
    calc = XRDCalculator(wavelength=args["wavelength_angstrom"], symprec=0)
    pattern = calc.get_pattern(_structure(args["structure"]), scaled=True,
                               two_theta_range=(args["two_theta_min_degrees"], args["two_theta_max_degrees"]))
    if len(pattern.x) > 4096:
        reject("Diffraction result exceeds the reflection budget.", "resource_limit")
    families = [[{"hkl": [int(x) for x in f["hkl"]], "multiplicity": int(f["multiplicity"])}
                 for f in row] for row in pattern.hkls]
    return _result(args, {"two_theta_degrees": "degree", "d_spacings_angstrom": "angstrom",
                          "relative_intensity": "max_100", "wavelength_angstrom": "angstrom"},
                   two_theta_degrees=pattern.x, d_spacings_angstrom=pattern.d_hkls,
                   relative_intensity=pattern.y, hkl_families=families,
                   wavelength_angstrom=args["wavelength_angstrom"])


@operation("Geo500MineralOxygenBasisFormula")
def mineral_oxygen_basis_formula(args):
    np = _np()
    import pandas as pd
    from pyrolite.mineral.transform import recalc_cations
    oxides = args["oxides"]
    values = _array(args["oxide_wt_percent"], ndim=1, lower=0, upper=100)
    if len(oxides) != len(values) or len(set(oxides)) != len(oxides) or not set(oxides) <= _OXIDES:
        reject("Explicit distinct supported simple oxides are required.")
    if not 90 <= float(values.sum()) <= 102:
        reject("Measured mineral oxide total must lie within 90..102 wt%; no renormalization is hidden.")
    if not (values > 1e-8).any():
        reject("At least one quantified oxide is required.")
    apfu = recalc_cations(pd.Series(values, index=oxides, dtype=float),
                          ideal_cations=None, ideal_oxygens=args["oxygen_basis"],
                          oxygen_constrained=True)
    if not np.isfinite(apfu.to_numpy()).all() or (apfu < 0).any():
        reject("Nonfinite or negative structural formula.", "invalid_result")
    if abs(float(apfu["O"]) - args["oxygen_basis"]) > 1e-8:
        reject("Oxygen basis was not conserved.", "invalid_result")
    return _result(args, {"apfu": "atoms_per_formula_unit", "input_total": "wt_percent", "oxygen_basis": "atoms"},
                   ion_labels=[str(x) for x in apfu.index], apfu=apfu.to_numpy(),
                   input_total=float(values.sum()), oxygen_basis=args["oxygen_basis"],
                   iron_redox_inferred=False)


@operation("Geo500MineralReactionBalance")
def mineral_reaction_balance(args):
    np = _np()
    from pymatgen.analysis.reaction_calculator import Reaction
    reactants = [_formula(x) for x in args["reactants"]]
    products = [_formula(x) for x in args["products"]]
    comps = reactants + products
    if len({c.reduced_formula for c in comps}) != len(comps):
        reject("Duplicate or scalar-equivalent reaction formulas are ambiguous.")
    elements = sorted({e.symbol for c in comps for e in c.elements})
    stoich = np.array([[c[e] for c in comps] for e in elements])
    if len(comps) - np.linalg.matrix_rank(stoich) != 1:
        reject("The reaction must have a unique one-dimensional stoichiometric nullspace.")
    reaction = Reaction(reactants, products)
    reaction.normalize_to(reactants[0], factor=1)
    coefficients = np.asarray(reaction.coeffs, dtype=float)
    if (coefficients[:len(reactants)] >= -1e-10).any() or (coefficients[len(reactants):] <= 1e-10).any():
        reject("Upstream balancing swapped or removed requested reaction participants.")
    residual = stoich @ coefficients
    if not np.allclose(residual, 0, rtol=0, atol=1e-8):
        reject("Balanced reaction failed elemental conservation.", "invalid_result")
    return _result(args, {"coefficients": "mol_per_mol_first_reactant", "element_residuals": "mol_atoms"},
                   formulas=args["reactants"] + args["products"], coefficients=coefficients,
                   elements=elements, element_residuals=residual)


@operation("Geo500MineralPhaseHull")
def mineral_phase_hull(args):
    np = _np()
    from pymatgen.analysis.phase_diagram import PDEntry, PhaseDiagram
    rows = args["entries"]
    if len({x["id"] for x in rows}) != len(rows):
        reject("Phase identifiers must be unique.")
    entries = [PDEntry(_formula(r["formula"]), r["energy_ev_per_formula"], name=r["id"]) for r in rows]
    if len({e for row in entries for e in row.composition.elements}) > 4:
        reject("At most four chemical elements are supported.", "resource_limit")
    targets = args["target_ids"]
    index = {r["id"]: i for i, r in enumerate(rows)}
    if any(x not in index for x in targets) or len(set(targets)) != len(targets):
        reject("Target phases must be distinct input identifiers.")
    diagram = PhaseDiagram(entries)
    results = []
    for name in targets:
        decomposition, above = diagram.get_decomp_and_e_above_hull(entries[index[name]])
        parts = [{"phase_id": e.name, "atomic_fraction": float(w)} for e, w in decomposition.items()]
        if float(above) < -1e-7 or abs(sum(p["atomic_fraction"] for p in parts) - 1) > 1e-7:
            reject("Invalid convex-hull decomposition.", "invalid_result")
        results.append({"phase_id": name, "energy_above_hull_ev_per_atom": float(above),
                        "decomposition": parts})
    return _result(args, {"energy_above_hull_ev_per_atom": "eV/atom", "atomic_fraction": "1"},
                   results=results, energy_reference=args["energy_reference"],
                   stable_phase_ids=sorted(e.name for e in diagram.stable_entries))


@operation("Geo500CrystalCoordination")
def crystal_coordination(args):
    np = _np()
    from pymatgen.core.local_env import CrystalNN
    structure = _structure(args["structure"])
    if len(set(args["site_indices"])) != len(args["site_indices"]):
        reject("Site indices must be unique.")
    nn = CrystalNN(weighted_cn=False, cation_anion=False, distance_cutoffs=None,
                   x_diff_weight=0, porous_adjustment=False, search_cutoff=7)
    rows = []
    for i in args["site_indices"]:
        if i >= len(structure):
            reject("Coordination site index is outside the structure.")
        neighbors = nn.get_nn_info(structure, i)
        if not neighbors or len(neighbors) > 128:
            reject("Unsupported coordination environment.", "invalid_result")
        rows.append({"site_index": i, "coordination_number": len(neighbors),
                     "neighbors": [{"site_index": int(n["site_index"]),
                                    "image": [int(k) for k in n["image"]],
                                    "distance_angstrom": float(np.linalg.norm(n["site"].coords - structure[i].coords))}
                                   for n in neighbors]})
    return _result(args, {"coordination_number": "1", "distance_angstrom": "angstrom"},
                   sites=rows, interpretation="Geometric CrystalNN neighbors; not inferred chemical bond orders.")


@operation("Geo500BondValenceOxidation")
def bond_valence_oxidation(args):
    np = _np()
    from pymatgen.core.bond_valence import BVAnalyzer
    structure = _structure(args["structure"])
    valences = np.asarray(BVAnalyzer(symm_tol=0, max_radius=4, max_permutations=10000,
                                   distance_scale_factor=1.0).get_valences(structure), dtype=float)
    if valences.shape != (len(structure),) or abs(float(valences.sum())) > 1e-6:
        reject("Bond-valence assignment did not yield a neutral ordered cell.", "invalid_result")
    return _result(args, {"inferred_valences": "elementary_charge", "cell_charge": "elementary_charge"},
                   inferred_valences=valences, cell_charge=float(valences.sum()),
                   measured_redox=False, interpretation="Model-inferred oxidation states, not measured iron speciation.")


@operation("Geo500CrystalStructureEquivalence")
def crystal_structure_equivalence(args):
    _np()
    from pymatgen.core.structure_matcher import StructureMatcher
    left, right = _structure(args["left_structure"]), _structure(args["right_structure"])
    matcher = StructureMatcher(ltol=0.1, stol=0.1, angle_tol=2,
                               primitive_cell=False, scale=False, attempt_supercell=False)
    rms = matcher.get_rms_dist(left, right)
    return _result(args, {"rms_displacement": "normalized_free_length", "maximum_displacement": "normalized_free_length"},
                   equivalent=rms is not None, rms_displacement=None if rms is None else float(rms[0]),
                   maximum_displacement=None if rms is None else float(rms[1]),
                   scale_allowed=False, supercell_search=False)


@operation("Geo500WulffCrystalHabit")
def wulff_crystal_habit(args):
    np = _np()
    from pymatgen.core import Lattice
    from pymatgen.analysis.wulff import WulffShape
    lattice = _array(args["lattice_angstrom"], shape=(3, 3))
    if float(np.linalg.det(lattice)) <= 0.01 or np.linalg.cond(lattice) > 1e4:
        reject("A right-handed well-conditioned conventional lattice is required.")
    hkls = [_miller(x) for x in args["miller_indices"]]
    if len(hkls) != len(args["surface_energies_j_m2"]) or len(set(hkls)) != len(hkls):
        reject("Each distinct Miller family needs one positive surface energy.")
    shape = WulffShape(Lattice(lattice), hkls, args["surface_energies_j_m2"])
    fractions = [{"hkl": list(h), "area_fraction": float(v)} for h, v in shape.area_fraction_dict.items()]
    if abs(sum(x["area_fraction"] for x in fractions) - 1) > 1e-7:
        reject("Wulff facet fractions do not sum to one.", "invalid_result")
    return _result(args, {"area_fraction": "1", "shape_factor": "1", "weighted_surface_energy": "J/m2"},
                   facets=fractions, shape_factor=float(shape.shape_factor),
                   weighted_surface_energy=float(shape.weighted_surface_energy),
                   absolute_crystal_size_inferred=False)


@operation("Geo500PeriodicIonicLatticeEnergy")
def ionic_lattice_energy(args):
    np = _np()
    from pymatgen.core.ewald import EwaldSummation
    structure = _structure(args["structure"])
    charges = _array(args["site_charges_e"], shape=(len(structure),), lower=-8, upper=8)
    if abs(float(charges.sum())) > 1e-10 or not (np.abs(charges) > 0).any():
        reject("An explicitly charged, exactly neutral periodic cell is required.")
    structure.add_oxidation_state_by_site(charges.tolist())
    total = float(EwaldSummation(structure, acc_factor=8).total_energy)
    return _result(args, {"total_energy_ev": "eV/cell", "energy_per_atom_ev": "eV/atom", "cell_charge": "elementary_charge"},
                   total_energy_ev=total, energy_per_atom_ev=total / len(structure),
                   cell_charge=float(charges.sum()), interpretation="3D periodic point-charge Coulomb energy only.")


@operation("Geo500CoherentMineralInterfaceMatch")
def coherent_interface_match(args):
    np = _np()
    from pymatgen.analysis.interfaces.zsl import ZSLGenerator
    film = _array(args["film_vectors_angstrom"], shape=(2, 3))
    substrate = _array(args["substrate_vectors_angstrom"], shape=(2, 3))
    areas = [float(np.linalg.norm(np.cross(*v))) for v in (film, substrate)]
    if min(areas) < 1 or args["max_area_angstrom2"] / min(areas) > 25:
        reject("Degenerate lattices or a superlattice multiplier above 25 are not supported.", "resource_limit")
    generator = ZSLGenerator(max_area=args["max_area_angstrom2"],
                             max_area_ratio_tol=0.05, max_length_tol=0.03, max_angle_tol=0.01)
    match = next(generator(film, substrate, lowest=True), None)
    if match is None:
        return _result(args, {"match_area": "angstrom2", "transformation": "1"},
                       found=False, match_area=None, transformation=None,
                       film_superlattice=None, substrate_superlattice=None)
    return _result(args, {"match_area": "angstrom2", "transformation": "1"},
                   found=True, match_area=float(match.match_area),
                   transformation=match.match_transformation, film_superlattice=match.film_sl_vectors,
                   substrate_superlattice=match.substrate_sl_vectors)


@operation("Geo500MineralSurfaceTerminations")
def mineral_surface_terminations(args):
    _np()
    from pymatgen.core.surface import SlabGenerator
    structure = _structure(args["structure"])
    if len(structure) > 32:
        reject("Slab input is limited to 32 atomic sites.", "resource_limit")
    slabber = SlabGenerator(structure, _miller(args["miller_index"]),
                            args["minimum_slab_angstrom"], args["minimum_vacuum_angstrom"],
                            lll_reduce=False, center_slab=True, in_unit_planes=False,
                            primitive=False, max_normal_search=3)
    slabs = slabber.get_slabs(symmetrize=False, repair=False)
    if not slabs or len(slabs) > 64 or sum(len(s) for s in slabs) > 8192:
        reject("Slab result outside the declared atom/termination budget.", "resource_limit")
    rows = [{"shift_fraction": float(s.shift), "surface_area_angstrom2": float(s.surface_area),
             "lattice_angstrom": s.lattice.matrix, "species": [x.specie.symbol for x in s],
             "fractional_coords": s.frac_coords} for s in slabs]
    return _result(args, {"shift_fraction": "1", "surface_area_angstrom2": "angstrom2",
                          "lattice_angstrom": "angstrom", "fractional_coords": "1"},
                   terminations=rows, atomic_repair_applied=False, surface_energy_calculated=False)


@operation("Geo500REEOrthogonalShape")
def ree_orthogonal_shape(args):
    np = _np()
    import pandas as pd
    from pyrolite.util.lambdas import calc_lambdas
    values = _array(args["ree_ppm"], ndim=2, lower=1e-12)
    reference = _array(args["reference_ppm"], shape=(13,), lower=1e-12)
    if values.shape[1] != 13:
        reject("Provide La..Lu excluding Pm and Eu in the fixed documented order.")
    frame = pd.DataFrame(np.log(values / reference), columns=_REE)
    result = calc_lambdas(frame, params=None, degree=4, exclude=[], anomalies=[],
                          fit_tetrads=False, algorithm="ONeill", add_uncertainties=False, add_X2=False)
    if result.shape != (len(values), 4):
        reject("Unexpected orthogonal polynomial coefficient shape.", "invalid_result")
    return _result(args, {"lambda_coefficients": "ONeill2016_orthogonal_log_ratio_basis"},
                   coefficient_labels=["lambda0", "lambda1", "lambda2", "lambda3"],
                   lambda_coefficients=result.to_numpy(), element_order=_REE,
                   reference_source=args["reference_source"])


@operation("Geo500VolcanicTASClass")
def volcanic_tas_class(args):
    np = _np()
    from pyrolite.util.classification import TAS, _read_poly
    from matplotlib.patches import Polygon
    values = _array(args["anhydrous_sio2_na2o_k2o_wt_percent"], ndim=2, lower=0, upper=100)
    if values.shape[1] != 3 or (values.sum(axis=1) > 100).any():
        reject("Each anhydrous composition needs SiO2, Na2O, K2O; their sum cannot exceed 100 wt%.")
    model = TAS()
    xy = np.column_stack((values[:, 0], values[:, 1] + values[:, 2]))
    predictions = model.predict(xy, data_scale=100).tolist()
    classes = []
    for row, code in zip(xy, predictions):
        inside, touching = [], False
        for key, config in model.fields.items():
            if not config["poly"]:
                continue
            polygon = np.asarray(_read_poly(config["poly"]), dtype=float)
            path = Polygon(polygon, closed=True).get_path()
            if path.contains_point(row, radius=1e-6) != path.contains_point(row, radius=-1e-6):
                touching = True
            if path.contains_point(row, radius=-1e-6):
                inside.append(key)
        if touching or len(inside) != 1 or code == "none":
            classes.append({"class_id": None, "status": "boundary_or_outside"})
        else:
            classes.append({"class_id": str(code), "status": "classified"})
    return _result(args, {"anhydrous_sio2_na2o_k2o_wt_percent": "wt_percent"},
                   classifications=classes, model="Middlemost1994", anhydrous_basis_confirmed=True)


@operation("Geo500MineralNeutronContrast")
def mineral_neutron_contrast(args):
    _np()
    import re
    from periodictable.nsf import neutron_scattering
    if not re.fullmatch(r"(?:[A-Z][a-z]?[0-9]*(?:\.[0-9]+)?){1,16}", args["formula"]):
        reject("Only bounded natural-isotope elemental formulas are supported.")
    sld, cross_sections, depth = neutron_scattering(
        args["formula"], density=args["density_g_cm3"], wavelength=args["wavelength_angstrom"])
    if sld is None or cross_sections is None or depth is None:
        reject("Upstream neutron tables do not cover this composition.", "unsupported_conditions")
    return _result(args, {"sld": "1e-6/angstrom2", "macroscopic_cross_sections": "1/cm", "penetration_depth": "cm"},
                   sld=sld, sld_order=["real", "minus_imaginary", "incoherent"],
                   macroscopic_cross_sections=cross_sections,
                   cross_section_order=["coherent", "absorption", "incoherent"],
                   penetration_depth=float(depth))


@operation("Geo500PoreChordDistribution")
def pore_chord_distribution(args):
    np = _np()
    from porespy.filters import apply_chords
    from porespy.metrics import chord_length_distribution
    pore = _volume(args)
    if args["axis"] >= pore.ndim:
        reject("Chord direction is outside the geometry axes.")
    edges = _edges(args["bin_edges_m"])
    chords = apply_chords(pore, spacing=1, axis=args["axis"], trim_edges=True, label=True)
    labels, counts = np.unique(chords[chords > 0], return_counts=True)
    if len(labels) == 0:
        reject("No complete uncensored pore chords remain.", "empty_input")
    lengths = counts * args["voxel_size_m"]
    if edges[0] > lengths.min() or edges[-1] < lengths.max():
        reject("Bins must include every complete chord; no silent histogram truncation.")
    distribution = chord_length_distribution(chords, bins=edges, log=False,
                                              voxel_size=args["voxel_size_m"], normalization="count")
    return _result(args, {"bin_centers_m": "m", "relative_frequency": "1", "chord_lengths_m": "m"},
                   bin_centers_m=distribution.bin_centers, relative_frequency=distribution.relfreq,
                   chord_lengths_m=lengths, chord_count=len(labels), edge_censoring=True)


@operation("Geo500PoreBodyRadiusDistribution")
def pore_body_radius_distribution(args):
    np = _np()
    from porespy.filters import local_thickness
    from porespy.metrics import pore_size_distribution
    pore = _volume(args)
    # A solid collar makes the exterior convention explicit rather than open.
    for axis in range(pore.ndim):
        if np.take(pore, [0, pore.shape[axis] - 1], axis=axis).any():
            reject("Radius analysis requires a solid outer collar; unbounded exterior pores are unsupported.")
    edges = _edges(args["bin_edges_m"])
    radii = local_thickness(pore, method="bf", smooth=True, sizes=None)
    physical = radii[pore] * args["voxel_size_m"]
    if not np.isfinite(physical).all() or (physical <= 0).any():
        reject("Upstream did not resolve every pore voxel radius.", "invalid_result")
    if edges[0] > physical.min() or edges[-1] < physical.max():
        reject("Bins must contain every resolved pore radius.")
    dist = pore_size_distribution(radii, bins=edges, log=False, voxel_size=args["voxel_size_m"])
    return _result(args, {"bin_centers_m": "m", "pore_volume_fraction": "1", "radius_field_m": "m"},
                   bin_centers_m=dist.bin_centers, pore_volume_fraction=dist.satn,
                   radius_field_m=(radii * args["voxel_size_m"]).ravel(order="C"),
                   shape=list(pore.shape), radius_convention="integer sphere radii; smooth=True; not diameter")


@operation("Geo500QuasistaticCapillaryDrainage")
def quasistatic_capillary_drainage(args):
    np = _np()
    from porespy.simulations import drainage
    pore = _volume(args)
    n = pore.size
    inlet = np.asarray(args["inlet_mask"], dtype=bool)
    outlet = np.asarray(args["outlet_mask"], dtype=bool)
    if inlet.shape != (n,) or outlet.shape != (n,):
        reject("Inlet and outlet masks must match the pore geometry.")
    inlet, outlet = inlet.reshape(pore.shape), outlet.reshape(pore.shape)
    if not inlet.any() or not outlet.any() or (inlet & outlet).any() or ((inlet | outlet) & ~pore).any():
        reject("Nonempty disjoint inlet/outlet masks must be subsets of the pore space.")
    pc = _array(args["entry_pressure_pa"], shape=(n,), lower=0).reshape(pore.shape)
    if (pc[pore] <= 0).any():
        reject("Every pore voxel needs a positive physical entry pressure.")
    steps = _array(args["pressure_steps_pa"], ndim=1, lower=0)
    if not (np.diff(steps) > 0).all():
        reject("Applied pressures must be strictly increasing.")
    results = drainage(pore, pc=pc, inlets=inlet, outlets=outlet, residual=None,
                       steps=steps, conn="min", min_size=0, smooth=True)
    invaded_at = np.asarray(results.im_pc)
    if invaded_at.shape != pore.shape or np.isnan(invaded_at[pore]).any() or np.isneginf(invaded_at[pore]).any():
        reject("Invalid invasion-pressure map.", "invalid_result")
    mask = pore & np.isfinite(invaded_at)
    # Infinity means uninvaded in this upstream API; preserve it as explicit null.
    pressures = [float(x) if active else None for x, active in zip(invaded_at.ravel(), mask.ravel())]
    saturation = [float(np.count_nonzero(mask & (invaded_at <= step)) / np.count_nonzero(pore)) for step in steps]
    return _result(args, {"invasion_pressure_pa": "Pa", "applied_pressure_pa": "Pa", "nonwetting_saturation": "1"},
                   shape=list(pore.shape), invasion_pressure_pa=pressures,
                   invaded_mask=mask.ravel().tolist(), applied_pressure_pa=steps,
                   nonwetting_saturation=saturation, trapping_enabled=True,
                   null_convention="null for solid or uninvaded; distinguish using pore_mask and invaded_mask")


@operation("Geo500MineralEhPHStability")
def mineral_eh_ph_stability(args):
    np = _np()
    from pymatgen.analysis.phase_diagram import PDEntry
    from pymatgen.analysis.pourbaix_diagram import PourbaixEntry, PourbaixDiagram, IonEntry
    from pymatgen.core.ion import Ion
    rows = args["entries"]
    if any(not (-2 <= x[0] <= 16 and -3 <= x[1] <= 3) for x in args["ph_eh_points"]):
        reject("Supported pH is -2..16 and Eh is -3..3 V versus SHE.")
    if len({x["id"] for x in rows}) != len(rows):
        reject("Pourbaix entries need distinct identifiers.")
    metal = args["element"]
    if metal not in _ELEMENTS or metal in ("H", "O"):
        reject("One explicit non-H/O chemical element is required.")
    entries = []
    for r in rows:
        comp = _formula(r["formula"])
        if {e.symbol for e in comp.elements} - {"H", "O", metal} or comp[metal] <= 0:
            reject("Each entry must belong to the same single-metal H/O system.")
        if r["phase"] == "ion":
            if not math.isclose(r["concentration_mol_l"], args["metal_concentration_mol_l"] / comp[metal], rel_tol=1e-10):
                reject("Ion concentration must equal metal concentration divided by metal stoichiometry.")
            raw = IonEntry(Ion(comp, r["charge_e"]), r["formation_energy_ev_per_formula"])
        else:
            if r["charge_e"] != 0 or r["concentration_mol_l"] != 1:
                reject("Solid entries require zero charge and unit activity marker.")
            raw = PDEntry(comp, r["formation_energy_ev_per_formula"])
        entries.append(PourbaixEntry(raw, entry_id=r["id"], concentration=r["concentration_mol_l"]))
    diagram = PourbaixDiagram(entries, comp_dict={metal: 1},
                               conc_dict={metal: args["metal_concentration_mol_l"]},
                               filter_solids=False, nproc=1)
    target = next((e for e in entries if e.entry_id == args["target_id"]), None)
    if target is None:
        reject("Target entry is not in the supplied thermodynamic data.")
    values = [float(diagram.get_decomposition_energy(target, x[0], x[1])) for x in args["ph_eh_points"]]
    if min(values) < -1e-6:
        reject("Target lies below the constructed Pourbaix hull.", "invalid_result")
    return _result(args, {"decomposition_energy_ev_per_atom": "eV/atom", "pH": "1", "Eh": "V_vs_SHE"},
                   target_id=args["target_id"], decomposition_energy_ev_per_atom=values,
                   ph_eh_points=args["ph_eh_points"], temperature_convention="upstream fixed room-temperature PREFAC",
                   energy_reference=args["energy_reference"])


@operation("Geo500SpatialCellDeclustering")
def spatial_cell_declustering(args):
    np = _np()
    import pandas as pd
    # A source archive pin is not falsely labelled as PyPI 0.0.79.
    direct = metadata.distribution("geostatspy").read_text("direct_url.json")
    if not direct:
        reject("GeoStatsPy must be installed from the reviewed immutable source archive.", "missing_dependency")
    info = json.loads(direct)
    expected = "https://github.com/GeostatsGuy/GeostatsPy/archive/45b2032a1e3f05de6cd0cb7f32ed43203399dbfa.zip"
    if info.get("url") != expected:
        reject("GeoStatsPy source identity does not match the reviewed archive.", "incompatible_dependency")
    from geostatspy.geostats import declus
    coords = _array(args["coordinates_m"], ndim=2)
    values = _array(args["values"], shape=(len(coords),))
    if coords.shape[1] != 2 or len({tuple(x) for x in coords.tolist()}) != len(coords):
        reject("Distinct projected 2D sample coordinates are required.")
    cmin, cmax = args["cell_size_min_m"], args["cell_size_max_m"]
    if cmin > cmax:
        reject("Cell-size limits are reversed.")
    extents = np.ptp(coords, axis=0)
    allocation = math.prod(int((x + cmin + 0.01) / cmin) + 1 for x in extents)
    if allocation > 100000:
        reject("Declustering grid exceeds 100000 cells.", "resource_limit")
    frame = pd.DataFrame({"x": coords[:, 0], "y": coords[:, 1], "v": values})
    log = _BoundedLog()
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        weights, sizes, means = declus(frame, "x", "y", "v", 1, args["origin_offsets"],
                                       args["cell_size_steps"], cmin, cmax)
    weights = _array(weights, shape=(len(coords),), lower=0)
    weights = weights / weights.sum()
    return _result(args, {"weights": "1", "declustered_mean": args["value_unit"],
                          "tested_cell_sizes_m": "m", "tested_means": args["value_unit"]},
                   weights=weights, declustered_mean=float(weights @ values),
                   tested_cell_sizes_m=sizes, tested_means=means,
                   selection_rule="minimum declustered mean, including naive case; code iminmax=1, contrary to docstring")


@operation("GeoSlopeLimitEquilibrium")
def slope_limit_equilibrium(args):
    np = _np()
    from pyslope import Slope, Material, Udl, LineLoad
    layers = args["materials"]
    depths = [x["depth_to_bottom_m"] for x in layers]
    if any(b <= a for a, b in zip(depths, depths[1:])) or depths[-1] < args["height_m"]:
        reject("Layer-bottom depths must increase and extend beneath the slope toe.")
    slope = Slope(height=args["height_m"], angle=args["angle_degrees"], length=None)
    slope.set_materials(*[Material(unit_weight=x["unit_weight_kn_m3"],
                                   friction_angle=x["friction_degrees"], cohesion=x["cohesion_kpa"],
                                   depth_to_bottom=x["depth_to_bottom_m"]) for x in layers])
    if args["water_depth_m"] is not None:
        slope.set_water_table(args["water_depth_m"])
    if args["uniform_loads"]:
        slope.set_udls(*[Udl(magnitude=x["magnitude_kpa"], offset=x["offset_m"], length=x["length_m"])
                         for x in args["uniform_loads"]])
    if args["line_loads"]:
        slope.set_lls(*[LineLoad(magnitude=x["magnitude_kn_m"], offset=x["offset_m"])
                        for x in args["line_loads"]])
    top, bottom = slope.get_top_coordinates(), slope.get_bottom_coordinates()
    left = top[0] - args["search_crest_distance_m"]
    right = bottom[0] + args["search_toe_distance_m"]
    if left < 0:
        reject("Requested search extends outside the upstream slope boundary.")
    slope.set_analysis_limits(left, right)
    slope.update_analysis_options(slices=args["slices"], iterations=args["search_iterations"],
                                  tolerance=1e-5, max_iterations=100)
    log = _BoundedLog()
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        slope.analyse_slope()
    if not slope._search:
        reject("No valid circular slip surface converged.", "invalid_result")
    factor = float(slope.get_min_FOS())
    if not math.isfinite(factor) or factor <= 0:
        reject("Invalid factor of safety.", "invalid_result")
    return _result(args, {"factor_of_safety": "1", "critical_circle": "m", "critical_endpoints": "m",
                          "search_limits_m": "m"},
                   factor_of_safety=factor, critical_circle=slope.get_min_FOS_circle(),
                   critical_endpoints=slope.get_min_FOS_end_points(), search_limits_m=[left, right],
                   converged_surface_count=len(slope._search),
                   method="Bishop simplified, searched circular surfaces; not engineering certification")


@operation("GeoMantleMeltingPath")
def mantle_melting_path(args):
    np = _np()
    import pyMelt
    from pyMelt.lithologies.katz import lherzolite
    from pyMelt.lithologies.shorttle import harzburgite
    proportions = _array(args["lithology_mass_fractions"], shape=(2,), lower=0, upper=1)
    if abs(float(proportions.sum()) - 1) > 1e-10 or proportions[0] <= 0:
        reject("Explicit mass fractions must sum to one and contain fusible lherzolite.")
    if args["start_pressure_gpa"] <= args["end_pressure_gpa"]:
        reject("Decompression requires decreasing pressure.")
    mantle = pyMelt.mantle([lherzolite(), harzburgite()], proportions.tolist(),
                          names=["Katz2003_lherzolite", "Shorttle2014_harzburgite"])
    log = _BoundedLog()
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        column = mantle.adiabaticMelt(Tp=args["potential_temperature_degc"],
                                     Pstart=args["start_pressure_gpa"], Pend=args["end_pressure_gpa"],
                                     steps=args["steps"], ReportSSS=False, adjust_pressure=False,
                                     prevent_freezing=False, warn_prevent_freezing=False)
    pressure = _array(column.P.to_numpy(), shape=(args["steps"],))
    temperature = _array(column.T.to_numpy(), shape=pressure.shape)
    fractions = column.calculation_results[["Katz2003_lherzolite", "Shorttle2014_harzburgite"]].to_numpy()
    fractions = _array(fractions, shape=(len(pressure), 2), lower=-1e-10, upper=1 + 1e-10)
    if not (np.diff(pressure) < 0).all() or not np.allclose(column.F, fractions @ proportions, atol=1e-10):
        reject("Invalid decompression path or mass-weighted melt fraction.", "invalid_result")
    return _result(args, {"pressure_gpa": "GPa", "temperature_degc": "degC", "melt_fractions": "1",
                          "bulk_melt_fraction": "1"},
                   pressure_gpa=pressure, temperature_degc=temperature, melt_fractions=fractions,
                   bulk_melt_fraction=column.F, lithologies=["Katz2003_lherzolite", "Shorttle2014_harzburgite"],
                   model="anhydrous equilibrium decompression; freezing allowed; no extraction or ore prediction")


@operation("GeoImplicitStructuralModel")
def implicit_structural_model(args):
    np = _np()
    import gempy as gp
    from gempy.core.data.gempy_engine_config import GemPyEngineConfig
    from gempy_engine.config import AvailableBackends
    bounds = _array(args["extent_m"], shape=(6,))
    lo, hi = bounds[::2], bounds[1::2]
    resolution = args["resolution"]
    if (hi <= lo).any() or math.prod(resolution) > 32768:
        reject("Positive 3D extent and at most 32768 cells are required.", "resource_limit")
    names = args["surface_names_youngest_first"]
    if len(set(names)) != len(names):
        reject("Surface names must be unique.")
    points = _array(args["surface_points_xyz_m"], ndim=2)
    orientation = _array(args["orientation_xyz_m"], ndim=2)
    normals = _array(args["orientation_normals"], shape=(len(orientation), 3))
    pi, oi = args["point_surface_indices"], args["orientation_surface_indices"]
    if points.shape[1] != 3 or orientation.shape[1] != 3 or len(pi) != len(points) or len(oi) != len(orientation):
        reject("Every observation needs an aligned surface index and XYZ coordinates.")
    if any(i >= len(names) for i in pi + oi):
        reject("Observation references an undefined surface.")
    if ((points < lo) | (points > hi)).any() or ((orientation < lo) | (orientation > hi)).any():
        reject("All constraints must lie within the declared local Cartesian extent.")
    if not np.allclose(np.linalg.norm(normals, axis=1), 1, atol=1e-6, rtol=0):
        reject("Orientation normals must be explicit unit vectors; no silent normalization.")
    for i in range(len(names)):
        subset = points[np.asarray(pi) == i]
        if len(subset) < 3 or np.linalg.matrix_rank(subset - subset.mean(axis=0)) < 2 or i not in oi:
            reject("Every surface needs three noncollinear points and an orientation.")
    if len({tuple(x) for x in points.tolist()}) != len(points):
        reject("Duplicate surface constraints are not accepted.")
    mapping = {name: i for i, name in enumerate(names)}
    sp = gp.data.SurfacePointsTable.from_arrays(
        x=points[:, 0], y=points[:, 1], z=points[:, 2], names=[names[i] for i in pi],
        nugget=np.full(len(points), 1e-6), name_id_map=mapping)
    orient = gp.data.OrientationsTable.from_arrays(
        x=orientation[:, 0], y=orientation[:, 1], z=orientation[:, 2],
        G_x=normals[:, 0], G_y=normals[:, 1], G_z=normals[:, 2],
        names=[names[i] for i in oi], nugget=np.full(len(orientation), 0.01), name_id_map=mapping)
    frame = gp.data.StructuralFrame.from_data_tables(sp, orient)
    log = _BoundedLog()
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        model = gp.create_geomodel(project_name="bounded_expansion501", extent=bounds.tolist(),
                                   resolution=resolution, refinement=1, structural_frame=frame)
        gp.map_stack_to_surfaces(gempy_model=model, mapping_object={"stratigraphy": names})
        model.interpolation_options.mesh_extraction = False
        solution = gp.compute_model(model, engine_config=GemPyEngineConfig(
            backend=AvailableBackends.numpy, use_gpu=False, dtype="float64", compute_grads=False),
            validate_serialization=False)
    lithology = _array(solution.raw_arrays.lith_block, ndim=1)
    scalar = _array(solution.raw_arrays.scalar_field_matrix, ndim=2)
    if lithology.size != math.prod(resolution) or scalar.shape[1] != lithology.size:
        reject("Engine result does not match the requested dense grid.", "invalid_result")
    if not np.allclose(lithology, np.rint(lithology), atol=1e-8):
        reject("Engine lithology labels are not integral.", "invalid_result")
    return _result(args, {"lithology_labels": "category_id", "scalar_fields": "engine_scalar",
                          "extent_m": "m", "grid_coordinates_m": "m"},
                   lithology_labels=np.rint(lithology).astype(int), scalar_fields=scalar,
                   grid_coordinates_m=model.grid.regular_grid.values,
                   resolution=resolution, extent_m=bounds, coordinate_reference=args["coordinate_reference"],
                   surface_names_youngest_first=names,
                   scope="one stratigraphic stack; no faults, unconformity editing, meshes or geophysics")

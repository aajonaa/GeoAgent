"""Independent, CPU-only acceptance source for the 26 expansion501 geology adapters.

No kernel is run on import. Runtime cases require the parent-staged catalog and
an explicitly bound, private Linux CPU revision. Missing dependencies are errors,
never skips or successful scientific-negative cases. All fixtures are synthetic.
This suite does not install dependencies, stage catalogs, launch SSH, or deploy.
"""
from __future__ import annotations

import ast
import copy
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import random
import re
import sys
import unittest
from fractions import Fraction
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
GROUP = ROOT / "catalog/source_delivery/expansion501-20261026/groups/geology"
MODULE = "geological_agent.geology.expansion501_geology"
MODULE_FILE = ROOT / "geological_agent/geology/expansion501_geology.py"
CPU_ID = "expansion501-geology-cpu-v1"

ENTRYPOINTS = {
    "Geo500CrystalSpaceGroupAudit": "crystal_space_group",
    "Geo500IrreducibleReciprocalMesh": "irreducible_reciprocal_mesh",
    "Geo500PowderXRDPattern": "powder_xrd_pattern",
    "Geo500MineralOxygenBasisFormula": "mineral_oxygen_basis_formula",
    "Geo500MineralReactionBalance": "mineral_reaction_balance",
    "Geo500MineralPhaseHull": "mineral_phase_hull",
    "Geo500CrystalCoordination": "crystal_coordination",
    "Geo500BondValenceOxidation": "bond_valence_oxidation",
    "Geo500CrystalStructureEquivalence": "crystal_structure_equivalence",
    "Geo500WulffCrystalHabit": "wulff_crystal_habit",
    "Geo500PeriodicIonicLatticeEnergy": "ionic_lattice_energy",
    "Geo500CoherentMineralInterfaceMatch": "coherent_interface_match",
    "Geo500MineralSurfaceTerminations": "mineral_surface_terminations",
    "Geo500REEOrthogonalShape": "ree_orthogonal_shape",
    "Geo500VolcanicTASClass": "volcanic_tas_class",
    "Geo500MineralNeutronContrast": "mineral_neutron_contrast",
    "Geo500PoreChordDistribution": "pore_chord_distribution",
    "Geo500PoreBodyRadiusDistribution": "pore_body_radius_distribution",
    "Geo500QuasistaticCapillaryDrainage": "quasistatic_capillary_drainage",
    "Geo500MineralEhPHStability": "mineral_eh_ph_stability",
    "Geo500SpatialCellDeclustering": "spatial_cell_declustering",
    "GeoSlopeLimitEquilibrium": "slope_limit_equilibrium",
    "GeoMantleMeltingPath": "mantle_melting_path",
    "GeoImplicitStructuralModel": "implicit_structural_model",
    "GeoConditionedResourceEnsemble": "conditioned_resource_ensemble",
    "Geo500PoreDiffusionTortuosity": "pore_diffusion_tortuosity",
}
BLOCKED_IDS = {
    "Geo50026ConstrainedChemicalEquilibrium",
    "Geo50026MineralReactionKinetics",
    "Geo50026ReactiveColumnTransport",
    "GeoGeobodyTopology",
    "GeoCpxMeltThermobarometry",
}
BASE_PINS = {
    "numpy": "2.1.3", "scipy": "1.15.3", "pandas": "2.3.0",
    "matplotlib": "3.10.7", "jsonschema": "4.25.1",
}
PRIVATE_BASE_PINS = {
    "Geo500PoreDiffusionTortuosity": {**BASE_PINS, "scipy": "1.16.2", "pandas": "2.3.2"},
}
SOURCE_COMMITS = {
    "https://github.com/spglib/spglib":
        "3ebd8ac3318793932baeee90b44f453a7c35b5b4",
    "https://github.com/materialsproject/pymatgen-core":
        "cddebfb21ed5acaee3987948b6704a2790d4e056",
    "https://github.com/materialsproject/pymatgen":
        "e3fdb6d4bb2a3bc1622f4c133e088d660f0c3c26",
    "https://github.com/morganjwilliams/pyrolite":
        "ab651b448ecd2ce1bc22d752b80a977a1f4dd1ca",
    "https://github.com/python-periodictable/periodictable":
        "83b643f4ca4c7d8cf5202c13e32921b572da9896",
    "https://github.com/PMEAL/porespy":
        "916fdc135bfb08d84b8d9173d6de9174ff217e5d",
    "https://github.com/GeostatsGuy/GeostatsPy":
        "45b2032a1e3f05de6cd0cb7f32ed43203399dbfa",
    "https://github.com/JesseBonanno/PySlope":
        "b50f46ac342b569e251890239560ec311c8015cb",
    "https://github.com/simonwmatthews/pyMelt":
        "53246591d796275b4d3c7e6102897a886b76d63a",
    "https://github.com/gempy-project/gempy":
        "4bc16d39edbba98804a43d4ff0a62262140cbffe",
    "https://github.com/scikit-learn/scikit-learn":
        "25dee604bae18205b01548348388baf7a1cdfe0e",
}
PROFILES = {
    "chemistry": {
        "Geo500MineralOxygenBasisFormula", "Geo500REEOrthogonalShape",
        "Geo500VolcanicTASClass", "Geo500MineralNeutronContrast",
    },
    "pores": {
        "Geo500PoreChordDistribution", "Geo500PoreBodyRadiusDistribution",
        "Geo500QuasistaticCapillaryDrainage",
    },
    "geostatspy": {"Geo500SpatialCellDeclustering"},
    "slope": {"GeoSlopeLimitEquilibrium"},
    "mantle": {"GeoMantleMeltingPath"},
    "gempy": {"GeoImplicitStructuralModel"},
    "conditional": {"GeoConditionedResourceEnsemble"},
    "tortuosity": {"Geo500PoreDiffusionTortuosity"},
}
PROFILES["crystals"] = set(ENTRYPOINTS) - set().union(*PROFILES.values())
PROFILES["all"] = set(ENTRYPOINTS)
PROFILE = os.environ.get("GEOAGENT_GEOLOGY_ACCEPTANCE_PROFILE", "all")
if PROFILE not in PROFILES:
    raise RuntimeError("Unknown fixed geology acceptance profile: " + PROFILE)
SELECTED_IDS = sorted(PROFILES[PROFILE])


def _read_json(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def _beneath(path, root):
    return Path(path).resolve().is_relative_to(root.resolve())


def _require_private_cpu():
    """Refuse scientific execution in the main environment or an unknown host."""
    if sys.platform != "linux" or sys.version_info[:2] != (3, 12):
        raise RuntimeError("Acceptance requires the approved private Linux Python 3.12 worker.")
    value = os.environ.get("GEOAGENT_GEOLOGY_ACCEPTANCE_ROOT", "")
    if not re.fullmatch(r"/data/wangjian/expansion501-20261026/geology-r[1-9][0-9]*", value):
        raise RuntimeError("A fresh, explicit geology-rN revision must be bound by the parent.")
    revision = Path(value)
    if not revision.is_dir() or revision.is_symlink():
        raise RuntimeError("Acceptance revision must exist as a real private directory.")
    if sys.prefix == sys.base_prefix or not _beneath(sys.prefix, revision):
        raise RuntimeError("Refusing a base interpreter or a venv outside this revision.")
    if not _beneath(ROOT, revision):
        raise RuntimeError("The source delta must be staged within this private revision.")
    required = {
        "GEOAGENT_EXPANSION501_GEOLOGY_CPU": CPU_ID,
        "CUDA_VISIBLE_DEVICES": "",
        "NVIDIA_VISIBLE_DEVICES": "void",
        "HIP_VISIBLE_DEVICES": "",
        "ROCR_VISIBLE_DEVICES": "",
        "ZE_AFFINITY_MASK": "",
        "JAX_PLATFORMS": "cpu",
        "JAX_PLATFORM_NAME": "cpu",
        "GEMPY_USE_GPU": "False",
        "GEMPY_GPU_FALLBACK": "False",
        "MPLBACKEND": "Agg",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    for key, expected in required.items():
        if os.environ.get(key) != expected:
            raise RuntimeError("CPU acceptance environment mismatch: " + key)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS"):
        if os.environ.get(key) not in ("1", "2"):
            raise RuntimeError("Explicit one- or two-thread limit required: " + key)
    for key in ("HOME", "XDG_CACHE_HOME", "TMPDIR", "TEMP", "TMP",
                "MPLCONFIGDIR", "NUMBA_CACHE_DIR"):
        path = os.environ.get(key)
        if not path or not Path(path).is_dir() or not _beneath(path, revision):
            raise RuntimeError("Private pre-created HOME/cache/temp path required: " + key)
    return revision


def _first_leaf_path(value, numeric=True, prefix=()):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "data_source":
                continue
            found = _first_leaf_path(child, numeric, prefix + (key,))
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _first_leaf_path(child, numeric, prefix + (index,))
            if found is not None:
                return found
    elif (isinstance(value, (int, float)) and not isinstance(value, bool)) if numeric else isinstance(value, str):
        return prefix
    return None


def _set_path(value, path, replacement):
    current = value
    for part in path[:-1]:
        current = current[part]
    current[path[-1]] = replacement


def _physical_case(tool_id, args):
    """One independently chosen, specific physical-domain violation per tool."""
    x = copy.deepcopy(args)
    if tool_id in ("Geo500CrystalSpaceGroupAudit", "Geo500BondValenceOxidation"):
        x["structure"]["lattice_angstrom"] = [[0, 0, 0]] * 3
    elif tool_id == "Geo500IrreducibleReciprocalMesh":
        x["structure"]["lattice_angstrom"][0][0] *= -1
    elif tool_id == "Geo500PowderXRDPattern":
        x["two_theta_min_degrees"], x["two_theta_max_degrees"] = 80, 10
    elif tool_id == "Geo500MineralOxygenBasisFormula":
        x["oxide_wt_percent"] = [10, 10]
    elif tool_id == "Geo500MineralReactionBalance":
        x["reactants"], x["products"] = ["MgO", "SiO2"], ["CaO"]
    elif tool_id == "Geo500MineralPhaseHull":
        x["entries"][1]["id"] = x["entries"][0]["id"]
    elif tool_id == "Geo500CrystalCoordination":
        x["site_indices"] = [127]
    elif tool_id == "Geo500CrystalStructureEquivalence":
        x["right_structure"]["fractional_coords"][1] = copy.deepcopy(
            x["right_structure"]["fractional_coords"][0])
    elif tool_id == "Geo500WulffCrystalHabit":
        x["miller_indices"][0] = [0, 0, 0]
    elif tool_id == "Geo500PeriodicIonicLatticeEnergy":
        x["site_charges_e"][0] = 2
    elif tool_id == "Geo500CoherentMineralInterfaceMatch":
        x["film_vectors_angstrom"] = [[2, 0, 0], [4, 0, 0]]
    elif tool_id == "Geo500MineralSurfaceTerminations":
        x["miller_index"] = [0, 0, 0]
    elif tool_id == "Geo500REEOrthogonalShape":
        x["reference_ppm"][0] = 0
    elif tool_id == "Geo500VolcanicTASClass":
        x["anhydrous_sio2_na2o_k2o_wt_percent"] = [[95, 5, 5]]
    elif tool_id == "Geo500MineralNeutronContrast":
        x["density_g_cm3"] = -1
    elif tool_id == "Geo500PoreChordDistribution":
        x["axis"] = 2
    elif tool_id == "Geo500PoreBodyRadiusDistribution":
        x["pore_mask"][0] = True
    elif tool_id == "Geo500QuasistaticCapillaryDrainage":
        x["inlet_mask"] = list(x["outlet_mask"])
    elif tool_id == "Geo500MineralEhPHStability":
        x["entries"][1]["concentration_mol_l"] = 0.5
    elif tool_id == "Geo500SpatialCellDeclustering":
        x["coordinates_m"][1] = list(x["coordinates_m"][0])
    elif tool_id == "GeoSlopeLimitEquilibrium":
        x["materials"][-1]["depth_to_bottom_m"] = 1
    elif tool_id == "GeoMantleMeltingPath":
        x["lithology_mass_fractions"] = [0.8, 0.8]
    elif tool_id == "GeoImplicitStructuralModel":
        x["orientation_normals"] = [[0, 0, 2]]
    elif tool_id == "GeoConditionedResourceEnsemble":
        x["observation_coordinates_m"] = [[0, 0, 0], [0, 0, 0]]
        x["observed_values_ppm"] = [12, 12]
    elif tool_id == "Geo500PoreDiffusionTortuosity":
        x["axis"] = 3
    else:
        raise AssertionError("No physical negative defined: " + tool_id)
    code = "resource_limit" if tool_id == "Geo500CoherentMineralInterfaceMatch" else "invalid_arguments"
    return x, code


def _shape_case(tool_id, args):
    x = copy.deepcopy(args)
    if "structure" in x:
        x["structure"]["species"].append("Mg")
    elif "right_structure" in x:
        x["right_structure"]["species"].append("Mg")
    elif tool_id == "Geo500MineralOxygenBasisFormula":
        x["oxide_wt_percent"] = x["oxide_wt_percent"][:-1]
    elif tool_id == "Geo500MineralReactionBalance":
        x["reactants"] = "MgO"
    elif tool_id == "Geo500MineralPhaseHull":
        x["entries"][0]["energy_ev_per_formula"] = [0]
    elif tool_id == "Geo500WulffCrystalHabit":
        x["surface_energies_j_m2"] = x["surface_energies_j_m2"][:-1]
    elif tool_id == "Geo500CoherentMineralInterfaceMatch":
        x["film_vectors_angstrom"] = [[2, 0, 0]]
    elif tool_id == "Geo500REEOrthogonalShape":
        x["reference_ppm"] = x["reference_ppm"][:-1]
    elif tool_id == "Geo500VolcanicTASClass":
        x["anhydrous_sio2_na2o_k2o_wt_percent"] = [[50, 3]]
    elif tool_id == "Geo500MineralNeutronContrast":
        x["formula"] = ["SiO2"]
    elif tool_id in ("Geo500PoreChordDistribution", "Geo500PoreBodyRadiusDistribution"):
        x["shape"][-1] += 1
    elif tool_id == "Geo500QuasistaticCapillaryDrainage":
        x["outlet_mask"] = x["outlet_mask"][:-1]
    elif tool_id == "Geo500MineralEhPHStability":
        x["ph_eh_points"] = [[7]]
    elif tool_id == "Geo500SpatialCellDeclustering":
        x["values"] = x["values"][:-1]
    elif tool_id == "GeoSlopeLimitEquilibrium":
        x["materials"] = x["materials"][0]
    elif tool_id == "GeoMantleMeltingPath":
        x["lithology_mass_fractions"] = [1]
    elif tool_id == "GeoImplicitStructuralModel":
        x["point_surface_indices"] = x["point_surface_indices"][:-1]
    elif tool_id == "GeoConditionedResourceEnsemble":
        x["observed_values_ppm"] = [12, 13]
    elif tool_id == "Geo500PoreDiffusionTortuosity":
        x["pore_mask"] = x["pore_mask"][:-1]
    else:
        raise AssertionError("No shape negative defined: " + tool_id)
    return x


class GeologySourceRegistration(unittest.TestCase):
    """Static schema/source/manifest checks; these are not kernel acceptance."""

    @classmethod
    def setUpClass(cls):
        from jsonschema import Draft202012Validator
        cls.Validator = Draft202012Validator
        cls.catalog = _read_json(GROUP / "catalog-additions.json")
        cls.tools = {t["id"]: t for t in cls.catalog["tools"]}
        cls.examples = _read_json(GROUP / "examples-additions.json")
        cls.statuses = _read_json(GROUP / "adaptation-status.json")["operations"]
        cls.tree = ast.parse(MODULE_FILE.read_text(encoding="utf-8-sig"))
        cls.definitions = {}
        for node in cls.tree.body:
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == "operation":
                        cls.definitions[ast.literal_eval(dec.args[0])] = node

    def test_00_complete_assignment_and_blocked_exclusion(self):
        self.assertEqual(len(self.catalog["tools"]), 26)
        self.assertEqual(set(self.tools), set(ENTRYPOINTS))
        self.assertEqual(set(self.examples), set(ENTRYPOINTS))
        self.assertEqual(len(self.statuses), 31)
        states = {row["id"]: row for row in self.statuses}
        self.assertEqual(len(states), 31)
        self.assertEqual(set(states), set(ENTRYPOINTS) | BLOCKED_IDS)
        self.assertEqual(set(self.definitions), set(ENTRYPOINTS))
        candidates = _read_json(GROUP / "candidate-operations.json")["operations"]
        self.assertEqual(len(candidates), 26)
        self.assertEqual({row["tool_id"] for row in candidates}, set(ENTRYPOINTS))
        for tool_id, row in states.items():
            self.assertTrue(row["reason"].strip())
            if tool_id in BLOCKED_IDS:
                self.assertEqual(row["state"], "blocked")
                self.assertTrue(row["blockers"])
                self.assertNotIn(tool_id, self.tools)
                self.assertNotIn(tool_id, self.definitions)
            else:
                self.assertEqual(row["state"], "source_adapted_unverified")

    def test_01_explicit_delivery_and_skill_status(self):
        paths = _read_json(GROUP / "delivery-files.json")["files"]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertIn("geological_agent/geology/expansion501_geology.py", paths)
        skills = []
        for relative in paths:
            self.assertFalse(Path(relative).is_absolute())
            path = ROOT / relative
            self.assertTrue(_beneath(path, ROOT), relative)
            self.assertFalse(path.is_symlink(), relative)
            self.assertTrue(path.is_file(), relative)
            if relative.startswith("catalog/skills/expansion501-geology-") and relative.endswith("/SKILL.md"):
                skills.append(path)
        self.assertEqual(len(skills), 9)
        for path in skills:
            text = path.read_text(encoding="utf-8-sig")
            for marker in ("not_deployed", "not_submitted", "not_run"):
                self.assertIn(marker, text, str(path))

    def test_02_no_eager_science_or_arbitrary_dispatch(self):
        scientific = {"numpy", "scipy", "pandas", "pymatgen", "pyrolite", "spglib",
                      "porespy", "openpnm", "sklearn", "geostatspy", "pyslope", "pyMelt", "gempy", "gempy_engine"}
        for node in self.tree.body:
            if isinstance(node, ast.Import):
                self.assertFalse({x.name.split(".")[0] for x in node.names} & scientific)
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[0], scientific)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, {"eval", "exec", "compile", "__import__"})
                if isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, {"system", "popen", "import_module"})
            if isinstance(node, ast.Import):
                self.assertFalse({x.name.split(".")[0] for x in node.names} &
                                 {"subprocess", "requests", "httpx", "socket", "pickle"})
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[0],
                                 {"subprocess", "requests", "httpx", "socket", "pickle"})


def _source_test(tool_id):
    def test(self):
        tool = self.tools[tool_id]
        interface = tool["source_interface"]
        self.assertEqual(interface["kind"], "expansion501_geology")
        self.assertEqual(interface["entrypoint"]["callable"], MODULE + ":" + ENTRYPOINTS[tool_id])
        self.assertEqual(interface["entrypoint"]["argument_parameter"], "args")
        self.assertEqual(interface["entrypoint"]["bound_arguments"], {})
        self.assertEqual(interface["path_fields"], [])
        self.assertIs(interface["network_required"], False)
        self.assertIs(interface["pure"], False)
        definition = self.definitions[tool_id]
        self.assertEqual(definition.name, ENTRYPOINTS[tool_id])
        self.assertEqual([x.arg for x in definition.args.args], ["args"])
        self.assertIsNone(definition.args.vararg)
        self.assertIsNone(definition.args.kwarg)
        meta = tool["registration_metadata"]
        self.assertRegex(meta["source_commit"], r"^[0-9a-f]{40}$")
        matches = [url for url in SOURCE_COMMITS
                   if meta["source_url"].rstrip("/") == url]
        self.assertEqual(len(matches), 1, meta["source_url"])
        self.assertEqual(meta["source_commit"], SOURCE_COMMITS[matches[0]])
        self.assertTrue(meta["license"].strip())
        lifecycle = meta["lifecycle"]
        self.assertEqual(lifecycle["deployment_status"], "not_deployed")
        self.assertEqual(lifecycle["submission_status"], "not_submitted")
        for key in ("unit_validation", "workflow_validation", "model_workflow_validation",
                    "platform_validation"):
            self.assertEqual(lifecycle[key], "not_run")
        lock = ROOT / meta["runtime"]["dependency_lock"]
        self.assertTrue(_beneath(lock, GROUP))
        self.assertTrue(lock.is_file())
        requirements = lock.read_text(encoding="utf-8-sig")
        self.assertTrue(any(line.strip() and not line.startswith("#") for line in requirements.splitlines()))
        for package, version in PRIVATE_BASE_PINS.get(tool_id, BASE_PINS).items():
            self.assertIn(package + "==" + version, requirements)
    return test


def _interface_test(tool_id):
    def test(self):
        tool = self.tools[tool_id]
        for key in ("input_schema", "output_schema"):
            schema = tool[key]
            self.Validator.check_schema(schema)
            self.assertEqual(schema["type"], "object")
            self.assertIs(schema["additionalProperties"], False)
            self.assertEqual(set(schema["required"]), set(schema["properties"]))
        self.assertEqual(tool["function"]["function"]["parameters"], tool["input_schema"])
        self.assertEqual(tool["function"]["function"]["name"], tool_id)
        self.Validator(tool["input_schema"]).validate(self.examples[tool_id])
        self.assertIn("SYNTHETIC", self.examples[tool_id]["data_source"].upper())
        output = tool["output_schema"]
        self.assertTrue({"units", "artifacts", "provenance"} <= set(output["required"]))
        self.assertIs(output["properties"]["units"]["additionalProperties"], False)
        self.assertIs(output["properties"]["provenance"]["additionalProperties"], False)
        self.assertEqual(output["properties"]["artifacts"]["maxItems"], 0)
        properties = output["properties"]["provenance"]["properties"]
        self.assertEqual(properties["tool"]["const"], tool_id)
        self.assertEqual(properties["reviewed_archive_commit"]["const"],
                         tool["registration_metadata"]["source_commit"])
        pins = properties["installed_versions"]
        self.assertIs(pins["additionalProperties"], False)
        for package, version in PRIVATE_BASE_PINS.get(tool_id, BASE_PINS).items():
            self.assertEqual(pins["properties"][package]["const"], version)
        for package, schema in pins["properties"].items():
            self.assertIsInstance(schema["const"], str, package)
            self.assertTrue(schema["const"], package)
    return test


class GeologyCPUAcceptance(unittest.TestCase):
    """Real decorated calls only, with explicit CPU/profile and staging gates."""

    @classmethod
    def setUpClass(cls):
        cls.revision = _require_private_cpu()
        cls.network_patches = []
        for target in ("socket.create_connection", "socket.getaddrinfo",
                       "socket.socket.connect", "socket.socket.connect_ex"):
            patcher = mock.patch(target, side_effect=AssertionError(
                "Acceptance forbids network access from adapters or their dependencies."))
            patcher.start()
            cls.network_patches.append(patcher)
            cls.addClassCleanup(patcher.stop)
        from jsonschema import Draft202012Validator
        from legacy.ToolsAgent.ToolsFuns import source_contracts
        from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError
        cls.Validator = Draft202012Validator
        cls.ScientificToolError = ScientificToolError
        cls.source_contracts = source_contracts
        cls.module = importlib.import_module(MODULE)
        cls.tools = {t["id"]: t for t in _read_json(GROUP / "catalog-additions.json")["tools"]}
        cls.examples = _read_json(GROUP / "examples-additions.json")
        cls.cache = {}

    def _invoke(self, tool_id, args, json_input=False):
        fn = getattr(self.module, ENTRYPOINTS[tool_id])
        submitted = json.dumps(args, allow_nan=False) if json_input else copy.deepcopy(args)
        before = copy.deepcopy(submitted)
        if tool_id == "GeoSlopeLimitEquilibrium":
            # Test-only common random numbers preserve the same searched family.
            # They do not establish operational determinism or change pure=false.
            import numpy as np
            python_state, numpy_state = random.getstate(), np.random.get_state()
            try:
                random.seed(50126)
                np.random.seed(50126)
                result = fn(submitted)
            finally:
                random.setstate(python_state)
                np.random.set_state(numpy_state)
        else:
            result = fn(submitted)
        self.assertEqual(submitted, before, "Adapter mutated caller input.")
        return result

    def _baseline(self, tool_id):
        if tool_id not in self.cache:
            self.cache[tool_id] = self._invoke(tool_id, self.examples[tool_id])
        return copy.deepcopy(self.cache[tool_id])

    def _assert_output(self, tool_id, args, result):
        self.assertIsInstance(result, dict)
        self.Validator(self.tools[tool_id]["output_schema"]).validate(result)
        json.dumps(result, allow_nan=False)
        self.assertEqual(result["input_source"], args["data_source"])
        self.assertEqual(result["artifacts"], [])
        provenance = result["provenance"]
        self.assertEqual(provenance["tool"], tool_id)
        self.assertEqual(provenance["reviewed_archive_commit"],
                         self.tools[tool_id]["registration_metadata"]["source_commit"])
        self.assertIs(provenance["network_required"], False)
        self.assertEqual(provenance["output_sha256"], {})
        self.assertEqual(provenance["vendored_source"], [])
        for field in ("input_sha256", "implementation_sha256", "contract_sha256"):
            self.assertRegex(provenance[field], r"^[0-9a-f]{64}$")
        self.assertTrue(provenance["runtime_source_correspondence"].strip())
        for key, schema in self.tools[tool_id]["output_schema"]["properties"]["units"]["properties"].items():
            if "const" in schema:
                self.assertEqual(result["units"][key], schema["const"])

    def _reject(self, tool_id, args, code="invalid_arguments"):
        with self.assertRaises(self.ScientificToolError) as caught:
            getattr(self.module, ENTRYPOINTS[tool_id])(copy.deepcopy(args))
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        return caught.exception

    def _close(self, actual, expected, absolute=1e-8, relative=0):
        self.assertTrue(math.isfinite(float(actual)))
        self.assertTrue(math.isclose(float(actual), float(expected),
                                     abs_tol=absolute, rel_tol=relative),
                        "actual={!r}, independent expected={!r}, atol={}, rtol={}".format(
                            actual, expected, absolute, relative))

    def _vector(self, actual, expected, absolute=1e-8, relative=0):
        self.assertEqual(len(actual), len(expected))
        for a, b in zip(actual, expected):
            self._close(a, b, absolute, relative)

    def _oracle(self, tool_id, args, result):
        """Analytic geometry, stoichiometry and external constants, never upstream replay."""
        if tool_id == "Geo500CrystalSpaceGroupAudit":
            self.assertEqual(result["space_group_number"], 221)
            self.assertEqual(result["rotation_count"], 48)
            self.assertEqual(result["international_symbol"], "Pm-3m")
            self.assertEqual(result["equivalent_atoms"], [0])
        elif tool_id == "Geo500IrreducibleReciprocalMesh":
            self.assertEqual(result["full_mesh_size"], 8)
            self.assertEqual(sorted(result["weights"]), [1, 1, 3, 3])
            self.assertEqual(sum(result["weights"]), 8)
            self.assertEqual(len(result["fractional_kpoints"]), 4)
        elif tool_id == "Geo500PowderXRDPattern":
            # Cubic (100) spacing a; Bragg's law 2*d*sin(theta)=lambda.
            theta = 2 * math.degrees(math.asin(1 / 8))
            self._close(result["two_theta_degrees"][0], theta, absolute=1e-7)
            self._close(result["d_spacings_angstrom"][0], 4, absolute=1e-10)
            self._close(max(result["relative_intensity"]), 100, absolute=1e-10)
        elif tool_id == "Geo500MineralOxygenBasisFormula":
            pairs = list(zip(result["ion_labels"], result["apfu"]))
            expected_formula = _oxygen_reference(args["oxide_wt_percent"])
            for element, expected in expected_formula.items():
                values = [value for label, value in pairs
                          if re.match(r"^" + element + r"(?:$|[^a-z])", label)]
                self.assertEqual(len(values), 1, pairs)
                # Original wt% retained; explicit 2.1.0 elemental masses, not upstream replay.
                self._close(values[0], expected, absolute=1e-6)
            self._close(result["input_total"], 100, absolute=1e-10)
            self.assertIs(result["iron_redox_inferred"], False)
            self.assertEqual(result["atomic_weight_convention"], "periodictable-2.1.0-elemental")
            self._vector(result["oxide_molar_masses"], [40.304, 60.083], absolute=1e-12)
        elif tool_id == "GeoConditionedResourceEnsemble":
            # One conditioned point: Ctt-Cto*(4+alpha)^-1*Cot, evaluated analytically.
            noise = args["measurement_noise_variance_ppm2"]
            cross = 4 / math.e
            expected_mean = 10 + cross * 2 / (4 + noise)
            diagonal = 4 - cross * cross / (4 + noise)
            off_diagonal = 4 * math.exp(-2) - cross * cross / (4 + noise)
            self._vector(result["conditional_mean"], [expected_mean] * 2, absolute=1e-12)
            self._vector(result["conditional_covariance"][0], [diagonal, off_diagonal], absolute=1e-12)
            self._vector(result["conditional_covariance"][1], [off_diagonal, diagonal], absolute=1e-12)
            self.assertEqual(len(result["realizations"]), args["realization_count"])
            for draw in result["realizations"]:
                self.assertEqual(len(draw), 2)
                self.assertTrue(all(math.isfinite(x) for x in draw))
            self.assertIs(result["optimizer_used"], False)
            self.assertIs(result["jitter_added"], False)
            self.assertIs(result["negative_realizations_clipped"], False)
        elif tool_id == "Geo500PoreDiffusionTortuosity":
            # One straight five-voxel channel through a 3x3 cross section.
            # Four unit resistors, length four lattice spacings, cross section nine.
            self._close(result["tortuosity"], 1, absolute=1e-7)
            self._close(result["formation_factor"], 9, absolute=1e-7)
            self._close(result["original_porosity"], 1 / 9, absolute=1e-12)
            self._close(result["effective_porosity"], 1 / 9, absolute=1e-12)
            self._close(result["effective_diffusivity"], args["molecular_diffusivity_m2_s"] / 9,
                        absolute=1e-17)
            self._vector(result["normalized_concentration"][20:25], [1, .75, .5, .25, 0], absolute=1e-7)
            self.assertEqual(result["retained_pore_mask"], args["pore_mask"])
            self.assertIs(result["flux_balance_converged"], True)
        elif tool_id == "Geo500MineralReactionBalance":
            self._vector(result["coefficients"], [-1, -1, 2], absolute=1e-10)
            self._vector(result["element_residuals"], [0] * len(result["elements"]), absolute=1e-10)
        elif tool_id == "Geo500MineralPhaseHull":
            self.assertEqual(len(result["results"]), 1)
            row = result["results"][0]
            self.assertEqual(row["phase_id"], "LiO_high")
            self._close(row["energy_above_hull_ev_per_atom"], 1, absolute=1e-10)
            self.assertEqual(len(row["decomposition"]), 1)
            self.assertEqual(row["decomposition"][0]["phase_id"], "LiO_low")
            self._close(row["decomposition"][0]["atomic_fraction"], 1, absolute=1e-10)
        elif tool_id == "Geo500CrystalCoordination":
            self.assertEqual(len(result["sites"]), 1)
            site = result["sites"][0]
            self.assertEqual(site["coordination_number"], 6)
            self.assertEqual(len(site["neighbors"]), 6)
            for neighbor in site["neighbors"]:
                self._close(neighbor["distance_angstrom"], 2.82, absolute=1e-10)
        elif tool_id == "Geo500BondValenceOxidation":
            self._vector(result["inferred_valences"], [2] * 4 + [-2] * 4, absolute=1e-12)
            self._close(result["cell_charge"], 0, absolute=1e-12)
            self.assertIs(result["measured_redox"], False)
        elif tool_id == "Geo500CrystalStructureEquivalence":
            self.assertIs(result["equivalent"], True)
            self._close(result["rms_displacement"], 0, absolute=1e-10)
            self._close(result["maximum_displacement"], 0, absolute=1e-10)
            self.assertIs(result["scale_allowed"], False)
            self.assertIs(result["supercell_search"], False)
        elif tool_id == "Geo500WulffCrystalHabit":
            facets = {tuple(row["hkl"]): row["area_fraction"] for row in result["facets"]}
            self._close(facets[(1, 0, 0)], 1)
            self._close(sum(facets.values()), 1)
            for hkl, area in facets.items():
                if hkl != (1, 0, 0):
                    self._close(area, 0)
            self._close(result["shape_factor"], 6)
            self._close(result["weighted_surface_energy"], 1)
            self.assertIs(result["absolute_crystal_size_inferred"], False)
        elif tool_id == "Geo500PeriodicIonicLatticeEnergy":
            # Frozen independent NaCl Madelung reference, four ion pairs per cell.
            # 1e-5 eV is the predeclared acc_factor=8 numerical budget, not a
            # tolerance fitted to an observed adapter result. Citation freeze pending.
            self._close(result["total_energy_ev"], -35.694057607611626, absolute=1e-5)
            self._close(result["energy_per_atom_ev"], -35.694057607611626 / 8, absolute=1.25e-6)
            self._close(result["cell_charge"], 0, absolute=1e-12)
        elif tool_id == "Geo500CoherentMineralInterfaceMatch":
            self.assertIs(result["found"], True)
            self._close(result["match_area"], 4, absolute=1e-10)
            matrix = result["transformation"]
            self.assertIn(len(matrix), (2, 3))
            for i, row in enumerate(matrix):
                self._vector(row, [int(i == j) for j in range(len(matrix))], absolute=1e-10)
        elif tool_id == "Geo500MineralSurfaceTerminations":
            self.assertEqual(len(result["terminations"]), 1)
            slab = result["terminations"][0]
            self._close(slab["surface_area_angstrom2"], 4, absolute=1e-10)
            self.assertEqual(slab["species"], ["Si"] * 4)
            heights = sorted(sum(frac[k] * slab["lattice_angstrom"][k][2]
                                 for k in range(3)) for frac in slab["fractional_coords"])
            self._vector([b - a for a, b in zip(heights, heights[1:])], [2, 2, 2], absolute=1e-10)
            self.assertIs(result["atomic_repair_applied"], False)
            self.assertIs(result["surface_energy_calculated"], False)
        elif tool_id == "Geo500REEOrthogonalShape":
            self.assertEqual(len(result["element_order"]), 13)
            self.assertEqual(len(result["lambda_coefficients"]), 1)
            self._vector(result["lambda_coefficients"][0], [2, 0, 0, 0], absolute=1e-8)
        elif tool_id == "Geo500VolcanicTASClass":
            self.assertEqual(result["classifications"], [{"class_id": "Bs", "status": "classified"}])
            self.assertIs(result["anhydrous_basis_confirmed"], True)
        elif tool_id == "Geo500MineralNeutronContrast":
            # NIST/Sears bSi=4.1491 fm, bO=5.803 fm, natural SiO2 at 2.65 g/cm3.
            # 0.1% was frozen before execution for independently tabulated constants.
            self.assertEqual(result["sld_order"][0], "real")
            self._close(result["sld"][0], 4.184719291694345, absolute=0, relative=0.001)
            self.assertGreater(result["penetration_depth"], 0)
            self.assertTrue(all(value >= 0 for value in result["macroscopic_cross_sections"]))
        elif tool_id == "Geo500PoreChordDistribution":
            self.assertEqual(result["chord_count"], 2)
            self._vector(sorted(result["chord_lengths_m"]), [0.02, 0.04], absolute=1e-12)
            self._vector(result["relative_frequency"], [0.5, 0.5], absolute=1e-12)
            self._close(sum(result["chord_lengths_m"]) / 2, 0.03, absolute=1e-12)
            self.assertIs(result["edge_censoring"], True)
        elif tool_id == "Geo500PoreBodyRadiusDistribution":
            field = result["radius_field_m"]
            self.assertEqual(result["shape"], [7, 7, 7])
            self.assertEqual(len(field), 343)
            self.assertEqual(sum(args["pore_mask"]), 27)
            for is_pore, radius in zip(args["pore_mask"], field):
                self._close(radius, 2e-6 if is_pore else 0, absolute=1e-12)
            self._vector(result["pore_volume_fraction"], [0, 1], absolute=1e-10)
        elif tool_id == "Geo500QuasistaticCapillaryDrainage":
            self._vector(result["applied_pressure_pa"], [1000, 3000], absolute=1e-10)
            self._vector(result["nonwetting_saturation"], [0, 1], absolute=1e-12)
            self.assertEqual(len(result["invaded_mask"]), 49)
            self.assertEqual(result["invaded_mask"], args["pore_mask"])
            for is_pore, pressure in zip(args["pore_mask"], result["invasion_pressure_pa"]):
                if is_pore:
                    self._close(pressure, 3000, absolute=1e-10)
                else:
                    self.assertIsNone(pressure)
            self.assertIs(result["trapping_enabled"], True)
        elif tool_id == "Geo500MineralEhPHStability":
            self._vector(result["decomposition_energy_ev_per_atom"], [0, 1], absolute=1e-8)
            self.assertEqual(result["target_id"], "Fe_s")
        elif tool_id == "Geo500SpatialCellDeclustering":
            self._vector(result["weights"], [1/6, 1/6, 1/6, 1/2], absolute=1e-10)
            self._close(result["declustered_mean"], 6, absolute=1e-10)
            self._close(sum(result["weights"]), 1, absolute=1e-12)
        elif tool_id == "GeoSlopeLimitEquilibrium":
            self.assertGreater(result["factor_of_safety"], 0)
            self.assertGreater(result["converged_surface_count"], 0)
            scaled = copy.deepcopy(args)
            for row in scaled["materials"]:
                row["unit_weight_kn_m3"] *= 2
                row["cohesion_kpa"] *= 2
            for row in scaled["uniform_loads"]:
                row["magnitude_kpa"] *= 2
            for row in scaled["line_loads"]:
                row["magnitude_kn_m"] *= 2
            key = tool_id + ":scaled"
            if key not in self.cache:
                self.cache[key] = self._invoke(tool_id, scaled)
            other = self.cache[key]
            self._assert_output(tool_id, scaled, other)
            # Dry Bishop equations are homogeneous in forces, with unchanged geometry.
            self._close(other["factor_of_safety"] / result["factor_of_safety"], 1, absolute=1e-5)
            self.assertNotEqual(other["provenance"]["input_sha256"], result["provenance"]["input_sha256"])
            # This invariant is explicitly NOT an independent absolute-FOS benchmark.
        elif tool_id == "GeoMantleMeltingPath":
            self.assertEqual(len(result["pressure_gpa"]), 101)
            self._close(result["pressure_gpa"][0], 4, absolute=1e-12)
            self._close(result["pressure_gpa"][-1], 0.1, absolute=1e-12)
            self.assertTrue(all(a > b for a, b in zip(result["pressure_gpa"], result["pressure_gpa"][1:])))
            self.assertEqual(len(result["temperature_degc"]), 101)
            self.assertEqual(len(result["melt_fractions"]), 101)
            self.assertEqual(len(result["bulk_melt_fraction"]), 101)
            for fractions, bulk in zip(result["melt_fractions"], result["bulk_melt_fraction"]):
                self.assertEqual(len(fractions), 2)
                self.assertTrue(all(0 <= f <= 1 for f in fractions))
                self._close(bulk, 0.8 * fractions[0] + 0.2 * fractions[1], absolute=1e-10)
            # Absolute thermal/melt-path benchmark is still acceptance_pending.
        elif tool_id == "GeoImplicitStructuralModel":
            xyz, labels = result["grid_coordinates_m"], result["lithology_labels"]
            self.assertEqual(len(xyz), 512)
            self.assertEqual(len(labels), 512)
            self.assertEqual(result["resolution"], [8, 8, 8])
            centers = {62.5 + 125 * i for i in range(8)}
            self.assertEqual({tuple(p) for p in xyz},
                             {(x, y, z) for x in centers for y in centers for z in centers})
            lower = {label for p, label in zip(xyz, labels) if p[2] < 500}
            upper = {label for p, label in zip(xyz, labels) if p[2] > 500}
            self.assertEqual(len(lower), 1)
            self.assertEqual(len(upper), 1)
            self.assertTrue(lower.isdisjoint(upper))
            self.assertEqual(sorted(labels.count(label) for label in set(labels)), [256, 256])
        else:
            self.fail("Independent oracle missing: " + tool_id)


def _runtime_test(tool_id, kind):
    def test(self):
        args = copy.deepcopy(self.examples[tool_id])
        if kind == "staged_registration_and_pins":
            staged = self.source_contracts.catalog()
            matches = [row for row in staged["tools"] if row["id"] == tool_id]
            self.assertEqual(len(matches), 1, "Parent must stage exactly one real catalog entry.")
            actual, supplied = matches[0], self.tools[tool_id]
            for key in ("input_schema", "output_schema"):
                self.assertEqual(actual[key], supplied[key])
            self.assertEqual(actual["source_interface"]["kind"], "expansion501_geology")
            self.assertEqual(actual["source_interface"]["entrypoint"], supplied["source_interface"]["entrypoint"])
            self.assertEqual(actual["registration_metadata"]["source_commit"],
                             supplied["registration_metadata"]["source_commit"])
            pins = supplied["output_schema"]["properties"]["provenance"]["properties"]["installed_versions"]
            for package, schema in pins["properties"].items():
                self.assertEqual(importlib.metadata.version(package), schema["const"], package)
            if tool_id == "Geo500SpatialCellDeclustering":
                direct = importlib.metadata.distribution("geostatspy").read_text("direct_url.json")
                self.assertTrue(direct)
                self.assertEqual(json.loads(direct)["url"],
                    "https://github.com/GeostatsGuy/GeostatsPy/archive/45b2032a1e3f05de6cd0cb7f32ed43203399dbfa.zip")
        elif kind == "direct_dict_numeric":
            result = self._baseline(tool_id)
            self._assert_output(tool_id, args, result)
            self._oracle(tool_id, args, result)
        elif kind == "direct_json_numeric":
            result = self._invoke(tool_id, args, json_input=True)
            self._assert_output(tool_id, args, result)
            self._oracle(tool_id, args, result)
            previous = self._baseline(tool_id)["provenance"]
            for field in ("input_sha256", "implementation_sha256", "contract_sha256"):
                self.assertEqual(result["provenance"][field], previous[field])
        elif kind == "reject_unknown_dispatch_fields":
            for key in ("module", "function", "python_function", "code", "script", "output_dir"):
                with self.subTest(field=key):
                    invalid = copy.deepcopy(args)
                    invalid[key] = "not_an_allowed_argument"
                    self._reject(tool_id, invalid)
        elif kind == "reject_missing_required":
            del args["data_source"]
            self._reject(tool_id, args)
        elif kind == "reject_nonfinite":
            path = _first_leaf_path(args, numeric=True)
            if path is None:
                path = _first_leaf_path(args, numeric=False)
            self.assertIsNotNone(path)
            for value in (float("nan"), float("inf"), float("-inf")):
                with self.subTest(value=repr(value)):
                    invalid = copy.deepcopy(args)
                    _set_path(invalid, path, value)
                    self._reject(tool_id, invalid)
        elif kind == "reject_specific_physical_domain":
            invalid, code = _physical_case(tool_id, args)
            self._reject(tool_id, invalid, code)
        elif kind == "reject_shape_mismatch":
            self._reject(tool_id, _shape_case(tool_id, args))
        elif kind == "reject_wrong_dependency_version":
            # Negative contract injection only; no upstream kernel is mocked.
            wrong = "0.0.0-expansion501-negative"
            with mock.patch("importlib.metadata.version", return_value=wrong):
                with self.assertRaises(self.ScientificToolError) as caught:
                    getattr(self.module, ENTRYPOINTS[tool_id])(args)
            self.assertIn(caught.exception.code, {"missing_dependency", "incompatible_dependency"})
            expected_dependency = {
                "Geo500BondValenceOxidation": "pymatgen-core",
                "Geo500CoherentMineralInterfaceMatch": "pymatgen",
                "Geo500CrystalCoordination": "pymatgen-core",
                "Geo500CrystalSpaceGroupAudit": "spglib",
                "Geo500CrystalStructureEquivalence": "pymatgen-core",
                "Geo500IrreducibleReciprocalMesh": "spglib",
                "Geo500MineralEhPHStability": "pymatgen",
                "Geo500MineralPhaseHull": "pymatgen-core",
                "Geo500MineralReactionBalance": "pymatgen-core",
                "Geo500MineralSurfaceTerminations": "pymatgen-core",
                "Geo500PeriodicIonicLatticeEnergy": "pymatgen-core",
                "Geo500PowderXRDPattern": "pymatgen",
                "Geo500WulffCrystalHabit": "pymatgen",
                "Geo500MineralNeutronContrast": "periodictable",
                "Geo500MineralOxygenBasisFormula": "pyrolite",
                "Geo500REEOrthogonalShape": "pyrolite",
                "Geo500VolcanicTASClass": "pyrolite",
                "Geo500PoreBodyRadiusDistribution": "porespy",
                "Geo500PoreChordDistribution": "porespy",
                "Geo500QuasistaticCapillaryDrainage": "porespy",
                "GeoSlopeLimitEquilibrium": "pyslope",
                "GeoMantleMeltingPath": "pyMelt",
                "GeoImplicitStructuralModel": "gempy",
                "GeoConditionedResourceEnsemble": "scikit-learn",
                "Geo500PoreDiffusionTortuosity": "porespy",
                "Geo500SpatialCellDeclustering": "numpy",
            }.get(tool_id)
            if expected_dependency is None:
                # Unexecuted GeoStatsPy case retains its prior assertion.
                self.assertIn(wrong, str(caught.exception))
            else:
                self.assertEqual(
                    str(caught.exception),
                    "Install the reviewed dependency release for " + expected_dependency,
                )
        elif kind == "reject_missing_private_cpu_identity":
            # CUDA and all other GPU-disable settings remain unchanged throughout.
            previous = os.environ.pop("GEOAGENT_EXPANSION501_GEOLOGY_CPU")
            try:
                error = self._reject(tool_id, args, "missing_dependency")
                self.assertIn("Parent-bound private CPU environment", str(error))
            finally:
                os.environ["GEOAGENT_EXPANSION501_GEOLOGY_CPU"] = previous
        else:
            self.fail("Unknown fixed acceptance case: " + kind)
    return test


def _oxygen_reference(weights):
    """Independent exact-decimal stoichiometry, no periodictable/pyrolite imports."""
    mg_o = Fraction("24.305") + Fraction("15.999")
    si_o2 = Fraction("28.085") + 2 * Fraction("15.999")
    mg_moles = Fraction(str(weights[0])) / mg_o
    si_moles = Fraction(str(weights[1])) / si_o2
    oxygen_moles = mg_moles + 2 * si_moles
    return {"Mg": float(4 * mg_moles / oxygen_moles),
            "Si": float(4 * si_moles / oxygen_moles), "O": 4.0}


class GeologyLocalReferences(unittest.TestCase):
    """Standard-library reference/source gates only; no upstream scientific acceptance."""

    def test_original_oxygen_input_under_explicit_mass_table(self):
        expected = _oxygen_reference([57.293630232496, 42.706369767504])
        self.assertAlmostEqual(expected["Mg"], 1.9999704077834797, places=12)
        self.assertAlmostEqual(expected["Si"], 1.0000147961082602, places=12)
        self.assertGreater(abs(expected["Mg"] - 2), 1e-6)
        self.assertEqual(expected["O"], 4)

    def test_ideal_oxygen_formula_is_separate_fixture(self):
        mg_o, si_o2 = Fraction("40.304"), Fraction("60.083")
        weights = [float(100 * 2 * mg_o / (2 * mg_o + si_o2)),
                   float(100 * si_o2 / (2 * mg_o + si_o2))]
        expected = _oxygen_reference(weights)
        self.assertAlmostEqual(expected["Mg"], 2, places=12)
        self.assertAlmostEqual(expected["Si"], 1, places=12)

    def test_exponential_conditional_cross_covariance_counterexample(self):
        off_diagonal = 4 * math.exp(-2) - (4 * math.exp(-1)) ** 2 / 4
        self.assertAlmostEqual(off_diagonal, 0, places=14)
        self.assertGreater(4 * (1 - math.exp(-2)), 0)
        self.assertGreater(4 * math.exp(-2) * (1 - math.exp(-2)), 0)

    def test_measurement_noise_preserves_nonzero_joint_covariance(self):
        off_diagonal = 4 * math.exp(-2) - (4 * math.exp(-1)) ** 2 / 5
        self.assertAlmostEqual(off_diagonal, .8 * math.exp(-2), places=14)
        self.assertGreater(off_diagonal, 0)

    def test_straight_channel_resistance_oracle(self):
        resistance = Fraction(4)
        length, area, porosity = Fraction(4), Fraction(9), Fraction(1, 9)
        relative_diffusivity = length / (area * resistance)
        self.assertEqual(relative_diffusivity, Fraction(1, 9))
        self.assertEqual(porosity / relative_diffusivity, 1)

    def test_authored_fixed_entrypoints_and_blocked_exclusion(self):
        tree = ast.parse(MODULE_FILE.read_text(encoding="utf-8-sig"))
        names = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == "operation":
                        names[ast.literal_eval(dec.args[0])] = node.name
                        self.assertEqual([a.arg for a in node.args.args], ["args"])
        self.assertEqual(names, ENTRYPOINTS)
        self.assertTrue(set(names).isdisjoint(BLOCKED_IDS))

    def test_contribution_assignment_and_closed_top_level(self):
        catalog = _read_json(GROUP / "catalog-additions.json")
        statuses = _read_json(GROUP / "adaptation-status.json")["operations"]
        self.assertEqual({s["id"] for s in statuses}, set(ENTRYPOINTS) | BLOCKED_IDS)
        self.assertEqual(len(statuses), 31)
        self.assertEqual({t["id"] for t in catalog["tools"]}, set(ENTRYPOINTS))
        for tool in catalog["tools"]:
            for name in ("input_schema", "output_schema"):
                schema = tool[name]
                self.assertEqual(schema["type"], "object")
                self.assertIs(schema["additionalProperties"], False)
                self.assertEqual(set(schema["properties"]), set(schema["required"]))
            self.assertEqual(set(tool["example_arguments"]), set(tool["input_schema"]["required"]))
            self.assertIs(tool["metadata"]["scientific_contract"]["formal_eligible"], False)


def _extended_reference_test(tool_id):
    def test(self):
        args = copy.deepcopy(self.examples[tool_id])
        if tool_id == "Geo500MineralOxygenBasisFormula":
            mg_o, si_o2 = Fraction("40.304"), Fraction("60.083")
            args["oxide_wt_percent"] = [float(200 * mg_o / (2 * mg_o + si_o2)),
                                       float(100 * si_o2 / (2 * mg_o + si_o2))]
        else:
            args["measurement_noise_variance_ppm2"] = 1.0
        result = self._invoke(tool_id, args)
        self._assert_output(tool_id, args, result)
        self._oracle(tool_id, args, result)
    return test


for _tool_id in sorted(ENTRYPOINTS):
    setattr(GeologySourceRegistration, "test_source_" + _tool_id, _source_test(_tool_id))
    setattr(GeologySourceRegistration, "test_interface_" + _tool_id, _interface_test(_tool_id))

RUNTIME_CASES = (
    "staged_registration_and_pins", "direct_dict_numeric", "direct_json_numeric",
    "reject_unknown_dispatch_fields", "reject_missing_required", "reject_nonfinite",
    "reject_specific_physical_domain", "reject_shape_mismatch",
    "reject_wrong_dependency_version", "reject_missing_private_cpu_identity",
)
for _tool_id in SELECTED_IDS:
    for _kind in RUNTIME_CASES:
        setattr(GeologyCPUAcceptance, "test_" + _tool_id + "__" + _kind,
                _runtime_test(_tool_id, _kind))
    if _tool_id in {"Geo500MineralOxygenBasisFormula", "GeoConditionedResourceEnsemble"}:
        setattr(GeologyCPUAcceptance, "test_" + _tool_id + "__extended_independent_reference",
                _extended_reference_test(_tool_id))


if __name__ == "__main__":
    unittest.main(verbosity=2)


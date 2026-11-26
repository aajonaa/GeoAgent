"""Independent, SYNTHETIC expansion501 geophysics CPU acceptance source.

Not executed during authoring. Parent must stage the contribution first. No
catalog overlay, installation, upstream-generated expected results, GPU, model,
network or deployment is performed here. Missing scientific references FAIL
explicitly; passing an interface test is not scientific acceptance.
"""
import ast
import copy
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
GROUP = ROOT / "catalog/source_delivery/expansion501-20261026/groups/geophysics"
MODULE = "geological_agent.geology.expansion501_geophysics"
SYNTHETIC = "SYNTHETIC independent analytic acceptance fixture; not field observations"
G = 6.67430e-11
ENTRIES = {
    "GeoSeismicInstrumentDeconvolution": "seismic_instrument_deconvolution",
    "GeoEMLayeredBipoleResponse": "em_layered_bipole_response",
    "GeoGravityTesseroid": "gravity_tesseroid",
    "GeoPotentialEulerSourceLocation": "potential_euler_source_location",
    "GeoSurfaceWaveDispersion": "surface_wave_dispersion",
    "GeoPotentialEquivalentSources": "potential_equivalent_sources",
    "GeoPotentialUpwardContinuation": "potential_upward_continuation",
    "GeoMagneticReductionToPole": "magnetic_reduction_to_pole",
    "GeoDCFourElectrodeResponse": "dc_four_electrode_response",
    "GeoGravityNormalEllipsoid": "gravity_normal_ellipsoid",
    "GeoSeismicArrayBeamforming": "seismic_array_beamforming",
    "GeoSeismicSTALTADetection": "seismic_sta_lta_detection",
    "GeoSeismicTemplateDetection": "seismic_template_detection",
    "GeoSeismicPolarization": "seismic_polarization",
    "GeoSeismicTauPRays": "seismic_taup_rays",
    "GeoSeismicNMO": "seismic_nmo",
    "GeoSeismicComplexAttributes": "seismic_complex_attributes",
    "GeoSeismicWindowCoherence": "seismic_window_coherence",
    "GeoPotentialEdgeAttributes": "potential_edge_attributes",
    "GeoSeismicArrayStrainRotation": "seismic_array_strain_rotation",
    "GeoGravityBouguerSlab": "gravity_bouguer_slab",
    "GeoCrustAiryMoho": "crust_airy_moho",
    "GeoEMConductiveSphere": "em_conductive_sphere",
    "GeoMagneticWirePath": "magnetic_wire_path",
    "GeoSeismicARPhasePick": "seismic_ar_phase_pick",
    "GeoSeismicProbabilisticNoise": "seismic_probabilistic_noise",
    "GeoSeismicWaveformTFMisfit": "seismic_waveform_tf_misfit",
    "GeoSeismicRadiationPattern": "seismic_radiation_pattern",
    "GeoSurfaceWaveEigenfunctions": "surface_wave_eigenfunctions",
    "GeoSurfaceWaveSensitivity": "surface_wave_sensitivity",
    "GeoDCResistivityInversion": "dc_resistivity_inversion",
    "GeoFDEMConductivityInversion": "fdem_conductivity_inversion",
    "GeoTDEMConductivityInversion": "tdem_conductivity_inversion",
    "GeoGravityDensityInversion": "gravity_density_inversion",
    "GeoMagneticSusceptibilityInversion": "magnetic_susceptibility_inversion",
    "GeoSeismicLeastSquaresMigration": "seismic_least_squares_migration",
    "GeoSeismicPoststackImpedanceInversion": "seismic_poststack_impedance_inversion",
    "GeoSeismicPrestackElasticInversion": "seismic_prestack_elastic_inversion",
    "GeoSeismicReceiverDeghosting": "seismic_receiver_deghosting",
    "GeoSeismicUpDownWavefieldSeparation": "seismic_up_down_wavefield_separation",
    "GeoSeismicMultidimensionalDeconvolution": "seismic_multidimensional_deconvolution",
    "GeoIPChargeabilityInversion": "ip_chargeability_inversion",
}
BLOCKED_ADAPTERS = {"GeoSeismicMarchenkoRedatuming", "GeoSeismicTraveltimeTomography"}
PINS = {
    "obspy": ("1.4.2", "a629e8c021052904b6b8d62699d03f2a3721ae63"),
    "bruges": ("0.5.4", "24e2e7912f49089465dd622363fd2788029266b1"),
    "harmonica": ("0.7.0", "b9f9c00b0999f470dcae971b19add28b055633c9"),
    "empymod": ("2.6.0", "7a7c221da5940a8e0d8f60478b929e2690806521"),
    "geoana": ("0.9.0", "7c47ec2e1253e698c26c95d6dd0c7e493a1c8630"),
    "boule": ("0.6.0", "8666d0823c667c543bfce503cc3759b9c3047287"),
    "disba": ("0.7.0", "18b7d023288f2bf22d2f128e8ca6a10d15b5913a"),
    "simpeg": ("0.25.2", "5f2d643c484ebe8b8ccfa029aa7377d133f2f53f"),
    "pylops": ("2.6.0", "97992be198c66a489c945c3feff31f6ed7d9117b"),
}

# These are scientific-acceptance blockers, not skips or expected successes.
# Authoring a direct-call test must not turn an illustrative fixture into truth.
ORACLE_BLOCKERS = {
    "GeoSeismicArrayBeamforming": "Independent calibrated finite-aperture/slowness and back-azimuth reference accounting for the fixed spectral window is not supplied.",
    "GeoSeismicTauPRays": "An independently tabulated iasp91 absolute travel-time/ray benchmark with source-depth and phase identity is missing; endpoint geometry alone is insufficient.",
    "GeoSeismicARPhasePick": "Known synthetic pulse centers do not establish expected AR-AIC pick times; a separately justified onset benchmark and uncertainty interval are missing.",
    "GeoSeismicProbabilisticNoise": "Absolute calibrated PSD reference including segment taper, octave smoothing, response and histogram binning is missing; a 6.0206 dB scaling check alone is insufficient.",
    "GeoSurfaceWaveSensitivity": "Independent heterogeneous modal derivatives with a confirmed matching finite-perturbation convention are missing; normalization or zero Vp sensitivity is insufficient.",
    "GeoDCResistivityInversion": "Independent heterogeneous DC inverse benchmark with the fixed mesh/boundary discretization, identifiable recovery target and uncertainty is missing.",
    "GeoIPChargeabilityInversion": "Independent nonzero heterogeneous IP benchmark with DC background, apparent-chargeability normalization and recovery uncertainty is missing.",
    "GeoFDEMConductivityInversion": "Independent complex secondary-H layered inverse benchmark is missing; the authoring fixture is not analytic truth.",
    "GeoTDEMConductivityInversion": "Independent absolute loop step-off dB/dt inverse benchmark is missing; the late-time power-law slope alone is insufficient.",
    "GeoGravityDensityInversion": "Independent nontrivial density-recovery benchmark with the stated regularization and nonuniqueness assessment is missing.",
    "GeoMagneticSusceptibilityInversion": "Independent nontrivial induced-susceptibility inverse benchmark and regularization/identifiability assessment are missing.",
    "GeoSeismicLeastSquaresMigration": "Independent amplitude-calibrated Kirchhoff inverse benchmark including interpolation, wavelet normalization and acquisition null space is missing.",
    "GeoSeismicReceiverDeghosting": "Independent finite-aperture ghost benchmark matching padding, taper and spectral null-space treatment is missing; an infinite plane-wave delay alone is insufficient.",
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setUpModule():
    """Refuse to import scientific dependencies outside the approved private CPU run."""
    if os.environ.get("E501_CPU_ACCEPTANCE") != "1" or sys.platform != "linux":
        raise RuntimeError("CPU acceptance is gated: parent must launch the private Linux runner")
    root = Path(os.environ["E501_GEO_ACCEPTANCE_ROOT"]).resolve()
    if not re.fullmatch(r"/data/wangjian/expansion501-20261026/geophysics-r[1-9][0-9]*", str(root)):
        raise RuntimeError("Unexpected acceptance revision root")
    if not Path(sys.prefix).resolve().is_relative_to(root):
        raise RuntimeError("Refusing accepted/base interpreter: a private revision venv is required")
    if not ROOT.is_relative_to(root):
        raise RuntimeError("Source must be in the private revision, not the deployed checkout")
    required = {
        "CUDA_VISIBLE_DEVICES": "-1", "NVIDIA_VISIBLE_DEVICES": "void",
        "HIP_VISIBLE_DEVICES": "-1", "ROCR_VISIBLE_DEVICES": "-1",
        "JAX_PLATFORMS": "cpu", "JAX_PLATFORM_NAME": "cpu", "NUMBA_DISABLE_CUDA": "1",
        "SYCL_DEVICE_FILTER": "cpu", "ZE_AFFINITY_MASK": "",
    }
    for key, value in required.items():
        if os.environ.get(key) != value:
            raise RuntimeError("CPU isolation environment mismatch: " + key)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS", "NUMBA_NUM_THREADS"):
        if os.environ.get(key) not in {"1", "2"}:
            raise RuntimeError("Thread budget not bounded to at most two: " + key)
    for key in ("HOME", "XDG_CACHE_HOME", "TMPDIR", "MPLCONFIGDIR", "NUMBA_CACHE_DIR"):
        if not Path(os.environ[key]).resolve().is_relative_to(root):
            raise RuntimeError("Non-private home/cache/temp: " + key)


def flatten(value):
    if isinstance(value, list):
        return [x for child in value for x in flatten(child)]
    return [value]


def shape(value):
    if not isinstance(value, list):
        return ()
    if not value:
        return (0,)
    tail = shape(value[0])
    if any(shape(v) != tail for v in value):
        return (len(value), "ragged")
    return (len(value),) + tail


def field(result, *patterns, expected_shape=None):
    """Fixed scientific field mapping; never select or execute a user callable.

    Ambiguous/missing mappings are explicit test-source failures, not silently
    accepted alternate scientific quantities. Shape is an additional condition.
    """
    values = result["values"]
    for pattern in patterns:
        matches = [(k, v) for k, v in values.items()
                   if re.search(pattern, k, re.I)
                   and (expected_shape is None or shape(v) == expected_shape)]
        if len(matches) == 1:
            return matches[0][1]
    raise AssertionError("ORACLE_FIELD_MAPPING_UNRESOLVED: patterns=" + repr(patterns)
                         + "; available=" + repr({k: shape(v) for k, v in values.items()}))


def only_shape(result, wanted):
    matches = [v for v in result["values"].values() if shape(v) == wanted]
    if len(matches) != 1:
        raise AssertionError("ORACLE_FIELD_MAPPING_UNRESOLVED: nonunique shape " + repr(wanted))
    return matches[0]


def replace_first_number(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, (int, float)) and not isinstance(child, bool):
                value[key] = float("nan")
                return True
            if isinstance(child, (dict, list)) and replace_first_number(child):
                return True
    elif isinstance(value, list):
        for i, child in enumerate(value):
            if isinstance(child, (int, float)) and not isinstance(child, bool):
                value[i] = float("nan")
                return True
            if isinstance(child, (dict, list)) and replace_first_number(child):
                return True
    return False


def zeros_like(value):
    return [zeros_like(v) for v in value] if isinstance(value, list) else 0.0


def physical_negative(tool, args):
    """One explicit physical/shape failure per operation, in addition to NaN/schema probes."""
    if tool in {"GeoSeismicInstrumentDeconvolution", "GeoSeismicProbabilisticNoise"}:
        args["epoch_end_s"] = args["record_start_s"]
    elif tool == "GeoEMLayeredBipoleResponse":
        args["interfaces_depth_m"] = [0, 0]
        args["horizontal_resistivity_ohm_m"] = [100, 100, 100]
        args["anisotropy_sqrt_rhov_rhoh"] = [1, 1, 1]
    elif tool == "GeoGravityTesseroid":
        cell = args["tesseroids_wesnbt"][0]
        cell[0], cell[1] = cell[1], cell[0]
    elif tool == "GeoPotentialEulerSourceLocation":
        args["gradient_enu_per_m"] = zeros_like(args["gradient_enu_per_m"])
    elif tool in {"GeoSurfaceWaveDispersion", "GeoSurfaceWaveEigenfunctions", "GeoSurfaceWaveSensitivity"}:
        args["layers_h_vp_vs_rho_si"][0][1] = args["layers_h_vp_vs_rho_si"][0][2] / 2
    elif tool == "GeoPotentialEquivalentSources":
        args["source_points_enu_m"][0][2] = max(p[2] for p in args["observations_enu_m"]) + 100
    elif tool == "GeoPotentialUpwardContinuation":
        args["height_displacement_m"] = -1
    elif tool == "GeoMagneticReductionToPole":
        args["field_inclination_deg"] = 0
    elif tool == "GeoDCFourElectrodeResponse":
        args["current_electrodes_enu_m"][1] = args["current_electrodes_enu_m"][0][:]
    elif tool == "GeoGravityNormalEllipsoid":
        args["geodetic_lon_lat_height"][0][1] = 91
    elif tool in {"GeoSeismicArrayBeamforming", "GeoSeismicARPhasePick"}:
        args["fmax_hz"] = args["fmin_hz"]
    elif tool == "GeoSeismicSTALTADetection":
        args["sta_samples"] = args["lta_samples"]
    elif tool == "GeoSeismicTemplateDetection":
        args["template_channel_time"] = zeros_like(args["template_channel_time"])
    elif tool == "GeoSeismicPolarization":
        args["displacement_zne_m"] = zeros_like(args["displacement_zne_m"])
    elif tool == "GeoSeismicTauPRays":
        args["distance_deg"] = 181
    elif tool == "GeoSeismicNMO":
        args["nmo_velocity_m_s"] = zeros_like(args["nmo_velocity_m_s"])
    elif tool in {"GeoSeismicComplexAttributes", "GeoSeismicMultidimensionalDeconvolution"}:
        args["dt_s"] = 0
    elif tool == "GeoSeismicWindowCoherence":
        args["inline_crossline_time_window"] = zeros_like(args["inline_crossline_time_window"])
    elif tool == "GeoPotentialEdgeAttributes":
        args["periodic_grid_acknowledged"] = False
    elif tool == "GeoSeismicArrayStrainRotation":
        args["vp_m_s"] = args["vs_m_s"] / 2
    elif tool == "GeoGravityBouguerSlab":
        args["crust_density_kg_m3"] = -1
    elif tool == "GeoCrustAiryMoho":
        args["mantle_density_kg_m3"] = args["crust_density_kg_m3"]
    elif tool == "GeoEMConductiveSphere":
        p = args["center_enu_m"][:]
        p[0] += args["radius_m"]
        args["observations_enu_m"] = [p]
    elif tool == "GeoMagneticWirePath":
        a, b = args["closed_loop_nodes_enu_m"][:2]
        args["observations_enu_m"] = [[(x + y) / 2 for x, y in zip(a, b)]]
    elif tool == "GeoSeismicWaveformTFMisfit":
        args["observed"] = zeros_like(args["observed"])
    elif tool == "GeoSeismicRadiationPattern":
        args["direction_enu"] = [[0, 0, 0]]
    elif tool in {"GeoDCResistivityInversion", "GeoIPChargeabilityInversion",
                  "GeoFDEMConductivityInversion", "GeoTDEMConductivityInversion",
                  "GeoGravityDensityInversion", "GeoMagneticSusceptibilityInversion"}:
        key = next(k for k in args if k.startswith("standard_deviation"))
        args[key] = zeros_like(args[key])
    elif tool == "GeoSeismicLeastSquaresMigration":
        args["time_s"][1] = args["time_s"][0]
    elif tool == "GeoSeismicPoststackImpedanceInversion":
        args["wavelet"] = [1, 1]
    elif tool == "GeoSeismicPrestackElasticInversion":
        args["angle_deg"][-1] = 90
    elif tool == "GeoSeismicReceiverDeghosting":
        args["receiver_depth_m"] = -1
    elif tool == "GeoSeismicUpDownWavefieldSeparation":
        args["pressure_receiver_time_pa"] = [[1.0 for _ in row]
                                              for row in args["pressure_receiver_time_pa"]]
    else:
        raise AssertionError("Missing physical negative for " + tool)
    return args


def love_two_layer(period, h=1000.0, v1=2000.0, v2=3500.0, rho1=2200.0, rho2=2700.0):
    """Independent SH continuity equation, not disba/CPS or copied kernel output.

    u1=A cos(qz), u2=B exp[-p(z-h)], mu1*q*sin(qh)=mu2*p*cos(qh).
    The fundamental root has 0<qh<pi/2. Group velocity follows implicit
    differentiation of this scalar boundary-condition equation.
    """
    w = 2 * math.pi / period
    mu1, mu2 = rho1 * v1 * v1, rho2 * v2 * v2
    low, high = v1 * (1 + 1e-12), v2 * (1 - 1e-12)
    quarter = math.pi / (2 * h)
    if (w / v1) ** 2 > quarter ** 2:
        high = min(high, w / math.sqrt((w / v1) ** 2 - quarter ** 2) * (1 - 1e-12))
    for _ in range(90):
        c = (low + high) / 2
        k = w / c
        q = math.sqrt((w / v1) ** 2 - k * k)
        p = math.sqrt(k * k - (w / v2) ** 2)
        f = mu1 * q * math.sin(q * h) - mu2 * p * math.cos(q * h)
        if f > 0:
            high = c
        else:
            low = c
    c = (low + high) / 2
    k = w / c
    q, p = math.sqrt((w / v1) ** 2 - k*k), math.sqrt(k*k - (w / v2) ** 2)
    fq = mu1 * (math.sin(q*h) + q*h*math.cos(q*h)) + mu2*p*h*math.sin(q*h)
    fp = -mu2 * math.cos(q*h)
    fw = fq*w/(v1*v1*q) - fp*w/(v2*v2*p)
    fk = -fq*k/q + fp*k/p
    return c, -fk/fw, math.cos(q*h)


class TestExpansion501Geophysics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = read_json(GROUP / "catalog-additions.json")
        cls.specs = {t["id"]: t for t in cls.catalog["tools"]}
        cls.examples = read_json(GROUP / "examples-additions.json")
        cls.implementation = importlib.import_module(MODULE)
        cls.contracts = importlib.import_module("geological_agent.geology.collection_contracts")
        cls.source_contracts = importlib.import_module("legacy.ToolsAgent.ToolsFuns.source_contracts")
        cls.Error = importlib.import_module("legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools").ScientificToolError
        cls.Validator = importlib.import_module("jsonschema").Draft202012Validator
        cls.staged = {t["id"]: t for t in cls.source_contracts.catalog()["tools"]}
        cls.results = {}

    def args(self, tool, **changes):
        args = copy.deepcopy(self.examples[tool])
        args.update(changes)
        args["input_source"] = SYNTHETIC
        return args

    def call(self, tool, args, as_json=False):
        before = copy.deepcopy(args)
        result = getattr(self.implementation, ENTRIES[tool])(
            json.dumps(args, allow_nan=False) if as_json else args)
        self.assertEqual(args, before, "Adapter mutated caller-owned input")
        self.check_result(tool, args, result)
        return result

    def check_result(self, tool, args, result):
        spec = self.specs[tool]
        self.Validator(spec["output_schema"]).validate(result)
        json.dumps(result, allow_nan=False)
        self.assertEqual(result["artifacts"], [])
        self.assertEqual(set(result["units"]), set(result["values"]))
        self.assertTrue(all(isinstance(u, str) and u for u in result["units"].values()))
        p = result["provenance"]
        self.assertEqual(p["tool"], tool)
        self.assertFalse(p["network_required"])
        self.assertEqual(p["output_sha256"], {})
        self.assertEqual(p["implementation_sha256"], sha(Path(self.implementation.__file__)))
        self.assertEqual(p["contract_sha256"], sha(Path(self.contracts.__file__)))
        self.assertEqual(p["reviewed_archive_commit"], spec["registration_metadata"]["source_commit"])
        self.assertEqual(p["upstream_url"], spec["metadata"]["upstream"]["url"])
        expected_hash = hashlib.sha256(json.dumps(args, sort_keys=True, ensure_ascii=True,
                                                 allow_nan=False).encode()).hexdigest()
        self.assertEqual(p["input_sha256"], expected_hash)
        upstream = spec["metadata"]["upstream"]
        required = [upstream["package"] + "==" + upstream["version"]] + upstream["requirements"]
        versions = {r.split("==")[0]: r.split("==")[1] for r in required}
        self.assertEqual(p["installed_versions"], versions)
        for package, version in versions.items():
            self.assertEqual(importlib.metadata.version(package), version)
        d = result["diagnostics"]
        self.assertIsInstance(d["convergence"], str)
        self.assertTrue(d["uncertainty"], "Uncertainty/identifiability limitations must not disappear")
        if d["iterations"] is not None:
            self.assertGreaterEqual(d["iterations"], 0)

    def near(self, actual, expected, rel=1e-8, absolute=1e-10):
        if isinstance(expected, list):
            self.assertIsInstance(actual, list)
            self.assertEqual(len(actual), len(expected))
            for a, e in zip(actual, expected):
                self.near(a, e, rel, absolute)
            return
        self.assertIsInstance(actual, (int, float))
        self.assertNotIsInstance(actual, bool)
        self.assertTrue(math.isfinite(actual))
        self.assertTrue(math.isclose(actual, expected, rel_tol=rel, abs_tol=absolute),
                        f"actual={actual!r}; independent={expected!r}; rel={rel}; abs={absolute}")

    def test_assignment_and_blocked_registration(self):
        self.assertEqual(len(ENTRIES), 42)
        self.assertEqual(set(self.specs), set(ENTRIES))
        self.assertEqual(set(self.examples), set(ENTRIES))
        statuses = read_json(GROUP / "adaptation-status.json")["operations"]
        self.assertEqual(len(statuses), 44)
        self.assertEqual({s["id"] for s in statuses}, set(ENTRIES) | BLOCKED_ADAPTERS)
        self.assertEqual({s["id"] for s in statuses if s["state"] == "blocked"}, BLOCKED_ADAPTERS)
        self.assertFalse(BLOCKED_ADAPTERS & set(self.staged))
        tree = ast.parse(Path(self.implementation.__file__).read_text(encoding="utf-8"))
        actual = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name)
                            and decorator.func.id == "operation" and decorator.args
                            and isinstance(decorator.args[0], ast.Constant)):
                        actual[decorator.args[0].value] = node.name
        self.assertEqual(actual, ENTRIES)

    def test_skill_availability_is_not_certification(self):
        skills = self.catalog["skills"]
        self.assertEqual(len(skills), 7)
        refs = []
        for skill in skills:
            refs.extend(skill["tool_references"])
            delivery = skill["delivery"]
            self.assertEqual(delivery["deployment_status"], "not_deployed")
            self.assertEqual(delivery["submission_status"], "not_submitted")
            self.assertEqual(delivery["model_workflow_validation"], "not_run")
            self.assertEqual(delivery["workflow_validation"], "not_run")
            self.assertEqual(delivery["receiving_lab_approval"], "pending")
            self.assertFalse(skill["metadata"]["formal_eligible"])
        self.assertEqual(sorted(refs), sorted(ENTRIES))

    def test_explicit_delivery_manifest_and_fixture_identity(self):
        paths = read_json(GROUP / "delivery-files.json")["files"]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertIn("geological_agent/geology/expansion501_geophysics.py", paths)
        for relative in paths:
            path = ROOT / relative
            self.assertFalse(path.is_symlink(), relative)
            self.assertTrue(path.resolve().is_relative_to(ROOT), relative)
            self.assertTrue(path.is_file(), relative)
        for tool in ENTRIES:
            relative = "assets/expansion501-geophysics/" + tool + ".json"
            self.assertIn(relative, paths)
            self.assertEqual(read_json(ROOT / relative), self.examples[tool])
            self.assertIn("SYNTHETIC", self.examples[tool]["input_source"])

    def test_reported_instrument_length_contract_boundary(self):
        # Reported during test authoring. Do not xfail, cap the input, or repair
        # the adapter here. The schema promises this input length is supported.
        tool = "GeoSeismicInstrumentDeconvolution"
        n = 8193
        args = self.args(tool, counts=[2*math.sin(2*math.pi*i/32) for i in range(n)],
                         dt_s=0.01, record_start_s=0, epoch_start_s=-1, epoch_end_s=200)
        self.Validator(self.specs[tool]["input_schema"]).validate(args)
        result = self.call(tool, args)
        self.assertEqual(len(field(result, "velocity")), n)

    def numeric(self, tool):
        if tool in ORACLE_BLOCKERS:
            self.fail("SCIENTIFIC_ORACLE_BLOCKED[" + tool + "]: " + ORACLE_BLOCKERS[tool])

        if tool == "GeoSeismicInstrumentDeconvolution":
            n, dt = 2048, 0.01
            truth = [math.sin(2*math.pi*i/32) for i in range(n)]
            args = self.args(tool, counts=[2*x for x in truth], dt_s=dt,
                             record_start_s=0, epoch_start_s=-1, epoch_end_s=100,
                             poles_rad_s=[], zeros_rad_s=[], normalization_factor=1,
                             sensitivity_counts_per_m_s=2, reference_frequency_hz=1,
                             prefilter_hz=[0.1, 0.2, 20, 25], water_level_db=60)
            y = field(self.call(tool, args), "velocity")
            self.assertEqual(len(y), n)
            # Fixed 0.5% interior RMS requirement for finite-window prefilter leakage.
            rms = math.sqrt(sum((y[i]-truth[i])**2 for i in range(512, 1536))/1024)
            self.assertLessEqual(rms, 0.005)
            gain = sum(y[i]*truth[i] for i in range(512, 1536))/sum(x*x for x in truth[512:1536])
            self.near(gain, 1.0, rel=0, absolute=0.005)
        elif tool == "GeoEMLayeredBipoleResponse":
            args = self.args(tool, interfaces_depth_m=[0], horizontal_resistivity_ohm_m=[100, 100],
                             anisotropy_sqrt_rhov_rhoh=[1, 1],
                             source_endpoints_end_m=[[0, 0, 10], [10, 0, 10]],
                             receivers_end_azimuth_dip=[[100, 0, 10, 0, 0]], frequency_hz=[0.001], current_a=1)
            result = self.call(tool, args)
            expected = 100/(4*math.pi)*(1/90**2 - 1/100**2)
            self.assertGreater(expected, 0)
            self.near(flatten(field(result, "electric_real"))[0], expected, rel=2e-5, absolute=1e-12)
            self.assertLess(abs(flatten(field(result, "electric_imag"))[0]), expected*2e-5)
        elif tool == "GeoGravityTesseroid":
            bottom, top, radius, density = 5900000, 6000000, 6500000, 1000
            cells = [[w, w+90, s, s+90, bottom, top] for w in (-180, -90, 0, 90) for s in (-90, 0)]
            args = self.args(tool, observations_lon_lat_radius=[[17, 23, radius]],
                             tesseroids_wesnbt=cells, density_contrast_kg_m3=[density]*8)
            result = self.call(tool, args)
            mass = 4*math.pi*density*(top**3-bottom**3)/3
            # Shell theorem: fixed accuracy requirements, not upstream-derived targets.
            self.near(field(result, "potential")[0], G*mass/radius, rel=1e-5, absolute=1e-8)
            self.near(field(result, "gravity")[0], G*mass/radius**2, rel=1e-5, absolute=1e-10)
        elif tool == "GeoPotentialEulerSourceLocation":
            xyz = [[x, y, z] for x in (-50, 25, 70) for y in (-40, 40) for z in (0, 20)]
            vals, grad = [], []
            for x, y, z in xyz:
                dx, dy, dz = x-10, y+20, z+100
                r2 = dx*dx+dy*dy+dz*dz
                vals.append(2+1e5*dz/r2**1.5)
                grad.append([-3e5*dz*dx/r2**2.5, -3e5*dz*dy/r2**2.5,
                             1e5*(r2-3*dz*dz)/r2**2.5])
            result = self.call(tool, self.args(tool, observations_enu_m=xyz, field=vals,
                               gradient_enu_per_m=grad, structural_index=2, field_unit="mGal"))
            self.near(field(result, "source"), [10, -20, -100], rel=1e-8, absolute=1e-7)
            self.near(field(result, "base"), 2, absolute=1e-8)
        elif tool == "GeoSurfaceWaveDispersion":
            args = self.args(tool, layers_h_vp_vs_rho_si=[[1000, 4000, 2000, 2200], [0, 6000, 3500, 2700]],
                             wave="love", mode=0, period_s=[1.0])
            result = self.call(tool, args)
            phase, group, _ = love_two_layer(1.0)
            self.near(field(result, "phase")[0], phase, rel=0, absolute=0.1)
            # Group speed uses a finite-period derivative upstream; retain the fixed 0.1% requirement.
            self.near(field(result, "group")[0], group, rel=0.001, absolute=0.1)
        elif tool == "GeoPotentialEquivalentSources":
            obs = [[-50, 0, 0], [50, 0, 0], [0, 50, 0]]
            result = self.call(tool, self.args(tool, observations_enu_m=obs,
                               source_points_enu_m=[[0, 0, -100]], prediction_points_enu_m=[[0, 0, 0]],
                               field=[200/math.sqrt(12500)]*3, standard_deviation=[1]*3,
                               damping=0, field_unit="mGal"))
            self.near(field(result, "predict")[0], 2.0, absolute=1e-8)
        elif tool in {"GeoPotentialUpwardContinuation", "GeoMagneticReductionToPole", "GeoPotentialEdgeAttributes"}:
            n, dx = 16, 10
            grid = [[math.cos(2*math.pi*j/n) for j in range(n)] for _ in range(n)]
            args = self.args(tool, easting_m=[dx*i for i in range(n)], northing_m=[dx*i for i in range(n)],
                             field_grid=grid, field_unit="nT", periodic_grid_acknowledged=True)
            if tool == "GeoPotentialUpwardContinuation":
                args["height_displacement_m"] = 20
                expected = [[v*math.exp(-2*math.pi*20/(n*dx)) for v in row] for row in grid]
                self.near(only_shape(self.call(tool, args), (n, n)), expected, absolute=1e-9)
            elif tool == "GeoMagneticReductionToPole":
                args.update(field_inclination_deg=90, field_declination_deg=0,
                            magnetization_inclination_deg=90, magnetization_declination_deg=0)
                self.near(only_shape(self.call(tool, args), (n, n)), grid, absolute=1e-9)
            else:
                args["gradient_floor_per_m"] = 1e-12
                result = self.call(tool, args)
                total = field(result, "total.*gradient", "analytic.*signal", expected_shape=(n, n))
                self.near(total, [[2*math.pi/(n*dx)]*n for _ in range(n)], absolute=1e-9)
        elif tool == "GeoDCFourElectrodeResponse":
            result = self.call(tool, self.args(tool, current_electrodes_enu_m=[[-15, 0, 0], [15, 0, 0]],
                               potential_pairs_enu_m=[[[-5, 0, 0], [5, 0, 0]]], resistivity_ohm_m=100, current_a=1))
            self.near(flatten(field(result, "voltage", "potential_difference"))[0], 100/(20*math.pi), absolute=1e-10)
        elif tool == "GeoGravityNormalEllipsoid":
            result = self.call(tool, self.args(tool, geodetic_lon_lat_height=[[0, 0, 0], [0, 90, 0]]))
            self.near(field(result, "gravity"), [9.78032533590406, 9.8321849378634], rel=0, absolute=2e-9)
        elif tool == "GeoSeismicSTALTADetection":
            x = [(-1)**i * (4 if 80 <= i < 100 else 1) for i in range(160)]
            result = self.call(tool, self.args(tool, amplitude=x, sta_samples=5, lta_samples=20, on_ratio=2, off_ratio=1.2))
            expected = [0.0]*19 + [(sum(v*v for v in x[i-4:i+1])/5)/(sum(v*v for v in x[i-19:i+1])/20)
                                   for i in range(19, len(x))]
            self.near(field(result, "characteristic", "sta_lta", "ratio", expected_shape=(160,)), expected,
                      rel=1e-10, absolute=1e-10)
        elif tool == "GeoSeismicTemplateDetection":
            template = [math.sin(2*math.pi*i/16)*math.sin(math.pi*i/63)**2 for i in range(64)]
            data = [0.0]*512
            data[100:164] = [2*v for v in template]
            result = self.call(tool, self.args(tool, data_channel_time=[data], template_channel_time=[template],
                               dt_s=0.01, minimum_similarity=0.99, minimum_separation_s=1))
            # A copy shifted exactly 100 samples has normalized correlation one.
            similarity = field(result, "similarit", "correlation")
            numeric = [v for v in flatten(similarity) if isinstance(v, (int, float))]
            self.assertTrue(numeric, "Template similarity output must be numerically inspectable")
            self.near(max(numeric), 1.0, absolute=1e-9)
        elif tool == "GeoSeismicPolarization":
            x = [math.sin(2*math.pi*i/32) for i in range(256)]
            result = self.call(tool, self.args(tool, displacement_zne_m=[[3*v for v in x], [0.0]*256, [4*v for v in x]], dt_s=0.01))
            self.near(field(result, "rectilinearity"), 1.0, absolute=1e-8)
            self.near(field(result, "incidence"), math.degrees(math.atan2(4, 3)), absolute=1e-7)
        elif tool == "GeoSeismicNMO":
            n, dt = 128, 0.004
            args = self.args(tool, cmp_time_offset=[[(i*dt)**2]*2 for i in range(n)], offset_m=[0, 100],
                             nmo_velocity_m_s=[2000]*n, dt_s=dt)
            result = self.call(tool, args)
            corrected = field(result, "correct", "nmo", "gather", expected_shape=(n, 2))
            self.near(corrected[50], [0.04, 0.0425], rel=0, absolute=1e-8)
        elif tool == "GeoSeismicComplexAttributes":
            n, dt, k = 256, 0.01, 8
            args = self.args(tool, amplitude=[2*math.cos(2*math.pi*k*i/n) for i in range(n)], dt_s=dt, amplitude_floor=1e-8)
            result = self.call(tool, args)
            envelope = field(result, "envelope", "amplitude")
            self.near(envelope[16:-16], [2.0]*(n-32), absolute=1e-8)
            # SO central difference, not a continuous derivative: sin(omega*dt)/(2*pi*dt).
            expected = math.sin(2*math.pi*k/n)/(2*math.pi*dt)
            freq = result["values"]["interval_frequency_hz"]
            valid = result["values"]["frequency_valid"]
            self.assertEqual(len(freq), n-1)
            self.assertEqual(valid, [True]*(n-1))
            self.assertTrue(all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                and math.isfinite(v) for v in freq))
            unsupported = self.call(tool, self.args(tool, amplitude=args["amplitude"],
                                                   dt_s=dt, amplitude_floor=3.0))
            self.assertEqual(unsupported["values"]["frequency_valid"], [False]*(n-1))
            self.assertEqual(unsupported["values"]["interval_frequency_hz"], [None]*(n-1))
            self.assertEqual(unsupported["values"]["phase_rad"], [None]*n)
            # Preserve the r1 numeric target and tolerance; only fix interval mapping.
            self.near(freq[16:-16], [expected]*(n-33), absolute=1e-7)
        elif tool == "GeoSeismicWindowCoherence":
            trace = [1, -2, 3, -4, 5, -4, 3, -2, 1]
            args = self.args(tool, inline_crossline_time_window=[[trace[:] for _ in range(3)] for _ in range(3)])
            self.near(field(self.call(tool, args), "coherence", "semblance"), 1.0, absolute=1e-12)
        elif tool == "GeoSeismicArrayStrainRotation":
            stations = [[0, 0, 0], [100, 0, 0], [0, 100, 0], [100, 100, 0]]
            displacement = [[[1e-5*(1+0.01*i)*x, 2e-5*(1+0.01*i)*y, 0] for x, y, _ in stations] for i in range(64)]
            result = self.call(tool, self.args(tool, station_enu_m=stations, displacement_time_station_enu_m=displacement,
                               vp_m_s=3000, vs_m_s=1500, displacement_error_m=1e-7))
            strain = field(result, "strain", expected_shape=(64, 3, 3))
            for i, tensor in enumerate(strain):
                a = 1+0.01*i
                self.near(tensor, [[1e-5*a, 0, 0], [0, 2e-5*a, 0], [0, 0, -1.5e-5*a]],
                          rel=1e-7, absolute=1e-12)
        elif tool == "GeoGravityBouguerSlab":
            result = self.call(tool, self.args(tool, topography_m=[100, -100], crust_density_kg_m3=2670, water_density_kg_m3=1040))
            self.near(field(result, "gravity", "bouguer", "correction"),
                      [2*math.pi*G*2670*100, -2*math.pi*G*(2670-1040)*100], absolute=1e-12)
        elif tool == "GeoCrustAiryMoho":
            layer_schema = self.specs[tool]["input_schema"]["properties"]["overlying_layers"]
            empty = {} if layer_schema["type"] == "object" else []
            args = self.args(tool, basement_height_m=[1000], overlying_layers=empty,
                             crust_density_kg_m3=2800, mantle_density_kg_m3=3300, reference_depth_m=30000)
            self.near(flatten(field(self.call(tool, args), "moho", "depth"))[0], 35600, absolute=1e-8)
        elif tool == "GeoEMConductiveSphere":
            result = self.call(tool, self.args(tool, observations_enu_m=[[5, 0, 0], [20, 0, 0]], center_enu_m=[0, 0, 0],
                               radius_m=10, sphere_conductivity_s_m=0.1, background_conductivity_s_m=0.01,
                               primary_electric_enu_v_m=[1, 0, 0]))
            self.near(field(result, "^total_electric_v_m$", expected_shape=(2, 3)), [[0.25, 0, 0], [1.1875, 0, 0]], absolute=1e-10)
            self.near(field(result, "current", expected_shape=(2, 3)), [[0.025, 0, 0], [0.011875, 0, 0]], absolute=1e-11)
        elif tool == "GeoMagneticWirePath":
            result = self.call(tool, self.args(tool, closed_loop_nodes_enu_m=[[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0], [-1, -1, 0]],
                               observations_enu_m=[[0, 0, 0]], current_a=1))
            # Four finite straight wires, each subtending +/-45 degrees at the center.
            # For half-side a=1 m: B=sqrt(2)*mu0*I/(pi*a). r1 had an extra factor 2.
            expected = math.sqrt(2)*(4*math.pi*1e-7)/math.pi
            self.near(only_shape(result, (1, 3))[0], [0, 0, expected], rel=1e-8, absolute=1e-14)
        elif tool == "GeoSeismicWaveformTFMisfit":
            observed = [math.sin(2*math.pi*i/16)*math.sin(math.pi*i/255)**2 for i in range(256)]
            result = self.call(tool, self.args(tool, observed=observed, synthetic=[2*v for v in observed],
                               dt_s=0.01, fmin_hz=2, fmax_hz=20))
            envelope = [v for v in flatten(field(result, "envelope")) if v is not None]
            phase = [v for v in flatten(field(result, "phase")) if v is not None]
            self.near(max(envelope), 1.0, absolute=1e-8)
            self.assertTrue(phase)
            self.assertLessEqual(max(abs(v) for v in phase), 1e-8)
        elif tool == "GeoSeismicRadiationPattern":
            result = self.call(tool, self.args(tool, moment_tensor_enu_nm=[1, 0, -1, 0, 0, 0],
                               direction_enu=[[1, 0, 0], [1/math.sqrt(2), 0, 1/math.sqrt(2)]]))
            self.near(field(result, "^p_", expected_shape=(2, 3)), [[1/math.sqrt(2), 0, 0], [0, 0, 0]], absolute=1e-10)
            self.near(field(result, "^s_", expected_shape=(2, 3)), [[0, 0, 0], [0.5, 0, -0.5]], absolute=1e-10)
        elif tool == "GeoSurfaceWaveEigenfunctions":
            args = self.args(tool, layers_h_vp_vs_rho_si=[[1000, 4000, 2000, 2200], [0, 6000, 3500, 2700]], wave="love", mode=0, period_s=1.0)
            result = self.call(tool, args)
            _, _, expected_ratio = love_two_layer(1.0)
            u = flatten(field(result, "displacement", "eigenfunction"))
            self.assertEqual(len(u), 2)
            self.assertGreater(abs(u[0]), 0.1)
            self.near(u[1]/u[0], expected_ratio, rel=1e-4, absolute=1e-5)
        elif tool == "GeoSeismicPoststackImpedanceInversion":
            n = 65
            log_delta = [0.1*math.sin(2*math.pi*i/(n-1)) for i in range(n)]
            data = [0.0] + [0.25*(log_delta[i+1]-log_delta[i-1]) for i in range(1, n-1)] + [0.0]
            result = self.call(tool, self.args(tool, poststack_trace=data, background_impedance_kg_m2_s=[6000000]*n,
                               wavelet=[0, 1, 0], damping=0, max_iterations=50))
            self.near(field(result, "impedance"), [6000000*math.exp(v) for v in log_delta], rel=1e-6, absolute=0.1)
        elif tool == "GeoSeismicPrestackElasticInversion":
            n, angles, bg = 65, [0, 10, 20, 30], [3000, 1500, 2200]
            logs = [[a*math.sin(2*math.pi*i/(n-1)) for a in (0.05, 0.02, 0.03)] for i in range(n)]
            data = []
            for i in range(n):
                derivative = [0, 0, 0] if i in (0, n-1) else [(logs[i+1][j]-logs[i-1][j])/2 for j in range(3)]
                row = []
                for angle in angles:
                    t = math.radians(angle)
                    s2 = math.sin(t)**2
                    coefficients = [0.5/math.cos(t)**2, -s2, 0.5*(1-s2)]
                    row.append(sum(a*b for a, b in zip(coefficients, derivative)))
                data.append(row)
            result = self.call(tool, self.args(tool, angle_gather_time_angle=data, angle_deg=angles,
                               background_vp_vs_rho_si=[bg[:] for _ in range(n)], wavelet=[0, 1, 0], damping=0, max_iterations=50))
            expected = [[bg[j]*math.exp(logs[i][j]) for j in range(3)] for i in range(n)]
            candidates = [v for v in result["values"].values() if shape(v) == (n, 3)]
            if len(candidates) == 1:
                self.near(candidates[0], expected, rel=1e-5, absolute=1e-3)
            else:
                for j, pattern in enumerate(("vp", "vs", "density|rho")):
                    self.near(field(result, pattern, expected_shape=(n,)), [r[j] for r in expected], rel=1e-5, absolute=1e-3)
        elif tool == "GeoSeismicUpDownWavefieldSeparation":
            n, nr, rho, c = 128, 16, 1000, 1500
            p = [[math.sin(2*math.pi*i/32) for i in range(n)] for _ in range(nr)]
            result = self.call(tool, self.args(tool, pressure_receiver_time_pa=p,
                               vertical_velocity_receiver_time_m_s=[[x/(rho*c) for x in row] for row in p],
                               dt_s=0.01, receiver_spacing_m=10, water_velocity_m_s=c, water_density_kg_m3=rho))
            self.near(field(result, "down", expected_shape=(nr, n)), p, absolute=1e-8)
            self.near(field(result, "up", expected_shape=(nr, n)), [[0.0]*n for _ in range(nr)], absolute=1e-8)
        elif tool == "GeoSeismicMultidimensionalDeconvolution":
            n, dt, dr = 32, 0.01, 1
            kernel = [[[1/(dt*dr) if s == r and t == 0 else 0.0 for t in range(n)] for r in range(2)] for s in range(2)]
            data = [[math.sin(2*math.pi*(s+2)*i/n) for i in range(n)] for s in range(2)]
            result = self.call(tool, self.args(tool, kernel_source_receiver_time_per_m_s=kernel,
                               data_source_time_pa=data, dt_s=dt, receiver_spacing_m=dr, damping=0, max_iterations=50))
            # dt*dr weighted temporal delta is the identity convolution. Negative time is zero.
            recovered = only_shape(result, (2, 2*n-1))
            self.near(recovered, [[0.0]*(n-1)+row for row in data], rel=1e-7, absolute=1e-7)
        else:
            self.fail("SCIENTIFIC_ORACLE_BLOCKED: no independent case authored for " + tool)


def registration_case(tool):
    def test(self):
        spec = self.specs[tool]
        self.assertIn(tool, self.staged, "Parent must stage the real catalog; no test overlay is allowed")
        for key in ("input_schema", "output_schema", "source_interface", "metadata"):
            self.assertEqual(self.staged[tool][key], spec[key], key)
        for key in ("input_schema", "output_schema"):
            schema = spec[key]
            self.Validator.check_schema(schema)
            self.assertEqual(schema["type"], "object")
            self.assertIs(schema["additionalProperties"], False)
        self.assertTrue({"units", "artifacts", "provenance"} <= set(spec["output_schema"]["required"]))
        interface = spec["source_interface"]
        self.assertEqual(interface["kind"], "expansion501_geophysics")
        self.assertEqual(interface["entrypoint"]["callable"], MODULE + ":" + ENTRIES[tool])
        self.assertEqual(interface["entrypoint"]["argument_parameter"], "args")
        self.assertEqual(interface["entrypoint"]["bound_arguments"], {})
        upstream = spec["metadata"]["upstream"]
        package = upstream["package"].lower().replace("_", "-")
        version, commit = PINS[package]
        self.assertEqual(upstream["version"], version)
        self.assertEqual(spec["registration_metadata"]["source_commit"], commit)
        self.assertRegex(commit, r"^[0-9a-f]{40}$")
        self.assertTrue(spec["registration_metadata"]["license"])
        self.assertTrue(upstream["requirements"])
        for requirement in upstream["requirements"]:
            self.assertRegex(requirement, r"^[A-Za-z0-9_.-]+==[A-Za-z0-9_.+-]+$")
        self.Validator(spec["input_schema"]).validate(self.examples[tool])
    return test


def direct_case(tool, serialized):
    def test(self):
        args = copy.deepcopy(self.examples[tool])
        result = self.call(tool, args, as_json=serialized)
        if serialized:
            if tool not in self.results:
                self.results[tool] = self.call(tool, args)
            self.assertEqual(result, self.results[tool], "JSON and dict contract results differ")
        else:
            self.results[tool] = result
    return test


def negative_case(tool):
    def test(self):
        fn = getattr(self.implementation, ENTRIES[tool])
        variants = [self.args(tool, arbitrary_function="os.system"),
                    physical_negative(tool, self.args(tool))]
        nonfinite = self.args(tool)
        self.assertTrue(replace_first_number(nonfinite))
        variants.append(nonfinite)
        for label, args in zip(("arbitrary_dispatch", "physical_domain", "nonfinite"), variants):
            with self.subTest(constraint=label):
                with self.assertRaises(self.Error) as caught:
                    fn(args)
                self.assertIn(caught.exception.code, {"invalid_arguments", "unsupported_conditions"})
    return test


def numeric_case(tool):
    def test(self):
        self.numeric(tool)
    return test


for _tool in ENTRIES:
    for _category, _factory in (
        ("source_registration", registration_case),
        ("direct_dict", lambda t: direct_case(t, False)),
        ("direct_json", lambda t: direct_case(t, True)),
        ("negative", negative_case),
        ("numeric", numeric_case),
    ):
        _fn = _factory(_tool)
        _fn.tool_id = _tool
        _fn.category = _category
        setattr(TestExpansion501Geophysics, "test_" + _category + "_" + _tool, _fn)


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = []

    def record(self, test, state, detail=""):
        method = getattr(test, getattr(test, "_testMethodName", ""), None)
        self.rows.append({"test": test.id(), "tool_id": getattr(method, "tool_id", None),
                          "category": getattr(method, "category", "contribution"),
                          "state": state, "detail": detail})

    def addSuccess(self, test):
        super().addSuccess(test)
        self.record(test, "passed_case_only_not_certification")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        message = self._exc_info_to_string(err, test)
        self.record(test, "blocked" if "SCIENTIFIC_ORACLE_BLOCKED" in message else "failed", message)

    def addError(self, test, err):
        super().addError(test, err)
        self.record(test, "error", self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.record(test, "skipped_not_passed", reason)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.record(test, "failed_subtest", str(subtest) + "\n" + self._exc_info_to_string(err, test))


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult)
    program = unittest.main(testRunner=runner, exit=False)
    result = program.result
    target = os.environ.get("E501_GEO_RESULTS_JSON")
    if target:
        path = Path(target)
        root = Path(os.environ["E501_GEO_ACCEPTANCE_ROOT"]).resolve()
        if not path.resolve().is_relative_to(root):
            raise RuntimeError("Evidence destination escaped private acceptance root")
        receipt = {"status": "cpu_test_cases_completed_not_certification", "tests_run": result.testsRun,
                   "successful_suite": result.wasSuccessful(), "rows": result.rows,
                   "native_blocked_not_registered": sorted(BLOCKED_ADAPTERS),
                   "independent_oracle_blockers": ORACLE_BLOCKERS,
                   "test_source_sha256": sha(Path(__file__)),
                   "adapter_source_sha256": sha(ROOT / "geological_agent/geology/expansion501_geophysics.py"),
                   "deployment": "not_run", "model_workflow": "not_run", "gpu": "not_used"}
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(receipt, handle, indent=2, allow_nan=False)
            handle.write("\n")
    sys.exit(0 if result.wasSuccessful() else 1)

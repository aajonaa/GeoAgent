"""Fresh, CPU-only remote acceptance sources; never run against the local checkout.

Run only after parent provisions an exact Python interpreter and a manifest-only
source copy below /data/wangjian/expansion501-20261026/remote-r1.
No installs, SSH, GPU initialization, registry/service edits or source repairs.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import unittest
from unittest import mock
import uuid

RUN_ROOT = Path("/data/wangjian/expansion501-20261026/remote-r1")
SOURCE_ROOT = Path(__file__).resolve().parents[5]
GROUP = "catalog/source_delivery/expansion501-20261026/groups/remote"
ASSETS = "assets/expansion501-remote"
IMPL = "geological_agent/geology/expansion501_remote.py"
CONTRACT = "geological_agent/geology/collection_contracts.py"
ENTRYPOINTS = {
    "GeoSARCoherentChange": "coherent_change",
    "GeoRemotePhaseUnwrap": "phase_unwrap",
    "GeoRemoteBrightnessTemperature": "brightness_temperature",
    "GeoRemoteGaussianClassify": "gaussian_classify",
    "GeoRemoteEndmemberDiscovery": "endmember_discovery",
    "GeoRemoteClassSeparability": "class_separability",
    "GeoRemoteDenseOpticalFlow": "dense_optical_flow",
    "GeoRemoteProjectiveTiePoints": "projective_tie_points",
    "GeoRemoteTemplateLocate": "template_locate",
    "GeoRemoteScaleSpaceBlobs": "scale_space_blobs",
    "GeoRemoteHoughLineEvidence": "hough_line_evidence",
    "GeoRemoteWaveletPyramid": "wavelet_pyramid",
    "GeoSARDopplerDeskew": "doppler_deskew",
    "GeoSARSubaperture": "subaperture",
    "GeoRemoteTOAReflectance": "toa_reflectance",
    "GeoRemotePansharpenFusion": "pansharpen_fusion",
    "GeoRemoteMADChange": "mad_change",
    "GeoSARPolarimetricHAlpha": "polarimetric_halpha",
    "GeoSARPolarizationSynthesis": "polarization_synthesis",
    "GeoInSARNetworkDisplacement": "network_displacement",
    "GeoInSARResidualDEM": "residual_dem",
    "GeoInSARIonosphericDelay": "ionospheric_delay",
    "GeoInSARPlateFrameCorrection": "plate_frame_correction",
    "GeoInSARAscDescDecomposition": "asc_desc_decomposition",
    "GeoInSAREnvisatOscillatorCorrection": "envisat_oscillator_correction",
    "GeoInSARCoherenceNetworkSelection": "coherence_network_selection",
}
# No scientific imports occur before remote root, CPU and source-hash checks.
SESSION = None
SPECS = {}
EXAMPLES = {}
HASHES = {}
ADAPTER = None
LEGACY = None
ScientificToolError = None


def _inside(path, root=RUN_ROOT):
    p = Path(path)
    if not p.is_absolute() or not p.resolve().is_relative_to(root.resolve()):
        raise RuntimeError("Path outside fresh remote-r1 workspace: " + str(p))
    for q in (p, *p.parents):
        if q.is_symlink():
            raise RuntimeError("Symbolic links are not accepted: " + str(q))
        if q == root:
            break
    return p


def _guard():
    if os.name != "posix" or not RUN_ROOT.is_dir():
        raise RuntimeError("Acceptance is authorized only inside the fresh Linux remote-r1 root")
    _inside(SOURCE_ROOT)
    if os.environ.get("CUDA_VISIBLE_DEVICES") not in ("", "-1"):
        raise RuntimeError("Explicitly hide all GPUs before starting Python")
    if os.environ.get("PYTHONNOUSERSITE") != "1":
        raise RuntimeError("PYTHONNOUSERSITE=1 is required")
    for key in ("HOME", "XDG_CACHE_HOME", "TMPDIR", "TMP", "TEMP",
                "PYTHONPYCACHEPREFIX", "MPLCONFIGDIR", "NUMBA_CACHE_DIR"):
        value = os.environ.get(key)
        if not value:
            raise RuntimeError("Missing isolated path: " + key)
        _inside(value)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        if os.environ.get(key) not in ("1", "2"):
            raise RuntimeError("Thread bound must be 1 or 2: " + key)


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(262144), b""):
            h.update(block)
    return h.hexdigest()


def _source_identity():
    # Frozen hashes must come from parent staging, not be derived as an oracle here.
    lock_name = os.environ.get("EXPANSION501_REMOTE_SOURCE_HASHES")
    if not lock_name:
        raise RuntimeError("Require parent-frozen source hash manifest")
    lock = _read_json(_inside(lock_name))
    hashes = lock.get("files")
    if not isinstance(hashes, dict) or not hashes:
        raise RuntimeError("Source hash manifest must be {files:{relative_path:sha256}}")
    delivery = _read_json(SOURCE_ROOT / GROUP / "delivery-files.json")["files"]
    required = set(delivery) | {IMPL, CONTRACT, "legacy/ToolsAgent/ToolsFuns/source_contracts.py"}
    if not required <= set(hashes):
        raise RuntimeError("Hash manifest omits delivery/shared-contract sources")
    for relative in required:
        if not isinstance(relative, str) or "\\" in relative or ":" in relative:
            raise RuntimeError("Invalid source path")
        if any(part in ("", ".", "..") for part in relative.split("/")):
            raise RuntimeError("Unsafe source path")
        path = _inside(SOURCE_ROOT / relative)
        expected = hashes[relative]
        if not re.fullmatch(r"[0-9a-f]{64}", str(expected)):
            raise RuntimeError("Invalid expected SHA256")
        if not path.is_file() or path.stat().st_size > 32 * 1024 * 1024 or _sha(path) != expected:
            raise RuntimeError("Source snapshot mismatch: " + relative)
    return hashes


def setUpModule():
    global SESSION, SPECS, EXAMPLES, HASHES, ADAPTER, LEGACY, ScientificToolError
    _guard()
    HASHES = _source_identity()
    SESSION = _inside(RUN_ROOT / "results" / ("acceptance-" + uuid.uuid4().hex))
    SESSION.mkdir(parents=True, exist_ok=False)
    catalog = _read_json(SOURCE_ROOT / GROUP / "catalog-additions.json")
    SPECS = {s["id"]: s for s in catalog["tools"]}
    if len(SPECS) != len(catalog["tools"]) or set(SPECS) != set(ENTRYPOINTS):
        raise RuntimeError("Private catalog must contain exactly the 26 real remote adapters")
    EXAMPLES = {tool: _read_json(SOURCE_ROOT / ASSETS / (tool + ".json")) for tool in ENTRYPOINTS}
    sys.path.insert(0, str(SOURCE_ROOT))
    LEGACY = importlib.import_module("legacy.ToolsAgent.ToolsFuns.source_contracts")
    ADAPTER = importlib.import_module("geological_agent.geology.expansion501_remote")
    errors = importlib.import_module("legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools")
    ScientificToolError = errors.ScientificToolError
    for module in (LEGACY, ADAPTER, errors):
        if not Path(module.__file__).resolve().is_relative_to(SOURCE_ROOT):
            raise RuntimeError("Imported code outside the private source copy")
    # Redirect only the in-process catalog ROOT of this private test process.
    # No shared file, service or accepted registry is written.
    private = SESSION / "private-catalog"
    (private / "catalog").mkdir(parents=True)
    (private / "catalog" / "registry.json").write_text(
        json.dumps(catalog, allow_nan=False), encoding="utf-8")
    LEGACY.ROOT = private
    LEGACY.catalog.cache_clear()


def tearDownModule():
    # Preserve every failure, artifact and private catalog for independent review.
    if LEGACY is not None:
        LEGACY.catalog.cache_clear()


class RemoteCases(unittest.TestCase):
    def setUp(self):
        self.root = SESSION / self._testMethodName
        self.root.mkdir(exist_ok=False)

    def _args(self, tool):
        return copy.deepcopy(EXAMPLES[tool])

    def _call(self, tool, args=None, as_json=False, label="out"):
        value = self._args(tool) if args is None else copy.deepcopy(args)
        frozen = copy.deepcopy(value)
        function = getattr(ADAPTER, ENTRYPOINTS[tool])
        result = function(json.dumps(value, allow_nan=False) if as_json else value,
                          output_dir=self.root / label)
        self.assertEqual(value, frozen, "decorated call mutated supplied arguments")
        self._artifact_contract(tool, frozen, result, self.root / label)
        return result, self.root / label

    def _artifact_contract(self, tool, args, result, root):
        import numpy as np
        import rasterio
        from jsonschema import Draft202012Validator
        Draft202012Validator(SPECS[tool]["output_schema"]).validate(result)
        json.dumps(result, allow_nan=False)
        p = result["provenance"]
        self.assertEqual(p["tool"], tool)
        self.assertIs(p["network_required"], False)
        self.assertEqual(p["implementation_sha256"], HASHES[IMPL])
        self.assertEqual(p["contract_sha256"], HASHES[CONTRACT])
        self.assertEqual(p["reviewed_archive_commit"],
                         SPECS[tool]["registration_metadata"]["source_commit"])
        canonical = json.dumps(args, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()
        self.assertEqual(p["input_sha256"], hashlib.sha256(canonical).hexdigest())
        paths = [Path(v) for v in result["artifacts"]]
        self.assertTrue(paths)
        self.assertEqual(len(paths), len(set(paths)))
        expected_paths = {}
        for path in paths:
            self.assertTrue(path.resolve().is_relative_to(root.resolve()))
            self.assertFalse(path.is_symlink())
            self.assertTrue(path.is_file())
            self.assertLessEqual(path.stat().st_size, 128 * 1024 * 1024)
            expected_paths[path.relative_to(root).as_posix()] = _sha(path)
            if path.suffix.lower() == ".csv":
                with path.open(newline="", encoding="utf-8") as f:
                    rows = list(csv.reader(f))
                self.assertTrue(rows and rows[0])
                self.assertTrue(all(len(row) == len(rows[0]) for row in rows[1:]))
        self.assertEqual(p["output_sha256"], expected_paths)
        self.assertEqual(set(paths), {x for x in root.rglob("*") if x.is_file()})
        if result["kind"] == "raster":
            with rasterio.open(root / "result.tif") as ds:
                data = ds.read()
                masks = ds.read_masks() != 0
                self.assertEqual(ds.driver, "GTiff")
                self.assertEqual(ds.crs, rasterio.crs.CRS.from_user_input(args["grid"]["crs"]))
                self.assertEqual(tuple(ds.transform)[:6], tuple(args["grid"]["affine"]))
                self.assertEqual(ds.nodata, args["grid"]["nodata"])
                self.assertEqual(list(data.shape), result["shape"])
                self.assertTrue(np.isfinite(data[masks]).all())
                self.assertTrue(np.all(masks == masks[0]))
                self.assertEqual(int(masks[0].sum()), result["valid_count"])
                expected = np.asarray(args["grid"]["mask"], dtype=bool).copy()
                border = args["window_size"] // 2 if tool == "GeoSARCoherentChange" else 4 if tool == "GeoSARPolarimetricHAlpha" else 0
                if border:
                    expected[:border] = False
                    expected[-border:] = False
                    expected[:, :border] = False
                    expected[:, -border:] = False
                if tool == "GeoRemoteTemplateLocate":
                    expected = expected[:ds.height, :ds.width]
                np.testing.assert_array_equal(masks[0], expected)
                for b, stat in enumerate(result["statistics"]):
                    self.assertEqual(ds.tags(b + 1)["units"], stat["unit"])

    def _raster(self, root, name="result.tif"):
        import rasterio
        with rasterio.open(root / name) as ds:
            return ds.read(), ds.read_masks()[0] != 0

    def _rows(self, root, name):
        with (root / name).open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def _oracle(self, tool, root):
        """Independent analytic expectations, never computed with upstream kernels."""
        import numpy as np
        if (root / "result.tif").exists():
            x, valid = self._raster(root)
        if tool == "GeoSARCoherentChange":
            np.testing.assert_allclose(x[0, valid], 1, atol=1e-8, rtol=0)
            np.testing.assert_allclose(x[1, valid], math.pi / 3, atol=1e-8, rtol=0)
            self.assertEqual(int(valid.sum()), 35)
        elif tool == "GeoRemotePhaseUnwrap":
            self.assertAlmostEqual(float(x[0, 0, 7] - x[0, 0, 0]), 7 * math.pi / 2, delta=1e-8)
        elif tool == "GeoRemoteBrightnessTemperature":
            np.testing.assert_allclose(x[0, valid], 300, atol=.001, rtol=0)
        elif tool == "GeoRemoteGaussianClassify":
            self.assertEqual(float(x[0, 2, 0]), 2)
        elif tool == "GeoRemoteEndmemberDiscovery":
            rows = self._rows(root, "mixture-coefficients.csv")
            row = next(r for r in rows if r["valid_pixel_index"] == "2")
            np.testing.assert_allclose([float(row["coefficient_1"]), float(row["coefficient_2"])], [.5, .5], atol=1e-8, rtol=0)
            endpoints = self._rows(root, "discovered-endmembers.csv")
            rays = sorted((float(r["band_1"]), float(r["band_2"])) for r in endpoints)
            np.testing.assert_allclose(rays, [(0, 1), (1, 0)], atol=1e-8, rtol=0)
        elif tool == "GeoRemoteClassSeparability":
            rows = self._rows(root, "separability.csv")
            self.assertAlmostEqual(float(rows[0]["bhattacharyya_distance"]), 1.5, delta=1e-8)
        elif tool == "GeoRemoteDenseOpticalFlow":
            np.testing.assert_allclose(np.median(x[:, 12:36, 12:36], axis=(1, 2)), [1, 2], atol=.35, rtol=0)
        elif tool == "GeoRemoteProjectiveTiePoints":
            row = self._rows(root, "projected-points.csv")[0]
            np.testing.assert_allclose([float(row["column"]), float(row["row"])], [6, 3.5], atol=1e-8, rtol=0)
        elif tool == "GeoRemoteTemplateLocate":
            row = self._rows(root, "peak-placement.csv")[0]
            self.assertEqual((int(row["top_row"]), int(row["left_column"])), (3, 4))
            self.assertAlmostEqual(float(row["normalized_correlation"]), 1, delta=1e-7)
        elif tool == "GeoRemoteScaleSpaceBlobs":
            rows = self._rows(root, "blobs.csv")
            self.assertTrue(rows)
            row = min(rows, key=lambda r: (float(r["row"]) - 32) ** 2 + (float(r["column"]) - 32) ** 2)
            np.testing.assert_allclose([float(row["row"]), float(row["column"])], [32, 32], atol=1, rtol=0)
            self.assertAlmostEqual(float(row["sigma_pixels"]), 3, delta=.1)
        elif tool == "GeoRemoteHoughLineEvidence":
            rows = self._rows(root, "hough-evidence.csv")
            row = next(r for r in rows if float(r["rho_pixels"]) == 3 and float(r["normal_angle_rad"]) == 0)
            self.assertEqual(int(row["votes"]), 10)
        elif tool == "GeoRemoteWaveletPyramid":
            row = next(r for r in self._rows(root, "wavelet-coefficients.csv") if r["component"] == "approximation")
            self.assertAlmostEqual(float(row["coefficient"]), 2, delta=1e-8)
            row = next(r for r in self._rows(root, "scale-energy.csv") if r["component"] == "approximation")
            self.assertAlmostEqual(float(row["squared_coefficient_energy"]), 4, delta=1e-8)
        elif tool == "GeoSARDopplerDeskew":
            np.testing.assert_allclose(x[0, valid], 2, atol=1e-8, rtol=0)
            np.testing.assert_allclose(x[1, valid], 0, atol=1e-8, rtol=0)
        elif tool == "GeoSARSubaperture":
            np.testing.assert_allclose(np.hypot(x[0, valid], x[1, valid]), 2, atol=1e-8, rtol=0)
        elif tool == "GeoRemoteTOAReflectance":
            np.testing.assert_allclose(x[:, valid], .1, atol=1e-6, rtol=0)
        elif tool == "GeoRemotePansharpenFusion":
            np.testing.assert_allclose(x[0, 2:-2, 2:-2], .2, atol=1e-7, rtol=0)
            np.testing.assert_allclose(x[1, 2:-2, 2:-2], .6, atol=1e-7, rtol=0)
        elif tool == "GeoRemoteMADChange":
            values = sorted(float(r["variance"]) for r in self._rows(root, "mad-sample-variance.csv"))
            np.testing.assert_allclose(values, [1, 1.5], atol=.03, rtol=0)
        elif tool == "GeoSARPolarimetricHAlpha":
            entropy = -sum(p * math.log(p) / math.log(3) for p in (.5, 1 / 3, 1 / 6))
            np.testing.assert_allclose(x[0, valid], entropy, atol=1e-5, rtol=0)
            np.testing.assert_allclose(x[1, valid], 45, atol=1e-4, rtol=0)
            np.testing.assert_allclose(x[2, valid], 1 / 3, atol=1e-5, rtol=0)
        elif tool == "GeoSARPolarizationSynthesis":
            np.testing.assert_allclose(x[0, valid], 1, atol=1e-7, rtol=0)
        elif tool == "GeoInSARNetworkDisplacement":
            self.assertAlmostEqual(float(x[-1, 1, 1]), .02, delta=1e-8)
            quality = [float(r["temporal_coherence"]) for r in self._rows(root, "network-quality.csv")]
            np.testing.assert_allclose(quality, 1, atol=1e-6, rtol=0)
        elif tool == "GeoInSARResidualDEM":
            np.testing.assert_allclose(x[0, valid], 20, atol=1e-5, rtol=0)
            np.testing.assert_allclose(x[-1, valid], .01 * 1095 / 365.25, atol=1e-8, rtol=0)
        elif tool == "GeoInSARIonosphericDelay":
            self.assertAlmostEqual(float(x[-1, 1, 1]), .04, delta=1e-8)
            delay, _ = self._raster(root, "ionospheric-los-delay.tif")
            self.assertAlmostEqual(float(delay[-1, 1, 1]), .02, delta=1e-8)
        elif tool == "GeoInSARPlateFrameCorrection":
            enu, _ = self._raster(root, "plate-enu.tif")
            expected_east = 6378137 * math.pi / (180 * 3600 * 1000)
            self.assertAlmostEqual(float(enu[0, 0, 0]), expected_east, delta=1e-8)
        elif tool == "GeoInSARAscDescDecomposition":
            np.testing.assert_allclose(x[0, valid], .02, atol=1e-8, rtol=0)
            np.testing.assert_allclose(x[1, valid], .03, atol=1e-8, rtol=0)
        elif tool == "GeoInSAREnvisatOscillatorCorrection":
            self.assertAlmostEqual(float(x[1, 1, 1]), .000613, delta=1e-8)
        elif tool == "GeoInSARCoherenceNetworkSelection":
            rows = self._rows(root, "selected-network.csv")
            self.assertEqual(sum(int(r["keep"]) for r in rows), 2)
            middle = next(r for r in rows if r["pair"] == "20200113_20200125")
            self.assertEqual(int(middle["keep"]), 1)
        else:
            self.fail("Missing independent oracle for " + tool)

    def _negative(self, tool, mutation):
        args = self._args(tool)
        if mutation == "extra":
            args["arbitrary_function"] = "os.system"
        elif mutation == "unit":
            key = next(k for k in args if k.endswith("_unit"))
            args[key] = "unsupported_incompatible_unit"
        elif mutation == "nonfinite":
            args["unexpected_nonfinite"] = math.nan
        elif mutation == "duplicate_json":
            payload = json.dumps(args)
            key = next(iter(args))
            payload = payload[:-1] + "," + json.dumps(key) + ":" + json.dumps(args[key]) + "}"
            with self.assertRaises(ScientificToolError) as caught:
                getattr(ADAPTER, ENTRYPOINTS[tool])(payload, output_dir=self.root / "rejected")
            self.assertEqual(caught.exception.code, "invalid_arguments")
            return
        elif mutation == "missing_crs":
            if "grid" not in args:
                self.skipTest("This operation has no raster grid; not a passed grid test")
            del args["grid"]["crs"]
        elif mutation == "singular":
            if "grid" not in args:
                self.skipTest("This operation has no raster grid; not a passed grid test")
            args["grid"]["affine"] = [0, 0, 0, 0, 0, 0]
        elif mutation == "empty_mask":
            if "grid" not in args:
                self.skipTest("This operation has no raster grid; not a passed grid test")
            args["grid"]["mask"] = [[False for v in row] for row in args["grid"]["mask"]]
        else:
            self.fail("Unknown fixed mutation")
        with self.assertRaises(ScientificToolError) as caught:
            getattr(ADAPTER, ENTRYPOINTS[tool])(args, output_dir=self.root / "rejected")
        self.assertEqual(caught.exception.code, "invalid_arguments")

    def test_ccd_nonperfect_complex_coherence(self):
        import numpy as np
        args = self._args("GeoSARCoherentChange")
        h, w = len(args["reference_real"]), len(args["reference_real"][0])
        args["reference_real"] = [[1.0] * w for _ in range(h)]
        args["reference_imag"] = [[0.0] * w for _ in range(h)]
        args["secondary_real"] = [[1.0 if c % 2 == 0 else -1.0 for c in range(w)] for _ in range(h)]
        args["secondary_imag"] = [[0.0] * w for _ in range(h)]
        _, root = self._call("GeoSARCoherentChange", args)
        x, valid = self._raster(root)
        np.testing.assert_allclose(x[0, valid], 1 / 3, atol=1e-8, rtol=0)
        for c in range(1, w - 1):
            # Three alternating signs sum to the negative of the central sign.
            expected_complex = -1.0 if c % 2 == 0 else 1.0
            np.testing.assert_allclose(np.exp(1j * x[1, 1:-1, c]), expected_complex, atol=1e-8, rtol=0)

    def test_ccd_negative_phase_and_gain_invariance(self):
        import numpy as np
        args = self._args("GeoSARCoherentChange")
        h, w = len(args["reference_real"]), len(args["reference_real"][0])
        args["reference_real"] = [[4.0] * w for _ in range(h)]
        args["secondary_real"] = [[3 * math.cos(-math.pi / 4)] * w for _ in range(h)]
        args["secondary_imag"] = [[3 * math.sin(-math.pi / 4)] * w for _ in range(h)]
        _, root = self._call("GeoSARCoherentChange", args)
        x, valid = self._raster(root)
        np.testing.assert_allclose(x[0, valid], 1, atol=1e-8, rtol=0)
        np.testing.assert_allclose(x[1, valid], -math.pi / 4, atol=1e-8, rtol=0)

    def test_ccd_nodata_metadata_and_full_window_mask(self):
        import numpy as np
        args = self._args("GeoSARCoherentChange")
        args["grid"]["nodata"] = -9999
        result, root = self._call("GeoSARCoherentChange", args)
        x, valid = self._raster(root)
        np.testing.assert_array_equal(x[:, ~valid], -9999)
        self.assertEqual(result["valid_count"], 35)

    def test_ccd_shape_and_physical_rejections(self):
        base = self._args("GeoSARCoherentChange")
        cases = {}
        value = copy.deepcopy(base)
        value["secondary_real"].pop()
        cases["misaligned_array"] = value
        value = copy.deepcopy(base)
        value["reference_real"][2][2] = 0
        value["reference_imag"][2][2] = 0
        cases["zero_complex_amplitude"] = value
        value = copy.deepcopy(base)
        value["window_size"] = 4
        cases["even_window"] = value
        value = copy.deepcopy(base)
        value["window_size"] = 15
        cases["oversize_window"] = value
        value = copy.deepcopy(base)
        value["grid"]["mask"][2][2] = False
        cases["incomplete_neighborhood"] = value
        value = copy.deepcopy(base)
        value["complex_sar"]["secondary_acquisition"] = value["complex_sar"]["reference_acquisition"]
        cases["identical_acquisition_ids"] = value
        value = copy.deepcopy(base)
        value["complex_sar"]["state"] = "RGB"
        cases["not_complex_SAR"] = value
        for label, args in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(ScientificToolError) as caught:
                    ADAPTER.coherent_change(args, output_dir=self.root / label)
                self.assertEqual(caught.exception.code, "invalid_arguments")

    def test_ccd_upstream_result_contract_fault_injection(self):
        import numpy as np
        args = self._args("GeoSARCoherentChange")
        shape = (7, 9)
        one = np.ones(shape, dtype=complex)
        phase = np.zeros(shape)
        bad_nan = one.copy()
        bad_nan[2, 2] = complex(math.nan, 0)
        bad_phase = phase.copy()
        bad_phase[2, 2] = math.inf
        cases = {
            "wrong_ccd_shape": (one.reshape(-1, 1), phase),
            "wrong_phase_shape": (one, phase.reshape(-1, 1)),
            "nonfinite_ccd": (bad_nan, phase),
            "nonfinite_phase": (one, bad_phase),
            "complex_phase": (one, phase.astype(complex)),
            "magnitude_above_one": (one * 1.01, phase),
        }
        for label, returned in cases.items():
            with self.subTest(case=label):
                with mock.patch("sarpy.processing.sicd.ccd.mem", return_value=returned):
                    with self.assertRaises(ScientificToolError) as caught:
                        ADAPTER.coherent_change(args, output_dir=self.root / label)
                self.assertEqual(caught.exception.code, "invalid_output")
        # This is fault-injection evidence, never a scientific kernel pass.


def _numeric_case(tool, as_json):
    def test(self):
        _, root = self._call(tool, as_json=as_json)
        self._oracle(tool, root)
    test.category = "direct_json_numeric_artifact" if as_json else "direct_dict_numeric_artifact"
    return test


def _registry_case(tool):
    def test(self):
        from jsonschema import Draft202012Validator
        spec = LEGACY.definition(tool)
        self.assertEqual(spec, SPECS[tool])
        LEGACY.validate_registration_metadata(spec)
        for name in ("input_schema", "output_schema"):
            self.assertIs(spec[name]["additionalProperties"], False)
            Draft202012Validator.check_schema(spec[name])
        Draft202012Validator(spec["input_schema"]).validate(EXAMPLES[tool])
        entry = spec["source_interface"]["entrypoint"]
        self.assertEqual(entry["callable"],
                         "geological_agent.geology.expansion501_remote:" + ENTRYPOINTS[tool])
        self.assertEqual(entry["argument_parameter"], "args")
        self.assertEqual(entry["output_directory_parameter"], "output_dir")
        self.assertTrue(callable(getattr(ADAPTER, ENTRYPOINTS[tool])))
        self.assertIs(spec["metadata"]["scientific_contract"]["formal_eligible"], False)
        self.assertEqual(spec["metadata"]["scientific_contract"]["review_status"], "acceptance_pending")
        self.assertEqual(spec["source_interface"]["kind"], "expansion501_remote")
        self.assertIs(spec["source_interface"]["pure"], False)
    test.category = "private_catalog_lookup_and_schema"
    return test


def _negative_case(tool, mutation):
    def test(self):
        self._negative(tool, mutation)
    test.category = "negative_input"
    return test


# Fixed internal test cases, not a user-selected dispatch API.
for _tool in ENTRYPOINTS:
    setattr(RemoteCases, "test_registry_" + _tool, _registry_case(_tool))
    setattr(RemoteCases, "test_dict_" + _tool, _numeric_case(_tool, False))
    setattr(RemoteCases, "test_json_" + _tool, _numeric_case(_tool, True))
    for _mutation in ("extra", "unit", "nonfinite", "duplicate_json",
                      "missing_crs", "singular", "empty_mask"):
        setattr(RemoteCases, "test_reject_" + _mutation + "_" + _tool,
                _negative_case(_tool, _mutation))

RemoteCases.test_ccd_nonperfect_complex_coherence.category = "ccd_independent_numeric_artifact"
RemoteCases.test_ccd_negative_phase_and_gain_invariance.category = "ccd_independent_numeric_artifact"
RemoteCases.test_ccd_nodata_metadata_and_full_window_mask.category = "ccd_artifact_contract"
RemoteCases.test_ccd_shape_and_physical_rejections.category = "negative_input_subcases"
RemoteCases.test_ccd_upstream_result_contract_fault_injection.category = "upstream_contract_fault_injection"


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []
        self.subcases = []

    def _record(self, test, state, detail=None):
        method = getattr(test, getattr(test, "_testMethodName", ""), None)
        self.records.append({"test": test.id(), "category": getattr(method, "category", "setup_or_teardown"),
                             "state": state, "detail": detail})

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "passed")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "failed", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "error", self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "skipped_not_accepted", reason)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        self.subcases.append({"test": test.id(), "subcase": str(subtest),
                              "state": "passed" if err is None else "failed",
                              "detail": None if err is None else self._exc_info_to_string(err, test)})
        if err is not None:
            self._record(test, "failed_subcase", str(subtest))



def _ccd_nonfinite_input(self):
    for value, label in ((math.nan, "nan"), (math.inf, "infinity")):
        with self.subTest(case=label):
            args = self._args("GeoSARCoherentChange")
            args["secondary_imag"][2][2] = value
            with self.assertRaises(ScientificToolError) as caught:
                ADAPTER.coherent_change(args, output_dir=self.root / label)
            self.assertEqual(caught.exception.code, "invalid_arguments")


_ccd_nonfinite_input.category = "negative_input_subcases"
RemoteCases.test_ccd_nonfinite_input = _ccd_nonfinite_input

if __name__ == "__main__":
    _guard()
    started = time.time()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RemoteCases)
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite)
    counts = {}
    for row in result.records:
        category = counts.setdefault(row["category"], {})
        category[row["state"]] = category.get(row["state"], 0) + 1
    report = {
        "status": "fresh_independent_test_execution_only",
        "elapsed_seconds": time.time() - started,
        "tests_run": result.testsRun,
        "successful": result.wasSuccessful(),
        "counts_by_category": counts,
        "records": result.records,
        "subcases": result.subcases,
        "unique_source_tools": len(ENTRYPOINTS),
        "scientific_oracle_scope": "26 analytic operation oracles, each called via dict and JSON; duplicate invocation modes are not new capabilities",
        "registry_scope": "private source catalog lookup/schema only; merged central dispatcher acceptance remains parent-owned",
        "model_workflow_validation": "not_run",
        "platform_certification": "not_established",
        "deployment": "not_deployed",
        "source_hash_manifest": os.environ.get("EXPANSION501_REMOTE_SOURCE_HASHES"),
    }
    # If setup fails before SESSION allocation, preserve the fresh failure separately.
    report_dir = SESSION if SESSION is not None else _inside(RUN_ROOT / "results" / ("setup-failure-" + uuid.uuid4().hex))
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_dir / "report.json"), "tests_run": result.testsRun,
                      "successful": result.wasSuccessful(), "counts_by_category": counts}))
    raise SystemExit(0 if result.wasSuccessful() else 1)

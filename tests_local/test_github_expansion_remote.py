"""Independent synthetic acceptance SOURCE. NOT RUN by the authoring agent.

Run only in the parent's authorized pinned CPU environment. Catalog lookup is
patched in memory so these tests do not register tools or alter the baseline.
Oracles use arithmetic/combinatorics, never the target upstream implementation.
"""
import copy
import csv
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
GROUP = ROOT / "catalog/source_delivery/github-expansion-20261025/groups/remote"
ASSETS = ROOT / "assets/github-expansion-remote"


class RemoteExpansionAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.additions = json.loads((GROUP / "catalog-additions.json").read_text(encoding="utf-8"))
        cls.specs = {s["id"]: s for s in cls.additions["tools"]}
        cls.oracles = json.loads((ASSETS / "oracles.json").read_text(encoding="utf-8"))["operations"]
        cls.module = importlib.import_module("geological_agent.geology.github_expansion_remote")
        cls.contract = importlib.import_module("geological_agent.geology.collection_contracts")
        cls.transport = importlib.import_module("legacy.ToolsAgent.ToolsFuns.source_contracts")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="remote-synthetic-acceptance-")
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.patches = [patch.object(self.contract, "definition", side_effect=self.specs.__getitem__),
                        patch.object(self.transport, "definition", side_effect=self.specs.__getitem__)]
        for active in self.patches:
            active.start()
            self.addCleanup(active.stop)

    def arguments(self, spec, overrides=None):
        args = copy.deepcopy(spec["example_arguments"])
        args.update(overrides or {})
        for field in spec["source_interface"]["path_fields"]:
            if field in args:
                value = Path(args[field])
                args[field] = str(value if value.is_absolute() else ROOT / value)
        return args

    def function(self, spec):
        entry = spec["source_interface"]["entrypoint"]
        module, function = entry["callable"].split(":")
        self.assertEqual(module, self.module.__name__)
        self.assertEqual(entry["argument_parameter"], "args")
        self.assertEqual(entry["output_directory_parameter"], "output_dir")
        return getattr(self.module, function)

    def assert_provenance(self, result, spec, args):
        self.assertEqual(result["provenance"]["tool"], spec["id"])
        self.assertEqual(result["provenance"]["reviewed_archive_commit"], spec["registration_metadata"]["source_commit"])
        self.assertFalse(result["provenance"]["network_required"])
        self.assertEqual(result["provenance"]["source_mode"], "package_release")
        for requirement in spec["metadata"]["upstream"]["requirements"]:
            package, version = requirement.split("==")
            self.assertEqual(result["provenance"]["installed_versions"][package], version)
        canonical = copy.deepcopy(args)
        for field in spec["source_interface"]["path_fields"]:
            if field in args:
                path = Path(args[field])
                content = path.read_bytes()
                canonical[field] = {"content_sha256": hashlib.sha256(content).hexdigest(),
                                    "bytes": len(content), "suffix": path.suffix.lower()}
        digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()).hexdigest()
        self.assertEqual(result["provenance"]["input_sha256"], digest)
        self.assertEqual(result["provenance"]["implementation_sha256"], hashlib.sha256(Path(self.module.__file__).read_bytes()).hexdigest())
        self.assertEqual(result["provenance"]["contract_sha256"], hashlib.sha256(Path(self.contract.__file__).read_bytes()).hexdigest())
        self.assertTrue(result["artifacts"])
        for filename in result["artifacts"]:
            path = Path(filename)
            self.assertTrue(path.is_file())
            self.assertEqual(result["provenance"]["output_sha256"][path.name], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_thirty_independent_positive_numeric_oracles_and_provenance(self):
        import numpy as np
        import rasterio
        from jsonschema import Draft202012Validator

        self.assertEqual(len(self.specs), 30)
        self.assertEqual(set(self.oracles), set(self.specs))
        for index, (tool_id, spec) in enumerate(self.specs.items()):
            with self.subTest(tool=tool_id):
                args = self.arguments(spec)
                # Exercise both allowed input transports without bypassing the decorator.
                supplied = json.dumps(args) if index % 2 else args
                out = self.root / tool_id
                result = self.function(spec)(supplied, output_dir=out)
                Draft202012Validator(spec["output_schema"]).validate(result)
                oracle = self.oracles[tool_id]
                actual = result["measurements"]
                for key in oracle["measurement"]["path"]:
                    actual = actual[key]
                expected = oracle["measurement"]["expected"]
                self.assertGreater(expected, 0, "Every operation needs a positive independent numerical expectation")
                self.assertAlmostEqual(actual, expected, delta=oracle["absolute_tolerance"])
                self.assert_provenance(result, spec, args)
                if result["raster_statistics"]:
                    with rasterio.open(args["raster_path"]) as source, rasterio.open(out / "result.tif") as target:
                        self.assertEqual(source.crs, target.crs)
                        self.assertEqual(source.transform, target.transform)
                        self.assertEqual(source.shape, target.shape)
                        expected_mask = np.all(source.read_masks() != 0, axis=0)
                        np.testing.assert_array_equal(target.dataset_mask() != 0, expected_mask)
                        self.assertTrue(np.isfinite(target.read(masked=True).compressed()).all())
                        probe = oracle["raster_probe"]
                        if probe:
                            value = target.read(probe["band"])[probe["row"], probe["column"]]
                            self.assertAlmostEqual(float(value), probe["expected"], delta=oracle["absolute_tolerance"])
                if tool_id == "GeoRemoteMatchedFilter":
                    self.assertEqual(result["grid"]["valid_pixels"], 63)
                    self.assertAlmostEqual(result["measurements"]["mean"], 1.0, delta=1e-7)
                if tool_id == "GeoRemoteSensorBandResample":
                    self.assertEqual(result["grid"]["valid_pixels"], 63)
                    np.testing.assert_allclose(result["measurements"]["resampling_weights"], [[.5, .5]], rtol=0, atol=1e-12)
                    with (out / "resampling-weights.csv").open(newline="", encoding="utf-8") as stream:
                        rows = list(csv.DictReader(stream))
                    self.assertEqual([(int(row["target_band"]), int(row["source_band"])) for row in rows], [(1, 1), (1, 2)])
                    for row in rows:
                        self.assertAlmostEqual(float(row["weight"]), .5, delta=1e-12)
                        self.assertEqual(float(row["target_center_nm"]), 1050)
                        self.assertEqual(float(row["target_fwhm_nm"]), 200)
                    with rasterio.open(out / "result.tif") as ds:
                        self.assertEqual(ds.count, 1)
                        self.assertEqual(float(ds.tags(1)["wavelength_nm"]), 1050)
                        self.assertEqual(float(ds.tags(1)["fwhm_nm"]), 200)
                        self.assertEqual(ds.tags(1)["radiometric_unit"], "reflectance")
                        self.assertEqual(ds.nodata, -9999)
                        np.testing.assert_allclose(ds.read(1, masked=True).compressed(), .4, rtol=0, atol=1e-12)
                if tool_id == "GeoRemotePhaseRegistration":
                    self.assertAlmostEqual(result["measurements"]["shift_row_pixels"], -2, delta=1e-8)
                    self.assertAlmostEqual(result["measurements"]["shift_x"], 30, delta=1e-8)
                    self.assertAlmostEqual(result["measurements"]["shift_y"], 60, delta=1e-8)
                if tool_id == "GeoRemoteRegionProperties":
                    self.assertEqual(result["measurements"]["centroid-0"], [2.5])
                    self.assertEqual(result["measurements"]["centroid-1"], [3.0])

    def test_each_operation_rejects_its_specific_negative_constraint(self):
        for tool_id, spec in self.specs.items():
            with self.subTest(tool=tool_id):
                args = self.arguments(spec, self.oracles[tool_id]["negative_overrides"])
                with self.assertRaises(self.contract.ScientificToolError):
                    self.function(spec)(args, output_dir=self.root / tool_id)

    def test_each_operation_rejects_arbitrary_parameters(self):
        for tool_id, spec in self.specs.items():
            for value in ("os.system", "spectral.algorithms.resampling.BandResampler"):
                with self.subTest(tool=tool_id, value=repr(value)):
                    args = self.arguments(spec)
                    args["arbitrary_callable"] = value
                    with self.assertRaises(self.contract.ScientificToolError):
                        self.function(spec)(args, output_dir=self.root / tool_id)

    def test_quality_mask_preserved_for_mask_aware_entropy_and_otsu(self):
        import numpy as np
        import rasterio
        for tool_id in ("GeoRemoteLocalEntropy", "GeoRemoteOtsu"):
            with self.subTest(tool=tool_id):
                spec = self.specs[tool_id]
                args = self.arguments(spec, {"quality_mask_path": str(ASSETS / "quality.tif")})
                output = self.root / tool_id
                result = self.function(spec)(args, output_dir=output)
                self.assertEqual(result["grid"]["excluded_pixels"], 1)
                with rasterio.open(output / "result.tif") as ds:
                    expected = np.ones((16, 16), dtype=bool)
                    expected[0, 0] = False
                    np.testing.assert_array_equal(ds.dataset_mask() != 0, expected)
                self.assert_provenance(result, spec, args)

    def test_complete_patch_kernel_rejects_masked_gap(self):
        spec = self.specs["GeoRemoteTVDenoise"]
        args = self.arguments(spec, {"quality_mask_path": str(ASSETS / "quality.tif")})
        with self.assertRaises(self.contract.ScientificToolError):
            self.function(spec)(args, output_dir=self.root / "gap")

    def test_output_conflict_and_unmasked_nonfinite_geotiff(self):
        import numpy as np
        import rasterio
        spec = self.specs["GeoRemoteTVDenoise"]
        args = self.arguments(spec)
        occupied = self.root / "occupied"
        occupied.mkdir()
        (occupied / "keep.txt").write_text("preserve this file", encoding="utf-8")
        with self.assertRaises(self.contract.ScientificToolError):
            self.function(spec)(args, output_dir=occupied)
        with rasterio.open(args["raster_path"]) as ds:
            profile = ds.profile
            values = ds.read()
        values[0, 1, 1] = np.inf
        bad_path = self.root / "nonfinite-synthetic.tif"
        with rasterio.open(bad_path, "w", **profile) as ds:
            ds.write(values)
        args["raster_path"] = str(bad_path)
        with self.assertRaises(self.contract.ScientificToolError):
            self.function(spec)(args, output_dir=self.root / "nonfinite")


    def raster_variant(self, source, name, *, profile_changes=None, pixel_value=None):
        """Write a synthetic test variant only when the parent runs acceptance."""
        import rasterio
        with rasterio.open(source) as ds:
            profile, values = ds.profile, ds.read()
        profile.update(profile_changes or {})
        if pixel_value is not None:
            values[0, 1, 1] = pixel_value
        path = self.root / (name + ".tif")
        with rasterio.open(path, "w", **profile) as ds:
            ds.write(values)
        return str(path)

    def test_contribution_membership_excludes_duplicate_and_retains_history(self):
        candidates = json.loads((GROUP / "candidate-operations.json").read_text(encoding="utf-8"))
        examples = json.loads((GROUP / "examples-additions.json").read_text(encoding="utf-8"))
        sources = json.loads((GROUP / "sources.json").read_text(encoding="utf-8"))
        excluded = json.loads((GROUP / "excluded-candidates.json").read_text(encoding="utf-8"))
        self.assertEqual(candidates["group"], "remote")
        self.assertEqual(len(candidates["operations"]), 30)
        self.assertEqual({row["tool_id"] for row in candidates["operations"]}, set(self.specs))
        self.assertEqual({row["tool_id"] for row in sources["operations"]}, set(self.specs))
        self.assertEqual(set(examples), set(self.specs))
        self.assertIn("GeoRemoteSensorBandResample", self.specs)
        self.assertNotIn("GeoRemoteHistogramMatch", self.specs)
        self.assertFalse(hasattr(self.module, "relative_histogram_match"))
        historical = excluded["operations"][0]
        self.assertEqual(historical["tool_id"], "GeoRemoteHistogramMatch")
        self.assertEqual(historical["duplicate_of"], "SkdownscaleQuantileBiasCorrection")
        self.assertFalse(historical["counted_as_new"])
        self.assertIn("match_histograms", historical["original_adapter_source"])
        references = []
        for skill in self.additions["skills"]:
            self.assertEqual(len(skill["tool_references"]), 6)
            references.extend(skill["tool_references"])
        self.assertEqual(len(self.additions["skills"]), 5)
        self.assertEqual(len(references), 30)
        self.assertEqual(set(references), set(self.specs))

    def test_every_operation_rejects_missing_crs_and_unmasked_nonfinite_raster(self):
        cases = [
            ("missing-crs", {"profile_changes": {"crs": None}}, "explicit CRS"),
            ("unmasked-inf", {"pixel_value": float("inf")}, "finite"),
            ("unmasked-nan", {"pixel_value": float("nan")}, "finite"),
        ]
        for name, options, message in cases:
            bad = self.raster_variant(ASSETS / "flat.tif", name, **options)
            for tool_id, spec in self.specs.items():
                with self.subTest(case=name, tool=tool_id):
                    args = self.arguments(spec, {"raster_path": bad})
                    with self.assertRaisesRegex(self.contract.ScientificToolError, message):
                        self.function(spec)(args, output_dir=self.root / (name + "-" + tool_id))

    def test_auxiliary_crs_and_affine_must_match(self):
        import rasterio
        cases = [
            ("GeoRemotePhaseRegistration", "reference_path", None),
            ("GeoRemoteSSIMChange", "reference_path", None),
            ("GeoRemoteSeedReconstruction", "seed_path", None),
            ("GeoRemoteWatershed", "markers_path", None),
            ("GeoRemoteRandomWalker", "markers_path", None),
            ("GeoRemoteLocalEntropy", "quality_mask_path", ASSETS / "quality.tif"),
            ("GeoRemoteSensorBandResample", "quality_mask_path", ASSETS / "quality-spectral.tif"),
        ]
        for tool_id, field, fixture in cases:
            spec = self.specs[tool_id]
            args = self.arguments(spec)
            source = fixture if fixture is not None else args[field]
            with rasterio.open(source) as ds:
                transform = ds.transform
            shifted = transform * type(transform).translation(1, 0)
            for label, changes, message in (
                ("missing-crs", {"crs": None}, "explicit CRS"),
                ("wrong-crs", {"crs": "EPSG:32651"}, "grids differ"),
                ("shifted-affine", {"transform": shifted}, "grids differ"),
            ):
                with self.subTest(tool=tool_id, field=field, case=label):
                    bad = self.raster_variant(source, tool_id + "-" + label, profile_changes=changes)
                    changed = {**args, field: bad}
                    with self.assertRaisesRegex(self.contract.ScientificToolError, message):
                        self.function(spec)(changed, output_dir=self.root / ("output-" + tool_id + "-" + label))

    def test_units_and_known_numeric_arguments_reject_invalid_values(self):
        for tool_id, spec in self.specs.items():
            with self.subTest(tool=tool_id, case="unknown-unit"):
                args = self.arguments(spec, {"input_unit": "ore_grade"})
                with self.assertRaises(self.contract.ScientificToolError):
                    self.function(spec)(args, output_dir=self.root / tool_id)
        for index, value in enumerate((float("nan"), float("inf"), -float("inf"))):
            for tool_id, override in (
                ("GeoRemoteTVDenoise", {"weight": value}),
                ("GeoRemoteMNF", {"noise_covariance": [[1, 0], [0, value]]}),
                ("GeoRemoteSensorBandResample", {"source_fwhm_nm": [100, value]}),
            ):
                with self.subTest(tool=tool_id, value=repr(value)):
                    spec = self.specs[tool_id]
                    with self.assertRaises(self.contract.ScientificToolError):
                        self.function(spec)(self.arguments(spec, override),
                                            output_dir=self.root / (tool_id + "-nonfinite-" + str(index)))

    def test_matched_filter_rejects_wrong_shape_nonfinite_and_complex_results(self):
        import numpy as np
        spec = self.specs["GeoRemoteMatchedFilter"]
        args = self.arguments(spec)
        # Independent fixture count: 8*8 minus its top-left NoData cell = 63.
        invalid = [np.ones((63, 2)), np.ones((62, 1)), np.ones((1, 63)),
                   np.ones((63, 1, 1)), np.asarray(1.0),
                   np.full((63, 1), np.nan), np.full((63,), np.inf),
                   np.full((63, 1), 1 + 1j)]
        for index, values in enumerate(invalid):
            with self.subTest(case=index):
                with patch("spectral.algorithms.detectors.matched_filter", return_value=values):
                    with self.assertRaises(self.contract.ScientificToolError) as raised:
                        self.function(spec)(args, output_dir=self.root / ("invalid-score-" + str(index)))
                    self.assertEqual(raised.exception.code, "invalid_result")

    def test_tv_rejects_categorical_units_and_physical_domain_violations(self):
        spec = self.specs["GeoRemoteTVDenoise"]
        for unit in ("binary", "label"):
            with self.subTest(unit=unit):
                with self.assertRaises(self.contract.ScientificToolError):
                    self.function(spec)(self.arguments(spec, {"input_unit": unit}),
                                        output_dir=self.root / ("categorical-" + unit))
        for index, (unit, value) in enumerate((
            ("reflectance", -.1), ("reflectance", 1.1), ("normalized_intensity", 1.1),
            ("radiance", -1), ("DN", -1), ("brightness_temperature_K", -1),
        )):
            with self.subTest(unit=unit, value=value):
                raster = self.raster_variant(ASSETS / "flat.tif", "tv-domain-" + str(index), pixel_value=value)
                with self.assertRaises(self.contract.ScientificToolError):
                    self.function(spec)(self.arguments(spec, {"input_unit": unit, "raster_path": raster}),
                                        output_dir=self.root / ("tv-domain-out-" + str(index)))

    def test_tv_output_remains_continuous_in_declared_units(self):
        from jsonschema import Draft202012Validator
        spec = self.specs["GeoRemoteTVDenoise"]
        allowed = ["reflectance", "radiance", "DN", "brightness_temperature_K", "normalized_intensity"]
        self.assertEqual(spec["input_schema"]["properties"]["input_unit"]["enum"], allowed)
        for unit in allowed:
            with self.subTest(unit=unit):
                args = self.arguments(spec, {"input_unit": unit})
                result = self.function(spec)(args, output_dir=self.root / ("tv-unit-" + unit))
                Draft202012Validator(spec["output_schema"]).validate(result)
                for key in ("input", "minimum", "maximum", "mean"):
                    self.assertEqual(result["units"][key], unit)
                self.assertEqual(result["raster_statistics"][0]["unit"], unit)
                # The unchanged constant .5 fixed point is not a binary/label result.
                self.assertAlmostEqual(result["measurements"]["mean"], .5, delta=1e-12)
                broken = copy.deepcopy(result)
                broken["raster_statistics"][0]["unit"] = "label"
                self.assertFalse(Draft202012Validator(spec["output_schema"]).is_valid(broken))

    def test_sensor_resampling_joint_nodata_quality_mask_and_georeferencing(self):
        import numpy as np
        import rasterio
        spec = self.specs["GeoRemoteSensorBandResample"]
        args = self.arguments(spec, {"quality_mask_path": str(ASSETS / "quality-spectral.tif")})
        out = self.root / "resample-mask"
        result = self.function(spec)(args, output_dir=out)
        self.assertEqual(result["grid"]["valid_pixels"], 62)
        self.assertEqual(result["grid"]["excluded_pixels"], 2)
        expected = np.ones((8, 8), dtype=bool)
        expected[0, 0] = expected[1, 1] = False
        with rasterio.open(args["raster_path"]) as source, rasterio.open(out / "result.tif") as target:
            self.assertEqual(source.crs, target.crs)
            self.assertEqual(source.transform, target.transform)
            self.assertEqual(source.shape, target.shape)
            np.testing.assert_array_equal(target.dataset_mask() != 0, expected)
            np.testing.assert_allclose(target.read(1)[expected], .4, rtol=0, atol=1e-12)
            np.testing.assert_array_equal(target.read(1)[~expected], [-9999, -9999])
        self.assert_provenance(result, spec, args)

    def test_sensor_resampling_rejects_unsupported_bandpasses_and_units(self):
        spec = self.specs["GeoRemoteSensorBandResample"]
        cases = [
            {"target_wavelength_nm": [1300], "target_fwhm_nm": [100]},
            {"target_fwhm_nm": [250]},  # Partial support at both ends.
            {"source_fwhm_nm": [80, 80]},  # Gap inside the target interval.
            {"source_fwhm_nm": [120, 120]},  # Double-counted overlapping support.
            {"source_fwhm_nm": [0, 100]},
            {"source_fwhm_nm": [100]},
            {"wavelength_nm": [1100, 1000]},
            {"wavelength_nm": [1000, 1000]},
            {"wavelength_nm": [1000, 1100, 1200]},
            {"target_fwhm_nm": [200, 200]},
            {"target_wavelength_nm": [1000, 900], "target_fwhm_nm": [50, 50]},
            {"target_wavelength_nm": [100], "target_fwhm_nm": [200]},
            {"input_unit": "DN"}, {"input_unit": "radiance"}, {"input_unit": "label"},
        ]
        for index, changed in enumerate(cases):
            with self.subTest(case=index):
                with self.assertRaises(self.contract.ScientificToolError):
                    self.function(spec)(self.arguments(spec, changed), output_dir=self.root / ("bandpass-" + str(index)))
        for index, value in enumerate((-.01, 1.01)):
            bad = self.raster_variant(ASSETS / "spectral-resample.tif", "reflectance-domain-" + str(index), pixel_value=value)
            with self.assertRaises(self.contract.ScientificToolError):
                self.function(spec)(self.arguments(spec, {"raster_path": bad}),
                                    output_dir=self.root / ("reflectance-domain-out-" + str(index)))


if __name__ == "__main__":
    unittest.main()

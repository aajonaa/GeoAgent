"""Unrun CPU acceptance source for twenty-nine r2 geophysics candidates and blocked diagnostics.

Requires exact declared dependencies installed by the parent. No installation,
network, global registry rewrite, GPU or deployment is performed by these tests.
All fixtures are explicitly synthetic. Oracles contain no upstream output data.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from geological_agent.geology import github_expansion_geophysics as implementation
from geological_agent.geology import collection_contracts
from legacy.ToolsAgent.ToolsFuns import source_contracts
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError

ROOT = Path(__file__).resolve().parents[1]
GROUP = ROOT / "catalog/source_delivery/github-expansion-20261025/groups/geophysics"


class TestGeophysicsContribution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((GROUP / "catalog-additions.json").read_text(encoding="utf-8"))
        cls.specs = cls.catalog["tools"]
        cls.fixtures = {
            spec["id"]: json.loads((ROOT / spec["example_path"]).read_text(encoding="utf-8"))
            for spec in cls.specs
        }

    def setUp(self):
        # Isolated in-memory contract overlay, not a global catalog modification.
        self.catalog_patch = patch.object(source_contracts, "catalog", return_value=self.catalog)
        self.catalog_patch.start()
        self.addCleanup(self.catalog_patch.stop)

    def assert_numeric(self, actual, expected, relative, absolute):
        if isinstance(expected, list):
            self.assertIsInstance(actual, list)
            self.assertEqual(len(actual), len(expected))
            for a, e in zip(actual, expected):
                self.assert_numeric(a, e, relative, absolute)
        else:
            self.assertIsInstance(actual, (float, int))
            self.assertTrue(math.isfinite(actual))
            self.assertTrue(math.isclose(actual, expected, rel_tol=relative, abs_tol=absolute),
                            msg=f"{actual!r} != analytic {expected!r}")

    @staticmethod
    def entrypoint(spec):
        module, name = spec["source_interface"]["entrypoint"]["callable"].split(":")
        if module != "geological_agent.geology.github_expansion_geophysics":
            raise AssertionError("Unexpected callable module")
        return getattr(implementation, name)

    def test_twenty_nine_candidates_match_tools_skills_examples(self):
        candidates = json.loads((GROUP / "candidate-operations.json").read_text(encoding="utf-8"))
        examples = json.loads((GROUP / "examples-additions.json").read_text(encoding="utf-8"))
        self.assertEqual(set(candidates), {"group", "operations"})
        self.assertEqual(candidates["group"], "geophysics")
        ids = [s["id"] for s in self.specs]
        self.assertEqual(len(ids), 29)
        self.assertEqual(len(set(ids)), 29)
        self.assertEqual(ids, [r["tool_id"] for r in candidates["operations"]])
        self.assertEqual(set(ids), set(examples))
        self.assertEqual(len({r["capability_key"] for r in candidates["operations"]}), 29)
        row_keys = {"tool_id", "capability_key", "upstream_callable", "scientific_task",
                    "distinct_from_existing", "numeric_oracle", "status"}
        for row in candidates["operations"]:
            self.assertEqual(set(row), row_keys)
            self.assertEqual(row["status"], "source_authored_unverified")
        references = [id for s in self.catalog["skills"] for id in s["tool_references"]]
        self.assertEqual(len(self.catalog["skills"]), 5)
        self.assertEqual(sorted(references), sorted(ids))

    def test_analytic_values_native_errors_and_provenance_for_every_operation(self):
        from jsonschema import Draft202012Validator
        implementation_hash = hashlib.sha256(Path(implementation.__file__).read_bytes()).hexdigest()
        contract_hash = hashlib.sha256(Path(collection_contracts.__file__).read_bytes()).hexdigest()
        for spec in self.specs:
            with self.subTest(tool=spec["id"]):
                fixture = self.fixtures[spec["id"]]
                self.assertTrue(fixture["synthetic"])
                self.assertEqual(fixture["status"], "source_authored_unverified")
                self.assertTrue(fixture["expected_checks"])
                args = copy.deepcopy(fixture["arguments"])
                function = self.entrypoint(spec)
                Draft202012Validator.check_schema(spec["input_schema"])
                Draft202012Validator.check_schema(spec["output_schema"])
                result = function(args)
                # Exercise the same native JSON-string entry contract.
                serialized = function(json.dumps(args, allow_nan=False))
                self.assertEqual(result, serialized)
                Draft202012Validator(spec["output_schema"]).validate(result)
                self.assertEqual(result["input_source"], fixture["input_source"])
                positive_expected = False
                for oracle in fixture["expected_checks"]:
                    value = result
                    for key in oracle["path"]:
                        value = value[key]
                    self.assert_numeric(value, oracle["value"], oracle["relative_tolerance"],
                                        oracle["absolute_tolerance"])
                    values = oracle["value"] if isinstance(oracle["value"], list) else [oracle["value"]]
                    positive_expected |= any(isinstance(v, (float, int)) and v > 0 for v in values)
                self.assertTrue(positive_expected, "Every operation needs a positive analytic expectation")
                provenance = result["provenance"]
                self.assertEqual(provenance["tool"], spec["id"])
                self.assertEqual(provenance["implementation_sha256"], implementation_hash)
                self.assertEqual(provenance["contract_sha256"], contract_hash)
                self.assertEqual(provenance["reviewed_archive_commit"],
                                 spec["registration_metadata"]["source_commit"])
                self.assertEqual(provenance["upstream_url"], spec["metadata"]["upstream"]["url"])
                self.assertFalse(provenance["network_required"])
                self.assertEqual(result["artifacts"], [])
                self.assertEqual(provenance["output_sha256"], {})
                expected_input_hash = hashlib.sha256(json.dumps(
                    args, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()).hexdigest()
                self.assertEqual(provenance["input_sha256"], expected_input_hash)
                upstream = spec["metadata"]["upstream"]
                requirements = [upstream["package"]+"=="+upstream["version"]] + upstream["requirements"]
                self.assertEqual(provenance["installed_versions"],
                                 {r.split("==")[0]: r.split("==")[1] for r in requirements})
                self.assertEqual(set(result["units"]),
                                 set(result)-{"input_source", "units", "artifacts", "provenance"})
                bad = copy.deepcopy(args)
                bad.update(fixture["negative_overrides"])
                with self.assertRaises(ScientificToolError) as rejected:
                    function(bad)
                self.assertIn(rejected.exception.code, {"invalid_arguments", "unsupported_conditions"})
                with self.assertRaises(ScientificToolError):
                    function({**args, "arbitrary_function": "os.system"})
                with self.assertRaises(ScientificToolError):
                    function({**args, "input_source": float("nan")})
                json.dumps(result, allow_nan=False)

    def test_tensor_and_wave_physical_relations(self):
        # Additional independent invariants, not duplicate upstream calculations.
        by_id = {s["id"]: s for s in self.specs}
        for name in ("GeoPointMassGravity", "GeoPrismGravity"):
            result = self.entrypoint(by_id[name])(self.fixtures[name]["arguments"])
            for tensor in result["gradient_enu_s2"]:
                self.assertAlmostEqual(sum(tensor[i][i] for i in range(3)), 0, delta=1e-12)
                for i in range(3):
                    for j in range(3):
                        self.assertAlmostEqual(tensor[i][j], tensor[j][i], delta=1e-14)
        name = "GeoSeismicZoeppritzScattering"
        result = self.entrypoint(by_id[name])(self.fixtures[name]["arguments"])
        # At normal incidence, energy flux R^2+(Z2/Z1)T^2 = 1.
        reflected = result["scattering_real"][0][0][0]
        transmitted = result["scattering_real"][0][0][2]
        self.assertAlmostEqual(reflected**2+1.5*transmitted**2, 1, places=10)
        self.assertTrue(any(abs(v) > 1e-8 for row in result["scattering_imag"][2] for v in row))


    def test_r2_independent_sphere_prolate_and_domain_oracles(self):
        evidence = json.loads((ROOT / "assets/github-expansion-geophysics/r2-oracles.json").read_text(encoding="utf-8"))
        self.assertTrue(evidence["synthetic"])
        self.assertFalse(evidence["upstream_used_to_generate_expectations"])
        by_id = {s["id"]: s for s in self.specs}
        for case in evidence["positive_cases"]:
            with self.subTest(case=case["case_id"]):
                args = copy.deepcopy(case["arguments"])
                original = copy.deepcopy(args)
                self.assertTrue(all(f > 0 for f in args["fractions"]))
                self.assertGreater(len(set(args["bulk_gpa"])), 1)
                self.assertGreater(len(set(args["shear_gpa"])), 1)
                result = self.entrypoint(by_id[case["tool_id"]])(args)
                self.assertEqual(args, original, "Exact spheres must not mutate caller arrays")
                for oracle in case["expected_checks"]:
                    value = result
                    for key in oracle["path"]:
                        value = value[key]
                    self.assert_numeric(value, oracle["value"], oracle["relative_tolerance"],
                                        oracle["absolute_tolerance"])
                self.assertEqual(result["units"]["density_kg_m3"], "kg/m^3")
                for key, phase_key in (("bulk_residual_pa", "bulk_gpa"),
                                       ("shear_residual_pa", "shear_gpa")):
                    self.assertEqual(result["units"][key], "Pa")
                    self.assertLessEqual(abs(result[key]), 1e-8 * max(args[phase_key]) * 1e9)
                self.assertEqual(result["provenance"]["reviewed_archive_commit"],
                                 "68cd21b6a581e591d78ef90003292444cb81fe81")
                self.assertEqual(result["provenance"]["installed_versions"]["rock-physics-open"], "1.0.1")
                self.assertEqual(result["provenance"]["installed_versions"]["tmatrix"], "1.2.0")
        for case in evidence["negative_cases"]:
            with self.subTest(case=case["case_id"]):
                with self.assertRaises(ScientificToolError) as caught:
                    self.entrypoint(by_id[case["tool_id"]])(copy.deepcopy(case["arguments"]))
                self.assertEqual(caught.exception.code, case["expected_error"])

    def test_blocked_stress_is_not_registered_or_counted(self):
        blocked = json.loads((GROUP / "blocked-operations.json").read_text(encoding="utf-8"))
        self.assertEqual([r["tool_id"] for r in blocked["operations"]], ["GeoRockStressAnisotropy"])
        self.assertNotIn("GeoRockStressAnisotropy", {s["id"] for s in self.specs})
        for skill in self.catalog["skills"]:
            self.assertNotIn("GeoRockStressAnisotropy", skill["tool_references"])
        self.assertTrue((ROOT / "assets/github-expansion-geophysics/GeoRockStressAnisotropy.json").is_file())
        with self.assertRaises(ScientificToolError) as caught:
            implementation.rock_stress_anisotropy({"hydrostatic_strain": -0.0005, "axial_strain": -0.002})
        self.assertEqual(caught.exception.code, "unsupported_conditions")


class TestBlockedStressAnisotropyDiagnostic(unittest.TestCase):
    @unittest.expectedFailure
    def test_unequal_strain_angular_integral(self):
        """Historical known failure, NOT one of the 29 acceptance operations.

        This diagnostic intentionally calls the unmodified upstream. An unexpected
        success requires review, not automatic unblocking. No catalog registration.
        Independent I_n = integral_0^1 u^n sqrt(alpha^2+u^2) du.
        """
        from rockphypy import GM
        alpha = 0.5
        i0 = (math.sqrt(1+alpha**2) + alpha**2*math.asinh(1/alpha))/2
        i2 = ((1+alpha**2)**1.5-alpha**2*i0)/4
        i4 = ((1+alpha**2)**1.5-3*alpha**2*i2)/6
        cn, ct = 75.0, 200/3
        bw = 2/(math.pi*cn)
        cw = 4/math.pi*(1/ct-1/cn)
        gamma = 3/32*cn*ct*6*0.6*math.sqrt(0.0005)
        expected_c33 = gamma/alpha*(4*bw*i2+2*cw*i4)
        actual, _, _ = GM.johnson(20, 15, 6, 0.4, -0.0005, -0.002, path="together")
        self.assertGreater(expected_c33, 0)
        self.assertTrue(math.isclose(float(actual[2, 2]), expected_c33,
                                     rel_tol=1e-10, abs_tol=1e-12),
                        msg="BLOCKED: unequal-strain Johnson angular integral disagrees with upstream logarithm")


if __name__ == "__main__":
    unittest.main()

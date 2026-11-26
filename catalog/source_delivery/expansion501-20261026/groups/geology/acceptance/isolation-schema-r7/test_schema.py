"""Contract-only regression. No model, scientific kernel, deployment or GPU use."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

import jsonschema


ROOT = Path(__file__).resolve().parents[7]
GROUP = ROOT / "catalog/source_delivery/expansion501-20261026/groups/geology"
PINS = {"scikit-learn": "1.7.2", "numpy": "2.1.3", "scipy": "1.15.3",
        "pandas": "2.3.0", "matplotlib": "3.10.7", "jsonschema": "4.25.1"}


class IsolationSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("geology_generator", GROUP / "build_contribution.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.generated = module.gpr_isolation_schema(PINS)
        cls.catalog = json.loads((GROUP / "catalog-additions.json").read_text(encoding="utf-8"))
        matches = [t for t in cls.catalog["tools"] if t["id"] == "GeoConditionedResourceEnsemble"]
        if len(matches) != 1:
            raise AssertionError("Expected exactly one GPR definition")
        cls.tool = matches[0]
        cls.provenance_schema = cls.tool["output_schema"]["properties"]["provenance"]
        cls.schema = cls.provenance_schema["properties"]["isolation"]
        cls.validator = jsonschema.Draft202012Validator(cls.schema)

    def evidence(self):
        return {
            "profile_id": "expansion501-geology-gpr-cpu-v2",
            "profile_sha256": "1" * 64, "worker_sha256": "2" * 64,
            "python_version": "3.12.14", "python_sha256": "3" * 64,
            "build_receipt_sha256": "4" * 64, "installed_versions": dict(PINS),
            "spec_sha256": "5" * 64, "protocol": "geoagent-isolated-cpu-v2",
            "native_projects": {}, "gpu_requested": False, "runtime_install": False,
            "os_sandbox": False, "evidence_directory": "synthetic-contract-fixture/not-executed",
        }

    def assertRejected(self, value):
        self.assertFalse(self.validator.is_valid(value))

    def test_generated_catalog_matches_and_schema_is_valid(self):
        self.assertEqual(self.schema, self.generated)
        jsonschema.Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.evidence())

    def test_child_provenance_remains_valid_without_parent_evidence(self):
        value = {
            "tool": "GeoConditionedResourceEnsemble",
            "upstream_url": "https://github.com/scikit-learn/scikit-learn",
            "source_mode": "package_release",
            "reviewed_archive_commit": "25dee604bae18205b01548348388baf7a1cdfe0e",
            "installed_versions": dict(PINS), "vendored_source": [],
            "input_sha256": "0" * 64, "implementation_sha256": "0" * 64,
            "contract_sha256": "0" * 64, "output_sha256": {},
            "network_required": False, "runtime_source_correspondence": "Synthetic schema fixture only.",
        }
        validator = jsonschema.Draft202012Validator(self.provenance_schema)
        validator.validate(value)
        value["isolation"] = self.evidence()
        validator.validate(value)

    def test_every_inner_field_required(self):
        self.assertEqual(set(self.schema["required"]), set(self.evidence()))
        for field in self.evidence():
            with self.subTest(field=field):
                value = self.evidence()
                del value[field]
                self.assertRejected(value)

    def test_unknown_fields_and_native_projects_rejected(self):
        value = self.evidence()
        value["untrusted"] = "not allowed"
        self.assertRejected(value)
        value = self.evidence()
        value["native_projects"] = {"fake_native_project": {}}
        self.assertRejected(value)

    def test_exact_dependency_pins(self):
        for package in PINS:
            with self.subTest(package=package):
                value = self.evidence()
                value["installed_versions"][package] = "0.0.0"
                self.assertRejected(value)
                del value["installed_versions"][package]
                self.assertRejected(value)
        value = self.evidence()
        value["installed_versions"]["extra-package"] = "1.0.0"
        self.assertRejected(value)

    def test_fixed_protocol_and_profile(self):
        for field in ("protocol", "profile_id"):
            value = self.evidence()
            value[field] += "-untrusted"
            self.assertRejected(value)

    def test_hash_shape(self):
        for field in ("profile_sha256", "worker_sha256", "python_sha256",
                      "build_receipt_sha256", "spec_sha256"):
            for invalid in ("", "a" * 63, "g" * 64, "A" * 64, "a" * 65):
                with self.subTest(field=field, invalid=invalid):
                    value = self.evidence()
                    value[field] = invalid
                    self.assertRejected(value)

    def test_no_gpu_install_or_sandbox_claim(self):
        for field in ("gpu_requested", "runtime_install", "os_sandbox"):
            value = self.evidence()
            value[field] = True
            self.assertRejected(value)

    def test_python_and_evidence_bounds(self):
        for invalid in ("3.11.9", "3.13.1", "3.12", "3.12.14 extra"):
            value = self.evidence()
            value["python_version"] = invalid
            self.assertRejected(value)
        for invalid in ("", "x" * 4097):
            value = self.evidence()
            value["evidence_directory"] = invalid
            self.assertRejected(value)

    def test_no_runtime_profile_implicitly_enabled(self):
        self.assertNotIn("isolation_profile_id", self.tool["registration_metadata"]["runtime"])
        self.assertFalse(self.tool["metadata"]["scientific_contract"]["formal_eligible"])
        for tool in self.catalog["tools"]:
            if tool["id"] != "GeoConditionedResourceEnsemble":
                self.assertNotIn("isolation", tool["output_schema"]["properties"]["provenance"]["properties"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

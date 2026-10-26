"""Synthetic schema/context unit tests. No scientific GPR call or real profile."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest import mock
from jsonschema import Draft202012Validator, ValidationError

AREA = Path(__file__).resolve().parent
ROOT = AREA.parents[4]

def module_from(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

bridge = module_from(ROOT / "geological_agent/geology/isolated_cpu_bridge_v2.py", "plumbing_r5_bridge")
worker = module_from(ROOT / "geological_agent/geology/isolated_cpu_worker_v2.py", "plumbing_r5_worker")
SCHEMA = json.loads((AREA / "gpr-isolation.schema.json").read_text(encoding="utf-8"))

class GPRPlumbing(unittest.TestCase):
    def value(self):
        # Deliberately SYNTHETIC schema data, never an administrator profile/receipt.
        return {"profile_id": worker.GPR_PROFILE_ID, "profile_sha256": "a" * 64,
                "worker_sha256": "b" * 64, "python_version": "3.12.14", "python_sha256": "c" * 64,
                "build_receipt_sha256": "d" * 64,
                "installed_versions": {"scikit-learn": "1.7.2", "numpy": "2.1.3", "scipy": "1.15.3",
                                       "pandas": "2.3.0", "matplotlib": "3.10.7", "jsonschema": "4.25.1"},
                "spec_sha256": "e" * 64, "protocol": bridge.PROTOCOL, "native_projects": {},
                "gpu_requested": False, "runtime_install": False, "os_sandbox": False,
                "evidence_directory": "SYNTHETIC_SCHEMA_ONLY_NOT_AN_EXECUTED_JOB"}

    def validate(self, value):
        Draft202012Validator(SCHEMA).validate(value)

    def test_closed_schema_accepts_synthetic_shape(self):
        Draft202012Validator.check_schema(SCHEMA)
        self.validate(self.value())
        self.assertEqual(len(SCHEMA["required"]), 14)

    def test_unknown_property_rejected(self):
        value = self.value()
        value["user_environment"] = {}
        with self.assertRaises(ValidationError):
            self.validate(value)

    def test_all_internal_fields_required(self):
        for key in SCHEMA["required"]:
            with self.subTest(field=key):
                value = self.value()
                del value[key]
                with self.assertRaises(ValidationError):
                    self.validate(value)

    def test_strict_six_dependency_versions(self):
        for name in self.value()["installed_versions"]:
            with self.subTest(package=name):
                value = self.value()
                value["installed_versions"][name] = "0.0.0"
                with self.assertRaises(ValidationError):
                    self.validate(value)
        value = self.value()
        value["installed_versions"]["unreviewed"] = "1.0"
        with self.assertRaises(ValidationError):
            self.validate(value)

    def test_native_projects_must_be_empty(self):
        value = self.value()
        value["native_projects"]["PDAL"] = "2.9.1"
        with self.assertRaises(ValidationError):
            self.validate(value)

    def test_wrong_profile_and_true_capability_claims_rejected(self):
        for key, bad in (("profile_id", "Other"), ("gpu_requested", True),
                         ("runtime_install", True), ("os_sandbox", True)):
            with self.subTest(field=key):
                value = self.value()
                value[key] = bad
                with self.assertRaises(ValidationError):
                    self.validate(value)

    def profile(self):
        # Only the internal policy branch is under test: NOT a valid complete profile.
        return {"tool": "GeoConditionedResourceEnsemble",
                "module": "geological_agent.geology.expansion501_geology",
                "callable": "conditioned_resource_ensemble"}

    def child(self, profile):
        token = bridge.CHILD.set({"pid": os.getpid(), "tool": profile["tool"], "profile": profile})
        self.addCleanup(bridge.CHILD.reset, token)

    def test_marker_requires_child_context(self):
        self.assertIsNone(bridge.CHILD.get())
        with self.assertRaises(bridge.BridgeError):
            with worker._scientific_cpu_policy(bridge, self.profile(), worker.GPR_PROFILE_ID):
                self.fail("Untrusted policy body executed")

    def test_fixed_marker_is_set_then_restored(self):
        profile = self.profile()
        self.child(profile)
        with mock.patch.dict(os.environ, {worker._GEOLOGY_CPU_KEY: "SYNTHETIC_PRIOR_VALUE"}):
            with worker._scientific_cpu_policy(bridge, profile, worker.GPR_PROFILE_ID):
                self.assertEqual(os.environ[worker._GEOLOGY_CPU_KEY], "expansion501-geology-cpu-v1")
            self.assertEqual(os.environ[worker._GEOLOGY_CPU_KEY], "SYNTHETIC_PRIOR_VALUE")

    def test_wrong_gpr_profile_refused(self):
        profile = self.profile()
        self.child(profile)
        with self.assertRaises(bridge.BridgeError) as caught:
            with worker._scientific_cpu_policy(bridge, profile, "unreviewed-profile"):
                self.fail("Unreviewed GPR profile executed")
        self.assertEqual(caught.exception.code, "missing_dependency")

    def test_wrong_fixed_entry_refused(self):
        profile = self.profile()
        profile["callable"] = "arbitrary_function"
        self.child(profile)
        with self.assertRaises(bridge.BridgeError):
            with worker._scientific_cpu_policy(bridge, profile, worker.GPR_PROFILE_ID):
                self.fail("Wrong GPR callable executed")

    def test_other_tool_not_given_geology_marker(self):
        profile = {"tool": "IsolationFixture", "module": "isolated_fixture", "callable": "fixture"}
        self.child(profile)
        with mock.patch.dict(os.environ):
            os.environ.pop(worker._GEOLOGY_CPU_KEY, None)
            with worker._scientific_cpu_policy(bridge, profile, "FixtureProfile"):
                self.assertNotIn(worker._GEOLOGY_CPU_KEY, os.environ)

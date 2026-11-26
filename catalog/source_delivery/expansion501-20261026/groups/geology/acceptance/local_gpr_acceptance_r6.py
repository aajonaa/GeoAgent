"""Independent local GPR acceptance. Fixed private CPU profile; no remote/service/model/GPU."""
from __future__ import annotations

import copy
from dataclasses import asdict
import hashlib
import importlib
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import shutil
import sys
from threading import Event
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[6]
GROUP = REPO / "catalog/source_delivery/expansion501-20261026/groups/geology"
RUN = GROUP / "acceptance/local-r6-gpr-20261026"
SOURCE = RUN / "source"
STAGED_REGISTRY = Path("C:/Users/jona/github/expansion501-staging-20261026-r3/payload/geological_agent/geology/source_registry.py")
STAGED_REGISTRY_SHA256 = "c107ec7ab91587122fcc77c9e02756ca2aa8800319407b5d7879e651362e3576"
ID = "GeoConditionedResourceEnsemble"
MODULE = "geological_agent.geology.expansion501_geology"
PINS = {"numpy": "2.1.3", "scipy": "1.15.3", "pandas": "2.3.0",
        "matplotlib": "3.10.7", "jsonschema": "4.25.1", "scikit-learn": "1.7.2",
        "PyYAML": "6.0.3"}
COUNTS = {"direct_decorated_invocations": 0, "registered_runtime_invocations": 0}
FROZEN = {}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")

def schur_reference(args):
    """Independent scalar/2x2 inversion with stdlib exp, not sklearn or numpy.linalg."""
    observation = args["observation_coordinates_m"]
    targets = args["target_coordinates_m"]
    variance = args["prior_variance_ppm2"]
    length = args["correlation_length_m"]
    alpha = args["measurement_noise_variance_ppm2"]
    known_mean = args["known_mean_ppm"]

    def cov(a, b):
        distance = math.sqrt(math.fsum((x - y) ** 2 for x, y in zip(a, b)))
        return variance * math.exp(-distance / length)

    coo = [[cov(a, b) + (alpha if i == j else 0)
            for j, b in enumerate(observation)] for i, a in enumerate(observation)]
    if len(observation) == 1:
        inverse = [[1 / coo[0][0]]]
    elif len(observation) == 2:
        determinant = coo[0][0] * coo[1][1] - coo[0][1] * coo[1][0]
        if determinant <= 0:
            raise ValueError("Independent oracle requires a nonsingular covariance.")
        inverse = [[coo[1][1] / determinant, -coo[0][1] / determinant],
                   [-coo[1][0] / determinant, coo[0][0] / determinant]]
    else:
        raise ValueError("Reference fixtures deliberately use at most two observations.")
    cto = [[cov(t, o) for o in observation] for t in targets]
    weights = [[math.fsum(row[k] * inverse[k][j] for k in range(len(observation)))
                for j in range(len(observation))] for row in cto]
    centered = [y - known_mean for y in args["observed_values_ppm"]]
    means = [known_mean + math.fsum(w * y for w, y in zip(row, centered)) for row in weights]
    conditional = [[cov(a, b) - math.fsum(w * c for w, c in zip(weights[i], cto[j]))
                    for j, b in enumerate(targets)] for i, a in enumerate(targets)]
    return means, conditional

class LocalGPR(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from jsonschema import Draft202012Validator
        from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError
        from legacy.ToolsAgent.ToolsFuns import source_contracts
        from geological_agent.geology import source_registry
        from geological_agent.tools import ToolRegistry, ToolExecutor, ToolExecutionContext
        from geological_agent.contracts import ToolCall
        from geological_agent.settings import Settings
        cls.Validator = Draft202012Validator
        cls.Error = ScientificToolError
        cls.ToolExecutionContext = ToolExecutionContext
        cls.ToolCall = ToolCall
        cls.Settings = Settings
        cls.spec = source_contracts.definition(ID)
        cls.fixture = copy.deepcopy(cls.spec["example_arguments"])
        cls.registry = ToolRegistry()
        cls.registered = source_registry.register(cls.registry)
        cls.executor = ToolExecutor(cls.registry)
        cls.adapter = importlib.import_module(MODULE)
        cls.fn = staticmethod(cls.adapter.conditioned_resource_ensemble)

    def direct(self, args=None, json_input=False):
        submitted = copy.deepcopy(self.fixture if args is None else args)
        original = copy.deepcopy(submitted)
        if json_input:
            submitted = json.dumps(submitted, allow_nan=False)
        COUNTS["direct_decorated_invocations"] += 1
        result = self.fn(submitted)
        if not json_input:
            self.assertEqual(submitted, original)
        self.Validator(self.spec["output_schema"]).validate(result)
        self.assertEqual(result["artifacts"], [])
        self.assertEqual(result["provenance"]["output_sha256"], {})
        self.assertEqual(result["provenance"]["tool"], ID)
        self.assertEqual(result["provenance"]["installed_versions"]["scikit-learn"], "1.7.2")
        self.assertEqual(result["provenance"]["implementation_sha256"],
                         digest(SOURCE / "geological_agent/geology/expansion501_geology.py"))
        for key in ("input_sha256", "implementation_sha256", "contract_sha256"):
            self.assertRegex(result["provenance"][key], r"^[0-9a-f]{64}$")
        self.assertIs(result["optimizer_used"], False)
        self.assertIs(result["jitter_added"], False)
        return result

    def numerical(self, result, args):
        expected_mean, expected_covariance = schur_reference(args)
        self.assertEqual(len(result["conditional_mean"]), len(expected_mean))
        for actual, expected in zip(result["conditional_mean"], expected_mean):
            self.assertTrue(math.isclose(actual, expected, abs_tol=1e-12, rel_tol=0))
        self.assertEqual(len(result["conditional_covariance"]), len(expected_covariance))
        for actual_row, expected_row in zip(result["conditional_covariance"], expected_covariance):
            self.assertEqual(len(actual_row), len(expected_row))
            for actual, expected in zip(actual_row, expected_row):
                self.assertTrue(math.isclose(actual, expected, abs_tol=1e-12, rel_tol=0),
                                (actual, expected))

    def reject(self, args, code="invalid_arguments"):
        COUNTS["direct_decorated_invocations"] += 1
        with self.assertRaises(self.Error) as caught:
            self.fn(copy.deepcopy(args))
        self.assertEqual(caught.exception.code, code)
        self.assertIs(caught.exception.retryable, False)
        self.assertTrue(str(caught.exception))
        return caught.exception

    def test_01_fixed_source_registration_schemas_pins(self):
        self.assertEqual(self.registered, {ID: ID})
        self.assertEqual(self.registry.names(), (ID,))
        self.assertEqual(self.registry.get(ID).definition.input_schema, self.spec["input_schema"])
        self.assertEqual(self.registry.get(ID).definition.result_schema, self.spec["output_schema"])
        self.assertIs(self.registry.get(ID).pure, False)
        for schema in (self.spec["input_schema"], self.spec["output_schema"]):
            self.Validator.check_schema(schema)
            self.assertIs(schema["additionalProperties"], False)
        for package, version in PINS.items():
            self.assertEqual(importlib.metadata.version(package), version)
        from legacy.ToolsAgent.ToolsFuns.source_contracts import validate_registration_metadata
        validate_registration_metadata(self.spec)

    def test_02_decorated_dictionary_full_covariance(self):
        result = self.direct()
        self.numerical(result, self.fixture)
        self.assertLessEqual(abs(result["conditional_covariance"][0][1]), 1e-12)
        save(RUN / "noiseless-direct-result.json", result)

    def test_03_decorated_json_full_covariance(self):
        result = self.direct(json_input=True)
        self.numerical(result, self.fixture)

    def test_04_registered_executor_typed_result(self):
        context = self.ToolExecutionContext("gpr-r6-local", RUN / "workspace", (ID,),
                                           self.Settings(tool_timeout_seconds=120), Event())
        COUNTS["registered_runtime_invocations"] += 1
        result = self.executor.execute(self.ToolCall("joint-covariance", ID, self.fixture), context)
        self.assertEqual(result.status, "ok", result.error)
        self.assertIsNone(result.error)
        self.assertFalse(result.cached)
        self.assertEqual(result.artifacts, ())
        self.Validator(self.spec["output_schema"]).validate(result.data)
        self.numerical(result.data, self.fixture)
        self.assertEqual(result.data["provenance"]["installed_versions"]["scikit-learn"], "1.7.2")
        save(RUN / "registered-runtime-result.json", asdict(result))

    def test_05_explicit_measurement_noise_schur_covariance(self):
        args = copy.deepcopy(self.fixture)
        args["measurement_noise_variance_ppm2"] = 1
        result = self.direct(args)
        self.numerical(result, args)
        self.assertTrue(math.isclose(result["conditional_covariance"][0][1],
                                    .8 * math.exp(-2), abs_tol=1e-12, rel_tol=0))
        save(RUN / "noisy-direct-result.json", result)

    def test_06_two_observation_full_schur_matrix(self):
        args = copy.deepcopy(self.fixture)
        args.update(observation_coordinates_m=[[-1, 0, 0], [1, 0, 0]],
                    observed_values_ppm=[4, 8], target_coordinates_m=[[-2, 0, 0], [0, 0, 0], [2, 0, 0]],
                    known_mean_ppm=5, prior_variance_ppm2=9, correlation_length_m=2,
                    measurement_noise_variance_ppm2=.25)
        self.numerical(self.direct(args), args)

    def test_07_observed_target_exact_conditioning_psd_boundary(self):
        args = copy.deepcopy(self.fixture)
        args["target_coordinates_m"] = [[0, 0, 0], [1, 0, 0]]
        result = self.direct(args)
        self.numerical(result, args)
        self.assertEqual(result["conditional_covariance"][0][0], 0)
        self.assertTrue(all(row[0] == 12 for row in result["realizations"]))

    def test_08_seeded_joint_realizations_repeat_without_clipping(self):
        first, second = self.direct(), self.direct()
        self.assertEqual(first["realizations"], second["realizations"])
        self.assertIs(first["negative_realizations_clipped"], False)

    def test_09_joint_sample_covariance_statistical_check(self):
        args = copy.deepcopy(self.fixture)
        args["realization_count"] = 2048
        result = self.direct(args)
        self.numerical(result, args)
        draws = result["realizations"]
        n = len(draws)
        means = [math.fsum(row[j] for row in draws) / n for j in range(2)]
        expected = schur_reference(args)[1]
        for i in range(2):
            for j in range(2):
                empirical = math.fsum((row[i] - means[i]) * (row[j] - means[j]) for row in draws) / (n - 1)
                # Predeclared Gaussian sample-covariance standard error, not a fitted tolerance.
                standard_error = math.sqrt((expected[i][i] * expected[j][j] + expected[i][j] ** 2) / (n - 1))
                self.assertLessEqual(abs(empirical - expected[i][j]), 5 * standard_error)

    def test_10_duplicate_conditioning_rejected(self):
        args = copy.deepcopy(self.fixture)
        args.update(observation_coordinates_m=[[0, 0, 0], [0, 0, 0]], observed_values_ppm=[12, 12])
        error = self.reject(args)
        self.assertIn("Repeated conditioning", str(error))

    def test_11_duplicate_targets_rejected(self):
        args = copy.deepcopy(self.fixture)
        args["target_coordinates_m"] = [[1, 0, 0], [1, 0, 0]]
        self.assertIn("Repeated target", str(self.reject(args)))

    def test_12_near_singular_conditioning_fails_without_jitter(self):
        args = copy.deepcopy(self.fixture)
        args.update(observation_coordinates_m=[[0, 0, 0], [1e-14, 0, 0]], observed_values_ppm=[12, 12])
        self.assertIn("no jitter", str(self.reject(args)))

    def test_13_non_psd_upstream_result_fault_injection_is_rejected(self):
        import numpy as np
        # Explicit fault injection verifies the boundary guard, NOT a numeric oracle.
        with mock.patch("sklearn.gaussian_process.GaussianProcessRegressor.predict",
                        return_value=(np.array([1., 1.]), np.array([[1., 2.], [2., 1.]]))):
            with mock.patch("sklearn.gaussian_process.GaussianProcessRegressor.sample_y") as sample:
                self.assertIn("not PSD", str(self.reject(self.fixture, "invalid_result")))
                sample.assert_not_called()

    def test_14_physical_parameter_domains(self):
        for field, value in (("prior_variance_ppm2", 0), ("measurement_noise_variance_ppm2", -1),
                             ("correlation_length_m", 0), ("observed_values_ppm", [-1])):
            with self.subTest(field=field):
                args = copy.deepcopy(self.fixture)
                args[field] = value
                self.reject(args)

    def test_15_nonfinite_arguments(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=repr(value)):
                args = copy.deepcopy(self.fixture)
                args["prior_variance_ppm2"] = value
                self.reject(args)

    def test_16_alignment_and_output_budget(self):
        args = copy.deepcopy(self.fixture)
        args["observed_values_ppm"] = [12, 12]
        self.reject(args)
        args = copy.deepcopy(self.fixture)
        args["target_coordinates_m"] = [[i, 0, 0] for i in range(128)]
        args["realization_count"] = 4096
        self.reject(args, "resource_limit")

    def test_17_arbitrary_dispatch_rejected(self):
        for name in ("module", "function", "code", "script", "output_dir", "executable"):
            with self.subTest(field=name):
                args = copy.deepcopy(self.fixture)
                args[name] = "not_allowed"
                self.reject(args)

    def test_18_wrong_dependency_retains_native_hint(self):
        with mock.patch("importlib.metadata.version", return_value="0.0.0-gpr-negative"):
            error = self.reject(self.fixture, "missing_dependency")
        self.assertEqual(str(error), "Install the reviewed dependency release for scikit-learn")

    def test_19_missing_cpu_identity_is_not_a_pass(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("GEOAGENT_EXPANSION501_GEOLOGY_CPU", None)
            self.assertIn("Parent-bound private CPU environment",
                          str(self.reject(self.fixture, "missing_dependency")))

    def test_20_runtime_domain_failure_preserves_type_code_retryability(self):
        args = copy.deepcopy(self.fixture)
        args["measurement_noise_variance_ppm2"] = -1
        context = self.ToolExecutionContext("gpr-r6-negative", RUN / "workspace", (ID,),
                                           self.Settings(tool_timeout_seconds=120), Event())
        COUNTS["registered_runtime_invocations"] += 1
        result = self.executor.execute(self.ToolCall("invalid-alpha", ID, args), context)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error.code, "invalid_arguments")
        self.assertIs(result.error.retryable, False)
        self.assertEqual(result.artifacts, ())

def main():
    if sys.version_info[:3] != (3, 12, 14) or Path(sys.prefix).resolve() != (RUN / "venv").resolve():
        raise RuntimeError("Use only the authorized fresh local Python 3.12.14 GPR venv.")
    if sys.prefix == sys.base_prefix:
        raise RuntimeError("Shared/base interpreter execution forbidden.")
    flow_path = Path("C:/Users/jona/.codex/skills/flowing/scripts")
    sys.path.insert(0, str(flow_path))
    from flowing import Flow, task
    if (RUN / "gpr-report.json").exists() or SOURCE.exists():
        raise RuntimeError("Never overwrite an earlier acceptance run.")

    @task
    def freeze_private_source():
        expected_pins = {p: importlib.metadata.version(p) for p in PINS}
        if expected_pins != PINS:
            raise RuntimeError("Private exact-pins precondition failed: " + repr(expected_pins))
        if digest(STAGED_REGISTRY) != STAGED_REGISTRY_SHA256:
            raise RuntimeError("Parent r3 source-registry precondition mismatch; do not rebase.")
        relative_files = [
            "geological_agent/__init__.py", "geological_agent/geology/__init__.py",
            "geological_agent/geology/expansion501_geology.py",
            "geological_agent/geology/collection_contracts.py",
            "legacy/ToolsAgent/ToolsFuns/source_contracts.py",
            "legacy/ToolsAgent/ToolsFuns/GeoEval/scientific_tools.py",
            "geological_agent/skills.py", "geological_agent/tools.py", "geological_agent/contracts.py",
            "geological_agent/settings.py", "geological_agent/tool_evidence.py"]
        for optional in ("geological_agent/geology/isolated_cpu_bridge_v2.py",
                         "geological_agent/geology/worker_v2.py"):
            if (REPO / optional).is_file():
                relative_files.append(optional)
        records = []
        for relative in relative_files + ["geological_agent/geology/source_registry.py"]:
            origin = STAGED_REGISTRY if relative.endswith("/source_registry.py") else REPO / relative
            before = digest(origin)
            destination = SOURCE / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origin, destination)
            if before != digest(destination) or before != digest(origin):
                raise RuntimeError("Source changed while copying: " + relative)
            records.append({"origin": str(origin), "relative": relative, "sha256": before})
            FROZEN[str(origin)] = before
        catalog = json.loads((GROUP / "catalog-additions.json").read_text(encoding="utf-8"))
        tools = [x for x in catalog["tools"] if x["id"] == ID]
        if len(tools) != 1:
            raise RuntimeError("Exactly one actual GPR tool contribution required.")
        save(SOURCE / "catalog/registry.json", {"tools": tools, "skills": []})
        for name in ("home", "cache", "tmp", "mpl", "numba", "workspace"):
            (RUN / name).mkdir(exist_ok=True)
        environment = {
            "GEOAGENT_EXPANSION501_GEOLOGY_CPU": "expansion501-geology-cpu-v1",
            "CUDA_VISIBLE_DEVICES": "", "NVIDIA_VISIBLE_DEVICES": "void",
            "HIP_VISIBLE_DEVICES": "", "ROCR_VISIBLE_DEVICES": "", "ZE_AFFINITY_MASK": "",
            "JAX_PLATFORMS": "cpu", "JAX_PLATFORM_NAME": "cpu",
            "GEMPY_USE_GPU": "False", "GEMPY_GPU_FALLBACK": "False", "MPLBACKEND": "Agg",
            "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false",
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                     "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS"):
            environment[name] = "2"
        for name, leaf in (("HOME", "home"), ("USERPROFILE", "home"), ("XDG_CACHE_HOME", "cache"),
                           ("TMPDIR", "tmp"), ("TEMP", "tmp"), ("TMP", "tmp"),
                           ("MPLCONFIGDIR", "mpl"), ("NUMBA_CACHE_DIR", "numba")):
            environment[name] = str(RUN / leaf)
        os.environ.update(environment)
        sys.path.insert(0, str(SOURCE))
        save(RUN / "source-preconditions.json", {"files": records,
            "catalog_scope": "private_group_only_one_entry_not_production_catalog",
            "parent_whitelist_source": str(STAGED_REGISTRY),
            "v2_main_runtime_dispatch": "not_tested", "environment": environment,
            "installed_direct_pins": expected_pins})
        save(RUN / "installed-distributions.json",
             sorted([{"name": d.metadata["Name"], "version": d.version}
                     for d in importlib.metadata.distributions()], key=lambda x: x["name"].lower()))
        return {"ready": True, "file_count": len(records)}

    @task(depends_on=[freeze_private_source],
          when=lambda freeze_private_source: freeze_private_source["ready"])
    def direct_and_registered_acceptance(freeze_private_source):
        stream = io.StringIO()
        suite = unittest.TestLoader().loadTestsFromTestCase(LocalGPR)
        patches = [mock.patch(name, side_effect=AssertionError("No network during CPU acceptance"))
                   for name in ("socket.create_connection", "socket.getaddrinfo",
                                "socket.socket.connect", "socket.socket.connect_ex")]
        for patcher in patches:
            patcher.start()
        try:
            result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        finally:
            for patcher in reversed(patches):
                patcher.stop()
        (RUN / "gpr-tests.log").write_text(stream.getvalue(), encoding="utf-8", newline="\n")
        report = {"tool_id": ID, "actual_provider": "scikit-learn==1.7.2",
            "scope": "local_windows_python312_private_direct_and_group_registered_runtime",
            "executed_unique_tests": result.testsRun, "passed": result.testsRun - len(result.failures) - len(result.errors),
            "failures": [{"test": str(t), "traceback": trace} for t, trace in result.failures],
            "errors": [{"test": str(t), "traceback": trace} for t, trace in result.errors],
            "skipped": result.skipped, "counts": dict(COUNTS),
            "independent_reference": "Scalar/2x2 analytic inversion of exponential covariance; full Schur complement, no upstream replay.",
            "negative_psd_evidence": "Explicit upstream-predict fault injection, not a naturally produced covariance or numerical oracle.",
            "v2_cross_interpreter_main_runtime": "not_run", "linux_production_acceptance": "not_run",
            "model_workflow": "not_run", "formal_eligible": False, "deployment": "not_deployed",
            "source_status_change": "Only local evidence may advance; no claim of production integration."}
        save(RUN / "gpr-report.json", report)
        if not result.wasSuccessful():
            raise RuntimeError("Local GPR failure preserved; report before any repair/retry.")
        return {"passed": result.testsRun, "counts": dict(COUNTS)}

    @task(depends_on=[freeze_private_source, direct_and_registered_acceptance],
          when=lambda freeze_private_source, direct_and_registered_acceptance:
              direct_and_registered_acceptance["passed"] == 20)
    def source_stability_gate(freeze_private_source, direct_and_registered_acceptance):
        stability = {path: digest(Path(path)) == expected for path, expected in FROZEN.items()}
        save(RUN / "source-stability.json", {"unchanged": all(stability.values()), "files": stability})
        if not all(stability.values()):
            raise RuntimeError("Source changed during local acceptance; do not promote the result.")
        return {**direct_and_registered_acceptance, "source_unchanged": True,
                "integration": "private_group_registry_only_not_v2_or_production"}

    flow = Flow(source_stability_gate, max_workers=1, fail_fast=True, journal_path=str(RUN / "gpr-flow.jsonl"))
    flow.run()
    print(json.dumps(flow.value(source_stability_gate), ensure_ascii=False))

if __name__ == "__main__":
    main()


"""Local stdlib protocol/reference gates; scientific direct calls are opt-in.

Skipped scientific tests are NOT passed, accepted, or integrated operations.
The known new worker error-classification failure is intentionally retained.
"""
import ast
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[7]
ADAPTER = ROOT / "geological_agent/geology/expansion501_geophysics.py"
WORKER = ROOT / "geological_agent/geology/expansion501_geophysics/fixed_cpu_entry.py"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from reference_oracles_r6 import marchenko_reference, crosshole_reference


class Rejected(Exception):
    pass


def reject(message, code="invalid_arguments"):
    raise Rejected(code + ": " + message)


tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
names = {"_E501R6SolverLog", "_e501r6_lsqr_report", "_e501r6_scalar"}
nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
namespace = {"reject": reject}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ADAPTER), "exec"), namespace)
parse = namespace["_e501r6_lsqr_report"]
scalar = namespace["_e501r6_scalar"]
Log = namespace["_E501R6SolverLog"]
spec = importlib.util.spec_from_file_location("fixed_geophysics_worker_under_test", WORKER)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

REPORT = ("LSQR finished\nAx - b is small enough\n"
          "istop =       1   r1norm = 1.0e-10   anorm = 1.0e+00 arnorm = 1.0e-10\n"
          "itn   =       3   r2norm = 1.0e-10   acond = 1.0e+00 xnorm = 1.0e+00\n")


class LocalProtocolAndReference(unittest.TestCase):
    def test_actual_public_report_layout(self):
        self.assertEqual(parse(REPORT, 20), {"stop_code": 1, "iterations": 3})

    def test_limit_is_not_claimed_success(self):
        self.assertEqual(parse(REPORT.replace("istop =       1", "istop =       7"), 20)["stop_code"], 7)

    def test_missing_final_report_rejected(self):
        with self.assertRaises(Rejected):
            parse("early return without a structured summary", 20)

    def test_duplicate_report_rejected(self):
        with self.assertRaises(Rejected):
            parse(REPORT + REPORT, 20)

    def test_iteration_overflow_rejected(self):
        with self.assertRaises(Rejected):
            parse(REPORT, 2)

    def test_zero_iterations_rejected(self):
        with self.assertRaises(Rejected):
            parse(REPORT.replace("itn   =       3", "itn   =       0"), 20)

    def test_rounded_norm_is_not_the_oracle(self):
        self.assertEqual(parse(REPORT.replace("1.0e-10", "9.9e+09"), 20)["iterations"], 3)

    def test_solver_log_has_live_bound(self):
        log = Log()
        log.write("x" * 32768)
        with self.assertRaises(Rejected):
            log.write("x")

    def test_bool_is_not_physical_number(self):
        with self.assertRaises(Rejected):
            scalar(True, "velocity", 0, 100)

    def test_nonfinite_rejected(self):
        with self.assertRaises(Rejected):
            scalar(float("inf"), "velocity", 0, 100)

    def test_fractional_iteration_rejected(self):
        with self.assertRaises(Rejected):
            scalar(2.5, "iterations", 1, 20, True)

    def test_request_valid_json(self):
        self.assertEqual(worker.decode_request(b'{"a":[1,2]}'), {"a": [1, 2]})

    def test_request_duplicate_key_rejected(self):
        with self.assertRaises(ValueError):
            worker.decode_request(b'{"a":1,"a":2}')

    def test_request_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            worker.decode_request(b'{"a":1e999}')

    def test_request_size_bounded(self):
        with self.assertRaises(worker.WorkerFailure):
            worker.decode_request(b" " * 262145)

    def test_request_requires_object(self):
        with self.assertRaises(ValueError):
            worker.decode_request(b"[]")

    def test_worker_invalid_json_error_classification(self):
        env = dict(os.environ, CUDA_VISIBLE_DEVICES="", NVIDIA_VISIBLE_DEVICES="none",
                   HIP_VISIBLE_DEVICES="", ROCR_VISIBLE_DEVICES="", OPENBLAS_NUM_THREADS="2",
                   OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", PYTHONDONTWRITEBYTECODE="1",
                   LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false")
        completed = subprocess.run(
            [sys.executable, str(WORKER), worker.IDS[0]],
            input=b'{"a":1,"a":2}', stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, timeout=10, check=False)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout)["error"]["code"], "invalid_arguments")

    def test_independent_fraction_oracle_has_nonzero_coupling(self):
        args, result, coda = marchenko_reference()
        self.assertTrue(any(value != 0 for value in coda))
        self.assertGreater(max(result["focusing_upgoing"][0]), 0)
        self.assertEqual(args["reflection_response"][0][0][1:3], [0.25, 0.125])

    def test_two_layer_traveltime_oracle(self):
        args = crosshole_reference()
        self.assertEqual(args["traveltime_s"][:2], [0.01, 0.01])
        self.assertAlmostEqual(args["traveltime_s"][2], 1.0 / 150.0, places=15)
        self.assertNotEqual(args["traveltime_s"][0], args["traveltime_s"][2])


@unittest.skipUnless(os.environ.get("EXPANSION501_R6_RUN_SCIENCE") == "1",
                     "Requires reviewed private Python 3.12 environment and parent-staged pending schemas")
class PendingScientificDirectCalls(unittest.TestCase):
    def test_marchenko_nonzero_rational_coupled_reference(self):
        sys.path.insert(0, str(ROOT))
        from geological_agent.geology.expansion501_geophysics import GeoSeismicMarchenkoRedatuming
        args, expected, _ = marchenko_reference()
        result = GeoSeismicMarchenkoRedatuming(json.dumps(args))
        for key, rows in expected.items():
            for observed, reference in zip(result["values"][key][0], rows[0], strict=True):
                self.assertAlmostEqual(observed, float(reference), delta=1e-7)
        self.assertEqual(result["diagnostics"]["convergence"], "coupled_residuals_satisfied")
        self.assertLessEqual(result["diagnostics"]["equation_one_relative_residual"], 1e-7)
        self.assertLessEqual(result["diagnostics"]["equation_two_relative_residual"], 1e-7)
        self.assertEqual(result["artifacts"], [])
        self.assertEqual(result["provenance"]["installed_versions"]["pylops"], "2.6.0")

    def test_marchenko_negative_receiver_shape(self):
        sys.path.insert(0, str(ROOT))
        from geological_agent.geology.expansion501_geophysics import GeoSeismicMarchenkoRedatuming
        from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError
        args, _, _ = marchenko_reference()
        args["direct_arrival"] = [[1.0] * 9]
        with self.assertRaises(ScientificToolError):
            GeoSeismicMarchenkoRedatuming(args)

    def test_tomography_heterogeneous_observation_reference(self):
        sys.path.insert(0, str(ROOT))
        from geological_agent.geology.expansion501_geophysics import GeoSeismicTraveltimeTomography
        args = crosshole_reference()
        result = GeoSeismicTraveltimeTomography(args)
        for observed, reference, sigma in zip(result["values"]["predicted_traveltime_s"],
                                               args["traveltime_s"], args["uncertainty_s"], strict=True):
            self.assertLessEqual(abs(observed - reference), 3 * sigma)
        self.assertIsNone(result["diagnostics"]["upstream_stop_code"])
        self.assertEqual(result["diagnostics"]["convergence"], "not_certified")
        self.assertEqual(result["provenance"]["installed_versions"]["pgcore"], "1.6.0")

    def test_tomography_missing_error_rejected(self):
        sys.path.insert(0, str(ROOT))
        from geological_agent.geology.expansion501_geophysics import GeoSeismicTraveltimeTomography
        from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError
        args = crosshole_reference()
        args["uncertainty_s"][0] = 0.0
        with self.assertRaises(ScientificToolError):
            GeoSeismicTraveltimeTomography(args)


if __name__ == "__main__":
    unittest.main(verbosity=2)


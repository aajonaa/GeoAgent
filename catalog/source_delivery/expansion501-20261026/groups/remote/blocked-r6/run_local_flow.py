"""Local-only Flow gates. No remote transport, installation, or scientific imports."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest

# The reviewed local skill runner is external development tooling, never a runtime dependency.
FLOW_ROOT = Path("C:/Users/jona/.codex/skills/flowing/scripts")
sys.path.insert(0, str(FLOW_ROOT))
from flowing import Flow, task

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]


@task
def evidence():
    data = json.loads((HERE / "assessment.json").read_text(encoding="utf-8"))
    return data


def local_scope(evidence):
    expected = {
        "GeoSARSigma0Calibration", "GeoInSARClosureAmbiguityCorrection",
        "GeoInSARTroposphericDelay", "GeoInSARSolidEarthTideCorrection",
        "GeoInSARMultilookClosureBias", "GeoInSARSentinelInterplatformRangeBias",
        "GeoRemoteAtmosphericRadiativeTransfer", "GeoRemoteCanopySoilRadiativeTransfer",
    }
    rows = evidence["operations"]
    if len(rows) != 8 or {x["id"] for x in rows} != expected:
        raise ValueError("Incomplete or duplicate blocked-candidate coverage.")
    permissions = evidence["permissions"]
    if (permissions["remote_setup"] or permissions["remote_transfer"] or permissions["install"]
            or permissions["deployment"] or permissions["gpu"]):
        raise ValueError("This Flow is exclusively offline local contract preparation.")
    if any(x["state"] != "blocked" or x["formal_eligible"] for x in rows):
        raise ValueError("Missing bridge/scientific gates cannot be promoted by contract tests.")


@task(depends_on=[evidence], validate=local_scope)
def contract_tests(evidence):
    path = HERE / "test_blocked_contracts.py"
    spec = importlib.util.spec_from_file_location("remote_r6_contract_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(module.ContractTests)
    log = io.StringIO()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    return {
        "executed": result.testsRun, "failures": len(result.failures),
        "errors": len(result.errors), "skipped": len(result.skipped),
        "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
        "successful": result.wasSuccessful(), "log": log.getvalue(),
        "failure_details": [{"test": str(t), "traceback": trace}
                            for t, trace in result.failures + result.errors],
    }


@task(depends_on=[evidence, contract_tests])
def handoff(evidence, contract_tests):
    tracked = [
        ROOT / "geological_agent/geology/expansion501_remote/blocked_support.py",
        HERE / "test_blocked_contracts.py", HERE / "run_local_flow.py",
        HERE / "assessment.json", HERE / "preflight-schemas.json", HERE / "sources.json",
        ROOT / "assets/expansion501-remote/blocked-r6-synthetic.json",
    ]
    return {
        "revision": "blocked-r6", "python": sys.version, "scope": "stdlib_preflight_contracts_only",
        "source_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"):
                          hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked},
        "contract_tests": contract_tests, "local_scientific_tests_executed": 0,
        "remote_scientific_tests_executed": 0, "new_registered_tools": 0,
        "new_integrated_tools": 0, "new_certified_tools": 0,
        "remaining_blocked": [x["id"] for x in evidence["operations"]],
        "remote_policy": "prior_denial_not_retried", "deployment": "not_deployed",
        "submission": "not_submitted", "model_workflow": "not_run",
    }


@task(depends_on=[handoff])
def persist_report(handoff):
    # Exclusive creation preserves earlier attempts rather than rewriting failures.
    path = HERE / "local-contract-report-r1.json"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(handoff, handle, indent=2, ensure_ascii=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"report": str(path), "contract_tests":
                      {k: handoff["contract_tests"][k] for k in
                       ("executed", "passed", "failures", "errors", "skipped")},
                      "scientific_tests_executed": 0, "blocked": 8}))
    return handoff["contract_tests"]["successful"]


if __name__ == "__main__":
    flow = Flow(persist_report, max_workers=1)
    flow.run()
    raise SystemExit(0 if flow.value(persist_report) else 1)

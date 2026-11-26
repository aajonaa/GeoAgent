"""Run the explicitly approved, CPU-only expansion acceptance DAG."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET


GEOPHYSICS_MODULE = "tests_local/test_github_expansion_geophysics.py"
DIAGNOSTIC_CLASS = "TestBlockedStressAnisotropyDiagnostic"
DIAGNOSTIC_TEST = "test_unequal_strain_angular_integral"
DIAGNOSTIC_NODE = GEOPHYSICS_MODULE + "::" + DIAGNOSTIC_CLASS + "::" + DIAGNOSTIC_TEST


def group_selections(group):
    selections = ["tests_local/test_github_expansion_" + group + ".py"]
    if group == "geophysics":
        selections.append("--deselect=" + DIAGNOSTIC_NODE)
    return selections


def classify_historical_diagnostic(return_code, cases):
    """Record exactly one known defect, never convert it into a passing case."""
    if return_code != 0 or len(cases) != 1:
        raise ValueError("Historical diagnostic must run exactly once with its original expected-failure outcome")
    case = cases[0]
    if case.get("name") != DIAGNOSTIC_TEST or not case.get("classname", "").endswith("." + DIAGNOSTIC_CLASS):
        raise ValueError("Unexpected historical diagnostic identity")
    skips = list(case.findall("skipped"))
    if (len(skips) != 1 or skips[0].get("type") != "pytest.xfail"
            or case.find("failure") is not None or case.find("error") is not None):
        raise ValueError("Historical defect changed outcome; manual review required")
    return {
        "outcome": "known_upstream_failure",
        "expected_failures": 1,
        "passed_cases": 0,
        "counted_as_available_tool": False,
        "recorded": True,
    }


def write_new(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True)
    parser.add_argument("--flow-module", required=True)
    args = parser.parse_args()
    stage = Path(args.stage).resolve(strict=True)
    candidate = (stage / "candidate").resolve(strict=True)
    candidate.relative_to(stage)
    reports = stage / "reports" / "cpu-acceptance"
    reports.mkdir()
    env = os.environ.copy()
    for name in ("CUDA_VISIBLE_DEVICES", "HIP_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES"):
        env[name] = ""
    env["NVIDIA_VISIBLE_DEVICES"] = "void"
    for name, suffix in {
        "HOME": "home", "XDG_CACHE_HOME": "cache", "MPLCONFIGDIR": "mpl",
        "NUMBA_CACHE_DIR": "cache/numba", "PYTHONPYCACHEPREFIX": "bytecode",
        "TMPDIR": "tmp",
    }.items():
        directory = stage / suffix
        directory.mkdir(parents=True, exist_ok=True)
        env[name] = str(directory)
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
        env[name] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_CONFIG_FILE"] = "/dev/null"
    env["PYTHONPATH"] = os.pathsep.join([
        str(candidate), str(stage / "deps"),
        "/data/wangjian/github-minerals-20261025-r3/deps",
        "/data/wangjian/geoagent-literature49-fix-20261024-r1/deps",
        "/data/wangjian/geotoolagent-context-postgres/python",
    ])
    os.environ.update(env)
    sys.dont_write_bytecode = True
    flow_file = Path(args.flow_module).resolve(strict=True)
    expected_flow = Path("/data/wangjian/earth-python-coverage101-offline-originals-20261022/u13-parent-r3/flowing.py").resolve(strict=True)
    if flow_file != expected_flow:
        raise ValueError("Unrecognized Flow implementation")
    spec = importlib.util.spec_from_file_location("flowing", flow_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules["flowing"] = module
    spec.loader.exec_module(module)
    Flow, TaskDef = module.Flow, module.TaskDef

    groups = ("geophysics", "remote", "geology", "spatial")
    contributions = candidate / "catalog/source_delivery/github-expansion-20261025/groups"
    ids = []
    group_counts = {}
    for group in groups:
        data = json.loads((contributions / group / "catalog-additions.json").read_text(encoding="utf-8"))
        group_ids = [row["id"] for row in data["tools"]]
        group_counts[group] = len(group_ids)
        ids.extend(group_ids)
    baseline_nodes_file = Path("/data/wangjian/github-expansion120-20261025-r1/reports/baseline229-regression-nodes.json")
    baseline_nodes = json.loads(baseline_nodes_file.read_text(encoding="utf-8"))
    if not isinstance(baseline_nodes, list) or not all(isinstance(node, str) for node in baseline_nodes):
        raise TypeError("The frozen baseline node list must contain strings")
    native_prefix = "tests_local/test_professional_catalog.py::test_every_ready_source_executes_through_native_runtime["
    new_nodes = [native_prefix + name.encode("unicode_escape").decode("ascii") + "]" for name in ids]
    manifest = {
        "new_tools": len(ids), "group_counts": group_counts,
        "baseline_professional_tools": 229,
        "native_new_nodes": new_nodes, "baseline_selections": baseline_nodes,
        "production_modified": False, "gpu_enabled": False,
        "dependencies": env["PYTHONPATH"].split(os.pathsep),
        "separate_historical_diagnostic": DIAGNOSTIC_NODE,
        "historical_diagnostic_counted_as_pass": False,
    }
    write_new(reports / "selection.json", manifest)

    def preflight(*_args, **_kwargs):
        if len(ids) < 101 or len(set(ids)) != len(ids):
            raise ValueError("At least 101 unique additional operations are required")
        old_native = [node for node in baseline_nodes if node.startswith(native_prefix)]
        if len(old_native) != 229 or len(set(old_native)) != 229:
            raise ValueError("The complete original 229-operation baseline is required")
        if set(old_native).intersection(new_nodes):
            raise ValueError("Additional IDs overlap the deployed baseline")
        return manifest

    def run_suite(label, selections, minimum_cases):
        log = reports / (label + ".log")
        xml = reports / (label + ".xml")
        command = [sys.executable, "-m", "pytest", "-q", *selections, "--junitxml=" + str(xml)]
        started = time.monotonic()
        receipt = {"label": label, "command": command, "cwd": str(candidate)}
        try:
            with log.open("x", encoding="utf-8") as output:
                process = subprocess.run(command, cwd=candidate, env=env, stdout=output, stderr=subprocess.STDOUT)
            receipt["return_code"] = process.returncode
            receipt["seconds"] = time.monotonic() - started
            if xml.is_file():
                root = ET.parse(xml).getroot()
                cases = list(root.iter("testcase"))
                receipt["junit_cases"] = len(cases)
                receipt["failures"] = sum(case.find("failure") is not None for case in cases)
                receipt["errors"] = sum(case.find("error") is not None for case in cases)
                receipt["skipped"] = sum(case.find("skipped") is not None for case in cases)
                receipt["passed_cases"] = sum(not any(case.find(tag) is not None for tag in ("failure", "error", "skipped")) for case in cases)
                receipt["case_names"] = [case.get("name") for case in cases]
            else:
                receipt["missing_junit"] = True
            receipt["accepted"] = bool(
                process.returncode == 0 and receipt.get("junit_cases", 0) >= minimum_cases
                and receipt.get("failures", 0) == 0 and receipt.get("errors", 0) == 0
                and receipt.get("skipped", 0) == 0 and not receipt.get("missing_junit")
            )
        except Exception as error:
            receipt["accepted"] = False
            receipt["error"] = repr(error)
            receipt["traceback"] = traceback.format_exc()
            try:
                write_new(reports / (label + ".json"), receipt)
            except Exception as report_error:
                print("Report write failed:", repr(report_error), file=sys.stderr)
            raise
        write_new(reports / (label + ".json"), receipt)
        print(label, json.dumps({key: receipt.get(key) for key in ("return_code", "junit_cases", "failures", "errors", "skipped", "accepted")}), flush=True)
        if not receipt["accepted"]:
            raise RuntimeError("Acceptance gate failed: " + label + "; see " + str(log))
        return receipt

    def record_historical_diagnostic(*_args, **_kwargs):
        label = "blocked-stress-diagnostic"
        xml = reports / (label + ".xml")
        log = reports / (label + ".log")
        command = [sys.executable, "-m", "pytest", "-q", DIAGNOSTIC_NODE, "--junitxml=" + str(xml)]
        receipt = {"label": label, "command": command, "cwd": str(candidate), "counted_as_available_tool": False}
        try:
            with log.open("x", encoding="utf-8") as output:
                process = subprocess.run(command, cwd=candidate, env=env, stdout=output, stderr=subprocess.STDOUT)
            receipt["return_code"] = process.returncode
            cases = list(ET.parse(xml).getroot().iter("testcase"))
            receipt.update(classify_historical_diagnostic(process.returncode, cases))
        except Exception as error:
            receipt.update(recorded=False, error=repr(error), traceback=traceback.format_exc())
            try:
                write_new(reports / (label + ".json"), receipt)
            except Exception as report_error:
                print("Diagnostic report write failed:", repr(report_error), file=sys.stderr)
            raise
        write_new(reports / (label + ".json"), receipt)
        print(label, "known upstream failure recorded; NOT passed or counted as a tool", flush=True)
        return receipt

    prerequisite = TaskDef(name="preflight", fn=preflight)
    definitions = [("contracts", ["tests_local/test_github_expansion_contracts.py"], 1)]
    definitions += [(group, group_selections(group), 5 if group == "geophysics" else 1) for group in groups]
    definitions += [("native-new", new_nodes, len(ids)), ("baseline229", baseline_nodes, 229)]
    terminals = []
    for label, selections, minimum in definitions:
        def execute(*_args, _label=label, _selections=selections, _minimum=minimum, **_kwargs):
            return run_suite(_label, _selections, _minimum)
        terminals.append(TaskDef(name=label, fn=execute, depends_on=[prerequisite]))
    terminals.append(TaskDef(name="record-historical-diagnostic", fn=record_historical_diagnostic, depends_on=[prerequisite]))
    flow = Flow(*terminals, max_workers=1, fail_fast=False, journal_path=str(reports / "flow.jsonl"))
    result = flow.run()
    statuses = {name: {"state": item.state.name, "error": str(item.error) if item.error else None} for name, item in result.items()}
    accepted = len(result) == len(terminals) + 1 and all(item.state.name == "SUCCEEDED" for item in result.values())
    formal_results = [result[label] for label, _, _ in definitions if label in result]
    formal_receipts = [item.value for item in formal_results if item.state.name == "SUCCEEDED"]
    totals = {key: sum(receipt.get(key, 0) for receipt in formal_receipts) for key in ("junit_cases", "passed_cases", "failures", "errors", "skipped")}
    write_new(reports / "summary.json", {
        **manifest, "states": statuses, "accepted": accepted,
        "formal_totals": totals,
        "formal_suites_completed": len(formal_receipts),
        "formal_suites_required": len(definitions),
        "historical_diagnostic_report": "blocked-stress-diagnostic.json",
        "historical_diagnostic_in_formal_totals": False,
    })
    print(flow.summary(), flush=True)
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())

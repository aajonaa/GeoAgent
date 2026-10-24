"""Test source functions and the unchanged agent JSON transport independently."""

from __future__ import annotations

import argparse
import copy
import importlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from legacy.ToolsAgent.ToolsFuns.source_contracts import arguments, catalog, decode
from geotool.domain_worker import run as transport, digest
from source_asset_checks.helpers import create, oracle


def invoke_source(tool, params, workspace, output, serialized=False):
    spec = tool["source_interface"]
    payload = copy.deepcopy(params)
    for key in spec.get("path_fields", []):
        if key not in payload:
            continue
        value = payload[key]
        payload[key] = [str(workspace / item) for item in value] if isinstance(value, list) else str(workspace / value)
    entry = spec["entrypoint"]
    module, name = entry["callable"].split(":")
    fn = getattr(importlib.import_module(module), name)
    kwargs = dict(entry["bound_arguments"])
    kwargs[entry["argument_parameter"]] = json.dumps(payload, ensure_ascii=False, allow_nan=False) if serialized else payload
    if entry.get("output_directory_parameter"):
        kwargs[entry["output_directory_parameter"]] = output
    value = fn(**kwargs)
    Draft202012Validator(tool["output_schema"]).validate(value)
    artifacts = []
    for path in output.rglob("*"):
        if path.is_file():
            artifacts.append({"path": path.relative_to(workspace).as_posix(), "sha256": digest(path), "size_bytes": path.stat().st_size})
    return {"ok": True, "result": value, "artifacts": artifacts}


def assert_numeric_reference(name, value):
    if name == "GeoMagnitudeToEnergy":
        assert math.isclose(value["energy_j"], 10 ** 14.55, rel_tol=1e-12)
        assert math.isclose(value["tnt_tons"], 10 ** 14.55 / 4.184e9, rel_tol=1e-12)


def populate(workspace, examples, tools):
    create(workspace)
    for name, params in examples.items():
        for field in tools[name]["source_interface"].get("path_fields", []):
            if field not in params:
                continue
            values = params[field] if isinstance(params[field], list) else [params[field]]
            for value in values:
                relative = Path(value)
                if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] != ("assets",):
                    raise ValueError("Acceptance input is not an asset fixture: " + value)
                target = workspace / relative
                if target.exists():
                    continue
                source = ROOT / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, target)
                else:
                    shutil.copyfile(source, target)


def check_assets(c, tools):
    from geological_agent.bootstrap import build_registry
    registry, _, _ = build_registry()
    callable_names = set(registry.names())
    rows = []
    for skill in c["skills"]:
        row = {"skill": skill["id"], "status": "failed", "workflow_validation": "not_run"}
        try:
            path = (ROOT / skill["skill_file"]).resolve(strict=True)
            assert path.is_relative_to((ROOT / "catalog/skills").resolve())
            text = path.read_text(encoding="utf-8")
            assert text.startswith("---") and re.search(r"(?m)^name:", text) and re.search(r"(?m)^description:", text)
            assert "## Source interface and delivery" in text
            assert "### Current availability" in text
            assert all(name in tools or name in callable_names for name in skill.get("tool_references", []))
            assert "capabilities" not in skill
            delivery = skill["delivery"]
            expected = ("tool_candidates_available_workflow_unverified" if delivery["source_candidates"] and not delivery["unavailable_references"] else "partially_blocked" if delivery["source_candidates"] else "blocked_no_source_candidates")
            assert delivery["availability_status"] == expected
            assert delivery["workflow_validation"] == "not_run"
            assert expected in text
            assert skill["registration_metadata"]["platform_validation"] == "not_run"
            row.update(status="passed", checks=["document", "front_matter_present", "source_call_guidance", "references_resolve"], unavailable_references=skill.get("delivery", {}).get("unavailable_references", []))
        except Exception as exc:
            row["error"] = type(exc).__name__ + ": " + str(exc)
        rows.append(row)
    return rows


def run_checks():
    c = catalog()
    tools = {tool["id"]: tool for tool in c["tools"]}
    examples = json.loads((ROOT / "catalog/source_delivery/examples.json").read_text(encoding="utf-8"))
    selected = [tool for tool in c["tools"] if tool.get("source_interface", {}).get("status") == "source_revised_unverified"]
    rows, negative = [], []
    assert set(examples) == {tool["id"] for tool in selected}
    assert "capabilities" not in c
    with tempfile.TemporaryDirectory(prefix="geotool-source-acceptance-") as directory:
        workspace = Path(directory)
        populate(workspace, examples, tools)
        for tool in selected:
            name = tool["id"]
            row = {"tool": name, "status": "failed", "checks": []}
            try:
                for key in ("input_schema", "output_schema"):
                    Draft202012Validator.check_schema(tool[key])
                fn = tool["function_definition"]["function"]
                assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", fn["name"])
                assert fn["parameters"] == tool["input_schema"]
                assert fn["description"] == tool["description"] and fn["description"]
                assert all(spec.get("description") for spec in tool["input_schema"]["properties"].values())
                assert all(spec.get("description", "").strip().lower() not in {"finite numeric result.", "numeric value.", "value."} for spec in tool["input_schema"]["properties"].values())
                assert all(spec.get("description") for spec in tool["output_schema"].get("properties", {}).values())
                assert tool["registration_metadata"]["platform_validation"] == "not_run"
                Draft202012Validator(tool["input_schema"]).validate(examples[name])
                row["checks"].append("schemas_and_standard_definition")
                for mode in ("source_object", "source_json_object", "agent_transport"):
                    output = workspace / "outputs" / str(len(rows)) / mode
                    output.mkdir(parents=True)
                    if mode == "agent_transport":
                        response = transport({"tool_id": name, "input": copy.deepcopy(examples[name]), "workspace": str(workspace)})
                        response.setdefault("artifacts", [])
                        Draft202012Validator(tool["output_schema"]).validate(response["result"])
                    else:
                        response = invoke_source(tool, examples[name], workspace, output, serialized=(mode == "source_json_object"))
                    assert response["ok"]
                    oracle(name, response, workspace)
                    assert_numeric_reference(name, response["result"])
                    row["checks"].append(mode + "_and_result_oracle")
                invalid = dict(examples[name], undeclared_parameter=True)
                try:
                    arguments(name, invalid)
                except ValidationError as exc:
                    assert exc.validator == "additionalProperties", "Rejected for a different validation reason"
                    row["checks"].append("unknown_parameter_rejected")
                else:
                    raise AssertionError("Undeclared input accepted")
                row["status"] = "passed"
            except Exception as exc:
                row["error"] = type(exc).__name__ + ": " + str(exc)
            rows.append(row)
            print(json.dumps({"tool": name, "status": row["status"], "error": row.get("error")}, ensure_ascii=False), flush=True)
        cases = [
            ("zero_divisor", "RemoteSensingDivision", {"a": 1, "b": 0}),
            ("zero_baseline", "RemoteSensingPercentageChange", {"a": 0, "b": 1}),
            ("constant_kurtosis", "RemoteSensingKurtosis", {"x": [1, 1, 1]}),
            ("zero_mean_cv", "RemoteSensingCoefficientOfVariation", {"x": [-1, 1]}),
            ("invalid_latitude", "CCSHaversineDistance", {"lat1": 100, "lon1": 0, "lat2": 0, "lon2": 1}),
            ("nonunique_bearing", "GeoBearing", {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 180}),
            ("reversed_bbox", "CCSBBoxArea", {"bbox": [10, 0, 0, 1]}),
            ("missing_file", "NaturalHazardCountRecords", {"source": "missing.csv"}),
            ("missing_sheet", "NaturalHazardCountRecords", {"source": "assets/full-examples/events.xlsx", "sheet": "Missing"}),
            ("unknown_column", "NaturalHazardCountRecords", {"source": "assets/full-examples/events.csv", "filters": {"Unknown": 1}}),
            ("binary_required", "RemoteSensingExtremeSnowLossPercentage", {"binary_map_path": "assets/full-examples/a.tif"}),
            ("unpaired_bands", "RemoteSensingBatchNDSI", {"green_file_list": ["assets/full-examples/a.tif"], "swir_file_list": ["assets/full-examples/a.tif", "assets/full-examples/b.tif"]}),
            ("placeholder_blocked", "多源空间数据格式转换与标准化", {}),
            ("known_bug_blocked", "CCSRasterAlgebra", {}),
            ("nonfinite_rejected", "RemoteSensingMean", {"x": [float("inf")]}),
            ("absolute_path_blocked_by_agent", "NaturalHazardCountRecords", {"source": str(workspace / "assets/full-examples/events.csv")}),
            ("native_dms_latitude_range", "GeoDecimalToDMS", {"value": 91, "axis": "lat"}),
            ("deep_time_dms_latitude_range", "DeepTimeDecimalToDMS", {"value": 91, "field": "lat"}),
            ("ccs_dms_longitude_range", "CCSDecimalToDMS", {"value": 181, "field": "lon"}),
        ]
        for label, name, params in cases:
            try:
                transport({"tool_id": name, "input": params, "workspace": str(workspace)})
                negative.append({"test": label, "status": "failed", "error": "Invalid input succeeded"})
            except Exception as exc:
                negative.append({"test": label, "status": "passed", "rejection": type(exc).__name__ + ": " + str(exc)})
        for label, raw in (("duplicate_key", '{"a":1,"a":2}'), ("overflow", '{"x":1e999}')):
            try:
                decode(raw)
                negative.append({"test": label, "status": "failed"})
            except (ValueError, TypeError):
                negative.append({"test": label, "status": "passed"})
        try:
            result = transport({"tool_id": "NaturalHazardCountRecords", "input": {"source": "assets/full-examples/events.csv"}, "workspace": str(workspace)})
            assert result["result"]["count"] == 2
            negative.append({"test": "csv_source", "status": "passed"})
        except Exception as exc:
            negative.append({"test": "csv_source", "status": "failed", "error": str(exc)})
        # Confirm the three distinct threshold conventions with equality cases.
        for name in ("RemoteSensingBatchHotspotRaster", "RemoteSensingCountAboveThreshold", "RemoteSensingFireIncreaseMap"):
            try:
                params = copy.deepcopy(examples[name])
                params["threshold"] = 2
                output = workspace / "threshold-boundaries" / name
                output.mkdir(parents=True)
                response = invoke_source(tools[name], params, workspace, output)
                value = response["result"]
                if name == "RemoteSensingCountAboveThreshold":
                    assert value["count"] == 3 and value["percentage"] == 75
                else:
                    import numpy as np
                    import rasterio
                    files = value["outputs"] if name == "RemoteSensingBatchHotspotRaster" else [value["output_path"]]
                    expected_masks = [[[1, 0], [0, 0]], [[0, 0], [0, 0]]] if name == "RemoteSensingBatchHotspotRaster" else [[[0, 1], [1, 1]]]
                    assert len(files) == len(expected_masks)
                    for filename, expected_mask in zip(files, expected_masks):
                        with rasterio.open(filename) as raster:
                            np.testing.assert_array_equal(raster.read(1), expected_mask)
                    if name == "RemoteSensingFireIncreaseMap":
                        assert value["positive_pixels"] == 3
                negative.append({"test": name + "_threshold_equality", "status": "passed"})
            except Exception as exc:
                negative.append({"test": name + "_threshold_equality", "status": "failed", "error": str(exc)})
    skills = check_assets(c, tools)
    adapter_imports = [name for name in sys.modules if name.split(".")[0] in {"asset_bridge", "asset_catalog"}]
    negative.append({"test": "no_execution_adapter_imports", "status": "failed" if adapter_imports else "passed", "imports": adapter_imports})
    return {
        "tools": rows, "additional_checks": negative, "skills": skills,
        "passed": sum(row["status"] == "passed" for row in rows),
        "failed": sum(row["status"] != "passed" for row in rows),
        "additional_failed": sum(row["status"] != "passed" for row in negative),
        "skill_interface_failed": sum(row["status"] != "passed" for row in skills),
        "blocked_tools": [{"tool": t["id"], "reason": t.get("source_interface", {}).get("reason", "Not revised")} for t in c["tools"] if t not in selected],
        "scope": "Synthetic offline source, JSON-object compatibility, agent worker transport and skill-document checks. Not live agent, model, Linux sandbox, complete skill execution, scientific certification or official platform acceptance.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run_checks()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("passed", "failed", "additional_failed", "skill_interface_failed")}), flush=True)
    raise SystemExit(1 if report["failed"] or report["additional_failed"] or report["skill_interface_failed"] else 0)


if __name__ == "__main__":
    main()

"""One-shot source materializer. Standard library only; no tests or scientific imports."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
GROUP = "catalog/source_delivery/expansion501-20261026/groups/geology"
MODULE_FILE = "geological_agent/geology/expansion501_geology.py"
MODULE = "geological_agent.geology.expansion501_geology"
ASSETS = "assets/expansion501-geology"
STATUS = "source_revised_unverified"


def closed(props):
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def fixed(value):
    return {"type": "boolean" if isinstance(value, bool) else "string", "const": value}


def string(maximum=512):
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def main():
    spec = json.loads((ROOT / GROUP / "contribution-spec.json").read_text(encoding="utf-8"))
    files = [MODULE_FILE, GROUP + "/build_contribution.py", GROUP + "/contribution-spec.json",
             GROUP + "/README.md", *spec["license_copy_paths"]]

    def write(relative, value, raw=False):
        target = ROOT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        content = value if raw else json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        files.append(relative)

    lifecycle = {"registration": STATUS, "contract_validation": "not_run", "unit_validation": "not_run",
                 "workflow_validation": "not_run", "model_workflow_validation": "not_run",
                 "platform_validation": "not_run", "deployment_status": "not_deployed",
                 "submission_status": "not_submitted", "release_status": "draft"}
    profiles = {}
    for source in spec["sources"].values():
        profiles.setdefault(source["profile"], set()).update(source["requirements"])
    for profile, requirements in profiles.items():
        write(GROUP + "/requirements-" + profile + ".txt",
              "# Private CPU profile only. Exact direct pins; full transitive/native lock pending.\n"
              + "\n".join(sorted(requirements)) + "\n", raw=True)
    write(GROUP + "/requirements.txt",
          "# Retained scientific base; use one requirements-<profile>.txt in a private environment.\n"
          "# Not a complete transitive lock; no installation authorization.\n"
          + "\n".join(spec["common_requirements"]) + "\n", raw=True)
    tools, examples, statuses, candidates, oracles = [], {}, [], [], []
    for row in spec["operations"]:
        identifier = row["id"]
        source = spec["sources"][row["source"]]
        url = "https://github.com/" + source["repo"]
        mode = source.get("source_mode", "package_release")
        api_url = url + "/blob/" + source["commit"] + "/" + row["api"]
        installed = {}
        if mode == "package_release":
            installed[source["package"]] = source["version"]
        for requirement in source["requirements"]:
            if "==" in requirement and " " not in requirement and "@" not in requirement:
                package, version = requirement.split("==", 1)
                installed[package] = version
        provenance = closed({
            "tool": fixed(identifier), "upstream_url": fixed(url), "source_mode": fixed(mode),
            "reviewed_archive_commit": fixed(source["commit"]),
            "installed_versions": closed({p: fixed(v) for p, v in installed.items()}),
            "vendored_source": {"type": "array", "items": string(), "maxItems": 0},
            "input_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "implementation_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "contract_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "output_sha256": closed({}), "network_required": fixed(False),
            "runtime_source_correspondence": string(1200)})
        units = closed({k: ({"type": "string", "enum": v} if isinstance(v, list) else fixed(v))
                        for k, v in row["units"].items()})
        output = closed({**copy.deepcopy(row["output_properties"]), "input_source": string(),
                         "units": units, "artifacts": {"type": "array", "items": string(), "maxItems": 0},
                         "provenance": provenance})
        definition = {"type": "function", "function": {"name": identifier, "description": row["task"],
                                                       "parameters": copy.deepcopy(row["input_schema"])}}
        upstream = {"package": source["package"], "version": source["version"], "license": source["license"],
                    "url": url, "source_mode": mode, "requirements": source["requirements"],
                    "source_commit": source["commit"], "api_url": api_url,
                    "upstream_callable": spec["upstream_callables"][identifier],
                    "license_evidence": url + "/blob/" + source["commit"] + "/" + source["license_file"]}
        registration = {
            "asset_version": "1.0.0", "provider": source["repo"].split("/")[0], "license": source["license"],
            "upstream_license": source["license"], "source_url": url, "source_commit": source["commit"],
            "official_protocol_version": None,
            "official_protocol": {"applicability": "not_applicable", "name": None, "version": None},
            "metadata_profile": "scientific",
            "runtime": {"python": "==3.12.*", "dependency_lock": GROUP + "/requirements-" + source["profile"] + ".txt",
                        "environment_version": "expansion501-geology-" + source["profile"] + "-cpu-v1"},
            "lifecycle": copy.deepcopy(lifecycle), "platform_validation": "not_run",
            "pending_fields": ["adapter_license", "receiving_lab_approval", "private_cpu_acceptance",
                               "transitive_dependency_lock", "native_wheel_identity", "redistribution_review"]}
        tools.append({
            "id": identifier, "name": identifier, "description": row["task"],
            "input_schema": row["input_schema"], "output_schema": output,
            "constraints": {"finite_numbers_only": True, "no_automatic_dependency_install": True,
                            "no_runtime_network": True, "no_arbitrary_dispatch": True, "no_grade_imputation": True,
                            "max_json_bytes": 4000000, "max_result_bytes": 8000000,
                            "private_cpu_environment_required": True},
            "metadata": {"category": "expansion501_geology",
                "input_format": "Bounded strict JSON with physical units and caller source.",
                "output_format": "Finite closed JSON with units and shared provenance; no artifacts.",
                "source": url, "upstream": upstream,
                "scientific_contract": {"implementation_kind": "upstream_library", "review_status": "acceptance_pending",
                    "formal_eligible": False, "numeric_oracle": row["numeric_oracle"],
                    "oracle_source": GROUP + "/oracle-cases.json", "synthetic_fixtures": True,
                    "execution_status": "NOT TESTED", "deployment_status": "not_deployed",
                    "submission_status": "not_submitted", "model_workflow_validation": "not_run",
                    "receiving_lab_certification": "not_established"}},
            "category": "expansion501_geology", "function": definition,
            "function_definition": copy.deepcopy(definition), "version": "1.0.0",
            "example_arguments": row["example"], "example_arguments_path": ASSETS + "/" + identifier + ".json",
            "limitations": row["limitations"] + [
                "NOT TESTED / NOT DEPLOYED / NOT SUBMITTED. Model/platform workflows not_run.",
                "Delivered fixtures are SYNTHETIC, not geological/mineral-resource evidence.",
                "Parent must bind a private CPU worker; no accepted bridge profile is reused or modified.",
                "Direct pins are exact; complete transitive/native locking and redistribution review remain pending."],
            "source_interface": {"status": STATUS, "kind": "expansion501_geology", "path_fields": [],
                "network_required": False, "pure": False, "validation": "acceptance_pending",
                "entrypoint": {"callable": MODULE + ":" + row["fn"], "argument_parameter": "args", "bound_arguments": {}}},
            "error_contract": {"direct_exception": "ScientificToolError", "fields": ["code", "message", "retryable"],
                "codes": ["invalid_arguments", "missing_dependency", "incompatible_dependency", "resource_limit",
                          "invalid_result", "unsupported_conditions", "empty_input", "upstream_failure"],
                "retry_policy": "Correct inputs or prepare the reviewed private profile; no automatic retry/install."},
            "tags": ["geology", "scientific", "source-only", source["package"]],
            "registration_metadata": registration})
        examples[identifier] = row["example"]
        write(ASSETS + "/" + identifier + ".json", row["example"])
        statuses.append({"id": identifier, "state": "source_adapted_unverified",
            "reason": "Explicit decorated " + row["fn"] + " calls the fixed upstream with bounded inputs and physical checks. Private CPU binding and independent scientific/lab/platform acceptance remain pending; never executed here.",
            "blockers": []})
        candidates.append({"tool_id": identifier, "capability_key": "geology:" + row["fn"].replace("_", "-"),
            "upstream_callable": upstream["upstream_callable"], "scientific_task": row["task"],
            "distinct_from_existing": row["distinct_from_existing"], "numeric_oracle": row["numeric_oracle"],
            "status": STATUS})
        oracles.append({"tool_id": identifier, "fixture": ASSETS + "/" + identifier + ".json",
            "synthetic": True, "status": "proposed_not_run", "independent_check": row["numeric_oracle"],
            "negative_constraints": row["limitations"],
            "common_negative_checks": ["unknown fields", "NaN/Infinity", "wrong rank/length", "physical-domain violation",
                                      "wrong dependency profile", "missing CPU identity"],
            "provenance_check": "Shared input/implementation/contract hashes, installed pins, artifacts=[] and output_sha256={}.",
            "acceptance_note": "Not an executable suite; absolute-FOS and thermal melting-path benchmarks remain explicitly pending."})
    statuses.extend({"id": r["id"], "state": "blocked", "reason": r["reason"], "blockers": r["blockers"]}
                    for r in spec["blocked"])
    skills = []
    for slug, name in spec["skills"].items():
        rows = [r for r in spec["operations"] if r["skill"] == slug]
        ids = [r["id"] for r in rows]
        identifier = "expansion501-geology-" + slug
        path = "catalog/skills/" + identifier + "/SKILL.md"
        description = " ".join(r["task"] for r in rows)
        delivery = {"source_candidates": ids, "unavailable_references": [],
                    "availability_status": "source_adapted_unverified", "workflow_validation": "not_run",
                    "model_workflow_validation": "not_run", "deployment_status": "not_deployed",
                    "submission_status": "not_submitted", "receiving_lab_approval": "pending"}
        registration = copy.deepcopy(next(t["registration_metadata"] for t in tools if t["id"] == ids[0]))
        registration["provider"] = "GeoAgent"
        registration["pending_fields"].append("skill_workflow_acceptance")
        skills.append({"id": identifier, "name": name, "description": description, "tool_references": ids,
            "skill_file": path, "metadata": {"canonical_skill_file": path, "validation": "not_run",
                "model_workflow_validation": "not_run",
                "context_policy": "Load only this scientific workflow when relevant; engine unchanged."},
            "delivery": delivery, "registration_metadata": registration})
        text = "---\nid: " + identifier + "\nname: " + json.dumps(name) + "\ndescription: " + json.dumps(description) + "\n"
        text += 'when_to_use: "Use only for this documented scientific task."\ntools:\n'
        text += "".join("- " + x + "\n" for x in ids)
        text += 'required_inputs:\n- Explicit data, units, assumptions and data_source\nconstraints:\n- No imputed grade, arbitrary code, network fetch or runtime installation\n- Preserve uncertainty and native provenance\nexpected_outputs:\n- Finite scientific JSON with units and hashes\n---\n\n# ' + name + "\n\n"
        text += "## When to use\n\n" + description + "\n\n## Required inputs\n\nRead the chosen complete schema and limitations. Supply measurements or explicitly identified model inputs, units, source and assumptions. Never fill missing field observations from synthetic examples.\n\n"
        text += "## Procedure\n\n1. Choose the operation matching the scientific question.\n2. Confirm physical domain, component order, units and provenance.\n3. Have the parent bind its fixed private CPU environment; never install or fetch at call time.\n4. Invoke the named function with args as a dictionary or JSON-object string after staging.\n5. Preserve units/hashes and interpret within the declared assumptions.\n\n## Tools and synthetic examples\n\n"
        for row in rows:
            source = spec["sources"][row["source"]]
            link = "https://github.com/" + source["repo"] + "/blob/" + source["commit"] + "/" + row["api"]
            text += "### " + row["id"] + "\n\n" + row["task"] + "\n\n"
            text += "Entrypoint: " + MODULE + ":" + row["fn"] + ". Example: " + ASSETS + "/" + row["id"] + ".json (SYNTHETIC).\n\n"
            text += " ".join(row["limitations"]) + "\n\n[Reviewed upstream implementation](" + link + ").\n\n"
        text += "## Interpretation and constraints\n\nNo result certifies ore grade, reserves, mineral identity, engineering safety or real-event prediction. No GPU, arbitrary callable, serialized class, shell command, database fetch or hidden missing-value replacement is exposed. Failures return errors, never local substitute kernels.\n\n"
        text += "## Native errors\n\nScientificToolError carries code, message and retryable through collection_contracts.operation. Missing/incompatible dependencies need parent-controlled preparation. Do not invent data to bypass a rejected domain.\n\n"
        text += "## Source interface and delivery\n\nKind: expansion501_geology. Module: " + MODULE + ". Explicit decorated functions accept args and return JSON only. No output_dir or generated artifact. Shared contracts provide input, implementation and contract hashes plus empty artifact hashes. Existing native bridge profiles are unchanged. Full paths are in " + GROUP + "/delivery-files.json.\n\n"
        text += "## Availability and handoff\n\nsource_revised_unverified; acceptance_pending; formal_eligible=false. NOT TESTED. Deployment: not_deployed. Submission: not_submitted. Unit, model workflow, Skill workflow and platform validation: not_run. Receiving AI Lab certification is not established. Parent owns registry/kind allowlisting, private CPU binding, tests, acceptance and release.\n\n"
        text += "## Acceptance evidence\n\nSource and proposed independent oracle cases only; no scientific tool/test executed. Complete transitive/native identities, outstanding absolute reference benchmarks, license/distribution review and lab approval remain pending. Blocked assignments are excluded from this Skill and catalog-additions.json; see adaptation-status.json and blocked-evidence.json.\n"
        write(path, text, raw=True)
    for name, document in [
        ("catalog-additions.json", {"tools": tools, "skills": skills}),
        ("examples-additions.json", examples),
        ("candidate-operations.json", {"group": "geology", "operations": candidates}),
        ("adaptation-status.json", {"operations": statuses}),
        ("blocked-evidence.json", {"operations": spec["blocked"]}),
        ("sources.json", {"status": STATUS, "sources": spec["sources"], "license_copy_paths": spec["license_copy_paths"],
                         "qualification": "Reviewed source and published package pins are distinct. No complete legal/AI Lab certification or general byte-identity claim."}),
        ("oracle-cases.json", {"status": "proposed_not_run", "operations": oracles})]:
        write(GROUP + "/" + name, document)
    write(GROUP + "/private-cpu-binding.json", {
        "status": "parent_binding_pending_not_executed", "module": MODULE, "kind": "expansion501_geology",
        "fixed_entrypoints": {r["id"]: r["fn"] for r in spec["operations"]},
        "required_environment": {"GEOAGENT_EXPANSION501_GEOLOGY_CPU": "expansion501-geology-cpu-v1",
            "CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1", "GEMPY_USE_GPU": "False", "GEMPY_GPU_FALLBACK": "False", "MPLBACKEND": "Agg"},
        "dependency_profiles": {k: GROUP + "/requirements-" + k + ".txt" for k in profiles},
        "launcher": "Parent-owned fixed JSON CPU worker; no new launcher or accepted profile modification included.",
        "transport": "JSON only, artifacts forbidden. No user-controlled module/function/argv/environment.",
        "required_parent_controls": {"private_workspace": True, "timeout_seconds": 120, "stdout_bytes": 65536,
            "stderr_bytes": 65536, "memory_bytes": 2147483648, "real_exit_status": True,
            "native_identity_hashes": "pending", "transitive_lock": "pending",
            "network_disabled": True, "cache_paths_inside_private_workspace": True},
        "result_validation": "Shared contract enforces finite closed outputs and hashes; parent additionally bounds process streams and records real exit status. Import is not scientific acceptance."})
    manifest = GROUP + "/delivery-files.json"
    files.append(manifest)
    write(manifest, {"files": sorted(files)})
    print(json.dumps({"source_adapted_unverified": len(tools), "blocked": len(spec["blocked"]),
        "assigned": len(statuses), "skills": len(skills), "delivery_manifest": manifest,
        "generation_only": True, "tests": "not_run", "deployment": "not_deployed"}))


if __name__ == "__main__":
    main()

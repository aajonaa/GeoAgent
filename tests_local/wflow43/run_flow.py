"""New revision: immutable source reuse, real shared collection, CPU acceptance.

Only this private contribution and a fresh private remote candidate are written.
The R4 baseline, prior frozen receipts, parent latest and 7-op union are not edited.
"""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
for key, leaf in (("MPLCONFIGDIR", "matplotlib"), ("NUMBA_CACHE_DIR", "numba"), ("XDG_CACHE_HOME", "xdg")):
    p = HERE / "cache/flow" / leaf
    p.mkdir(parents=True, exist_ok=True)
    os.environ[key] = str(p)
os.environ.update(CUDA_VISIBLE_DEVICES="", NVIDIA_VISIBLE_DEVICES="none", PROJ_NETWORK="OFF",
    LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false", GEOTOOL_LANGSMITH_ENABLED="0",
    OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1",
    NUMBA_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")

import ast
import base64
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(r"C:\Users\jona\.codex\visualizations\2026\08\29\01a04b19-6e61-7b12-88df-4878c03a46da\earth-python-all-20261022")
OLD = ROOT / "coverage-101/approved-replacements/engine-investigation/wflow43-r1"
REMOTE = "/data/wangjian/earth-python-approved-replacements-20261022/wflow43-collection-native-r4"
BASE = "/data/wangjian/earth-python-all-20261022-r4/candidate"
PYTHON = "/data/wangjian/earth-python-all-20261022-r4/venv/bin/python"
MODULE = "geological_agent.geology.collection_wflow43"
NAME = "EarthWflowKinematicWaveReachStep"
SCIENCE_PINS = ["numba==0.68.0", "numpy==2.1.3", "llvmlite==0.50.0"]
HOST_PINS = ["jsonschema==4.25.1", "pydantic==2.13.5", "typing-extensions==4.16.0", "langgraph==1.2.12"]
PROTECTED = {
    "geological_agent/geology/collection_contracts.py": "25f805cf5531ff8bf1f8894f006dca40c6035efd44967507583c820dcc323fa9",
    "geological_agent/geology/source_registry.py": "41e93b038a29d63152f0488dc0a42331d4453fa598278ce13a97e85ae8136da3",
    "legacy/ToolsAgent/ToolsFuns/source_contracts.py": "10303dc89014564d4bcd7a00fbd22f1319c15c4d0a9393787c4327883b1e0d84",
    "catalog/registry.json": "61e7c52959f5fa7462e754931b91dfcc24be7e0e679fc33a6a1311365fd88c8c",
}
SSH = ["ssh", "-T", "-i", str(Path.home() / ".ssh/id_ed25519_a100_server2"), "-p", "8005",
       "-oBatchMode=yes", "-oStrictHostKeyChecking=yes", "-oConnectTimeout=8", "wangjian@59.72.109.190"]
sys.path.insert(0, str(ROOT.parent / "earth-python-intake-20261021/orchestration"))
from flowing import Flow, task


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False), encoding="utf-8")


def copy_verified(old, target, expected):
    assert sha(old) == expected, str(old)
    target.parent.mkdir(parents=True, exist_ok=True)
    assert not target.exists(), str(target)
    shutil.copyfile(old, target)
    assert sha(target) == expected


def prepare(*args, **kwargs):
    assert sha(OLD / "HANDOFF.json") == "0178d38a6044063c086a91ee8a42d81f4424784614899b2207a632a16f634d3d"
    previous = json.loads((OLD / "HANDOFF.json").read_text(encoding="utf-8"))
    proposal = HERE / "proposal"
    proposal.mkdir(exist_ok=False)
    proof = HERE / "original-proof"
    proof.mkdir(exist_ok=False)
    vendor_root = proposal / "source/geological_agent/geology/collection_vendor/approved_wflow43"
    reused = ["kernel_adapter.py", "operation.json", "vendor/original_kinematic_wave.py", "vendor/wflow_funcs.py", "vendor/LICENSE", "vendor/NOTICE.json"]
    for name in reused:
        expected = previous["files_sha256"][name]
        copy_verified(OLD / name, proof / name, expected)
        copy_verified(OLD / name, vendor_root / name, expected)
    for name in ("acceptance.py", "fixed_entry.py"):
        copy_verified(OLD / name, proof / name, previous["files_sha256"][name])
    (vendor_root / "__init__.py").write_text("", encoding="utf-8")
    copy_verified(HERE / "collection_wflow43.py", proposal / "source/geological_agent/geology/collection_wflow43.py", sha(HERE / "collection_wflow43.py"))
    original = json.loads((proof / "operation.json").read_text(encoding="utf-8"))
    ast_full = ast.parse((proof / "vendor/wflow_funcs.py").read_text(encoding="utf-8"))
    function = next(n for n in ast_full.body if isinstance(n, ast.FunctionDef) and n.name == "kinematic_wave")
    schema = json.loads(json.dumps(original["output_schema"]))
    wrapper_ast = ast.parse((HERE / "collection_wflow43.py").read_text(encoding="utf-8"))
    units = ast.literal_eval(next(n.value for n in wrapper_ast.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "UNITS" for t in n.targets)))
    schema["properties"]["units"] = {"type": "object", "properties": {k: {"const": v} for k, v in units.items()}, "required": list(units), "additionalProperties": False}
    schema["required"].append("units")
    schema["properties"]["provenance"] = {"type": "object", "description": "Unmodified shared collection SDK source/contract/input hashes and executing-interpreter exact pins."}
    receipt = original["source_receipt"]
    upstream_source = receipt["archive_source_path"]
    archive_root = upstream_source.rsplit("/wflow/wflow_funcs.py", 1)[0]
    vendored = [
        {"relative_path": "approved_wflow43/vendor/original_kinematic_wave.py", "archive_path": upstream_source,
         "source_sha256": receipt["archive_source_sha256"], "vendored_sha256": receipt["files_sha256"]["vendor/original_kinematic_wave.py"],
         "license": "GPL-3.0-or-later", "excerpt_ranges": [{"symbol": "kinematic_wave", "start_line": min(function.lineno, *(n.lineno for n in function.decorator_list)), "end_line": function.end_lineno}], "algorithm_modified": False},
        {"relative_path": "approved_wflow43/vendor/wflow_funcs.py", "archive_path": upstream_source,
         "source_sha256": receipt["archive_source_sha256"], "vendored_sha256": receipt["archive_source_sha256"], "license": "GPL-3.0-or-later", "algorithm_modified": False},
        {"relative_path": "approved_wflow43/vendor/LICENSE", "archive_path": archive_root + "/LICENSE",
         "source_sha256": receipt["files_sha256"]["vendor/LICENSE"], "vendored_sha256": receipt["files_sha256"]["vendor/LICENSE"], "license": "GPL-3.0-or-later", "algorithm_modified": False},
    ]
    description = "Original archived Wflow implicit kinematic-wave solver for one SI reach step, A=alpha*Q**beta. Returns observed outflow and finite-volume continuity; not a complete basin/runoff, PCRaster or Wflow.jl system."
    record = {
        "id": NAME, "name": NAME, "version": "1.0.0", "category": "earth_collection",
        "description": description, "coverage_kind": "original_bounded_operation", "coverage_target_project_id": 43,
        "input_schema": original["input_schema"], "output_schema": schema,
        "function_definition": {"type": "function", "function": {"name": NAME, "description": description, "parameters": original["input_schema"]}},
        "source_interface": {"status": "source_revised_unverified", "kind": "earth_collection", "path_fields": [], "pure": True,
            "network_required": False, "validation": "independent_acceptance_pending", "entrypoint": {"callable": MODULE + ":reach_step", "argument_parameter": "args", "bound_arguments": {}, "output_directory_parameter": None}},
        "metadata": {"category": "earth_collection", "source_project_id": 43,
            "input_format": "Schema-validated SI JSON object or JSON-object string; args= supported.",
            "output_format": "Observed JSON values, explicit units, shared SDK provenance; no artifacts generated.",
            "upstream": {"package": "wflow", "version": None, "url": "https://github.com/openstreams/wflow", "license": "GPL-3.0-or-later", "source_mode": "vendored_source", "requirements": SCIENCE_PINS + HOST_PINS, "vendor_files": vendored},
            "source_receipt": receipt, "reviewed_archive_commit": None,
            "execution_profile": {"science_requirements": SCIENCE_PINS, "host_SDK_requirements": HOST_PINS,
                "requirements_semantics": "The shared SDK checks combined exact pins in the interpreter executing this operation. These are bounded-kernel execution pins, not the full upstream Wflow requirements. No worker or runtime installs.", "tested_interpreter": PYTHON, "parent_latest_Wflow_profile_checked": False},
            "scientific_contract": {"implementation_kind": "vendored_original_source", "review_status": "independent_acceptance_pending", "formal_eligible": False},
            "registration_allowed": False, "full_legacy_engine_installed": False, "Wflow_jl_equivalence_claimed": False},
        "registration_metadata": {"asset_version": "1.0.0", "provider": "openstreams/wflow original archived kernel",
            "license": "GPL-3.0-or-later; wrapper/interface redistribution review pending", "upstream_license": "GPL-3.0-or-later", "source_commit": None,
            "runtime": {"python": ">=3.12", "dependency_lock": "requirements-wflow43-collection.txt", "environment_version": "wflow43-collection-r4-R4-CPU"},
            "lifecycle": {"registration": "independent_native_candidate", "release_status": "not_deployed"},
            "pending_fields": ["parent_union", "receiving_lab_approval", "redistribution_review", "full_upstream_release_correspondence"], "platform_validation": "not_run"},
        "example_arguments": {"upstream_inflow_m3_s": 2, "previous_outflow_m3_s": 1, "lateral_inflow_m2_s": .0005, "alpha": .02, "beta": 1, "timestep_seconds": 60, "reach_length_m": 100},
        "constraints": [original["unsupported_domain"], "Finite SI parameters must satisfy declared schema bounds.", original["tolerance_m3"]],
        "limitations": original["unreplaced_capabilities"] + ["Original code/hash/AST/JIT retained; archived bounded operation, not full-system equivalence.", "Independent CPU acceptance does not imply parent merge, production, official AI Lab or redistribution approval."],
        "error_contract": {"direct_exception": "ScientificToolError", "codes": ["invalid_arguments", "missing_dependency", "incompatible_dependency", "invalid_result", "upstream_failure", "resource_limit", "invalid_input"]},
        "tags": ["hydrology", "kinematic-wave", "SI", "original-source", "CPU"],
    }
    record["function"] = json.loads(json.dumps(record["function_definition"]))
    skill = {"id": "wflow-kinematic-reach", "name": "Original Wflow single-reach routing", "description": "One implicit reach step from the archived original Wflow kernel; explicit SI inputs, continuity and strict limitations.",
        "tool_references": [NAME], "skill_file": "catalog/skills/wflow-kinematic-reach/SKILL.md", "applicability": {"keywords": ["wflow", "kinematic wave", "river reach", "routing", "continuity"]},
        "metadata": {"domain": {"primary": "Hydrology"}, "workflow": {"steps": [{"inputs": list(record["input_schema"]["required"]), "outputs": ["outflow_m3_s", "continuity_residual_m3"]}]}},
        "examples": [{"prompt": "Route a supplied single-reach SI timestep with the archived Wflow kernel, reporting continuity and limitations; do not invent parameters."}],
        "delivery": {"source_candidates": [NAME], "unavailable_references": [], "availability_status": "independent_candidate_only", "workflow_validation": "not_run"},
        "source_interface": {"status": "source_revised_unverified", "unavailable_tools": [], "agent_end_to_end": "not_tested"},
        "registration_metadata": {"asset_version": "1.0.0", "provider": "GeoAgent bounded original-source interface", "license": "upstream GPL-3.0-or-later; redistribution review pending", "pending_fields": ["parent_union", "receiving_lab_approval"], "platform_validation": "not_run"}}
    write_json(proposal / "catalog-records.json", [record])
    write_json(proposal / "skill-records.json", [skill])
    skill_path = proposal / skill["skill_file"]
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("---\nid: wflow_kinematic_reach\nname: Original Wflow single-reach routing\ndescription: A bounded archived-original SI kinematic-wave reach step.\nwhen_to_use: Supplied SI parameters for one river reach and timestep.\ntools:\n  - EarthWflowKinematicWaveReachStep\n---\n\nConfirm all supplied inflows, previous flow, alpha/beta, reach length and timestep with their SI units. Do not infer missing parameters. Call the single native operation, check its returned continuity residual and tolerance, and preserve its source provenance. A dry reach with positive lateral inflow and beta<1 is unsupported and must not be silently repaired. This is an archived original kernel, not full Wflow/PCRaster, a catchment calibration or Wflow.jl. No web, model or code execution is needed.\n", encoding="utf-8")
    (proposal / "requirements-wflow43-collection.txt").write_text("\n".join(SCIENCE_PINS + HOST_PINS) + "\n", encoding="utf-8")
    write_json(proposal / "examples.json", {NAME: {"data_kind": "explicit_synthetic_SI_analytic_test_case_not_observed_catchment_data", "arguments": record["example_arguments"]}})
    write_json(proposal / "manifest.json", {"operations": [{"id": NAME, "source_project_id": 43, "coverage_target_project_id": 43, "coverage_kind": "original_bounded_operation", "profile": "requirements-wflow43-collection.txt", "native_entry": MODULE + ":reach_step"}], "parent_count_delta": 0})
    acceptance = proposal / "acceptance"
    acceptance.mkdir()
    oracle_source = (proof / "acceptance.py").read_text(encoding="utf-8")
    oracle_ast = next(n for n in ast.parse(oracle_source).body if isinstance(n, ast.FunctionDef) and n.name == "oracle")
    oracle = ast.get_source_segment(oracle_source, oracle_ast)
    fixture_code = "import json\nfrom pathlib import Path\n\nEXAMPLES = " + repr({NAME: record["example_arguments"]}) + "\n\ndef prepare(task_root):\n    target = Path(task_root) / 'assets/earth-collection/wflow43/synthetic-si-example.json'\n    target.parent.mkdir(parents=True, exist_ok=True)\n    with target.open('x', encoding='utf-8') as stream:\n        json.dump({'data_kind': 'synthetic_analytic_fixture_not_real_catchment_data', 'operations': EXAMPLES}, stream, allow_nan=False)\n    return EXAMPLES\n"
    (acceptance / "fixtures.py").write_text(fixture_code, encoding="utf-8")
    check_code = "import hashlib,json,math\nKEYS = " + repr(tuple(record["input_schema"]["required"])) + "\nPINS = " + repr({r.split('==')[0]: r.split('==')[1] for r in SCIENCE_PINS + HOST_PINS}) + "\nUNITS = " + repr(units) + "\n\n" + oracle + "\n\ndef check(name, result, args, output_dir=None):\n    assert name == 'EarthWflowKinematicWaveReachStep'\n    qi,qo,q,a,b,dt,dx = (float(args[k]) for k in KEYS)\n    out = result['outflow_m3_s']\n    assert math.isclose(out, oracle(args), rel_tol=1e-9, abs_tol=1e-10)\n    residual = dx*a*(out**b-qo**b)+dt*(out-qi-q*dx)\n    tolerance = max(1e-12*dx, 1e-10*max(1.,abs(dx*a*qo**b)+abs(qi*dt)+abs(q*dx*dt),abs(dx*a*out**b)+abs(out*dt)))\n    assert abs(residual) <= tolerance\n    assert math.isclose(result['continuity_tolerance_m3'], tolerance, rel_tol=1e-14)\n    assert result['units'] == UNITS and result['alpha_units'] == 'm^(2-3*beta) s^beta'\n    assert result['artifacts'] == [] and result['provenance']['output_sha256'] == {}\n    assert result['provenance']['installed_versions'] == PINS\n    assert result['provenance']['source_mode'] == 'vendored_source'\n    assert result['provenance']['input_sha256'] == hashlib.sha256(json.dumps(args,sort_keys=True,ensure_ascii=True,allow_nan=False).encode()).hexdigest()\n"
    (acceptance / "checks.py").write_text(check_code, encoding="utf-8")
    write_json(HERE / "preparation-receipt.json", {"prior_handoff_sha256": sha(OLD / "HANDOFF.json"), "only_hash_matching_prior_files_reused": True, "old_frozen_files_modified": False, "new_shared_wrapper_sha256": sha(HERE / "collection_wflow43.py"), "source_sha256": receipt["files_sha256"]})
    parent_profile = ROOT / "c101-replacements-profile-r1/profile.json"
    if parent_profile.is_file():
        target = proposal / "profiles/parent-replacements-profile.json"
        copy_verified(parent_profile, target, sha(parent_profile))
        write_json(proposal / "profiles/replacements-profile-supplement-r2.json", {"source_record": str(parent_profile), "source_sha256": sha(parent_profile), "interpreter": "/data/wangjian/earth-python-coverage101-imports-20261022/venv/bin/python", "applies_to": ["ScipyGroundwaterFrequencyResponse", "StatsmodelsSeasonalFlowForecast"], "dependency_gate_only": True, "58_tests_rerun_in_parent_latest": False, "parent_union_accepted": False, "Wflow_NumBa_profile_in_parent_latest_asserted": False, "prior_frozen_replacements_modified": False})
    return {"hash_bound_sources_prepared": True}


def run_tests(*args, **kwargs):
    payload_files = ["fixed_entry_collection.py", "acceptance_collection.py"]
    payload_files += [p.relative_to(HERE).as_posix() for p in (HERE / "original-proof").rglob("*") if p.is_file()]
    payload_files += [p.relative_to(HERE).as_posix() for p in (HERE / "proposal").rglob("*") if p.is_file()]
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for name in payload_files: archive.add(HERE / name, arcname=name)
    payload = base64.b64encode(stream.getvalue()).decode()
    remote_code = r'''
from pathlib import Path
import base64,hashlib,io,json,os,shutil,subprocess,sys,tarfile,difflib
root=Path(__REMOTE__);base=Path(__BASE__);python=__PYTHON__;expected=__PROTECTED__
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
before={p:digest(base/p) for p in expected}
assert before==expected,'R4 baseline hashes changed; do not overwrite or reuse silently'
root.mkdir(parents=True,exist_ok=False)
with tarfile.open(fileobj=io.BytesIO(base64.b64decode(__PAYLOAD__)),mode='r:gz') as archive:
 for item in archive.getmembers():
  target=(root/item.name).resolve()
  assert item.isfile() and target.is_relative_to(root.resolve())
  target.parent.mkdir(parents=True,exist_ok=True)
  target.write_bytes(archive.extractfile(item).read())
candidate=root/'candidate'
shutil.copytree(base,candidate,ignore=shutil.ignore_patterns('__pycache__','.pytest_cache','.git'))
proposal=root/'proposal'
for source in (proposal/'source').rglob('*'):
 if source.is_file():
  target=candidate/source.relative_to(proposal/'source')
  assert not target.exists(),str(target)
  target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
catalog_path=candidate/'catalog/registry.json';catalog=json.loads(catalog_path.read_text())
record=json.loads((proposal/'catalog-records.json').read_text())[0]
skill=json.loads((proposal/'skill-records.json').read_text())[0]
assert all(row['id']!=record['id'] for row in catalog['tools'])
assert all(row['id']!=skill['id'] for row in catalog['skills'])
catalog['tools'].append(record);catalog['skills'].append(skill)
catalog_path.write_text(json.dumps(catalog,ensure_ascii=True,indent=2))
target=candidate/skill['skill_file'];target.parent.mkdir(parents=True,exist_ok=True)
shutil.copyfile(proposal/skill['skill_file'],target)
shutil.copyfile(proposal/'requirements-wflow43-collection.txt',candidate/'requirements-wflow43-collection.txt')
registry_path=candidate/'geological_agent/geology/source_registry.py'
old=registry_path.read_text();marker='ENTRY_MODULES = {'
assert old.count(marker)==1
new=old.replace(marker,marker+'\n    "geological_agent.geology.collection_wflow43",',1)
registry_path.write_text(new)
evidence=root/'evidence';evidence.mkdir()
(evidence/'source-registry.patch').write_text(''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/geological_agent/geology/source_registry.py',tofile='b/geological_agent/geology/source_registry.py')))
for p in ('geological_agent/geology/collection_contracts.py','legacy/ToolsAgent/ToolsFuns/source_contracts.py'):
 assert digest(candidate/p)==expected[p]
env=os.environ.copy();env['WFLOW_HOST_CANDIDATE']=str(candidate)
original=subprocess.run([python,str(root/'original-proof/acceptance.py')],cwd=root/'original-proof',capture_output=True,text=True,env=env)
(evidence/'original66.stdout.txt').write_text(original.stdout);(evidence/'original66.stderr.txt').write_text(original.stderr)
code=original.returncode
if code==0:
 shared=subprocess.run([python,str(root/'acceptance_collection.py')],cwd=root,capture_output=True,text=True,env=env)
 (evidence/'shared.stdout.txt').write_text(shared.stdout);(evidence/'shared.stderr.txt').write_text(shared.stderr)
 code=shared.returncode
after={p:digest(base/p) for p in expected}
(evidence/'baseline-immutability.json').write_text(json.dumps({'before':before,'after':after,'unchanged':before==after,'private_shared_SDK_sha256':digest(candidate/'geological_agent/geology/collection_contracts.py'),'private_legacy_contract_sha256':digest(candidate/'legacy/ToolsAgent/ToolsFuns/source_contracts.py')},indent=2))
if after!=before and code==0:code=2
(evidence/'setup.json').write_text(json.dumps({'interpreter':python,'candidate':str(candidate),'baseline':str(base),'fixed_entry':str(root/'fixed_entry_collection.py'),'record':record['id'],'registration':'real_catalog_and_shared_decorator_and_source_registry','shared_contracts_modified':False,'parent_latest_or_7op_touched':False,'runtime_installs':False,'all_child_exit_codes_propagated':True},indent=2))
files={str(p.relative_to(root)):base64.b64encode(p.read_bytes()).decode() for folder in (evidence,root/'original-proof/evidence') if folder.exists() for p in folder.iterdir() if p.is_file()}
print(json.dumps({'exit_code':code,'files_base64':files,'original_child_exit_code':original.returncode}))
sys.exit(code)
'''
    for marker, value in {"__REMOTE__": repr(REMOTE), "__BASE__": repr(BASE), "__PYTHON__": repr(PYTHON), "__PROTECTED__": repr(PROTECTED), "__PAYLOAD__": repr(payload)}.items():
        assert remote_code.count(marker) == 1, marker
        remote_code = remote_code.replace(marker, value)
    environment = ("env CUDA_VISIBLE_DEVICES='' NVIDIA_VISIBLE_DEVICES=none PROJ_NETWORK=OFF LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false GEOTOOL_LANGSMITH_ENABLED=0 "
        "OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 NUMBA_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 "
        f"MPLCONFIGDIR={REMOTE}/cache/transport/matplotlib NUMBA_CACHE_DIR={REMOTE}/cache/transport/numba XDG_CACHE_HOME={REMOTE}/cache/transport/xdg python3 -")
    proc = subprocess.run(SSH + [environment], input=remote_code.encode(), capture_output=True)
    (HERE / "ssh.stdout.txt").write_bytes(proc.stdout)
    (HERE / "ssh.stderr.txt").write_bytes(proc.stderr)
    if proc.stdout:
        response = json.loads(proc.stdout)
        for relative, encoded in response["files_base64"].items():
            target = (HERE / relative).resolve()
            assert target.is_relative_to(HERE)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(base64.b64decode(encoded))
    if proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, "independent shared Wflow collection acceptance", proc.stdout, proc.stderr)
    return {"child_exit_code": proc.returncode}


def freeze(*args, **kwargs):
    shared = json.loads((HERE / "evidence/acceptance.json").read_text())
    original = json.loads((HERE / "original-proof/evidence/acceptance.json").read_text())
    for report in (shared, original):
        assert report["passed"] and report["failures"] == report["errors"] == report["skipped"] == 0
    assert original["tests"] == 66
    destination = HERE / "integration-r4"
    shutil.copytree(HERE / "proposal", destination)
    shutil.copytree(HERE / "evidence", destination / "evidence")
    shutil.copytree(HERE / "original-proof", destination / "acceptance/original-proof", ignore=shutil.ignore_patterns("cache", "workspaces", "__pycache__"))
    for name in ("fixed_entry_collection.py", "acceptance_collection.py", "run_flow.py"):
        shutil.copyfile(HERE / name, destination / "acceptance" / name)
    profile = destination / "profiles/r4-runtime-profile.json"
    profile.parent.mkdir(exist_ok=True)
    shutil.copyfile(HERE / "evidence/runtime-profile.json", profile)
    original_proof_hash = sha(OLD / "HANDOFF.json")
    assert original_proof_hash == "0178d38a6044063c086a91ee8a42d81f4424784614899b2207a632a16f634d3d"
    files = {p.relative_to(destination).as_posix(): sha(p) for p in destination.rglob("*") if p.is_file()}
    contribution = {
        "revision": "wflow43-real-shared-collection-r4", "frozen": True,
        "operation": NAME, "source_project_id": 43, "coverage_target_project_id": 43, "coverage_kind": "original_bounded_operation",
        "functional_replacement": False, "original_source_and_GPL_retained": True, "full_system_equivalence": False,
        "catalog_records": "catalog-records.json", "manifest_operations": "manifest.json", "source_helpers": "source/geological_agent/geology/collection_wflow43.py",
        "source_vendor_package": "source/geological_agent/geology/collection_vendor/approved_wflow43", "source_registry_patch": "evidence/source-registry.patch",
        "skill_records": "skill-records.json", "examples": "examples.json", "shared_fixtures": "acceptance/fixtures.py:prepare", "shared_checks": "acceptance/checks.py:check",
        "shared_collection_acceptance": shared, "retained_original_proof_acceptance": original,
        "interpreter": PYTHON, "candidate": REMOTE + "/candidate", "fixed_entry": REMOTE + "/fixed_entry_collection.py",
        "fixed_entry_request": "JSON object on stdin; WFLOW_COLLECTION_WORKSPACE must be an existing fresh owned workspace; fixed entry sets private CPU/cache/tracing guards before all native imports",
        "host_requirements": HOST_PINS, "science_requirements": SCIENCE_PINS,
        "source_mode": "vendored_source", "requirements_semantics": "Unmodified shared SDK checks combined exact host and science pins in actual executing R4 interpreter. No worker, no installed full wflow package/version claim, no runtime installation, no pin stripping. Parent latest NumBa/Wflow environment is not asserted checked.",
        "old_frozen_receipt_sha256": original_proof_hash, "old_failures_retained": True,
        "corrected_diagnostic": "evidence/diagnostic-repaired.json", "only_diagnostic_mechanics_corrected": "The previously nonexistent module lookup now resolves real collection_contracts and legacy.ToolsAgent.ToolsFuns.source_contracts; no shared core edited.",
        "parent_replacements_profile_supplement": "profiles/replacements-profile-supplement-r2.json" if (destination / "profiles/replacements-profile-supplement-r2.json").exists() else None,
        "two_prior_replacements_58_tests_in_latest_profile_rerun": False,
        "parent_canonical_or_7op_candidate_modified": False, "parent_count_delta": 0,
        "auto_merge_or_deployment_authorized_by_this_receipt": False,
        "formal_lab_and_redistribution_review": "pending receiving owner; original GPL source/license preserved, no formal legal or full system claims",
        "GPU_used": False, "models_used": False, "runtime_installs": False, "deployed": False, "pushed": False,
        "files_sha256": files,
    }
    write_json(destination / "contribution.json", contribution)
    write_json(HERE / "HANDOFF.json", {"frozen_contribution": str(destination / "contribution.json"),
        "contribution_sha256": sha(destination / "contribution.json"), "operation": NAME, "source_project_id": 43,
        "shared_tests": shared["tests"], "retained_original_tests": original["tests"], "failures": 0, "skipped": 0,
        "real_collection_decorator_catalog_registry_and_native_acceptance": True, "parent_count_delta": 0,
        "all_file_hashes": "integration-r4/contribution.json:files_sha256", "actual_interpreter": PYTHON,
        "fixed_entry": REMOTE + "/fixed_entry_collection.py", "science_requirements": SCIENCE_PINS, "host_requirements": HOST_PINS,
        "scope": "Independent CPU source contribution only; no production, parent canonical or 7-op changes"})
    return {"handoff": str(HERE / "HANDOFF.json"), "contribution_sha256": sha(destination / "contribution.json")}


if __name__ == "__main__":
    a = task(prepare, name="hash_bound_old_sources_and_new_collection_proposal")
    b = task(run_tests, name="retained66_and_real_shared_collection_CPU_native_acceptance", depends_on=[a])
    c = task(freeze, name="freeze_real_integrable_source_contribution", depends_on=[b])
    results = Flow(c, max_workers=1, journal_path=str(HERE / "flow-r4.jsonl")).run()
    failed = [value for value in results.values() if value.state.value not in ("succeeded", "cached")]
    for value in failed:
        if isinstance(value.error, subprocess.CalledProcessError): raise SystemExit(value.error.returncode or 1)
    raise SystemExit(1 if failed else 0)

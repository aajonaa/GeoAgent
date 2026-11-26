"""Attach completed local evidence without changing scientific source, pins or schemas."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[6]
REL = "catalog/source_delivery/expansion501-20261026/groups/geology"
GROUP = ROOT / REL
RUN = GROUP / "acceptance/local-r6-gpr-20261026"
ID = "GeoConditionedResourceEnsemble"

def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

report = read(RUN / "gpr-report.json")
stability = read(RUN / "source-stability.json")
preconditions = read(RUN / "source-preconditions.json")
distributions = read(RUN / "installed-distributions.json")
if (report["executed_unique_tests"] != 20 or report["passed"] != 20
        or report["failures"] or report["errors"] or report["skipped"] or not stability["unchanged"]):
    raise RuntimeError("Do not promote failed/incomplete local evidence.")
milestone = GROUP / "resolution-r6/local-gpr-milestone.json"
if milestone.exists():
    raise RuntimeError("Preserve immutable evidence; this finalizer is one-shot.")

evidence = {
    "status": "local_private_cpu_passed_not_production_accepted",
    "python": "3.12.14", "platform": "Windows", "provider": "scikit-learn==1.7.2",
    "executed_unique_tests": 20, "passed": 20, "failed": 0,
    "breakdown": {"registration_schema_pins": 1, "numeric_and_reproducibility": 8, "negative": 11},
    "calls": report["counts"], "positive_decorated_calls": 8, "positive_runtime_calls": 1,
    "negative_decorated_calls": 21, "negative_runtime_calls": 1,
    "source_unchanged_during_run": True, "report": (RUN / "gpr-report.json").relative_to(ROOT).as_posix(),
    "report_sha256": sha(RUN / "gpr-report.json"),
    "catalog_scope": "private_single_entry_group_catalog_with_unmodified_parent_r3_source_registry",
    "non_psd_test": "Explicit upstream-predict fault injection; not a naturally produced invalid covariance.",
    "main_runtime_v2": "not_run", "linux_production_acceptance": "not_run",
    "model_workflow": "not_run", "platform_validation": "not_run", "formal_eligible": False,
    "deployment_status": "not_deployed", "submission_status": "not_submitted"}

spec = read(GROUP / "contribution-spec.json")
row = next(x for x in spec["operations"] if x["id"] == ID)
row["local_acceptance"] = evidence
write(GROUP / "contribution-spec.json", spec)

catalog = read(GROUP / "catalog-additions.json")
tool = next(x for x in catalog["tools"] if x["id"] == ID)
tool["metadata"]["scientific_contract"]["local_cpu_acceptance"] = evidence
tool["metadata"]["scientific_contract"]["execution_status"] = "LOCAL_CPU_PARTIAL_ACCEPTANCE; Linux/v2 not_run"
tool["limitations"] = [
    "Local private CPU evidence exists; Linux/v2 acceptance NOT TESTED. NOT DEPLOYED / NOT SUBMITTED. Model/platform workflows not_run."
    if x == "NOT TESTED / NOT DEPLOYED / NOT SUBMITTED. Model/platform workflows not_run." else x
    for x in tool["limitations"]]
write(GROUP / "catalog-additions.json", catalog)

statuses = read(GROUP / "adaptation-status.json")
status = next(x for x in statuses["operations"] if x["id"] == ID)
status["reason"] += (
    " Local private Python 3.12.14 acceptance passed 20/20 tests, including actual source registration, "
    "decorated calls, ToolExecutor typed results, analytic full Schur covariance and negative guards. "
    "This is not parent v2 cross-interpreter or Linux acceptance; formal_eligible remains false.")
write(GROUP / "adaptation-status.json", statuses)

binding = read(GROUP / "private-cpu-binding.json")
binding["local_acceptance"] = {ID: evidence}
write(GROUP / "private-cpu-binding.json", binding)

skill = ROOT / "catalog/skills/expansion501-geology-conditional-resource-fields/SKILL.md"
text = skill.read_text(encoding="utf-8")
text = text.replace(
    "formal_eligible=false. NOT TESTED. Deployment:",
    "formal_eligible=false. Linux/v2 acceptance NOT TESTED. Local private CPU acceptance passed 20/20. Deployment:")
text += (
    "\n## Local CPU acceptance r6\n\n"
    "Python 3.12.14 / scikit-learn 1.7.2 in a fresh private Windows environment: 20/20 tests passed; "
    "29 decorated invocations and 2 registered ToolExecutor invocations. Full analytic conditional covariance, "
    "the zero cross-covariance counterexample, explicit noise, repeatability, duplicate-coordinate rejection, "
    "near-singular conditioning and fault-injected non-PSD rejection were checked. Source hashes were stable. "
    "Report: " + evidence["report"] + ". No result certifies a resource or measured grade.\n\n"
    "The single-entry private catalog is not production registration. Parent v2 cross-interpreter dispatch, "
    "Linux acceptance, receiving-lab approval, model workflow and deployment remain pending/not_run. "
    "not_deployed; not_submitted.\n")
skill.write_text(text, encoding="utf-8", newline="\n")

lock = RUN / "observed-local-distributions.txt"
lock.write_text(
    "# Observed private Windows acceptance environment, NOT a Linux/transitive compatibility certification.\n"
    "# Exact downloaded wheel URLs/hashes are in pip-install-report.json and pip-runtime-support-report.json.\n"
    + "\n".join(x["name"] + "==" + x["version"] for x in distributions) + "\n",
    encoding="utf-8", newline="\n")
write(milestone, evidence)

old_milestone = GROUP / "resolution-r6/source-milestone.json"
snapshot = GROUP / "resolution-r6/source-milestone-before-local-gpr.json"
shutil.copyfile(old_milestone, snapshot)
current = read(old_milestone)
current["local_gpr_acceptance"] = evidence
current["upstream_tests_executed"] = 20
current["upstream_test_scope"] = "Only the local private GPR suite; not all 26 tools or Linux/v2."
current["source_sha256"] = {p: sha(ROOT / p) for p in current["source_sha256"]}
write(old_milestone, current)

manifest_path = GROUP / "delivery-files.json"
manifest = read(manifest_path)
extras = [
    GROUP / "acceptance/local_gpr_acceptance_r6.py",
    GROUP / "acceptance/finalize_local_gpr_r6.py",
    GROUP / "acceptance/requirements-local-gpr-r6.txt",
    milestone, snapshot,
    RUN / "venv-create.log", RUN / "interpreter.log", RUN / "pip-install.log",
    RUN / "pip-install-report.json", RUN / "provision-exit.json",
    RUN / "pip-runtime-support-report.json", RUN / "pip-runtime-support.log",
    RUN / "source-preconditions.json", RUN / "installed-distributions.json", lock,
    RUN / "gpr-tests.log", RUN / "gpr-report.json", RUN / "source-stability.json",
    RUN / "gpr-flow.jsonl", RUN / "noiseless-direct-result.json",
    RUN / "noisy-direct-result.json", RUN / "registered-runtime-result.json",
    RUN / "source/catalog/registry.json"]
extras.extend(RUN / "source" / x["relative"] for x in preconditions["files"])
manifest["files"] = sorted(set(manifest["files"] + [p.relative_to(ROOT).as_posix() for p in extras]))
write(manifest_path, manifest)
print(json.dumps({"authored": 26, "blocked": 5, "local_gpr_passed": 20,
                  "main_runtime_v2_passed": 0, "linux_new_passed": 0,
                  "delivery_files": len(manifest["files"]), "manifest": str(manifest_path),
                  "scientific_adapter_sha256": sha(ROOT / "geological_agent/geology/expansion501_geology.py")}))


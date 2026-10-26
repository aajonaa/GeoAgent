"""Snapshot-gated r6 source materialization and local reference checks, never a runtime bridge."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import unittest
from fractions import Fraction

ROOT = Path(__file__).resolve().parents[5]
GROUP = "catalog/source_delivery/expansion501-20261026/groups/geology"
HERE = ROOT / GROUP
BEFORE = HERE / "acceptance/blocker-resolution-r6-before"
RUN = HERE / "acceptance/blocker-resolution-r6-local"
RESOLUTION = HERE / "resolution-r6"
ASSETS = "assets/expansion501-geology"
MODULE = "geological_agent.geology.expansion501_geology"
CPU_ID = "expansion501-geology-cpu-v1"
SYNTHETIC = "SYNTHETIC analytic fixture; no measured resource, assay or engineering observation."
CONVENTION = "periodictable-2.1.0-elemental"
COMMON = ["numpy==2.1.3", "scipy==1.15.3", "pandas==2.3.0",
          "matplotlib==3.10.7", "jsonschema==4.25.1"]
CONDITIONAL = COMMON + ["scikit-learn==1.7.2"]
TORTUOSITY = ["numpy==2.1.3", "scipy==1.16.2", "pandas==2.3.2",
              "matplotlib==3.10.7", "jsonschema==4.25.1", "porespy==3.2.0",
              "openpnm==3.6.1", "pyamg==5.3.0", "numba==0.68.0", "scikit-image==0.26.0"]
CONDITIONAL_ID = "GeoConditionedResourceEnsemble"
TORTUOSITY_ID = "Geo500PoreDiffusionTortuosity"
BINDING_GAPS = ["parent_owned_v2_fixed_profile_binding_pending",
                "main_runtime_to_private_cpu_result_path_not_accepted",
                "full_transitive_binary_lock_and_license_review_pending"]

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def closed(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}

def number(lower=None, upper=None, positive=False):
    result = {"type": "number"}
    if lower is not None:
        result["minimum"] = lower
    if upper is not None:
        result["maximum"] = upper
    if positive:
        result["exclusiveMinimum"] = 0
    return result

def integer(lower, upper):
    return {"type": "integer", "minimum": lower, "maximum": upper}

def arr(items, lower, upper):
    return {"type": "array", "items": items, "minItems": lower, "maxItems": upper}

def fixed(value):
    return {"type": "boolean" if isinstance(value, bool) else "string", "const": value}

def provenance_input():
    return {"type": "string", "minLength": 1, "maxLength": 512,
            "description": "Caller-declared provenance, not independently authenticated."}

def conditional_row():
    xyz = arr(number(-1e9, 1e9), 3, 3)
    return {
        "id": CONDITIONAL_ID, "fn": "conditioned_resource_ensemble", "source": "conditional",
        "task": "Jointly condition and sample a Gaussian geochemical field using an explicit known mean, exponential covariance and measurement-noise variance.",
        "api": "sklearn/gaussian_process/_gpr.py",
        "input_schema": closed({
            "data_source": provenance_input(),
            "observation_coordinates_m": arr(xyz, 1, 64),
            "observed_values_ppm": arr(number(0, 1e6), 1, 64),
            "target_coordinates_m": arr(copy.deepcopy(xyz), 1, 128),
            "known_mean_ppm": number(0, 1e6), "prior_variance_ppm2": number(upper=1e12, positive=True),
            "correlation_length_m": number(upper=1e8, positive=True),
            "measurement_noise_variance_ppm2": number(0, 1e12),
            "realization_count": integer(1, 4096), "random_seed": integer(0, 4294967295)}),
        "output_properties": {
            "conditional_mean": arr(number(), 1, 128),
            "conditional_covariance": arr(arr(number(), 1, 128), 1, 128),
            "realizations": arr(arr(number(), 1, 128), 1, 4096),
            "measurement_noise_variance": number(0, 1e12),
            "covariance_model": fixed("isotropic_exponential_matern_nu_0.5"),
            "predicted_quantity": fixed("latent_gaussian_field"), "optimizer_used": fixed(False),
            "jitter_added": fixed(False), "negative_realizations_clipped": fixed(False),
            "random_seed": integer(0, 4294967295)},
        "units": {"conditional_mean": "ppm", "conditional_covariance": "ppm^2",
                  "realizations": "ppm", "coordinates": "m", "measurement_noise_variance": "ppm^2"},
        "example": {"data_source": SYNTHETIC, "observation_coordinates_m": [[0, 0, 0]],
                    "observed_values_ppm": [12], "target_coordinates_m": [[-1, 0, 0], [1, 0, 0]],
                    "known_mean_ppm": 10, "prior_variance_ppm2": 4, "correlation_length_m": 1,
                    "measurement_noise_variance_ppm2": 0, "realization_count": 64, "random_seed": 50126},
        "numeric_oracle": "Independent one-observation Schur complement: mean=10+2/e, covariance diagonal=4*(1-exp(-2)), off-diagonal exactly zero for x=-1,+1 conditioned at 0. With alpha=1, off-diagonal=0.8*exp(-2)>0 and mean=10+8/(5e). Check full covariance, not empirical marginals. Samples use that same joint covariance; no pointwise scaling.",
        "distinct_from_existing": "Original GSTools candidate is replaced, not counted twice. Existing kriging and external-drift estimates do not return joint conditional realizations and full cross-covariance. No covariance-model or axis variants are separate tools.",
        "limitations": [
            "Actual provider is scikit-learn 1.7.2, not GSTools. Fixed ConstantKernel times Matern nu=0.5; optimizer=None, normalize_y=False, explicit known mean.",
            "Independent homoscedastic observation-error variance alpha is explicit; outputs describe the latent field, not a fresh noisy assay.",
            "Coordinates are metres in one caller-defined Cartesian system; no CRS transform, detrending, fit or hyperparameter optimization.",
            "Repeated conditioning/target positions are rejected; a target may equal one observation. Conditioning eigenvalue ratio must be at least 1e-12.",
            "Negative posterior covariance eigenvalues fail without clipping, repair or jitter. A roundoff-induced failure remains a failure.",
            "At most 64 observations, 128 targets and 32768 realization values. Gaussian draws may be negative; never clipped, treated as measured grade, or used alone to certify a mineral resource.",
            "Seed is explicit but pure=false; reproducibility is tied to the fixed interpreter/dependency profile."],
        "skill": "conditional-resource-fields", "integration_blockers": BINDING_GAPS}

def tortuosity_row():
    mask = [False] * 45
    mask[20:25] = [True] * 5
    return {
        "id": TORTUOSITY_ID, "fn": "pore_diffusion_tortuosity", "source": "tortuosity",
        "task": "Solve steady normalized pore diffusion and derive effective diffusivity, formation factor and tortuosity from a face-connected binary voxel geometry.",
        "api": "src/porespy/simulations/_dns.py",
        "input_schema": closed({
            "data_source": provenance_input(), "shape": arr(integer(3, 64), 2, 3),
            "pore_mask": arr({"type": "boolean"}, 9, 32768), "axis": integer(0, 2),
            "voxel_spacing_m": number(upper=10, positive=True),
            "molecular_diffusivity_m2_s": number(upper=1, positive=True)}),
        "output_properties": {
            "tortuosity": number(positive=True), "formation_factor": number(positive=True),
            "original_porosity": number(0, 1), "effective_porosity": number(0, 1),
            "effective_diffusivity": number(positive=True),
            "normalized_concentration": arr(number(-1e-8, 1 + 1e-8), 9, 32768),
            "retained_pore_mask": arr({"type": "boolean"}, 9, 32768),
            "shape": arr(integer(3, 64), 2, 3), "axis": integer(0, 2),
            "voxel_spacing": number(upper=10, positive=True),
            "flux_balance_converged": fixed(True), "normalized_boundary_values": {
                "type": "array", "prefixItems": [{"const": 1.0}, {"const": 0.0}],
                "items": False, "minItems": 2, "maxItems": 2}},
        "units": {"tortuosity": "dimensionless", "formation_factor": "dimensionless",
                  "porosity": "volume_fraction", "normalized_concentration": "dimensionless",
                  "effective_diffusivity": "m^2/s", "voxel_spacing": "m"},
        "example": {"data_source": SYNTHETIC, "shape": [3, 3, 5], "pore_mask": mask, "axis": 2,
                    "voxel_spacing_m": 1e-5, "molecular_diffusivity_m2_s": 1e-9},
        "numeric_oracle": "Independent series-resistance calculation for a five-voxel straight channel in a 3x3 cross-section: porosity=1/9, four unit resistors, lattice length=4, tortuosity=1, formation factor=9, Deff=D0/9; channel concentration=[1,.75,.5,.25,0]. Fixed numerical tolerances are 1e-7 for tau/formation/concentration, 1e-17 m^2/s for Deff.",
        "distinct_from_existing": "Existing pore chords, body radii and quasistatic drainage do not solve the Laplace/Fick diffusion boundary-value problem or estimate transport tortuosity. No axis is counted as another tool.",
        "limitations": [
            "PoreSpy 3.2.0 calls OpenPNM 3.6.1 and its fixed PyAMG solver; no local replacement diffusion solver.",
            "Dedicated profile requires SciPy 1.16.2 and pandas 2.3.2. Never install this profile over the existing pores or main environment.",
            "2D means unit out-of-plane thickness; isotropic voxel spacing cancels from the relative diffusivity. Boundary distance is (shape[axis]-1)*spacing.",
            "Both solid and void required; face-connected spanning pores required. Nonspanning pores are removed by upstream and both original/effective porosities are returned.",
            "Fixed residual tolerance 1e-10 and relative inlet/outlet flux-balance tolerance 1e-6. No arbitrary solver, executable, convergence loosening or GPU.",
            "Concentration is meaningful only where retained_pore_mask is true; zeros elsewhere are upstream solid/dropped-void sentinels, not measurements.",
            "Full binary lock, including OpenPNM's Linux x86_64 pypardiso dependency, remains pending. Only CPU PyAMG is explicitly selected."],
        "skill": "porous-geometry", "integration_blockers": BINDING_GAPS}

def source_records():
    return {
        "conditional": {"package": "scikit-learn", "version": "1.7.2",
            "repo": "scikit-learn/scikit-learn", "commit": "25dee604bae18205b01548348388baf7a1cdfe0e",
            "license": "BSD-3-Clause", "license_file": "COPYING",
            "requirements": CONDITIONAL, "profile": "conditional",
            "qualification": "Maintained replacement for the blocked GSTools joint-conditional candidate. Published release/source commit are separate identities; redistribution acceptance not established."},
        "tortuosity": {"package": "porespy", "version": "3.2.0", "repo": "PMEAL/porespy",
            "commit": "916fdc135bfb08d84b8d9173d6de9174ff217e5d", "license": "MIT", "license_file": "LICENSE",
            "requirements": TORTUOSITY, "profile": "tortuosity",
            "companion": {"package": "openpnm", "version": "3.6.1", "repo": "PMEAL/OpenPNM",
                "commit": "a8b46807f4d4f61ec9a9f0c16fa5d37fc95c9337", "license": "MIT",
                "license_evidence": "https://github.com/PMEAL/OpenPNM/blob/a8b46807f4d4f61ec9a9f0c16fa5d37fc95c9337/LICENSE"},
            "qualification": "Separate CPU profile; no main-runtime or existing pores-profile replacement. Source confirms NumPy<2.2, SciPy>=1.16.2 and pandas>=2.3.2."}}

BLOCKED = {
    "Geo50026ConstrainedChemicalEquilibrium": {
        "reason": "Reaktoro 2.13.0 source and a CPU py312 conda artifact are identified, but a complete native dependency lock, verified database raw-byte hash/license, fixed constrained-system contract and independent equilibrium reference are not delivered. No registered wrapper or fixed v2 binding.",
        "blockers": ["native_transitive_binary_lock_missing", "database_raw_sha256_and_terms_pending",
                     "fixed_system_and_independent_equilibrium_reference_pending", "v2_native_binding_pending"]},
    "Geo50026MineralReactionKinetics": {
        "reason": "The maintained Reaktoro Palandri-Kharaka workflow is confirmed, but its database, parameter bytes, mineral surface convention, native runtime lock and independent time-path reference are not frozen together. Equilibrium imports or endpoint conservation cannot certify this kinetic operation.",
        "blockers": ["native_transitive_binary_lock_missing", "database_and_rate_parameter_identity_pending",
                     "surface_area_and_rate_domain_contract_pending", "independent_time_path_oracle_pending",
                     "v2_native_binding_pending"]},
    "Geo50026ReactiveColumnTransport": {
        "reason": "Maintained PhreeqPy 0.6.0 wrapper wheel is identified, but its bundled IPhreeqc binary's content identity and ABI, release-to-source correspondence, offline database rights/hash, fixed column template and lifecycle reference are not verified. Arbitrary PHREEQC input strings remain forbidden.",
        "blockers": ["iphreeqc_binary_sha256_abi_pending", "wrapper_release_source_mapping_pending",
                     "database_identity_and_terms_pending", "fixed_transport_template_oracle_pending",
                     "v2_native_binding_pending"]},
    "GeoGeobodyTopology": {
        "reason": "gempy_plugins 2026.0.3 has a real compute_topology implementation, but its topology.py header declares GPL-3.0-or-later while repository metadata says EUPL-1.2. File-level obligations and fixed fault/lithology model binding are unresolved. The pinned core engine topology interface is empty and is not a substitute.",
        "blockers": ["file_level_license_interpretation_pending", "fixed_fault_and_lithology_solution_binding_pending",
                     "independent_geobody_adjacency_reference_pending"]},
    "GeoCpxMeltThermobarometry": {
        "reason": "The identified Thermobar 1.0.75 source retains custom GUI/permission/payment/citation conditions; permission for this delivery is not established. No confirmed maintained license-compatible paired clinopyroxene-melt replacement was found. Cpx-only thermometry, olivine primary melts and own equation rewrites are not accepted substitutes.",
        "blockers": ["original_license_use_not_authorized", "maintained_compatible_equivalent_not_confirmed",
                     "paired_composition_calibration_and_oracle_pending"]}}

def evidence_document():
    return {"status": "source_revised_unverified", "formal_eligible": False,
        "legal_review": "Source evidence only; not a complete delivery-license determination.",
        "records": [
            {"id": CONDITIONAL_ID, "candidate_provider": "GSTools", "actual_provider": "scikit-learn",
             "source_commit": "25dee604bae18205b01548348388baf7a1cdfe0e",
             "api": "sklearn.gaussian_process.GaussianProcessRegressor.predict(return_cov=True) and sample_y",
             "url": "https://github.com/scikit-learn/scikit-learn/blob/25dee604bae18205b01548348388baf7a1cdfe0e/sklearn/gaussian_process/_gpr.py",
             "license_url": "https://github.com/scikit-learn/scikit-learn/blob/25dee604bae18205b01548348388baf7a1cdfe0e/COPYING"},
            {"id": TORTUOSITY_ID, "api": "porespy.simulations.tortuosity_fd",
             "url": "https://github.com/PMEAL/porespy/blob/916fdc135bfb08d84b8d9173d6de9174ff217e5d/src/porespy/simulations/_dns.py",
             "dependency_evidence": "https://github.com/PMEAL/OpenPNM/blob/a8b46807f4d4f61ec9a9f0c16fa5d37fc95c9337/pyproject.toml",
             "cleanup_api": "openpnm.Workspace.close_project",
             "cleanup_url": "https://github.com/PMEAL/OpenPNM/blob/a8b46807f4d4f61ec9a9f0c16fa5d37fc95c9337/src/openpnm/utils/_workspace.py"},
            {"ids": ["Geo50026ConstrainedChemicalEquilibrium", "Geo50026MineralReactionKinetics"],
             "project": "Reaktoro", "release": "2.13.0",
             "source_commit": "3c5838e7c0ed2931ad152176414cb786311dbe47", "license": "LGPL-2.1-or-later in source; conda metadata differs",
             "license_url": "https://github.com/reaktoro/reaktoro/blob/3c5838e7c0ed2931ad152176414cb786311dbe47/LICENSE",
             "artifact_url": "https://api.anaconda.org/download/conda-forge/reaktoro/2.13.0/linux-64/reaktoro-2.13.0-py312h0d7fa09_1.conda",
             "artifact_sha256": "909ee85c9c077c363d9586ef00cc357a1c7d57440360a2388a37f7f60624d72d",
             "artifact_identity_evidence": "https://api.anaconda.org/package/conda-forge/reaktoro",
             "artifact_status": "metadata_identified_not_downloaded_not_locked_not_executed",
             "database_url": "https://github.com/reaktoro/reaktoro/blob/3c5838e7c0ed2931ad152176414cb786311dbe47/embedded/databases/phreeqc/phreeqc.dat",
             "database_git_blob_sha1_not_sha256": "9e69a1875801b8fe41c363030e9139bbb635a35c",
             "rate_parameter_url": "https://github.com/reaktoro/reaktoro/blob/3c5838e7c0ed2931ad152176414cb786311dbe47/embedded/params/PalandriKharaka.yaml",
             "rate_parameter_git_blob_sha1_not_sha256": "d53496171fb6af33c756ab7cb751b56376fbaa8f",
             "api_evidence": ["https://reaktoro.org/api/classReaktoro_1_1PhreeqcDatabase.html",
                              "https://reaktoro.org/tutorials/kinetics/kinetics-minerals-using-palandri-kharaka-model.html"]},
            {"id": "Geo50026ReactiveColumnTransport", "project": "PhreeqPy", "release": "0.6.0",
             "source_commit_reviewed_main_not_release_mapping": "3cc5fde5b2196491f239520715570d2a87e8f4d8",
             "api": "phreeqpy.iphreeqc.phreeqc_dll.IPhreeqc.load_database_string/run_string/get_selected_output_array/destroy_iphreeqc",
             "source_url": "https://github.com/hydrocomputing/phreeqpy/blob/3cc5fde5b2196491f239520715570d2a87e8f4d8/src/phreeqpy/iphreeqc/phreeqc_dll.py",
             "license_url": "https://github.com/hydrocomputing/phreeqpy/blob/3cc5fde5b2196491f239520715570d2a87e8f4d8/LICENSE",
             "wheel_url": "https://files.pythonhosted.org/packages/d6/34/aee229940fb5b264e7fc42f0a18c3ddf715ca0dbc21350ec10c29cf175fd/phreeqpy-0.6.0-py3-none-any.whl",
             "wheel_sha256": "fc133d1ce9224f94a39633010026858f2dd0cdbe9dab6dad9ea8d47f4143cbda",
             "identity_evidence": "https://pypi.org/pypi/phreeqpy/0.6.0/json",
             "binary_path": "src/phreeqpy/iphreeqc/phreeqc3/libiphreeqc-3.7.3.so",
             "binary_git_blob_sha1_not_sha256": "a837924a5e3a4141e30e5063656c7c3464f38761",
             "qualification": "No binary was downloaded or executed; wrapper BSD evidence does not establish database or bundled-binary rights."},
            {"id": "GeoGeobodyTopology", "project": "gempy_plugins", "release": "2026.0.3",
             "source_commit": "647ae9eae821d7b8a02c9ae85f67f56cf42d8ffa",
             "api": "gempy_plugins.topology_analysis.topology.compute_topology",
             "source_url": "https://github.com/gempy-project/gempy_plugins/blob/647ae9eae821d7b8a02c9ae85f67f56cf42d8ffa/gempy_plugins/topology_analysis/topology.py",
             "license_url": "https://github.com/gempy-project/gempy_plugins/blob/647ae9eae821d7b8a02c9ae85f67f56cf42d8ffa/LICENSE",
             "qualification": "File header GPL-3.0-or-later versus repository EUPL-1.2 is not resolved by choosing the root license. GemPy engine 18a1f876d2816e1a953d14cdbfce28845c51c750 core topology interface is empty."},
            {"id": "GeoCpxMeltThermobarometry", "project": "Thermobar", "release": "1.0.75",
             "source_commit": "c1978e87f073902778b5589bd2b3b6adfd6de695",
             "license_url": "https://github.com/PennyWieser/Thermobar/blob/c1978e87f073902778b5589bd2b3b6adfd6de695/LICENSE.txt",
             "qualification": "Original not used. No maintained legally compatible exact replacement confirmed; no inferred permission."}]}

def bridge_document():
    profiles = {}
    for name, identifier, function, requirements in (
        ("conditional", CONDITIONAL_ID, "conditioned_resource_ensemble", CONDITIONAL),
        ("tortuosity", TORTUOSITY_ID, "pore_diffusion_tortuosity", TORTUOSITY)):
        profiles["expansion501-geology-" + name + "-cpu-v1"] = {
            "tool_ids": [identifier], "kind": "expansion501_geology",
            "entrypoint": MODULE + ":" + function, "argument_parameter": "args",
            "requirements": requirements, "python": "3.12.*",
            "requirements_file": GROUP + "/requirements-" + name + ".txt",
            "environment": {"GEOAGENT_EXPANSION501_GEOLOGY_CPU": CPU_ID,
                "CUDA_VISIBLE_DEVICES": "", "NVIDIA_VISIBLE_DEVICES": "void",
                "HIP_VISIBLE_DEVICES": "", "ROCR_VISIBLE_DEVICES": "", "ZE_AFFINITY_MASK": "",
                "JAX_PLATFORMS": "cpu", "GEMPY_USE_GPU": "False", "GEMPY_GPU_FALLBACK": "False",
                "MPLBACKEND": "Agg", "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2",
                "MKL_NUM_THREADS": "2", "NUMEXPR_NUM_THREADS": "2",
                "VECLIB_MAXIMUM_THREADS": "2", "BLIS_NUM_THREADS": "2",
                "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"},
            "limits": {"stdout_bytes": 4194304, "stderr_bytes": 65536,
                       "wall_seconds": 120, "memory_bytes": 2147483648},
            "transport": "JSON-only; no output_dir, artifact paths, user program, module, function, argv or environment.",
            "artifacts": [], "main_runtime_integration": "pending_parent_v2",
            "runtime_and_entry_hashes": "parent_must_bind_verified_absolute_private_interpreter_and_source_hashes",
            "full_transitive_lock": "pending"}
    return {"owner": "parent/Ramanujan", "bridge": "isolated_cpu_bridge_v2.py + worker_v2.py",
        "status": "requirements_only_not_a_second_bridge",
        "dependency_hook": "After strict input/schema validation and before main-interpreter _dependencies: only an administrator-approved fixed tool/profile binding may dispatch. The authenticated child executes the ordinary operation wrapper and checks every real declared dependency. A user environment marker alone must not authorize recursion bypass.",
        "result_path": "Parent validates real exit code, bounded live stdout/stderr, matching request/tool/profile/identity, finite closed output schema and empty artifacts. Preserve the child's installed_versions and input/implementation/contract hashes; do not overwrite them with main-environment versions.",
        "existing_bridge_insufficiency": "Accepted native_cpu_bridge is JSON-only but has fixed accepted profiles, four-thread defaults, post-capture stream limits and different provenance envelope. Do not mutate accepted profiles or use it as an unverified generic bridge.",
        "profiles": profiles,
        "oxygen_profile": {"existing_profile": "chemistry", "tool_id": "Geo500MineralOxygenBasisFormula",
                           "requirements_file": GROUP + "/requirements-chemistry.txt",
                           "change": "Explicit periodictable-2.1.0-elemental input/output convention; original profile pins unchanged."}}

def main():
    sys.path.insert(0, str(Path.home() / ".codex/skills/flowing/scripts"))
    from flowing import Flow, task
    from build_contribution import main as build

    RUN.mkdir(parents=True, exist_ok=False)
    RESOLUTION.mkdir(parents=True, exist_ok=False)

    @task
    def source_and_snapshot_gate():
        snapshot = json.loads((BEFORE / "snapshot.json").read_text(encoding="utf-8-sig"))
        for item in snapshot["files"]:
            archived = BEFORE / item["path"]
            if sha(archived) != item["sha256"]:
                raise RuntimeError("Preserved source hash mismatch: " + item["path"])
        for source in source_records().values():
            if not re.fullmatch(r"[0-9a-f]{40}", source["commit"]):
                raise RuntimeError("Missing immutable upstream source identity")
        return {"ready": True, "preserved": len(snapshot["files"]),
                "snapshot_paths": [(BEFORE / x["path"]).relative_to(ROOT).as_posix()
                                   for x in snapshot["files"]] +
                                  [(BEFORE / "snapshot.json").relative_to(ROOT).as_posix()]}

    @task(depends_on=[source_and_snapshot_gate],
          when=lambda source_and_snapshot_gate: source_and_snapshot_gate["ready"])
    def materialize(source_and_snapshot_gate):
        spec = json.loads((HERE / "contribution-spec.json").read_text(encoding="utf-8"))
        if len(spec["operations"]) != 24 or len(spec["blocked"]) != 7:
            raise RuntimeError("Expected the preserved 24-authored/7-blocked source, not a rerun.")
        spec["sources"].update(source_records())
        spec["skills"]["conditional-resource-fields"] = "Joint conditional geochemical field ensembles"
        oxygen = next(r for r in spec["operations"] if r["id"] == "Geo500MineralOxygenBasisFormula")
        oxygen["input_schema"]["properties"]["atomic_weight_convention"] = fixed(CONVENTION)
        oxygen["input_schema"]["required"].append("atomic_weight_convention")
        oxygen["example"]["atomic_weight_convention"] = CONVENTION
        oxygen["output_properties"]["atomic_weight_convention"] = fixed(CONVENTION)
        oxygen["output_properties"]["oxide_molar_masses"] = arr(number(positive=True), 1, 12)
        oxygen["units"]["oxide_molar_masses"] = "g/mol"
        oxygen["numeric_oracle"] = (
            "Original wt% fixture is preserved: 57.293630232496 MgO and 42.706369767504 SiO2. "
            "Explicit elemental masses Mg=24.305, Si=28.085, O=15.999 g/mol give oxide masses "
            "40.304 and 60.083. Independent exact-decimal stoichiometry yields Mg=1.9999704077834797, "
            "Si=1.0000147961082602, O=4; atol=1e-6 and rtol=0 unchanged. A separate ideal "
            "2MgO+SiO2 fixture constructed from the same masses must give Mg=2, Si=1, O=4. "
            "Neither expected value calls pyrolite or periodictable.")
        oxygen["limitations"].append(
            "Required atomic_weight_convention is periodictable-2.1.0-elemental; aligned oxide molar masses "
            "are reported. No isotope override, hidden normalization, tolerance change or rewritten kernel.")
        spec["operations"].extend([conditional_row(), tortuosity_row()])
        spec["upstream_callables"].update({
            CONDITIONAL_ID: "sklearn.gaussian_process.GaussianProcessRegressor.fit/predict/sample_y",
            TORTUOSITY_ID: "porespy.simulations.tortuosity_fd"})
        retained = []
        for old in spec["blocked"]:
            if old["id"] in (CONDITIONAL_ID, TORTUOSITY_ID):
                continue
            item = copy.deepcopy(old)
            item["previous_reason_preserved"] = old["reason"]
            item.update(BLOCKED[old["id"]])
            item["evidence_revision"] = GROUP + "/resolution-r6/source-evidence.json"
            retained.append(item)
        spec["blocked"] = retained
        spec["license_copy_paths"].extend([
            GROUP + "/licenses/scikit-learn-1.7.2-COPYING.txt",
            GROUP + "/licenses/openpnm-3.6.1-LICENSE.txt"])
        save(HERE / "contribution-spec.json", spec)
        save(RESOLUTION / "source-evidence.json", evidence_document())
        save(RESOLUTION / "shared-bridge-requirements.json", bridge_document())
        mg_o, si_o2 = Fraction("40.304"), Fraction("60.083")
        ideal = copy.deepcopy(oxygen["example"])
        ideal["data_source"] = SYNTHETIC + " Ideal Mg2SiO4 constructed from explicitly declared atomic masses."
        ideal["oxide_wt_percent"] = [float(200 * mg_o / (2 * mg_o + si_o2)),
                                   float(100 * si_o2 / (2 * mg_o + si_o2))]
        ideal_path = ASSETS + "/Geo500MineralOxygenBasisFormula-ideal.json"
        save(ROOT / ideal_path, ideal)
        save(RESOLUTION / "oxygen-convention.json", {
            "tool_id": oxygen["id"], "convention": CONVENTION,
            "atomic_masses_g_mol": {"Mg": 24.305, "Si": 28.085, "O": 15.999},
            "oxide_molar_masses_g_mol": {"MgO": 40.304, "SiO2": 60.083},
            "original_wt_percent_preserved": [57.293630232496, 42.706369767504],
            "original_expected_apfu": {"Mg": 1.9999704077834797, "Si": 1.0000147961082602, "O": 4},
            "absolute_tolerance_unchanged": 1e-6, "relative_tolerance_unchanged": 0,
            "ideal_fixture": ideal_path, "ideal_expected_apfu": {"Mg": 2, "Si": 1, "O": 4},
            "causes": ["The original fixture is not exact 2MgO:SiO2 under the pinned elemental masses.",
                       "The previous oracle asserted ideal APFU without declaring a matching atomic-weight convention; dict and JSON failures share this cause, not two different kernels."],
            "evidence": [
                "https://github.com/python-periodictable/periodictable/blob/83b643f4ca4c7d8cf5202c13e32921b572da9896/periodictable/mass.py",
                "https://github.com/morganjwilliams/pyrolite/blob/ab651b448ecd2ce1bc22d752b80a977a1f4dd1ca/pyrolite/mineral/transform.py"],
            "historical_failures": "All prior CPU logs and pre-resolution-r6 snapshots retained. This convention correction does not retroactively convert any historical failure into a pass."})
        README = """# Geology blocker resolution r6

26 concrete source adapters, 5 blocked assignments, 9 workflow Skills. All 31 original assignments are covered exactly once; no new candidate ID is added. Two previously blocked candidates now have concrete source, not accepted main-runtime integration.

- GeoConditionedResourceEnsemble: maintained scikit-learn 1.7.2 replacement, full joint posterior covariance and posterior draws, fixed exponential covariance, explicit mean/noise, no fitting or jitter.
- Geo500PoreDiffusionTortuosity: PoreSpy 3.2.0 / OpenPNM 3.6.1 / PyAMG 5.3.0; separate SciPy 1.16.2 / pandas 2.3.2 profile.
- Geo500MineralOxygenBasisFormula: original wt% retained; explicit periodictable 2.1.0 elemental masses and independent stoichiometry; original atol=1e-6/rtol=0 retained; separate ideal-mineral fixture.

The five remaining blocked assignments are excluded from catalog-additions.json. Their exact native/database/license/model-binding gaps and immutable procurement evidence are in resolution-r6/source-evidence.json and blocked-evidence.json. No unsupported Thermobar or GemPy-plugin wrapper is registered.

## Runtime handoff

Parent/Ramanujan owns isolated_cpu_bridge_v2.py, worker_v2.py and the shared collection_contracts hook. This group authors no alternative bridge. See resolution-r6/shared-bridge-requirements.json for two fixed profiles. Keep exact dependency checks inside the authenticated private interpreter; a catalog plus venv is not main-runtime integration. Empty artifacts only. No user executable/module/function/shell argument is accepted. GPU devices must be hidden and every BLAS limit at most 2.

## Evidence and status

source_revised_unverified; acceptance_pending; formal_eligible=false.
not_deployed; not_submitted; model/Skill/platform workflow not_run. Receiving AI Lab certification is not established.

Historical remote evidence remains unchanged, including the two oxygen failures and missing GeoStatsPy timeout. Original 59 delivery files were snapshotted under acceptance/blocker-resolution-r6-before. No prior pass or failure is relabelled.

resolve_blockers_r6.py uses Flow to gate preserved hashes, source materialization and seven standard-library reference/source tests. Those seven checks do not execute upstream kernels and do not establish scientific or integration acceptance. A separate local private Python 3.12 GPR run, if executed, must have its own report and cannot substitute for parent v2 acceptance. No remote setup/upload is attempted.

## Reproduction and limits

build_contribution.py remains a stdlib materializer; default mode refuses overwrites. The r6 revision driver explicitly enables replacement only after immutable snapshot checks. Direct requirements are exact; complete transitive/native locks and redistribution reviews remain pending. Local venv/cache contents are never delivery artifacts. Current source/test manifests are explicit files, not directory scans.
"""
        (HERE / "README.md").write_text(README, encoding="utf-8", newline="\n")
        extras = source_and_snapshot_gate["snapshot_paths"] + [
            GROUP + "/resolve_blockers_r6.py", "tests/test_expansion501_geology.py",
            GROUP + "/resolution-r6/source-evidence.json",
            GROUP + "/resolution-r6/shared-bridge-requirements.json",
            GROUP + "/resolution-r6/oxygen-convention.json", ideal_path]
        build(allow_replacement=True, extra_files=extras)
        return {"authored": 26, "blocked": 5, "skills": 9, "upstream_tests_executed": 0}

    @task(depends_on=[materialize], when=lambda materialize: materialize["authored"] == 26)
    def local_reference_gate(materialize):
        test_path = ROOT / "tests/test_expansion501_geology.py"
        module_spec = importlib.util.spec_from_file_location("geology_r6_local_reference_tests", test_path)
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_spec.name] = module
        module_spec.loader.exec_module(module)
        stream = io.StringIO()
        suite = unittest.TestLoader().loadTestsFromTestCase(module.GeologyLocalReferences)
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        (RUN / "reference-tests.log").write_text(stream.getvalue(), encoding="utf-8", newline="\n")
        report = {"scope": "stdlib_reference_and_source_only_not_upstream_acceptance",
                  "executed": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                  "passed": result.testsRun - len(result.failures) - len(result.errors),
                  "scientific_upstream_executed": 0, "main_runtime_v2_executed": 0,
                  "model_workflow": "not_run", "deployment": "not_deployed"}
        save(RUN / "reference-report.json", report)
        if not result.wasSuccessful():
            raise RuntimeError("New local reference/source failure preserved; do not silently fix or retry.")
        return report

    @task(depends_on=[materialize, local_reference_gate],
          when=lambda materialize, local_reference_gate: local_reference_gate["passed"] == 7)
    def delivery_gate(materialize, local_reference_gate):
        manifest_path = HERE / "delivery-files.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        extra = [RUN / "reference-tests.log", RUN / "reference-report.json",
                 RUN / "flow.jsonl", RESOLUTION / "source-milestone.json"]
        manifest["files"] = sorted(set(manifest["files"] + [p.relative_to(ROOT).as_posix() for p in extra]))
        save(manifest_path, manifest)
        milestone = {**materialize, "source_status": "source_revised_unverified",
            "formal_eligible": False, "main_runtime_dispatch": "pending_parent_v2",
            "local_reference_checks": local_reference_gate,
            "historical_failures": "preserved_not_reclassified", "remote_operations": "not_attempted",
            "paths": manifest["files"],
            "source_sha256": {p: sha(ROOT / p) for p in (
                "geological_agent/geology/expansion501_geology.py", "tests/test_expansion501_geology.py",
                GROUP + "/contribution-spec.json", GROUP + "/catalog-additions.json")}}
        save(RESOLUTION / "source-milestone.json", milestone)
        return {**materialize, "local_reference_checks_passed": 7, "main_runtime_v2_executed": 0}

    flow = Flow(delivery_gate, max_workers=1, fail_fast=True, journal_path=str(RUN / "flow.jsonl"))
    flow.run()
    print(json.dumps(flow.value(delivery_gate), ensure_ascii=False))

if __name__ == "__main__":
    main()


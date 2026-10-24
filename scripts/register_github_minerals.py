"""One-shot additive catalog migration for the reviewed GitHub minerals intake."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
ASSET = "assets/github-minerals"
DELIVERY = "catalog/source_delivery/github-minerals"
UPSTREAM = {
    "spectral": ("0.25", "spectralpython/spectral", "bd91dc47377028683ef5c97bc7c1cc2dff14012c"),
    "pyrolite": ("0.3.7", "morganjwilliams/pyrolite", "ab651b448ecd2ce1bc22d752b80a977a1f4dd1ca"),
    "mplstereonet": ("0.6.3", "joferkington/mplstereonet", "fb7ef203c57baf8a583c5027c1198df2e6c10819"),
}
PINS = ["numpy==2.1.3", "scipy==1.15.3", "pandas==2.3.0", "matplotlib==3.10.7", "rasterio==1.4.3",
        "spectral==0.25", "pyrolite==0.3.7", "mplstereonet==0.6.3", "periodictable==2.1.0",
        "mpltern==1.0.5", "sympy==1.14.0", "mpmath==1.3.0"]


def obj(props, required=None):
    return {"type": "object", "properties": props, "required": list(props) if required is None else required, "additionalProperties": False}


def number(description, **kwargs):
    return {"type": "number", "description": description, **kwargs}


def string(description, **kwargs):
    return {"type": "string", "description": description, **kwargs}


def array(description, items=None, **kwargs):
    return {"type": "array", "description": description, "items": items or {"type": "number"}, **kwargs}


def matrix(description):
    return array(description, {"type": "array", "items": {"type": "number"}, "minItems": 1, "maxItems": 2048}, minItems=1, maxItems=128)


def labels(description):
    return array(description, {"type": "string"}, minItems=1, maxItems=128)


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def records():
    data = {"data_path": string("Task-relative UTF-8 JSON file using this tool's documented scientific file schema.", minLength=1, maxLength=512)}
    angle = number("Largest accepted reference-match angle in degrees; larger values are unmatched.", minimum=0, maximum=90, default=10)
    source = string("Caller-declared reference source; this field is not independent authentication of that source.")
    common_s = {"sample_ids": labels("Input sample identifiers, in original order.")}
    common_r = {"reference_labels": labels("Reference spectra labels in library order."), "reference_source": source}
    common_c = {**common_s, "components": labels("Chemical columns in their declared order.")}
    return [
      ("GeoSpectralAngleMatch", "spectral_angle_match", "spectral", "Match measured spectra to a supplied mineral reference library by Spectral Python spectral angle; export angle table and heatmap.",
       obj({**data, "max_angle_degrees": angle}, ["data_path"]),
       {**common_s, **common_r, "angles_degrees": matrix("Each sample's angle to every reference in degrees."), "matches": array("Nearest accepted reference or null when outside threshold.", {"type": ["string", "null"]}), "max_angle_degrees": angle},
       {"data_path": ASSET + "/spectra.json", "max_angle_degrees": 10}, ["data_path"], True),
      ("GeoSpectralContinuumRemoval", "continuum_removal", "spectral", "Remove the convex upper spectral continuum and report absorption depth, using Spectral Python; export spectral curves.",
       obj(data), {**common_s, "wavelength_nm": array("Strictly increasing wavelength centers in nanometres."), "continuum": matrix("Convex upper continuum reflectance."), "continuum_removed": matrix("Reflectance divided by convex continuum."), "deepest_wavelength_nm": array("Wavelength of maximum sampled absorption depth; first equal-depth band wins."), "maximum_depth": array("Maximum sampled 1-minus-continuum-removed reflectance.")},
       {"data_path": ASSET + "/continuum.json"}, ["data_path"], True),
      ("GeoSpectralLinearUnmix", "linear_unmix", "spectral", "Unmix measured spectra using supplied independent endmembers and Spectral Python unconstrained least squares; export coefficients and residuals.",
       obj(data), {**common_s, **common_r, "coefficients": matrix("Unconstrained spectral coefficients, potentially negative; not mass fractions or ore grade."), "rmse_reflectance": array("Per-spectrum reconstruction RMSE in reflectance units."), "sum_to_one_enforced": {"const": False, "description": "The upstream operation does not constrain coefficient sums."}, "nonnegative_enforced": {"const": False, "description": "The upstream operation does not constrain coefficient signs."}},
       {"data_path": ASSET + "/spectra.json"}, ["data_path"], True),
      ("GeoSpectralAngleMap", "spectral_angle_map", "spectral", "Map supplied spectral references onto a calibrated GeoTIFF with Spectral Python; preserve CRS, quality exclusions, class and angle GeoTIFFs, statistics and PNG/SVG previews.",
       obj({"raster_path": string("Task-relative single-file GeoTIFF; explicit CRS and declared ordered bands.", maxLength=512), "library_path": string("Task-relative JSON reference library with wavelengths, spectra, labels and source.", maxLength=512), "quality_mask_path": string("Optional aligned GeoTIFF with 1=valid, 0=excluded, NoData excluded; no reprojection.", maxLength=512), "raster_wavelength_nm": array("One explicit wavelength in nm for every raster band; increasing and matching the reference library.", number("Wavelength center in nm.", minimum=100, maximum=30000), minItems=3, maxItems=2048), "reflectance_scale": number("Multiply raw raster values by this explicit scale.", exclusiveMinimum=0, maximum=100, default=1), "reflectance_offset": number("Add this offset after scaling raw values.", minimum=-100, maximum=100, default=0), "max_angle_degrees": angle}, ["raster_path", "library_path", "raster_wavelength_nm", "reflectance_scale", "reflectance_offset"]),
       {**common_r, "width": {"type": "integer", "minimum": 1, "description": "Original raster column count."}, "height": {"type": "integer", "minimum": 1, "description": "Original raster row count."}, "crs": string("Preserved input CRS."), "affine": array("Preserved affine coefficients a,b,c,d,e,f.", minItems=6, maxItems=6), "matched_pixels": array("Per-reference matched pixel counts.", {"type": "integer", "minimum": 0}), "valid_pixels": {"type": "integer", "minimum": 0, "description": "Finite unmasked pixel count before angle threshold."}, "excluded_pixels": {"type": "integer", "minimum": 0, "description": "Quality mask and NoData excluded pixels."}, "unmatched_pixels": {"type": "integer", "minimum": 0, "description": "Valid pixels exceeding the requested angle threshold."}},
       {"raster_path": ASSET + "/synthetic-spectra.tif", "library_path": ASSET + "/library.json", "quality_mask_path": ASSET + "/synthetic-mask.tif", "raster_wavelength_nm": [1000, 1500, 2000], "reflectance_scale": 1, "reflectance_offset": 0, "max_angle_degrees": 10}, ["raster_path", "library_path", "quality_mask_path"], True),
      ("GeoGeochemCLR", "geochem_clr", "pyrolite", "Transform strictly positive same-unit geological compositions with pyrolite centered log ratios; preserve components and export a heatmap.",
       obj(data), {**common_c, "clr": matrix("Natural-log centered log ratios; each row sums to approximately zero."), "input_unit": string("Shared input concentration unit: ppm or wt_percent.")},
       {"data_path": ASSET + "/clr.json"}, ["data_path"], True),
      ("GeoGeochemOxideMoles", "oxide_moles", "pyrolite", "Convert supported whole-rock oxide wt_percent to mol/100g and normalized oxide mol percent with pyrolite; no inferred iron redox split.",
       obj(data), {**common_c, "moles_per_100g": matrix("Moles of each supplied oxide per 100 g original sample."), "mol_percent": matrix("Molar percentages normalized among supplied oxides."), "input_totals_wt_percent": array("Unmodified input oxide totals, in wt percent.")},
       {"data_path": ASSET + "/oxides.json"}, ["data_path"], True),
      ("GeoGeochemREEPattern", "ree_pattern", "pyrolite", "Normalize rare-earth element ppm to an explicitly supplied reference composition using pyrolite; export log-scale REE patterns and Eu anomaly where Sm, Eu, Gd are present.",
       obj(data), {**common_c, "normalized": matrix("Concentration divided by aligned reference concentration."), "eu_anomaly": {"type": ["array", "null"], "items": {"type": "number"}, "description": "Eu_N/sqrt(Sm_N*Gd_N); null when one of those components is absent."}, "reference_source": source},
       {"data_path": ASSET + "/ree.json"}, ["data_path"], True),
      ("GeoStereonetAnalysis", "stereonet_analysis", "mplstereonet", "Plot lower-hemisphere equal-area structural planes and poles with mplstereonet; fit the dominant plane only when eigenvalues define a unique pole.",
       obj(data), {"measurement_count": {"type": "integer", "minimum": 3, "maximum": 500, "description": "Number of right-hand-rule strike/dip observations."}, "fit_plane": {"type": ["object", "null"], "properties": {"strike_degrees": number("Fitted right-hand-rule strike in degrees.", minimum=0, exclusiveMaximum=360), "dip_degrees": number("Fitted dip in degrees.", minimum=0, maximum=90)}, "required": ["strike_degrees", "dip_degrees"], "additionalProperties": False, "description": "Dominant plane or null for indistinguishable leading eigenvalues."}, "eigenvalues": array("Descending eigenvalues of bidirectional pole covariance.", minItems=3, maxItems=3), "eigenvector_plunges_degrees": array("Descending eigenvector plunges in degrees.", minItems=3, maxItems=3), "eigenvector_bearings_degrees": array("Descending eigenvector bearings in degrees.", minItems=3, maxItems=3)},
       {"data_path": ASSET + "/structures.json"}, ["data_path"], True),
      ("GeoStructuralPlaneIntersection", "plane_intersection", "mplstereonet", "Compute the line of intersection of two right-hand-rule geological planes using mplstereonet; reject parallel planes and return null bearing for vertical lines.",
       obj({"strike1_degrees": number("First plane strike, right-hand-rule degrees clockwise from north.", minimum=0, exclusiveMaximum=360), "dip1_degrees": number("First plane dip in degrees.", minimum=0, maximum=90), "strike2_degrees": number("Second plane strike, right-hand-rule degrees clockwise from north.", minimum=0, exclusiveMaximum=360), "dip2_degrees": number("Second plane dip in degrees.", minimum=0, maximum=90)}),
       {"plunge_degrees": number("Intersection plunge downward in degrees.", minimum=0, maximum=90), "bearing_degrees": {"type": ["number", "null"], "minimum": 0, "exclusiveMaximum": 360, "description": "Clockwise bearing in degrees; null for a vertical intersection."}},
       {"strike1_degrees": 0, "dip1_degrees": 90, "strike2_degrees": 90, "dip2_degrees": 90}, [], False),
    ]


def raster_fixtures():
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    root = ROOT / ASSET
    profile = dict(driver="GTiff", height=2, width=2, crs="EPSG:32652", transform=from_origin(500000, 4500000, 10, 10))
    with rasterio.open(root / "synthetic-spectra.tif", "w", **profile, count=3, dtype="float32", nodata=-9999) as out:
        out.write(np.asarray([[[1, 0], [.25, -9999]], [[0, 1], [.75, -9999]], [[0, 0], [0, -9999]]], dtype="float32"))
    with rasterio.open(root / "synthetic-mask.tif", "w", **profile, count=1, dtype="uint8", nodata=255) as out:
        out.write(np.asarray([[1, 1], [0, 1]], dtype="uint8"), 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--downloads", type=Path)
    parser.add_argument("--raster-fixtures-only", action="store_true")
    args = parser.parse_args()
    if args.raster_fixtures_only:
        raster_fixtures()
        return
    registry_path = ROOT / "catalog/registry.json"
    catalog = json.loads(registry_path.read_text(encoding="utf-8"))
    old_tools, old_skills = copy.deepcopy(catalog["tools"]), copy.deepcopy(catalog["skills"])
    examples_path = ROOT / "catalog/source_delivery/examples.json"
    examples = json.loads(examples_path.read_text(encoding="utf-8"))
    old_examples = copy.deepcopy(examples)
    rows = records()
    if len(old_tools) != 220 or len(old_skills) != 47 or any(r[0] in {t["id"] for t in old_tools} for r in rows):
        raise RuntimeError("Expected the unchanged 220-tool / 47-Skill starting catalog; refusing duplicate migration")
    tools = []
    for name, function, package, desc, schema, result, example, paths, generates in rows:
        version, repo, commit = UPSTREAM[package]
        result = obj({**result, "units": {"type": "object", "additionalProperties": {"type": "string"}, "description": "Explicit scientific units."}, "artifacts": array("Generated local files returned through ArtifactRef at runtime.", {"type": "string"}), "provenance": {"type": "object", "description": "Pinned upstream, installed versions, input hashes, implementation hash and per-output SHA-256."}})
        entry = {"callable": "geological_agent.geology.github_minerals:" + function, "argument_parameter": "args", "bound_arguments": {}}
        if generates:
            entry["output_directory_parameter"] = "output_dir"
        limitation = ["One bounded operation; no arbitrary code or runtime downloads.", "Reference labels and sources are caller declarations. Similarity or coefficients do not prove mineral presence, grade or reserves.", "Synthetic acceptance fixtures are not observations; real-data and model-workflow acceptance is separate."]
        meta = {"asset_version": "1.0.0", "provider": repo.split('/')[0], "license": "MIT", "upstream_license": "MIT", "source_url": "https://github.com/" + repo, "source_commit": commit, "official_protocol_version": None, "official_protocol": {"applicability": "not_applicable", "name": None, "version": None}, "metadata_profile": "scientific", "runtime": {"python": ">=3.11", "dependency_lock": "requirements-github-minerals.txt", "environment_version": "github-minerals-20261024"}, "lifecycle": {"registration": "registered", "contract_validation": "not_run", "unit_validation": "not_run", "workflow_validation": "not_run", "platform_validation": "not_run", "release_status": "draft"}, "pending_fields": ["receiving_lab_approval", "adapter_license"], "platform_validation": "not_run"}
        definition = {"type": "function", "function": {"name": name, "description": desc, "parameters": schema}}
        spec = {"id": name, "name": name, "description": desc, "input_schema": schema, "output_schema": result, "constraints": {"finite_numbers_only": True, "no_implicit_reprojection": True, "no_automatic_dependency_install": True, "max_file_bytes": 67108864, "max_json_bytes": 4000000}, "metadata": {"category": "github_minerals", "input_format": "JSON args plus declared scientific JSON/GeoTIFF files", "output_format": "Schema-validated JSON and artifact files", "source": "https://github.com/" + repo, "upstream": {"package": package, "version": version, "license": "MIT", "url": "https://github.com/" + repo, "requirements": PINS}, "scientific_contract": {"implementation_kind": "upstream_library", "review_status": "acceptance_pending", "formal_eligible": False}}, "category": "github_minerals", "function": definition, "function_definition": copy.deepcopy(definition), "version": "1.0.0", "example_arguments": example, "limitations": limitation, "source_interface": {"status": "source_revised_unverified", "kind": "github_minerals", "path_fields": paths, "network_required": False, "pure": False, "validation": "acceptance_pending", "entrypoint": entry}, "error_contract": {"direct_exception": "ScientificToolError", "fields": ["code", "message", "retryable"], "codes": ["invalid_arguments", "missing_input", "missing_dependency", "incompatible_dependency", "resource_limit", "invalid_input", "invalid_result", "invalid_path", "empty_input", "unsupported_conditions", "output_conflict", "upstream_failure"], "retry_policy": "Correct inputs or installation before retrying; deterministic failures are not blindly retryable."}, "tags": ["geology", "minerals", package], "registration_metadata": meta}
        tools.append(spec)
        examples[name] = example
    groups = [("mineral-spectral-analysis", "Mineral spectral analysis / 矿物高光谱分析", tools[:4]), ("geochemical-composition-analysis", "Geochemical composition / 地球化学组成分析", tools[4:7]), ("structural-geology-analysis", "Structural geology / 构造地质分析", tools[7:])]
    for key, title, group in groups:
        names = [t["id"] for t in group]
        desc = " ".join(t["description"] for t in group)
        skill = {"id": key, "name": title, "description": desc, "tool_references": names, "skill_file": f"catalog/skills/{key}/SKILL.md", "metadata": {"canonical_skill_file": f"catalog/skills/{key}/SKILL.md", "validation": "not_run"}, "delivery": {"source_candidates": names, "unavailable_references": [], "availability_status": "tool_candidates_available_workflow_unverified", "workflow_validation": "not_run", "deployment_status": "not_deployed", "submission_status": "not_submitted", "model_workflow_validation": "not_run", "receiving_lab_approval": "pending"}, "registration_metadata": copy.deepcopy(group[0]["registration_metadata"])}
        skill["registration_metadata"].update(provider="GeoAgent", license=None, source_commit=None, pending_fields=["adapter_license", "receiving_lab_approval"])
        catalog["skills"].append(skill)
        front = "---\nid: " + key.replace('-', '_') + "\nname: " + json.dumps(title, ensure_ascii=False) + "\ndescription: " + json.dumps(desc) + "\nwhen_to_use: " + json.dumps(title + " using declared measurements and supplied reference data", ensure_ascii=False) + "\ntools:\n" + "".join('- ' + n + '\n' for n in names)
        front += "required_inputs:\n- Declared measured inputs with units and source\nconstraints:\n- Select only the operation required for the question.\n- Preserve units, wavelengths, quality masks, file provenance and uncertainty.\n- Never infer mineral grade or reserves from a spectral match.\nexpected_outputs:\n- Numeric evidence and downloadable PNG, SVG, CSV or GeoTIFF artifacts\n---\n"
        body = "\n# " + title + "\n\n" + "\n\n".join("## " + t["id"] + "\n" + t["description"] + "\nExample (synthetic acceptance only): `" + json.dumps(t["example_arguments"]) + "`" for t in group)
        body += "\n\n## Source interface and delivery\n\nEach named function in geological_agent.geology.github_minerals accepts args=dict or args=JSON-object-string. File-producing functions require a new or empty output_dir. Native execution authorizes workspace-relative input paths and returns ArtifactRef outputs. See catalog/source_delivery/github-minerals/FILE_SCHEMAS.md for the exact file fields, units, limits, error behavior and interpretation. Preserve output hashes and do not replace professional numerical kernels with generated code.\n\n### Current availability\n\ntool_candidates_available_workflow_unverified\n\nSource registration is available; exact test execution is recorded in acceptance receipts. Model workflow validation: not_run. Platform validation: not_run. Deployment status: not_deployed. Submission status: not_submitted. Receiving lab approval: pending.\n"
        p = ROOT / skill["skill_file"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(front + body, encoding="utf-8")
    catalog["tools"].extend(tools)
    dump(registry_path, catalog)
    dump(examples_path, examples)
    dump(ROOT / DELIVERY / "baseline-preservation.json", {"professional_tools_before": 220, "professional_tools_after": 229, "skills_before": 47, "skills_after": 50, "old_tools_canonical_sha256": canonical(old_tools), "old_skills_canonical_sha256": canonical(old_skills), "old_examples_canonical_sha256": canonical(old_examples), "added_tool_ids": [r[0] for r in rows]})
    source = args.downloads
    downloads = json.loads((source / "downloads.json").read_text())
    dump(ROOT / DELIVERY / "upstream-lock.json", {"repositories": {p: {"version": v, "repository": r, "commit": c} for p, (v, r, c) in UPSTREAM.items()}, "distributions": downloads, "scientific_dependencies": PINS})
    for package in UPSTREAM:
        licenses = [p for p in (source / "review" / package).iterdir() if p.name.rsplit('__', 1)[-1].startswith("LICENSE")]
        if len(licenses) != 1:
            raise RuntimeError("Ambiguous license source for " + package)
        dest = ROOT / DELIVERY / "licenses" / (package + ".txt")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(licenses[0], dest)
    (ROOT / "requirements-github-minerals.txt").write_text("# Reviewed CPU scientific dependencies; install before tool execution.\n" + "\n".join(PINS) + "\n", encoding="utf-8")
    spectra = {"wavelength_nm": [1000, 1500, 2000], "sample_ids": ["SYNTHETIC_A", "SYNTHETIC_B", "SYNTHETIC_MIX"], "spectra": [[1, 0, 0], [0, 1, 0], [.25, .75, 0]], "reference_wavelength_nm": [1000, 1500, 2000], "reference_labels": ["SYNTHETIC_REF_A", "SYNTHETIC_REF_B"], "reference_spectra": [[1, 0, 0], [0, 1, 0]], "reference_source": "Explicitly synthetic analytical acceptance vectors; not mineral observations"}
    fixtures = {"spectra": spectra, "library": {k: v for k, v in spectra.items() if k.startswith('reference_')}, "continuum": {"wavelength_nm": [1000, 1500, 2000], "sample_ids": ["SYNTHETIC_ABSORPTION"], "spectra": [[1, .5, 1]]}, "clr": {"sample_ids": ["SYNTHETIC_CHEM"], "components": ["Cu", "Pb", "Zn"], "values": [[1, 2, 4]], "unit": "ppm"}, "oxides": {"sample_ids": ["SYNTHETIC_OXIDES"], "components": ["SiO2", "MgO"], "values": [[60.083, 40.304]], "unit": "wt_percent"}, "ree": {"sample_ids": ["SYNTHETIC_REE"], "components": ["Sm", "Eu", "Gd"], "values": [[2, 4, 2]], "unit": "ppm", "reference_values": [1, 1, 1], "reference_source": "Synthetic unity reference, not chondrite values"}, "structures": {"measurement_ids": ["SYNTHETIC_P1", "SYNTHETIC_P2", "SYNTHETIC_P3"], "strike_degrees": [0, 0, 0], "dip_degrees": [45, 45, 45], "convention": "right_hand_rule"}}
    for name, value in fixtures.items():
        dump(ROOT / ASSET / (name + ".json"), value)
    (ROOT / ASSET / "README.md").write_text("# Synthetic acceptance inputs\n\nAll data here are explicitly synthetic numerical fixtures. They are not geological observations, public mineral spectra or mineral evidence. The map fixture uses a declared arbitrary UTM transform solely to verify preservation.\n", encoding="utf-8")
    print(json.dumps({"added_tools": len(tools), "professional_tools": len(catalog['tools']), "skills": len(catalog['skills'])}))


if __name__ == "__main__":
    main()

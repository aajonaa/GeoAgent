"""UNEXECUTED r2 CPU acceptance source for 28 geological contributions.

Two blocked operations are excluded; historical r1 failure evidence is retained.

All fixtures are SYNTHETIC. Expected values come from analytic expressions,
geometry, exact mass balance or hand-enumerated pairs, never upstream output.
Missing/incompatible dependencies fail; tests are not silently skipped.
Catalog injection is in-process only and does not alter the original registry.
"""
import copy
import hashlib
import json
import math
from pathlib import Path

import pytest

from legacy.ToolsAgent.ToolsFuns import source_contracts
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError
from geological_agent.geology import github_expansion_geology as geology

ROOT = Path(__file__).resolve().parents[1]
GROUP = ROOT / "catalog/source_delivery/github-expansion-20261025/groups/geology"
CONTRIBUTION = json.loads((GROUP / "catalog-additions.json").read_text(encoding="utf-8"))
ORACLES = json.loads((GROUP / "oracle-cases.json").read_text(encoding="utf-8"))["cases"]
CANDIDATES = json.loads((GROUP / "candidate-operations.json").read_text(encoding="utf-8"))
SPECS = {tool["id"]: tool for tool in CONTRIBUTION["tools"]}


@pytest.fixture(autouse=True)
def private_catalog(monkeypatch):
    # The normal decorator still performs real schema, dependency and provenance
    # checks. Only catalog lookup is redirected to this unregistered contribution.
    monkeypatch.setattr(source_contracts, "catalog", lambda: CONTRIBUTION)


def _arguments(tool_id, negative=False):
    case = ORACLES[tool_id]
    args = copy.deepcopy(case["negative_arguments" if negative else "arguments"])
    for field in SPECS[tool_id]["source_interface"]["path_fields"]:
        args[field] = str(ROOT / args[field])
    return args


def _entry(tool_id):
    return getattr(geology, ORACLES[tool_id]["function"])


def _finite(value):
    if isinstance(value, float):
        assert math.isfinite(value)
    elif isinstance(value, list):
        for child in value:
            _finite(child)
    elif isinstance(value, dict):
        for child in value.values():
            _finite(child)


def _close(actual, expected, atol, rtol, absolute=False):
    if isinstance(expected, list):
        assert isinstance(actual, list)
        assert len(actual) == len(expected)
        for a, e in zip(actual, expected):
            _close(a, e, atol, rtol, absolute)
    else:
        value = abs(actual) if absolute else actual
        assert value == pytest.approx(expected, abs=atol, rel=rtol)


def _input_hash(tool_id, args):
    canonical = copy.deepcopy(args)
    for field in SPECS[tool_id]["source_interface"]["path_fields"]:
        path = Path(args[field])
        data = path.read_bytes()
        canonical[field] = {"content_sha256": hashlib.sha256(data).hexdigest(),
                            "bytes": len(data), "suffix": path.suffix.lower()}
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("tool_id", list(ORACLES))
def test_independent_analytic_oracle_and_native_provenance(tool_id):
    args = _arguments(tool_id)
    result = _entry(tool_id)(json.dumps(args, allow_nan=False))
    for check in ORACLES[tool_id]["checks"]:
        actual = result
        for component in check["path"]:
            actual = actual[int(component)] if isinstance(actual, list) else actual[component]
        _close(actual, check["expected"], check["atol"], check["rtol"], check["absolute"])
    _finite(result)
    assert result["input_source"] == args["data_source"]
    assert "SYNTHETIC" in result["input_source"]
    assert result["artifacts"] == []
    assert isinstance(result["units"], dict) and result["units"]
    provenance = result["provenance"]
    assert provenance["tool"] == tool_id
    assert provenance["network_required"] is False
    assert provenance["output_sha256"] == {}
    assert provenance["input_sha256"] == _input_hash(tool_id, args)
    assert provenance["reviewed_archive_commit"] == SPECS[tool_id]["registration_metadata"]["source_commit"]
    for field in ("input_sha256", "implementation_sha256", "contract_sha256"):
        assert len(provenance[field]) == 64
        int(provenance[field], 16)
    assert provenance["implementation_sha256"] == hashlib.sha256(Path(geology.__file__).read_bytes()).hexdigest()
    expected_versions = dict(r.split("==", 1) for r in SPECS[tool_id]["metadata"]["upstream"]["requirements"])
    assert provenance["installed_versions"] == expected_versions
    # Independent domain checks in addition to stored positive numeric constants.
    if tool_id == "GeoAPSGFisherDirectionalConfidence":
        kappa = result["precision"]
        assert kappa > 0
        assert 1/math.tanh(kappa)-1/kappa == pytest.approx(math.sqrt(3)/2, abs=1e-7)
    if tool_id == "GeoAPSGFaultKinematicAxes":
        p, t = result["p_axes_ned"][0], result["t_axes_ned"][0]
        assert sum(a*b for a,b in zip(p,t)) == pytest.approx(0, abs=1e-9)
    if tool_id == "GeoLasioLogAudit":
        assert result["curves"][0]["values"][1] is None
    if tool_id == "GeoSKGstatSpaceTimeVariogram":
        for i in range(3):
            for j in range(3):
                assert result["semivariance"][i][j] == pytest.approx((4*(i+1)**2+9*(j+1)**2)/2)
                assert result["pair_counts"][i][j] == 2*(3-i)*(3-j)


@pytest.mark.parametrize("tool_id", list(ORACLES))
def test_operation_specific_negative_constraint(tool_id):
    with pytest.raises(ScientificToolError) as error:
        _entry(tool_id)(_arguments(tool_id, negative=True))
    assert error.value.code == ORACLES[tool_id]["negative_code"]


@pytest.mark.parametrize("tool_id", list(ORACLES))
def test_arbitrary_code_and_extra_properties_are_rejected(tool_id):
    args = _arguments(tool_id)
    args["python_function"] = "never_allowed"
    with pytest.raises(ScientificToolError) as error:
        _entry(tool_id)(args)
    assert error.value.code == "invalid_arguments"


def test_nonfinite_input_is_rejected_before_a_kernel_call():
    args = _arguments("GeoAPSGFiniteStrainEllipsoid")
    args["deformation_gradient"][0][0] = float("nan")
    with pytest.raises(ScientificToolError) as error:
        geology.finite_strain_ellipsoid(args)
    assert error.value.code == "invalid_arguments"


def test_manifest_bijection_and_exact_native_entrypoints():
    ids = list(SPECS)
    candidates = CANDIDATES["operations"]
    assert set(CANDIDATES) == {"group", "operations"}
    assert CANDIDATES["group"] == "geology"
    assert len(ids) == len(set(ids)) == len(candidates) == len(ORACLES) == 28
    assert {r["tool_id"] for r in candidates} == set(ids) == set(ORACLES)
    expected_keys = {"tool_id", "capability_key", "upstream_callable", "scientific_task", "distinct_from_existing", "numeric_oracle", "status"}
    for row in candidates:
        assert set(row) == expected_keys
        assert row["status"] == "source_authored_unverified"
        assert row["distinct_from_existing"] and row["numeric_oracle"]
    for tool_id, spec in SPECS.items():
        assert spec["source_interface"]["kind"] == "github_expansion_geology"
        assert spec["source_interface"]["entrypoint"]["callable"] == "geological_agent.geology.github_expansion_geology:" + ORACLES[tool_id]["function"]
        assert callable(_entry(tool_id))
        assert spec["input_schema"]["additionalProperties"] is False
        assert spec["output_schema"]["additionalProperties"] is False
        assert "output_directory_parameter" not in spec["source_interface"]["entrypoint"]
        source_contracts.validate_registration_metadata(spec)
    assert len(CONTRIBUTION["skills"]) == 5
    assert [len(skill["tool_references"]) for skill in CONTRIBUTION["skills"]] == [5, 6, 5, 6, 6]
    referenced = [name for skill in CONTRIBUTION["skills"] for name in skill["tool_references"]]
    assert len(referenced) == len(set(referenced)) == 28
    assert set(referenced) == set(ids)


@pytest.mark.parametrize("entry", [geology.bingham_axial_confidence, geology.cipw_normative_mineralogy])
def test_blocked_operations_fail_closed_without_catalog_or_kernel(entry):
    with pytest.raises(ScientificToolError) as error:
        entry({})
    assert error.value.code == "unsupported_conditions"


def test_blocked_manifest_and_apsg_environment_separation():
    blocked = json.loads((GROUP / "blocked-operations.json").read_text(encoding="utf-8"))
    ids = {row["tool_id"] for row in blocked["operations"]}
    assert ids == {"GeoAPSGBinghamAxialConfidence", "GeoPyroliteCIPWNorm"}
    assert ids.isdisjoint(SPECS)
    assert ids.isdisjoint(ORACLES)
    examples = json.loads((GROUP / "examples-additions.json").read_text(encoding="utf-8"))
    assert set(examples) == set(SPECS)
    apsg_specs = [s for s in SPECS.values() if s["metadata"]["upstream"]["package"] == "apsg"]
    assert len(apsg_specs) == 11
    for spec in apsg_specs:
        requirements = spec["metadata"]["upstream"]["requirements"]
        assert "apsg==2.0.6" in requirements
        assert "SQLAlchemy==1.4.54" in requirements
        assert not any("44f9dde" in pin or pin == "apsg==2.1.0" for pin in requirements)
    profile = json.loads((GROUP / "private-workers/bingham/worker-profile.json").read_text(encoding="utf-8"))
    assert profile["enabled"] is False
    assert profile["tool_allowlist"] == ["GeoAPSGBinghamAxialConfidence"]
    assert profile["source_commit"] == "44f9dde66e2e36417e09aebffd9992756705d7ab"
    assert profile["fallback_to_main_runtime"] is False

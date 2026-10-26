"""Release plumbing tests; these do not substitute for scientific acceptance."""
import importlib.util
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fixed_cpu_profile_builder", ROOT / "scripts/build_fixed_cpu_profiles.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_source_closure_includes_relative_dynamic_and_package_imports(tmp_path):
    for relative in builder.MANDATORY:
        write(tmp_path, relative, "# protocol fixture\n")
    write(tmp_path, "sample/__init__.py", "from . import initialization\n")
    write(tmp_path, "sample/initialization.py", "VALUE = 1\n")
    write(tmp_path, "sample/operation.py", "from .helper import value\nimport importlib\nimportlib.import_module('sample.dynamic')\n")
    write(tmp_path, "sample/helper.py", "value = 2\n")
    write(tmp_path, "sample/dynamic.py", "VALUE = 3\n")
    closure = builder.source_closure(tmp_path, "sample.operation")
    expected = set(builder.MANDATORY) | {
        "sample/__init__.py", "sample/initialization.py", "sample/operation.py",
        "sample/helper.py", "sample/dynamic.py",
    }
    assert set(closure) == expected
    assert all(sha == builder.digest(tmp_path / name) for name, sha in closure.items())


@pytest.mark.parametrize("relative", ["../outside.py", "/tmp/outside.py", "missing.py"])
def test_source_paths_cannot_escape_or_be_missing(tmp_path, relative):
    with pytest.raises(ValueError):
        builder.bound_file(tmp_path, relative)


def test_dependency_identity_uses_canonical_names_and_exact_pins():
    assert builder.canonical_pins(["typing_extensions==4.16.0", "# retained", ""]) == {"typing-extensions": "4.16.0"}
    with pytest.raises(ValueError, match="Duplicate"):
        builder.canonical_pins(["some.package==1.0", "some-package==1.0"])
    with pytest.raises(ValueError, match="Non-exact"):
        builder.canonical_pins(["numpy>=2"])


def test_evidence_copy_is_exact_and_never_overwrites(tmp_path):
    source = write(tmp_path, "original.txt", "original license\n")
    record = {"path": str(source), "sha256": builder.digest(source)}
    copied = builder.checked_evidence([record], tmp_path / "evidence")
    assert Path(copied[0]["published_path"]).read_bytes() == source.read_bytes()
    with pytest.raises(FileExistsError):
        builder.checked_evidence([record], tmp_path / "evidence")
    source.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="hash changed"):
        builder.checked_evidence([record], tmp_path / "other")


def test_isolation_proof_schema_remains_closed_and_cpu_only():
    schema = builder.isolation_schema("a-profile", {"numpy": "2.1.3"}, {})
    Draft202012Validator.check_schema(schema)
    proof = {
        "profile_id": "a-profile", "profile_sha256": "a" * 64, "worker_sha256": "b" * 64,
        "python_version": "3.12.14", "python_sha256": "c" * 64,
        "build_receipt_sha256": "d" * 64, "installed_versions": {"numpy": "2.1.3"},
        "spec_sha256": "e" * 64, "protocol": "geoagent-isolated-cpu-v2", "native_projects": {},
        "gpu_requested": False, "runtime_install": False, "os_sandbox": False,
        "evidence_directory": "/private/job",
    }
    validator = Draft202012Validator(schema)
    validator.validate(proof)
    assert not validator.is_valid({**proof, "gpu_requested": True})
    assert not validator.is_valid({**proof, "unrecorded": True})
    assert not validator.is_valid({**proof, "installed_versions": {"numpy": "2.0.0"}})
    assert not validator.is_valid({key: value for key, value in proof.items() if key != "spec_sha256"})

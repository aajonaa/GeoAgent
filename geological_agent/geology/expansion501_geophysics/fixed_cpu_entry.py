"""Fixed existing-v1 JSON CPU entry. Source only until the parent profile is ready.

No user-selected executable, callable, filesystem path, shell, installation,
GPU, or alternate transport is supported. No adjacent build receipt is fabricated.
"""
import hashlib
from importlib import metadata
import json
import math
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
RECEIPT = Path(__file__).with_name("cpu-build-receipt.json")
IDS = ("GeoSeismicMarchenkoRedatuming", "GeoSeismicTraveltimeTomography")
COMMON = {"numpy": "2.1.3", "scipy": "1.15.3", "jsonschema": "4.25.1"}
PINS = {
    IDS[0]: dict(COMMON, pylops="2.6.0"),
    IDS[1]: dict(COMMON, pygimli="1.6.0", pgcore="1.6.0", scooby="0.11.2",
                 setuptools="80.9.0", matplotlib="3.10.7"),
}
COMMITS = {
    IDS[0]: "97992be198c66a489c945c3feff31f6ed7d9117b",
    IDS[1]: "d598724a75cf0abbefcb354b8cd71bb48c232fc6",
}
PGCORE_FILES = {
    "pgcore/libs/_pygimli_.so": "d2711cd14bac81613adff5e002b3ec09a495856aee2d28fcb2f2e5fa03774321",
    "pgcore.libs/libamd-a26d1aab.so.2.4.1": "a2024c38166cf4851fba82cb72198de3c07264e871dae9a9cc146989164937ee",
    "pgcore.libs/libboost_python312-mt-x64-d4403d08.so.1.86.0": "31ae08abb32dc9c6e1f823c2338a11c102728f39b5dc84a87957f6048c37ee0c",
    "pgcore.libs/libcamd-28bb7d13.so.2.4.1": "29030fe997c5b1db1a7904078eb36c9c8f554f844aaa170a93940433573ae139",
    "pgcore.libs/libccolamd-b4f1d742.so.2.9.1": "415f4654c39fb576a6487f9ffb1a15da440e9d1e2943151a600eaa5b24a20ac2",
    "pgcore.libs/libcholmod-8f6cf142.so.3.0.6": "92d0ed7f4366f61e88bbb0e1e8cc4fcc2f8c412f0073f2b4d22cba424ea55bb2",
    "pgcore.libs/libcolamd-dc193ab4.so.2.9.1": "4fff914a2f7e7f54cb9e998cb5f2f42ded19c59f7adf00b779581a2da3ecbd86",
    "pgcore.libs/libgfortran-83c28eba.so.5.0.0": "e554879fee7eda80055b6ca1407a54d00050874f830cc86b2bf3f50df5c7bb2b",
    "pgcore.libs/libgimli-5caae48d.so": "f7546d4eb0f520c3eb0883935680b18e1912e39c8de9ab47baf2a7d419222a10",
    "pgcore.libs/libgomp-e985bcbb.so.1.0.0": "a43904e4fa297301d4640dc1bb3c8a3480b406f99e498eba9b1914b68aab604a",
    "pgcore.libs/libopenblas-r0-11edc3fa.3.15.so": "b6d41fcb596929a866df6e907627678e61f24c94c35ed604e687a08728ad59b8",
    "pgcore.libs/libquadmath-2284e583.so.0.0.0": "a9307bbaa353623fa014e8b682d50c4629f5e5c7d61daa9a8652f7d165cd421a",
    "pgcore.libs/libsatlas-6c1f674f.so.3.10": "4059b63273d0ea4519a8ee6e4c9c80bead9605e83dfaf661561a45a0a4300c97",
    "pgcore.libs/libsuitesparseconfig-e4e8c4aa.so.4.4.4": "769b0c914367995078d0d3652316a2f1660c8778eae7ab1539f3016ded16d9bf",
    "pgcore.libs/libumfpack-2e055419.so.5.7.1": "924721f9fe5556a00093f8f13461be6176dff82223c918efa634ad13d2d989eb"
}


class WorkerFailure(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(262144), b""):
            h.update(chunk)
    return h.hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def decode_request(raw):
    if len(raw) > 262144:
        raise WorkerFailure("resource_limit", "Input exceeds the existing bridge's 256 KiB limit")
    def constant(value):
        raise ValueError("Nonfinite JSON constant")
    args = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                      parse_constant=constant)
    if not isinstance(args, dict):
        raise ValueError("Arguments must be an object")
    def finite(value, depth=0):
        if depth > 12:
            raise ValueError("Arguments are too deeply nested")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Nonfinite numeric value")
        if isinstance(value, dict):
            for child in value.values():
                finite(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                finite(child, depth + 1)
    finite(args)
    return args


def prepare_profile(name):
    if sys.platform != "linux" or sys.version_info[:3] != (3, 12, 14):
        raise WorkerFailure("incompatible_dependency", "This reviewed private entry requires Linux CPython 3.12.14")
    if sys.prefix == sys.base_prefix:
        raise WorkerFailure("integrity_error", "A separate private virtual environment is mandatory")
    if not RECEIPT.is_file() or RECEIPT.is_symlink():
        raise WorkerFailure("missing_dependency", "The administrator-reviewed private build receipt is not prepared")
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if receipt.get("profile_id") != "expansion501-geophysics-pending-two-r6":
        raise WorkerFailure("integrity_error", "Wrong fixed CPU profile")
    profile_root = Path(receipt["profile_root"])
    if not profile_root.is_absolute() or profile_root.is_symlink():
        raise WorkerFailure("integrity_error", "The fixed profile root is invalid")
    profile_root = profile_root.resolve(strict=True)
    if not ROOT.is_relative_to(profile_root) or not Path(sys.prefix).resolve().is_relative_to(profile_root):
        raise WorkerFailure("integrity_error", "Source and venv must both belong to the fixed private profile")
    profile = receipt["operations"][name]
    if profile.get("requirements") != PINS[name] or profile.get("source_commit") != COMMITS[name]:
        raise WorkerFailure("integrity_error", "Receipt does not match reviewed source and dependency pins")
    for gate in ("source_wheel_correspondence", "runtime_abi", "bundled_license_review"):
        if profile.get("gates", {}).get(gate) != "passed":
            raise WorkerFailure("missing_dependency", "Private build gate still pending: " + gate)
    if receipt.get("python_sha256") != digest(sys.executable):
        raise WorkerFailure("integrity_error", "Interpreter identity mismatch")
    expected = receipt["files_sha256"]
    required_files = [Path(__file__), ROOT / "geological_agent/geology/expansion501_geophysics.py",
                      ROOT / "geological_agent/geology/collection_contracts.py",
                      ROOT / "catalog/registry.json"]
    for path in required_files:
        if path.relative_to(profile_root).as_posix() not in expected:
            raise WorkerFailure("integrity_error", "Receipt lacks a required source/catalog binding")
    for relative, sha in expected.items():
        path = profile_root / relative
        if Path(relative).is_absolute() or path.is_symlink() or not path.resolve().is_relative_to(profile_root):
            raise WorkerFailure("integrity_error", "Build file escapes the fixed profile")
        if not path.is_file() or digest(path) != sha:
            raise WorkerFailure("integrity_error", "Private build content hash mismatch")
    for package, pin in PINS[name].items():
        if metadata.version(package) != pin:
            raise WorkerFailure("missing_dependency", "Private dependency differs from reviewed pin: " + package)
        distribution = metadata.distribution(package)
        if not Path(distribution.locate_file("")).resolve().is_relative_to(Path(sys.prefix).resolve()):
            raise WorkerFailure("integrity_error", "A scientific dependency was inherited from outside the private venv")
    binary = profile_root / profile["binary_relative_path"]
    if binary.is_symlink() or not binary.resolve().is_relative_to(profile_root) or not binary.is_file():
        raise WorkerFailure("integrity_error", "Fixed kernel identity file is invalid")
    if binary.relative_to(profile_root).as_posix() not in expected:
        raise WorkerFailure("integrity_error", "Kernel identity is not included in the reviewed hash set")
    if name == IDS[1]:
        distribution = metadata.distribution("pgcore")
        for relative, sha in PGCORE_FILES.items():
            path = Path(distribution.locate_file(relative))
            if not path.resolve().is_relative_to(Path(sys.prefix).resolve()) or digest(path) != sha:
                raise WorkerFailure("integrity_error", "Pinned pgcore native library content differs")
        if digest(binary) != PGCORE_FILES["pgcore/libs/_pygimli_.so"]:
            raise WorkerFailure("integrity_error", "Tomography kernel identity is not the reviewed CPython extension")
    return profile_root, {
        "binary_sha256": digest(binary),
        "build_receipt_sha256": digest(RECEIPT),
        "private_catalog_sha256": digest(ROOT / "catalog/registry.json"),
        "private_python_sha256": digest(sys.executable),
        "private_python_version": ".".join(map(str, sys.version_info[:3])),
    }


def invoke_fixed(name, args):
    # Literal imports and branches only. The actual decorator performs dependency,
    # input/output schema and provenance checks inside this interpreter.
    from geological_agent.geology.expansion501_geophysics import (
        GeoSeismicMarchenkoRedatuming, GeoSeismicTraveltimeTomography)
    if name == "GeoSeismicMarchenkoRedatuming":
        return GeoSeismicMarchenkoRedatuming(args)
    if name == "GeoSeismicTraveltimeTomography":
        return GeoSeismicTraveltimeTomography(args)
    raise WorkerFailure("invalid_arguments", "Unknown fixed CPU operation")


def main():
    name = sys.argv[1] if len(sys.argv) == 2 else ""
    wire = os.dup(1)
    # Native C++ stdout must not corrupt the JSON wire.
    os.dup2(2, 1)
    exit_code = 1
    try:
        if name not in IDS:
            raise WorkerFailure("invalid_arguments", "Only the two reviewed operation IDs are allowed")
        args = decode_request(sys.stdin.buffer.read(262145))
        for key in ("CUDA_VISIBLE_DEVICES", "HIP_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES"):
            os.environ[key] = ""
        os.environ["NVIDIA_VISIBLE_DEVICES"] = "none"
        os.environ["ONEAPI_DEVICE_SELECTOR"] = "opencl:cpu"
        for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                    "NUMEXPR_NUM_THREADS", "NUMBA_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
            os.environ[key] = "2"
        os.environ.update(LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false",
                          GEOTOOL_LANGSMITH_ENABLED="0", PYTHONDONTWRITEBYTECODE="1",
                          PYTHONNOUSERSITE="1", MPLBACKEND="Agg", PROJ_NETWORK="OFF")
        profile_root, proof = prepare_profile(name)
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (120, 121))
        resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))
        sys.path.insert(0, str(ROOT))
        cache = profile_root / "runtime-private-cache"
        cache.mkdir(mode=0o700, exist_ok=True)
        if cache.is_symlink() or not cache.resolve().is_relative_to(profile_root):
            raise WorkerFailure("integrity_error", "Private cache root is invalid")
        with tempfile.TemporaryDirectory(prefix="geophysics-", dir=cache) as temporary:
            for key, folder in (("HOME", "home"), ("XDG_CACHE_HOME", "xdg"),
                                ("MPLCONFIGDIR", "mpl"), ("NUMBA_CACHE_DIR", "numba"),
                                ("TMPDIR", "tmp"), ("TEMP", "temp"), ("TMP", "tmp2")):
                path = Path(temporary) / folder
                path.mkdir(mode=0o700)
                os.environ[key] = str(path)
            previous = Path.cwd()
            try:
                os.chdir(temporary)
                result = invoke_fixed(name, args)
            finally:
                os.chdir(previous)
        if result.get("artifacts") != [] or result["provenance"].get("output_sha256") != {}:
            raise WorkerFailure("invalid_result", "These fixed kernels may only return bounded JSON")
        result["provenance"].update(proof)
        response = {"status": "ok", "tool": name, "data": result}
        exit_code = 0
    except Exception as exc:
        code = getattr(exc, "code", None)
        allowed = {"invalid_arguments", "invalid_result", "resource_limit",
                   "missing_dependency", "incompatible_dependency", "integrity_error",
                   "upstream_failure", "invalid_input", "invalid_path", "missing_input"}
        if code not in allowed:
            code = "missing_dependency" if isinstance(exc, metadata.PackageNotFoundError) else "upstream_failure"
        response = {"status": "error", "tool": name,
                    "error": {"code": code, "message": str(exc)[:4096], "retryable": False}}
    encoded = json.dumps(response, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 2097152:
        encoded = json.dumps({"status": "error", "tool": name, "error": {
            "code": "resource_limit", "message": "CPU response exceeded 2 MiB", "retryable": False}}).encode()
        exit_code = 1
    offset = 0
    while offset < len(encoded):
        offset += os.write(wire, encoded[offset:])
    os.close(wire)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())


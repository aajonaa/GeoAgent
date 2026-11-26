"""Common native source contracts, not an LLM/text action protocol."""
from copy import deepcopy
from functools import wraps
import hashlib
from importlib import metadata
import json
from pathlib import Path
from threading import RLock

from jsonschema import Draft202012Validator, ValidationError
from legacy.ToolsAgent.ToolsFuns.source_contracts import arguments, definition, finite
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError

MAX_ARGUMENT_BYTES = 4_000_000
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_INPUT_BYTES = 128 * 1024 * 1024
MAX_OUTPUT_BYTES = 128 * 1024 * 1024
MAX_OUTPUT_FILES = 64
_FILE_OPERATION_LOCK = RLock()


def reject(message, code="invalid_arguments"):
    raise ScientificToolError(code, message)


def _digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(262144), b""):
            value.update(block)
    return value.hexdigest()


def _canonical_inputs(args, path_fields):
    canonical = deepcopy(args)
    total = 0
    for field in path_fields:
        if field not in args:
            continue
        values = args[field] if isinstance(args[field], list) else [args[field]]
        descriptors = []
        for value in values:
            path = Path(value)
            if path.is_symlink():
                reject("Input files cannot be symbolic links", "invalid_path")
            if not path.is_file():
                reject("A declared input file is missing", "missing_input")
            size = path.stat().st_size
            total += size
            if size > MAX_FILE_BYTES or total > MAX_TOTAL_INPUT_BYTES:
                reject("Declared inputs exceed the source file budget", "resource_limit")
            descriptors.append({"content_sha256": _digest(path), "bytes": size, "suffix": path.suffix.lower()})
        canonical[field] = descriptors if isinstance(args[field], list) else descriptors[0]
    return canonical


def _dependencies(spec):
    upstream = spec["metadata"]["upstream"]
    package, version = upstream.get("package"), upstream.get("version")
    installed = {}
    if upstream.get("source_mode", "package_release") == "package_release":
        if not package or not version:
            reject("An operation dependency profile is incomplete", "missing_dependency")
        actual = metadata.version(package)
        if actual != version:
            reject("Install the reviewed dependency release for " + package, "missing_dependency")
        installed[package] = actual
    for requirement in upstream.get("requirements", []):
        if "==" not in requirement or " " in requirement or "@" in requirement:
            continue
        dependency, expected = requirement.split("==", 1)
        actual = metadata.version(dependency)
        installed[dependency] = actual
        if actual != expected:
            reject("Install the reviewed dependency release for " + dependency, "missing_dependency")
    return installed


def _output_directory(value):
    if value is None:
        reject("This operation needs an explicit new or empty output directory")
    root = Path(value)
    if root.is_symlink():
        reject("Output directory cannot be a symbolic link", "invalid_path")
    root = root.resolve()
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        reject("Output directory must be new or empty", "output_conflict")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _outputs(root):
    paths, hashes, total = [], {}, 0
    if root is not None:
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                reject("A generated output escaped its result directory", "invalid_result")
            if not path.is_file():
                continue
            total += path.stat().st_size
            if len(paths) >= MAX_OUTPUT_FILES or total > MAX_OUTPUT_BYTES:
                reject("Generated outputs exceed the artifact budget", "resource_limit")
            paths.append(str(path))
            hashes[path.relative_to(root).as_posix()] = _digest(path)
    return paths, hashes


def operation(name):
    def decorate(function):
        @wraps(function)
        def call(args, output_dir=None):
            try:
                if isinstance(args, str) and len(args.encode("utf-8")) > MAX_ARGUMENT_BYTES:
                    reject("Arguments exceed the 4 MB source-operation budget", "resource_limit")
                args = arguments(name, args)
                if len(json.dumps(args, ensure_ascii=True).encode()) > MAX_ARGUMENT_BYTES:
                    reject("Arguments exceed the 4 MB source-operation budget", "resource_limit")
                spec = definition(name)
                upstream = spec["metadata"]["upstream"]
                profile_id = spec.get("registration_metadata", {}).get("runtime", {}).get("isolation_profile_id")
                if profile_id:
                    from geological_agent.geology import isolated_cpu_bridge_v2 as bridge
                    try:
                        if not bridge.active_child(name, spec):
                            return bridge.invoke(name, args, output_dir, function, spec)
                    except bridge.BridgeError as exc:
                        native = ScientificToolError(exc.code, str(exc), retryable=False)
                        native.remote_error = exc.details
                        raise native from exc
                installed = _dependencies(spec)
                canonical = _canonical_inputs(args, spec["source_interface"].get("path_fields", []))
                generates = bool(spec["source_interface"]["entrypoint"].get("output_directory_parameter"))
                root = _output_directory(output_dir) if generates else None
                if generates:
                    with _FILE_OPERATION_LOCK:
                        result = function(args, output_dir=root)
                else:
                    result = function(args)
                if not isinstance(result, dict) or not isinstance(result.get("units"), dict):
                    reject("Source operations must return a result object and explicit units", "invalid_result")
                paths, output_hashes = _outputs(root)
                source_file = Path(function.__code__.co_filename)
                result["artifacts"] = paths
                result["provenance"] = {
                    "tool": name,
                    "upstream_url": upstream.get("url"),
                    "source_mode": upstream.get("source_mode", "package_release"),
                    "reviewed_archive_commit": spec["registration_metadata"].get("source_commit"),
                    "installed_versions": installed,
                    "vendored_source": upstream.get("vendor_files", []),
                    "input_sha256": hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()).hexdigest(),
                    "implementation_sha256": _digest(source_file),
                    "contract_sha256": _digest(Path(__file__)),
                    "output_sha256": output_hashes,
                    "network_required": bool(spec["source_interface"].get("network_required", False)),
                    "runtime_source_correspondence": "Pinned published release and source archive HEAD are distinct unless vendored-source hashes explicitly establish correspondence.",
                }
                try:
                    finite(result)
                    Draft202012Validator(spec["output_schema"]).validate(result)
                    json.dumps(result, allow_nan=False)
                except (ValidationError, ValueError, TypeError):
                    reject("The actual source result violates the output contract", "invalid_result")
                return result
            except ScientificToolError:
                raise
            except (metadata.PackageNotFoundError, ModuleNotFoundError):
                reject("Install the declared reviewed dependency profile before invoking this operation", "missing_dependency")
            except ImportError:
                reject("Installed dependencies are incompatible with this reviewed operation", "incompatible_dependency")
            except FileNotFoundError:
                reject("A required input or configured resource is missing", "missing_input")
            except PermissionError:
                reject("Input or output access was denied", "invalid_path")
            except (ValidationError, ValueError, TypeError, KeyError, OverflowError):
                reject("Arguments do not satisfy the input schema and declared operation constraints")
            except MemoryError:
                reject("Operation exceeded available memory", "resource_limit")
            except OSError:
                reject("The declared input could not be read using its required format", "invalid_input")
            except Exception as exc:
                qualified = type(exc).__module__ + "." + type(exc).__name__
                if qualified == "pyproj.exceptions.CRSError":
                    reject("The declared CRS is invalid")
                reject("The reviewed upstream operation failed: " + qualified, "upstream_failure")
        call.__geoagent_operation_id__ = name
        return call
    return decorate

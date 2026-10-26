"""Fixed admin-only CPU IPC v2. Environment isolation is NOT an OS sandbox."""
from contextvars import ContextVar
from copy import deepcopy
import ctypes
import fnmatch
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time

PROTOCOL = "geoagent-isolated-cpu-v2"
MAGIC = b"GEOCPU2\n"
ROOT = Path(__file__).resolve().parents[2]
PROFILE_FILE = ROOT / "catalog/source_delivery/expansion501-20261026/shared-isolation-v2/profiles.json"
CHILD = ContextVar("geoagent_isolated_cpu_v2_child", default=None)
SHA = re.compile(r"[0-9a-f]{64}")
IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,79}")
PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9][A-Za-z0-9_.+!-]*)")
VALIDATORS = {"text_utf8", "json", "csv", "png", "geotiff", "hdf5"}
LIMITS = {
    "timeout_seconds": (1, 3600), "memory_bytes": (67108864, 17179869184),
    "request_bytes": (1024, 4000000), "response_json_bytes": (1024, 4000000),
    "stderr_bytes": (1024, 1048576), "input_bytes": (1, 134217728),
    "input_files": (1, 256), "output_bytes": (1, 134217728),
    "output_files": (1, 64), "file_bytes": (1, 67108864),
}
PROFILE_KEYS = {
    "tool", "source_root", "private_root", "input_root", "output_root",
    "python", "python_realpath", "python_prefix", "python_sha256", "python_version",
    "worker", "worker_sha256", "module", "callable", "catalog", "catalog_sha256",
    "source_files", "requirements", "dependency_lock", "dependency_lock_sha256",
    "build_receipt", "build_receipt_sha256", "source_closure_complete",
    "projects", "artifact_rules", "limits",
}


class BridgeError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.retryable, self.details = code, False, details or {}


def need(condition, message, code="integrity_error"):
    if not condition:
        raise BridgeError(code, message)


def closed(obj, keys):
    need(isinstance(obj, dict) and set(obj) == set(keys), "Protocol object has unknown or missing fields.")


def finite(value, depth=0):
    need(depth <= 64, "JSON nesting exceeds the fixed bound.", "resource_limit")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        need(math.isfinite(value), "Nonfinite JSON.", "invalid_arguments")
    elif isinstance(value, list):
        for child in value:
            finite(child, depth + 1)
    elif isinstance(value, dict):
        need(all(isinstance(k, str) for k in value), "JSON keys must be strings.")
        for child in value.values():
            finite(child, depth + 1)
    else:
        need(False, "Value is not JSON compatible.", "invalid_arguments")


def json_bytes(value):
    finite(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def strict_json(data, limit):
    need(len(data) <= limit, "JSON byte limit exceeded.", "resource_limit")
    def pairs(items):
        obj = {}
        for key, value in items:
            need(key not in obj, "Duplicate JSON key.")
            obj[key] = value
        return obj
    def constant(value):
        raise BridgeError("invalid_arguments", "Nonfinite JSON constant.")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise BridgeError("invalid_result", "Malformed bounded UTF-8 JSON.") from error
    finite(value)
    return value


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for data in iter(lambda: stream.read(262144), b""):
            result.update(data)
    return result.hexdigest()


def relative(value):
    need(isinstance(value, str) and 1 <= len(value) <= 240 and
         re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", value),
         "Invalid relative protocol path.", "invalid_path")
    path = PurePosixPath(value)
    need(not path.is_absolute() and all(x not in (".", "..") for x in path.parts),
         "Path traversal is forbidden.", "invalid_path")
    return path


def no_links(path):
    path = Path(path)
    for part in (path, *path.parents):
        need(not part.is_symlink() and not getattr(part, "is_junction", lambda: False)(),
             "Symlink or junction path component.", "invalid_path")


def regular(path, *, single_link=False):
    path = Path(path)
    no_links(path)
    need(path.is_file(), "Required reviewed file is missing.", "missing_dependency")
    info = path.stat()
    need(stat.S_ISREG(info.st_mode) and (not single_link or info.st_nlink == 1),
         "Only ordinary non-hardlinked files are permitted.", "invalid_path")
    return info


def within(root, path, *, must_exist=True):
    root, path = Path(root), Path(path)
    need(root.is_absolute() and path.is_absolute(), "Admin paths must be absolute.")
    no_links(root)
    no_links(path)
    try:
        resolved = path.resolve(strict=must_exist)
        base = root.resolve(strict=True)
    except OSError as error:
        raise BridgeError("missing_dependency", "Reviewed workspace is unavailable.") from error
    need(resolved.is_relative_to(base), "Path escapes its administrator boundary.", "invalid_path")
    return resolved


def bound_file(root, rel, digest):
    need(isinstance(digest, str) and SHA.fullmatch(digest), "Missing real SHA-256 binding.")
    path = within(root, Path(root).joinpath(*relative(rel).parts))
    regular(path)
    need(sha(path) == digest, "Reviewed file hash mismatch.")
    return path


def pin_map(requirements):
    need(isinstance(requirements, list) and len(requirements) <= 128,
         "Invalid exact dependency requirements.")
    result = {}
    for requirement in requirements:
        match = PIN.fullmatch(requirement) if isinstance(requirement, str) else None
        need(match is not None, "Only exact package==version pins are supported by v2; source builds need reviewed installed-version metadata.", "missing_dependency")
        name, version = match.groups()
        need(name not in result, "Duplicate dependency pin.")
        result[name] = version
    return result


def expected_requirements(spec):
    upstream = spec["metadata"]["upstream"]
    requirements = list(upstream.get("requirements", []))
    if upstream.get("source_mode", "package_release") == "package_release":
        requirement = str(upstream.get("package", "")) + "==" + str(upstream.get("version", ""))
        if requirement not in requirements:
            requirements.append(requirement)
    return pin_map(requirements)


def validate_profile(profile_id, profile, tool):
    need(isinstance(profile_id, str) and IDENTIFIER.fullmatch(profile_id), "Invalid fixed profile ID.")
    closed(profile, PROFILE_KEYS)
    p = profile
    need(p["tool"] == tool and isinstance(tool, str) and IDENTIFIER.fullmatch(tool),
         "Tool/profile mismatch.")
    need(p["source_closure_complete"] is True, "Reviewed source closure is incomplete.", "missing_dependency")
    for name in ("source_root", "private_root", "input_root", "output_root", "python_prefix"):
        value = Path(p[name])
        need(value.is_absolute() and value.is_dir(), "Missing fixed administrator directory.", "missing_dependency")
        no_links(value)
    need(re.fullmatch(r"\d+\.\d+\.\d+", p["python_version"]) is not None, "Exact Python version required.")
    python = Path(p["python"])
    real = Path(p["python_realpath"])
    need(python.is_absolute() and real.is_absolute(), "Interpreter paths must be absolute.")
    regular(real)
    need(python.resolve(strict=True) == real.resolve(strict=True) and sha(real) == p["python_sha256"],
         "Interpreter identity mismatch.")
    # A venv interpreter symlink is allowed only with its exact real target binding.
    need(isinstance(p["source_files"], dict) and 1 <= len(p["source_files"]) <= 4096,
         "Missing reviewed source closure.")
    for rel, digest in p["source_files"].items():
        bound_file(p["source_root"], rel, digest)
    worker = within(p["source_root"], Path(p["worker"]))
    need(worker == Path(p["source_root"]) / "geological_agent/geology/isolated_cpu_worker_v2.py",
         "Only the fixed v2 worker is allowed.")
    need(sha(worker) == p["worker_sha256"] and
         p["source_files"].get("geological_agent/geology/isolated_cpu_worker_v2.py") == p["worker_sha256"],
         "Worker binding mismatch.")
    need(re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", p["module"]) is not None and
         re.fullmatch(r"[A-Za-z_]\w*", p["callable"]) is not None, "Invalid fixed source entry.")
    module_rel = p["module"].replace(".", "/") + ".py"
    need(module_rel in p["source_files"], "Fixed callable source is not in the reviewed closure.")
    for required in ("geological_agent/geology/isolated_cpu_bridge_v2.py",
                     "geological_agent/geology/collection_contracts.py",
                     "legacy/ToolsAgent/ToolsFuns/source_contracts.py",
                     "legacy/ToolsAgent/ToolsFuns/GeoEval/scientific_tools.py"):
        need(required in p["source_files"], "Incomplete contract source binding.")
    for path_key, hash_key in (("catalog", "catalog_sha256"), ("dependency_lock", "dependency_lock_sha256"),
                               ("build_receipt", "build_receipt_sha256")):
        path = within(p["source_root"], Path(p[path_key]))
        regular(path)
        need(sha(path) == p[hash_key], "Catalog/lock/build receipt identity mismatch.")
    need(Path(p["catalog"]) == Path(p["source_root"]) / "catalog/registry.json",
         "Only the staged canonical catalog location is supported.")
    pins = pin_map(p["requirements"])
    lock = Path(p["dependency_lock"]).read_text(encoding="utf-8")
    need(pin_map([x.strip() for x in lock.splitlines() if x.strip() and not x.lstrip().startswith("#")]) == pins,
         "Exact dependency lock disagrees with profile.")
    receipt = strict_json(Path(p["build_receipt"]).read_bytes(), 1048576)
    closed(receipt, {"profile_id", "python_version", "python_sha256", "dependency_lock_sha256",
                     "license_review_complete", "source_closure_complete", "projects"})
    need(receipt == {
        "profile_id": profile_id, "python_version": p["python_version"],
        "python_sha256": p["python_sha256"], "dependency_lock_sha256": p["dependency_lock_sha256"],
        "license_review_complete": True, "source_closure_complete": True,
        "projects": sorted(p["projects"]),
    }, "Reviewed build/license receipt is incomplete or mismatched.", "missing_dependency")
    need(isinstance(p["projects"], dict) and set(p["projects"]) <= {"PDAL", "GRASS", "CBC", "OTB", "6S", "ISCE2", "SNAPHU", "PySolid", "ecCodes"},
         "Unknown administrator native project.")
    for project, item in p["projects"].items():
        closed(item, {"version", "root", "executable", "build_receipt", "closure_complete", "files_sha256"})
        need(item["closure_complete"] is True and isinstance(item["version"], str) and 1 <= len(item["version"]) <= 80,
             "Native project version/closure incomplete.", "missing_dependency")
        need(isinstance(item["files_sha256"], dict) and 1 <= len(item["files_sha256"]) <= 4096,
             "Native closure hash map is missing.")
        for rel, digest in item["files_sha256"].items():
            bound_file(item["root"], rel, digest)
        need(item["executable"] in item["files_sha256"] and item["build_receipt"] in item["files_sha256"],
             "Native executable/receipt is not hash bound.")
        native_receipt = strict_json((Path(item["root"]) / relative(item["build_receipt"])).read_bytes(), 1048576)
        closed(native_receipt, {"project", "version", "license_review_complete", "closure_complete"})
        need(native_receipt == {"project": project, "version": item["version"],
                                "license_review_complete": True, "closure_complete": True},
             "Native project receipt does not prove its declared identity.", "missing_dependency")
    closed(p["limits"], LIMITS)
    for name, (minimum, maximum) in LIMITS.items():
        value = p["limits"][name]
        need(type(value) is int and minimum <= value <= maximum, "Invalid fixed resource limit.")
    need(isinstance(p["artifact_rules"], list) and len(p["artifact_rules"]) <= 32, "Invalid artifact rules.")
    for rule in p["artifact_rules"]:
        closed(rule, {"glob", "validator_id"})
        need(isinstance(rule["glob"], str) and 1 <= len(rule["glob"]) <= 120 and
             "\\" not in rule["glob"] and ":" not in rule["glob"] and
             not rule["glob"].startswith("/") and ".." not in rule["glob"],
             "Unsafe administrator artifact pattern.")
        need(rule["validator_id"] in VALIDATORS, "Unsupported fixed artifact content validator.", "missing_dependency")
    return p


def load_profile(profile_id, tool, registry=None):
    path = Path(registry or PROFILE_FILE)
    regular(path)
    need(path.stat().st_size <= 1048576, "Admin profile file is too large.", "resource_limit")
    raw = path.read_bytes()
    config = strict_json(raw, 1048576)
    closed(config, {"protocol", "profiles"})
    need(config["protocol"] == PROTOCOL and isinstance(config["profiles"], dict),
         "Unknown admin profile protocol.")
    need(profile_id in config["profiles"], "No reviewed isolated CPU profile is prepared.", "missing_dependency")
    return validate_profile(profile_id, config["profiles"][profile_id], tool), raw


def active_child(name, spec):
    context = CHILD.get()
    if context is None:
        return False
    need(context["pid"] == os.getpid() and context["tool"] == name and
         context["spec_sha256"] == hashlib.sha256(json_bytes(spec)).hexdigest(),
         "A child context cannot dispatch another operation.")
    return True


def native_projects():
    context = CHILD.get()
    need(context is not None and context["pid"] == os.getpid(), "Native profiles are available only inside the fixed worker.")
    return deepcopy(context["profile"]["projects"])


def read_exact(stream, count):
    data = bytearray()
    while len(data) < count:
        block = stream.read(min(262144, count - len(data)))
        need(block, "Truncated IPC frame.", "invalid_result")
        data.extend(block)
    return bytes(data)


def write_header(stream, value, limit):
    data = json_bytes(value)
    need(len(data) <= limit, "Control frame exceeds limit.", "resource_limit")
    stream.write(MAGIC + struct.pack(">I", len(data)) + data)


def read_header(stream, limit):
    need(read_exact(stream, len(MAGIC)) == MAGIC, "Wrong IPC magic.", "invalid_result")
    size = struct.unpack(">I", read_exact(stream, 4))[0]
    need(size <= limit, "Control frame exceeds limit.", "resource_limit")
    return strict_json(read_exact(stream, size), limit)


def artifact_validator(p, name):
    matches = [r["validator_id"] for r in p["artifact_rules"] if fnmatch.fnmatchcase(name, r["glob"])]
    need(len(matches) == 1, "Artifact needs exactly one fixed content validator.", "invalid_result")
    return matches[0]


def content_check(path, validator, *, semantic):
    regular(path, single_link=True)
    with Path(path).open("rb") as handle:
        prefix = handle.read(32)
    if validator in ("text_utf8", "json", "csv"):
        raw = Path(path).read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise BridgeError("invalid_result", "Artifact is not UTF-8.") from error
        need("\x00" not in text, "NUL in text artifact.", "invalid_result")
        if validator == "json":
            strict_json(raw, 67108864)
        if validator == "csv":
            import csv
            import io
            rows = csv.reader(io.StringIO(text))
            header = next(rows, None)
            need(header and len(header) <= 4096, "CSV needs a bounded header.", "invalid_result")
            for index, row in enumerate(rows):
                need(index < 1000000 and len(row) == len(header), "Ragged/oversized CSV.", "invalid_result")
    elif validator == "png":
        need(len(prefix) >= 24, "Truncated PNG.", "invalid_result")
        need(prefix[:8] == b"\x89PNG\r\n\x1a\n" and prefix[12:16] == b"IHDR",
             "Invalid PNG signature.", "invalid_result")
        width, height = struct.unpack(">II", prefix[16:24])
        need(0 < width <= 16384 and 0 < height <= 16384 and width * height <= 16777216,
             "PNG dimensions exceed bound.", "resource_limit")
        import zlib
        decompressor, expanded, saw_data, first = zlib.decompressobj(), 0, False, True
        with Path(path).open("rb") as handle:
            read_exact(handle, 8)
            while True:
                length = struct.unpack(">I", read_exact(handle, 4))[0]
                kind = read_exact(handle, 4)
                need(length <= 67108864, "PNG chunk exceeds bound.", "resource_limit")
                data = read_exact(handle, length)
                crc = struct.unpack(">I", read_exact(handle, 4))[0]
                need(zlib.crc32(kind + data) & 0xffffffff == crc, "PNG CRC mismatch.", "invalid_result")
                if first:
                    need(kind == b"IHDR" and length == 13, "Invalid PNG IHDR.", "invalid_result")
                    first = False
                if kind == b"IDAT":
                    saw_data = True
                    try:
                        expanded += len(decompressor.decompress(data, 134217729 - expanded))
                    except zlib.error as error:
                        raise BridgeError("invalid_result", "Invalid PNG compressed stream.") from error
                    need(expanded <= 134217728 and not decompressor.unconsumed_tail,
                         "PNG expansion exceeds bound.", "resource_limit")
                if kind == b"IEND":
                    need(length == 0 and saw_data and decompressor.eof and handle.read(1) == b"",
                         "Incomplete PNG stream.", "invalid_result")
                    break
    elif validator == "geotiff":
        need(prefix[:4] in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"),
             "Invalid TIFF signature.", "invalid_result")
        if semantic:
            import rasterio
            with rasterio.open(path) as image:
                need(image.driver == "GTiff" and image.crs is not None and
                     0 < image.width * image.height * image.count <= 16777216 and
                     all(math.isfinite(x) for x in image.transform) and abs(image.transform.determinant) > 0,
                     "Invalid georeferenced TIFF content.", "invalid_result")
    elif validator == "hdf5":
        need(prefix[:8] == b"\x89HDF\r\n\x1a\n", "Invalid HDF5 signature.", "invalid_result")
        if semantic:
            import h5py
            with h5py.File(path, "r") as handle:
                seen = set()
                def visit(group, depth=0):
                    need(depth <= 32, "HDF5 hierarchy too deep.", "resource_limit")
                    for name in group:
                        link = group.get(name, getlink=True)
                        need(isinstance(link, h5py.HardLink), "External/soft HDF5 links forbidden.", "invalid_result")
                        item = group[name]
                        address = h5py.h5o.get_info(item.id).addr
                        need(address not in seen, "Aliased/cyclic HDF5 objects forbidden.", "invalid_result")
                        seen.add(address)
                        if isinstance(item, h5py.Group):
                            visit(item, depth + 1)
                        else:
                            need(not item.is_virtual and not item.external and item.size <= 16777216,
                                 "Unsupported/oversized HDF5 storage.", "invalid_result")
                visit(handle)


def snapshot_inputs(args, spec, p, destination):
    copied, manifest, total, copied_paths = deepcopy(args), [], 0, {}
    fields = spec["source_interface"].get("path_fields", [])
    need(isinstance(fields, list) and len(fields) <= 64 and len(set(fields)) == len(fields),
         "Invalid declared path fields.")
    for field in fields:
        if field not in args:
            continue
        values = args[field] if isinstance(args[field], list) else [args[field]]
        need(isinstance(values, list), "Declared input paths must be strings/lists.")
        output = []
        for index, value in enumerate(values):
            need(isinstance(value, str), "Declared input path is not a string.", "invalid_path")
            source = Path(value)
            if not source.is_absolute():
                source = Path(p["input_root"]) / relative(value)
            source = within(p["input_root"], source)
            info = regular(source, single_link=True)
            rel = source.relative_to(Path(p["input_root"])).as_posix()
            relative(rel)
            if rel not in copied_paths:
                total += info.st_size
                need(info.st_size <= p["limits"]["file_bytes"] and total <= p["limits"]["input_bytes"] and
                     len(copied_paths) < p["limits"]["input_files"], "Input snapshot exceeds bounds.", "resource_limit")
                target = destination / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                before = sha(source)
                with source.open("rb") as src, target.open("xb") as dst:
                    size = 0
                    for block in iter(lambda: src.read(262144), b""):
                        size += len(block)
                        need(size <= info.st_size, "Input changed during snapshot.")
                        dst.write(block)
                digest = sha(target)
                need(size == info.st_size and digest == before == sha(source), "Input changed during snapshot.")
                target.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
                copied_paths[rel] = {"path": rel, "bytes": size, "sha256": digest}
            record = dict(copied_paths[rel], field=field, index=index if isinstance(args[field], list) else None)
            manifest.append(record)
            output.append(rel)
        copied[field] = output if isinstance(args[field], list) else output[0]
    return copied, manifest


def check_snapshots(root, records):
    expected = {}
    for item in records:
        closed(item, {"path", "bytes", "sha256", "field", "index"})
        relative(item["path"])
        need(type(item["bytes"]) is int and item["bytes"] >= 0 and SHA.fullmatch(item["sha256"]),
             "Invalid snapshot manifest.")
        expected[item["path"]] = item
    actual = set()
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            no_links(Path(directory) / name)
        for name in files:
            path = Path(directory) / name
            info = regular(path, single_link=True)
            rel = path.relative_to(root).as_posix()
            need(rel in expected and info.st_size == expected[rel]["bytes"] and sha(path) == expected[rel]["sha256"],
                 "Immutable input snapshot was modified.")
            actual.add(rel)
    need(actual == set(expected), "Input snapshot files were removed.")


class ProcessTree:
    """POSIX process group or Windows Job Object; not a filesystem/network sandbox."""
    def __init__(self, process, memory_bytes):
        self.process, self.job = process, None
        if os.name == "nt":
            from ctypes import wintypes as w
            class Basic(ctypes.Structure):
                _fields_ = [("user", ctypes.c_longlong), ("jobtime", ctypes.c_longlong), ("flags", w.DWORD),
                            ("minws", ctypes.c_size_t), ("maxws", ctypes.c_size_t), ("active", w.DWORD),
                            ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]
            class IO(ctypes.Structure):
                _fields_ = [(name, ctypes.c_ulonglong) for name in ("ro", "wo", "oo", "rb", "wb", "ob")]
            class Extended(ctypes.Structure):
                _fields_ = [("basic", Basic), ("io", IO), ("processmem", ctypes.c_size_t),
                            ("jobmem", ctypes.c_size_t), ("peakprocess", ctypes.c_size_t), ("peakjob", ctypes.c_size_t)]
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateJobObjectW.restype = w.HANDLE
            kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
            kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
            kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
            kernel.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
            kernel.CloseHandle.argtypes = [w.HANDLE]
            self.kernel, self.job = kernel, kernel.CreateJobObjectW(None, None)
            info = Extended()
            info.basic.flags = 0x2000 | 0x200  # KILL_ON_JOB_CLOSE | JOB_MEMORY
            info.jobmem = memory_bytes
            if not self.job or not kernel.SetInformationJobObject(self.job, 9, ctypes.byref(info), ctypes.sizeof(info)) or not kernel.AssignProcessToJobObject(self.job, w.HANDLE(process._handle)):
                if self.job:
                    kernel.CloseHandle(self.job)
                process.kill()
                raise BridgeError("resource_limit", "Windows process-tree resource binding failed.")
            kernel.GetProcessAffinityMask.argtypes = [w.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
            kernel.SetProcessAffinityMask.argtypes = [w.HANDLE, ctypes.c_size_t]
            process_mask, system_mask = ctypes.c_size_t(), ctypes.c_size_t()
            if not kernel.GetProcessAffinityMask(w.HANDLE(process._handle), ctypes.byref(process_mask), ctypes.byref(system_mask)):
                self.kill()
                self.close()
                raise BridgeError("resource_limit", "Could not determine the worker CPU affinity.")
            if process_mask.value:
                bits = [1 << n for n in range(8 * ctypes.sizeof(ctypes.c_size_t)) if process_mask.value & (1 << n)]
                if not kernel.SetProcessAffinityMask(w.HANDLE(process._handle), sum(bits[:2])):
                    self.kill()
                    self.close()
                    raise BridgeError("resource_limit", "Could not bind worker to at most two CPUs.")

    def kill(self):
        if os.name == "nt":
            if self.job:
                self.kernel.TerminateJobObject(self.job, 1)
        else:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def close(self):
        if self.job:
            self.kernel.CloseHandle(self.job)
            self.job = None


def private_environment(job):
    env = {}
    for name in ("SystemRoot", "WINDIR", "COMSPEC"):
        if name in os.environ:
            env[name] = os.environ[name]
    env.update(CUDA_VISIBLE_DEVICES="", NVIDIA_VISIBLE_DEVICES="none", HIP_VISIBLE_DEVICES="",
               ROCR_VISIBLE_DEVICES="", GPU_DEVICE_ORDINAL="", ZE_AFFINITY_MASK="",
               JAX_PLATFORMS="cpu", GEMPY_USE_GPU="False", GEMPY_GPU_FALLBACK="False", OTEL_SDK_DISABLED="true",
               LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false", GEOTOOL_LANGSMITH_ENABLED="0",
               PROJ_NETWORK="OFF", PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1",
               PYTHONUTF8="1", LANG="C.UTF-8", LC_ALL="C.UTF-8", MPLBACKEND="Agg")
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS",
                 "NUMBA_NUM_THREADS", "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        env[name] = "2"
    for name, sub in (("HOME", "home"), ("XDG_CACHE_HOME", "cache"), ("MPLCONFIGDIR", "mpl"),
                      ("NUMBA_CACHE_DIR", "numba"), ("TMPDIR", "tmp"), ("TMP", "tmp"), ("TEMP", "tmp")):
        path = job / sub
        path.mkdir(exist_ok=True)
        env[name] = str(path)
    return env


def run_framed_process(command, request, job, p):
    """command is built only from validated administrator paths by invoke()."""
    limits = p["limits"]
    stdout_path, stderr_path = job / "stdout.frames", job / "stderr.log"
    budget = limits["response_json_bytes"] + limits["output_bytes"] + limits["output_files"] * 8 + 64
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               cwd=job / "inputs", env=private_environment(job), shell=False,
                               start_new_session=os.name != "nt", creationflags=flags if os.name == "nt" else 0)
    tree = ProcessTree(process, limits["memory_bytes"])
    failed, errors = threading.Event(), []
    def drain(pipe, path, maximum):
        try:
            with path.open("xb") as stream:
                count = 0
                while True:
                    block = pipe.read(16384)
                    if not block:
                        break
                    remaining = maximum - count
                    stream.write(block[:max(0, remaining)])
                    count += len(block)
                    if count > maximum:
                        errors.append("Worker output stream exceeded its byte budget.")
                        failed.set()
                        tree.kill()
                        break
        except Exception as error:
            errors.append(type(error).__name__)
            failed.set()
            tree.kill()
    def send():
        try:
            process.stdin.write(request)
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass
    threads = [threading.Thread(target=drain, args=(process.stdout, stdout_path, budget), daemon=True),
               threading.Thread(target=drain, args=(process.stderr, stderr_path, limits["stderr_bytes"]), daemon=True),
               threading.Thread(target=send, daemon=True)]
    deadline = time.monotonic() + limits["timeout_seconds"]
    try:
        for thread in threads:
            thread.start()
        while process.poll() is None and not failed.is_set() and time.monotonic() < deadline:
            time.sleep(0.02)
        deadline_expired = time.monotonic() >= deadline
        if process.poll() is None or failed.is_set():
            tree.kill()
        process.wait(timeout=5)
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in threads):
            failed.set()
            errors.append("Worker process-tree deadline exceeded.")
            tree.kill()
            for thread in threads:
                thread.join(2)
        need(not failed.is_set() and not deadline_expired and time.monotonic() < deadline,
             "; ".join(errors) or "Worker deadline exceeded.", "resource_limit")
        return process.returncode, stdout_path, stderr_path
    finally:
        tree.kill()
        tree.close()
        for pipe in (process.stdin, process.stdout, process.stderr):
            try:
                pipe.close()
            except OSError:
                pass


def receive(stream, p, nonce, destination):
    response = read_header(stream, p["limits"]["response_json_bytes"])
    need(isinstance(response, dict), "Worker response must be an object.", "invalid_result")
    need(response.get("protocol") == PROTOCOL and response.get("tool") == p["tool"]
         and response.get("nonce") == nonce, "Worker response identity mismatch.", "invalid_result")
    if response.get("status") == "error":
        closed(response, {"protocol", "tool", "nonce", "status", "error"})
        closed(response["error"], {"code", "message", "retryable", "exception_chain"})
        error = response["error"]
        need(isinstance(error["code"], str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", error["code"]) and
             isinstance(error["message"], str) and len(error["message"]) <= 4096 and
             error["retryable"] is False and isinstance(error["exception_chain"], list) and
             len(error["exception_chain"]) <= 4, "Invalid structured worker error.")
        for cause in error["exception_chain"]:
            closed(cause, {"type", "message"})
            need(all(isinstance(x, str) and len(x) <= 4096 for x in cause.values()), "Invalid exception chain.")
        need(stream.read(1) == b"", "Unexpected trailing error payload.", "invalid_result")
        return response
    closed(response, {"protocol", "tool", "nonce", "status", "data", "files", "proof"})
    need(response["status"] == "ok" and isinstance(response["data"], dict) and
         isinstance(response["files"], list) and len(response["files"]) <= p["limits"]["output_files"],
         "Invalid success manifest.", "invalid_result")
    seen, total = set(), 0
    for item in response["files"]:
        closed(item, {"path", "bytes", "sha256", "validator_id"})
        relative(item["path"])
        need(item["path"] not in seen and type(item["bytes"]) is int and
             0 <= item["bytes"] <= p["limits"]["file_bytes"] and
             isinstance(item["sha256"], str) and SHA.fullmatch(item["sha256"]),
             "Invalid/duplicate artifact manifest entry.", "invalid_result")
        seen.add(item["path"])
        total += item["bytes"]
        need(total <= p["limits"]["output_bytes"], "Aggregate artifact budget exceeded.", "resource_limit")
        need(item["validator_id"] == artifact_validator(p, item["path"]), "Content-validator identity mismatch.")
        size = struct.unpack(">Q", read_exact(stream, 8))[0]
        need(size == item["bytes"], "Artifact frame length mismatch.", "invalid_result")
        target = destination.joinpath(*relative(item["path"]).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with target.open("xb") as handle:
            remaining = size
            while remaining:
                block = read_exact(stream, min(262144, remaining))
                handle.write(block)
                digest.update(block)
                remaining -= len(block)
        need(digest.hexdigest() == item["sha256"], "Artifact frame hash mismatch.")
        content_check(target, item["validator_id"], semantic=False)
    need(stream.read(1) == b"", "Unexpected trailing IPC bytes.", "invalid_result")
    need(response["data"].get("artifacts") == [x["path"] for x in response["files"]],
         "Data artifacts and transport manifest disagree.", "invalid_result")
    return response


def validate_result(spec, data):
    try:
        from jsonschema import Draft202012Validator
    except ImportError as error:
        raise BridgeError("missing_dependency", "jsonschema is required for the actual operation contract.") from error
    finite(data)
    errors = list(Draft202012Validator(spec["output_schema"]).iter_errors(data))
    need(not errors, "Isolated result violates the registered output schema.", "invalid_result")


def invoke(name, args, output_dir, function, spec):
    profile_id = spec.get("registration_metadata", {}).get("runtime", {}).get("isolation_profile_id")
    p, raw_config = load_profile(profile_id, name)
    need(spec["source_interface"].get("network_required") is False,
         "Only explicitly offline operation contracts are supported.", "missing_dependency")
    need(function.__name__ == p["callable"] and function.__module__ == p["module"],
         "Callable is not the administrator-bound entry.")
    implementation = Path(function.__code__.co_filename).resolve()
    regular(implementation)
    need(sha(implementation) == p["source_files"][p["module"].replace(".", "/") + ".py"],
         "Main callable bytes differ from the reviewed child source.")
    need(expected_requirements(spec) == pin_map(p["requirements"]), "Catalog dependencies differ from fixed child profile.")
    catalog = strict_json(Path(p["catalog"]).read_bytes(), 33554432)
    matches = [row for row in catalog["tools"] if row["id"] == name]
    need(len(matches) == 1 and json_bytes(matches[0]) == json_bytes(spec), "Staged catalog specification mismatch.")
    generates = bool(spec["source_interface"]["entrypoint"].get("output_directory_parameter"))
    need(generates or output_dir is None, "JSON-only isolated tools do not accept output_dir.", "invalid_arguments")
    target = None
    if generates:
        need(output_dir is not None, "Explicit output directory required.", "invalid_arguments")
        target = within(p["output_root"], Path(output_dir).absolute(), must_exist=False)
        need(not target.exists() or (target.is_dir() and not any(target.iterdir())),
             "Output directory must be new or empty.", "output_conflict")
    job = Path(tempfile.mkdtemp(prefix="v2-", dir=p["private_root"]))
    for sub in ("inputs", "outputs", "control", "received"):
        (job / sub).mkdir()
    # Preserve private evidence after failures and successes; operator owns retention.
    try:
        copied_args, inputs = snapshot_inputs(args, spec, p, job / "inputs")
        from geological_agent.geology.collection_contracts import _canonical_inputs
        hash_args = deepcopy(copied_args)
        for field in spec["source_interface"].get("path_fields", []):
            if field in hash_args:
                value = hash_args[field]
                hash_args[field] = [str(job / "inputs" / x) for x in value] if isinstance(value, list) else str(job / "inputs" / value)
        canonical = _canonical_inputs(hash_args, spec["source_interface"].get("path_fields", []))
        expected_input_hash = hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()).hexdigest()
        (job / "control/registry.json").write_bytes(raw_config)
        (job / "control/registry.json").chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
        nonce = secrets.token_hex(24)
        request = {"protocol": PROTOCOL, "tool": name, "profile_id": profile_id, "nonce": nonce,
                   "spec_sha256": hashlib.sha256(json_bytes(spec)).hexdigest(),
                   "args": copied_args, "inputs": inputs}
        import io
        encoded = io.BytesIO()
        write_header(encoded, request, p["limits"]["request_bytes"])
        command = [p["python"], "-I", "-B", p["worker"], profile_id, str(job),
                   hashlib.sha256(raw_config).hexdigest()]
        returncode, stdout_path, stderr_path = run_framed_process(command, encoded.getvalue(), job, p)
        with stdout_path.open("rb") as stream:
            response = receive(stream, p, nonce, job / "received")
        check_snapshots(job / "inputs", inputs)
        validate_profile(profile_id, p, name)  # detect changed source/native identities around execution
        need(Path(PROFILE_FILE).read_bytes() == raw_config, "Administrator profile changed during execution.")
        if response["status"] == "error":
            need(returncode != 0, "Worker error contradicts successful process exit.", "invalid_result")
            raise BridgeError(response["error"]["code"], response["error"]["message"],
                              {"remote_exception_chain": response["error"]["exception_chain"],
                               "exit_code": returncode, "evidence_directory": str(job)})
        need(returncode == 0, "Worker success contradicts process exit status.", "invalid_result")
        proof = response["proof"]
        closed(proof, {"profile_id", "profile_sha256", "worker_sha256", "python_version",
                       "python_sha256", "build_receipt_sha256", "installed_versions", "spec_sha256"})
        need(proof == {"profile_id": profile_id, "profile_sha256": hashlib.sha256(raw_config).hexdigest(),
                       "worker_sha256": p["worker_sha256"], "python_version": p["python_version"],
                       "python_sha256": p["python_sha256"], "build_receipt_sha256": p["build_receipt_sha256"],
                       "installed_versions": pin_map(p["requirements"]),
                       "spec_sha256": request["spec_sha256"]}, "Child execution identity mismatch.")
        data = response["data"]
        need(data.get("provenance", {}).get("installed_versions") == proof["installed_versions"] and
             data["provenance"].get("input_sha256") == expected_input_hash,
             "Provenance dependencies/input hash do not come from the verified child.")
        validate_result(spec, data)
        expected_hashes = {x["path"]: x["sha256"] for x in response["files"]}
        need(data["provenance"].get("output_sha256") == expected_hashes,
             "Child contract hashes disagree with artifacts.")
        data["provenance"]["isolation"] = dict(proof, protocol=PROTOCOL,
                                               native_projects={key: value["version"] for key, value in p["projects"].items()},
                                               gpu_requested=False, runtime_install=False,
                                               os_sandbox=False, evidence_directory=str(job))
        data["artifacts"] = [str(target / x["path"]) for x in response["files"]] if target is not None else []
        validate_result(spec, data)  # fail schema checks before writing the caller output directory
        if target is not None:
            target.mkdir(parents=True, exist_ok=True)
            for item in response["files"]:
                destination = target / relative(item["path"])
                no_links(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with (job / "received" / relative(item["path"])).open("rb") as src, destination.open("xb") as dst:
                    shutil.copyfileobj(src, dst, 262144)
                need(sha(destination) == item["sha256"], "Artifact changed during controlled ingestion.")
            from geological_agent.geology.collection_contracts import _outputs
            paths, hashes = _outputs(target)
            need(hashes == expected_hashes, "Main contract output hashes differ from child hashes.")
            data["artifacts"] = paths
        else:
            need(not response["files"], "JSON-only operation unexpectedly returned artifacts.", "invalid_result")
        validate_result(spec, data)
        (job / "status.json").write_bytes(json_bytes({"status": "ok", "exit_code": returncode, "tool": name}))
        return data
    except BaseException as error:
        (job / "status.json").write_bytes(json_bytes({"status": "failed", "exception_type":
            type(error).__module__ + "." + type(error).__name__, "message": str(error)[:4096]}))
        raise

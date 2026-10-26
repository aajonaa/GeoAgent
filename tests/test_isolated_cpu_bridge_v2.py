"""Synthetic contract/real-process tests; never scientific or Linux acceptance."""
import copy
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "catalog/source_delivery/expansion501-20261026/shared-isolation-v2"
SPEC = importlib.util.spec_from_file_location("v2_bridge_contract_test", ROOT / "geological_agent/geology/isolated_cpu_bridge_v2.py")
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)
HAS_JSONSCHEMA = importlib.util.find_spec("jsonschema") is not None


def limits():
    return {"timeout_seconds": 10, "memory_bytes": 536870912, "request_bytes": 4096,
            "response_json_bytes": 4096, "stderr_bytes": 4096, "input_bytes": 65536,
            "input_files": 8, "output_bytes": 65536, "output_files": 8, "file_bytes": 65536}


def settings():
    # Wire-test limits, deliberately NOT a valid administrator profile.
    return {"tool": "Fixture", "limits": limits(),
            "artifact_rules": [{"glob": "*.txt", "validator_id": "text_utf8"}]}


def response(body=b"11", **changes):
    item = {"path": "answer.txt", "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            "validator_id": "text_utf8"}
    value = {"protocol": bridge.PROTOCOL, "tool": "Fixture", "nonce": "a" * 48, "status": "ok",
             "data": {"artifacts": ["answer.txt"]}, "files": [item], "proof": {}}
    value.update(changes)
    return value


def encoded(value, bodies=()):
    stream = io.BytesIO()
    bridge.write_header(stream, value, 65536)
    for body in bodies:
        stream.write(struct.pack(">Q", len(body)) + body)
    stream.seek(0)
    return stream


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        scratch = AREA / "local-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="stdlib-", dir=scratch)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def reject_receive(self, value, bodies=(b"11",), expected=None):
        with self.assertRaises(bridge.BridgeError) as caught:
            bridge.receive(encoded(value, bodies), settings(), "a" * 48, self.root)
        if expected:
            self.assertEqual(caught.exception.code, expected)

    def test_frame_roundtrip(self):
        value = {"x": 3, "units": {"x": "synthetic_count"}}
        self.assertEqual(bridge.read_header(encoded(value), 4096), value)

    def test_duplicate_json(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.strict_json(b'{"x":1,"x":2}', 100)

    def test_nan_json(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.strict_json(b'{"x":NaN}', 100)

    def test_deep_json(self):
        value = 1
        for _ in range(66):
            value = [value]
        with self.assertRaises(bridge.BridgeError):
            bridge.json_bytes(value)

    def test_truncated_header(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.read_header(io.BytesIO(bridge.MAGIC + b"\x00"), 4096)

    def test_oversized_control_header(self):
        with self.assertRaises(bridge.BridgeError) as caught:
            bridge.read_header(io.BytesIO(bridge.MAGIC + struct.pack(">I", 5000)), 4096)
        self.assertEqual(caught.exception.code, "resource_limit")

    def test_artifact_payload_roundtrip(self):
        result = bridge.receive(encoded(response(), [b"11"]), settings(), "a" * 48, self.root)
        self.assertEqual((self.root / "answer.txt").read_bytes(), b"11")
        self.assertEqual(result["files"][0]["sha256"], hashlib.sha256(b"11").hexdigest())

    def test_unknown_response_field(self):
        self.reject_receive(response(extra="forbidden"))

    def test_response_not_object(self):
        self.reject_receive(["not", "an", "object"], bodies=())

    def test_artifact_traversal(self):
        value = response()
        value["files"][0]["path"] = "../outside.txt"
        self.reject_receive(value, expected="invalid_path")

    def test_absolute_artifact(self):
        value = response()
        value["files"][0]["path"] = "/outside.txt"
        self.reject_receive(value, expected="invalid_path")

    def test_windows_artifact(self):
        value = response()
        value["files"][0]["path"] = "C:/outside.txt"
        self.reject_receive(value, expected="invalid_path")

    def test_tampered_artifact_hash(self):
        value = response()
        value["files"][0]["sha256"] = "0" * 64
        self.reject_receive(value)

    def test_mismatched_frame_size(self):
        value = response()
        value["files"][0]["bytes"] = 1
        self.reject_receive(value)

    def test_duplicate_artifacts(self):
        value = response()
        value["files"].append(copy.deepcopy(value["files"][0]))
        value["data"]["artifacts"].append("answer.txt")
        self.reject_receive(value, bodies=(b"11", b"11"))

    def test_artifact_limit(self):
        value = response()
        value["files"][0]["bytes"] = 65537
        self.reject_receive(value)

    def test_validator_binding(self):
        value = response()
        value["files"][0]["validator_id"] = "json"
        self.reject_receive(value)

    def test_result_manifest_mismatch(self):
        value = response()
        value["data"]["artifacts"] = []
        self.reject_receive(value)

    def test_nonce_mismatch(self):
        self.reject_receive(response(nonce="b" * 48))

    def test_trailing_bytes(self):
        stream = encoded(response(), [b"11"])
        data = stream.getvalue() + b"unexpected"
        with self.assertRaises(bridge.BridgeError):
            bridge.receive(io.BytesIO(data), settings(), "a" * 48, self.root)

    def test_structured_error_preserved(self):
        value = {"protocol": bridge.PROTOCOL, "tool": "Fixture", "nonce": "a" * 48,
                 "status": "error", "error": {"code": "missing_dependency", "message": "fixture missing",
                     "retryable": False, "exception_chain": [{"type": "builtins.ModuleNotFoundError", "message": "fixture"}]}}
        actual = bridge.receive(encoded(value), settings(), "a" * 48, self.root)
        self.assertEqual(actual["error"], value["error"])

    def test_unknown_error_field(self):
        value = {"protocol": bridge.PROTOCOL, "tool": "Fixture", "nonce": "a" * 48,
                 "status": "error", "error": {"code": "x", "message": "x", "retryable": False,
                                            "exception_chain": [], "install": True}}
        self.reject_receive(value, bodies=())

    def test_closed_profile_no_placeholders(self):
        profile = {"python": "not-a-profile"}
        with self.assertRaises(bridge.BridgeError):
            bridge.validate_profile("Fixture", profile, "Fixture")

    def test_empty_admin_allowlist(self):
        registry = self.root / "profiles.json"
        registry.write_bytes(bridge.json_bytes({"protocol": bridge.PROTOCOL, "profiles": {}}))
        with self.assertRaises(bridge.BridgeError) as caught:
            bridge.load_profile("Fixture", "Fixture", registry)
        self.assertEqual(caught.exception.code, "missing_dependency")

    def test_unsupported_requirement(self):
        with self.assertRaises(bridge.BridgeError) as caught:
            bridge.pin_map(["package>=1"])
        self.assertEqual(caught.exception.code, "missing_dependency")

    def test_text_content_check(self):
        path = self.root / "answer.txt"
        path.write_text("11", encoding="utf-8")
        bridge.content_check(path, "text_utf8", semantic=False)

    def test_binary_not_text(self):
        path = self.root / "answer.txt"
        path.write_bytes(b"\x00binary")
        with self.assertRaises(bridge.BridgeError):
            bridge.content_check(path, "text_utf8", semantic=False)

    def test_ragged_csv(self):
        path = self.root / "x.csv"
        path.write_text("a,b\n1\n", encoding="utf-8")
        with self.assertRaises(bridge.BridgeError):
            bridge.content_check(path, "csv", semantic=False)

    def test_invalid_png(self):
        path = self.root / "x.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        with self.assertRaises(bridge.BridgeError):
            bridge.content_check(path, "png", semantic=False)

    def test_snapshot_copy_and_tamper(self):
        source, target = self.root / "source", self.root / "snapshot"
        source.mkdir()
        target.mkdir()
        (source / "a.txt").write_bytes(b"4")
        p = settings()
        p["input_root"] = str(source)
        args, manifest = bridge.snapshot_inputs({"file": "a.txt"}, {"source_interface": {"path_fields": ["file"]}}, p, target)
        self.assertEqual(args["file"], "a.txt")
        bridge.check_snapshots(target, manifest)
        (target / "a.txt").chmod(0o600)
        (target / "a.txt").write_bytes(b"5")
        with self.assertRaises(bridge.BridgeError):
            bridge.check_snapshots(target, manifest)
        self.assertEqual((source / "a.txt").read_bytes(), b"4")

    def test_no_context_bypass(self):
        self.assertFalse(bridge.active_child("Fixture", {}))
        with mock.patch.dict(os.environ, {"GEOAGENT_CHILD": "1"}):
            self.assertFalse(bridge.active_child("Fixture", {}))

    def test_wrong_child_context(self):
        token = bridge.CHILD.set({"pid": os.getpid(), "tool": "Other", "spec_sha256": "x"})
        try:
            with self.assertRaises(bridge.BridgeError):
                bridge.active_child("Fixture", {})
        finally:
            bridge.CHILD.reset(token)

    def child_script(self, source):
        (self.root / "inputs").mkdir()
        path = self.root / "synthetic_child.py"
        path.write_text(source, encoding="utf-8")
        return [sys.executable, "-I", "-B", str(path)]

    def test_real_subprocess_framed_artifact(self):
        # Genuine OS process + binary frame path, not the decorator/scientific suite.
        wire = encoded(response(), [b"11"]).getvalue()
        command = self.child_script("import sys\nsys.stdin.buffer.read()\nsys.stdout.buffer.write(" + repr(wire) + ")\n")
        code, stdout, stderr = bridge.run_framed_process(command, b"request", self.root, settings())
        self.assertEqual(code, 0)
        received = self.root / "received"
        received.mkdir()
        with stdout.open("rb") as handle:
            bridge.receive(handle, settings(), "a" * 48, received)
        self.assertEqual((received / "answer.txt").read_bytes(), b"11")
        self.assertEqual(stderr.read_bytes(), b"")

    def test_real_process_nonzero_exit(self):
        command = self.child_script("import sys\nsys.stdin.buffer.read()\nsys.exit(7)\n")
        code, _, _ = bridge.run_framed_process(command, b"x", self.root, settings())
        self.assertEqual(code, 7)

    def test_real_process_stderr_bound(self):
        command = self.child_script("import sys\nsys.stdin.buffer.read()\nsys.stderr.write('x' * 1000000)\n")
        with self.assertRaises(bridge.BridgeError) as caught:
            bridge.run_framed_process(command, b"x", self.root, settings())
        self.assertEqual(caught.exception.code, "resource_limit")
        self.assertIn("stream", str(caught.exception))

    def test_real_process_stdout_bound(self):
        command = self.child_script("import sys\nsys.stdin.buffer.read()\nsys.stdout.write('x' * 1000000)\n")
        with self.assertRaises(bridge.BridgeError) as caught:
            bridge.run_framed_process(command, b"x", self.root, settings())
        self.assertEqual(caught.exception.code, "resource_limit")
        self.assertIn("stream", str(caught.exception))

    def test_real_process_deadline(self):
        command = self.child_script("import sys,time\nsys.stdin.buffer.read()\ntime.sleep(5)\n")
        p = settings()
        p["limits"]["timeout_seconds"] = 1
        with self.assertRaises(bridge.BridgeError) as caught:
            bridge.run_framed_process(command, b"x", self.root, p)
        self.assertEqual(caught.exception.code, "resource_limit")


@unittest.skipUnless(HAS_JSONSCHEMA, "Actual canonical decorator dependency jsonschema is unavailable; no substitute/mock installed.")
class CanonicalEndToEndTests(unittest.TestCase):
    """Real canonical decorator + fixed production worker, only synthetic data."""

    def setUp(self):
        sys.path.insert(0, str(ROOT))
        self.addCleanup(lambda: sys.path.remove(str(ROOT)))
        from geological_agent.geology import collection_contracts as contracts
        from geological_agent.geology import isolated_cpu_bridge_v2 as real_bridge
        from legacy.ToolsAgent.ToolsFuns import source_contracts
        self.contracts, self.bridge, self.source_contracts = contracts, real_bridge, source_contracts
        scratch = AREA / "local-tests"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="canonical-", dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        shared = [
            "geological_agent/__init__.py", "geological_agent/geology/__init__.py",
            "geological_agent/geology/collection_contracts.py",
            "geological_agent/geology/isolated_cpu_bridge_v2.py",
            "geological_agent/geology/isolated_cpu_worker_v2.py",
            "legacy/ToolsAgent/__init__.py", "legacy/ToolsAgent/ToolsFuns/__init__.py",
            "legacy/ToolsAgent/ToolsFuns/GeoEval/__init__.py",
            "legacy/ToolsAgent/ToolsFuns/source_contracts.py",
            "legacy/ToolsAgent/ToolsFuns/GeoEval/scientific_tools.py",
        ]
        for rel in shared:
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, target)
        source = (
            "from pathlib import Path\n"
            "from geological_agent.geology.collection_contracts import operation\n"
            "@operation('IsolationFixture')\n"
            "def fixture(args, output_dir=None):\n"
            "    if args['behavior'] == 'error': raise ValueError('SYNTHETIC_ORIGINAL_ERROR')\n"
            "    value = args['value'] + int(Path(args['input_path']).read_text())\n"
            "    if output_dir is not None: (Path(output_dir) / 'answer.txt').write_text(str(value), encoding='utf-8')\n"
            "    return {'value': value, 'units': {'value': 'synthetic_count'}}\n"
        )
        (self.root / "isolated_fixture.py").write_text(source, encoding="utf-8")
        shared.append("isolated_fixture.py")
        prototype = json.loads((ROOT / "catalog/source_delivery/expansion501-20261026/groups/remote/catalog-additions.json").read_text(encoding="utf-8"))["tools"][0]
        spec = copy.deepcopy(prototype)
        spec["id"] = "IsolationFixture"
        spec["metadata"]["upstream"] = {"source_mode": "vendored_source", "url": "urn:synthetic:IPC-only",
                                        "requirements": ["jsonschema==" + importlib.metadata.version("jsonschema")]}
        spec["registration_metadata"]["source_commit"] = None
        spec["registration_metadata"].setdefault("runtime", {})["isolation_profile_id"] = "FixtureProfile"
        spec["source_interface"].update({"path_fields": ["input_path"], "network_required": False,
                                       "entrypoint": {"output_directory_parameter": "output_dir"}})
        spec["input_schema"] = {"type": "object", "additionalProperties": False,
            "properties": {"value": {"type": "integer"}, "input_path": {"type": "string"},
                           "behavior": {"enum": ["normal", "error"]}}, "required": ["value", "input_path", "behavior"]}
        spec["output_schema"] = {"type": "object", "additionalProperties": False,
            "properties": {"value": {"type": "integer"}, "units": {"type": "object"},
                           "artifacts": {"type": "array", "items": {"type": "string"}},
                           "provenance": {"type": "object"}}, "required": ["value", "units", "artifacts", "provenance"]}
        self.spec = spec
        (self.root / "catalog").mkdir(exist_ok=True)
        self.catalog = self.root / "catalog/registry.json"
        self.catalog.write_bytes(real_bridge.json_bytes({"tools": [spec], "skills": []}))
        for name in ("private", "inputs", "outputs"):
            (self.root / name).mkdir()
        (self.root / "inputs/in.txt").write_text("4", encoding="ascii")
        lock = self.root / "requirements.lock"
        lock.write_text("\n".join(spec["metadata"]["upstream"]["requirements"]) + "\n", encoding="ascii")
        python = Path(sys.executable)
        receipt = self.root / "build-receipt.json"
        p = {"tool": "IsolationFixture", "source_root": str(self.root), "private_root": str(self.root / "private"),
             "input_root": str(self.root / "inputs"), "output_root": str(self.root / "outputs"),
             "python": str(python), "python_realpath": str(python.resolve()), "python_prefix": str(Path(sys.prefix).resolve()),
             "python_sha256": real_bridge.sha(python), "python_version": ".".join(map(str, sys.version_info[:3])),
             "worker": str(self.root / shared[4]), "worker_sha256": real_bridge.sha(self.root / shared[4]),
             "module": "isolated_fixture", "callable": "fixture", "catalog": str(self.catalog),
             "catalog_sha256": real_bridge.sha(self.catalog),
             "source_files": {rel: real_bridge.sha(self.root / rel) for rel in shared},
             "requirements": spec["metadata"]["upstream"]["requirements"], "dependency_lock": str(lock),
             "dependency_lock_sha256": real_bridge.sha(lock), "build_receipt": str(receipt),
             "build_receipt_sha256": "", "source_closure_complete": True, "projects": {},
             "artifact_rules": [{"glob": "*.txt", "validator_id": "text_utf8"}], "limits": limits()}
        receipt.write_bytes(real_bridge.json_bytes({"profile_id": "FixtureProfile", "python_version": p["python_version"],
            "python_sha256": p["python_sha256"], "dependency_lock_sha256": p["dependency_lock_sha256"],
            "license_review_complete": True, "source_closure_complete": True, "projects": []}))
        p["build_receipt_sha256"] = real_bridge.sha(receipt)
        self.profile = p
        self.registry = self.root / "profiles.json"
        self.registry.write_bytes(real_bridge.json_bytes({"protocol": real_bridge.PROTOCOL, "profiles": {"FixtureProfile": p}}))
        old_root = source_contracts.ROOT
        self.addCleanup(lambda: setattr(source_contracts, "ROOT", old_root))
        self.addCleanup(source_contracts.catalog.cache_clear)
        source_contracts.ROOT = self.root
        source_contracts.catalog.cache_clear()
        patcher = mock.patch.object(real_bridge, "PROFILE_FILE", self.registry)
        patcher.start()
        self.addCleanup(patcher.stop)
        module_spec = importlib.util.spec_from_file_location("isolated_fixture", self.root / "isolated_fixture.py")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        self.fixture = module.fixture

    def args(self, behavior="normal"):
        return {"value": 7, "input_path": "in.txt", "behavior": behavior}

    def test_canonical_main_to_worker_artifact(self):
        with mock.patch.object(self.contracts, "_dependencies", side_effect=AssertionError("main guard must not check child packages")):
            result = self.fixture(self.args(), output_dir=self.root / "outputs/result")
        self.assertEqual(result["value"], 11)
        self.assertEqual(Path(result["artifacts"][0]).read_text(), "11")
        self.assertEqual(result["provenance"]["installed_versions"], bridge.pin_map(self.profile["requirements"]))
        self.assertEqual(result["provenance"]["output_sha256"]["answer.txt"], hashlib.sha256(b"11").hexdigest())
        self.assertFalse(result["provenance"]["isolation"]["os_sandbox"])
        self.assertEqual((self.root / "inputs/in.txt").read_text(), "4")

    def test_original_error_chain_survives(self):
        with self.assertRaises(self.contracts.ScientificToolError) as caught:
            self.fixture(self.args("error"), output_dir=self.root / "outputs/result")
        self.assertEqual(caught.exception.code, "invalid_arguments")
        self.assertIn("SYNTHETIC_ORIGINAL_ERROR", json.dumps(caught.exception.remote_error))

    def test_tampered_source_rejected(self):
        with (self.root / "isolated_fixture.py").open("a", encoding="utf-8") as handle:
            handle.write("\n# changed\n")
        with self.assertRaises(self.contracts.ScientificToolError) as caught:
            self.fixture(self.args(), output_dir=self.root / "outputs/result")
        self.assertEqual(caught.exception.code, "integrity_error")

    def test_old_nonisolated_path(self):
        del self.spec["registration_metadata"]["runtime"]["isolation_profile_id"]
        self.spec["source_interface"]["entrypoint"] = {}
        self.catalog.write_bytes(bridge.json_bytes({"tools": [self.spec], "skills": []}))
        self.source_contracts.catalog.cache_clear()
        args = self.args()
        args["input_path"] = str(self.root / "inputs/in.txt")
        with mock.patch.object(self.bridge, "invoke", side_effect=AssertionError("non-isolated path changed")):
            result = self.fixture(args)
        self.assertEqual(result["value"], 11)
        self.assertNotIn("isolation", result["provenance"])
        self.assertEqual(result["artifacts"], [])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    log = io.StringIO()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    report = {"scope": "synthetic_windows_or_local_contract_and_IPC_not_science",
        "python": sys.version, "platform": sys.platform, "jsonschema_available": HAS_JSONSCHEMA,
        "executed_including_skips": result.testsRun,
        "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
        "failures": [{"test": str(t), "traceback": text} for t, text in result.failures],
        "errors": [{"test": str(t), "traceback": text} for t, text in result.errors],
        "skipped": [{"test": str(t), "reason": reason} for t, reason in result.skipped],
        "scientific_tests_executed": 0, "remote_tests_executed": 0, "log": log.getvalue()}
    path = AREA / "local-test-report-r1.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=True)
    print(log.getvalue())
    print(json.dumps({key: report[key] for key in ("passed", "jsonschema_available", "scientific_tests_executed")}))
    print("REPORT=" + str(path))
    raise SystemExit(0 if result.wasSuccessful() else 1)

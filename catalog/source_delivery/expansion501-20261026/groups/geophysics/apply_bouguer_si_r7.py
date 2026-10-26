"""One-shot stdlib Bouguer SI boundary edit. No scientific tests or installs.

Reads each edited source/manifest once, preserves the old bytes, and does not
reread or validate written source. Flow gates only source-edit preconditions.
"""
import ast
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path("C:/Users/jona/github/GeoAgent-tools220-release")
GROUP = ROOT / "catalog/source_delivery/expansion501-20261026/groups/geophysics"
REV = GROUP / "acceptance/bouguer-si-r7"
MODULE = ROOT / "geological_agent/geology/expansion501_geophysics.py"
sys.path.insert(0, "C:/Users/jona/.codex/skills/flowing/scripts")
from flowing import task, Flow

TEST_SOURCE = r'''"""Focused unit-boundary regression, not full registration acceptance.

The first class evaluates the actual adapter's conversion expression against
independently derived slab values using a controlled upstream mGal value.
The second calls real Harmonica only when every declared exact pin is present.
No installation, registry replacement or dependency-guard bypass is performed.
"""
import ast
import copy
import hashlib
from importlib import metadata
import json
import math
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[6]
RECORD = json.loads((HERE / "source-edit.json").read_text(encoding="utf-8"))
SOURCE = ROOT / "geological_agent/geology/expansion501_geophysics.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
OWNER = next(node for node in TREE.body
             if isinstance(node, ast.FunctionDef) and node.name == RECORD["function"])
CALLS = [node for node in ast.walk(OWNER) if isinstance(node, ast.Call)
         and ((isinstance(node.func, ast.Attribute) and node.func.attr == "bouguer_correction")
              or (isinstance(node.func, ast.Name) and node.func.id == "bouguer_correction"))]
if len(CALLS) != 1:
    raise AssertionError("Expected the one actual Harmonica Bouguer call")
CALL = CALLS[0]
PARENTS = {child: parent for parent in ast.walk(OWNER) for child in ast.iter_child_nodes(parent)}
BOUNDARY = PARENTS[CALL]
if not (isinstance(BOUNDARY, ast.BinOp) and isinstance(BOUNDARY.op, ast.Mult)
        and BOUNDARY.left is CALL and isinstance(BOUNDARY.right, ast.Constant)
        and BOUNDARY.right.value == 1e-5):
    raise AssertionError("The actual upstream result must cross the mGal-to-SI boundary exactly once")
EXPRESSION = copy.deepcopy(BOUNDARY)
EXPRESSION.left = ast.Name(id="native_mgal", ctx=ast.Load())
EXPRESSION = ast.fix_missing_locations(ast.Expression(body=EXPRESSION))
CONVERSION = compile(EXPRESSION, str(SOURCE), "eval")

# Independent Newtonian slab oracle, in SI. Not obtained from Harmonica output.
G_SI = 6.67430e-11
CASES = (
    ("land_positive", 100.0, 2670.0, 1040.0),
    ("ocean_density_deficit", -100.0, 2670.0, 1040.0),
    ("sea_level_zero", 0.0, 2670.0, 1040.0),
    ("equal_underwater_densities", -100.0, 2670.0, 2670.0),
)


def slab_si(height, crust, water):
    if height >= 0:
        return 2.0 * math.pi * G_SI * crust * height
    return 2.0 * math.pi * G_SI * (water - crust) * abs(height)


def convert(native_mgal):
    return eval(CONVERSION, {"__builtins__": {}}, {"native_mgal": native_mgal})


def assert_case(test, height, crust, water, native_mgal):
    expected = slab_si(height, crust, water)
    actual = float(convert(native_mgal))
    test.assertTrue(math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-15),
                    (actual, expected))
    if height < 0 and crust > water:
        test.assertLess(actual, 0.0)
    if height > 0:
        test.assertGreater(actual, 0.0)


def exact_pin_status():
    problems = []
    pins = {RECORD["upstream_package"]: RECORD["upstream_version"]}
    for requirement in RECORD["requirements"]:
        if "==" in requirement and " " not in requirement and "@" not in requirement:
            package, version = requirement.split("==", 1)
            pins[package] = version
    for package, expected in sorted(pins.items()):
        try:
            actual = metadata.version(package)
        except metadata.PackageNotFoundError:
            actual = "not installed"
        if actual != expected:
            problems.append(package + ": expected " + expected + ", found " + actual)
    return problems


PIN_PROBLEMS = exact_pin_status()


class UnitBoundaryRegression(unittest.TestCase):
    def test_original_upstream_arguments_unchanged(self):
        actual = hashlib.sha256(ast.dump(CALL, include_attributes=False).encode()).hexdigest()
        self.assertEqual(actual, RECORD["original_upstream_call_ast_sha256"])

    def test_land_slab_si(self):
        _, height, crust, water = CASES[0]
        # A controlled native-unit value tests conversion, not a simulated
        # scientific pass. The independent SI expectation is kept unchanged.
        assert_case(self, height, crust, water, slab_si(height, crust, water) / 1e-5)

    def test_ocean_density_difference_negative(self):
        _, height, crust, water = CASES[1]
        assert_case(self, height, crust, water, slab_si(height, crust, water) / 1e-5)

    def test_sea_level(self):
        _, height, crust, water = CASES[2]
        assert_case(self, height, crust, water, 0.0)

    def test_equal_underwater_densities(self):
        _, height, crust, water = CASES[3]
        assert_case(self, height, crust, water, 0.0)


@unittest.skipIf(bool(PIN_PROBLEMS), "Real pinned dependency unavailable: " + "; ".join(PIN_PROBLEMS))
class PinnedHarmonicaBoundary(unittest.TestCase):
    def check_case(self, index):
        import numpy as np
        from harmonica import bouguer_correction
        _, height, crust, water = CASES[index]
        native = bouguer_correction(np.array([height], dtype=float),
                                    density_crust=crust, density_water=water)
        self.assertEqual(native.shape, (1,))
        assert_case(self, height, crust, water, native[0])

    def test_real_land_slab_si(self):
        self.check_case(0)

    def test_real_ocean_density_difference_negative(self):
        self.check_case(1)

    def test_real_sea_level(self):
        self.check_case(2)

    def test_real_equal_underwater_densities(self):
        self.check_case(3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


@task
def prepare_edit():
    if REV.exists():
        raise RuntimeError("Refusing to overwrite an earlier Bouguer r7 revision")
    raw = MODULE.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    content = raw[3:] if bom else raw
    source = content.decode("utf-8")
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and ((isinstance(node.func, ast.Attribute) and node.func.attr == "bouguer_correction")
                  or (isinstance(node.func, ast.Name) and node.func.id == "bouguer_correction"))]
    if len(calls) != 1:
        raise RuntimeError("Expected exactly one reviewed Bouguer call; no edit applied")
    call = calls[0]
    owners = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
              and node.lineno <= call.lineno <= node.end_lineno]
    owner = min(owners, key=lambda node: node.end_lineno - node.lineno)
    ids = [node.args[0].value for node in owner.decorator_list
           if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
           and node.func.id == "operation" and len(node.args) == 1
           and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)]
    if len(ids) != 1 or "Bouguer" not in ids[0]:
        raise RuntimeError("The call is not the assigned decorated Bouguer adapter")
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    ancestor = parents[call]
    while ancestor is not owner:
        if isinstance(ancestor, ast.BinOp) and isinstance(ancestor.op, (ast.Mult, ast.Div)):
            constants = [node.value for node in (ancestor.left, ancestor.right)
                         if isinstance(node, ast.Constant) and isinstance(node.value, (int, float))]
            if any(value in (1e-5, 1e5) for value in constants):
                raise RuntimeError("Unexpected existing unit conversion; stop without editing")
        ancestor = parents[ancestor]
    catalog = json.loads((GROUP / "catalog-additions.json").read_text(encoding="utf-8-sig"))
    specs = [spec for spec in catalog["tools"] if spec["id"] == ids[0]]
    if len(specs) != 1:
        raise RuntimeError("The existing contribution must contain exactly one Bouguer specification")
    spec = specs[0]
    upstream = spec["metadata"]["upstream"]
    if upstream.get("package") != "harmonica":
        raise RuntimeError("Unexpected upstream package; preserve source and ask for review")
    lines = content.splitlines(keepends=True)
    start = sum(map(len, lines[:call.lineno - 1])) + call.col_offset
    end = sum(map(len, lines[:call.end_lineno - 1])) + call.end_col_offset
    original_call = content[start:end]
    replacement = b"(" + original_call + b" * 1e-5)"
    amended = content[:start] + replacement + content[end:]
    if bom:
        amended = b"\xef\xbb\xbf" + amended
    manifest_bytes = (GROUP / "delivery-files.json").read_bytes()
    record = {
        "tool_id": ids[0], "function": owner.name,
        "source_path": MODULE.relative_to(ROOT).as_posix(),
        "edited_call_line_before": call.lineno,
        "upstream_package": upstream["package"], "upstream_version": upstream["version"],
        "requirements": upstream.get("requirements", []),
        "reviewed_source_commit": spec["registration_metadata"].get("source_commit"),
        "original_module_sha256": digest(raw), "authored_module_sha256": digest(amended),
        "original_upstream_call_ast_sha256": digest(ast.dump(call, include_attributes=False).encode()),
        "original_upstream_call": original_call.decode("utf-8"),
        "replacement": replacement.decode("utf-8"),
        "conversion": "mGal * 1e-5 -> existing declared m/s^2",
        "upstream_arguments": "Byte-for-byte unchanged within the original call",
        "source_evidence": "https://www.fatiando.org/harmonica/latest/api/generated/harmonica.bouguer_correction.html",
        "independent_oracle": "Land: 2*pi*G*rho_crust*h. Ocean: 2*pi*G*(rho_water-rho_crust)*abs(h). G=6.67430e-11 SI.",
        "existing_test_expectations_and_tolerances": "Not edited",
        "new_boundary_tolerance": {"relative": 1e-12, "absolute_si": 1e-15},
        "scientific_execution": "not_run",
    }
    return {"ready": True, "before": raw, "after": amended,
            "manifest_bytes": manifest_bytes, "record": record}


@task(depends_on=[prepare_edit], when=lambda prepare_edit: prepare_edit["ready"])
def apply_edit(prepare_edit):
    REV.mkdir(parents=True, exist_ok=False)
    before = REV / "before"
    before.mkdir()
    (before / "expansion501_geophysics.py").write_bytes(prepare_edit["before"])
    (before / "delivery-files.json").write_bytes(prepare_edit["manifest_bytes"])
    MODULE.write_bytes(prepare_edit["after"])
    (REV / "source-edit.json").write_bytes(json_bytes(prepare_edit["record"]))
    (REV / "test_bouguer_si_r7.py").write_text(TEST_SOURCE, encoding="utf-8")
    return prepare_edit


@task(depends_on=[apply_edit])
def publish_source_status(apply_edit):
    record = apply_edit["record"]
    files = [
        "geological_agent/geology/expansion501_geophysics.py",
        (GROUP / "delivery-files.json").relative_to(ROOT).as_posix(),
        (REV / "apply_bouguer_si_r7.py").relative_to(ROOT).as_posix(),
        (REV / "before/expansion501_geophysics.py").relative_to(ROOT).as_posix(),
        (REV / "before/delivery-files.json").relative_to(ROOT).as_posix(),
        (REV / "source-edit.json").relative_to(ROOT).as_posix(),
        (REV / "test_bouguer_si_r7.py").relative_to(ROOT).as_posix(),
        (REV / "source-report.json").relative_to(ROOT).as_posix(),
        (REV / "README.md").relative_to(ROOT).as_posix(),
        (REV / "flow.log").relative_to(ROOT).as_posix(),
    ]
    # The generator itself lives outside the new revision directory, allowing
    # REV's exclusive creation to preserve never-overwritten revision semantics.
    files[2] = (GROUP / "apply_bouguer_si_r7.py").relative_to(ROOT).as_posix()
    manifest = json.loads(apply_edit["manifest_bytes"].decode("utf-8-sig"))
    manifest["files"] = list(dict.fromkeys(manifest["files"] + files))
    (GROUP / "delivery-files.json").write_bytes(json_bytes(manifest))
    report = {
        "revision": "bouguer-si-r7", "tool_id": record["tool_id"],
        "status": "source_stable_source_revised_unverified",
        "formal_eligible": False, "acceptance_pending": True,
        "source_count": 42, "blocked_candidates": 2,
        "newly_registered": 0, "newly_accepted": 0,
        "changed_source": record["source_path"],
        "change": "Multiply actual Harmonica Bouguer mGal return by 1e-5 at the existing adapter boundary.",
        "old_tests_and_failures": "Unchanged; before-source and before-delivery preserved in this revision.",
        "new_test_source": (REV / "test_bouguer_si_r7.py").relative_to(ROOT).as_posix(),
        "new_test_cases_authored": {"unit_boundary": 5, "real_pinned_upstream_boundary": 4},
        "tests_executed_this_revision": 0,
        "unit_boundary_status": "not_run",
        "real_pinned_science_status": "not_run; no available authorized pinned runtime established here",
        "full_decorated_interface_acceptance": "not_run; parent-owned staged v2 route remains pending",
        "scope_exclusions": ["Tesseroid", "Edge", "Eigenfunctions", "superseded v1 diagnostic worker", "shared bridge", "shared registry", "old test assertions"],
        "not_deployed": True, "not_submitted": True, "model_workflow": "not_run",
        "remote_setup_or_upload": False, "install": False, "gpu": False,
        "git_or_push": False, "delivery_files": files,
    }
    (REV / "source-report.json").write_bytes(json_bytes(report))
    (REV / "README.md").write_text(
        "# Bouguer SI boundary correction, r7\n\n"
        "Source-stable, unverified. Existing operation: " + record["tool_id"] + ".\n"
        "The only scientific adapter edit wraps the existing upstream call as\n"
        "(harmonica.bouguer_correction(...) * 1e-5). Native arguments and all\n"
        "height, mass, density and sign conventions are unchanged. Harmonica\n"
        "returns mGal; the existing declared result is SI m/s^2.\n\n"
        "Independent references use 2*pi*G*rho*h on land and\n"
        "2*pi*G*(rho_water-rho_crust)*abs(h) underwater, with G=6.67430e-11 SI.\n"
        "The marine deficit stays negative; zero elevation and equal underwater\n"
        "densities stay zero. Existing SI assertions and tolerances were not edited.\n\n"
        "Five boundary-only tests and four real-pinned-upstream boundary tests\n"
        "were authored. NONE were run in this revision. Boundary test doubles\n"
        "are not scientific acceptance. Real upstream tests explicitly skip\n"
        "when exact declared dependencies are absent; imports are not attempted\n"
        "until the pin gate is satisfied. These focused tests do not certify\n"
        "the full decorated runtime or the parent v2 dispatch path.\n\n"
        "Before-source, before-manifest, original call, hashes and exact declared\n"
        "requirements are retained in before/ and source-edit.json. Historical\n"
        "r1 failures and the superseded v1 invalid-JSON failure remain untouched.\n"
        "No Tesseroid/Edge/Eigenfunction change, install, remote operation,\n"
        "GPU/model use, deployment, Git operation or push was performed.\n",
        encoding="utf-8")
    return report


def main():
    log = io.StringIO()
    flow = Flow(publish_source_status, max_workers=1, fail_fast=True)
    with contextlib.redirect_stdout(log):
        flow.run()
        flow.summary()
    # This is a source materialization log, NOT a scientific test result.
    (REV / "flow.log").write_text(log.getvalue(), encoding="utf-8")
    print(log.getvalue())
    print(json.dumps(flow.value(publish_source_status), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


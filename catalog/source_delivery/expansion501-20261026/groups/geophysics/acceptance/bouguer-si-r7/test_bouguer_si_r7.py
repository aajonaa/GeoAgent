"""Focused unit-boundary regression, not full registration acceptance.

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

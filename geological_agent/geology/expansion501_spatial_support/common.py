"""Private-worker building blocks, not a main-runtime dependency bypass.

The parent must bind a reviewed isolated profile before these pending kernels
are eligible for catalog registration. No installer or remote transport exists.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
GROUP = ROOT / "catalog/source_delivery/expansion501-20261026/groups/spatial"
MAX_BYTES = 4_000_000


class ContractError(ValueError):
    def __init__(self, message, code="invalid_arguments"):
        super().__init__(message)
        self.code = code


def fail(message, code="invalid_arguments"):
    raise ContractError(message, code)


def finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        fail("Non-finite data are not NoData")
    if isinstance(value, dict):
        for item in value.values():
            finite(item)
    if isinstance(value, (list, tuple)):
        for item in value:
            finite(item)


def exact(requirements):
    if sys.version_info[:2] != (3, 12):
        fail("The reviewed private interpreter is Python 3.12", "incompatible_dependency")
    installed = {}
    for requirement in requirements:
        package, version = requirement.split("==")
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            fail("Missing reviewed private dependency: " + requirement, "missing_dependency")
        if actual != version:
            fail("Private interpreter requires " + requirement + "; found " + actual,
                 "incompatible_dependency")
        installed[package] = actual
    return installed


def guard(tool_id, args):
    finite(args)
    if not isinstance(args, dict) or len(json.dumps(args, allow_nan=False).encode()) > MAX_BYTES:
        fail("Expected a bounded argument object")
    spec = json.loads((GROUP / "pending-contracts.json").read_text(encoding="utf-8"))[tool_id]
    exact(spec["requirements"])
    from jsonschema import Draft202012Validator
    Draft202012Validator(spec["input_schema"]).validate(args)
    return spec


def crs(value):
    from pyproj import CRS
    c = CRS.from_user_input(value)
    if not c.is_projected or len(c.axis_info) != 2:
        fail("A two-dimensional projected metric CRS is required")
    if [v.direction for v in c.axis_info] != ["east", "north"] or any(
        not math.isclose(v.unit_conversion_factor, 1.0, abs_tol=1e-12)
        for v in c.axis_info
    ):
        fail("CRS must use easting/northing in metres; no implicit reprojection")
    return c.to_string()


def array(value, shape=None, low=None, high=None):
    import numpy as np
    a = np.asarray(value, dtype=float)
    if a.size == 0 or a.size > 16384 or not np.isfinite(a).all():
        fail("Invalid finite array or resource limit")
    if shape is not None and a.shape != tuple(shape):
        fail("Array shape mismatch")
    if low is not None and np.any(a < low):
        fail("Array below physical domain")
    if high is not None and np.any(a > high):
        fail("Array above physical domain")
    return a


def grid_info(args, shape):
    crs(args["crs"])
    if len(shape) != 2 or min(shape) < 3 or max(shape) > 64:
        fail("Grid must be 3..64 by 3..64")
    x, y = args["origin_xy_m"]
    d = args["cell_size_m"]
    return dict(crs=args["crs"], shape=list(shape), origin_xy_m=[x, y],
                cell_size_m=d, affine=[d, 0, x, 0, -d, y],
                row_order="north_to_south", nodata=None)


def raster_grid(args, field):
    import numpy as np
    from landlab import RasterModelGrid
    a = array(args[field])
    meta = grid_info(args, a.shape)
    d = args["cell_size_m"]
    x, y = args["origin_xy_m"]
    g = RasterModelGrid(a.shape, xy_spacing=d,
                       xy_of_lower_left=(x + d / 2, y - (a.shape[0] - .5) * d))
    return g, a, meta


def node_field(grid, name, north_up):
    import numpy as np
    grid.add_field(name, np.flipud(north_up).ravel().copy(), at="node")


def raster(grid, name):
    import numpy as np
    a = grid.at_node[name]
    if not np.isfinite(a).all():
        fail("Upstream returned a non-finite field: " + name, "invalid_result")
    return np.flipud(a.reshape(grid.shape)).tolist()


def links_xy(grid):
    return [[[float(grid.x_of_node[u]), float(grid.y_of_node[u])],
             [float(grid.x_of_node[v]), float(grid.y_of_node[v])]]
            for u, v in grid.nodes_at_link]


def artifact(root, name, content, media_type):
    root = Path(root)
    if root.is_symlink() or not root.is_dir() or Path(name).name != name:
        fail("Expected private artifact directory and fixed filename", "invalid_path")
    if len(content) > 64 * 1024 * 1024:
        fail("Artifact byte limit", "resource_limit")
    destination = root / name
    with destination.open("xb") as stream:
        stream.write(content)
    return dict(name=name, bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
                media_type=media_type)


def finish(tool_id, result):
    finite(result)
    if len(json.dumps(result, allow_nan=False).encode()) > MAX_BYTES:
        fail("Typed response exceeds 4 MB", "resource_limit")
    return result

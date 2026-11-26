"""Thirty bounded spatial adapters. Source authored; NOT TESTED / NOT DEPLOYED.

The parent integrates catalog definitions before normal invocation. No runtime
registry edits, downloads, subprocesses, or caller-selected functions occur here.
JSON files declare their source, CRS, units, grid origin, and every invalid cell.
"""
from pathlib import Path
import math

from jsonschema import Draft202012Validator

from geological_agent.geology.collection_contracts import operation, reject
from legacy.ToolsAgent.ToolsFuns.source_contracts import decode, definition, finite


def _load(args, name):
    path = Path(args["data_path"])
    if path.suffix.lower() != ".json":
        reject("Scientific input must be a UTF-8 JSON file", "invalid_input")
    if path.stat().st_size > 262144:
        reject("Scientific JSON exceeds 256 KiB", "resource_limit")
    d = decode(path.read_text(encoding="utf-8"))
    finite(d)
    Draft202012Validator(definition(name)["metadata"]["scientific_contract"]["data_schema"]).validate(d)
    if not d["source"]["citation"].strip():
        reject("A nonblank caller-declared source citation is required")
    _crs(d["crs"], geographic=d["coordinate_unit"] == "degree")
    return d


def _crs(value, geographic=False):
    from pyproj import CRS
    c = CRS.from_user_input(value)
    if geographic:
        if c != CRS.from_epsg(4326):
            reject("Longitude/latitude input must explicitly use EPSG:4326")
    elif not c.is_projected or len(c.axis_info) != 2 or any(
        abs(a.unit_conversion_factor - 1.0) > 1e-12 for a in c.axis_info
    ):
        reject("Planar inputs require a two-dimensional projected CRS in metres")
    return c


def _result(d, data, value_unit, secondary="not_applicable"):
    # These are fixed adapter-owned result fields, not caller-selected functions.
    # Keep the same explicit grid contract on arrays and row/column paths.
    grid_fields = {"values", "filled_m", "hand_m", "distance_steps",
                   "longest_upstream_steps", "order", "path_rc", "cost_s",
                   "distance_m", "excess_cost_s"}
    reprojected = "dst_crs" in data
    if grid_fields.intersection(data):
        prefix = "dst_" if reprojected else ""
        if reprojected:
            shape = d["dst_shape"]
        elif "shape" in d:
            shape = d["shape"]
        else:
            shape = [len(d["values"]), len(d["values"][0])]
        data = {**data, "origin_xy": list(d[prefix + "origin_xy"]),
                "cell_size_m": d[prefix + "cell_size_m"],
                "affine": list(_affine(d, prefix))[:6], "shape": list(shape)}
    result = {"data": data, "crs": d["dst_crs"] if reprojected else d["crs"],
              "source": d["source"],
              "units": {"coordinates": d["coordinate_unit"], "value": value_unit,
                        "secondary": secondary}}
    if reprojected:
        result["source_crs"] = d["crs"]
    return result


def _grid(d, full=False):
    import numpy as np
    values, mask = d["values"], d["valid_mask"]
    widths = {len(row) for row in values}
    if len(widths) != 1 or len(mask) != len(values) or any(len(r) != len(values[0]) for r in mask):
        reject("Values and valid_mask must be rectangular and identically shaped")
    if len(values) * len(values[0]) > 4096:
        reject("Raster exceeds 4096 cells", "resource_limit")
    for row, valid in zip(values, mask):
        if any((v is None) == ok for v, ok in zip(row, valid)):
            reject("Exactly the invalid cells must contain JSON null; no implicit NoData")
    a = np.asarray(values, dtype=float)
    m = np.asarray(mask, dtype=bool)
    if not m.any():
        reject("Raster has no valid cells", "empty_input")
    if full and not m.all():
        reject("This drainage operation requires complete terrain; no missing-cell filling", "unsupported_conditions")
    if not np.isfinite(a[m]).all():
        reject("All valid values must be finite")
    return a, m


def _matrix(a, valid=None):
    import numpy as np
    a = np.asarray(a)
    good = np.isfinite(a) if valid is None else np.asarray(valid) & np.isfinite(a)
    return [[float(v) if ok else None for v, ok in zip(row, mr)] for row, mr in zip(a, good)]


def _affine(d, prefix=""):
    from rasterio.transform import from_origin
    x, y = d[prefix + "origin_xy"]
    s = d[prefix + "cell_size_m"]
    return from_origin(x, y, s, s)


def _polygon(text):
    import shapely
    g = shapely.from_wkt(text)
    if g.geom_type not in ("Polygon", "MultiPolygon") or g.is_empty or not g.is_valid or g.has_z or shapely.has_m(g):
        reject("Expected a nonempty valid 2D polygon; no automatic repair")
    if shapely.get_num_coordinates(g) > 1024:
        reject("Polygon exceeds 1024 vertices", "resource_limit")
    return g


def _geos_312():
    import shapely
    if shapely.geos_version < (3, 12, 0):
        reject("This topology operation requires GEOS >= 3.12", "incompatible_dependency")


@operation("GeoSpatialRasterReproject")
def raster_reproject(args):
    import numpy as np
    from rasterio.warp import reproject, Resampling
    from pyproj import CRS
    d = _load(args, "GeoSpatialRasterReproject")
    a, m = _grid(d)
    src, dst = _crs(d["crs"]), _crs(d["dst_crs"])
    wgs = CRS.from_epsg(4326)
    if not src.geodetic_crs.equals(wgs, ignore_axis_order=True) or not dst.geodetic_crs.equals(wgs, ignore_axis_order=True):
        reject("Offline warp is restricted to WGS84-based projected CRSs; datum grids are not fetched", "unsupported_conditions")
    h, w = d["dst_shape"]
    if h * w > 4096:
        reject("Target raster exceeds 4096 cells", "resource_limit")
    target = np.full((h, w), np.nan)
    reproject(source=np.where(m, a, np.nan), destination=target,
              src_transform=_affine(d), src_crs=src, src_nodata=np.nan,
              dst_transform=_affine(d, "dst_"), dst_crs=dst, dst_nodata=np.nan,
              resampling=Resampling.nearest, num_threads=1, init_dest_nodata=True)
    return _result(d, {"values": _matrix(target), "valid_mask": np.isfinite(target).tolist(),
                      "dst_crs": d["dst_crs"], "origin_xy": d["dst_origin_xy"],
                      "cell_size_m": d["dst_cell_size_m"]}, d["value_unit"])


@operation("GeoSpatialPolygonRasterize")
def polygon_rasterize(args):
    import numpy as np
    from rasterio.features import rasterize
    from shapely.geometry import mapping
    d = _load(args, "GeoSpatialPolygonRasterize")
    polygons = [_polygon(x) for x in d["polygons_wkt"]]
    if len(polygons) != len(d["class_ids"]) or len(set(d["class_ids"])) != len(polygons):
        reject("Each polygon needs one distinct positive class ID")
    mask = np.asarray(d["valid_mask"], dtype=bool)
    if tuple(mask.shape) != tuple(d["shape"]) or mask.size > 4096 or not mask.any():
        reject("Target mask must match the bounded, nonempty requested shape")
    a = rasterize([(mapping(p), v) for p, v in zip(polygons, d["class_ids"])],
                  out_shape=tuple(d["shape"]), transform=_affine(d), fill=0,
                  all_touched=d["all_touched"], dtype="int32")
    return _result(d, {"values": _matrix(a, mask), "valid_mask": mask.tolist(),
                      "origin_xy": d["origin_xy"], "cell_size_m": d["cell_size_m"]}, "class_id")


@operation("GeoSpatialRasterPolygonize")
def raster_polygonize(args):
    import numpy as np
    from rasterio.features import shapes
    from shapely.geometry import shape
    d = _load(args, "GeoSpatialRasterPolygonize")
    a, m = _grid(d)
    if np.any(a[m] != np.floor(a[m])) or np.any(abs(a[m]) > 2147483647):
        reject("Class raster values must be signed int32 integers")
    features = []
    for g, value in shapes(np.where(m, a, 0).astype("int32"), mask=m,
                           connectivity=4, transform=_affine(d)):
        p = shape(g)
        features.append({"class_id": int(value), "wkt": p.wkt, "area_m2": float(p.area)})
    return _result(d, {"features": features}, "class_id", "m2")


@operation("GeoSpatialPolygonIntersection")
def polygon_intersection(args):
    import shapely
    d = _load(args, "GeoSpatialPolygonIntersection")
    g = shapely.intersection(_polygon(d["polygon_a_wkt"]), _polygon(d["polygon_b_wkt"]))
    return _result(d, {"wkt": g.wkt, "area_m2": float(g.area)}, "m2")


@operation("GeoSpatialCoverageUnion")
def coverage_union(args):
    import shapely
    d = _load(args, "GeoSpatialCoverageUnion")
    _geos_312()
    polygons = [_polygon(x) for x in d["polygons_wkt"]]
    if not bool(shapely.coverage_is_valid(polygons)):
        reject("Coverage must have matching shared edges and nonoverlapping interiors")
    g = shapely.coverage_union_all(polygons)
    return _result(d, {"wkt": g.wkt, "area_m2": float(g.area)}, "m2")


@operation("GeoSpatialConstrainedTriangulation")
def constrained_triangulation(args):
    import shapely
    d = _load(args, "GeoSpatialConstrainedTriangulation")
    _geos_312()
    g = shapely.constrained_delaunay_triangles(_polygon(d["polygon_wkt"]))
    return _result(d, {"triangles_wkt": [p.wkt for p in g.geoms],
                      "areas_m2": [float(p.area) for p in g.geoms]}, "m2")


def _pysheds(d, a, nodata=math.nan):
    from pysheds.grid import Grid
    from pysheds.sview import Raster, ViewFinder
    vf = ViewFinder(affine=_affine(d), shape=a.shape, crs=_crs(d["crs"]), nodata=nodata)
    return Grid(viewfinder=vf), Raster(a.copy(), viewfinder=vf)


_D8 = {64: (-1, 0), 128: (-1, 1), 1: (0, 1), 2: (1, 1),
       4: (1, 0), 8: (1, -1), 16: (0, -1), 32: (-1, -1)}


def _flow(d, a):
    import numpy as np
    if min(a.shape) < 3 or not np.isin(a, [0, *_D8]).all() or not (a > 0).any():
        reject("A nonempty D8 graph needs a >=3x3 grid and codes 0,1,2,4,8,16,32,64,128")
    if (a[0] != 0).any() or (a[-1] != 0).any() or (a[:, 0] != 0).any() or (a[:, -1] != 0).any():
        reject("Pysheds requires an explicit zero-direction rim; boundary routing is unsupported")
    successors, active = {}, np.zeros(a.shape, dtype=bool)
    for r, c in zip(*np.nonzero(a)):
        dr, dc = _D8[int(a[r, c])]
        rr, cc = int(r + dr), int(c + dc)
        if not (0 < rr < a.shape[0] - 1 and 0 < cc < a.shape[1] - 1):
            reject("Flow may not enter the rim; supply an interior terminal cell")
        successors[(int(r), int(c))] = (rr, cc)
        active[r, c] = active[rr, cc] = True
    done = set()
    for start in successors:
        chain, p = set(), start
        while p in successors and p not in done:
            if p in chain:
                reject("D8 routing contains a directed cycle")
            chain.add(p)
            p = successors[p]
        done.update(chain)
    return active, successors


def _cell(point, shape, valid):
    r, c = point
    if not (0 <= r < shape[0] and 0 <= c < shape[1]) or not valid[r, c]:
        reject("A requested row,column cell is outside the valid raster")
    return r * shape[1] + c


@operation("GeoSpatialDepressionFill")
def depression_fill(args):
    import numpy as np
    d = _load(args, "GeoSpatialDepressionFill")
    a, m = _grid(d, full=True)
    if min(a.shape) < 3:
        reject("Depression analysis needs at least a 3x3 complete DEM")
    grid, dem = _pysheds(d, a)
    filled = np.asarray(grid.fill_depressions(dem))
    depth = filled - a
    return _result(d, {"filled_m": _matrix(filled), "fill_depth_m": _matrix(depth),
                      "fill_volume_m3": float(depth.sum() * d["cell_size_m"] ** 2)}, "m", "m3")


@operation("GeoSpatialHeightAboveDrainage")
def height_above_drainage(args):
    import numpy as np
    d = _load(args, "GeoSpatialHeightAboveDrainage")
    dem, _ = _grid(d, full=True)
    f = np.asarray(d["directions"], dtype=float)
    if f.shape != dem.shape:
        reject("DEM and direction shapes must agree")
    active, successors = _flow(d, f)
    channel = np.asarray(d["channels"], dtype=bool)
    if channel.shape != dem.shape or not channel.any() or (channel & ~active).any():
        reject("Channels must be a nonempty subset of the interior routing graph")
    if any(dem[p] < dem[q] for p, q in successors.items()):
        reject("HAND requires nonascending downstream elevations; terrain is not conditioned implicitly")
    grid, dr = _pysheds(d, dem)
    _, fr = _pysheds(d, f.astype("int64"), nodata=-9999)
    _, mr = _pysheds(d, channel, nodata=False)
    hand = np.asarray(grid.compute_hand(fr, dr, mr, routing="d8", algorithm="iterative"))
    return _result(d, {"hand_m": _matrix(hand, active),
                      "reachable_mask": (active & np.isfinite(hand)).tolist()}, "m")


@operation("GeoSpatialDistanceToOutlet")
def distance_to_outlet(args):
    import numpy as np
    d = _load(args, "GeoSpatialDistanceToOutlet")
    a, _ = _grid(d, full=True)
    active, _ = _flow(d, a)
    _cell(d["outlet_rc"], a.shape, active)
    grid, fr = _pysheds(d, a.astype("int64"), nodata=-9999)
    r, c = d["outlet_rc"]
    result = grid.distance_to_outlet(c, r, fr, xytype="index", routing="d8", algorithm="iterative")
    return _result(d, {"distance_steps": _matrix(result, active)}, "D8_steps")


@operation("GeoSpatialDistanceToRidge")
def distance_to_ridge(args):
    d = _load(args, "GeoSpatialDistanceToRidge")
    a, _ = _grid(d, full=True)
    active, _ = _flow(d, a)
    grid, fr = _pysheds(d, a.astype("int64"), nodata=-9999)
    result = grid.distance_to_ridge(fr, routing="d8", algorithm="iterative")
    return _result(d, {"longest_upstream_steps": _matrix(result, active)}, "D8_steps")


@operation("GeoSpatialStrahlerOrder")
def strahler_order(args):
    import numpy as np
    import pyflwdir
    d = _load(args, "GeoSpatialStrahlerOrder")
    a, _ = _grid(d, full=True)
    active, successors = _flow(d, a)
    mask = np.asarray(d["channels"], dtype=bool)
    if mask.shape != a.shape or not mask.any() or (mask & ~active).any():
        reject("Channel mask must select a nonempty subset of the routing graph")
    if any(mask[p] and not mask[q] for p, q in successors.items()):
        reject("Selected channel graph must be downstream-connected to its terminal cells")
    # PyFlwDir handles zero-direction terminal self-receivers without a
    # spurious order increment, and handles >2 inflowing tributaries.
    # _flow already validated codes, interior bounds and acyclicity.
    flow = pyflwdir.from_array(a.astype("uint8"), ftype="d8",
                              transform=_affine(d), latlon=False, cache=False)
    order = flow.stream_order(type="strahler", mask=mask)
    return _result(d, {"order": _matrix(order, mask)}, "Strahler_order")


@operation("GeoSpatialTerrainContours")
def terrain_contours(args):
    from skimage.measure import find_contours
    d = _load(args, "GeoSpatialTerrainContours")
    a, mask = _grid(d)
    if min(a.shape) < 2 or d["levels_m"] != sorted(set(d["levels_m"])):
        reject("Contours need >=2x2 terrain and strictly increasing unique levels")
    lines, vertices = [], 0
    x, y = d["origin_xy"]
    s = d["cell_size_m"]
    for level in d["levels_m"]:
        for line in find_contours(a, level=level, fully_connected="low", positive_orientation="low", mask=mask):
            vertices += len(line)
            if vertices > 32768:
                reject("Contour output exceeds 32768 vertices", "resource_limit")
            lines.append({"level_m": level, "coordinates": [[float(x + (c + .5) * s),
                          float(y - (r + .5) * s)] for r, c in line]})
    return _result(d, {"lines": lines}, "m")


def _weights(d):
    import numpy as np
    from libpysal.weights import DistanceBand
    xy = np.asarray(d["points_xy"], dtype=float)
    v = np.asarray(d["values"], dtype=float)
    if len(xy) != len(v) or len({tuple(p) for p in d["points_xy"]}) != len(xy):
        reject("One value per distinct point is required; no duplicate aggregation")
    if np.std(v) == 0:
        reject("Spatial association requires a nonconstant variable")
    w = DistanceBand(xy, threshold=d["radius_m"], binary=True, silence_warnings=True)
    if w.islands:
        reject("Distance-band graph has islands; enlarge the explicit radius or revise the dataset")
    return v, w


@operation("GeoSpatialLocalMoran")
def local_moran(args):
    from esda import Moran_Local
    d = _load(args, "GeoSpatialLocalMoran")
    v, w = _weights(d)
    r = Moran_Local(v, w, transformation="r", permutations=0, n_jobs=1, keep_simulations=False)
    return _result(d, {"local_i": r.Is.tolist(), "quadrant": r.q.tolist(), "inference": "not_computed"}, "dimensionless")


@operation("GeoSpatialBivariateLocalMoran")
def bivariate_local_moran(args):
    import numpy as np
    from esda import Moran_Local_BV
    d = _load(args, "GeoSpatialBivariateLocalMoran")
    v, w = _weights(d)
    other = np.asarray(d["other_values"], dtype=float)
    if len(other) != len(v) or np.std(other) == 0:
        reject("Second variable must align and be nonconstant")
    r = Moran_Local_BV(v, other, w, transformation="r", permutations=0, n_jobs=1, keep_simulations=False)
    return _result(d, {"local_i": r.Is.tolist(), "quadrant": r.q.tolist(), "inference": "not_computed"}, "dimensionless")


@operation("GeoSpatialLocalGetisOrd")
def local_getis_ord(args):
    from esda import G_Local
    d = _load(args, "GeoSpatialLocalGetisOrd")
    v, w = _weights(d)
    if (v <= 0).any():
        reject("This Gi profile requires strictly positive observations")
    r = G_Local(v, w, transform="B", permutations=0, star=False, n_jobs=1, keep_simulations=False)
    return _result(d, {"gi": r.Gs.tolist(), "inference": "not_computed"}, "dimensionless")


@operation("GeoSpatialGlobalGeary")
def global_geary(args):
    from esda import Geary
    d = _load(args, "GeoSpatialGlobalGeary")
    v, w = _weights(d)
    r = Geary(v, w, transformation="r", permutations=0)
    return _result(d, {"geary_c": float(r.C), "inference": "not_computed"}, "dimensionless")


@operation("GeoSpatialBinaryJoinCounts")
def binary_join_counts(args):
    import numpy as np
    from esda import Join_Counts
    d = _load(args, "GeoSpatialBinaryJoinCounts")
    v, w = _weights(d)
    if not np.isin(v, [0, 1]).all():
        reject("Join counts require explicit binary 0/1 observations")
    r = Join_Counts(v, w, permutations=0)
    return _result(d, {"black_black": float(r.bb), "white_white": float(r.ww),
                      "mixed": float(r.bw), "total_edges": float(r.J), "inference": "not_computed"}, "edge_count")


@operation("GeoSpatialLocalGeary")
def local_geary(args):
    from esda import Geary_Local
    d = _load(args, "GeoSpatialLocalGeary")
    v, w = _weights(d)
    r = Geary_Local(connectivity=w, labels=False, permutations=0, n_jobs=1, keep_simulations=False).fit(v)
    return _result(d, {"local_c": r.localG.tolist(), "inference": "not_computed"}, "dimensionless")


def _cost_graph(d, capacity=False):
    import numpy as np
    from scipy.sparse import csr_matrix
    a, m = _grid(d)
    if (a[m] <= 0).any():
        reject("Valid resistance/capacity values must be strictly positive; barriers use the mask")
    if capacity and (np.any(a[m] != np.floor(a[m])) or (a[m] > 1000000).any()):
        reject("Capacity values must be integers in [1,1000000]")
    rows, cols, costs = [], [], []
    for r, c in zip(*np.nonzero(m)):
        for rr, cc in ((r + 1, c), (r, c + 1)):
            if rr < a.shape[0] and cc < a.shape[1] and m[rr, cc]:
                i, j = int(r * a.shape[1] + c), int(rr * a.shape[1] + cc)
                value = min(a[r, c], a[rr, cc]) if capacity else (a[r, c] + a[rr, cc]) * .5 * d["cell_size_m"]
                rows.extend((i, j)); cols.extend((j, i)); costs.extend((value, value))
    graph = csr_matrix((np.asarray(costs, dtype="int64" if capacity else float), (rows, cols)), shape=(a.size, a.size))
    return a, m, graph


def _endpoints(d, a, m):
    start, end = _cell(d["start_rc"], a.shape, m), _cell(d["end_rc"], a.shape, m)
    if start == end:
        reject("Start and end must be distinct valid cells")
    return start, end


@operation("GeoSpatialLeastCostPath")
def least_cost_path(args):
    import numpy as np
    from skimage.graph import route_through_array
    d = _load(args, "GeoSpatialLeastCostPath")
    a, m = _grid(d)
    _endpoints(d, a, m)
    if (a[m] <= 0).any():
        reject("Traversable cell costs must be positive seconds per metre")
    path, cost = route_through_array(np.where(m, a, np.inf), tuple(d["start_rc"]),
                                    tuple(d["end_rc"]), fully_connected=False, geometric=True)
    if not math.isfinite(cost):
        reject("No traversable route connects the requested cells", "unsupported_conditions")
    return _result(d, {"path_rc": [[int(r), int(c)] for r, c in path],
                      "cost_s": float(cost * d["cell_size_m"])}, "s", "row_column_index")


@operation("GeoSpatialCostAllocation")
def cost_allocation(args):
    import numpy as np
    from scipy.sparse.csgraph import dijkstra
    d = _load(args, "GeoSpatialCostAllocation")
    a, m, graph = _cost_graph(d)
    sources = [_cell(p, a.shape, m) for p in d["sources_rc"]]
    if len(set(sources)) != len(sources):
        reject("Source cells must be distinct")
    distances = dijkstra(graph, directed=False, indices=sources)
    owners = np.argmin(distances, axis=0)
    costs = distances[owners, np.arange(a.size)].reshape(a.shape)
    good = m & np.isfinite(costs)
    return _result(d, {"cost_s": _matrix(costs, good),
                      "owner_index": _matrix(owners.reshape(a.shape), good)}, "s", "zero_based_source_index")


@operation("GeoSpatialEuclideanProximity")
def euclidean_proximity(args):
    import numpy as np
    from scipy.ndimage import distance_transform_edt
    d = _load(args, "GeoSpatialEuclideanProximity")
    a, m = _grid(d)
    if not np.isin(a[m], [0, 1]).all() or not (a[m] == 1).any():
        reject("Proximity requires a binary target grid with at least one valid target")
    targets = m & (a == 1)
    distances = distance_transform_edt(~targets, sampling=d["cell_size_m"])
    return _result(d, {"distance_m": _matrix(distances, m)}, "m")


@operation("GeoSpatialResistanceDistance")
def resistance_distance(args):
    import numpy as np
    from scipy.sparse.csgraph import connected_components, laplacian
    from scipy.linalg import pinvh
    d = _load(args, "GeoSpatialResistanceDistance")
    a, m, graph = _cost_graph(d)
    if a.size > 256:
        reject("Dense resistance solve is limited to 256 raster cells", "resource_limit")
    s, t = _endpoints(d, a, m)
    _, labels = connected_components(graph, directed=False)
    if labels[s] != labels[t]:
        reject("Effective resistance is undefined between disconnected components", "unsupported_conditions")
    nodes = np.flatnonzero(labels == labels[s])
    conductance = graph[nodes][:, nodes].copy()
    conductance.data = 1.0 / conductance.data
    inverse = pinvh(laplacian(conductance).toarray(), check_finite=True)
    i, j = int(np.flatnonzero(nodes == s)[0]), int(np.flatnonzero(nodes == t)[0])
    value = float(inverse[i, i] + inverse[j, j] - 2 * inverse[i, j])
    return _result(d, {"effective_resistance_s": value, "connected_cells": len(nodes)}, "s_network_resistance")


@operation("GeoSpatialCostCorridor")
def cost_corridor(args):
    import numpy as np
    from scipy.sparse.csgraph import dijkstra
    d = _load(args, "GeoSpatialCostCorridor")
    a, m, graph = _cost_graph(d)
    s, t = _endpoints(d, a, m)
    distances = dijkstra(graph, directed=False, indices=[s, t])
    best = float(distances[0, t])
    if not math.isfinite(best):
        reject("No traversable corridor connects endpoints", "unsupported_conditions")
    excess = np.maximum(distances[0] + distances[1] - best, 0).reshape(a.shape)
    good = m & np.isfinite(excess)
    return _result(d, {"excess_cost_s": _matrix(excess, good),
                      "corridor_mask": (good & (excess <= d["max_excess_s"])).tolist(),
                      "optimal_cost_s": best}, "s")


@operation("GeoSpatialCapacityMaxFlow")
def capacity_max_flow(args):
    from scipy.sparse.csgraph import maximum_flow
    d = _load(args, "GeoSpatialCapacityMaxFlow")
    a, m, graph = _cost_graph(d, capacity=True)
    s, t = _endpoints(d, a, m)
    r = maximum_flow(graph, s, t, method="dinic")
    return _result(d, {"maximum_flow_tonne_day": int(r.flow_value),
                      "capacity_model": "four_neighbor_edge_minimum_of_endpoint_capacities"}, "tonne/day")


def _lonlat(points):
    if any(not (-180 <= x <= 180 and -90 <= y <= 90) for x, y in points):
        reject("Geographic coordinates must be longitude,latitude in WGS84 degrees")


@operation("GeoSpatialEllipsoidalPolygonArea")
def ellipsoidal_polygon_area(args):
    from pyproj import Geod
    d = _load(args, "GeoSpatialEllipsoidalPolygonArea")
    p = _polygon(d["polygon_wkt"])
    if p.geom_type != "Polygon" or p.interiors:
        reject("This area profile accepts a single simple exterior ring without holes")
    points = list(p.exterior.coords)
    _lonlat(points)
    if max(x for x, _ in points) - min(x for x, _ in points) >= 180:
        reject("Polygon must span less than 180 degrees longitude; split wrapping regions explicitly")
    area, perimeter = Geod(ellps="WGS84").polygon_area_perimeter(*zip(*points))
    return _result(d, {"signed_area_m2": float(area), "perimeter_m": float(perimeter)}, "m2", "m")


@operation("GeoSpatialGeodesicTransect")
def geodesic_transect(args):
    from pyproj import Geod
    d = _load(args, "GeoSpatialGeodesicTransect")
    p, q = d["start_lonlat"], d["end_lonlat"]
    _lonlat([p, q])
    if p == q or (abs(abs(p[0] - q[0]) - 180) < 1e-10 and abs(p[1] + q[1]) < 1e-10):
        reject("Coincident or antipodal endpoints do not define this unique transect")
    geod = Geod(ellps="WGS84")
    _, _, distance = geod.inv(*p, *q)
    if distance <= 0:
        reject("Endpoints identify the same geographic location")
    interior = geod.npts(*p, *q, d["interior_points"])
    return _result(d, {"points_lonlat": [p, *[list(x) for x in interior], q], "length_m": float(distance)}, "m", "degree")


@operation("GeoSpatialProjectionDistortion")
def projection_distortion(args):
    from pyproj import Proj, CRS
    d = _load(args, "GeoSpatialProjectionDistortion")
    c = _crs(d["projection_crs"])
    if not c.geodetic_crs.equals(CRS.from_epsg(4326), ignore_axis_order=True):
        reject("Projection factors require a WGS84-based projected CRS")
    _lonlat(d["points_lonlat"])
    lon, lat = zip(*d["points_lonlat"])
    f = Proj(c).get_factors(lon, lat, radians=False, errcheck=True)
    return _result(d, {"meridional_scale": list(f.meridional_scale), "parallel_scale": list(f.parallel_scale),
                      "areal_scale": list(f.areal_scale), "angular_distortion_degrees": list(f.angular_distortion),
                      "meridian_convergence_degrees": list(f.meridian_convergence)}, "dimensionless", "degree")


@operation("GeoSpatialMaximumInscribedCircle")
def maximum_inscribed_circle(args):
    import shapely
    d = _load(args, "GeoSpatialMaximumInscribedCircle")
    _geos_312()
    p = _polygon(d["polygon_wkt"])
    if d["tolerance_m"] >= min(p.bounds[2] - p.bounds[0], p.bounds[3] - p.bounds[1]):
        reject("Search tolerance must be smaller than both polygon dimensions")
    line = shapely.maximum_inscribed_circle(p, tolerance=d["tolerance_m"])
    return _result(d, {"center_xy": list(line.coords[0]), "boundary_xy": list(line.coords[1]),
                      "radius_m": float(line.length), "tolerance_m": d["tolerance_m"]}, "m")


@operation("GeoSpatialSiteVoronoi")
def site_voronoi(args):
    import shapely
    from shapely.geometry import MultiPoint, Point
    d = _load(args, "GeoSpatialSiteVoronoi")
    _geos_312()
    region = _polygon(d["polygon_wkt"])
    points = d["points_xy"]
    if len({tuple(p) for p in points}) != len(points) or any(not region.covers(Point(p)) for p in points):
        reject("Distinct site points must be covered by the declared clipping region")
    cells = shapely.voronoi_polygons(MultiPoint(points), extend_to=region, ordered=True)
    clipped = [shapely.intersection(p, region) for p in cells.geoms]
    return _result(d, {"cells_wkt": [p.wkt for p in clipped], "areas_m2": [float(p.area) for p in clipped]}, "m2")


@operation("GeoSpatialSiteParcelSplit")
def site_parcel_split(args):
    import shapely
    from shapely.ops import split
    d = _load(args, "GeoSpatialSiteParcelSplit")
    polygon = _polygon(d["polygon_wkt"])
    line = shapely.from_wkt(d["splitter_wkt"])
    if line.geom_type != "LineString" or line.is_empty or not line.is_simple or line.has_z or shapely.has_m(line):
        reject("Splitter must be a nonempty simple 2D LineString")
    if shapely.get_num_coordinates(line) > 1024:
        reject("Splitter exceeds 1024 vertices", "resource_limit")
    pieces = split(polygon, line)
    return _result(d, {"parcels_wkt": [p.wkt for p in pieces.geoms],
                      "areas_m2": [float(p.area) for p in pieces.geoms]}, "m2")

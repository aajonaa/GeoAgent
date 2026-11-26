"""Bounded offline operations backed by inspected upstream scientific code.

Only the coordinator's collection contract registers these source-ready candidates.
Third-party and vendored imports occur inside operation invocations.
"""
import hashlib
import importlib
import math
from pathlib import Path

from .collection_contracts import operation, reject


def _number(value, name, low=-1.0e9, high=1.0e9):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        reject(name + " must be a finite number.", code="invalid_arguments")
    if not math.isfinite(value) or not low <= value <= high:
        reject(name + " is outside the supported finite range.", code="invalid_arguments")
    return float(value)


def _vector(value, name, minimum=1, maximum=4096, low=-1.0e9, high=1.0e9):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        reject(name + " has an unsupported sample count.", code="invalid_arguments")
    return [_number(v, name, low, high) for v in value]


def _matrix(value, name, rows=512, cols=64, nullable=False):
    if not isinstance(value, list) or not 1 <= len(value) <= rows:
        reject(name + " has an unsupported row count.", code="invalid_arguments")
    if not isinstance(value[0], list) or not 1 <= len(value[0]) <= cols:
        reject(name + " has an unsupported column count.", code="invalid_arguments")
    width = len(value[0])
    result = []
    for row in value:
        if not isinstance(row, list) or len(row) != width:
            reject(name + " must be rectangular.", code="invalid_arguments")
        result.append([None if nullable and v is None else _number(v, name, -1e30, 1e30)
                       for v in row])
    return result


def _same_length(*values):
    if len({len(value) for value in values}) != 1:
        reject("Related arrays must have equal lengths.", code="invalid_arguments")


def _load(module):
    try:
        return importlib.import_module(module, __package__)
    except (ImportError, OSError):
        reject("A required scientific dependency is unavailable.", code="missing_dependency")


def _run(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except Exception:
        reject("The upstream algorithm could not process the bounded inputs.",
               code="computation_failed")


def _result(data, units):
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            reject("The upstream algorithm produced a non-finite result.",
                   code="numerical_failure")
        if isinstance(value, dict):
            for child in value.values():
                finite(child)
        elif isinstance(value, list):
            for child in value:
                finite(child)
    finite(data)
    data["units"] = units
    return data


@operation("EarthFlopyWaterTable")
def flopy_water_table(args, output_dir=None):
    heads = args["heads_m"]
    if not isinstance(heads, list) or not 1 <= len(heads) <= 32:
        reject("heads_m must contain between 1 and 32 layers.", code="invalid_arguments")
    layers = [_matrix(layer, "heads_m", 64, 64) for layer in heads]
    shape = (len(layers[0]), len(layers[0][0]))
    if any((len(layer), len(layer[0])) != shape for layer in layers):
        reject("Every head layer must have the same row and column shape.",
               code="invalid_arguments")
    if len(layers) * shape[0] * shape[1] > 65536:
        reject("heads_m exceeds 65536 cells.", code="invalid_arguments")
    dry = _number(args.get("dry_value", -1e30), "dry_value", -1e30, 1e30)
    noflow = _number(args.get("no_flow_value", 1e30), "no_flow_value", -1e30, 1e30)
    masked = _vector(args.get("masked_values", []), "masked_values", 0, 16, -1e30, 1e30)
    if dry == noflow:
        reject("Dry and no-flow sentinels must be distinct.", code="invalid_arguments")
    np = _load("numpy")
    upstream = _load(".collection_vendor.groundwater_other.flopy_water_table")
    water = _run(upstream.get_water_table, np.array(layers, dtype=float),
                 hdry=dry, hnoflo=noflow, masked_values=masked)
    water = np.ma.asarray(water).reshape(shape)
    mask = np.ma.getmaskarray(water)
    values = [[None if mask[i, j] else float(water[i, j])
               for j in range(shape[1])] for i in range(shape[0])]
    return _result({"water_table_m": values, "inactive": mask.tolist()},
                   {"water_table_m": "m", "inactive": "1"})


@operation("EarthTimmlSteadyWellHeads")
def timml_steady_well_heads(args, output_dir=None):
    conductivity = _number(args["hydraulic_conductivity_m_d"], "conductivity", 1e-6, 1e4)
    top = _number(args["aquifer_top_m"], "aquifer_top_m", -1e5, 1e5)
    bottom = _number(args["aquifer_bottom_m"], "aquifer_bottom_m", -1e5, 1e5)
    if not 0.1 <= top - bottom <= 10000:
        reject("Confined aquifer thickness must be between 0.1 and 10000 m.",
               code="invalid_arguments")
    reference = args["reference"]
    xr = _number(reference["x_m"], "reference.x_m", -1e6, 1e6)
    yr = _number(reference["y_m"], "reference.y_m", -1e6, 1e6)
    hr = _number(reference["head_m"], "reference.head_m", -1e5, 1e5)
    wells = args["wells"]
    points = args["points_m"]
    if not isinstance(wells, list) or not 1 <= len(wells) <= 16:
        reject("Supply between 1 and 16 wells.", code="invalid_arguments")
    points = _matrix(points, "points_m", 64, 2)
    if len(points[0]) != 2:
        reject("Each observation point must have two coordinates.", code="invalid_arguments")
    for point in points:
        for coordinate in point:
            _number(coordinate, "observation coordinate", -1e6, 1e6)
    clean = []
    for well in wells:
        clean.append((_number(well["x_m"], "well.x_m", -1e6, 1e6),
                      _number(well["y_m"], "well.y_m", -1e6, 1e6),
                      _number(well["pumping_m3_d"], "well.pumping_m3_d", -1e6, 1e6),
                      _number(well.get("radius_m", 0.1), "well.radius_m", 0.01, 100)))
    for i, (x, y, q, radius) in enumerate(clean):
        if any(math.hypot(px - x, py - y) <= radius for px, py in points + [[xr, yr]]):
            reject("Reference and observation points must lie outside every well.",
                   code="invalid_arguments")
        if any(math.hypot(x - ox, y - oy) <= radius + other_radius
               for ox, oy, oq, other_radius in clean[:i]):
            reject("Well screens must not overlap.", code="invalid_arguments")
    timml = _load("timml")

    def calculate():
        model = timml.ModelMaq(kaq=conductivity, z=[top, bottom], topboundary="conf")
        timml.Constant(model, xr=xr, yr=yr, hr=hr, layer=0)
        for x, y, q, radius in clean:
            timml.Well(model, xw=x, yw=y, Qw=q, rw=radius, layers=0)
        model.solve(silent=True)
        return [float(model.head(x, y, layers=[0])[0]) for x, y in points]

    heads = _run(calculate)
    return _result({"heads_m": heads, "drawdown_from_reference_m": [hr - h for h in heads]},
                   {"heads_m": "m", "drawdown_from_reference_m": "m"})


@operation("EarthTtimTransientWellDrawdown")
def ttim_transient_well_drawdown(args, output_dir=None):
    k = _number(args["hydraulic_conductivity_m_d"], "conductivity", 1e-4, 1e3)
    thickness = _number(args["thickness_m"], "thickness_m", 1, 1000)
    storage = _number(args["specific_storage_per_m"], "specific_storage_per_m", 1e-7, 1e-3)
    pumping = _number(args["pumping_m3_d"], "pumping_m3_d", 0, 1e5)
    times = _vector(args["times_d"], "times_d", 2, 32, 0.001, 10000)
    radii = _vector(args["radii_m"], "radii_m", 1, 16, 1, 1e5)
    if any(b <= a for a, b in zip(times, times[1:])) or times[-1] / times[0] > 1e6:
        reject("Times must increase strictly over at most six decades.",
               code="invalid_arguments")
    # Keep the finite-radius well correction below the independent Theis tolerance.
    if k * times[0] / storage < 100:
        reject("The earliest time must satisfy K*t/Ss >= 100 m2.",
               code="invalid_arguments")
    ttim = _load("ttim")

    def calculate():
        model = ttim.ModelMaq(kaq=k, z=[thickness, 0], Saq=storage,
                             topboundary="conf", phreatictop=False,
                             tmin=times[0], tmax=times[-1] * 1.000001, M=10)
        ttim.DischargeWell(model, xw=0, yw=0, tsandQ=[(0, pumping)], rw=0.1, layers=0)
        model.solve(silent=True)
        return [[-float(value) for value in model.head(radius, 0, times, layers=[0])[0]]
                for radius in radii]

    return _result({"drawdown_m": _run(calculate)},
                   {"drawdown_m": "m"})


@operation("EarthPyhelpStationDistances")
def pyhelp_station_distances(args, output_dir=None):
    origin = _vector(args["origin_lat_lon_deg"], "origin_lat_lon_deg", 2, 2, -180, 180)
    targets = _matrix(args["target_lat_lon_deg"], "target_lat_lon_deg", 4096, 2)
    if len(targets[0]) != 2 or abs(origin[0]) > 90:
        reject("Coordinates must be latitude/longitude pairs in degrees.",
               code="invalid_arguments")
    for lat, lon in targets:
        _number(lat, "latitude", -90, 90)
        _number(lon, "longitude", -180, 180)
        antipodal = (abs(lat + origin[0]) < 1e-7
                     and abs(abs(lon - origin[1]) % 360 - 180) < 1e-7)
        if antipodal:
            reject("Near-antipodal pairs are outside this upstream kernel's stable domain.",
                   code="invalid_arguments")
    np = _load("numpy")
    upstream = _load(".collection_vendor.groundwater_other.pyhelp_distance")
    coordinates = np.asarray(targets, dtype=float)
    distances = _run(upstream.calc_dist_from_coord, origin[0], origin[1],
                     coordinates[:, 0], coordinates[:, 1])
    return _result({"distance_km": distances.tolist(), "earth_radius_km": 6373},
                   {"distance_km": "km", "earth_radius_km": "km"})


@operation("EarthImodFreshwaterHead")
def imod_freshwater_head(args, output_dir=None):
    heads = _vector(args["pointwater_head_m"], "pointwater_head_m")
    elevations = _vector(args["elevation_m"], "elevation_m")
    densities = _vector(args["density_kg_m3"], "density_kg_m3", low=900, high=1500)
    fresh = _number(args.get("freshwater_density_kg_m3", 1000),
                    "freshwater_density_kg_m3", 900, 1100)
    _same_length(heads, elevations, densities)
    if any(h < z for h, z in zip(heads, elevations)):
        reject("This point-only operation requires head at or above cell elevation.",
               code="invalid_arguments")
    np = _load("numpy")
    upstream = _load(".collection_vendor.groundwater_other.imod_freshwater")
    result = _run(upstream.convert_pointwaterhead_freshwaterhead,
                  np.asarray(heads), np.asarray(densities), np.asarray(elevations), fresh)
    return _result({"freshwater_head_m": result.tolist()}, {"freshwater_head_m": "m"})


@operation("EarthIdfMaskedRasterAggregate")
def idf_masked_raster_aggregate(args, output_dir=None):
    grids = args["rasters_m"]
    if not isinstance(grids, list) or not 2 <= len(grids) <= 16:
        reject("Supply between 2 and 16 masked rasters.", code="invalid_arguments")
    grids = [_matrix(grid, "rasters_m", 64, 64, nullable=True) for grid in grids]
    shape = (len(grids[0]), len(grids[0][0]))
    if any((len(grid), len(grid[0])) != shape for grid in grids):
        reject("Raster shapes must agree.", code="invalid_arguments")
    if len(grids) * shape[0] * shape[1] > 65536:
        reject("Masked rasters exceed 65536 total cells.", code="invalid_arguments")
    method = args.get("method", "mean")
    if method not in ("min", "max", "sum", "mean", "merge"):
        reject("Unsupported masked raster method.", code="invalid_arguments")
    if method == "merge" and len(grids) != 2:
        reject("Priority merge requires exactly two rasters.", code="invalid_arguments")
    np = _load("numpy")
    upstream = _load(".collection_vendor.groundwater_other.idf_calc")
    arrays = [np.ma.array([[0.0 if v is None else v for v in row] for row in grid],
                          mask=[[v is None for v in row] for row in grid], dtype=float)
              for grid in grids]
    result = (_run(upstream.merge, *arrays) if method == "merge"
              else _run(upstream.agg, *arrays, method=method, axis=-1))
    mask = np.ma.getmaskarray(result)
    values = [[None if mask[i, j] else float(result[i, j]) for j in range(shape[1])]
              for i in range(shape[0])]
    return _result({"values_m": values}, {"values_m": "m"})


@operation("EarthWellapplicationBaseflow")
def wellapplication_baseflow(args, output_dir=None):
    flow = _vector(args["discharge_m3_s"], "discharge_m3_s", 2, 36600, 0, 1e9)
    recession = _number(args.get("recession", 0.95), "recession", 0, 0.9999)
    factor = _number(args.get("baseflow_factor", 0.5), "baseflow_factor", 0, 10)
    alpha = _number(args.get("ihacres_alpha", -0.5), "ihacres_alpha", -1, 0)
    method = args.get("method", "chapman")
    if method not in ("chapman", "boughton", "ihacres"):
        reject("Unsupported baseflow filter.", code="invalid_arguments")
    pd = _load("pandas")
    upstream = _load(".collection_vendor.groundwater_other.wellapplication_baseflow")
    functions = {"chapman": (upstream.get_baseflow_chapman, (recession,)),
                 "boughton": (upstream.get_baseflow_boughton, (recession, factor)),
                 "ihacres": (upstream.get_baseflow_ihacres, (recession, factor, alpha))}
    function, parameters = functions[method]
    data = _run(function, pd.Series(flow, dtype=float), *parameters)
    return _result({"baseflow_m3_s": data.iloc[:, 0].astype(float).tolist()},
                   {"baseflow_m3_s": "m3/s"})


@operation("EarthWelltestBourdetDerivative")
def welltest_bourdet_derivative(args, output_dir=None):
    head = _vector(args["drawdown_m"], "drawdown_m", 3, 4096)
    times = _vector(args["times_d"], "times_d", 3, 4096, 1e-9, 1e9)
    _same_length(head, times)
    if any(b <= a or math.log(b / a) < 1e-8 for a, b in zip(times, times[1:])):
        reject("Times must strictly increase with nondegenerate log spacing.",
               code="invalid_arguments")
    np = _load("numpy")
    upstream = _load(".collection_vendor.groundwater_other.welltest_derivative")
    result = _run(upstream.smoothing_derivative, np.asarray(head), np.asarray(times),
                  method="bourdet")
    return _result({"derivative_m": result.tolist(), "endpoint_policy": "upstream_zero"},
                   {"derivative_m": "m", "endpoint_policy": "1"})


@operation("EarthPytesmoMeanStdScale")
def pytesmo_mean_std_scale(args, output_dir=None):
    source = _vector(args["source_vwc"], "source_vwc", 2, 4096, 0, 1)
    reference = _vector(args["reference_vwc"], "reference_vwc", 2, 4096, 0, 1)
    if max(source) - min(source) < 1e-12:
        reject("Source soil moisture must have nonzero variation.", code="invalid_arguments")
    np = _load("numpy")
    upstream = _load(".collection_vendor.groundwater_other.pytesmo_scaling")
    values = _run(upstream.mean_std, np.asarray(source), np.asarray(reference))
    return _result({"scaled_vwc": values.tolist(), "mean_vwc": float(np.mean(values)),
                    "std_vwc": float(np.std(values))},
                   {"scaled_vwc": "m3/m3", "mean_vwc": "m3/m3", "std_vwc": "m3/m3"})


@operation("EarthPhydrusReadTlevel")
def phydrus_read_tlevel(args, output_dir=None):
    raw_path = args["file_path"]
    if not isinstance(raw_path, str) or not raw_path or len(raw_path) > 4096:
        reject("file_path must identify a bounded HYDRUS text snapshot.",
               code="invalid_arguments")
    path = Path(raw_path)
    if not path.is_file():
        reject("The HYDRUS input snapshot is unavailable.", code="invalid_input_file")
    if path.stat().st_size > 1048576:
        reject("The HYDRUS text snapshot exceeds 1 MiB.", code="invalid_arguments")
    try:
        raw = path.read_bytes()
        lines = raw.decode("ascii").splitlines()
    except (OSError, UnicodeError):
        reject("The HYDRUS snapshot must be readable ASCII text.", code="invalid_input_file")
    header = "Time rTop vTop vBot hTop hBot".split()
    headers = [i for i, line in enumerate(lines) if line.split() == header]
    ends = [i for i, line in enumerate(lines) if line.strip() == "end"]
    if len(headers) != 1 or len(ends) != 1:
        reject("Supply one supported T_LEVEL header and one end marker.",
               code="invalid_input_file")
    start, end = headers[0], ends[0]
    if (not start + 4 <= end <= start + 4099 or lines[end - 1].strip()
            or any(("rTop" in line or "end" in line) for line in lines[:start])):
        reject("The bounded T_LEVEL section has an invalid layout.",
               code="invalid_input_file")
    if lines[start + 1].split() != ["[d]", "[m/d]", "[m/d]", "[m/d]", "[m]", "[m]"]:
        reject("The supported T_LEVEL dialect requires explicit day/metre units.",
               code="invalid_input_file")
    samples = []
    try:
        for line in lines[start + 2:end - 1]:
            row = [float(value) for value in line.split()]
            if len(row) != 6 or any(not math.isfinite(v) or abs(v) > 1e9 for v in row):
                raise ValueError
            samples.append(row)
    except ValueError:
        reject("Every T_LEVEL data row must contain six finite numeric values.",
               code="invalid_input_file")
    if not 1 <= len(samples) <= 4096 or samples[0][0] < 0 or any(
            b[0] <= a[0] for a, b in zip(samples, samples[1:])):
        reject("T_LEVEL times must be nonnegative and strictly increasing.",
               code="invalid_input_file")
    upstream = _load(".collection_vendor.groundwater_other.phydrus.read")
    data = _run(upstream.read_tlevel, path=str(path), usecols=header)
    names = ["rTop_m_d", "vTop_m_d", "vBot_m_d", "hTop_m", "hBot_m"]
    result = {"time_d": [float(v) for v in data.index],
              "input_sha256": hashlib.sha256(raw).hexdigest()}
    result.update({name: data[column].astype(float).tolist()
                   for name, column in zip(names, header[1:])})
    if len(result["time_d"]) != len(samples):
        reject("The upstream reader returned an unexpected row count.",
               code="computation_failed")
    return _result(result, {"time_d": "d", "rTop_m_d": "m/d", "vTop_m_d": "m/d",
                            "vBot_m_d": "m/d", "hTop_m": "m", "hBot_m": "m",
                            "input_sha256": "1"})


@operation("EarthLandlabFlowDirections")
def landlab_flow_directions(args, output_dir=None):
    elevation = _vector(args["elevation_m"], "elevation_m", 2, 4096, -1e5, 1e5)
    edges = args["links"]
    if not isinstance(edges, list) or not 1 <= len(edges) <= 16384:
        reject("Supply between 1 and 16384 graph links.", code="invalid_arguments")
    base = args.get("baselevel_nodes", [])
    if not isinstance(base, list) or len(base) > len(elevation):
        reject("baselevel_nodes is outside the graph bounds.", code="invalid_arguments")
    if any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(elevation)
           for i in base) or len(set(base)) != len(base):
        reject("Baselevel nodes must be unique valid node IDs.", code="invalid_arguments")
    tails, heads, slopes, seen = [], [], [], set()
    for edge in edges:
        tail, head = edge["tail"], edge["head"]
        if any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(elevation)
               for i in (tail, head)) or tail == head:
            reject("Link endpoints must be distinct valid node IDs.", code="invalid_arguments")
        key = tuple(sorted((tail, head)))
        if key in seen:
            reject("Duplicate graph links are not supported.", code="invalid_arguments")
        seen.add(key)
        length = _number(edge["length_m"], "link.length_m", 0.001, 1e6)
        tails.append(tail)
        heads.append(head)
        slopes.append((elevation[tail] - elevation[head]) / length)
    np = _load("numpy")
    upstream = _load("landlab.components.flow_director.flow_direction_DN")
    receiver, slope, sinks, link = _run(
        upstream.flow_directions, np.asarray(elevation, dtype=float),
        np.arange(len(edges), dtype=np.intp), np.asarray(tails, dtype=np.intp),
        np.asarray(heads, dtype=np.intp), np.asarray(slopes, dtype=float),
        baselevel_nodes=np.asarray(base, dtype=np.intp))
    return _result({"receiver": receiver.tolist(), "steepest_slope": slope.tolist(),
                    "sink_nodes": sinks.tolist(), "receiver_link": link.tolist()},
                   {"receiver": "1", "steepest_slope": "m/m",
                    "sink_nodes": "1", "receiver_link": "1"})


@operation("EarthIrisCubeCorrelation")
def iris_cube_correlation(args, output_dir=None):
    a = _matrix(args["a_K"], "a_K", 512, 64)
    b = _matrix(args["b_K"], "b_K", 512, 64)
    if len(a) < 3 or (len(a), len(a[0])) != (len(b), len(b[0])):
        reject("Temperature cubes must share a sample-by-site shape with at least 3 samples.",
               code="invalid_arguments")
    for matrix in (a, b):
        for row in matrix:
            for value in row:
                _number(value, "temperature_K", 100, 400)
        for column in zip(*matrix):
            if max(column) - min(column) < 1e-10:
                reject("Every temperature column must have nonzero variation.",
                       code="invalid_arguments")
    weights = _vector(args.get("weights", [1] * len(a)), "weights",
                      3, 512, 1e-6, 1e6)
    _same_length(a, weights)
    np = _load("numpy")
    cube_module = _load("iris.cube")
    coords = _load("iris.coords")
    statistics = _load("iris.analysis.stats")

    def calculate():
        sample = coords.DimCoord(np.arange(len(a)), long_name="sample", units="1")
        site = coords.DimCoord(np.arange(len(a[0])), long_name="site", units="1")
        ca = cube_module.Cube(np.asarray(a, dtype=float), long_name="temperature_a",
                              units="K", dim_coords_and_dims=[(sample, 0), (site, 1)])
        cb = cube_module.Cube(np.asarray(b, dtype=float), long_name="temperature_b",
                              units="K", dim_coords_and_dims=[(sample.copy(), 0), (site.copy(), 1)])
        weight_grid = np.asarray(weights, dtype=float)[:, None] * np.ones((1, len(a[0])))
        result = statistics.pearsonr(ca, cb, corr_coords=["sample"], weights=weight_grid,
                                     mdtol=0.0, common_mask=False)
        return np.asarray(result.data, dtype=float).reshape(-1).tolist()

    return _result({"correlation": _run(calculate)}, {"correlation": "1"})


@operation("EarthPyhspfReachTable")
def pyhspf_reach_table(args, output_dir=None):
    flow = _number(args["mean_flow_cfs"], "mean_flow_cfs", 0.001, 1e6)
    velocity = _number(args["mean_velocity_fps"], "mean_velocity_fps", 0.01, 30)
    length = _number(args["reach_length_km"], "reach_length_km", 0.001, 1000)
    slope = _number(args["channel_slope"], "channel_slope", 1e-6, 0.5)
    sides = [_number(args.get(key, default), key, 0.05, 10) for key, default in
             [("main_side_slope", 1), ("lower_side_slope", 0.5), ("upper_side_slope", 0.5)]]
    upstream = _load(".collection_vendor.groundwater_other.pyhspf_ftable")
    rows = _run(upstream.make_ftable, flow, velocity, length, slope, *sides)
    keys = ["depth_m", "surface_area_ha", "volume_Mm3", "discharge_m3_s"]
    return _result({"rows": [dict(zip(keys, row)) for row in rows]},
                   {"depth_m": "m", "surface_area_ha": "ha",
                    "volume_Mm3": "1e6 m3", "discharge_m3_s": "m3/s"})


@operation("EarthSphyCropEvapotranspiration")
def sphy_crop_evapotranspiration(args, output_dir=None):
    reference = _vector(args["reference_et_mm_d"], "reference_et_mm_d", 1, 4096, 0, 100)
    coefficients = _vector(args["crop_coefficient"], "crop_coefficient", 1, 4096, 0, 3)
    _same_length(reference, coefficients)
    np = _load("numpy")
    upstream = _load(".collection_vendor.groundwater_other.sphy_et")
    result = _run(upstream.ETpot, np.asarray(reference), np.asarray(coefficients))
    return _result({"potential_crop_et_mm_d": result.tolist()},
                   {"potential_crop_et_mm_d": "mm/d"})


@operation("EarthXsboringenLithology")
def xsboringen_lithology(args, output_dir=None):
    samples, rules = args["samples"], args["rules"]
    if not isinstance(samples, list) or not 1 <= len(samples) <= 4096:
        reject("Supply between 1 and 4096 CPT samples.", code="invalid_arguments")
    if not isinstance(rules, list) or not 1 <= len(rules) <= 32:
        reject("Supply between 1 and 32 lithology rules.", code="invalid_arguments")
    for rule in rules:
        limits = rule["limits"]
        if not isinstance(limits, list) or not 1 <= len(limits) <= 8:
            reject("Every rule requires between 1 and 8 bounded intervals.",
                   code="invalid_arguments")
        intervals = []
        for limit in limits:
            left = _number(limit["left"], "limit.left", 0, 20)
            right = _number(limit["right"], "limit.right", 0, 20)
            _number(limit["a"], "limit.a", 0, 100)
            _number(limit["b"], "limit.b", -5, 5)
            if right <= left or any(max(left, lo) < min(right, hi) for lo, hi in intervals):
                reject("Intervals within a rule must be increasing and disjoint.",
                       code="invalid_arguments")
            intervals.append((left, right))
    clean = [(_number(s["friction_ratio_percent"], "friction_ratio_percent", 0, 20),
              _number(s["cone_resistance_MPa"], "cone_resistance_MPa", 0, 100))
             for s in samples]
    upstream = _load(".collection_vendor.groundwater_other.xsboringen_calc")
    table = {"default": args["default_code"], "rules": rules}
    classifier = _run(upstream.LithologyClassifier, table, ruletype="exponential")
    result = [_run(classifier.classify, rf, qc) for rf, qc in clean]
    return _result({"lithology_codes": result}, {"lithology_codes": "1"})


@operation("EarthEflowMagnitudeIndices")
def eflow_magnitude_indices(args, output_dir=None):
    flows = _vector(args["daily_discharge_m3_s"], "daily_discharge_m3_s", 10, 36600, 0, 1e9)
    ordered = sorted(flows)
    def percentile(q):
        position = (len(ordered) - 1) * q
        lo = int(position)
        hi = min(lo + 1, len(ordered) - 1)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)
    if percentile(0.1) <= 0:
        reject("The 10th percentile must be positive for the magnitude ratios.",
               code="invalid_arguments")
    np = _load("numpy")
    upstream = _load(".collection_vendor.groundwater_other.eflow_magnitude")
    array = np.asarray(flows, dtype=float)
    mapping = {"mean_m3_s": "ma1", "median_m3_s": "ma2",
               "mean_median_ratio": "ma5", "p90_p10_ratio": "ma6", "p80_p20_ratio": "ma7"}
    result = {key: float(_run(getattr(upstream, function), array, None, None, None))
              for key, function in mapping.items()}
    return _result(result, {"mean_m3_s": "m3/s", "median_m3_s": "m3/s",
                            "mean_median_ratio": "1", "p90_p10_ratio": "1",
                            "p80_p20_ratio": "1"})


@operation("EarthHydroboxFlashiness")
def hydrobox_flashiness(args, output_dir=None):
    flow = _vector(args["discharge_m3_s"], "discharge_m3_s", 2, 36600, 0, 1e9)
    if sum(flow[1:]) <= 0:
        reject("Discharge after the first sample must have a positive sum.",
               code="invalid_arguments")
    np = _load("numpy")
    upstream = _load(".collection_vendor.groundwater_other.hydrobox_indices")
    result = _run(upstream.richards_baker, np.asarray(flow, dtype=float))
    return _result({"flashiness_index": float(result)}, {"flashiness_index": "1"})

"""Independent numerical/content assertions for coordinator-run CPU acceptance.

This module does not import or execute the adapters. It never installs packages.
"""
import hashlib
import math
from pathlib import Path


def _close(actual, expected, *, rtol=1e-8, atol=1e-9):
    if isinstance(expected, dict):
        for key, value in expected.items():
            assert key in actual, key
            _close(actual[key], value, rtol=rtol, atol=atol)
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected)
        for a, e in zip(actual, expected):
            _close(a, e, rtol=rtol, atol=atol)
    elif expected is None or isinstance(expected, (str, bool)):
        assert actual == expected
        if isinstance(expected, bool):
            assert isinstance(actual, bool)
    else:
        assert not isinstance(actual, bool)
        assert math.isfinite(actual)
        assert math.isclose(actual, expected, rel_tol=rtol, abs_tol=atol), (actual, expected)


def input_fingerprints(args):
    """Take snapshots before calling the operation; pass them to assert_immutable."""
    if "file_path" not in args:
        return {}
    path = Path(args["file_path"])
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()}


def assert_immutable(args, before):
    assert input_fingerprints(args) == before, "Input file bytes changed"


def _percentile(values, fraction):
    values = sorted(values)
    index = (len(values) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] * (upper - index) + values[upper] * (index - lower) if upper != lower else values[lower]


def _reach_reference(args):
    """Independent standard-library geometric/Manning reference, including source quirks."""
    f = args["mean_flow_cfs"]
    velocity = args["mean_velocity_fps"]
    length = args["reach_length_km"]
    slope = args["channel_slope"]
    s0, s1, s2 = [args.get(key, default) for key, default in
                  [("main_side_slope", 1), ("lower_side_slope", 0.5), ("upper_side_slope", 0.5)]]
    width = math.sqrt(f / velocity / 2) * 0.3048
    def area(depth, bottom):
        return depth * (bottom + depth)
    def perimeter(depth, bottom, side):
        return bottom + 2 * depth * math.sqrt(1 + 1 / side ** 2)
    def discharge(a, p):
        return 20 * a * (a / p) ** (2 / 3) * math.sqrt(slope)
    for _ in range(5):
        q = discharge(2 * width ** 2, perimeter(width, width, 1))
        width *= (f * 0.3048 ** 3 / q) ** (1 / 3)
    rows = [{"depth_m": 0.0, "surface_area_ha": 0.0,
             "volume_Mm3": 0.0, "discharge_m3_s": 0.0}]
    def add(depth, a, p, surface_width):
        rows.append({"depth_m": depth, "surface_area_ha": surface_width * length / 10,
                     "volume_Mm3": a * length / 1000, "discharge_m3_s": discharge(a, p)})
    for multiple in [0.25, 0.5, 0.75, 1, 1.25]:
        depth = multiple * width
        add(depth, area(depth, width), perimeter(depth, width, s0),
            2 * depth / s0 + width)
    d1 = 1.25 * width
    a1 = area(d1, width)
    p1 = perimeter(d1, width, s0) + 6 * width
    b1 = 9.5 * width
    for multiplier in [1.25, 1.5]:
        depth = multiplier * d1
        delta = depth - d1
        add(depth, a1 + area(delta, b1), p1 + perimeter(delta, b1, s1) - b1,
            2 * delta / s1 + b1)
    d2 = 1.5 * d1
    a2 = a1 + area(d2 - d1, b1)
    b2 = b1 + 2 * (d2 - d1) / s1
    for multiplier in [2, 3, 5, 10, 20, 40, 60]:
        depth = multiplier * width
        delta = depth - d2
        # The source uses p1 here, not the cumulative second-floodplain perimeter.
        add(depth, a2 + area(delta, b2), p1 + perimeter(delta, b2, s2) - b2,
            2 * delta / s2 + b2)
    return rows


def check(name, result, args, output_dir=None):
    if name not in _UNITS:
        raise AssertionError("Unknown groundwater_other operation: " + str(name))
    assert result["units"] == _UNITS[name], "Incorrect or missing scientific units"
    if name == "EarthFlopyWaterTable":
        heads = args["heads_m"]
        sentinels = [args.get("dry_value", -1e30), args.get("no_flow_value", 1e30)]
        sentinels += args.get("masked_values", [])
        expected = []
        for i in range(len(heads[0])):
            row = []
            for j in range(len(heads[0][0])):
                row.append(next((layer[i][j] for layer in heads
                                 if layer[i][j] not in sentinels), None))
            expected.append(row)
        _close(result["water_table_m"], expected)
        _close(result["inactive"], [[value is None for value in row] for row in expected])
    elif name == "EarthTimmlSteadyWellHeads":
        transmissivity = (args["aquifer_top_m"] - args["aquifer_bottom_m"]) * args["hydraulic_conductivity_m_d"]
        reference = args["reference"]
        expected = []
        for x, y in args["points_m"]:
            drawdown = 0.0
            for well in args["wells"]:
                radius = math.hypot(x - well["x_m"], y - well["y_m"])
                ref_radius = math.hypot(reference["x_m"] - well["x_m"],
                                        reference["y_m"] - well["y_m"])
                drawdown += well["pumping_m3_d"] / (2 * math.pi * transmissivity) * math.log(ref_radius / radius)
            expected.append(reference["head_m"] - drawdown)
        _close(result["heads_m"], expected)
        _close(result["drawdown_from_reference_m"],
               [reference["head_m"] - value for value in expected])
    elif name == "EarthTtimTransientWellDrawdown":
        # Independent closed-form Theis reference, not another TTim call.
        from scipy.special import exp1
        transmissivity = args["hydraulic_conductivity_m_d"] * args["thickness_m"]
        storativity = args["specific_storage_per_m"] * args["thickness_m"]
        expected = [[float(args["pumping_m3_d"] / (4 * math.pi * transmissivity)
                           * exp1(radius * radius * storativity /
                                  (4 * transmissivity * time)))
                     for time in args["times_d"]] for radius in args["radii_m"]]
        _close(result["drawdown_m"], expected, rtol=0.003, atol=3e-5)
    elif name == "EarthPyhelpStationDistances":
        lat, lon = [math.radians(x) for x in args["origin_lat_lon_deg"]]
        expected = []
        for target_lat, target_lon in args["target_lat_lon_deg"]:
            la, lo = math.radians(target_lat), math.radians(target_lon)
            cosine = math.sin(lat) * math.sin(la) + math.cos(lat) * math.cos(la) * math.cos(lo - lon)
            angle = math.acos(max(-1.0, min(1.0, cosine)))
            expected.append(6373 * angle)
        _close(result["distance_km"], expected, rtol=1e-8, atol=1e-4)
        _close(result["earth_radius_km"], 6373)
    elif name == "EarthImodFreshwaterHead":
        fresh = args.get("freshwater_density_kg_m3", 1000)
        expected = [z + (density / fresh) * (head - z) for head, z, density in
                    zip(args["pointwater_head_m"], args["elevation_m"], args["density_kg_m3"])]
        _close(result["freshwater_head_m"], expected)
    elif name == "EarthIdfMaskedRasterAggregate":
        rasters = args["rasters_m"]
        method = args.get("method", "mean")
        expected = []
        for i in range(len(rasters[0])):
            row = []
            for j in range(len(rasters[0][0])):
                values = [raster[i][j] for raster in rasters if raster[i][j] is not None]
                if not values:
                    value = None
                elif method == "merge":
                    value = values[0]
                elif method == "mean":
                    value = math.fsum(values) / len(values)
                elif method == "sum":
                    value = math.fsum(values)
                elif method == "min":
                    value = min(values)
                else:
                    value = max(values)
                row.append(value)
            expected.append(row)
        _close(result["values_m"], expected)
    elif name == "EarthWellapplicationBaseflow":
        flow = args["discharge_m3_s"]
        recession = args.get("recession", 0.95)
        factor = args.get("baseflow_factor", 0.5)
        alpha = args.get("ihacres_alpha", -0.5)
        method = args.get("method", "chapman")
        expected = [0.0]
        for previous_flow, current_flow in zip(flow, flow[1:]):
            if method == "chapman":
                value = (recession * expected[-1] + (1 - recession) * current_flow) / (2 - recession)
            elif method == "boughton":
                value = (recession * expected[-1] + factor * current_flow) / (1 + factor)
            else:
                value = (recession * expected[-1] + factor * (current_flow + alpha * previous_flow)) / (1 + factor)
            expected.append(value)
        _close(result["baseflow_m3_s"], expected)
    elif name == "EarthWelltestBourdetDerivative":
        times, heads = args["times_d"], args["drawdown_m"]
        expected = [0.0]
        for i in range(1, len(times) - 1):
            left = math.log(times[i] / times[i - 1])
            right = math.log(times[i + 1] / times[i])
            left_slope = (heads[i] - heads[i - 1]) / left
            right_slope = (heads[i + 1] - heads[i]) / right
            expected.append((left_slope * right + right_slope * left) / (left + right))
        expected.append(0.0)
        _close(result["derivative_m"], expected)
        assert result["endpoint_policy"] == "upstream_zero"
    elif name == "EarthPytesmoMeanStdScale":
        source, reference = args["source_vwc"], args["reference_vwc"]
        sm, rm = math.fsum(source) / len(source), math.fsum(reference) / len(reference)
        ss = math.sqrt(math.fsum((x - sm) ** 2 for x in source) / len(source))
        rs = math.sqrt(math.fsum((x - rm) ** 2 for x in reference) / len(reference))
        expected = [rm + (value - sm) * rs / ss for value in source]
        _close(result["scaled_vwc"], expected)
        _close(result["mean_vwc"], rm)
        _close(result["std_vwc"], rs)
    elif name == "EarthPhydrusReadTlevel":
        raw = Path(args["file_path"]).read_bytes()
        lines = raw.decode("ascii").splitlines()
        header = ["Time", "rTop", "vTop", "vBot", "hTop", "hBot"]
        start = next(i for i, line in enumerate(lines) if line.split() == header)
        end = next(i for i, line in enumerate(lines) if line.strip() == "end")
        rows = [[float(value) for value in line.split()]
                for line in lines[start + 2:end - 1]]
        for column, key in enumerate(["time_d", "rTop_m_d", "vTop_m_d",
                                      "vBot_m_d", "hTop_m", "hBot_m"]):
            _close(result[key], [row[column] for row in rows])
        assert result["input_sha256"] == hashlib.sha256(raw).hexdigest(), "Input bytes changed after the pre-call hash"
    elif name == "EarthLandlabFlowDirections":
        elevation = args["elevation_m"]
        receiver = list(range(len(elevation)))
        slope = [0.0] * len(elevation)
        receiver_link = [-1] * len(elevation)
        for index, edge in enumerate(args["links"]):
            a, b = edge["tail"], edge["head"]
            if elevation[a] < elevation[b]:
                a, b = b, a
            gradient = (elevation[a] - elevation[b]) / edge["length_m"]
            if gradient > slope[a]:
                receiver[a], slope[a], receiver_link[a] = b, gradient, index
        for node in args.get("baselevel_nodes", []):
            receiver[node], slope[node], receiver_link[node] = node, 0.0, -1
        _close(result["receiver"], receiver)
        _close(result["steepest_slope"], slope)
        _close(result["receiver_link"], receiver_link)
        _close(result["sink_nodes"], [i for i, downstream in enumerate(receiver) if i == downstream])
    elif name == "EarthIrisCubeCorrelation":
        weights = args.get("weights", [1] * len(args["a_K"]))
        total = math.fsum(weights)
        expected = []
        for x, y in zip(zip(*args["a_K"]), zip(*args["b_K"])):
            mx = math.fsum(w * value for w, value in zip(weights, x)) / total
            my = math.fsum(w * value for w, value in zip(weights, y)) / total
            covariance = math.fsum(w * (a - mx) * (b - my) for w, a, b in zip(weights, x, y))
            sx = math.fsum(w * (a - mx) ** 2 for w, a in zip(weights, x))
            sy = math.fsum(w * (b - my) ** 2 for w, b in zip(weights, y))
            expected.append(covariance / math.sqrt(sx * sy))
        _close(result["correlation"], expected)
    elif name == "EarthPyhspfReachTable":
        _close(result["rows"], _reach_reference(args))
        assert len(result["rows"]) == 15
        assert all(b["depth_m"] > a["depth_m"] for a, b in zip(result["rows"], result["rows"][1:]))
    elif name == "EarthSphyCropEvapotranspiration":
        _close(result["potential_crop_et_mm_d"],
               [et * coefficient for et, coefficient in
                zip(args["reference_et_mm_d"], args["crop_coefficient"])])
    elif name == "EarthXsboringenLithology":
        expected = []
        for sample in args["samples"]:
            rf, qc = sample["friction_ratio_percent"], sample["cone_resistance_MPa"]
            value = args["default_code"]
            for rule in args["rules"]:
                interval = next((interval for interval in rule["limits"]
                                 if interval["left"] < rf <= interval["right"]), None)
                if interval and qc > interval["a"] * math.exp(interval["b"] * rf):
                    value = rule["lithology"]
                    break
            expected.append(value)
        _close(result["lithology_codes"], expected)
    elif name == "EarthEflowMagnitudeIndices":
        values = args["daily_discharge_m3_s"]
        mean = math.fsum(values) / len(values)
        median = _percentile(values, 0.5)
        _close(result, {"mean_m3_s": mean, "median_m3_s": median,
                        "mean_median_ratio": mean / median,
                        "p90_p10_ratio": _percentile(values, 0.9) / _percentile(values, 0.1),
                        "p80_p20_ratio": _percentile(values, 0.8) / _percentile(values, 0.2)})
    elif name == "EarthHydroboxFlashiness":
        flow = args["discharge_m3_s"]
        expected = math.fsum(abs(b - a) for a, b in zip(flow, flow[1:])) / math.fsum(flow[1:])
        _close(result["flashiness_index"], expected)


_UNITS = {
  "EarthFlopyWaterTable": {
    "water_table_m": "m",
    "inactive": "1"
  },
  "EarthTimmlSteadyWellHeads": {
    "heads_m": "m",
    "drawdown_from_reference_m": "m"
  },
  "EarthTtimTransientWellDrawdown": {
    "drawdown_m": "m"
  },
  "EarthPyhelpStationDistances": {
    "distance_km": "km",
    "earth_radius_km": "km"
  },
  "EarthImodFreshwaterHead": {
    "freshwater_head_m": "m"
  },
  "EarthIdfMaskedRasterAggregate": {
    "values_m": "m"
  },
  "EarthWellapplicationBaseflow": {
    "baseflow_m3_s": "m3/s"
  },
  "EarthWelltestBourdetDerivative": {
    "derivative_m": "m",
    "endpoint_policy": "1"
  },
  "EarthPytesmoMeanStdScale": {
    "scaled_vwc": "m3/m3",
    "mean_vwc": "m3/m3",
    "std_vwc": "m3/m3"
  },
  "EarthPhydrusReadTlevel": {
    "time_d": "d",
    "rTop_m_d": "m/d",
    "vTop_m_d": "m/d",
    "vBot_m_d": "m/d",
    "hTop_m": "m",
    "hBot_m": "m",
    "input_sha256": "1"
  },
  "EarthLandlabFlowDirections": {
    "receiver": "1",
    "steepest_slope": "m/m",
    "sink_nodes": "1",
    "receiver_link": "1"
  },
  "EarthIrisCubeCorrelation": {
    "correlation": "1"
  },
  "EarthPyhspfReachTable": {
    "depth_m": "m",
    "surface_area_ha": "ha",
    "volume_Mm3": "1e6 m3",
    "discharge_m3_s": "m3/s"
  },
  "EarthSphyCropEvapotranspiration": {
    "potential_crop_et_mm_d": "mm/d"
  },
  "EarthXsboringenLithology": {
    "lithology_codes": "1"
  },
  "EarthEflowMagnitudeIndices": {
    "mean_m3_s": "m3/s",
    "median_m3_s": "m3/s",
    "mean_median_ratio": "1",
    "p90_p10_ratio": "1",
    "p80_p20_ratio": "1"
  },
  "EarthHydroboxFlashiness": {
    "flashiness_index": "1"
  }
}

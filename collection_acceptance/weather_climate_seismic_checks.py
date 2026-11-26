"""Independent numerical/content acceptance hooks; not executed by the shard author."""
from __future__ import annotations

import bisect
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct

FIXTURE_SHA256 = {
  "synthetic_wrf": "035d77d065c0cf34672c7b23b4950b91f18574a785195b763362b49bfe18ac47",
  "synthetic_rainymotion": "6fb30944266273424edb0d37a7d55d766ee1b5d7330b7a64e409c6a6525e520e",
  "synthetic_metsim": "18aad611d2bd7d5c27d8e5b604d069e5b859b2d8ef1b469ab36e8f39f22b316a",
  "synthetic_melodist": "8f9fbbe8d7a1e73f0cf09932eaedf6f86b0ec54193432f26bee9dcfdd5995680",
  "synthetic_improver": "1f1a9aee738a1abe4467947fa164099a6d3b0ebc778e4334e0bbd735f73f9d83",
  "synthetic_skdownscale": "918b01e86bf61f79c2807e8e3627565024616e531ff10d119214dbcc6c971a3c",
  "synthetic_jams": "da1706840e0178b321c4c06ade054fd6f0216070f597bc1cbed841d5fe00d38f",
  "synthetic_xgcm": "4d572f0faf909d73468559acebe909648fc620e3dac6a5bed227aaf313ff996a",
  "synthetic_climpred": "ab239886e09c87f3d17155910837abf83c6d22f62fe782e918776b44747ef235",
  "synthetic_climlab": "63e6946c46127231fe5534c9e1a43a343dda3766df50620d68514723ff16808a",
  "synthetic_aospy": "abfe81961d3b861c2f953dd91195f255afe688cc2a85baefa636ccbd96abc6f7",
  "synthetic_oocgcm": "ce8268d124ad77c98fd38335d2fb0a43052d5f248f263b3038f36c9d7300a942",
  "synthetic_ocgis": "fbd2e964e49ffd64d17af2999a14ab082abc8eff14f3023174a9212efe56bc83",
  "synthetic_pyrocko": "0011398e94be081e1885cc9815890b3d0df7ca2a9e2a13f320b0e1dd49905a3d",
  "synthetic_rsudp": "d8944103535a61783f9eb205d5bd5e479bc70985d73624e35e81bf239e843df0",
  "synthetic_seismic_zfp": "d46d5c0495c2331fb64b6b4388683b0397c7b356caaf9b2526c8c33f9a185fcf"
}


NAMES = (
    "WrfDestaggerGrid", "RainymotionPrecipitationScores",
    "MetSimPotentialEvapotranspiration", "MelodistDailyPrecipitationToHourly",
    "ImproverRescaleForecastField", "SkdownscaleQuantileBiasCorrection",
    "JamsDewPoint", "XgcmStaggeredGridDiagnostics", "ClimpredEnsembleCrps",
    "ClimlabLayerHeatCapacity", "AospyHybridPressure", "OocgcmSurfaceSpiciness",
    "OcgisHeatIndex", "PyrockoDoubleCoupleTensor", "RsudpWindowAmplitude",
    "SeismicZfpCompressCube",
)


def _close(actual, expected, atol=1e-9, rtol=1e-8):
    if isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected)
        for a, e in zip(actual, expected):
            _close(a, e, atol, rtol)
    elif expected is None:
        assert actual is None
    else:
        assert isinstance(actual, (int, float)) and not isinstance(actual, bool)
        assert math.isfinite(actual) and math.isclose(actual, expected, abs_tol=atol, rel_tol=rtol), (actual, expected)


def _interp(value, xs, ys):
    if value < xs[0]:
        return ys[0]
    i = bisect.bisect_right(xs, value)
    if i == len(xs):
        return ys[-1]
    lo, hi = i - 1, i
    fraction = (value - xs[lo]) / (xs[hi] - xs[lo])
    return ys[lo] + fraction * (ys[hi] - ys[lo])


def capture_inputs(args):
    """Coordinator may call before an invocation for any real or synthetic input."""
    path = Path(args["data_path"])
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()}


def assert_inputs_unchanged(before):
    for path, expected in before.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected


def check(name: str, result: dict, args: dict, output_dir: Path | None):
    if name not in NAMES:
        raise AssertionError("Unknown weather_climate_seismic operation: " + name)
    raw = Path(args["data_path"]).read_bytes()
    p = json.loads(raw)
    fixture_id = p.get("fixture_id")
    if fixture_id in FIXTURE_SHA256:
        assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA256[fixture_id], "Synthetic input was changed."
    assert isinstance(result.get("units"), dict) and result["units"]
    for value in result["units"].values():
        assert isinstance(value, str) and value

    if name == "WrfDestaggerGrid":
        shape, values = p["shape"], p["values"]
        axis = args["stagger_dim"] % len(shape)
        target = shape.copy()
        target[axis] -= 1
        input_stride = [math.prod(shape[i + 1:]) for i in range(len(shape))]
        output_stride = [math.prod(target[i + 1:]) for i in range(len(target))]
        expected = []
        for index in range(math.prod(target)):
            coordinates = [(index // stride) % extent for stride, extent in zip(output_stride, target)]
            first = sum(c * s for c, s in zip(coordinates, input_stride))
            expected.append((values[first] + values[first + input_stride[axis]]) / 2)
        assert result["shape"] == target
        _close(result["values"], expected)
        assert result["units"]["values"] == args["data_unit"]

    elif name == "RainymotionPrecipitationScores":
        obs, forecast = p["observed_mm_h"], p["forecast_mm_h"]
        threshold = args.get("threshold_mm_h", 0.1)
        hits = sum(o >= threshold and f >= threshold for o, f in zip(obs, forecast))
        misses = sum(o >= threshold and f < threshold for o, f in zip(obs, forecast))
        false = sum(o < threshold and f >= threshold for o, f in zip(obs, forecast))
        negatives = len(obs) - hits - misses - false
        assert result["contingency"] == {"hits": hits, "misses": misses, "false_alarms": false,
                                         "correct_negatives": negatives}
        _close(result["rmse"], math.sqrt(sum((f - o) ** 2 for o, f in zip(obs, forecast)) / len(obs)))
        _close(result["mae"], sum(abs(f - o) for o, f in zip(obs, forecast)) / len(obs))
        for key, numerator, denominator in (
            ("csi", hits, hits + misses + false),
            ("false_alarm_ratio", false, hits + false),
            ("probability_of_detection", hits, hits + misses),
            ("heidke_skill_score", 2 * (hits * negatives - misses * false),
             misses ** 2 + false ** 2 + 2 * hits * negatives + (misses + false) * (hits + negatives)),
        ):
            _close(result[key], numerator / denominator if denominator else None)
        assert result["units"]["rmse"] == result["units"]["mae"] == "mm/h"

    elif name == "MetSimPotentialEvapotranspiration":
        def vapour(t):
            base = 610.78 * math.exp(17.269 * t / (237.3 + t))
            return base * (1 + 0.00972 * t + 0.000042 * t * t) if t < 0 else base
        expected = []
        for rad, temp, daylight in zip(p["shortwave_w_m2"], p["temperature_degC"], p["daylength_s"]):
            latent = 2502300 - 2430.54 * temp
            slope = (vapour(temp + 0.2) - vapour(temp - 0.2)) / 0.4
            gamma = 1010 * args["pressure_pa"] / (latent * 0.62196351)
            expected.append(1.26 * slope / (slope + gamma) * (rad * 0.72) * daylight / latent / 10)
        _close(result["potential_evapotranspiration"], expected)
        assert result["units"]["potential_evapotranspiration"] == "cm/day"
        if fixture_id == "synthetic_metsim":
            assert result["potential_evapotranspiration"][0:2] == [0.0, 0.0]
            assert 0.1 < result["potential_evapotranspiration"][2] < 0.5

    elif name == "MelodistDailyPrecipitationToHourly":
        daily = p["daily_precipitation_mm"]
        expected = [value / 24 for value in daily for _ in range(24)]
        _close(result["hourly_precipitation"], expected)
        start = dt.datetime.fromisoformat(args["start_date"])
        assert result["timestamps"] == [(start + dt.timedelta(hours=i)).isoformat() for i in range(len(expected))]
        for day, total in enumerate(daily):
            _close(sum(result["hourly_precipitation"][24 * day:24 * (day + 1)]), total)
        assert result["units"]["hourly_precipitation"] == "mm per 1-hour interval"

    elif name == "ImproverRescaleForecastField":
        left, right = args["data_range"]
        a, b = args.get("scale_range", [0, 1])
        expected = [a + (v - left) / (right - left) * (b - a) for v in p["values"]]
        if args.get("clip", False):
            expected = [max(min(a, b), min(max(a, b), v)) for v in expected]
        _close(result["scaled_values"], expected)
        assert result["units"]["scaled_values"] == "1"

    elif name == "SkdownscaleQuantileBiasCorrection":
        x, y = sorted(p["historical_model"]), sorted(p["historical_observed"])
        _close(result["corrected_values"], [_interp(v, x, y) for v in p["future_model"]])
        assert result["units"]["corrected_values"] == args["data_unit"]
        if fixture_id == "synthetic_skdownscale":
            _close(result["corrected_values"], [10, 10, 13, 18, 18])

    elif name == "JamsDewPoint":
        unit = args.get("output_unit", "degC")
        expected = []
        for pressure in p["vapour_pressure_pa"]:
            w = math.log(pressure / 611.21)
            expected.append(240.97 * w / (17.502 - w) + (273.15 if unit == "K" else 0))
        _close(result["dew_point"], expected)
        assert result["units"]["dew_point"] == unit

    elif name == "XgcmStaggeredGridDiagnostics":
        values, dx = p["values"], args["spacing_m"]
        _close(result["interpolated_values"], [(a + b) / 2 for a, b in zip(values, values[1:])])
        _close(result["gradient"], [(b - a) / dx for a, b in zip(values, values[1:])])
        assert result["units"] == {"interpolated_values": args["data_unit"], "gradient": "(" + args["data_unit"] + ")/m"}

    elif name == "ClimpredEnsembleCrps":
        expected = []
        for row, observation in zip(p["forecast"], p["observed"]):
            count = len(row)
            expected.append(sum(abs(v - observation) for v in row) / count
                            - sum(abs(a - b) for a in row for b in row) / (2 * count * count))
        _close(result["sample_crps"], expected)
        _close(result["mean_crps"], sum(expected) / len(expected))
        assert result["units"] == {"sample_crps": args["data_unit"], "mean_crps": args["data_unit"]}
        if fixture_id == "synthetic_climpred":
            _close(result["sample_crps"], [0.5, 0.5, 0.5])
            _close(result["mean_crps"], 0.5)

    elif name == "ClimlabLayerHeatCapacity":
        coefficient = 1004 * 100 / 9.8 if args["medium"] == "atmosphere" else 1000 * 4181.3
        _close(result["areal_heat_capacity"], [coefficient * v for v in p["thickness"]])
        assert result["units"]["areal_heat_capacity"] == "J/(m2 K)"

    elif name == "AospyHybridPressure":
        expected = [[a + b * surface for a, b in zip(p["pressure_a_pa"], p["sigma_b"])]
                    for surface in p["surface_pressure_pa"]]
        _close(result["half_level_pressure"], expected)
        assert result["units"]["half_level_pressure"] == "Pa"
        if fixture_id == "synthetic_aospy":
            _close(result["half_level_pressure"], [[0, 50000, 100000], [0, 45000, 90000]])

    elif name == "OocgcmSurfaceSpiciness":
        coefficients = [
            [0, .77442, -.00585, -.000984, -.000206],
            [.051655, .002034, -.0002742, -.0000085, .0000136],
            [.00664783, -.00024681, -.00001428, .00003337, .000007894],
            [-.000054023, .000007326, .0000070036, -.0000030412, -.0000010853],
            [.0000003949, -.00000003029, -.00000038209, .00000010012, .000000047133],
            [-.000000000636, -.000000001309, .000000006048, -.0000000011409, -.0000000006676],
        ]
        expected = [sum(c * t ** i * (s - 35) ** j for i, row in enumerate(coefficients)
                        for j, c in enumerate(row))
                    for t, s in zip(p["potential_temperature_degC"], p["salinity_psu"])]
        _close(result["spiciness"], expected)
        assert result["units"]["spiciness"] == "kg/m3"
        if fixture_id == "synthetic_oocgcm":
            _close(result["spiciness"], [0, 0.54458641375])

    elif name == "OcgisHeatIndex":
        expected, valid = [], []
        for t, h in zip(p["temperature_degF"], p["relative_humidity_percent"]):
            good = t >= 80 and h >= 40
            valid.append(good)
            expected.append((-42.379 + 2.04901523 * t + 10.14333127 * h - .22475541 * t * h
                             - .00683783 * t * t - .05481717 * h * h + .00122874 * t * t * h
                             + .00085282 * t * h * h - .00000199 * t * t * h * h) if good else None)
        _close(result["heat_index"], expected)
        assert result["valid"] == valid
        assert result["units"]["heat_index"] == "degF"
        if fixture_id == "synthetic_ocgis":
            _close(result["heat_index"], [105.9220206, None, None])

    elif name == "PyrockoDoubleCoupleTensor":
        alpha, beta, gamma = math.radians(p["dip_deg"]), math.radians(p["strike_deg"]), -math.radians(p["rake_deg"])
        ca, cb, cg = math.cos(alpha), math.cos(beta), math.cos(gamma)
        sa, sb, sg = math.sin(alpha), math.sin(beta), math.sin(gamma)
        rotation = [[cb * cg - ca * sb * sg, sb * cg + ca * cb * sg, sa * sg],
                    [-cb * sg - ca * sb * cg, -sb * sg + ca * cb * cg, sa * cg],
                    [sa * sb, -sa * cb, ca]]
        scalar = p["scalar_moment_nm"]
        expected = [[-scalar * (rotation[0][i] * rotation[2][j] + rotation[2][i] * rotation[0][j])
                     for j in range(3)] for i in range(3)]
        _close(result["tensor_ned"], expected, atol=scalar * 1e-12)
        _close(result["scalar_moment"], scalar)
        _close(result["moment_magnitude"], math.log10(scalar * 1e7) / 1.5 - 10.7)
        _close(sum(result["tensor_ned"][i][i] for i in range(3)), 0, atol=scalar * 1e-12)
        _close(sum(v * v for row in result["tensor_ned"] for v in row), 2 * scalar * scalar)
        assert result["units"]["scalar_moment"] == "N m"

    elif name == "RsudpWindowAmplitude":
        values = [abs(v) for v in p["samples"]]
        for key, expected in (
            ("mean_absolute_amplitude", statistics.mean(values)),
            ("median_absolute_amplitude", statistics.median(values)),
            ("minimum_absolute_amplitude", min(values)),
            ("maximum_absolute_amplitude", max(values)),
        ):
            _close(result[key], expected)
            assert result["units"][key] == args["data_unit"]
        _close(result["duration"], len(values) / args["sample_rate_hz"])
        assert result["units"]["duration"] == "s"

    elif name == "SeismicZfpCompressCube":
        assert output_dir is not None and result["relative_path"] == "cube.sgz"
        artifact = Path(output_dir) / "cube.sgz"
        assert artifact.stat().st_size == result["compressed_bytes"] > 0
        assert result["shape"] == p["shape"]
        expected = [struct.unpack("<f", struct.pack("<f", v))[0] for v in p["values"]]
        decoded = result["decoded_values"]
        assert len(decoded) == len(expected)
        errors = [a - b for a, b in zip(decoded, expected)]
        _close(result["max_absolute_error"], max(map(abs, errors)))
        _close(result["rms_error"], math.sqrt(sum(e * e for e in errors) / len(errors)))
        assert max(map(abs, errors)) <= .001 * max(1, max(map(abs, expected)))
        from seismic_zfp.read import SgzReader
        ni, nx, nz = p["shape"]
        with SgzReader(str(artifact)) as reader:
            actual_file_values = reader.read_subvolume(0, ni, 0, nx, 0, nz, multithreading=False)
            _close(actual_file_values.ravel().tolist(), decoded)
            _close(list(reader.zslices), [i * args["sample_interval_ms"] for i in range(nz)])
        assert result["sample_interval"] == args["sample_interval_ms"]
        assert result["units"]["decoded_values"] == args["data_unit"]

    assert hashlib.sha256(Path(args["data_path"]).read_bytes()).hexdigest() == hashlib.sha256(raw).hexdigest()


def negative_cases():
    """Declarative probes for the coordinator; no adapter or backend is executed here."""
    prefix = "assets/earth-collection/weather_climate_seismic/"
    result = []
    for name in NAMES:
        for basename in ("synthetic_bad_json.json", "synthetic_bad_duplicate.json",
                         "synthetic_bad_nonfinite.json", "synthetic_bad_empty.json",
                         "synthetic_bad_utf8.json", "synthetic_bad_too_large.json"):
            result.append({"name": name, "overrides": {"data_path": prefix + basename},
                           "expected_code": "invalid_arguments",
                           "repeat_and_compare_error": True})
    for name, overrides in (
        ("WrfDestaggerGrid", {"stagger_dim": 4}),
        ("WrfDestaggerGrid", {"data_path": prefix + "synthetic_bad_shape.json"}),
        ("RainymotionPrecipitationScores", {"threshold_mm_h": 0}),
        ("MetSimPotentialEvapotranspiration", {"pressure_pa": 0}),
        ("MelodistDailyPrecipitationToHourly", {"start_date": "2001-02-30"}),
        ("ImproverRescaleForecastField", {"data_range": [1, 1]}),
        ("SkdownscaleQuantileBiasCorrection", {"data_unit": "unspecified"}),
        ("JamsDewPoint", {"output_unit": "F"}),
        ("XgcmStaggeredGridDiagnostics", {"spacing_m": 0}),
        ("ClimpredEnsembleCrps", {"data_unit": "unspecified"}),
        ("ClimlabLayerHeatCapacity", {"medium": "ocean", "thickness_unit": "hPa"}),
        ("RsudpWindowAmplitude", {"sample_rate_hz": 0}),
        ("SeismicZfpCompressCube", {"sample_interval_ms": 0}),
        ("SeismicZfpCompressCube", {"data_path": prefix + "synthetic_bad_shape.json"}),
    ):
        result.append({"name": name, "overrides": overrides, "expected_code": "invalid_arguments",
                       "repeat_and_compare_error": True})
    for name, basename in {"WrfDestaggerGrid":"synthetic_bad_wrf_axis","RainymotionPrecipitationScores":"synthetic_bad_rainymotion_lengths","MetSimPotentialEvapotranspiration":"synthetic_bad_metsim_lengths","MelodistDailyPrecipitationToHourly":"synthetic_bad_melodist_count","ImproverRescaleForecastField":"synthetic_bad_improver_count","SkdownscaleQuantileBiasCorrection":"synthetic_bad_skdownscale_count","JamsDewPoint":"synthetic_bad_jams_pressure","XgcmStaggeredGridDiagnostics":"synthetic_bad_xgcm_count","ClimpredEnsembleCrps":"synthetic_bad_climpred_members","ClimlabLayerHeatCapacity":"synthetic_bad_climlab_thickness","AospyHybridPressure":"synthetic_bad_aospy_levels","OocgcmSurfaceSpiciness":"synthetic_bad_oocgcm_salinity","OcgisHeatIndex":"synthetic_bad_ocgis_humidity","PyrockoDoubleCoupleTensor":"synthetic_bad_pyrocko_moment","RsudpWindowAmplitude":"synthetic_bad_rsudp_count","SeismicZfpCompressCube":"synthetic_bad_seismic_shape"}.items():
        result.append({"name": name, "overrides": {"data_path": prefix + basename + ".json"},
                       "expected_code": "invalid_arguments", "repeat_and_compare_error": True})
    return result

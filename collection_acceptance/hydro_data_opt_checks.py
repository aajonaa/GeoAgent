"""Independent numeric/content oracles and coordinator-callable acceptance helpers.

Nothing runs on import. run_case captures immutable file hashes before invocation.
"""
from collections import defaultdict
from copy import deepcopy
import csv
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

_NAMES = {
    "EarthHydroHyRiverFlowExceedance", "EarthHydroWetterdienstElevationAdjustment",
    "EarthHydroUlmoWaterMLValues", "EarthHydroFewsPiTimeSeries", "EarthHydroOpenradarRainRate",
    "EarthHydroCamelsStationSeries", "EarthHydroBomWaterMLObservations", "EarthHydroPastasExponentialImpulse",
    "EarthHydroHydropyChapmanBaseflow", "EarthHydroHydrostatsDailyClimatology", "EarthHydroHtimeseriesReadRecords",
    "EarthHydroEftsForecastEnsemble", "EarthHydroSpotpyNashSutcliffe", "EarthHydroClimateAccumulation",
    "EarthHydroPyemuExponentialCovariance", "EarthHydroHydrolmRegularizeDaily",
}


def _equal(actual, expected):
    if expected is None:
        assert actual is None, (actual, expected)
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert isinstance(actual, (int, float)) and not isinstance(actual, bool), actual
        assert math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-10), (actual, expected)
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), (actual, expected)
        for observed, reference in zip(actual, expected):
            _equal(observed, reference)
    else:
        assert actual == expected, (actual, expected)


def _unit(result, field, expected):
    assert result["units"][field] == expected, result["units"]


def _read(args):
    return Path(args["input_file"]).read_text(encoding="utf-8-sig")


def _utc(text):
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(dt.timezone.utc).isoformat()


def check(name: str, result: dict, args: dict, output_dir: Path | None):
    if name not in _NAMES:
        raise KeyError("Unknown hydro_data_opt operation: " + name)
    assert isinstance(result, dict) and isinstance(result["units"], dict)
    assert output_dir is None or not any(Path(output_dir).iterdir()), "JSON-only operation wrote files"
    if name == "EarthHydroHyRiverFlowExceedance":
        values = sorted((v for v in args["discharge_m3_s"] if v > args.get("threshold_m3_s", 0.001)), reverse=True)
        percentages = []
        for value in values:
            positions = [i + 1 for i, x in enumerate(values) if x == value]
            percentages.append(sum(positions) / len(positions) / len(values) * 100)
        _equal(result["discharge_m3_s"], values)
        _equal(result["exceedance_percent"], percentages)
        _equal(result["retained_count"], len(values))
        _unit(result, "discharge_m3_s", "m3/s")
        _unit(result, "exceedance_percent", "%")
    elif name == "EarthHydroWetterdienstElevationAdjustment":
        correction = args["lapse_degC_per_m"] * (args["target_elevation_m"] - args["station_elevation_m"])
        _equal(result["temperature_degC"], [x - correction for x in args["temperature_degC"]])
        _unit(result, "temperature_degC", "degC")
    elif name == "EarthHydroUlmoWaterMLValues":
        root = ET.fromstring(_read(args))
        ns = "{http://www.cuahsi.org/waterML/1.1/}"
        series = next(root.iter(ns + "timeSeries"))
        rows = list(series.iter(ns + "value"))
        missing = series.find(ns + "variable/" + ns + "noDataValue")
        sentinel = float(missing.text) if missing is not None else None
        values = [float(row.text) for row in rows]
        _equal(result["values"], [None if x == sentinel else x for x in values])
        _equal([_utc(x) for x in result["times"]], [_utc(row.attrib["dateTime"]) for row in rows])
        _equal(result["site_id"], series.find(ns + "sourceInfo/" + ns + "siteCode").text)
        _equal(result["qualifiers"], [row.attrib.get("qualifiers", "") for row in rows])
        _equal(result["count"], len(rows))
        _unit(result, "values", args["unit"])
    elif name == "EarthHydroFewsPiTimeSeries":
        root = ET.fromstring(_read(args))
        events = [x for x in root.iter() if x.tag.rsplit("}", 1)[-1] == "event"]
        events.sort(key=lambda x: x.attrib["date"] + "T" + x.attrib["time"])
        _equal(result["values"], [float(x.attrib["value"]) for x in events])
        _equal(result["flags"], [int(x.attrib["flag"]) for x in events])
        _equal([_utc(x) for x in result["times"]], [_utc(x.attrib["date"] + "T" + x.attrib["time"] + "+00:00") for x in events])
        _equal(result["count"], len(events))
        _unit(result, "values", args["unit"])
    elif name == "EarthHydroOpenradarRainRate":
        expected = [0.0 if x < 7 else (10 ** (min(x, 55) / 10) / 200) ** (5 / 8) for x in args["reflectivity_dbz"]]
        _equal(result["rain_rate_mm_h"], expected)
        _unit(result, "rain_rate_mm_h", "mm/h")
    elif name == "EarthHydroCamelsStationSeries":
        reader = csv.reader(io.StringIO(_read(args)))
        header = next(reader)
        rows = list(reader)
        expected = []
        for row in rows:
            expected.append([None if args.get("negative_is_missing", True) and float(x) < 0 else float(x) for x in row[3:]])
        _equal(result["station_ids"], header[3:])
        _equal(result["dates"], [dt.date(*(int(x) for x in row[:3])).isoformat() for row in rows])
        _equal(result["values"], expected)
        _unit(result, "values", args["unit"])
    elif name == "EarthHydroBomWaterMLObservations":
        root = ET.fromstring(_read(args))
        ns = "{http://www.opengis.net/waterml/2.0}"
        rows = list(root.iter(ns + "MeasurementTVP"))
        _equal(result["values"], [float(row.find(ns + "value").text) for row in rows])
        _equal(result["times"], [_utc(row.find(ns + "time").text).replace("+00:00", "Z") for row in rows])
        qualifier = -1
        for node in root.iter(ns + "defaultPointMetadata"):
            for child in node.iter():
                for value in child.attrib.values():
                    if "qualifier" in value:
                        qualifier = int(value.rsplit("/", 1)[-1])
        quality = []
        for row in rows:
            code = qualifier
            for child in row.iter():
                for value in child.attrib.values():
                    if "qualifier" in value:
                        code = int(value.rsplit("/", 1)[-1])
            quality.append(code)
        _equal(result["quality_codes"], quality)
        _equal(result["generated_at"], next(root.iter(ns + "generationDate")).text)
        _equal(result["count"], len(rows))
        _unit(result, "values", args["unit"])
    elif name == "EarthHydroPastasExponentialImpulse":
        expected = [args["gain"] / args["decay_days"] * math.exp(-x / args["decay_days"]) for x in args["time_days"]]
        _equal(result["impulse_per_day"], expected)
        _unit(result, "impulse_per_day", "1/day")
    elif name == "EarthHydroHydropyChapmanBaseflow":
        recession = args["recession_constant"]
        expected = [0.0]
        for flow in args["discharge_m3_s"][1:]:
            expected.append((recession * expected[-1] + (1 - recession) * flow) / (2 - recession))
        _equal(result["baseflow_m3_s"], expected)
        _unit(result, "baseflow_m3_s", "m3/s")
    elif name == "EarthHydroHydrostatsDailyClimatology":
        buckets = defaultdict(list)
        for date, value in zip(args["dates"], args["values"]):
            buckets[date[5:].replace("-", "/")].append(value)
        days = sorted(buckets)
        _equal(result["calendar_days"], days)
        _equal(result["mean_values"], [sum(buckets[day]) / len(buckets[day]) for day in days])
        _unit(result, "mean_values", args["unit"])
    elif name == "EarthHydroHtimeseriesReadRecords":
        rows = [row for row in csv.reader(io.StringIO(_read(args))) if row]
        _equal(result["values"], [float(row[1]) if row[1] else None for row in rows])
        _equal(result["flags"], [row[2] for row in rows])
        _equal(result["times"], [dt.datetime.strptime(row[0], "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc).isoformat() for row in rows])
        _equal(result["count"], len(rows))
        _unit(result, "values", args["unit"])
    elif name == "EarthHydroEftsForecastEnsemble":
        data = json.loads(_read(args))
        station = data["station_ids"].index(args["station_id"])
        _equal(result["member_values"], [member[station][:args["lead_count"]] for member in data["values"][args["time_index"]]])
        _equal(result["lead_hours"], data["lead_hours"][:args["lead_count"]])
        _equal(result["forecast_date"], data["times"][args["time_index"]])
        _equal(result["station_id"], args["station_id"])
        _unit(result, "member_values", data["unit"])
        _unit(result, "lead_hours", "hour")
    elif name == "EarthHydroSpotpyNashSutcliffe":
        observed, simulated = args["observed"], args["simulated"]
        mean = sum(observed) / len(observed)
        expected = 1 - sum((a - b) ** 2 for a, b in zip(observed, simulated)) / sum((a - mean) ** 2 for a in observed)
        _equal(result["nash_sutcliffe"], expected)
        _unit(result, "nash_sutcliffe", "dimensionless")
    elif name == "EarthHydroClimateAccumulation":
        scale, values = args["scale"], args["precipitation_mm"]
        expected = [None if i < scale - 1 else sum(values[i - scale + 1:i + 1]) for i in range(len(values))]
        _equal(result["accumulation_mm"], expected)
        _unit(result, "accumulation_mm", "mm")
    elif name == "EarthHydroPyemuExponentialCovariance":
        expected = [args["sill_m2"] / math.exp(x / args["range_m"]) if x / args["range_m"] < 700 else 0.0 for x in args["distance_m"]]
        _equal(result["covariance_m2"], expected)
        _unit(result, "covariance_m2", "m2")
    elif name == "EarthHydroHydrolmRegularizeDaily":
        dates = [dt.date.fromisoformat(x) for x in args["dates"]]
        expected_dates, expected_values = [], []
        for index in range(len(dates) - 1):
            gap = (dates[index + 1] - dates[index]).days
            for offset in range(gap):
                expected_dates.append((dates[index] + dt.timedelta(days=offset)).isoformat())
                if offset == 0:
                    expected_values.append(args["values"][index])
                elif offset <= args.get("max_gap_days", 7):
                    expected_values.append(args["values"][index] + (args["values"][index + 1] - args["values"][index]) * offset / gap)
                else:
                    expected_values.append(None)
        expected_dates.append(dates[-1].isoformat())
        expected_values.append(args["values"][-1])
        _equal(result["dates"], expected_dates)
        _equal(result["values"], expected_values)
        _unit(result, "values", args["unit"])


def capture_inputs(args):
    return {str(Path(value)): hashlib.sha256(Path(value).read_bytes()).hexdigest()
            for key, value in args.items() if key == "input_file"}


def assert_inputs_unchanged(snapshot):
    for filename, digest in snapshot.items():
        assert hashlib.sha256(Path(filename).read_bytes()).hexdigest() == digest, "Input file changed: " + filename


def run_case(invoke, name, args, output_dir=None):
    """invoke(name, args, output_dir) is provided by the coordinator, never a script."""
    snapshot = capture_inputs(args)
    original = deepcopy(args)
    try:
        result = invoke(name, args, output_dir)
        check(name, result, original, output_dir)
        assert args == original, "Operation mutated input arguments"
        return result
    finally:
        assert_inputs_unchanged(snapshot)


def negative_cases():
    p = "assets/earth-collection/hydro_data_opt/"
    return [
        {"name": "EarthHydroHyRiverFlowExceedance", "args": {"discharge_m3_s": [0, 0], "threshold_m3_s": 0.1}, "code": "invalid_arguments"},
        {"name": "EarthHydroWetterdienstElevationAdjustment", "args": {"temperature_degC": [10], "station_elevation_m": 0, "target_elevation_m": 100, "lapse_degC_per_m": 1}, "code": "invalid_arguments"},
        {"name": "EarthHydroUlmoWaterMLValues", "args": {"input_file": p + "synthetic_forbidden_dtd.xml", "unit": "m3/s"}, "code": "invalid_file"},
        {"name": "EarthHydroFewsPiTimeSeries", "args": {"input_file": p + "synthetic_fews_pi.xml", "unit": "mm"}, "code": "invalid_arguments"},
        {"name": "EarthHydroOpenradarRainRate", "args": {"reflectivity_dbz": [101]}, "code": "invalid_arguments"},
        {"name": "EarthHydroCamelsStationSeries", "args": {"input_file": p + "synthetic_camels.csv", "unit": "invented"}, "code": "invalid_arguments"},
        {"name": "EarthHydroBomWaterMLObservations", "args": {"input_file": p + "synthetic_bom_waterml2.xml", "unit": "mm"}, "code": "invalid_arguments"},
        {"name": "EarthHydroPastasExponentialImpulse", "args": {"time_days": [0, 1], "gain": 1, "decay_days": 0}, "code": "invalid_arguments"},
        {"name": "EarthHydroHydropyChapmanBaseflow", "args": {"discharge_m3_s": [1, 2], "recession_constant": 1}, "code": "invalid_arguments"},
        {"name": "EarthHydroHydrostatsDailyClimatology", "args": {"dates": ["2020-01-01", "2020-01-02"], "values": [1], "unit": "m3/s"}, "code": "invalid_arguments"},
        {"name": "EarthHydroHtimeseriesReadRecords", "args": {"input_file": p + "synthetic_duplicate_records.csv", "unit": "m3/s", "timezone": "UTC"}, "code": "invalid_file"},
        {"name": "EarthHydroEftsForecastEnsemble", "args": {"input_file": p + "synthetic_efts.json", "station_id": "ABSENT", "time_index": 0, "lead_count": 2}, "code": "invalid_arguments"},
        {"name": "EarthHydroSpotpyNashSutcliffe", "args": {"observed": [1, 1], "simulated": [1, 2], "unit": "m3/s"}, "code": "invalid_arguments"},
        {"name": "EarthHydroClimateAccumulation", "args": {"precipitation_mm": [1, 2], "scale": 3}, "code": "invalid_arguments"},
        {"name": "EarthHydroPyemuExponentialCovariance", "args": {"distance_m": [0, 1], "range_m": 0, "sill_m2": 1}, "code": "invalid_arguments"},
        {"name": "EarthHydroHydrolmRegularizeDaily", "args": {"dates": ["1900-01-01", "2100-01-01"], "values": [1, 2], "unit": "m3/s", "max_gap_days": 7}, "code": "resource_limit"},
        {"name": "EarthHydroOpenradarRainRate", "args": {"reflectivity_dbz": [0] * 10001}, "code": "invalid_arguments"},
        {"name": "EarthHydroUlmoWaterMLValues", "args": {"input_file": p + "synthetic_oversize.txt", "unit": "m3/s"}, "code": "resource_limit"},
        {"name": "EarthHydroClimateAccumulation", "args": {"precipitation_mm": [1] * 6000, "scale": 366}, "code": "invalid_arguments"},
    ]


def run_negative_cases(invoke, resolve_args=lambda args: args):
    """Coordinator supplies task-path resolution; assert exact stable repeated errors."""
    for case in negative_cases():
        args = resolve_args(deepcopy(case["args"]))
        before = capture_inputs(args)
        seen = []
        for _ in range(2):
            try:
                invoke(case["name"], deepcopy(args), None)
            except Exception as error:
                assert getattr(error, "code", None) == case["code"], (case["name"], error)
                seen.append((error.code, str(error)))
            else:
                raise AssertionError("Invalid input was accepted: " + case["name"])
        assert seen[0] == seen[1], "Nondeterministic error response"
        assert_inputs_unchanged(before)

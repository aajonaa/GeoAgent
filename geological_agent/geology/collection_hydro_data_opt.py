"""Bounded offline adapters. Third-party and vendored imports are operation-local."""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import math
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from .collection_contracts import operation, reject

_LIMIT = 10000
_FILE_LIMIT = 2 * 1024 * 1024
_UNITS = {"m3/s", "ML/day", "mm", "mm/day", "m", "degC", "K", "dimensionless"}


def _number(value, name, low=-1e12, high=1e12):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        reject(name + " must be a finite number", code="invalid_arguments")
    if not low <= value <= high:
        reject(name + " is outside its allowed bounds", code="invalid_arguments")
    return float(value)


def _integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        reject(name + " is outside its integer bounds", code="invalid_arguments")
    return value


def _array(value, name, low=-1e12, high=1e12, minimum=1):
    if not isinstance(value, list) or not minimum <= len(value) <= _LIMIT:
        reject(name + " has an invalid length", code="invalid_arguments")
    return [_number(x, name, low, high) for x in value]


def _unit(args):
    unit = args.get("unit")
    if unit not in _UNITS:
        reject("An explicit supported physical unit is required", code="invalid_arguments")
    return unit


def _dates(values):
    if not isinstance(values, list) or not 1 <= len(values) <= _LIMIT:
        reject("dates has an invalid length", code="invalid_arguments")
    result = []
    for value in values:
        try:
            if not isinstance(value, str) or len(value) != 10:
                raise ValueError()
            date = dt.date.fromisoformat(value)
        except (ValueError, TypeError):
            reject("dates must contain YYYY-MM-DD dates", code="invalid_arguments")
        if not 1900 <= date.year <= 2100:
            reject("dates must lie between 1900 and 2100", code="invalid_arguments")
        result.append(date)
    if any(b <= a for a, b in zip(result, result[1:])):
        reject("dates must be strictly increasing and unique", code="invalid_arguments")
    return result


def _text(path):
    try:
        source = Path(path)
        if not source.is_file():
            raise OSError()
        with source.open("rb") as stream:
            raw = stream.read(_FILE_LIMIT + 1)
    except (OSError, TypeError, ValueError):
        reject("Input must be a readable local file snapshot", code="invalid_file")
    if len(raw) > _FILE_LIMIT:
        reject("Input exceeds the 2 MiB file bound", code="resource_limit")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        reject("Input must be UTF-8 text", code="invalid_file")
    if "\x00" in text:
        reject("NUL bytes are not supported", code="invalid_file")
    return text


def _xml(text):
    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        reject("XML DTDs and entity declarations are forbidden", code="invalid_file")
    parser = ET.XMLPullParser(events=("start", "end"))
    root, depth, count = None, 0, 0
    try:
        for pos in range(0, len(text), 4096):
            parser.feed(text[pos:pos + 4096])
            for event, element in parser.read_events():
                if event == "start":
                    if root is None:
                        root = element
                    depth += 1
                    count += 1
                    if depth > 32 or count > 50000:
                        reject("XML exceeds its depth/node bound", code="resource_limit")
                else:
                    depth -= 1
        parser.close()
    except ET.ParseError:
        reject("Malformed XML input", code="invalid_file")
    if root is None:
        reject("XML input is empty", code="invalid_file")
    return root


def _file_number(value, allow_missing=False):
    if allow_missing and (value is None or value == ""):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        reject("File contains a nonnumeric measurement", code="invalid_file")
    if not math.isfinite(number) or abs(number) > 1e12:
        reject("File measurements must be finite and bounded", code="invalid_file")
    return number


def _clean(values):
    result = []
    for value in values:
        number = float(value)
        if math.isnan(number):
            result.append(None)
        elif not math.isfinite(number):
            reject("Upstream produced a nonfinite result", code="algorithm_error")
        else:
            result.append(number)
    return result


@operation("EarthHydroHyRiverFlowExceedance")
def hyriver_flow_exceedance(args, output_dir=None):
    flow = _array(args["discharge_m3_s"], "discharge_m3_s", 0, 1e9)
    threshold = _number(args.get("threshold_m3_s", 0.001), "threshold_m3_s", 0, 1e9)
    if not any(x > threshold for x in flow):
        reject("At least one discharge must exceed the threshold", code="invalid_arguments")
    import pandas as pd
    from .collection_vendor.hydro_data_opt.hyriver import exceedance
    table = exceedance(pd.Series(flow, name="flow"), threshold=threshold).dropna()
    return {"discharge_m3_s": table["flow"].tolist(),
            "exceedance_percent": table["flow_rank"].tolist(), "retained_count": len(table),
            "units": {"discharge_m3_s": "m3/s", "exceedance_percent": "%", "retained_count": "count"}}


@operation("EarthHydroWetterdienstElevationAdjustment")
def wetterdienst_elevation_adjustment(args, output_dir=None):
    values = _array(args["temperature_degC"], "temperature_degC", -100, 100)
    station = _number(args["station_elevation_m"], "station_elevation_m", -500, 9000)
    target = _number(args["target_elevation_m"], "target_elevation_m", -500, 9000)
    lapse = _number(args["lapse_degC_per_m"], "lapse_degC_per_m", -0.02, 0.02)
    import numpy as np
    from .collection_vendor.hydro_data_opt.wetterdienst import reduce_to_elevation
    adjusted = reduce_to_elevation(np.array(values), lapse, station, target)
    return {"temperature_degC": adjusted.tolist(),
            "units": {"temperature_degC": "degC"}}


@operation("EarthHydroUlmoWaterMLValues")
def ulmo_waterml_values(args, output_dir=None):
    unit = _unit(args)
    text = _text(args["input_file"])
    root = _xml(text)
    ns = "{http://www.cuahsi.org/waterML/1.1/}"
    series = list(root.iter(ns + "timeSeries"))
    if len(series) != 1 or len(series[0].findall(ns + "values")) != 1:
        reject("Supply exactly one WaterML 1.1 timeSeries and one values block", code="invalid_file")
    count = sum(1 for _ in series[0].iter(ns + "value"))
    if not 1 <= count <= _LIMIT:
        reject("WaterML must contain 1 to 10000 measurements", code="resource_limit")
    from .collection_vendor.hydro_data_opt.ulmo_waterml import parse_site_values
    try:
        parsed = parse_site_values(io.BytesIO(text.encode("utf-8")), ns)
        if len(parsed) != 1:
            raise ValueError()
        code, data = next(iter(parsed.items()))
        declared = data["variable"].get("units", {}).get("abbreviation")
        rows = data["values"]
        site = str(data["site"]["code"])
        missing = data["variable"].get("no_data_value")
    except (ValueError, TypeError, KeyError, AttributeError, IndexError):
        reject("Unsupported or incomplete WaterML 1.1 record structure", code="invalid_file")
    if declared != unit:
        reject("Declared unit must match the WaterML unit abbreviation", code="invalid_arguments")
    nodata = _file_number(missing) if missing is not None else None
    values = [_file_number(r["value"]) for r in rows]
    if nodata is not None:
        values = [None if x == nodata else x for x in values]
    return {"site_id": site, "variable_code": str(code), "times": [r["datetime"] for r in rows],
            "values": values, "qualifiers": [str(r.get("qualifiers", "")) for r in rows],
            "count": len(rows), "units": {"values": unit, "times": "ISO 8601 with offset", "count": "count"}}


@operation("EarthHydroFewsPiTimeSeries")
def fews_pi_time_series(args, output_dir=None):
    unit = _unit(args)
    text = _text(args["input_file"])
    root = _xml(text)
    # The unchanged upstream parser has defective negative-offset handling.
    # This operation explicitly accepts UTC records only.
    local = lambda name: [e for e in root.iter() if e.tag.rsplit("}", 1)[-1] == name]
    zones, series = local("timeZone"), local("series")
    if len(zones) != 1 or zones[0].text is None or zones[0].text.strip() not in {"0", "0.0"} or len(series) != 1:
        reject("Supply one unprefixed FEWS-PI series with an explicit UTC timeZone=0", code="invalid_file")
    if ":" in root.tag.rsplit("}", 1)[-1] or root.tag.rsplit("}", 1)[-1] != "TimeSeries":
        reject("Expected a FEWS-PI TimeSeries root", code="invalid_file")
    events = local("event")
    if not 1 <= len(events) <= _LIMIT:
        reject("FEWS-PI must contain 1 to 10000 events", code="resource_limit")
    headers = {e.tag.rsplit("}", 1)[-1]: e.text for e in series[0].findall("./{*}header/*")}
    for key in ("moduleInstanceId", "locationId", "stationName", "parameterId", "units"):
        if not headers.get(key):
            reject("FEWS-PI requires complete series header fields", code="invalid_file")
    if headers["units"] != unit:
        reject("Declared unit must match the FEWS-PI unit", code="invalid_arguments")
    for event in events:
        if not {"date", "time", "value", "flag", "user"}.issubset(event.attrib):
            reject("FEWS-PI events require date, time, value, flag and explicit user attributes", code="invalid_file")
        _file_number(event.attrib["value"])
        try:
            dt.datetime.fromisoformat(event.attrib["date"] + "T" + event.attrib["time"])
            int(event.attrib["flag"])
        except (ValueError, TypeError):
            reject("FEWS-PI event timestamps or flags are invalid", code="invalid_file")
    from .collection_vendor.hydro_data_opt.fews_pi import read_timeseries_response
    try:
        frame = read_timeseries_response(text, "UTC", header="longform")
    except (ValueError, TypeError, KeyError, AttributeError, IndexError):
        reject("Unsupported FEWS-PI record structure", code="invalid_file")
    return {"times": [x.isoformat() for x in frame.index], "values": frame["value"].tolist(),
            "flags": [int(x) for x in frame["flag"]], "location_id": headers["locationId"],
            "parameter_id": headers["parameterId"], "count": len(frame),
            "units": {"values": unit, "times": "ISO 8601 UTC", "flags": "FEWS quality code", "count": "count"}}


@operation("EarthHydroOpenradarRainRate")
def openradar_rain_rate(args, output_dir=None):
    reflectivity = _array(args["reflectivity_dbz"], "reflectivity_dbz", -100, 100)
    import numpy as np
    from .collection_vendor.hydro_data_opt.openradar import Rain
    values = Rain(np.array(reflectivity)).get()
    return {"rain_rate_mm_h": values.tolist(), "units": {"rain_rate_mm_h": "mm/h"}}


@operation("EarthHydroCamelsStationSeries")
def camels_station_series(args, output_dir=None):
    unit = _unit(args)
    text = _text(args["input_file"])
    try:
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
        rows = list(reader)
    except (csv.Error, StopIteration):
        reject("CAMELS CSV is malformed", code="invalid_file")
    if len(header) != len(set(header)) or header[:3] != ["year", "month", "day"] or not 1 <= len(header) - 3 <= 16:
        reject("CAMELS CSV requires year,month,day and 1 to 16 unique station columns", code="invalid_file")
    if not 2 <= len(rows) <= _LIMIT:
        reject("CAMELS CSV requires 2 to 10000 rows", code="resource_limit")
    dates = []
    for row in rows:
        if len(row) != len(header):
            reject("CAMELS CSV has inconsistent row widths", code="invalid_file")
        try:
            dates.append(dt.date(*(int(x) for x in row[:3])).isoformat())
        except (ValueError, TypeError):
            reject("CAMELS calendar fields must be valid integer dates", code="invalid_file")
        for x in row[3:]:
            _file_number(x)
    _dates(dates)
    import numpy as np
    from .collection_vendor.hydro_data_opt.camels import load_csv_stations_tseries, negative_is_missing
    missing = negative_is_missing if args.get("negative_is_missing", True) else None
    try:
        data = load_csv_stations_tseries(io.StringIO(text), is_missing=missing, units=unit, dtype="float64")
    except (ValueError, TypeError, KeyError, IndexError):
        reject("Unsupported CAMELS CSV contents", code="invalid_file")
    return {"dates": dates, "station_ids": [str(x) for x in data.coords["station_id"].values],
            "values": [_clean(row) for row in data.values],
            "units": {"values": unit, "dates": "YYYY-MM-DD UTC calendar date"}}


@operation("EarthHydroBomWaterMLObservations")
def bom_waterml_observations(args, output_dir=None):
    unit = _unit(args)
    text = _text(args["input_file"])
    root = _xml(text)
    ns = "{http://www.opengis.net/waterml/2.0}"
    observations = list(root.iter("{http://www.opengis.net/sos/2.0}observationData"))
    measurements = list(root.iter(ns + "MeasurementTVP"))
    if len(observations) != 1 or not 1 <= len(measurements) <= _LIMIT:
        reject("Supply one SOS observationData with 1 to 10000 WaterML 2.0 measurements", code="invalid_file")
    series = list(observations[0].iter(ns + "MeasurementTimeseries"))
    if len(series) != 1 or list(series[0].iter(ns + "MeasurementTVP")) != measurements:
        reject("WaterML units must bind to one complete measurement timeseries", code="invalid_file")
    defaults = series[0].findall(ns + "defaultPointMetadata")
    if len(defaults) != 1:
        reject("One explicit WaterML default unit block is required", code="invalid_file")
    default_units = defaults[0].findall(ns + "DefaultTVPMeasurementMetadata/" + ns + "uom")
    if len(default_units) != 1 or not default_units[0].get("code") or list(defaults[0].iter(ns + "uom")) != default_units:
        reject("WaterML default metadata requires one complete literal unit code", code="invalid_file")
    source_unit = default_units[0].get("code")
    bound_units = set(default_units)
    for row in measurements:
        value = row.find(ns + "value")
        if value is None:
            reject("Every WaterML 2.0 measurement requires a value", code="invalid_file")
        _file_number(value.text)
        metadata = row.findall(ns + "metadata")
        if len(metadata) > 1:
            reject("Duplicate WaterML point metadata is ambiguous", code="invalid_file")
        point_units = list(metadata[0].iter(ns + "uom")) if metadata else []
        if len(point_units) > 1 or list(row.iter(ns + "uom")) != point_units:
            reject("WaterML point units must have one unambiguous metadata binding", code="invalid_file")
        if point_units and point_units[0].get("code") != source_unit:
            reject("WaterML point units must exactly match the default unit; no conversion is performed", code="invalid_file")
        bound_units.update(point_units)
    if set(root.iter(ns + "uom")) != bound_units:
        reject("WaterML contains unit metadata outside the bound timeseries", code="invalid_file")
    if source_unit != unit:
        reject("Declared unit must match the original WaterML 2.0 unit code", code="invalid_arguments")
    from .collection_vendor.hydro_data_opt.bom_waterml import BomWater
    try:
        parsed = BomWater().parse_data(SimpleNamespace(text=text), stations=None)
        if len(parsed) != 1:
            raise ValueError()
        station, data = next(iter(parsed.items()))
        declared = data.attrs["units"]
        prop = data.attrs["property"]
        values = data[prop + " [" + declared + "]"].values
        times = data.time.to_index()
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError):
        reject("Unsupported or incomplete WaterML 2.0 observation structure", code="invalid_file")
    # The unchanged upstream parser applies URL-tail extraction to every
    # metadata field, including literal UCUM codes such as m3/s and ML/day.
    # Use its actual column for the unchanged values, but bind output units
    # to the original XML. This corrects metadata only, never numeric values.
    if declared != source_unit.rsplit("/", 1)[-1]:
        reject("Upstream unit metadata differs from its reviewed parsing behavior", code="algorithm_error")
    return {"station_id": station, "property": prop, "times": [x.isoformat() + "Z" for x in times],
            "values": _clean(values), "quality_codes": [int(x) for x in data["Quality"].values],
            "generated_at": str(data.attrs["generated_date"]), "count": len(values),
            "units": {"values": unit, "times": "ISO 8601 UTC", "quality_codes": "BOM qualifier code", "count": "count"}}


@operation("EarthHydroPastasExponentialImpulse")
def pastas_exponential_impulse(args, output_dir=None):
    times = _array(args["time_days"], "time_days", 0, 1e6)
    gain = _number(args["gain"], "gain", -1e6, 1e6)
    decay = _number(args["decay_days"], "decay_days", 1e-6, 1e6)
    import numpy as np
    from .collection_vendor.hydro_data_opt.pastas import Exponential
    values = Exponential.impulse(np.array(times), [gain, decay])
    return {"impulse_per_day": values.tolist(), "units": {"impulse_per_day": "1/day"}}


@operation("EarthHydroHydropyChapmanBaseflow")
def hydropy_chapman_baseflow(args, output_dir=None):
    flow = _array(args["discharge_m3_s"], "discharge_m3_s", 0, 1e9, minimum=2)
    recession = _number(args["recession_constant"], "recession_constant", 0, 0.999999)
    import pandas as pd
    from .collection_vendor.hydro_data_opt.hydropy import get_baseflow_chapman
    values = get_baseflow_chapman(pd.Series(flow), recession)
    return {"baseflow_m3_s": values.iloc[:, 0].tolist(),
            "units": {"baseflow_m3_s": "m3/s"}}


@operation("EarthHydroHydrostatsDailyClimatology")
def hydrostats_daily_climatology(args, output_dir=None):
    dates = _dates(args["dates"])
    values = _array(args["values"], "values")
    unit = _unit(args)
    if len(dates) != len(values):
        reject("dates and values must have equal length", code="invalid_arguments")
    import pandas as pd
    from .collection_vendor.hydro_data_opt.hydrostats import daily_average
    frame = pd.DataFrame({"value": values}, index=pd.to_datetime(dates))
    result = daily_average(frame, rolling=False)
    return {"calendar_days": result.index.tolist(), "mean_values": result["value"].tolist(),
            "units": {"calendar_days": "MM/DD", "mean_values": unit}}


@operation("EarthHydroHtimeseriesReadRecords")
def htimeseries_read_records(args, output_dir=None):
    unit = _unit(args)
    if args.get("timezone") != "UTC":
        reject("The source records must explicitly use UTC", code="invalid_arguments")
    text = _text(args["input_file"])
    try:
        rows = [row for row in csv.reader(io.StringIO(text)) if row]
    except csv.Error:
        reject("Malformed HTimeseries records CSV", code="invalid_file")
    if not 1 <= len(rows) <= _LIMIT:
        reject("HTimeseries requires 1 to 10000 records", code="resource_limit")
    for row in rows:
        if len(row) != 3 or len(row[0]) != 16 or len(row[2]) > 256:
            reject("Records require YYYY-MM-DD HH:MM,value,flags", code="invalid_file")
        try:
            dt.datetime.strptime(row[0], "%Y-%m-%d %H:%M")
        except ValueError:
            reject("Invalid HTimeseries timestamp", code="invalid_file")
        _file_number(row[1], allow_missing=True)
    from .collection_vendor.hydro_data_opt.htimeseries import TimeseriesRecordsReader
    reader = TimeseriesRecordsReader(None, None, None, dt.timezone.utc)
    try:
        frame = reader._read_data_from_stream(io.StringIO(text))
        reader._check_there_are_no_duplicates(frame)
    except (ValueError, TypeError, IndexError):
        reject("HTimeseries records are invalid or contain duplicate timestamps", code="invalid_file")
    return {"times": [x.isoformat() for x in frame.index], "values": _clean(frame["value"]),
            "flags": frame["flags"].tolist(), "count": len(frame),
            "units": {"values": unit, "times": "ISO 8601 UTC", "flags": "HTimeseries flag text", "count": "count"}}


@operation("EarthHydroEftsForecastEnsemble")
def efts_forecast_ensemble(args, output_dir=None):
    text = _text(args["input_file"])
    try:
        data = json.loads(text, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(data, dict) or set(data) != {"synthetic", "unit", "times", "station_ids", "lead_hours", "values"}:
            raise ValueError()
        unit = data["unit"]
        if unit not in _UNITS or not isinstance(data["synthetic"], bool):
            raise ValueError()
        times = _dates(data["times"])
        stations, leads, tensor = data["station_ids"], data["lead_hours"], data["values"]
        if not isinstance(stations, list) or not 1 <= len(stations) <= 32 or any(not isinstance(s, str) or not 1 <= len(s) <= 64 for s in stations) or len(set(stations)) != len(stations):
            raise ValueError()
        if not isinstance(leads, list) or not 1 <= len(leads) <= 366 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 10000 for v in leads) or any(b <= a for a, b in zip(leads, leads[1:])):
            raise ValueError()
        if not isinstance(tensor, list) or len(tensor) != len(times) or len(times) > 32 or not isinstance(tensor[0], list) or not 1 <= len(tensor[0]) <= 32:
            raise ValueError()
        ensemble_size = len(tensor[0])
        if len(times) * ensemble_size * len(stations) * len(leads) > 100000:
            reject("EFTS tensor exceeds 100000 cells", code="resource_limit")
        for time_slice in tensor:
            if not isinstance(time_slice, list) or len(time_slice) != ensemble_size:
                raise ValueError()
            for member in time_slice:
                if not isinstance(member, list) or len(member) != len(stations):
                    raise ValueError()
                for sequence in member:
                    if not isinstance(sequence, list) or len(sequence) != len(leads):
                        raise ValueError()
                    for x in sequence:
                        if isinstance(x, bool):
                            raise ValueError()
                        _file_number(x)
    except (ValueError, TypeError, KeyError, IndexError, RecursionError):
        reject("EFTS input must match the bounded time,member,station,lead JSON layout", code="invalid_file")
    time_index = _integer(args["time_index"], "time_index", 0, 31)
    lead_count = _integer(args["lead_count"], "lead_count", 1, 366)
    station = args["station_id"]
    if time_index >= len(times) or station not in stations or lead_count > len(leads):
        reject("Requested EFTS station, forecast time or lead count is absent", code="invalid_arguments")
    import numpy as np
    import pandas as pd
    import xarray as xr
    from .collection_vendor.hydro_data_opt.efts import EftsDataSet
    array = xr.DataArray(np.asarray(tensor, dtype=float), dims=("time", "ens_member", "station", "lead_time"),
                         coords={"time": pd.to_datetime(times), "ens_member": range(ensemble_size),
                                 "station": range(len(stations)), "station_id": ("station", stations), "lead_time": leads})
    wrapper = EftsDataSet()
    wrapper.data = xr.Dataset({"rain_sim": array})
    wrapper.ensemble_member_dim_name = "ens_member"
    wrapper.lead_time_dim_name = "lead_time"
    selected = wrapper.get_ensemble_forecasts(identifier=station, dimension_id="station_id",
                                               start_time=wrapper.data.time.values[time_index], lead_time_count=lead_count)
    return {"station_id": station, "forecast_date": times[time_index].isoformat(),
            "lead_hours": leads[:lead_count], "member_values": selected.values.tolist(),
            "units": {"member_values": unit, "lead_hours": "hour", "forecast_date": "YYYY-MM-DD UTC"}}


@operation("EarthHydroSpotpyNashSutcliffe")
def spotpy_nash_sutcliffe(args, output_dir=None):
    observed = _array(args["observed"], "observed", minimum=2)
    simulated = _array(args["simulated"], "simulated", minimum=2)
    _unit(args)
    if len(observed) != len(simulated) or max(observed) == min(observed):
        reject("Paired series must have equal length and nonconstant observations", code="invalid_arguments")
    from .collection_vendor.hydro_data_opt.spotpy import nashsutcliffe
    score = float(nashsutcliffe(observed, simulated))
    if not math.isfinite(score):
        reject("Nash-Sutcliffe efficiency is numerically undefined", code="invalid_arguments")
    return {"nash_sutcliffe": score, "units": {"nash_sutcliffe": "dimensionless"}}


@operation("EarthHydroClimateAccumulation")
def climate_accumulation(args, output_dir=None):
    rainfall = _array(args["precipitation_mm"], "precipitation_mm", 0, 1e6)
    scale = _integer(args["scale"], "scale", 1, 366)
    if scale > len(rainfall) or len(rainfall) * scale > 2000000:
        reject("Scale must fit the record and the two-million-work-unit bound", code="invalid_arguments")
    import numpy as np
    from .collection_vendor.hydro_data_opt.climate import sum_to_scale
    values = sum_to_scale(np.array(rainfall), scale)
    return {"accumulation_mm": _clean(values), "units": {"accumulation_mm": "mm"}}


@operation("EarthHydroPyemuExponentialCovariance")
def pyemu_exponential_covariance(args, output_dir=None):
    distance = _array(args["distance_m"], "distance_m", 0, 1e7)
    scale = _number(args["range_m"], "range_m", 1e-6, 1e7)
    sill = _number(args["sill_m2"], "sill_m2", 0, 1e12)
    import numpy as np
    from .collection_vendor.hydro_data_opt.pyemu import ExpVario
    variogram = ExpVario()
    variogram.a, variogram.contribution = scale, sill
    values = variogram._h_function(np.array(distance))
    return {"covariance_m2": values.tolist(), "units": {"covariance_m2": "m2"}}


@operation("EarthHydroHydrolmRegularizeDaily")
def hydrolm_regularize_daily(args, output_dir=None):
    dates = _dates(args["dates"])
    values = _array(args["values"], "values", minimum=2)
    unit = _unit(args)
    gap = _integer(args.get("max_gap_days", 7), "max_gap_days", 1, 365)
    if len(dates) != len(values):
        reject("dates and values must have equal length", code="invalid_arguments")
    if (dates[-1] - dates[0]).days + 1 > _LIMIT:
        reject("Daily regularization would exceed 10000 output rows", code="resource_limit")
    import pandas as pd
    from .collection_vendor.hydro_data_opt.hydrolm import tsreg
    frame = pd.DataFrame({"value": values}, index=pd.to_datetime(dates))
    result = tsreg(frame, freq="D", interp="linear", maxgap=gap)
    return {"dates": [x.date().isoformat() for x in result.index], "values": _clean(result["value"]),
            "units": {"dates": "YYYY-MM-DD UTC calendar date", "values": unit}}

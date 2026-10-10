"""Native scientific operations recovered from the GeoToolAgent source inventory.

Named object arguments and structured results, validated by the canonical
catalog. No text adapters, benchmark-answer lookup or implicit data locations.
The supplied GeoToolAgent algorithms are MIT, Copyright (c) 2024 Jing Yu.
The IDW algorithm is retained with explicit measurement and grid contracts.
"""
from __future__ import annotations
import base64
import csv
from datetime import datetime, timezone
import hashlib
import html
import io
import json
import math
from pathlib import Path
import re
import uuid

from jsonschema import ValidationError
from ..source_contracts import arguments, result
from .scientific_tools import ScientificToolError

RECOVERED = (
    "DeepEarthQueryLITHO1", "DeepEarthQuerySEMUCB", "DeepEarthQueryUSGSCatalog",
    "DeepEarthGetUSGSEvent", "DeepEarthSampleEventModels", "GeoBigDataExecuteGeoSPARQL",
    "ClimateQueryDeepTime", "ClimateQueryPresentMean", "ClimateQueryFutureSSP",
    "EnergyFacilityDistance", "EnergyMineralSiteDistance", "EnergyNearestFacility",
    "EnergyCapacityValue", "EnergyNearestMineralSite", "EnergyCountryRenewableSummary",
    "EnergyCapacityGrowth", "EnergyTransitionMetrics", "EnergyRegionalOverlaySummary",
    "OceanMonthlyGridValue", "OceanProfileValue", "OceanCruiseQC", "OceanStationDistance",
    "OceanAnnualCarbonSummary", "OceanVerticalProfileDifference", "OceanRegionalMapSummary",
    "OceanSurfaceDeepMatch", "OceanProfileDeduplication", "DeepTimeInterpolateIDW",
    "DeepTimeRasterAlgebra", "CCSInterpolateIDW", "CCSRasterAlgebra",
    "RemoteSensingCloudMask", "RemoteSensingNDTI", "USGS 地震数据获取", "地震事件地图可视化",
)


def fail(message, code="invalid_data"):
    raise ScientificToolError(code, message)


def number(value):
    try:
        if isinstance(value, bool):
            raise ValueError()
        value = float(value)
        if not math.isfinite(value):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        fail("Expected a finite numeric observation, not missing/NaN/infinity.")


def table(path, fields):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            fail("CSV requires a unique header.")
        missing = set(fields) - set(reader.fieldnames)
        if missing:
            fail("Missing CSV fields: " + ", ".join(sorted(missing)))
        rows = list(reader)
    if any(None in row or any(v is None for v in row.values()) for row in rows):
        fail("Malformed CSV row.")
    return rows


def select(rows, **filters):
    return [row for row in rows if all(str(row[k]) == str(v) for k, v in filters.items())]


def one(rows):
    if len(rows) != 1:
        fail("Expected exactly one observation; found " + str(len(rows)) + ".")
    return rows[0]


def point(row):
    lat, lon = number(row["latitude"]), number(row["longitude"])
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        fail("Coordinates must be WGS84 latitude/longitude in degrees.")
    return lat, lon


def distance(a, b):
    lat1, lon1 = point(a)
    lat2, lon2 = point(b)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    v = math.sin((p2-p1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(math.radians(lon2-lon1)/2)**2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1., max(0., v))))


def nearest(rows, origin):
    if not rows:
        fail("No matching observations; do not substitute another dataset.")
    scored = [(distance(origin, row), index, row) for index, row in enumerate(rows)]
    d, _, row = min(scored, key=lambda item: (item[0], item[1]))
    return row, d


def bounds(rows, bbox):
    west, south, east, north = bbox
    if not -180 <= west < east <= 180 or not -90 <= south < north <= 90:
        fail("Ordered WGS84 bbox required; split antimeridian crossing explicitly.")
    return [r for r in rows if west <= point(r)[1] <= east and south <= point(r)[0] <= north]


def timestamp(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except ValueError:
        fail("Date/time must be ISO 8601.")


def nonempty(rows):
    if not rows:
        fail("No observations match the requested scope.")
    return rows


def numeric_mean(rows, field):
    values = [number(r[field]) for r in nonempty(rows)]
    return math.fsum(values) / len(values)


def unique(rows, fields):
    keys = [tuple(r[k] for k in fields) for r in rows]
    if len(keys) != len(set(keys)):
        fail("Duplicate observation keys: " + ", ".join(fields))
    return rows


def source(path):
    path = Path(path)
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path), "sha256": checksum, "size_bytes": path.stat().st_size}


def output_path(root, name):
    if root is None:
        fail("An explicit output_dir is required.", "invalid_arguments")
    folder = Path(root) / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=False)
    return folder / name


def deep(name, a):
    path = a["dataset_path"]
    if name == "DeepEarthQueryLITHO1":
        field = {"CRUST3-BOTTOM": "moho_depth_km", "LAB": "lab_depth_km"}[a["layer"]]
        rows = unique(table(path, ["node_index", "latitude", "longitude", field]), ["node_index"])
        row, d = nearest(rows, a)
        return {"node_index": row["node_index"], "latitude": point(row)[0], "longitude": point(row)[1],
                "distance_km": d, "value_km": number(row[field]), "layer": a["layer"],
                "sampling": "nearest supplied node; no interpolation"}
    if name == "DeepEarthQuerySEMUCB":
        rows = table(path, ["latitude", "longitude", "depth_km", "dlnvs_percent"])
        rows = [r for r in rows if number(r["depth_km"]) == a["depth_km"]]
        unique(rows, ["latitude", "longitude", "depth_km"])
        row, d = nearest(rows, a)
        return {"latitude": point(row)[0], "longitude": point(row)[1], "depth_km": a["depth_km"],
                "distance_km": d, "dlnvs_percent": number(row["dlnvs_percent"]),
                "sampling": "nearest supplied sample at exact requested depth; no spline evaluation"}
    if name == "DeepEarthSampleEventModels":
        rows = table(path, ["event_id", "moho_depth_km", "lab_depth_km", "dlnvs_percent"])
        row = one(select(rows, event_id=a["event_id"]))
        return {"event_id": a["event_id"], "moho_depth_km": number(row["moho_depth_km"]),
                "lab_depth_km": number(row["lab_depth_km"]), "dlnvs_percent": number(row["dlnvs_percent"]),
                "sampling": "lookup of supplied precomputed event/model join, not new model sampling"}
    rows = unique(table(path, ["id", "time", "mag", "depth", "latitude", "longitude"]), ["id"])
    for r in rows:
        point(r); timestamp(r["time"]); number(r["mag"]); number(r["depth"])
    if name == "DeepEarthGetUSGSEvent":
        return {"event": one(select(rows, id=a["event_id"]))}
    if a.get("start"):
        rows = [r for r in rows if timestamp(r["time"]) >= timestamp(a["start"])]
    if a.get("end_exclusive"):
        rows = [r for r in rows if timestamp(r["time"]) < timestamp(a["end_exclusive"])]
    if a.get("start") and a.get("end_exclusive") and timestamp(a["start"]) >= timestamp(a["end_exclusive"]):
        fail("start must precede end_exclusive.")
    rows = [r for r in rows if number(r["mag"]) >= a["minimum_magnitude"]]
    if a["operation"] == "count":
        return {"count": len(rows), "event_ids": [r["id"] for r in rows]}
    if a["operation"] == "sum_energy":
        return {"count": len(rows), "total_energy_j": math.fsum(10**(1.5*number(r["mag"])+4.8) for r in rows)}
    field = "mag" if a["operation"] == "largest" else "depth"
    return {"count": len(rows), "event": max(nonempty(rows), key=lambda r: (number(r[field]), r["id"]))}


def climate(name, a):
    if name == "ClimateQueryDeepTime":
        rows = unique(table(a["dataset_path"], ["age_kyr_bp", "temp_anomaly_C"]), ["age_kyr_bp"])
        row = min(nonempty(rows), key=lambda r: abs(number(r["age_kyr_bp"])-a["age_kyr_bp"]))
        return {"requested_age_kyr_bp": a["age_kyr_bp"], "sample_age_kyr_bp": number(row["age_kyr_bp"]),
                "temp_anomaly_c": number(row["temp_anomaly_C"]), "baseline": a["baseline"]}
    if name == "ClimateQueryPresentMean":
        if a["year_start"] > a["year_end"]:
            fail("year_start must not exceed year_end.")
        rows = unique(table(a["dataset_path"], ["year", "temp_anomaly_C"]), ["year"])
        rows = [r for r in rows if a["year_start"] <= number(r["year"]) <= a["year_end"]]
        years = [int(number(r["year"])) for r in rows]
        if any(number(r["year"]) != int(number(r["year"])) for r in rows):
            fail("Annual records require integer years.")
        return {"mean_temp_anomaly_c": numeric_mean(rows, "temp_anomaly_C"), "n": len(rows),
                "years": years, "baseline": a["baseline"],
                "missing_years": sorted(set(range(a["year_start"], a["year_end"]+1))-set(years))}
    rows = table(a["dataset_path"], ["scenario", "horizon_year", "estimate_c", "lower_c", "upper_c"])
    row = one([r for r in rows if r["scenario"] == a["scenario"] and number(r["horizon_year"]) == a["horizon_year"]])
    low, value, high = (number(row[k]) for k in ("lower_c", "estimate_c", "upper_c"))
    if not low <= value <= high:
        fail("Scenario uncertainty interval is inconsistent.")
    return {"scenario": a["scenario"], "horizon_year": a["horizon_year"], "estimate_c": value,
            "lower_c": low, "upper_c": high, "baseline": a["baseline"]}


def energy(name, a):
    path = a["dataset_path"]
    if name in ("EnergyFacilityDistance", "EnergyMineralSiteDistance", "EnergyNearestFacility", "EnergyNearestMineralSite"):
        rows = unique(table(path, ["id", "latitude", "longitude"]), ["id"])
        if name in ("EnergyFacilityDistance", "EnergyMineralSiteDistance"):
            first, second = (one(select(rows, id=a[key])) for key in ("first_id", "second_id"))
            return {"first_id": first["id"], "second_id": second["id"], "distance_km": distance(first, second)}
        origin = a
        if name == "EnergyNearestMineralSite":
            origin = one(select(unique(table(a["facilities_path"], ["id", "latitude", "longitude"]), ["id"]), id=a["facility_id"]))
        row, d = nearest(rows, origin)
        return {"id": row["id"], "distance_km": d, "latitude": point(row)[0], "longitude": point(row)[1]}
    if name in ("EnergyCapacityValue", "EnergyCapacityGrowth"):
        rows = unique(table(path, ["series", "year", "capacity_mw"]), ["series", "year"])
        def value(year):
            row = one([r for r in rows if r["series"] == a["series"] and number(r["year"]) == year])
            v = number(row["capacity_mw"])
            if v < 0: fail("Capacity cannot be negative.")
            return v
        if name == "EnergyCapacityValue":
            return {"series": a["series"], "year": a["year"], "capacity_mw": value(a["year"])}
        if a["start_year"] >= a["end_year"]:
            fail("Growth requires increasing years.")
        first, last = value(a["start_year"]), value(a["end_year"])
        return {"start_mw": first, "end_mw": last, "absolute_growth_mw": last-first,
                "percentage_growth": None if first == 0 else 100*(last-first)/first}
    if name == "EnergyTransitionMetrics":
        rows = table(path, ["country", "year", "renewable_capacity_mw", "total_capacity_mw", "population"])
        row = one([r for r in rows if r["country"] == a["country"] and number(r["year"]) == a["year"]])
        renewable, total, pop = [number(row[k]) for k in ("renewable_capacity_mw", "total_capacity_mw", "population")]
        if not 0 <= renewable <= total or total <= 0 or pop <= 0:
            fail("Require 0 <= renewable <= total, total > 0 and population > 0.")
        return {"renewable_share_percent": renewable/total*100, "renewable_w_per_capita": renewable*1e6/pop,
                "country": a["country"], "year": a["year"]}
    rows = unique(table(path, ["id", "country", "energy_source", "capacity_mw", "latitude", "longitude"]), ["id"])
    if any(number(r["capacity_mw"]) < 0 for r in rows):
        fail("Capacity cannot be negative.")
    if name == "EnergyRegionalOverlaySummary":
        facilities = bounds(rows, a["bbox"])
        minerals = bounds(unique(table(a["minerals_path"], ["id", "latitude", "longitude"]), ["id"]), a["bbox"])
        return {"facility_count": len(facilities), "mineral_count": len(minerals),
                "total_capacity_mw": math.fsum(number(r["capacity_mw"]) for r in facilities),
                "selection": "inclusive bbox over supplied records only"}
    rows = [r for r in rows if r["country"] == a["country"] and r["energy_source"] in a["renewable_types"]]
    totals = {}
    for r in rows:
        totals[r["energy_source"]] = totals.get(r["energy_source"], 0.) + number(r["capacity_mw"])
    return {"country": a["country"], "total_capacity_mw": math.fsum(totals.values()),
            "by_type": [{"energy_source": k, "capacity_mw": v} for k, v in sorted(totals.items())]}


def ocean(name, a, root):
    path = a["dataset_path"]
    if name == "OceanStationDistance":
        rows = unique(table(path, ["station", "latitude", "longitude"]), ["station"])
        left, right = (one(select(rows, station=a[k])) for k in ("first_station", "second_station"))
        return {"distance_km": distance(left, right), "first_station": left["station"], "second_station": right["station"]}
    if name == "OceanMonthlyGridValue":
        rows = table(path, ["month", "latitude", "longitude", a["value_field"]])
        row = one([r for r in rows if r["month"] == a["month"] and point(r) == (a["latitude"], a["longitude"])])
        return {"value": number(row[a["value_field"]]), "value_unit": a["value_unit"], "month": a["month"]}
    if name in ("OceanProfileValue", "OceanVerticalProfileDifference"):
        rows = select(table(path, ["expocode", "station", "depth_m", a["value_field"]]), expocode=a["expocode"], station=a["station"])
        def sample(depth):
            return number(one([r for r in rows if number(r["depth_m"]) == depth])[a["value_field"]])
        if name == "OceanProfileValue":
            return {"value": sample(a["depth_m"]), "depth_m": a["depth_m"], "value_unit": a["value_unit"]}
        if a["deep_depth_m"] <= a["surface_depth_m"]:
            fail("Deep depth must exceed surface depth.")
        surface, deep_value = sample(a["surface_depth_m"]), sample(a["deep_depth_m"])
        return {"surface_value": surface, "deep_value": deep_value, "deep_minus_surface": deep_value-surface, "value_unit": a["value_unit"]}
    if name == "OceanCruiseQC":
        rows = select(table(path, ["cruise", a["quality_field"]]), cruise=a["cruise"])
        counts = {}
        for r in rows:
            counts[r[a["quality_field"]]] = counts.get(r[a["quality_field"]], 0)+1
        accepted = sum(v for k, v in counts.items() if k in a["accepted_flags"])
        return {"total_count": len(rows), "accepted_count": accepted, "rejected_count": len(rows)-accepted,
                "flag_counts": counts, "method": "count supplied QC flags; does not generate new instrument QC flags"}
    if name == "OceanProfileDeduplication":
        rows = table(path, a["key_fields"])
        seen, kept, duplicate_count = set(), [], 0
        for r in rows:
            key = tuple(r[k] for k in a["key_fields"])
            if any(not v.strip() for v in key):
                fail("Duplicate keys must be nonempty.")
            if key in seen:
                duplicate_count += 1
            else:
                seen.add(key); kept.append(r)
        output = output_path(root, "deduplicated.csv")
        with output.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else a["key_fields"])
            writer.writeheader(); writer.writerows(kept)
        return {"input_count": len(rows), "unique_count": len(kept), "duplicate_count": duplicate_count,
                "output_path": str(output), "rule": "first row for identical explicit keys; no fuzzy matching"}
    if name == "OceanSurfaceDeepMatch":
        surface = unique(table(path, ["id", "latitude", "longitude", a["value_field"]]), ["id"])
        deep_rows = unique(table(a["deep_path"], ["id", "latitude", "longitude", a["value_field"]]), ["id"])
        matches = []
        for s in surface:
            d, km = nearest(deep_rows, s)
            if km <= a["maximum_distance_km"]:
                matches.append({"surface_id": s["id"], "deep_id": d["id"], "distance_km": km,
                                "surface_value": number(s[a["value_field"]]), "deep_value": number(d[a["value_field"]])})
        return {"matches": matches, "matched_count": len(matches), "unmatched_count": len(surface)-len(matches),
                "value_unit": a["value_unit"], "method": "spatial nearest only; no temporal or water-mass equivalence implied"}
    rows = table(path, ["time", "latitude", "longitude", a["value_field"]])
    if name == "OceanAnnualCarbonSummary":
        rows = [r for r in rows if timestamp(r["time"]).year == a["year"]]
    else:
        rows = bounds(rows, a["bbox"])
    return {"count": len(rows), "mean": numeric_mean(rows, a["value_field"]), "value_unit": a["value_unit"],
            "method": "unweighted observation mean, not an area-weighted flux or ocean-wide estimate"}


def geo_sparql(a):
    from rdflib import Graph, Literal, URIRef
    from rdflib.plugins.sparql import prepareQuery
    from rdflib.plugins.sparql.operators import register_custom_function
    from rdflib.plugins.sparql.sparql import SPARQLError
    from shapely import wkt
    # Dataset loading is explicitly local; SERVICE and dataset clauses would
    # introduce network/file access outside the declared input, so reject them.
    if re.search(r"\b(SERVICE|FROM|LOAD|INSERT|DELETE|CLEAR|CREATE|DROP|MOVE|COPY|ADD)\b", a["query"], re.I):
        fail("Only local SELECT queries without dataset/service/update clauses are supported.", "unsupported_operation")
    query = prepareQuery(a["query"])
    if query.algebra.name != "SelectQuery":
        fail("Only SELECT is supported.", "unsupported_operation")
    def geometry(value):
        text = str(value).strip()
        if text.startswith("<"):
            crs, text = text.split(">", 1)
            if crs[1:] != "http://www.opengis.net/def/crs/OGC/1.3/CRS84":
                raise SPARQLError("Only CRS84 WKT is supported.")
        shape = wkt.loads(text.strip())
        if shape.is_empty or not shape.is_valid:
            raise SPARQLError("Invalid geometry.")
        return shape
    for name in ("within", "contains", "intersects", "disjoint", "touches"):
        def predicate(left, right, operation=name):
            return Literal(getattr(geometry(left), operation)(geometry(right)))
        register_custom_function(URIRef("http://www.opengis.net/def/function/geosparql/sf"+name.title()), predicate, override=True)
    graph = Graph()
    graph.parse(a["dataset_path"], format=a["format"])
    response = graph.query(query)
    columns = [str(v) for v in response.vars]
    rows = [{k: None if v is None else str(v) for k, v in zip(columns, row)} for row in response]
    return {"columns": columns, "rows": rows, "count": len(rows),
            "method": "executed SELECT on supplied RDF; CRS84 sfWithin/Contains/Intersects/Disjoint/Touches only"}


def idw(a, root):
    # Imported algorithm, with explicit field, spherical metric, duplicate policy
    # and bounded geographic grid. No automatic choice of an identifier as value.
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds
    rows = table(a["points_path"], ["latitude", "longitude", a["value_field"]])
    locations = {}
    for row in nonempty(rows):
        locations.setdefault(point(row), []).append(number(row[a["value_field"]]))
    if len(locations) < 2:
        fail("IDW requires at least two distinct observation locations.")
    bbox = a["bbox"]; bounds([], bbox)
    if bbox[2]-bbox[0] > 180: fail("Split grids spanning over 180 degrees.")
    size, power = a["grid_size"], a["power"]
    transform = from_bounds(*bbox, size, size)
    x, y = np.meshgrid(bbox[0]+(np.arange(size)+.5)*(bbox[2]-bbox[0])/size,
                       bbox[3]-(np.arange(size)+.5)*(bbox[3]-bbox[1])/size)
    numerator = np.zeros_like(x); denominator = np.zeros_like(x); exact = np.full_like(x, np.nan)
    for (lat, lon), values in locations.items():
        z = math.fsum(values)/len(values)
        h = np.sin((np.deg2rad(y)-math.radians(lat))/2)**2 + np.cos(np.deg2rad(y))*math.cos(math.radians(lat))*np.sin(np.deg2rad(x-lon)/2)**2
        d = 6371.0088*2*np.arcsin(np.sqrt(np.clip(h, 0, 1)))
        weight = 1/np.maximum(d, 1e-9)**power
        numerator += weight*z; denominator += weight; exact[d <= 1e-9] = z
    grid = np.where(np.isfinite(exact), exact, numerator/denominator)
    if not np.isfinite(grid).all(): fail("Non-finite interpolation result.", "invalid_result")
    output = output_path(root, "idw.tif")
    with rasterio.open(output, "w", driver="GTiff", width=size, height=size, count=1, dtype="float64",
                       crs="EPSG:4326", transform=transform, nodata=float("nan")) as dst:
        dst.write(grid, 1); dst.update_tags(1, unit=a["value_unit"], method="spherical IDW")
    return {"output_path": str(output), "shape": [size, size], "crs": "EPSG:4326",
            "value_unit": a["value_unit"], "observation_count": len(rows), "distinct_locations": len(locations),
            "method": "inverse spherical distance at pixel centers; duplicate locations averaged"}


def raster(a, operation, root):
    import numpy as np
    import rasterio
    from contextlib import ExitStack
    from .scientific_raster import read_scientific_raster
    if operation == "algebra":
        roles = ["raster_path"] + (["other_path"] if "other_path" in a else [])
        if (a.get("scalar") is None) == ("other_path" not in a):
            fail("Supply exactly one of scalar or other_path.", "invalid_arguments")
    elif operation == "cloud":
        roles = ["raster_path", "qa_path"]
    else:
        roles = ["red_path", "green_path"]
    with ExitStack() as stack:
        datasets = [stack.enter_context(rasterio.open(a[k])) for k in roles]
        first = datasets[0]
        if first.count != 1 or not first.crs:
            fail("Single-band georeferenced GeoTIFF required.")
        for ds in datasets[1:]:
            if ds.count != 1 or ds.crs != first.crs or ds.transform != first.transform or ds.shape != first.shape:
                fail("Input rasters must have identical grids and CRS.")
        values = read_scientific_raster(Path(a[roles[0]]))[0]
        if operation == "cloud":
            qa = datasets[1].read(1, masked=True)
            if qa.dtype.kind not in "ui" or qa.dtype.itemsize > 4:
                fail("QA_PIXEL must be an unsigned/nonnegative integer bit field.")
            if np.any(qa.compressed() < 0): fail("Negative QA value.")
            valid = ~np.ma.getmaskarray(qa)
            bits = sum(1 << v for v in (0, 1, 2, 3, 4, 5))
            valid &= (qa.filled(0).astype("uint32") & bits) == 0
            calculated = np.where(valid, values, np.nan)
            unit, method = a["value_unit"], "Landsat 8/9 Collection 2 QA_PIXEL: reject bits 0 through 5"
        elif operation == "ndti":
            other = read_scientific_raster(Path(a["green_path"]))[0]
            # Inputs must identify one acquisition; values are physical
            # reflectances (metadata scale/offset applied by the shared reader).
            red_date, green_date = a["red_date"], a["green_date"]
            if timestamp(red_date) != timestamp(green_date): fail("NDTI requires the same acquisition date.")
            for ds, date in zip(datasets, (red_date, green_date)):
                recorded = ds.tags().get("acquisition_date")
                if recorded and timestamp(recorded) != timestamp(date): fail("Date contradicts raster metadata.")
            denom = values+other
            calculated = np.divide(values-other, denom, out=np.full_like(values, np.nan), where=np.isfinite(denom)&(denom != 0))
            unit, method = "1", "normalized difference turbidity index (red-green)/(red+green); not turbidity concentration"
        else:
            other = read_scientific_raster(Path(a["other_path"]))[0] if "other_path" in a else a["scalar"]
            if a["operation"] == "divide":
                calculated = np.divide(values, other, out=np.full_like(values, np.nan), where=np.isfinite(other)&(other != 0))
            else:
                calculated = {"add": np.add, "subtract": np.subtract, "multiply": np.multiply}[a["operation"]](values, other)
            unit, method = a["output_unit"], "pixelwise "+a["operation"]+"; physical input values; no resampling"
        if np.isinf(calculated).any(): fail("Arithmetic overflow.", "invalid_result")
        valid = np.isfinite(calculated)
        if not valid.any(): fail("No valid pixels remain.", "invalid_result")
        output = output_path(root, operation+".tif")
        profile = first.profile.copy(); profile.update(dtype="float64", count=1, nodata=float("nan"))
        with rasterio.open(output, "w", **profile) as dst:
            dst.write(calculated, 1); dst.update_tags(1, unit=unit, method=method)
        return {"output_path": str(output), "valid_pixels": int(valid.sum()), "total_pixels": int(valid.size),
                "minimum": float(calculated[valid].min()), "maximum": float(calculated[valid].max()),
                "mean": float(calculated[valid].mean()), "value_unit": unit, "method": method}


USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"


def _usgs_response(params):
    import requests
    try:
        response = requests.get(USGS_URL, params=params, timeout=(15, 120), allow_redirects=False)
    except requests.RequestException as exc:
        raise ScientificToolError("upstream_error", str(exc), retryable=True) from exc
    if response.status_code != 200:
        raise ScientificToolError("upstream_error", "USGS HTTP "+str(response.status_code), retryable=response.status_code == 429 or response.status_code >= 500)
    return response.json()


def usgs(a, root):
    if timestamp(a["start"]) >= timestamp(a["end"]): fail("start must precede end.")
    params = {"format": "geojson", "starttime": a["start"], "endtime": a["end"],
              "minmagnitude": a["minimum_magnitude"], "limit": a["limit"], "orderby": "time-asc"}
    payload = _usgs_response(params)
    if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
        fail("USGS did not return a GeoJSON FeatureCollection.", "invalid_result")
    rows = []
    for f in payload["features"]:
        p = f["properties"]; lon, lat, depth = f["geometry"]["coordinates"]
        row = {"id": f["id"], "time": datetime.fromtimestamp(number(p["time"])/1000, timezone.utc).isoformat(),
               "latitude": lat, "longitude": lon, "depth": depth, "mag": p.get("mag"),
               "place": p.get("place") or ""}
        point(row); number(depth)
        if row["mag"] is not None: number(row["mag"])
        rows.append(row)
    output = output_path(root, "usgs-events.csv")
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "time", "latitude", "longitude", "depth", "mag", "place"])
        writer.writeheader(); writer.writerows(rows)
    return {"output_path": str(output), "count": len(rows), "request_url": USGS_URL,
            "request_parameters": params, "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "possibly_limited": len(rows) >= a["limit"]}


def earthquake_map(a, root):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    rows = table(a["dataset_path"], ["latitude", "longitude", "mag"])
    coords = [point(r) for r in nonempty(rows)]
    mags = [number(r["mag"]) for r in rows]
    figure = Figure(figsize=(9, 6)); FigureCanvasAgg(figure)
    ax = figure.subplots()
    plotted = ax.scatter([p[1] for p in coords], [p[0] for p in coords], c=mags, cmap="viridis", s=38, edgecolors="white", linewidths=.5)
    ax.set(xlabel="Longitude (degrees east)", ylabel="Latitude (degrees north)", title=a["title"])
    ax.grid(alpha=.2); figure.colorbar(plotted, ax=ax, label="Reported magnitude")
    output = output_path(root, "earthquakes.png"); figure.savefig(output, dpi=160, bbox_inches="tight")
    webpage = output.with_suffix(".html")
    image = base64.b64encode(output.read_bytes()).decode("ascii")
    webpage.write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:"><title>'+html.escape(a["title"])+'</title><h1>'+html.escape(a["title"])+'</h1><img alt="Earthquake point distribution" src="data:image/png;base64,'+image+'"><p>Coordinate scatter plot, not a projected basemap. Supplied events only.</p>', encoding="utf-8")
    return {"png_path": str(output), "html_path": str(webpage), "event_count": len(rows),
            "method": "static WGS84 coordinate scatter; no remote tiles, scripts or HTML from source records"}


def run(tool_name, args, *, output_dir=None):
    """Public native entrypoint. No LLM, server or old string transport needed."""
    if tool_name not in RECOVERED: fail("Unknown recovered tool.", "unknown_tool")
    try:
        a = arguments(tool_name, args)
    except (ValueError, TypeError, ValidationError) as exc:
        fail(str(exc), "invalid_arguments")
    from ..source_contracts import definition
    paths = definition(tool_name)["source_interface"]["path_fields"]
    try:
        provenance = [source(a[k]) for k in paths if k in a]
        if tool_name.startswith("DeepEarth"):
            data = deep(tool_name, a)
        elif tool_name.startswith("Climate"):
            data = climate(tool_name, a)
        elif tool_name.startswith("Energy"):
            data = energy(tool_name, a)
        elif tool_name.startswith("Ocean"):
            data = ocean(tool_name, a, output_dir)
        elif tool_name.endswith("InterpolateIDW"):
            data = idw(a, output_dir)
        elif tool_name.endswith("RasterAlgebra"):
            data = raster(a, "algebra", output_dir)
        elif tool_name == "RemoteSensingCloudMask":
            data = raster(a, "cloud", output_dir)
        elif tool_name == "RemoteSensingNDTI":
            data = raster(a, "ndti", output_dir)
        elif tool_name == "GeoBigDataExecuteGeoSPARQL":
            data = geo_sparql(a)
        elif tool_name == "USGS 地震数据获取":
            data = usgs(a, output_dir)
        else:
            data = earthquake_map(a, output_dir)
        return result(tool_name, {"data": data, "sources": provenance,
            "dataset_version": a.get("dataset_version"),
            "scope": "Supplied inputs only; no claim of complete geographic, temporal or model coverage."})
    except ScientificToolError:
        raise
    except ModuleNotFoundError as exc:
        fail("Missing dependency: "+str(exc.name), "missing_dependency")
    except FileNotFoundError as exc:
        fail(str(exc), "missing_input")
    except ValidationError as exc:
        fail(str(exc), "invalid_result")
    except (ValueError, KeyError, TypeError, OSError, OverflowError) as exc:
        fail(type(exc).__name__+": "+str(exc))

# Original public import names point directly to the same native implementation.
from functools import partial
usgs_earthquake_data_fetch = partial(run, "USGS 地震数据获取")
visualize_earthquake_event_map = partial(run, "地震事件地图可视化")

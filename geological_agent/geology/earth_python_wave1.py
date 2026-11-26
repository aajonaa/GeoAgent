"""Eight bounded upstream operations. No installers, network clients or GPU code."""
from functools import wraps
import hashlib
from importlib import metadata
import json
import math
from pathlib import Path
from threading import RLock

from jsonschema import Draft202012Validator, ValidationError
from legacy.ToolsAgent.ToolsFuns.source_contracts import arguments, definition, finite
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError

_RENDER_LOCK = RLock()
MAX_FILE_BYTES = 64 * 1024 * 1024


def reject(message, code="invalid_arguments"):
    raise ScientificToolError(code, message)


def operation(name):
    def decorate(function):
        @wraps(function)
        def call(args, output_dir=None):
            try:
                args = arguments(name, args)
                spec = definition(name)
                if len(json.dumps(args, ensure_ascii=True)) > 4_000_000:
                    reject("Arguments exceed the 4 MB operation limit", "resource_limit")
                upstream = spec["metadata"]["upstream"]
                package = upstream["package"]
                installed = metadata.version(package)
                if installed != upstream["version"]:
                    reject("Install the pinned package release for " + package, "missing_dependency")
                canonical = dict(args)
                for key in spec["source_interface"]["path_fields"]:
                    path = Path(args[key])
                    if path.is_symlink():
                        reject("A standalone input cannot be a symlink", "invalid_path")
                    if not path.is_file():
                        reject("A declared input file is missing", "missing_input")
                    if path.stat().st_size > MAX_FILE_BYTES:
                        reject("Input exceeds 64 MiB", "resource_limit")
                    canonical[key] = {"content_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                root = None
                generates_files = bool(spec["source_interface"]["entrypoint"].get("output_directory_parameter"))
                if generates_files:
                    if output_dir is None:
                        reject("This operation requires an explicit output directory")
                    root = Path(output_dir)
                    if root.is_symlink():
                        reject("Output directory cannot be a symlink", "invalid_path")
                    root = root.resolve()
                    if root.exists() and (not root.is_dir() or any(root.iterdir())):
                        reject("Output directory must be new or empty", "output_conflict")
                    root.mkdir(parents=True, exist_ok=True)
                    with _RENDER_LOCK:
                        result = function(args, root)
                else:
                    result = function(args, None)
                artifacts = []
                output_hashes = {}
                if root is not None:
                    for path in sorted(root.iterdir()):
                        if path.is_symlink() or not path.is_file() or path.resolve().parent != root:
                            reject("Unexpected output path", "invalid_result")
                        artifacts.append(str(path))
                        output_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
                result["artifacts"] = artifacts
                result["provenance"] = {
                    "tool": name, "upstream_url": upstream["url"],
                    "reviewed_archive_commit": spec["registration_metadata"]["source_commit"],
                    "runtime_source": "pinned_package_release_not_archive_head",
                    "installed_version": installed,
                    "input_sha256": hashlib.sha256(json.dumps(canonical, sort_keys=True,
                        ensure_ascii=True, allow_nan=False).encode()).hexdigest(),
                    "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "output_sha256": output_hashes,
                    "crs": args.get("crs", result.get("crs")),
                    "network_used": False,
                }
                try:
                    finite(result)
                    Draft202012Validator(spec["output_schema"]).validate(result)
                    json.dumps(result, allow_nan=False)
                except (ValueError, TypeError, ValidationError):
                    reject("Upstream output violates the result contract", "invalid_result")
                return result
            except ScientificToolError:
                raise
            except (ModuleNotFoundError, metadata.PackageNotFoundError) as exc:
                reject("Install the isolated pinned dependency profile; " + type(exc).__name__, "missing_dependency")
            except FileNotFoundError:
                reject("A declared input file is missing", "missing_input")
            except PermissionError:
                reject("File access denied", "invalid_path")
            except (ValidationError, ValueError, TypeError, KeyError, OverflowError):
                reject("Arguments do not satisfy the declared schema or operation constraints")
            except MemoryError:
                reject("Operation exceeded available memory", "resource_limit")
            except Exception as exc:
                reject("The pinned upstream operation failed: " + type(exc).__name__, "upstream_failure")
        return call
    return decorate


def projected_crs(value):
    from pyproj import CRS
    from pyproj.exceptions import CRSError
    try:
        crs = CRS.from_user_input(value)
    except CRSError:
        reject("crs must identify a valid projected coordinate reference system")
    if not crs.is_projected or len(crs.axis_info) < 2:
        reject("A projected CRS with two linear axes is required; no implicit reprojection")
    if crs.axis_info[0].unit_name != crs.axis_info[1].unit_name:
        reject("The two coordinate axes must have the same linear unit")
    return crs, crs.axis_info[0].unit_name


def geometry(value):
    from shapely.geometry import shape
    # Bound all nesting and ordinates before GEOS allocates a geometry.
    stack = [(value["coordinates"], 0)]
    ordinates = 0
    while stack:
        item, depth = stack.pop()
        if depth > 6:
            reject("Geometry nesting exceeds the supported GeoJSON types")
        if isinstance(item, list):
            stack.extend((x, depth + 1) for x in item)
        elif isinstance(item, (float, int)) and not isinstance(item, bool):
            ordinates += 1
        else:
            reject("Geometry coordinates must be numeric arrays")
        if ordinates + len(stack) > 100_000:
            reject("Geometry exceeds 100,000 ordinates", "resource_limit")
    geom = shape(value)
    if geom.is_empty or not geom.is_valid or geom.has_z:
        reject("Only valid, nonempty, two-dimensional geometries are supported")
    return geom


def aligned(x, y):
    if len(x) != len(y):
        reject("Coordinate arrays must have equal lengths")


def ordered_extent(extent):
    xmin, xmax, ymin, ymax = extent
    if not xmin < xmax or not ymin < ymax:
        reject("Extent must be ordered xmin,xmax,ymin,ymax")


def figure(width=8, height=5):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig = Figure(figsize=(width, height), facecolor="#f6f7f1", layout="constrained")
    FigureCanvasAgg(fig)
    return fig


@operation("GeoShapelyGeometry")
def shapely_geometry(args, output_dir=None):
    crs, unit = projected_crs(args["crs"])
    geom = geometry(args["geometry"])
    centroid = geom.centroid
    return {"geometry_type": geom.geom_type, "area": float(geom.area),
            "length": float(geom.length), "centroid": [float(centroid.x), float(centroid.y)],
            "bounds": list(map(float, geom.bounds)), "crs": crs.to_string(),
            "units": {"coordinates": unit, "length": unit, "area": unit + " squared"}}


@operation("GeoPandasSpatialJoin")
def geopandas_spatial_join(args, output_dir=None):
    import geopandas as gpd
    crs, unit = projected_crs(args["crs"])
    left = gpd.GeoDataFrame({"left_id": list(range(len(args["left"])))},
                           geometry=[geometry(g) for g in args["left"]], crs=crs)
    right = gpd.GeoDataFrame({"right_id": list(range(len(args["right"])))},
                            geometry=[geometry(g) for g in args["right"]], crs=crs)
    joined = gpd.sjoin(left, right, how="inner", predicate=args["predicate"])
    if len(joined) > args["max_matches"]:
        reject("Join exceeds max_matches; narrow inputs or explicitly request a larger bounded result", "resource_limit")
    pairs = sorted([[int(row.left_id), int(row.right_id)] for row in joined.itertuples()])
    return {"predicate": args["predicate"], "matches": pairs, "match_count": len(pairs),
            "left_count": len(left), "right_count": len(right), "crs": crs.to_string(),
            "units": {"coordinates": unit, "identifiers": "zero-based input indices"}}


@operation("GeoFionaDatasetInfo")
def fiona_dataset_info(args, output_dir=None):
    import fiona
    path = Path(args["input_path"])
    if path.suffix.lower() not in {".json", ".geojson", ".gpkg", ".fgb"}:
        reject("Only single-file GeoJSON, GeoPackage and FlatGeobuf inputs are supported")
    options = {"layer": args["layer"]} if "layer" in args else {}
    with fiona.open(str(path), mode="r", enabled_drivers=["GeoJSON", "GPKG", "FlatGeobuf"], **options) as collection:
        count = len(collection)
        if count > 50_000:
            reject("Dataset exceeds 50,000 features", "resource_limit")
        crs = collection.crs_wkt or None
        bounds = list(map(float, collection.bounds)) if count else None
        return {"driver": collection.driver, "feature_count": count,
                "geometry_type": collection.schema["geometry"],
                "fields": {str(k): str(v) for k, v in collection.schema["properties"].items()},
                "bounds": bounds, "crs": crs,
                "units": {"coordinates": "as declared by the dataset CRS; unknown if CRS is null"}}


@operation("GeoRasterioWindow")
def rasterio_window(args, output_dir=None):
    import numpy as np
    import rasterio
    from rasterio.windows import Window
    from PIL import Image
    bands = args["bands"]
    if len(bands) not in (1, 3) or len(set(bands)) != len(bands):
        reject("Select one band or three distinct display bands")
    if args["width"] * args["height"] * len(bands) > 4_194_304:
        reject("Window exceeds 4,194,304 band-pixels", "resource_limit")
    window = Window(args["col_off"], args["row_off"], args["width"], args["height"])
    with rasterio.open(args["input_path"], driver="GTiff") as source:
        if source.crs is None:
            reject("Raster CRS is missing; no CRS will be invented")
        if max(bands) > source.count or window.col_off + window.width > source.width or window.row_off + window.height > source.height:
            reject("Requested bands or pixel window are outside the source")
        data = source.read(bands, window=window, masked=True)
        invalid = np.any(np.ma.getmaskarray(data) | ~np.isfinite(data.data), axis=0)
        if np.all(invalid):
            reject("The selected window has no finite unmasked pixels", "invalid_input")
        transform = source.window_transform(window)
        profile = {"driver": "GTiff", "width": args["width"], "height": args["height"],
                   "count": len(bands), "dtype": data.dtype.name, "crs": source.crs,
                   "transform": transform, "compress": "deflate", "nodata": source.nodata}
        tif = output_dir / "window.tif"
        with rasterio.open(tif, "w", **profile) as destination:
            destination.write(data.filled(source.nodata if source.nodata is not None else 0))
            destination.write_mask((~invalid).astype("uint8") * 255)
        rgb = np.zeros((args["height"], args["width"], 4), dtype="uint8")
        summaries = []
        for i in range(len(bands)):
            values = data.data[i][~invalid].astype("float64")
            low, high = np.percentile(values, [2, 98])
            display = np.zeros(invalid.shape, dtype="uint8")
            if high > low:
                scaled = np.clip((data.data[i][~invalid].astype("float64") - low) / (high - low), 0, 1)
                display[~invalid] = (scaled * 255).astype("uint8")
            if len(bands) == 1:
                rgb[:, :, :3] = display[:, :, None]
            else:
                rgb[:, :, i] = display
            summaries.append({"band": bands[i], "min": float(values.min()),
                              "max": float(values.max()), "mean": float(values.mean())})
        rgb[:, :, 3] = (~invalid).astype("uint8") * 255
        Image.fromarray(rgb).save(output_dir / "window-preview.png")
        return {"shape": [args["height"], args["width"]], "bands": bands,
                "valid_pixels": int((~invalid).sum()), "statistics": summaries,
                "crs": source.crs.to_string(), "transform": list(transform)[:6],
                "preview_stretch": "per-band 2nd to 98th percentile; TIFF values unchanged",
                "mask_policy": "common dataset/band mask plus nonfinite values; no additional quality mask inferred",
                "units": {"values": args["value_unit"], "coordinates": "source CRS"}}


@operation("GeoCartopyPointMap")
def cartopy_point_map(args, output_dir=None):
    import cartopy.crs as ccrs
    aligned(args["longitude"], args["latitude"])
    ordered_extent(args["extent"])
    if not (-180 <= args["extent"][0] < args["extent"][1] <= 180 and
            -90 <= args["extent"][2] < args["extent"][3] <= 90):
        reject("Extent must lie within WGS84 and cannot cross the antimeridian")
    if any(not (args["extent"][0] <= x <= args["extent"][1] and args["extent"][2] <= y <= args["extent"][3])
           for x, y in zip(args["longitude"], args["latitude"])):
        reject("All supplied locations must lie within the requested map extent")
    projection = ccrs.PlateCarree() if args["projection"] == "plate_carree" else ccrs.Mercator()
    if args["projection"] == "mercator" and (args["extent"][2] < -80 or args["extent"][3] > 84):
        reject("Mercator output is restricted to latitude -80 to 84 degrees")
    fig = figure()
    ax = fig.add_subplot(1, 1, 1, projection=projection)
    ax.set_facecolor("#e8efe7")
    ax.set_extent(args["extent"], crs=ccrs.PlateCarree())
    ax.scatter(args["longitude"], args["latitude"], transform=ccrs.PlateCarree(),
               s=28, color="#996731", edgecolors="#fffdf5", linewidths=0.7)
    ax.gridlines(draw_labels=True, linewidth=0.5, color="#678078", alpha=0.6)
    ax.set_title(args["title"], color="#173d32", parse_math=False)
    fig.savefig(output_dir / "point-map.png", dpi=180)
    fig.savefig(output_dir / "point-map.svg")
    return {"point_count": len(args["longitude"]), "extent": args["extent"],
            "projection": args["projection"], "crs": "EPSG:4326",
            "basemap": "coordinate grid only; no coastlines or boundary data downloaded",
            "units": {"input_longitude": "degree_east", "input_latitude": "degree_north"}}


@operation("GeoDatashaderDensity")
def datashader_density(args, output_dir=None):
    import numpy as np
    import pandas as pd
    import datashader as ds
    import datashader.transfer_functions as tf
    aligned(args["x"], args["y"])
    ordered_extent(args["extent"])
    if any(not (args["extent"][0] <= x <= args["extent"][1] and args["extent"][2] <= y <= args["extent"][3])
           for x, y in zip(args["x"], args["y"])):
        reject("All supplied points must lie within the aggregation extent")
    canvas = ds.Canvas(plot_width=args["width"], plot_height=args["height"],
                       x_range=tuple(args["extent"][:2]), y_range=tuple(args["extent"][2:]))
    aggregate = canvas.points(pd.DataFrame({"x": args["x"], "y": args["y"]}), "x", "y", agg=ds.count())
    image = tf.shade(aggregate, how="linear", cmap=["#e5eddc", "#68a394", "#164b41"], min_alpha=255)
    image.to_pil().save(output_dir / "point-density.png")
    counts = np.asarray(aggregate.values, dtype="uint32")
    np.save(output_dir / "pixel-counts.npy", counts, allow_pickle=False)
    return {"point_count": len(args["x"]), "binned_points": int(counts.sum()),
            "shape": [args["height"], args["width"]], "extent": args["extent"],
            "max_count": int(counts.max()), "nonempty_pixels": int((counts > 0).sum()),
            "array_order": "rows increase from ymin to ymax; columns from xmin to xmax",
            "units": {"coordinates": args["coordinate_unit"], "density": "points per pixel, not per unit area"}}


@operation("HydroAnaFlowTheis")
def anaflow_theis(args, output_dir=None):
    import csv
    import numpy as np
    from anaflow.flow.homogeneous import theis
    times = args["time_s"]
    radii = args["radius_m"]
    if len(times) * len(radii) > 16_384:
        reject("Theis grid exceeds 16,384 time-radius pairs", "resource_limit")
    if times != sorted(set(times)) or radii != sorted(set(radii)):
        reject("Times and radii must each be unique and strictly increasing")
    heads = np.asarray(theis(time=np.asarray(times), rad=np.asarray(radii), storage=args["storativity"],
                             transmissivity=args["transmissivity_m2_s"], rate=-args["pumping_rate_m3_s"]), dtype=float)
    drawdown = -heads.reshape(len(times), len(radii))
    if not np.all(np.isfinite(drawdown)):
        reject("The upstream solution returned nonfinite drawdown", "invalid_result")
    with (output_dir / "drawdown.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time_s", "radius_m", "drawdown_m"])
        for i, time in enumerate(times):
            for j, radius in enumerate(radii):
                writer.writerow([time, radius, float(drawdown[i, j])])
    fig = figure()
    ax = fig.add_subplot()
    indices = np.unique(np.linspace(0, len(radii) - 1, min(8, len(radii))).astype(int)).tolist()
    for j in indices:
        ax.semilogx(times, drawdown[:, j], label=f"r = {radii[j]:g} m", linewidth=1.8)
    ax.set_xlabel("Elapsed pumping time (s)")
    ax.set_ylabel("Drawdown (m)")
    ax.grid(alpha=0.2)
    ax.legend()
    ax.set_title("Theis: confined homogeneous aquifer; constant pumping")
    fig.savefig(output_dir / "drawdown.png", dpi=180)
    return {"time_s": times, "radius_m": radii, "drawdown_m": drawdown.tolist(),
            "plot_radius_indices": indices,
            "assumptions": "Confined homogeneous infinite aquifer, fully penetrating zero-radius well, constant positive extraction rate; no parameter calibration.",
            "units": {"time": "s", "radius": "m", "drawdown": "m", "transmissivity": "m2/s",
                      "pumping_rate": "m3/s", "storativity": "dimensionless"}}


@operation("SeismicObsPyBandpass")
def obspy_bandpass(args, output_dir=None):
    import numpy as np
    from obspy import read
    if args["freqmin_hz"] >= args["freqmax_hz"]:
        reject("freqmin_hz must be below freqmax_hz")
    header = read(args["input_path"], format=args["format"], headonly=True)
    if not 1 <= len(header) <= 8 or sum(tr.stats.npts for tr in header) > 2_000_000:
        reject("Waveform limit is 8 traces and 2,000,000 total samples", "resource_limit")
    for tr in header:
        if tr.stats.npts < 32 or not math.isfinite(tr.stats.sampling_rate) or tr.stats.sampling_rate <= 0:
            reject("Each trace needs at least 32 samples and a finite positive sampling rate")
        if args["freqmax_hz"] >= tr.stats.sampling_rate / 2:
            reject("freqmax_hz must be strictly below every trace Nyquist frequency")
    stream = read(args["input_path"], format=args["format"])
    for tr in stream:
        if np.ma.isMaskedArray(tr.data) or not np.all(np.isfinite(tr.data)):
            reject("Masked gaps and nonfinite samples must be resolved explicitly before filtering", "invalid_input")
    stream.detrend("demean")
    stream.taper(max_percentage=0.05, type="cosine")
    stream.filter("bandpass", freqmin=args["freqmin_hz"], freqmax=args["freqmax_hz"], corners=args["corners"], zerophase=True)
    for tr in stream:
        tr.data = np.asarray(tr.data, dtype="float64")
        if not np.all(np.isfinite(tr.data)):
            reject("Filter returned nonfinite samples", "invalid_result")
    stream.write(str(output_dir / "filtered.mseed"), format="MSEED", encoding="FLOAT64", reclen=4096)
    fig = figure(height=max(3, 2 * len(stream)))
    axes = np.atleast_1d(fig.subplots(len(stream), 1))
    summaries = []
    for ax, tr in zip(axes, stream):
        indices = np.unique(np.linspace(0, tr.stats.npts - 1, min(4000, tr.stats.npts)).astype(int))
        ax.plot(indices / tr.stats.sampling_rate, tr.data[indices], color="#235c4e", linewidth=0.75)
        ax.set_title(tr.id, parse_math=False)
        ax.set_ylabel(args["data_unit"], parse_math=False)
        summaries.append({"id": tr.id, "npts": int(tr.stats.npts),
                          "sampling_rate_hz": float(tr.stats.sampling_rate),
                          "starttime_utc": str(tr.stats.starttime),
                          "endtime_utc": str(tr.stats.endtime),
                          "rms": float(np.sqrt(np.mean(tr.data ** 2)))})
    axes[-1].set_xlabel("Seconds from each trace start")
    fig.savefig(output_dir / "waveform.png", dpi=150)
    return {"traces": summaries, "filter": "demean, 5% cosine taper, zero-phase Butterworth bandpass",
            "preview": "At most 4,000 original sample positions per trace; MiniSEED retains all filtered samples.",
            "units": {"amplitude": args["data_unit"], "frequency": "Hz", "time": "s"}}

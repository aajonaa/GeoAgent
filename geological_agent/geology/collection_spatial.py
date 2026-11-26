"""Bounded spatial operations; upstream algorithms remain in their own libraries."""

import html
import json
import math
from pathlib import Path

from .collection_contracts import operation, reject


def _raster(path, *, projected=False, binary=False):
    import numpy as np
    import rasterio

    with rasterio.open(path) as src:
        if src.count != 1 or src.width * src.height > 1_000_000:
            reject("A single-band raster of at most 1,000,000 cells is required.", "resource_limit")
        if src.crs is None:
            reject("The source raster must declare a CRS.", "invalid_arguments")
        if src.transform.b != 0 or src.transform.d != 0 or src.transform.a <= 0 or src.transform.e >= 0:
            reject("A north-up, unrotated raster is required.", "invalid_arguments")
        if projected:
            if not src.crs.is_projected or src.crs.linear_units_factor[1] != 1:
                reject("A projected CRS with metre units is required.", "invalid_arguments")
        data = src.read(1, masked=True)
        if np.ma.getmaskarray(data).any() or not np.isfinite(data.data).all():
            reject("This bounded operation requires finite cells without nodata gaps.", "invalid_arguments")
        if binary and not np.isin(data.data, [0, 1]).all():
            reject("The region mask must contain only zero and one.", "invalid_arguments")
        return data.data.astype("float64"), src.profile.copy()


def _summary(values):
    import numpy as np

    array = np.asarray(values, dtype=float)
    if array.size == 0 or not np.isfinite(array).all():
        reject("The upstream result contains no finite data or contains non-finite values.", "invalid_input")
    return {"minimum": float(array.min()), "maximum": float(array.max()), "mean": float(array.mean())}


def _raster_files(values, profile, output_dir, stem, label, unit):
    import csv
    import matplotlib
    import numpy as np
    import rasterio

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    root = Path(output_dir)
    array = np.asarray(values, dtype="float64")
    if array.shape != (profile["height"], profile["width"]):
        reject("The result shape does not match the raster grid.", "invalid_input")
    stats = _summary(array)
    tif = root / (stem + ".tif")
    profile.update(driver="GTiff", count=1, dtype="float64", nodata=None, compress="deflate")
    with rasterio.open(tif, "w", **profile) as dst:
        dst.write(array, 1)
        dst.set_band_description(1, label)
        dst.update_tags(1, units=unit)
    fig, ax = plt.subplots(figsize=(7, 5), layout="constrained")
    try:
        image = ax.imshow(array, cmap="viridis", interpolation="nearest")
        ax.set(title=label, xlabel="Column", ylabel="Row")
        fig.colorbar(image, ax=ax, label=unit)
        fig.savefig(root / (stem + ".png"), dpi=140)
    finally:
        plt.close(fig)
    with (root / (stem + "-statistics.csv")).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["statistic", "value", "unit"])
        writer.writerows((key, value, unit) for key, value in stats.items())
    return {"raster": tif.name, "preview": stem + ".png", "statistics_csv": stem + "-statistics.csv", "statistics": stats}


@operation("GeoPyshedsFlowAccumulation")
def pysheds_flow_accumulation(args, output_dir=None):
    """Run the real pysheds D8 direction and unweighted accumulation methods."""
    import numpy as np
    from pysheds.grid import Grid

    values, profile = _raster(args["dem_path"], projected=True)
    if values.size > 250_000:
        reject("D8 routing is limited to 250,000 cells per call.", "resource_limit")
    if not math.isclose(profile["transform"].a, -profile["transform"].e, rel_tol=1e-9):
        reject("D8 routing requires square metre-sized cells.", "invalid_arguments")
    grid = Grid.from_raster(args["dem_path"])
    dem = grid.read_raster(args["dem_path"])
    directions = grid.flowdir(dem, routing="d8")
    accumulation = grid.accumulation(directions, routing="d8")
    root = Path(output_dir)
    grid.to_raster(directions, str(root / "flow-direction.tif"))
    result = _raster_files(np.asarray(accumulation), profile, root, "flow-accumulation", "D8 contributing cells", "cells")
    return {**result, "flow_direction": "flow-direction.tif", "routing": "D8", "conditioning": "none", "cell_count": int(values.size), "units": {"accumulation": "cells", "elevation": args["elevation_unit"], "horizontal": "m"}, "limitations": ["No pit filling or flat resolution is performed; flats and pits retain pysheds default codes.", "Contributing-cell counts are not discharge or groundwater flow."]}


@operation("GeoPywrWaterAllocation")
def pywr_water_allocation(args, output_dir=None):
    """Solve a fixed one-day supply-to-demand network using Pywr's LP solver."""
    from pywr.model import Model
    from pywr.nodes import Input, Output

    demands = args["demands_m3_per_day"]
    priorities = args["priorities"]
    if len(demands) != len(priorities) or len(set(priorities)) != len(priorities):
        reject("Demands and unique priorities must have the same length.", "invalid_arguments")
    model = Model(start="2000-01-01", end="2000-01-01", timestep=1)
    supply = Input(model, name="supply", max_flow=args["supply_m3_per_day"])
    outputs = []
    for index, (demand, priority) in enumerate(zip(demands, priorities)):
        node = Output(model, name="demand_" + str(index), max_flow=demand, cost=-float(priority))
        supply.connect(node)
        outputs.append(node)
    model.check()
    model.run()
    allocated = [float(node.flow[0]) for node in outputs]
    if any(not math.isfinite(value) for value in allocated):
        reject("The allocation solver returned a non-finite flow.", "invalid_input")
    return {"allocations": allocated, "deficits": [float(demand - actual) for demand, actual in zip(demands, allocated)], "supply_used": float(supply.flow[0]), "unused_supply": float(args["supply_m3_per_day"] - supply.flow[0]), "units": {"allocations": "m3/day", "deficits": "m3/day", "supply_used": "m3/day", "unused_supply": "m3/day", "priorities": "dimensionless"}, "limitations": ["One fixed day; no storage, losses, routing travel time, or calibrated catchment model.", "Higher numerical priorities have a lower allocation cost and are served first."]}


def _figure_files(element, output_dir, stem):
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    import holoviews as hv

    root = Path(output_dir)
    figure = hv.render(element, backend="matplotlib")
    try:
        figure.savefig(root / (stem + ".png"), dpi=140, bbox_inches="tight")
        figure.savefig(root / (stem + ".svg"), bbox_inches="tight")
    finally:
        plt.close(figure)
    return {"preview": stem + ".png", "vector": stem + ".svg"}


@operation("GeoHoloViewsLineProfile")
def holoviews_line_profile(args, output_dir=None):
    import holoviews as hv

    if len(args["x"]) != len(args["y"]):
        reject("The x and y arrays must have the same length.", "invalid_arguments")
    if any(left >= right for left, right in zip(args["x"], args["x"][1:])):
        reject("Profile coordinates must be strictly increasing.", "invalid_arguments")
    hv.extension("matplotlib")
    xdim = hv.Dimension("distance", label=args["x_label"], unit=args["x_unit"])
    ydim = hv.Dimension("value", label=args["y_label"], unit=args["y_unit"])
    curve = hv.Curve((args["x"], args["y"]), kdims=[xdim], vdims=[ydim], label=args["title"])
    return {**_figure_files(curve, output_dir, "line-profile"), "sample_count": len(args["x"]), "statistics": _summary(args["y"]), "units": {"x": args["x_unit"], "y": args["y_unit"]}}


@operation("GeoGeoViewsPolygonMap")
def geoviews_polygon_map(args, output_dir=None):
    import cartopy.crs as ccrs
    import geoviews as gv
    import holoviews as hv
    from shapely.geometry import shape

    document = json.loads(Path(args["geojson_path"]).read_text(encoding="utf-8"))
    features = document.get("features") if isinstance(document, dict) and document.get("type") == "FeatureCollection" else None
    if not isinstance(features, list) or not 1 <= len(features) <= 1000:
        reject("Provide a WGS84 FeatureCollection with 1 to 1,000 polygons.", "invalid_arguments")
    records, numbers = [], []
    for feature in features:
        geometry = shape(feature["geometry"])
        value = feature.get("properties", {}).get(args["value_field"])
        if geometry.geom_type not in {"Polygon", "MultiPolygon"} or geometry.is_empty or not geometry.is_valid:
            reject("Every feature must have a valid, non-empty polygon geometry.", "invalid_arguments")
        west, south, east, north = geometry.bounds
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90) or east - west > 180:
            reject("Polygon coordinates must be bounded WGS84 longitude/latitude without dateline crossing.", "invalid_arguments")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            reject("Each polygon needs a finite numeric value property.", "invalid_arguments")
        records.append({"geometry": geometry, "value": float(value)})
        numbers.append(float(value))
    hv.extension("matplotlib")
    element = gv.Polygons(records, vdims=[hv.Dimension("value", unit=args["value_unit"])], crs=ccrs.PlateCarree())
    element = element.opts(projection=ccrs.PlateCarree(), color="value", colorbar=True, cmap="viridis", title=args["title"])
    return {**_figure_files(element, output_dir, "polygon-map"), "feature_count": len(records), "statistics": _summary(numbers), "basemap": "none", "units": {"coordinates": "degrees", "value": args["value_unit"]}, "limitations": ["No downloaded coastline, administrative boundary, tile, or basemap is added.", "The map visualizes supplied values; it does not infer mineral resources."]}


@operation("GeoHVPlotHexbin")
def hvplot_hexbin(args, output_dir=None):
    import holoviews as hv
    import hvplot.pandas  # Registers the upstream pandas plotting accessor.
    import hvplot
    import pandas as pd

    if len(args["x"]) != len(args["y"]):
        reject("The x and y arrays must have the same length.", "invalid_arguments")
    if min(args["x"]) == max(args["x"]) or min(args["y"]) == max(args["y"]):
        reject("Both axes must have a non-zero range.", "invalid_arguments")
    hvplot.extension("matplotlib")
    frame = pd.DataFrame({"x": args["x"], "y": args["y"]})
    plot = frame.hvplot.hexbin(x="x", y="y", gridsize=args["gridsize"], min_count=1, colorbar=True, title=args["title"])
    plot = plot.redim(x=hv.Dimension("x", unit=args["x_unit"]), y=hv.Dimension("y", unit=args["y_unit"]))
    return {**_figure_files(plot, output_dir, "hexbin"), "point_count": len(frame), "gridsize": args["gridsize"], "units": {"x": args["x_unit"], "y": args["y_unit"], "bin_color": "point count"}, "limitations": ["Counts are not normalized by physical area and are not probability density estimates."]}


@operation("GeoPanelDataReport")
def panel_data_report(args, output_dir=None):
    import pandas as pd
    import panel as pn
    from bokeh.resources import INLINE

    frame = pd.read_csv(args["csv_path"], nrows=5001)
    if len(frame) > 5000 or len(frame.columns) > 32:
        reject("Reports accept at most 5,000 rows and 32 columns.", "resource_limit")
    if frame.empty or frame.isna().all(axis=None):
        reject("The table must contain data.", "invalid_arguments")
    # Escape every input string; the caller cannot provide executable HTML or callbacks.
    title = "<h1>" + html.escape(args["title"]) + "</h1>"
    count = "<p>Rows: " + str(len(frame)) + "; columns: " + str(len(frame.columns)) + "</p>"
    table = frame.to_html(index=False, escape=True, max_rows=5000, border=0)
    report = pn.Column(pn.pane.HTML(title + count), pn.pane.HTML(table, sizing_mode="stretch_width"))
    path = Path(output_dir) / "data-report.html"
    report.save(str(path), title=args["title"], resources=INLINE, embed=False)
    return {"report": path.name, "row_count": len(frame), "column_count": len(frame.columns), "external_resources": False, "units": {"row_count": "rows", "column_count": "columns"}, "limitations": ["A static escaped table report, not a deployed Panel server.", "Open the downloaded report in a browser; GeoAgent need not execute arbitrary embedded HTML."]}


@operation("GeoGeorastersBlockSum")
def georasters_block_sum(args, output_dir=None):
    import georasters
    from affine import Affine

    values, profile = _raster(args["raster_path"])
    row_factor, column_factor = args["row_factor"], args["column_factor"]
    if values.shape[0] % row_factor or values.shape[1] % column_factor:
        reject("Raster dimensions must be exactly divisible by the block factors.", "invalid_arguments")
    aggregated = georasters.aggregate(values, None, (row_factor, column_factor))
    profile.update(height=values.shape[0] // row_factor, width=values.shape[1] // column_factor, transform=profile["transform"] * Affine.scale(column_factor, row_factor))
    result = _raster_files(aggregated, profile, output_dir, "block-sum", "Extensive quantity per aggregated cell", args["value_unit"])
    return {**result, "aggregation": "sum", "source_shape": list(values.shape), "target_shape": list(aggregated.shape), "units": {"value": args["value_unit"]}, "limitations": ["Use only extensive per-cell quantities; summing temperature, concentration, elevation or reflectance is not a meaningful resampling method.", "No nodata gaps or partial edge blocks are accepted."]}


@operation("GeoPygeoprocessingDistanceTransform")
def pygeoprocessing_distance(args, output_dir=None):
    import numpy as np
    import pygeoprocessing
    import rasterio

    mask, profile = _raster(args["mask_path"], projected=True, binary=True)
    if not np.any(mask == 1):
        reject("At least one region cell must equal one.", "invalid_arguments")
    root = Path(output_dir)
    native = root / "upstream-distance.tif"
    transform = profile["transform"]
    pygeoprocessing.distance_transform_edt((args["mask_path"], 1), str(native), sampling_distance=(transform.a, -transform.e), working_dir=str(root))
    with rasterio.open(native) as src:
        values = src.read(1)
    result = _raster_files(values, profile, root, "distance", "Euclidean distance to supplied region", "m")
    return {**result, "native_raster": native.name, "region_cell_count": int(np.count_nonzero(mask)), "units": {"distance": "m"}, "limitations": ["Planar cell-centre distances, not geodesic, cost-path or slope-adjusted distances.", "The real upstream EDT algorithm is used; Python does not substitute an alternative distance algorithm."]}


@operation("GeoLidarMedianFilter")
def lidar_median_filter(args, output_dir=None):
    import rasterio
    from lidar.filtering import MedianFilter

    values, profile = _raster(args["dem_path"], projected=True)
    if args["kernel_size"] % 2 != 1:
        reject("The median-filter kernel size must be odd.", "invalid_arguments")
    if min(values.shape) < args["kernel_size"]:
        reject("The filter kernel must fit inside the raster.", "invalid_arguments")
    native = Path(output_dir) / "upstream-median.tif"
    MedianFilter(args["dem_path"], kernel_size=args["kernel_size"], out_file=str(native))
    with rasterio.open(native) as src:
        filtered = src.read(1)
    return {**_raster_files(filtered, profile, output_dir, "median-dem", "Median-filtered DEM", args["elevation_unit"]), "native_raster": native.name, "kernel_size": args["kernel_size"], "units": {"elevation": args["elevation_unit"], "kernel_size": "cells"}, "limitations": ["Smoothing only; this operation does not classify mineral targets or extract a full depression hierarchy.", "The upstream lidar/RichDEM/GDAL native dependency profile must be installed explicitly."]}


"""Licensed upstream excerpts, separated from package-release operations."""


@operation("GeoGeemapBoundingPolygon")
def geemap_bounding_polygon(args, output_dir=None):
    from .collection_vendor.spatial.geemap_bbox import bbox_to_geojson

    geometry = bbox_to_geojson(args["bbox"])
    return {"feature": geometry, "units": {"coordinates": "degrees"}, "limitations": ["Offline bounding-polygon conversion only; no Earth Engine service, authentication or image collection is implied."]}


@operation("GeoCollocatePressureMatch")
def collocate_pressure_match(args, output_dir=None):
    import pandas as pd
    from .collection_vendor.spatial.collocate_kernels import nn_pressure

    pressures, values = args["pressures_pa"], args["values"]
    if len(pressures) != len(values):
        reject("Pressure and value arrays must have equal lengths.")
    frame = pd.DataFrame({"air_pressure": pressures, "vals": list(range(len(values)))})
    target = pd.Series({"air_pressure": args["target_pressure_pa"]})
    selected = int(nn_pressure().get_value(target, frame))
    return {"index": selected, "pressure_pa": pressures[selected], "value": values[selected], "units": {"pressure_pa": "Pa", "value": args["value_unit"], "index": "zero-based row"}, "limitations": ["Nearest in pressure-ratio separation, not linear pressure distance or three-dimensional spatial distance.", "An exact separation tie preserves the first input row."]}


@operation("GeoSalemProjectCoordinates")
def salem_project_coordinates(args, output_dir=None):
    import numpy as np
    import pyproj
    from .collection_vendor.spatial.salem_projection import transform_proj

    if len(args["x"]) != len(args["y"]):
        reject("Coordinate arrays must have equal lengths.")
    if args["source_epsg"] == 4326 and any(not (-180 <= x <= 180 and -90 <= y <= 90) for x, y in zip(args["x"], args["y"])):
        reject("Source coordinates exceed WGS84 longitude/latitude bounds.")
    if args["source_epsg"] == 4326 and args["target_epsg"] == 3857 and any(abs(y) > 85.0511287798 for y in args["y"]):
        reject("Web Mercator output is limited to its conventional latitude extent.")
    source = pyproj.Proj("EPSG:" + str(args["source_epsg"]))
    target = pyproj.Proj("EPSG:" + str(args["target_epsg"]))
    x, y = transform_proj(source, target, np.asarray(args["x"], dtype=float), np.asarray(args["y"], dtype=float))
    x, y = np.asarray(x), np.asarray(y)
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        reject("Projection produced non-finite coordinates; check the CRS area of use.")
    unit = "degrees" if args["target_epsg"] == 4326 else "m"
    return {"x": x.tolist(), "y": y.tolist(), "source_epsg": args["source_epsg"], "target_epsg": args["target_epsg"], "axis_order": "x/y; longitude/latitude for geographic input", "units": {"x": unit, "y": unit}, "limitations": ["The upstream Salem projection functions are vendored verbatim; its auto-downloading graphics initialization is not imported.", "Only the declared EPSG choices are exposed; no arbitrary projection grids are downloaded."]}

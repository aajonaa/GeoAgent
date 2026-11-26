"""Author additive spatial handoff files using only the Python standard library.

This generator does not import scientific adapters, inspect the baseline catalog,
install dependencies, run acceptance, or modify shared registration/dispatch.
All generated fixtures are explicitly synthetic. Run by the parent as needed.
"""
from copy import deepcopy
import json
import math
from pathlib import Path

GROUP = Path(__file__).resolve().parent
ROOT = GROUP.parents[4]
ASSET = "assets/github-expansion-spatial"
LOCK = "catalog/source_delivery/github-expansion-20261025/groups/spatial/requirements-spatial.txt"
MODULE = "geological_agent.geology.github_expansion_spatial"
PINS = ["numpy==2.1.3", "scipy==1.15.3", "pandas==2.3.0", "rasterio==1.4.3", "affine==3.0.1",
        "shapely==2.1.2", "pyproj==3.7.2", "scikit-image==0.26.0", "scikit-learn==1.7.2",
        "esda==2.10.0", "libpysal==4.15.0", "pysheds==0.5", "pyflwdir==0.5.12", "numba==0.68.0", "jsonschema==4.25.1"]
WRITTEN = []
UPSTREAM = {
    "pyflwdir": ("0.5.12", "Deltares/pyflwdir", "v0.5.12", "4e598e77611232bbf5fc620919d914de5bfd2cdb", "MIT", "LICENSE"),
    "rasterio": ("1.4.3", "rasterio/rasterio", "1.4.3", "7f8bda2e32df5b5eefc6e1ea6b5f04a946567ede", "BSD-3-Clause", "LICENSE.txt"),
    "shapely": ("2.1.2", "shapely/shapely", "2.1.2", "5fb639d1056888d135fe56bfaf750c9648addeec", "BSD-3-Clause", "LICENSE.txt"),
    "scipy": ("1.15.3", "scipy/scipy", "v1.15.3", "e29dcb65a2040f04819b426a04b60d44a8f69c04", "BSD-3-Clause", "LICENSE.txt"),
    "scikit-image": ("0.26.0", "scikit-image/scikit-image", "v0.26.0", "ee0a7a3ebd9ac8c2602f40e55bc015a3c8a81ae8", "BSD-3-Clause; file-specific notices", "LICENSE.txt"),
    "esda": ("2.10.0", "pysal/esda", "v2.10.0", "6ffd5b66565791cede8703c438c90a819aacd49f", "BSD-3-Clause", "LICENSE.txt"),
    "libpysal": ("4.15.0", "pysal/libpysal", "v4.15.0", "40cab61991086968799609f0856bf1eb2042e5ef", "BSD-3-Clause", "LICENSE.txt"),
    "pysheds": ("0.5", "pysheds/pysheds", "0.5", "58428ce30375604bb7e821a2f1a98f607a12c160", "GPL-3.0 license text; distribution approval pending", "LICENSE"),
    "pyproj": ("3.7.2", "pyproj4/pyproj", "3.7.2", "f16037d2c45c3274ef28b828998267c3390393c8", "MIT", "LICENSE"),
}
DOCS = {
    "pyflwdir": "https://github.com/Deltares/pyflwdir/blob/4e598e77611232bbf5fc620919d914de5bfd2cdb/pyflwdir/flwdir.py#L508",
    "rasterio": "https://rasterio.readthedocs.io/en/stable/topics/features.html",
    "shapely": "https://shapely.readthedocs.io/en/2.1.2/manual.html",
    "scipy": "https://docs.scipy.org/doc/scipy-1.15.3/reference/",
    "scikit-image": "https://scikit-image.org/docs/0.26.x/api/",
    "esda": "https://pysal.org/esda/stable/api.html",
    "libpysal": "https://pysal.org/libpysal/generated/libpysal.weights.DistanceBand.html",
    "pysheds": "https://github.com/pysheds/pysheds/tree/0.5",
    "pyproj": "https://pyproj4.github.io/pyproj/stable/api/geod.html",
}


def obj(properties, description=""):
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False, "description": description}


def num(description="Finite scientific number.", **kwargs):
    return {"type": "number", "description": description, **kwargs}


def integer(description="Integer count or index.", **kwargs):
    return {"type": "integer", "description": description, **kwargs}


def string(description="Explicit text declaration.", **kwargs):
    return {"type": "string", "description": description, "minLength": 1, "maxLength": 1024, **kwargs}


def arr(items=None, description="Ordered values; original ordering is retained.", **kwargs):
    return {"type": "array", "items": items or num(), "description": description,
            "minItems": 1, "maxItems": 256, **kwargs}


def matrix(nullable=False, boolean=False):
    cell = {"type": "boolean"} if boolean else {"type": ["number", "null"] if nullable else "number"}
    return arr(arr(cell, maxItems=64), maxItems=64)


XY = arr(num(minimum=-1e9, maximum=1e9), minItems=2, maxItems=2)
RC = arr(integer(minimum=0, maximum=63), minItems=2, maxItems=2)
CRS = string("EPSG identifier; no caller-supplied PROJ pipelines or network grids.", pattern=r"^EPSG:[0-9]{4,6}$", maxLength=16)
SOURCE = obj({"kind": {"type": "string", "enum": ["synthetic", "caller_supplied"]},
              "citation": string("Caller declaration, not independent source authentication.", minLength=4)}, "Input provenance declaration.")
WKT = string("Valid two-dimensional WKT geometry; no repair or snapping.", maxLength=30000)
OUT_MATRIX = matrix(nullable=True)
BOOL_MATRIX = matrix(boolean=True)
NUMBERS = arr(num(), maxItems=4096)
OUT_WKTS = arr(string("Output geometry WKT.", maxLength=1000000), minItems=0, maxItems=4096)
INFERENCE = {"const": "not_computed", "description": "No permutations or statistical-significance claims."}
GRID_FIELDS = {"values": matrix(nullable=True), "valid_mask": BOOL_MATRIX,
               "origin_xy": XY, "cell_size_m": num("Square cell side in metres.", exclusiveMinimum=0, maximum=1e6)}


GRID_RESULT_KEYS = frozenset({
    "values", "filled_m", "hand_m", "distance_steps", "longest_upstream_steps",
    "order", "path_rc", "cost_s", "distance_m", "excess_cost_s",
})
GRID_RESULT_FIELDS = {
    "origin_xy": XY,
    "cell_size_m": num("Square cell side in output-CRS metres.", exclusiveMinimum=0, maximum=1e6),
    "affine": arr(num(), minItems=6, maxItems=6, description=(
        "Rasterio [a,b,c,d,e,f], not GDAL tuple order: x=a*col+b*row+c; "
        "y=d*col+e*row+f. Pixel corner coordinates; centers add 0.5 to row/col. "
        "North-up square grids use [s,0,x0,0,-s,y0].")),
    "shape": arr(integer(minimum=1, maximum=64), minItems=2, maxItems=2,
                 description="Output grid [height,width]; path_rc indexes this grid."),
}


def data_schema(fields, geographic=False):
    return obj({"source": SOURCE, "crs": CRS,
                "coordinate_unit": {"const": "degree" if geographic else "m"}, **fields},
               "Exact scientific JSON file schema. Unknown fields are errors.")


def grid_schema(unit, extra=None):
    return data_schema({**GRID_FIELDS, "value_unit": {"const": unit}, **(extra or {})})


SYNTHETIC = {"kind": "synthetic", "citation": "Explicit synthetic analytic fixture; not a geological observation or mineral evidence."}


def fixture(fields, geographic=False):
    return {"source": deepcopy(SYNTHETIC), "crs": "EPSG:4326" if geographic else "EPSG:32631",
            "coordinate_unit": "degree" if geographic else "m", **fields}


def grid_fixture(values, unit, **extra):
    return fixture({"values": values, "valid_mask": [[v is not None for v in row] for row in values],
                    "origin_xy": [0, len(values)], "cell_size_m": 1, "value_unit": unit, **extra})


def records():
    rows = []

    def add(short, function, package, callable_name, task, schema, result, example, comparison, oracle, constraints=""):
        if GRID_RESULT_KEYS.intersection(result):
            result = {**result, **GRID_RESULT_FIELDS}
            constraints += " Output includes origin_xy, cell_size_m, Rasterio affine and shape; retain them with arrays or row/column paths."
        rows.append({"id": "GeoSpatial" + short, "function": function, "package": package,
                     "upstream_callable": callable_name, "task": task, "data_schema": schema,
                     "result_schema": obj(result), "fixture": example, "comparison": comparison,
                     "oracle": oracle, "constraints": constraints})

    square = "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))"
    left = "POLYGON ((0 0, 1 0, 1 2, 0 2, 0 0))"
    right = "POLYGON ((1 0, 2 0, 2 2, 1 2, 1 0))"
    geometry_result = {"wkt": WKT, "area_m2": num("Planar output area in square metres.", minimum=0)}
    raster_result = {"values": OUT_MATRIX, "valid_mask": BOOL_MATRIX, "origin_xy": XY, "cell_size_m": num()}
    vector_nearest = "GeoShapelyGeometry measures an existing geometry; it does not construct this topology. GeoPandasSpatialJoin returns matching feature indices without creating new geometry."

    add("RasterReproject", "raster_reproject", "rasterio", "rasterio.warp.reproject",
        "Reproject a bounded metric raster onto an explicit WGS84-based target grid using nearest resampling and explicit NoData propagation.",
        grid_schema("dimensionless", {"dst_crs": CRS, "dst_shape": arr(integer(minimum=1, maximum=64), minItems=2, maxItems=2),
                    "dst_origin_xy": XY, "dst_cell_size_m": num(exclusiveMinimum=0, maximum=1e6), "resampling": {"const": "nearest"}}),
        {**raster_result, "dst_crs": CRS},
        grid_fixture([[1, None], [3, 4]], "dimensionless", dst_crs="EPSG:32631", dst_shape=[2, 2], dst_origin_xy=[1, 2], dst_cell_size_m=1, resampling="nearest"),
        "GeoRasterioWindow only crops integer windows without resampling; GeoSalemProjectCoordinates transforms point coordinates, not a masked raster grid.",
        "An explicit one-cell east target-grid shift produces [[null,null],[4,null]] and exactly one valid cell.",
        "Nearest resampling is explicit. Source and destination must be projected WGS84-based CRSs in metres; no datum-shift grids. Top-level crs describes the destination; source_crs retains the source CRS. The supplemental cross-CRS fixture uses the analytic equatorial UTM-to-Web-Mercator coordinate.")
    add("PolygonRasterize", "polygon_rasterize", "rasterio", "rasterio.features.rasterize",
        "Burn ordered site polygons and explicit class IDs into a declared raster grid; later polygons win overlaps.",
        data_schema({"polygons_wkt": arr(WKT, maxItems=32), "class_ids": arr(integer(minimum=1, maximum=2147483647), maxItems=32),
                     "shape": arr(integer(minimum=1, maximum=64), minItems=2, maxItems=2), "valid_mask": BOOL_MATRIX,
                     "origin_xy": XY, "cell_size_m": num(exclusiveMinimum=0, maximum=1e6), "all_touched": {"type": "boolean"}}),
        raster_result, fixture({"polygons_wkt": [left], "class_ids": [7], "shape": [2, 2], "valid_mask": [[True, True], [True, True]],
                                "origin_xy": [0, 2], "cell_size_m": 1, "all_touched": False}),
        "EarthGeoNotebookPolygonSubset masks an existing raster; this constructs a new classified raster from vector site polygons.",
        "A 1x2-m rectangle occupies the left column of a 2x2 one-metre grid: [[7,0],[7,0]].",
        "Explicit all_touched and last-input-polygon-wins rules; zero denotes unburned valid background.")
    add("RasterPolygonize", "raster_polygonize", "rasterio", "rasterio.features.shapes",
        "Convert connected integer raster classes into georeferenced polygons while excluding explicitly invalid cells.",
        grid_schema("class_id"), {"features": arr(obj({"class_id": integer(), "wkt": WKT, "area_m2": num(minimum=0)}), maxItems=4096)},
        grid_fixture([[2, 2], [2, None]], "class_id"),
        "GeoMapColorExtract first detects colors and regions in a map; this polygonizes supplied scientific class IDs without segmentation or color detection.",
        "Three one-square-metre cells of class 2 produce one polygon of area 3; the invalid fourth cell is excluded.", "Fixed four-cell connectivity; int32 classes only.")
    add("PolygonIntersection", "polygon_intersection", "shapely", "shapely.intersection",
        "Construct the exact intersection geometry of two projected site or exclusion-zone polygons.",
        data_schema({"polygon_a_wkt": WKT, "polygon_b_wkt": WKT}), geometry_result,
        fixture({"polygon_a_wkt": square, "polygon_b_wkt": "POLYGON ((1 0, 3 0, 3 2, 1 2, 1 0))"}), vector_nearest,
        "Overlapping 2x2-m squares offset by 1 m have an intersection area of 2 m2.")
    add("CoverageUnion", "coverage_union", "shapely", "shapely.coverage_union_all",
        "Dissolve a valid edge-matched polygon coverage into its combined site footprint.",
        data_schema({"polygons_wkt": arr(WKT, minItems=2, maxItems=32)}), geometry_result,
        fixture({"polygons_wkt": [left, right]}), vector_nearest,
        "Two edge-matched 1x2-m rectangles dissolve to area 4 m2 and perimeter 8 m; overlapping coverages are rejected.",
        "GEOS >=3.12 is required for coverage validation. Gaps remain gaps; no snapping or repair.")
    add("ConstrainedTriangulation", "constrained_triangulation", "shapely", "shapely.constrained_delaunay_triangles",
        "Triangulate site polygons while preserving parcel and hole boundaries for terrain-mesh preparation.",
        data_schema({"polygon_wkt": WKT}), {"triangles_wkt": OUT_WKTS, "areas_m2": NUMBERS},
        fixture({"polygon_wkt": square}), vector_nearest,
        "A 2x2-m square has exactly two triangles of area 2 m2 each; their union is the original polygon.",
        "No elevation interpolation. Input polygon topology remains authoritative; GEOS >=3.12 gate.")

    dem = [[5, 5, 5], [5, 1, 5], [5, 5, 5]]
    direction = [[0]*5 for _ in range(5)]
    direction[2] = [0, 1, 1, 0, 0]
    channels = [[False]*5 for _ in range(5)]
    channels[2][3] = True
    hand_dem = [[10]*5 for _ in range(5)]
    hand_dem[2] = [10, 5, 4, 2, 10]
    hydro_nearest = "GeoPyshedsFlowAccumulation returns flow directions and contributing-cell counts; EarthLandlabFlowDirections selects receivers. Neither returns this drainage diagnostic from an explicitly supplied graph."
    add("DepressionFill", "depression_fill", "pysheds", "pysheds.grid.Grid.fill_depressions",
        "Condition a complete DEM with priority-flood depression filling and quantify fill depth and storage volume.",
        grid_schema("m"), {"filled_m": OUT_MATRIX, "fill_depth_m": OUT_MATRIX, "fill_volume_m3": num(minimum=0)}, grid_fixture(dem, "m"),
        "GeoPyshedsFlowAccumulation may condition terrain internally, but does not expose an independently usable filled DEM, per-cell fill depths, or depression-storage volume.",
        "A 3x3 grid with rim elevation 5 m and center 1 m fills its center by 4 m; at 1-m cells the volume is 4 m3.",
        "Complete finite DEM only; no flat resolution, flow accumulation, slope calculation, or water-volume forecast.")
    add("HeightAboveDrainage", "height_above_drainage", "pysheds", "pysheds.grid.Grid.compute_hand",
        "Compute flow-connected height above a supplied drainage-channel mask using declared D8 directions and elevations.",
        grid_schema("m", {"directions": matrix(), "channels": BOOL_MATRIX}), {"hand_m": OUT_MATRIX, "reachable_mask": BOOL_MATRIX},
        grid_fixture(hand_dem, "m", directions=direction, channels=channels), hydro_nearest,
        "Interior east-flow chain elevations 5,4,2 m ending at a channel gives HAND 3,2,0 m; unrelated cells are null.",
        "Complete DEM, acyclic interior D8 graph, nonascending downstream elevation, explicit channels; HAND is not modeled flood depth.")
    add("DistanceToOutlet", "distance_to_outlet", "pysheds", "pysheds.grid.Grid.distance_to_outlet",
        "Calculate downstream topological D8 travel distance to a specified interior outlet.",
        grid_schema("D8_code", {"outlet_rc": RC}), {"distance_steps": OUT_MATRIX}, grid_fixture(direction, "D8_code", outlet_rc=[2, 3]),
        hydro_nearest + " Existing catchment delineation returns membership, not per-cell outlet path lengths.",
        "Three-cell east-flow chain gives downstream distances 2,1,0 D8 steps; noncontributing cells remain null.", "Steps are not metres or travel times; terminal direction is zero.")
    add("DistanceToRidge", "distance_to_ridge", "pysheds", "pysheds.grid.Grid.distance_to_ridge",
        "Calculate the longest upstream D8 path from each routed cell to an originating divide.",
        grid_schema("D8_code"), {"longest_upstream_steps": OUT_MATRIX}, grid_fixture(direction, "D8_code"), hydro_nearest,
        "Three-cell east-flow chain gives longest upstream path lengths 0,1,2 D8 steps; a branched oracle uses the longest parent.",
        "Longest upstream topological path, not the shortest distance to an outlet or Euclidean ridge proximity.")
    confluence = [[0]*5 for _ in range(5)]
    confluence[1][1], confluence[1][3], confluence[2][2] = 2, 8, 4
    streammask = [[False]*5 for _ in range(5)]
    for r, c in [(1, 1), (1, 3), (2, 2), (3, 2)]:
        streammask[r][c] = True
    add("StrahlerOrder", "strahler_order", "pyflwdir", "pyflwdir.FlwdirRaster.stream_order",
        "Assign Strahler stream order to an explicitly selected, downstream-connected D8 channel network.",
        grid_schema("D8_code", {"channels": BOOL_MATRIX}), {"order": OUT_MATRIX}, grid_fixture(confluence, "D8_code", channels=streammask),
        hydro_nearest, "Original oracle retained: two first-order tributaries give order 2 at [2,2] and zero-direction terminal [3,2]. Supplemental independent confluences [2,2,1] give 3, while [1,1,2] give 2; the downstream terminals retain those orders.",
        "PyFlwDir 0.5.12 original upstream algorithm, not Pysheds stream_order or a local correction. Zero-direction terminals and multi-tributary junctions are supported. Nonchannel cells are null; the selected network is supplied, not inferred by a flow-accumulation threshold.")
    add("TerrainContours", "terrain_contours", "scikit-image", "skimage.measure.find_contours",
        "Extract elevation isolines from a metric DEM using marching squares with explicit levels and nodata mask.",
        grid_schema("m", {"levels_m": arr(num(), maxItems=16)}),
        {"lines": arr(obj({"level_m": num(), "coordinates": arr(XY, minItems=2, maxItems=32768)}), minItems=0, maxItems=16384)},
        grid_fixture([[0, 1, 2], [0, 1, 2], [0, 1, 2]], "m", levels_m=[.5]),
        "HydroModelsPyDEMTerrainDerivatives returns slope/direction; EarthSimRasterCrossSection samples an existing line. This constructs elevation isolines and does not segment imagery.",
        "For columns 0,1,2 m at 1-m spacing, the 0.5-m contour lies at x=1 m and extends 2 m between outer sample centers.",
        "Sample centers use half-cell offsets. Low-valued cells are fully connected in saddle ambiguities; no nodata interpolation.")

    stats_fields = {"points_xy": arr(XY, minItems=4, maxItems=256), "values": arr(num(), minItems=4, maxItems=256),
                    "radius_m": num(exclusiveMinimum=0, maximum=1e6), "value_unit": {"type": "string", "enum": ["dimensionless", "m", "mg/kg", "count"]}}
    stats_example = fixture({"points_xy": [[0,0], [1,0], [1,1], [0,1]], "values": [1,2,3,4], "radius_m": 1.01, "value_unit": "dimensionless"})
    stats_note = "SpatialMoranI produces one global univariate cross-product statistic using KNN weights; this uses explicit metric distance-band weights and returns a different statistic."
    stats_limits = "At most 256 distinct points; islands and constant observations rejected. No permutations, significance labels, inferred causation, kriging, or interpolation."
    local_out = {"local_i": NUMBERS, "quadrant": arr(integer(minimum=1, maximum=4)), "inference": INFERENCE}
    add("LocalMoran", "local_moran", "esda", "esda.moran.Moran_Local",
        "Calculate per-site univariate local Moran association and descriptive PySAL quadrants.", data_schema(stats_fields), local_out, stats_example,
        stats_note, "Four square-corner observations [1,2,3,4] with edge-only neighbors yield local I [-0.45,0.15,0.15,-0.45].", stats_limits)
    add("BivariateLocalMoran", "bivariate_local_moran", "esda", "esda.moran.Moran_Local_BV",
        "Measure local association between a focal site variable and a different variable at its neighbors.",
        data_schema({**stats_fields, "other_values": arr(num(), minItems=4, maxItems=256), "other_value_unit": string("Explicit second-variable units.")}),
        local_out, {**stats_example, "other_values": [4,3,2,1], "other_value_unit": "m"},
        stats_note + " The cross-variable association cannot be obtained by changing a coordinate component or univariate threshold.",
        "Oppositely ordered second variable [4,3,2,1] gives [0.45,-0.15,-0.15,0.45] by independent standardized cross-products.", stats_limits)
    add("LocalGetisOrd", "local_getis_ord", "esda", "esda.getisord.G_Local",
        "Compute self-excluding local Getis-Ord Gi concentration ratios for strictly positive site observations.",
        data_schema(stats_fields), {"gi": NUMBERS, "inference": INFERENCE}, stats_example, stats_note,
        "Binary edge weights and values [1,2,3,4] give neighbor-sum / nonself-total ratios [6/9,4/8,6/7,4/6].",
        stats_limits + " Fixed Gi (not Gi-star), binary weights; descriptive ratios only.")
    add("GlobalGeary", "global_geary", "esda", "esda.geary.Geary",
        "Measure whole-region spatial dissimilarity using squared neighbor differences in global Geary C.",
        data_schema(stats_fields), {"geary_c": num(), "inference": INFERENCE}, stats_example, stats_note,
        "Four-square rook graph has directed row-weighted squared-difference sum 12, centered sum squares 5 and C=(3/8)*(12/5)=0.9.", stats_limits)
    binary_fields = {**stats_fields, "value_unit": {"const": "binary_class"}}
    add("BinaryJoinCounts", "binary_join_counts", "esda", "esda.join_counts.Join_Counts",
        "Count like-class and unlike-class spatial joins in a binary site-presence map.",
        data_schema(binary_fields), {"black_black": num(), "white_white": num(), "mixed": num(), "total_edges": num(), "inference": INFERENCE},
        {**stats_example, "values": [0,0,1,1], "value_unit": "binary_class"}, stats_note,
        "The square's four undirected edges contain one 1-1 join, one 0-0 join, and two mixed joins.", stats_limits + " Both binary classes must occur.")
    add("LocalGeary", "local_geary", "esda", "esda.geary_local.Geary_Local.fit",
        "Locate site-level neighbor dissimilarity using standardized local Geary squared differences.",
        data_schema(stats_fields), {"local_c": NUMBERS, "inference": INFERENCE}, stats_example, stats_note,
        "Population variance is 1.25; local mean squared neighbor differences / 1.25 equal [4,0.8,0.8,4].", stats_limits)

    ends = {"start_rc": RC, "end_rc": RC}
    route = grid_fixture([[1,1,1]], "s/m", start_rc=[0,0], end_rc=[0,2])
    access_note = "DeepTimeNearestNeighbor/CCSNearestNeighbor and EnergyNearestFacility measure point separation; they do not solve masked raster access networks."
    cost_limits = "Four-neighbor movement only. Edge cost is mean endpoint seconds/metre times cell side; invalid cells are impassable. Results describe a declared planning model, not observed travel times."
    add("LeastCostPath", "least_cost_path", "scikit-image", "skimage.graph.route_through_array",
        "Find an explicit minimum-cost four-neighbor route across a masked site-access raster.", grid_schema("s/m", ends),
        {"path_rc": arr(RC, minItems=2, maxItems=4096), "cost_s": num(minimum=0)}, route, access_note,
        "A single row of three unit-cost cells has path [[0,0],[0,1],[0,2]] and total edge cost 2 seconds.", cost_limits)
    add("CostAllocation", "cost_allocation", "scipy", "scipy.sparse.csgraph.dijkstra",
        "Allocate reachable raster cells to supplied service sites by network cost, with deterministic first-site tie handling.",
        grid_schema("s/m", {"sources_rc": arr(RC, maxItems=16)}), {"cost_s": OUT_MATRIX, "owner_index": OUT_MATRIX},
        grid_fixture([[1,1,1]], "s/m", sources_rc=[[0,0],[0,2]]), access_note,
        "Sites at both ends of a three-cell row yield costs [0,1,0] and owner indices [0,0,1]; a separate oracle includes barriers.", cost_limits)
    add("EuclideanProximity", "euclidean_proximity", "scipy", "scipy.ndimage.distance_transform_edt",
        "Calculate exact raster-cell-center Euclidean distances to declared target cells at metric resolution.",
        grid_schema("binary_target"), {"distance_m": OUT_MATRIX}, grid_fixture([[1,0],[0,0]], "binary_target"), access_note,
        "One target at the upper-left of a 2x2 unit grid produces [[0,1],[1,sqrt(2)]] metres.",
        "Mask excludes output cells but does not form a travel barrier for straight-line distance; not a point nearest-neighbor query.")
    add("ResistanceDistance", "resistance_distance", "scipy", "scipy.linalg.pinvh",
        "Compute effective resistance between access cells by the pseudoinverse of the graph conductance Laplacian.",
        grid_schema("s/m", ends), {"effective_resistance_s": num(minimum=0), "connected_cells": integer(minimum=2, maximum=256)},
        grid_fixture([[1,1],[1,1]], "s/m", start_rc=[0,0], end_rc=[1,1]), access_note,
        "Opposite corners of a unit-resistance 2x2 square have two 2-unit series routes in parallel: effective resistance 1.",
        cost_limits + " Maximum 256 total cells. Reciprocal edge costs are conductances; output is a connectivity diagnostic, not shortest travel time or geophysical resistivity.")
    add("CostCorridor", "cost_corridor", "scipy", "scipy.sparse.csgraph.dijkstra",
        "Map all cells within an explicit excess-cost budget of the optimum source-destination access route.",
        grid_schema("s/m", {**ends, "max_excess_s": num(minimum=0, maximum=1e12)}),
        {"excess_cost_s": OUT_MATRIX, "corridor_mask": BOOL_MATRIX, "optimal_cost_s": num(minimum=0)},
        grid_fixture([[1,1,1],[1,1,1]], "s/m", start_rc=[0,0], end_rc=[0,2], max_excess_s=0), access_note,
        "Across the top row of a 2x3 unit grid, optimum cost is 2; excess-cost rows are [0,0,0] and [2,2,2].",
        cost_limits + " A corridor is the set of feasible detours, not a second parameterization of the single returned path.")
    add("CapacityMaxFlow", "capacity_max_flow", "scipy", "scipy.sparse.csgraph.maximum_flow",
        "Solve maximum haul-throughput flow on a four-neighbor raster with integer edge capacities derived from endpoint minima.",
        grid_schema("tonne/day", ends), {"maximum_flow_tonne_day": integer(minimum=0), "capacity_model": {"const": "four_neighbor_edge_minimum_of_endpoint_capacities"}},
        grid_fixture([[5,3,4]], "tonne/day", start_rc=[0,0], end_rc=[0,2]), access_note,
        "A series corridor with endpoint capacities [5,3,4] has edge capacities [3,3], so the maximum throughput is 3 tonnes/day.",
        "A planning-network edge-capacity model, not a hydraulic flow model. Node throughput is not separately constrained. Each valid integer capacity is <=1000000.")

    add("EllipsoidalPolygonArea", "ellipsoidal_polygon_area", "pyproj", "pyproj.Geod.polygon_area_perimeter",
        "Measure oriented area and perimeter of a WGS84 geodesic polygon on the reference ellipsoid.",
        data_schema({"polygon_wkt": WKT}, geographic=True), {"signed_area_m2": num(), "perimeter_m": num(minimum=0)},
        fixture({"polygon_wkt": "POLYGON ((0 0, 90 0, 0 90, 0 0))"}, geographic=True),
        "GeoWGS84BBoxAreaKm2 estimates spherical bounding-box area; GeoShapelyGeometry uses planar geometry. This integrates ellipsoidal geodesic polygon edges.",
        "The equator/meridian/pole triangle is one eighth of the oblate WGS84 spheroid surface; compare the closed-form spheroid-area expression.",
        "Single valid exterior without holes; longitude span <180 degrees; signed orientation is retained.")
    add("GeodesicTransect", "geodesic_transect", "pyproj", "pyproj.Geod.npts",
        "Construct equal-distance survey stations along a shortest WGS84 ellipsoidal geodesic transect.",
        data_schema({"start_lonlat": XY, "end_lonlat": XY, "interior_points": integer(minimum=1, maximum=254)}, geographic=True),
        {"points_lonlat": arr(XY, minItems=3, maxItems=256), "length_m": num(exclusiveMinimum=0)},
        fixture({"start_lonlat": [0,0], "end_lonlat": [4,0], "interior_points": 3}, geographic=True),
        "GeoHaversineDistance and GeoBearing return scalar spherical measurements; this produces actual equal-spacing ellipsoidal survey coordinates.",
        "On the equator from 0 to 4 degrees, stations are at longitudes 0,1,2,3,4; length is 6378137*pi*4/180 metres.",
        "Reject coincident and antipodal endpoints; longitudes may wrap in returned WGS84 coordinates.")
    add("ProjectionDistortion", "projection_distortion", "pyproj", "pyproj.Proj.get_factors",
        "Assess metric projection scale, area, angular distortion, and convergence at declared WGS84 survey locations.",
        data_schema({"projection_crs": CRS, "points_lonlat": arr(XY, maxItems=256)}, geographic=True),
        {"meridional_scale": NUMBERS, "parallel_scale": NUMBERS, "areal_scale": NUMBERS,
         "angular_distortion_degrees": NUMBERS, "meridian_convergence_degrees": NUMBERS},
        fixture({"projection_crs": "EPSG:32631", "points_lonlat": [[3,0]]}, geographic=True),
        "GeoCheckCRSConsistency compares identifier text and GeoSalemProjectCoordinates transforms coordinates; neither quantifies projection distortion.",
        "UTM zone 31 at its equatorial central meridian has linear scales 0.9996, area scale 0.9996^2, and zero convergence/angular distortion within numerical tolerance.",
        "WGS84-based projected CRS only; factors are local and are not a correction of source observations.")
    add("MaximumInscribedCircle", "maximum_inscribed_circle", "shapely", "shapely.maximum_inscribed_circle",
        "Find the pole of inaccessibility and largest contained circular footprint in a site polygon within an explicit tolerance.",
        data_schema({"polygon_wkt": WKT, "tolerance_m": num(exclusiveMinimum=0, maximum=10000)}),
        {"center_xy": XY, "boundary_xy": XY, "radius_m": num(minimum=0), "tolerance_m": num(exclusiveMinimum=0)},
        fixture({"polygon_wkt": square, "tolerance_m": .001}),
        "GeoShapelyGeometry returns centroids and bounds; generic buffers expand a supplied center. This optimizes a feasible center and radius within the actual boundary.",
        "A 2x2-m square has a largest contained circle centered at [1,1] with radius 1 m.", "GEOS >=3.12 gate; explicit geometric tolerance, not a claim of safe infrastructure siting.")
    add("SiteVoronoi", "site_voronoi", "shapely", "shapely.voronoi_polygons",
        "Partition a site region into clipped Voronoi service polygons in original site-point order.",
        data_schema({"polygon_wkt": WKT, "points_xy": arr(XY, minItems=2, maxItems=64)}),
        {"cells_wkt": OUT_WKTS, "areas_m2": NUMBERS}, fixture({"polygon_wkt": square, "points_xy": [[.5,1],[1.5,1]]}),
        "Generic nearest-neighbor entries return a point match; this constructs and clips the complete planar service-area partition.",
        "Two symmetric sites in a 2x2-m square split it at x=1 into two polygons of area 2 m2.",
        "GEOS >=3.12 ordered Voronoi output required; distinct sites must lie within the region; no coordinate snapping.")
    add("SiteParcelSplit", "site_parcel_split", "shapely", "shapely.ops.split",
        "Split site parcels along a declared infrastructure alignment while retaining all resulting polygon pieces.",
        data_schema({"polygon_wkt": WKT, "splitter_wkt": WKT}), {"parcels_wkt": OUT_WKTS, "areas_m2": NUMBERS},
        fixture({"polygon_wkt": square, "splitter_wkt": "LINESTRING (1 -1, 1 3)"}), vector_nearest,
        "A vertical line x=1 splits a 2x2-m square into exactly two parcels of area 2 m2, conserving total area 4 m2.",
        "A valid simple 2D LineString is required; no snapping. Nonintersecting alignments legitimately return the unchanged parcel.")
    return rows


def supplementary_fixtures():
    """Three explicit synthetic regressions; no scientific package is imported."""
    result = {}
    for label, left_branch_order in (("221", 2), ("112", 1)):
        directions = [[0] * 7 for _ in range(7)]
        cells = {(1, 4): 4, (1, 5): 8, (2, 2): 2, (2, 3): 4,
                 (2, 4): 8, (3, 3): 4, (4, 3): 0}
        if left_branch_order == 2:
            cells.update({(1, 1): 2, (1, 2): 4})
        channels = [[False] * 7 for _ in range(7)]
        for (row, col), direction in cells.items():
            directions[row][col] = direction
            channels[row][col] = True
        result["strahler_order_multi_" + label + ".json"] = grid_fixture(
            directions, "D8_code", channels=channels)
    # At longitude 3 degrees, latitude 0: UTM 31N is (500000,0);
    # Web Mercator is (6378137*pi/60,0). Both one-cell rasters center there.
    # This is an analytic coordinate, not a call to the tested warp/PROJ.
    result["raster_reproject_cross_crs.json"] = grid_fixture(
        [[17]], "dimensionless", origin_xy=[499999.5, 0.5],
        dst_crs="EPSG:3857", dst_shape=[1, 1],
        dst_origin_xy=[6378137.0 * math.pi / 60 - 0.5, 0.5],
        dst_cell_size_m=1, resampling="nearest")
    return result


def registration(package):
    version, repo, tag, commit, license_name, _ = UPSTREAM[package]
    return {"asset_version": "1.0.0", "provider": repo.split('/')[0], "license": None,
            "upstream_license": license_name, "source_url": "https://github.com/" + repo,
            "source_commit": commit, "official_protocol_version": None,
            "official_protocol": {"applicability": "not_applicable", "name": None, "version": None},
            "metadata_profile": "scientific", "runtime": {"python": ">=3.12,<3.13", "dependency_lock": LOCK,
            "environment_version": "github-expansion-spatial-20261025-r2"},
            "lifecycle": {"registration": "not_registered", "contract_validation": "not_run", "unit_validation": "not_run",
                          "workflow_validation": "not_run", "platform_validation": "not_run", "release_status": "draft"},
            "pending_fields": ["adapter_license", "receiving_lab_approval", "parent_cpu_acceptance", "parent_registry_integration"],
            "platform_validation": "not_run"}


def provenance_schema(package):
    return obj({"tool": string(), "upstream_url": string(), "source_mode": {"const": "package_release"},
                "reviewed_archive_commit": {"const": UPSTREAM[package][3]},
                "installed_versions": obj({name: {"const": version} for name, version in (p.split("==") for p in PINS)}),
                "vendored_source": arr(string(), minItems=0, maxItems=0),
                "input_sha256": string(pattern="^[a-f0-9]{64}$"), "implementation_sha256": string(pattern="^[a-f0-9]{64}$"),
                "contract_sha256": string(pattern="^[a-f0-9]{64}$"), "output_sha256": obj({}),
                "network_required": {"const": False}, "runtime_source_correspondence": string(maxLength=2048)})


def make_tool(row):
    package = row["package"]
    version, repo, tag, commit, license_name, license_path = UPSTREAM[package]
    path = ASSET + "/" + row["function"] + ".json"
    schema = obj({"data_path": string("Task-relative bounded JSON using metadata.scientific_contract.data_schema. All declared fields, source, units, and CRS are required.", maxLength=512)})
    result = obj({"data": row["result_schema"], "crs": CRS, "source": SOURCE,
                  "units": obj({"coordinates": string(), "value": string(), "secondary": string()}),
                  "artifacts": arr(string(), minItems=0, maxItems=0), "provenance": provenance_schema(package)})
    if row["id"] == "GeoSpatialRasterReproject":
        result["properties"]["source_crs"] = deepcopy(CRS)
        result["required"].append("source_crs")
    desc = row["task"] + " Requires explicit units, CRS and source in the JSON file. " + row["constraints"]
    definition = {"type": "function", "function": {"name": row["id"], "description": desc, "parameters": schema}}
    return {"id": row["id"], "name": row["id"], "description": desc, "input_schema": schema, "output_schema": result,
            "constraints": {"finite_numbers_only": True, "no_implicit_reprojection": True, "no_automatic_dependency_install": True,
                            "max_file_bytes": 262144, "max_json_bytes": 262144, "max_grid_cells": 4096},
            "metadata": {"category": "github_expansion_spatial", "input_format": "Bounded UTF-8 scientific JSON with declared source, CRS, units and masks",
                         "output_format": "Schema-validated numeric/geometric JSON with content-hash provenance",
                         "source": "https://github.com/" + repo,
                         "upstream": {"package": package, "version": version, "source_mode": "package_release", "license": license_name,
                                      "url": "https://github.com/" + repo, "requirements": PINS, "release_tag": tag,
                                      "callable": row["upstream_callable"], "source_commit": commit,
                                      "license_url": "https://github.com/" + repo + "/blob/" + commit + "/" + license_path},
                         "scientific_contract": {"implementation_kind": "upstream_library", "review_status": "acceptance_pending",
                                                 "formal_eligible": False, "data_schema": row["data_schema"],
                                                 "distinct_from_existing": row["comparison"], "numeric_oracle": row["oracle"],
                                                 "status": "source_authored_unverified"}},
            "category": "github_expansion_spatial", "function": definition, "function_definition": deepcopy(definition),
            "version": "1.0.0", "example_arguments": {"data_path": path},
            "limitations": [row["constraints"], "Source citations are caller declarations, not authentication.",
                            "All included examples are synthetic; no mineral identification, grade, reserves, engineering safety, or significance is inferred.",
                            "NOT TESTED / NOT DEPLOYED / NOT SUBMITTED. Parent owns integration and CPU acceptance."],
            "source_interface": {"status": "source_revised_unverified", "kind": "github_expansion_spatial", "path_fields": ["data_path"],
                                 "network_required": False, "pure": False, "validation": "acceptance_pending",
                                 "entrypoint": {"callable": MODULE + ":" + row["function"], "argument_parameter": "args", "bound_arguments": {}}},
            "error_contract": {"direct_exception": "ScientificToolError", "fields": ["code", "message", "retryable"],
                               "codes": ["invalid_arguments", "missing_input", "missing_dependency", "incompatible_dependency", "resource_limit",
                                         "invalid_input", "invalid_result", "invalid_path", "empty_input", "unsupported_conditions", "output_conflict", "upstream_failure"],
                               "retry_policy": "Correct arguments, resource bounds, package pins or unsupported conditions before retry; deterministic failures are not blindly retried."},
            "tags": ["geology", "spatial", "cpu", package], "registration_metadata": registration(package)}


def skill(key, title, rows):
    names = [r["id"] for r in rows]
    path = "catalog/skills/" + key + "/SKILL.md"
    description = " ".join(r["task"] for r in rows)
    delivery = {"source_candidates": names, "unavailable_references": [],
                "availability_status": "tool_candidates_available_workflow_unverified", "workflow_validation": "not_run",
                "deployment_status": "not_deployed", "submission_status": "not_submitted", "model_workflow_validation": "not_run",
                "receiving_lab_approval": "pending"}
    record = {"id": key, "name": title, "description": description, "tool_references": names, "skill_file": path,
              "metadata": {"canonical_skill_file": path, "validation": "not_run"}, "delivery": delivery,
              "registration_metadata": registration(rows[0]["package"])}
    front = ["---", "id: " + key.replace("-", "_"), "name: " + json.dumps(title), "description: " + json.dumps(description),
             "when_to_use: " + json.dumps(title + " for declared spatial data and a concrete scientific task"), "tools:"]
    front += ["- " + n for n in names]
    front += ["required_inputs:", "- Task-relative JSON matching the exact per-tool data schema", "- Explicit source citation, CRS, units, grid mask or valid geometries",
              "constraints:", "- Select the scientific task first; never load or call every tool merely because it is present.",
              "- No implicit CRS changes, nodata filling, geometry repair, rescaling or dependency installation.",
              "- Synthetic fixtures are analytic examples, not field observations.", "expected_outputs:",
              "- Numeric or WKT evidence with explicit units and SHA-256 provenance", "---", "", "# " + title,
              "", "## When to use", "", description, "", "## Required inputs", "",
              "Use the exact `metadata.scientific_contract.data_schema` in `catalog-additions.json`. Every object forbids extra fields. "
              "Coordinates use x/y or longitude/latitude ordering; grid indices use row/column. A grid origin is its top-left corner; "
              "cell size is square and in metres. Each false mask cell must be JSON null, and each true cell must be finite. "
              "Files are bounded to 256 KiB and grids to 4096 cells. Source declarations do not authenticate measurements.",
              "", "## Workflow", "", "1. Select one operation matching the requested scientific result.",
              "2. Establish units, CRS, source citation and the operation-specific topology or mask policy.",
              "3. Use its explicit named function with `args` as a dictionary or JSON-object string.",
              "4. Preserve returned units, masks, geometry ordering, null semantics and provenance in downstream work.",
              "5. Hand off unresolved input/domain failures; do not silently select another model or install a package.",
              "", "## Tool contracts", ""]
    if "GeoSpatialStrahlerOrder" in names:
        front += ["## Strahler r2 regression handoff", "",
                  "Use PyFlwDir 0.5.12 at commit 4e598e77611232bbf5fc620919d914de5bfd2cdb. "
                  "Keep the original terminal order 2; never increase the oracle to match the Pysheds defect. "
                  "Additional synthetic inputs are assets/github-expansion-spatial/strahler_order_multi_221.json "
                  "and strahler_order_multi_112.json in the same directory. Expected confluence/terminal orders are 3 and 2. "
                  "No artificial outlets, tributary-count restriction, or local Strahler recurrence is applied.", ""]
    if "GeoSpatialRasterReproject" in names:
        front += ["## Reprojection r2 regression handoff", "",
                  "Top-level crs is the destination; source_crs is the original source CRS. "
                  "Keep destination origin, cell size, affine and shape with the returned raster. "
                  "assets/github-expansion-spatial/raster_reproject_cross_crs.json maps a one-cell UTM31N "
                  "equatorial patch to Web Mercator; its value remains 17.", ""]
    for r in rows:
        front += ["### " + r["id"], "", r["task"], "", "Scientific conditions: " + (r["constraints"] or "Valid projected metre geometries; no repair or reprojection."),
                  "", "Exact entrypoint: `" + MODULE + ":" + r["function"] + "`.",
                  "", "Synthetic example: `" + json.dumps({"data_path": ASSET + "/" + r["function"] + ".json"}) + "`.",
                  "", "Independent numeric oracle: " + r["oracle"], "", "Distinctness: " + r["comparison"],
                  "", "Upstream: `" + r["upstream_callable"] + "`; [official API/source](" + DOCS[r["package"]] + ").", ""]
    front += ["## Outputs and interpretation", "", "Results are bounded JSON evidence with explicit `data`, `crs`, `source`, `units`, `artifacts` and `provenance` fields. "
              "These operations return numeric arrays and WKT directly; `artifacts` is empty. They do not certify mineral occurrence, resource estimates, "
              "site engineering safety, causation, or statistical significance. No output directory is required. "
              "Grid/path results include data.origin_xy, cell_size_m, shape and affine in Rasterio [a,b,c,d,e,f] order. "
              "The origin is an upper-left pixel corner; pixel centers add 0.5 to row/column. "
              "For reprojection, crs is the destination and source_crs is preserved separately.",
              "", "## Errors", "", "The shared `ScientificToolError` envelope contains `code`, `message`, and `retryable`. "
              "Schema, unit, CRS, topology and source failures are `invalid_arguments`; missing or incompatible pinned packages, "
              "resource limits, unreadable paths, empty data, unsupported connectivity and upstream failures have separate codes. "
              "Correct deterministic causes before retry. Do not conceal an error with substitute data.",
              "", "## Sources and reproducibility", "", "See the group `sources.json`, verbatim upstream notices in `licenses/`, and `requirements-spatial.txt`. "
              "The shared decorator records exact installed pins, canonical input-file content hashes, adapter/contract hashes, and the release commit. "
              "No runtime network or arbitrary user-selected callable is supported. Adapter license and receiving-lab approval remain pending.",
              "", "## Handoff and availability", "", "NOT TESTED / NOT DEPLOYED / NOT SUBMITTED.", "",
              "availability_status: tool_candidates_available_workflow_unverified", "",
              "workflow_validation: not_run; model_workflow_validation: not_run; platform_validation: not_run; "
              "deployment_status: not_deployed; submission_status: not_submitted; receiving_lab_approval: pending.", "",
              "Parent must merge the additive catalog/examples, register the fixed module and worker kind, run the authored CPU tests "
              "against the pinned environment, and record fresh acceptance evidence. Existing skill_find/skill_load remains unchanged.", ""]
    return record, path, "\n".join(front)


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    WRITTEN.append(path.relative_to(ROOT).as_posix())


def dump(path, value):
    write(path, json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + "\n")


def main():
    rows = records()
    tools = [make_tool(r) for r in rows]
    skills = []
    for i, (key, title) in enumerate([
        ("github-spatial-gis-conversion", "GIS conversion and site topology"),
        ("github-spatial-terrain-drainage", "Terrain conditioning and drainage diagnostics"),
        ("github-spatial-site-association", "Spatial association of site observations"),
        ("github-spatial-raster-access", "Raster access, corridors and throughput"),
        ("github-spatial-survey-layout", "Ellipsoidal survey and site layout"),
    ]):
        record, path, content = skill(key, title, rows[i*6:(i+1)*6])
        skills.append(record)
        target = ROOT / path
        write(target, content)
    dump(GROUP / "catalog-additions.json", {"tools": tools, "skills": skills})
    dump(GROUP / "examples-additions.json", {t["id"]: t["example_arguments"] for t in tools})
    dump(GROUP / "candidate-operations.json", {"group": "spatial", "operations": [
        {"tool_id": r["id"], "capability_key": "spatial:" + r["function"].replace("_", "-"),
         "upstream_callable": r["upstream_callable"], "scientific_task": r["task"],
         "distinct_from_existing": r["comparison"], "numeric_oracle": r["oracle"],
         "status": "source_authored_unverified"} for r in rows]})
    sources = []
    for package, (version, repo, tag, commit, license_name, license_path) in UPSTREAM.items():
        sources.append({"package": package, "version": version, "repository": "https://github.com/" + repo,
                        "release_tag": tag, "source_commit": commit, "commit_evidence": "https://api.github.com/repos/" + repo + "/commits/" + tag,
                        "source_url": "https://github.com/" + repo + "/tree/" + commit, "official_docs": DOCS[package],
                        "license": license_name, "license_url": "https://github.com/" + repo + "/blob/" + commit + "/" + license_path,
                        "license_evidence_file": "licenses/" + package + ".txt",
                        "research_status": "Official release ref and license fetched; APIs researched; runtime NOT TESTED"})
    dump(GROUP / "sources.json", {"group": "spatial", "status": "source_authored_unverified", "sources": sources,
                                  "dependency_pins": PINS, "network_required_at_runtime": False,
                                  "binary_runtime_gates": ["GEOS >=3.12 for coverage validation, constrained triangulation, maximum inscribed circle and ordered Voronoi"],
                                   "r2_backend_change": {"tool_id": "GeoSpatialStrahlerOrder", "from": "pysheds==0.5", "to": "pyflwdir==0.5.12",
                                                        "source_commit": UPSTREAM["pyflwdir"][3],
                                                        "kernel_source": "https://github.com/Deltares/pyflwdir/blob/" + UPSTREAM["pyflwdir"][3] + "/pyflwdir/streams.py#L229",
                                                        "terminal_encoding_source": "https://github.com/Deltares/pyflwdir/blob/" + UPSTREAM["pyflwdir"][3] + "/pyflwdir/core_d8.py#L43",
                                                        "local_algorithm_patch": False, "original_terminal_oracle": 2},
                                   "projection_oracle_sources": ["https://proj.org/en/stable/operations/projections/utm.html",
                                                                 "https://proj.org/en/stable/operations/projections/webmerc.html"],
                                   "confirmed_runtime_metadata": {"source": "Parent-reported private CPU environment; not locally inspected", "affine": "3.0.1", "GEOS": "3.13.1"},
                                   "transitive_lock_note": "affine==3.0.1 is explicitly pinned from parent-confirmed private CPU metadata; GEOS 3.13.1 satisfies the retained >=3.12 gate. Parent retains the remaining transitive lock, including llvmlite and binary hashes. No main-environment replacement or NumPy downgrade is authorized by this file.",
                                  "license_review": "Pysheds supplies GPLv3 text. Adapter licensing and combined-distribution approval remain with parent/receiving lab."})
    write(GROUP / "requirements-spatial.txt", "# Python 3.12; preserve deployed scientific pins; parent confirmed private pyflwdir and affine.\n# No installs or tests by this group. Parent reports GEOS 3.13.1; retain the >=3.12 gate.\n# Parent retains remaining exact transitive/binary lock, including llvmlite and binary hashes.\n" + "\n".join(PINS) + "\n")
    for r in rows:
        dump(ROOT / ASSET / (r["function"] + ".json"), r["fixture"])
    extras = supplementary_fixtures()
    for filename, value in extras.items():
        dump(ROOT / ASSET / filename, value)
    write(ROOT / ASSET / "README.md",
        "# Synthetic spatial fixtures\n\nAll 30 primary and three supplemental JSON inputs are explicitly synthetic analytic constructions. "
        "They are not geological observations, mineral evidence, training data or acceptance receipts. "
        "Projected examples use arbitrary metre coordinates in EPSG:32631 solely for deterministic numerical examples. "
        "No external data files, downloads, raster sidecars or generated binary fixtures are required.\n\n"
        "r2 retains the original Strahler terminal=2 fixture and the original shifted-raster NoData fixture. "
        "strahler_order_multi_221.json has incoming branch orders 2,2,1 and confluence/terminal order 3; "
        "strahler_order_multi_112.json has incoming 1,1,2 and confluence/terminal order 2. "
        "raster_reproject_cross_crs.json uses UTM31N (500000,0) and Web Mercator (6378137*pi/60,0), "
        "the same equatorial longitude 3-degree pixel center, with expected value 17. "
        "The cross-CRS fixture is not a same-CRS identity warp and its expected coordinate does not call PROJ.\n")
    write(GROUP / "HANDOFF.md",
        "# Spatial r2 source handoff\n\n30 source-authored candidates in five six-tool Skills. NOT TESTED / NOT DEPLOYED / NOT SUBMITTED.\n\n"
        "The generator writes only this spatial group, assets/github-expansion-spatial, and catalog/skills/github-spatial-*. "
        "It does not read or alter the 229-tool registry, shared examples, worker dispatch or source registry. "
        "The module has 30 explicit decorated named functions; no generic callable or command selector.\n\n"
        "Parent integration: merge catalog-additions.json and examples-additions.json additively, preserve original baseline entries, "
        "add fixed kind github_expansion_spatial and module geological_agent.geology.github_expansion_spatial to central dispatch, "
        "then execute tests_local/test_github_expansion_spatial.py in a private CPU environment. Tests patch catalog lookup locally "
        "so they can also run before the global merge; real dependencies and upstream functions are not mocked.\n\n"
        "The exact file model schemas are embedded under metadata.scientific_contract.data_schema. All schema objects set "
        "additionalProperties:false, including nested output/provenance objects. The shared operation decorator supplies "
        "dict/JSON argument transport, error envelopes, package checks and hashes. No output files are generated by runtime operations.\n\n"
        "Bounds: scientific files <=256 KiB; <=4096 raster cells; <=256 statistic observations; resistance dense solve <=256 cells; "
        "<=1024 polygon vertices; <=32768 contour vertices. Every input declares source, CRS and coordinate units. "
        "Invalid raster cells must be null and explicitly masked; hydro operations instead reject incomplete DEMs. "
        "Pysheds graph inputs have an explicit zero rim and interior terminal cells, avoiding silent upstream rim removal. "
        "Routing is acyclic; no flow accumulation or slope operation is registered.\n\n"
        "Outstanding: parent CPU/schema/negative-case acceptance, global distinctness review across all four groups, "
        "binary GEOS >=3.12 check, adapter license, GPLv3 distribution assessment for Pysheds, receiving-lab approval. "
        "The new backend pin is pyflwdir==0.5.12; affine==3.0.1 explicitly locks its parent-confirmed dependency. All previously supplied pins are retained, including "
        "numpy==2.1.3, numba==0.68.0 and scipy==1.15.3. No main-environment install or replacement is performed. "
        "PyFlwDir declares affine, numpy, scipy and numba>=0.54,<1.0, with Python>=3.11. "
        "Parent reports affine 3.0.1 and GEOS 3.13.1 in the private CPU environment; no local runtime inspection was performed. "
        "The parent retains remaining transitive versions, including llvmlite, and binary hashes in its full lock. "
        "Full transitive environment/wheel hashes remain parent-owned. No claim of 30 verified tools is made.\n\n"
        "r2 repairs: GeoSpatialStrahlerOrder calls the original PyFlwDir 0.5.12 public API at "
        "4e598e77611232bbf5fc620919d914de5bfd2cdb, with no local recurrence, artificial outlet, or new tributary-count restriction. "
        "Original terminal=2 remains unchanged; added independent [2,2,1]->3 and [1,1,2]->2 fixtures. "
        "Nine previously unlocated grid/path results now carry origin_xy, cell_size_m, Rasterio affine and shape; "
        "RasterReproject and PolygonRasterize receive the same complete grid contract. "
        "RasterReproject crs is the destination, source_crs preserves the source, and a UTM31N-to-EPSG3857 "
        "equatorial analytic fixture exercises an actual cross-CRS warp. All result objects remain closed.\n\n"
        "GEOS >=3.12 remains a runtime gate for CoverageUnion, ConstrainedTriangulation, MaximumInscribedCircle "
        "and SiteVoronoi; parent-reported GEOS 3.13.1 satisfies that minimum. Authored negative gate tests patch version metadata only, not scientific kernels.\n\n"
        "Historical r1 CPU evidence is preserved and not reclassified as passing: "
        "/data/wangjian/github-expansion120-20261025-r1/reports/remote-spatial-contracts.log. "
        "No r1 report, online registry, shared SDK, shared dispatch or other group is written by this generator.\n")
    authored = ["geological_agent/geology/github_expansion_spatial.py",
                "tests_local/test_github_expansion_spatial.py",
                "catalog/source_delivery/github-expansion-20261025/groups/spatial/build_contribution.py",
                "catalog/source_delivery/github-expansion-20261025/groups/spatial/licenses/pyflwdir.txt"]
    manifest_path = GROUP / "changed-paths.json"
    paths = authored + WRITTEN + [manifest_path.relative_to(ROOT).as_posix()]
    dump(manifest_path, {
        "group": "spatial", "revision": "r2", "tool_count": len(rows), "skill_count": len(skills),
        "synthetic_fixture_count": len(rows) + len(extras), "changed_path_count": len(paths),
        "path_semantics": "Authored or generated paths in this r2 delivery; unchanged-content regenerated fixtures are included.",
        "status": "source_authored_unverified", "tests": "NOT TESTED", "deployment": "NOT DEPLOYED",
        "submission": "NOT SUBMITTED", "changed_paths": [(ROOT / path).as_posix() for path in paths],
        "dependency_pins": PINS, "r1_report_preserved": "/data/wangjian/github-expansion120-20261025-r1/reports/remote-spatial-contracts.log",
        "unresolved": ["Parent private CPU/schema/numeric/negative acceptance",
                       "Parent additive merge, fixed dispatch and global >=101 net-new distinctness acceptance",
                       "Parent final CPU acceptance; reported GEOS 3.13.1 meets the retained >=3.12 runtime gate",
                       "Parent remaining transitive lock including llvmlite and binary hashes; affine==3.0.1 is explicitly pinned",
                       "Adapter licensing, Pysheds GPLv3 distribution review and receiving-lab approval"],
        "validation_claim": "30 source-authored candidates; r2 was not scientifically tested by this group.",
    })
    print("Authored spatial r2: 30 operations, five Skills, 33 synthetic fixtures, " + str(len(paths)) + " delivery paths. NOT TESTED / NOT DEPLOYED / NOT SUBMITTED.")


if __name__ == "__main__":
    main()

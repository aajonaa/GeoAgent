"""Bounded, fixed upstream spatial adapters. SOURCE ONLY: acceptance pending.

No installation, network service, subprocess, shared bridge or user-selected
callable. Package/native compatibility and receiving-lab approval are pending.
All imports of scientific dependencies are lazy. JSON results deliberately
produce no files; the shared decorator supplies hashes, artifacts and provenance.
"""
from __future__ import annotations

import math
import re
import struct
import warnings
from pathlib import Path

from .collection_contracts import operation, reject


@operation("GeoSpatialRigidPointCloudRegistration")
def rigid_point_cloud_registration(args, output_dir=None):
    from .expansion501_spatial_support.native import rigid_point_cloud_registration as implementation
    return _pending_resolution(implementation, args, output_dir)


@operation("GeoSpatialNavigationBasedLidarGeoreference")
def navigation_based_lidar_georeference(args, output_dir=None):
    from .expansion501_spatial_support.native import navigation_based_lidar_georeference as implementation
    return _pending_resolution(implementation, args, output_dir)


@operation("GeoSpatialSurveyPoissonSurface")
def survey_poisson_surface(args, output_dir=None):
    from .expansion501_spatial_support.native import survey_poisson_surface as implementation
    return _pending_resolution(implementation, args, output_dir)


@operation("GeoSpatialTerrainSolarIrradiance")
def terrain_solar_irradiance(args, output_dir=None):
    from .expansion501_spatial_support.native import terrain_solar_irradiance as implementation
    return _pending_resolution(implementation, args, output_dir)


def _pending_resolution(function, args, output_dir=None):
    """No shared dependency bypass: these definitions remain unregistered."""
    from .expansion501_spatial_support.common import ContractError
    try:
        return function(args) if output_dir is None else function(args, output_dir)
    except ContractError as exc:
        reject(str(exc), exc.code)


@operation("GeoTidalCycleFlow")
def tidal_cycle_flow(args):
    from .expansion501_spatial_support.landlab_state import tidal_cycle_flow as implementation
    return _pending_resolution(implementation, args)


@operation("GeoBedrockLandslideEvolution")
def bedrock_landslide_evolution(args):
    from .expansion501_spatial_support.landlab_state import bedrock_landslide_evolution as implementation
    return _pending_resolution(implementation, args)


@operation("GeoRiverSedimentParcelTransport")
def river_sediment_parcel_transport(args):
    from .expansion501_spatial_support.landlab_state import river_sediment_parcel_transport as implementation
    return _pending_resolution(implementation, args)


@operation("GeoSpatialPointCloudGroundClassification")
def point_cloud_ground_classification(args, output_dir=None):
    from .expansion501_spatial_support.native import ground_classification
    return _pending_resolution(ground_classification, args, output_dir)


@operation("GeoSpatialPointCloudHeightAboveGround")
def point_cloud_height_above_ground(args, output_dir=None):
    from .expansion501_spatial_support.native import height_above_ground
    return _pending_resolution(height_above_ground, args, output_dir)


@operation("GeoSpatialIndividualTreeSegmentation")
def individual_tree_segmentation(args, output_dir=None):
    from .expansion501_spatial_support.native import individual_tree_segmentation as implementation
    return _pending_resolution(implementation, args, output_dir)


@operation("GeoSpatialPointCloudMorphologyDescriptors")
def point_cloud_morphology_descriptors(args, output_dir=None):
    from .expansion501_spatial_support.native import morphology_descriptors
    return _pending_resolution(morphology_descriptors, args, output_dir)


@operation("GeoSpatialTerrainViewshed")
def terrain_viewshed(args, output_dir=None):
    from .expansion501_spatial_support.native import terrain_viewshed as implementation
    return _pending_resolution(implementation, args, output_dir)


@operation("GeoSpatialGeomorphonLandforms")
def geomorphon_landforms(args, output_dir=None):
    from .expansion501_spatial_support.native import geomorphon_landforms as implementation
    return _pending_resolution(implementation, args, output_dir)


@operation("GeoSpatialDemandWeightedFacilitySiting")
def demand_weighted_facility_siting(args, output_dir=None):
    from .expansion501_spatial_support.native import demand_weighted_facility_siting as implementation
    return _pending_resolution(implementation, args, output_dir)


@operation("GeoSpatialMinimumCoverageFacilitySet")
def minimum_coverage_facility_set(args, output_dir=None):
    from .expansion501_spatial_support.native import minimum_coverage_facility_set as implementation
    return _pending_resolution(implementation, args, output_dir)


def _np():
    import numpy as np
    return np


def _array(value, name, ndim=None, shape=None, lower=None, upper=None):
    np = _np()
    try:
        a = np.asarray(value, dtype=float)
    except (ValueError, TypeError):
        reject(name + " must be a rectangular numeric array")
    if (ndim is not None and a.ndim != ndim) or (shape is not None and a.shape != tuple(shape)):
        reject(name + " has an incompatible shape")
    if a.size == 0 or a.size > 16384:
        reject(name + " must have 1..16384 entries", "resource_limit")
    if not np.isfinite(a).all():
        reject(name + " contains non-finite data; NoData is not supported")
    if lower is not None and np.any(a < lower):
        reject(name + " is below its physical domain")
    if upper is not None and np.any(a > upper):
        reject(name + " is above its physical domain")
    return a


def _crs(value):
    from pyproj import CRS
    if not isinstance(value, str) or not re.fullmatch(r"EPSG:[1-9][0-9]{2,6}", value):
        reject("crs must be a projected EPSG identifier")
    c = CRS.from_user_input(value)
    axes = c.axis_info
    if not c.is_projected or len(axes) != 2:
        reject("a two-dimensional projected CRS is required")
    if [v.direction for v in axes] != ["east", "north"] or any(
        not math.isclose(v.unit_conversion_factor, 1.0, abs_tol=1e-12) for v in axes
    ):
        reject("CRS axes must be easting/northing in metres")
    return c.to_string()


def _grid(args, shape):
    _crs(args["crs"])
    if len(shape) != 2 or min(shape) < 1 or max(shape) > 64 or math.prod(shape) > 4096:
        reject("grid must be 1..64 by 1..64 and at most 4096 cells", "resource_limit")
    dx = args["cell_size_m"]
    if not math.isfinite(dx) or not 0 < dx <= 100000:
        reject("cell_size_m must be positive and at most 100000")
    x, y = args["origin_xy_m"]
    if not all(math.isfinite(v) and abs(v) <= 1e8 for v in (x, y)):
        reject("invalid upper-left outer-corner origin")
    return {
        "crs": args["crs"], "shape": list(shape),
        "origin_xy_m": [x, y], "cell_size_m": dx,
        "affine": [dx, 0.0, x, 0.0, -dx, y],
        "row_order": "north_to_south", "nodata": None,
    }


def _pack(method, units, **values):
    return {"method": method, "units": units, **values}


def _points(value, name, minimum=1):
    a = _array(value, name, ndim=2, lower=-1e8, upper=1e8)
    if a.shape[1] != 2 or not minimum <= a.shape[0] <= 512:
        reject(name + " must have " + str(minimum) + "..512 XY pairs")
    return a


def _unique(a, name):
    if len({tuple(row) for row in a.tolist()}) != len(a):
        reject(name + " contains duplicate points")


def _flow(args):
    np = _np()
    from affine import Affine
    import pyflwdir
    a = _array(args["d8"], "d8", ndim=2)
    meta = _grid(args, a.shape)
    if not np.isin(a, [0, 1, 2, 4, 8, 16, 32, 64, 128]).all():
        reject("D8 accepts terminal 0 and powers of two only, without NoData")
    offsets = {1:(0,1), 2:(1,1), 4:(1,0), 8:(1,-1), 16:(0,-1),
               32:(-1,-1), 64:(-1,0), 128:(-1,1)}
    downstream = list(range(a.size))
    rows, cols = a.shape
    for r in range(rows):
        for c in range(cols):
            code = int(a[r,c])
            if code:
                dr, dc = offsets[code]
                rr, cc = r + dr, c + dc
                if not (0 <= rr < rows and 0 <= cc < cols):
                    reject("out-of-grid D8 links are not implicit terminals")
                downstream[r*cols+c] = rr*cols+cc
    state = [0] * a.size
    for start in range(a.size):
        trail, cur = [], start
        while state[cur] == 0:
            state[cur] = 1
            trail.append(cur)
            nxt = downstream[cur]
            if nxt == cur:
                break
            cur = nxt
        else:
            if state[cur] == 1:
                reject("D8 contains a directed cycle")
        for idx in trail:
            state[idx] = 2
    f = pyflwdir.from_array(a.astype(np.uint8), ftype="d8",
                           transform=Affine(*meta["affine"]), latlon=False)
    return f, a, meta


@operation("GeoSpatialFlowNetworkUpscaleIHU")
def flow_network_upscale_ihu(args):
    f, a, meta = _flow(args)
    factor = args["scale_factor"]
    if any(n % factor for n in a.shape) or min(a.shape) // factor < 2:
        reject("grid dimensions must be divisible by scale_factor; coarse grid at least 2x2")
    coarse, outlets = f.upscale(factor, method="ihu")
    target_args = {**args, "cell_size_m": args["cell_size_m"] * factor}
    out = coarse.to_array(ftype="d8")
    if (outlets < 0).any() or (outlets >= a.size).any():
        reject("IHU returned an invalid high-resolution outlet", "upstream_failure")
    return _pack("pyflwdir.IHU", {"d8":"D8_code", "outlet_indices":"zero_based_source_row_major"},
                 grid=_grid(target_args, out.shape), source_grid=meta,
                 d8=out.tolist(), outlet_indices=outlets.tolist())


@operation("GeoSpatialFloodplainStageStorage")
def floodplain_stage_storage(args):
    np = _np()
    f, a, meta = _flow(args)
    hand = _array(args["hand_m"], "hand_m", shape=a.shape, lower=0)
    outlets = _array(args["outlet_indices"], "outlet_indices", ndim=1, lower=0, upper=a.size-1)
    if not np.equal(outlets, np.floor(outlets)).all() or len(set(outlets)) != outlets.size:
        reject("outlet indices must be unique integers")
    outlets = outlets.astype(np.int64)
    if np.any(hand.ravel()[outlets] != 0):
        reject("HAND must be zero at each supplied outlet")
    depths = _array(args["stages_m"], "stages_m", ndim=1, lower=0)
    if not np.all(np.diff(depths) > 0):
        reject("stages_m must be strictly increasing")
    labels, volumes = f.ucat_volume(outlets, hand, depths)
    if np.any(labels == 0) or np.any(volumes < 0):
        reject("outlets do not cover the full input grid or volumes are invalid")
    return _pack("pyflwdir.ucat_volume", {"stages_m":"m","volume_m3":"m3","catchment_labels":"upstream_unit_catchment_id"},
                 grid=meta, stages_m=depths.tolist(), outlet_indices=outlets.tolist(),
                 catchment_labels=labels.tolist(), volume_m3=volumes.tolist())


def _geometries(values, allowed):
    import shapely
    result = []
    count = 0
    for text in values:
        g = shapely.from_wkt(text)
        if g.is_empty or not g.is_valid or g.geom_type not in allowed or g.has_z or g.has_m:
            reject("geometry must be valid, nonempty, two-dimensional and of the declared type")
        coords = shapely.get_coordinates(g)
        _array(coords, "geometry coordinates", ndim=2, lower=-1e8, upper=1e8)
        count += len(coords)
        if count > 8192:
            reject("geometry vertex budget exceeded", "resource_limit")
        result.append(g)
    return result


@operation("GeoSpatialCoverageSimplification")
def coverage_simplification(args):
    import shapely
    _crs(args["crs"])
    if shapely.geos_version < (3, 12, 0):
        reject("coverage simplification requires GEOS >= 3.12", "incompatible_dependency")
    gs = _geometries(args["polygons_wkt"], {"Polygon", "MultiPolygon"})
    if not bool(shapely.coverage_is_valid(gs)):
        reject("input is not a valid nonoverlapping polygon coverage")
    out = shapely.coverage_simplify(gs, args["tolerance_m"], simplify_boundary=False)
    if not bool(shapely.coverage_is_valid(out)):
        reject("upstream simplified coverage is invalid", "upstream_failure")
    return _pack("shapely.coverage_simplify_internal_edges",
                 {"area_m2":"m2", "tolerance_m":"sqrt_triangle_area_m"},
                 crs=args["crs"], polygons_wkt=[g.wkt for g in out],
                 area_m2=[float(g.area) for g in out], tolerance_m=args["tolerance_m"],
                 geos_version=shapely.geos_version_string)


@operation("GeoSpatialConservativeArealTransfer")
def conservative_areal_transfer(args):
    np = _np()
    import geopandas as gpd
    import shapely
    from tobler.area_weighted import area_interpolate
    _crs(args["crs"])
    source = _geometries(args["source_wkt"], {"Polygon", "MultiPolygon"})
    target = _geometries(args["target_wkt"], {"Polygon", "MultiPolygon"})
    totals = _array(args["source_totals"], "source_totals", shape=(len(source),), lower=0)
    for polys in (source, target):
        if any(g.area <= 0 for g in polys):
            reject("zero-area polygon")
        for i, g in enumerate(polys):
            for h in polys[i+1:]:
                if g.intersection(h).area > 1e-10:
                    reject("source and target partitions may not overlap internally")
    su, tu = shapely.union_all(source), shapely.union_all(target)
    if su.symmetric_difference(tu).area > 1e-9 * max(1.0, su.area):
        reject("source and target must cover the same footprint; no implicit renormalization")
    sdf = gpd.GeoDataFrame({"total":totals}, geometry=source, crs=args["crs"])
    tdf = gpd.GeoDataFrame(geometry=target, crs=args["crs"])
    ans = area_interpolate(sdf, tdf, extensive_variables=["total"],
                           allocate_total=False, n_jobs=1)["total"].to_numpy()
    if not np.isfinite(ans).all() or not math.isclose(float(ans.sum()), float(totals.sum()), rel_tol=1e-8, abs_tol=1e-9):
        reject("areal-transfer mass balance failed", "upstream_failure")
    return _pack("tobler.area_interpolate_extensive", {"target_totals":args["quantity_unit"]},
                 crs=args["crs"], target_wkt=args["target_wkt"],
                 target_totals=ans.tolist(), source_total=float(totals.sum()),
                 target_total=float(ans.sum()))


def _modflow(args, require_hk=False):
    np = _np()
    import flopy
    top = _array(args["top_m"], "top_m", ndim=2, lower=-12000, upper=10000)
    bottom = _array(args["bottom_m"], "bottom_m", ndim=3, lower=-20000, upper=10000)
    if bottom.shape[1:] != top.shape or bottom.shape[0] > 16:
        reject("bottom_m must be layers x rows x columns, at most 16 layers")
    tops = np.concatenate([top[None,:,:], bottom[:-1]], axis=0)
    if np.any(tops <= bottom):
        reject("each layer must have positive thickness")
    meta = _grid(args, top.shape)
    # Construction only: no write_input(), run_model(), executable or subprocess.
    model = flopy.modflow.Modflow(modelname="bounded_spatial", model_ws=".")
    flopy.modflow.ModflowDis(model, nlay=bottom.shape[0], nrow=top.shape[0], ncol=top.shape[1],
                            delr=args["cell_size_m"], delc=args["cell_size_m"],
                            top=top, botm=bottom, lenuni=2, itmuni=1)
    flopy.modflow.ModflowBas(model, ibound=np.ones(bottom.shape, dtype=int), strt=tops)
    if require_hk:
        k = _array(args["conductivity_m_s"], "conductivity_m_s", shape=bottom.shape, lower=1e-15, upper=10)
        flopy.modflow.ModflowLpf(model, hk=k, laytyp=0)
    return model, top, bottom, meta


@operation("GeoSpatialDarcySpecificDischarge")
def darcy_specific_discharge(args):
    from flopy.utils.postprocessing import get_specific_discharge
    model, top, bottom, meta = _modflow(args)
    nl, nr, nc = bottom.shape
    qx = _array(args["east_face_flux_m3_s"], "east_face_flux_m3_s", shape=(nl,nr,nc+1))
    qy = _array(args["north_face_flux_m3_s"], "north_face_flux_m3_s", shape=(nl,nr+1,nc))
    qz = _array(args["up_face_flux_m3_s"], "up_face_flux_m3_s", shape=(nl+1,nr,nc))
    x, y, z = get_specific_discharge((qx,qy,qz), model, head=None, position="faces")
    return _pack("flopy.get_specific_discharge_faces",
                 {"qx_m_s":"m/s_east", "qy_m_s":"m/s_north", "qz_m_s":"m/s_up"},
                 grid=meta, top_m=top.tolist(), bottom_m=bottom.tolist(),
                 qx_m_s=x.tolist(), qy_m_s=y.tolist(), qz_m_s=z.tolist(),
                 sampling="x_y_z_faces_not_cell_centres", saturation="fully_saturated_active_cells")


@operation("GeoSpatialScreenedTransmissivity")
def screened_transmissivity(args):
    np = _np()
    from flopy.utils.postprocessing import get_transmissivities
    model, top, bottom, meta = _modflow(args, require_hk=True)
    loc = _array(args["well_row_col"], "well_row_col", ndim=2, lower=0)
    if loc.shape[1] != 2 or not np.equal(loc, np.floor(loc)).all():
        reject("well_row_col must be integer row-column pairs")
    r, c = loc.astype(int).T
    if np.any(r >= top.shape[0]) or np.any(c >= top.shape[1]):
        reject("well lies outside model")
    heads = _array(args["heads_m"], "heads_m", shape=bottom.shape)
    if np.any(heads <= bottom):
        reject("dry layers are not supported; supply heads above every layer bottom")
    st = _array(args["screen_top_m"], "screen_top_m", shape=(len(r),))
    sb = _array(args["screen_bottom_m"], "screen_bottom_m", shape=(len(r),))
    if np.any(st <= sb) or np.any(st > top[r,c]) or np.any(sb < bottom[-1,r,c]):
        reject("screens must lie entirely inside the model and have positive length")
    if np.any(sb >= np.max(heads[:,r,c], axis=0)):
        reject("screen must intersect saturated material")
    out = get_transmissivities(heads, model, r=r, c=c, sctop=st, scbot=sb)
    if np.any(out < 0):
        reject("negative transmissivity returned", "upstream_failure")
    return _pack("flopy.get_transmissivities", {"layer_transmissivity_m2_s":"m2/s"},
                 grid=meta, well_row_col=loc.astype(int).tolist(),
                 layer_transmissivity_m2_s=out.tolist(), total_transmissivity_m2_s=out.sum(axis=0).tolist())


def _cbc_path_and_header(args, zones):
    np = _np()
    raw = Path(args["budget_path"])
    if raw.is_absolute() or ".." in raw.parts:
        reject("budget_path must be workspace-relative", "invalid_path")
    root = Path.cwd().resolve()
    path = root / raw
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            reject("symlink budget paths are not allowed", "invalid_path")
    path = path.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        reject("budget input is missing or outside workspace", "invalid_path")
    if not 36 <= path.stat().st_size <= 2 * 1024 * 1024:
        reject("CBC file must be at most 2 MiB", "resource_limit")
    allowed = {"FLOW RIGHT FACE","FLOW FRONT FACE","FLOW LOWER FACE","STORAGE","WELLS","CONSTANT HEAD"}
    seen, names, count = set(), set(), 0
    with path.open("rb") as stream:
        while True:
            header = stream.read(36)
            if not header:
                break
            if len(header) != 36:
                reject("truncated classic CBC header")
            step, period, text, nc, nr, nl = struct.unpack("<ii16siii", header)
            name = text.decode("ascii", errors="strict").strip()
            if (nl,nr,nc) != zones.shape or step < 1 or period < 1 or name not in allowed:
                reject("only bounded little-endian single-precision classic full-array CBC records are supported")
            key = (step,period,name)
            if key in seen:
                reject("duplicate CBC term/time record")
            seen.add(key)
            if (step-1,period-1) == tuple(args["time_step_period"]):
                names.add(name)
            payload = stream.read(zones.size*4)
            if len(payload) != zones.size*4 or not np.isfinite(np.frombuffer(payload,dtype="<f4")).all():
                reject("truncated or non-finite CBC payload")
            count += 1
            if count > 128:
                reject("CBC record budget exceeded", "resource_limit")
    if not {"FLOW RIGHT FACE","FLOW FRONT FACE","FLOW LOWER FACE"}.issubset(names):
        reject("selected timestep requires all three intercell flow records")
    return path


@operation("GeoSpatialGroundwaterZoneBudget")
def groundwater_zone_budget(args):
    np = _np()
    from flopy.utils import CellBudgetFile, ZoneBudget
    z = _array(args["zones"], "zones", ndim=3, lower=1, upper=32)
    if not np.equal(z,np.floor(z)).all() or z.shape[0] > 16 or z.size > 4096:
        reject("zones must be integer 1..32 with at most 16 layers and 4096 cells")
    meta = _grid(args, z.shape[1:])
    path = _cbc_path_and_header(args,z)
    cbc = CellBudgetFile(str(path), precision="single")
    try:
        budget = ZoneBudget(cbc,z.astype(np.int32),kstpkper=tuple(args["time_step_period"]))
        table = budget.get_budget()
        labels = sorted(int(v) for v in np.unique(z))
        rows = []
        for record in table:
            term = str(record["name"])
            rows.append({"term":term,"values":[float(record["ZONE_"+str(v)]) for v in labels],
                         "unit":"percent" if term == "PERCENT_DISCREPANCY" else "m3/s"})
        if len(rows) > 128:
            reject("zone budget output exceeds term bound", "resource_limit")
    finally:
        cbc.close()
    return _pack("flopy.ZoneBudget", {"flow_terms":"m3/s","PERCENT_DISCREPANCY":"percent"},
                 grid=meta, zone_ids=labels, time_step_period=args["time_step_period"], terms=rows)


@operation("GeoSpatialRPCGeolocation")
def rpc_geolocation(args):
    np = _np()
    from rasterio.rpc import RPC
    from rasterio.transform import RPCTransformer
    rpc = args["rpc"]
    rows = _array(args["rows"], "rows", ndim=1, lower=0, upper=args["image_shape"][0]-1)
    cols = _array(args["cols"], "cols", shape=rows.shape, lower=0, upper=args["image_shape"][1]-1)
    heights = _array(args["height_m"], "height_m", shape=rows.shape)
    if np.any(np.abs(heights-rpc["height_off"]) > rpc["height_scale"]):
        reject("query height outside calibrated RPC normalization range")
    for name in ("line_den_coeff","samp_den_coeff"):
        if not any(rpc[name]):
            reject("RPC denominator polynomial cannot be identically zero")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with RPCTransformer(RPC(**rpc), RPC_PIXEL_ERROR_THRESHOLD=1e-6) as transform:
            lon,lat = transform.xy(rows,cols,zs=heights,offset="center")
        if caught:
            reject("RPC transform produced warnings; inverse may not have converged", "upstream_failure")
    xy = _points(list(zip(lon,lat)), "RPC coordinates")
    if np.any(np.abs(xy[:,0]) > 180) or np.any(np.abs(xy[:,1]) > 90):
        reject("RPC output outside geographic domain", "upstream_failure")
    offsets = np.array([rpc["long_off"],rpc["lat_off"]],dtype=float)
    scales = np.array([rpc["long_scale"],rpc["lat_scale"]],dtype=float)
    excess = np.abs(xy-offsets)-scales
    outside = np.any(excess > 0,axis=1)
    if np.any(outside):
        # This ULP budget only permits another upstream inverse solve. It is
        # never an acceptance tolerance or an expansion of the calibration box.
        # The retained linear-camera fixture overshoots by about 496 ULPs on
        # GDAL's initial inverse; a 1024-ULP retry gate bounds this special case.
        retry_budget = 1024.0*np.spacing(np.maximum(np.abs(offsets),scales))
        if np.any(excess[outside] > retry_budget):
            reject("RPC output outside calibration envelope", "upstream_failure")
        for index in np.flatnonzero(outside):
            target = np.array([rows[index]+0.5,cols[index]+0.5],dtype=float)
            # Use GDAL again, rather than clipping or implementing another RPC
            # inverse. Four pixel-coordinate ULPs force a refinement of the
            # observed residual while retaining the original forward tolerance.
            refined_threshold = float(4.0*np.max(np.spacing(np.maximum(1.0,np.abs(target)))))
            with warnings.catch_warnings(record=True) as refined_warnings:
                warnings.simplefilter("always")
                with RPCTransformer(RPC(**rpc), RPC_PIXEL_ERROR_THRESHOLD=refined_threshold) as transform:
                    refined_lon,refined_lat = transform.xy(
                        [float(rows[index])],[float(cols[index])],
                        zs=[float(heights[index])],offset="center")
                    refined_xy = _points(list(zip(refined_lon,refined_lat)), "refined RPC coordinates")
                    if np.any(np.abs(refined_xy-offsets) > scales):
                        reject("Refined RPC output outside calibration envelope", "upstream_failure")
                    if np.any(np.abs(refined_xy[:,0]) > 180) or np.any(np.abs(refined_xy[:,1]) > 90):
                        reject("Refined RPC output outside geographic domain", "upstream_failure")
                    forward_rows,forward_cols = transform.rowcol(
                        refined_lon,refined_lat,zs=[float(heights[index])],op=lambda value:value)
                    forward = np.array([forward_rows[0],forward_cols[0]],dtype=float)
                    if not np.isfinite(forward).all() or np.any(np.abs(forward-target) > 1e-6):
                        reject("Refined RPC forward residual exceeds inverse tolerance", "upstream_failure")
                if refined_warnings:
                    reject("Refined RPC transform produced warnings", "upstream_failure")
            xy[index] = refined_xy[0]
        if np.any(np.abs(xy-offsets) > scales):
            reject("RPC output outside calibration envelope", "upstream_failure")
    return _pack("rasterio.RPCTransformer.xy", {"lon_lat":"degree","height_m":"m_ellipsoid_WGS84"},
                 crs="EPSG:4326", source_crs="image_row_col", lon_lat=xy.tolist(),
                 height_m=heights.tolist(), pixel_reference="centre_zero_based")


@operation("GeoSpatialGCPGeoreferencing")
def gcp_georeferencing(args):
    np = _np()
    from rasterio.control import GroundControlPoint
    from rasterio.transform import GCPTransformer
    from shapely import MultiPoint, Point
    _crs(args["crs"])
    controls = _array(args["control_row_col_xy"], "control_row_col_xy", ndim=2)
    if controls.shape[1] != 4 or controls.shape[0] < 4:
        reject("at least four row,col,x,y controls are required")
    rc, xy = controls[:,:2], controls[:,2:]
    _unique(rc,"GCP pixels")
    _unique(xy,"GCP ground coordinates")
    if np.linalg.matrix_rank(np.column_stack([rc,np.ones(len(rc))])) < 3:
        reject("pixel controls are collinear")
    if np.linalg.matrix_rank(np.column_stack([xy,np.ones(len(xy))])) < 3:
        reject("ground controls are collinear")
    queries = _points(args["query_row_col"], "query_row_col")
    hull = MultiPoint(rc).convex_hull
    if not all(hull.covers(Point(p)) for p in queries):
        reject("TPS extrapolation outside pixel-control convex hull is not supported")
    gcps = [GroundControlPoint(row=float(r),col=float(c),x=float(x),y=float(y),z=0) for r,c,x,y in controls]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with GCPTransformer(gcps,tps=True) as transform:
            xs,ys = transform.xy(queries[:,0],queries[:,1],offset="ul")
        if caught:
            reject("GCP TPS transform warned", "upstream_failure")
    return _pack("rasterio.GCPTransformer_TPS.xy", {"xy_m":"m"}, crs=args["crs"],
                 source_crs="image_row_col", xy_m=_points(list(zip(xs,ys)),"transformed XY").tolist(),
                 pixel_reference="corner_zero_based")


def _weights(neighbors, n, connected=False):
    from libpysal.weights import W
    if len(neighbors) != n:
        reject("neighbor lists must match observation count")
    sets = [set(row) for row in neighbors]
    for i,row in enumerate(neighbors):
        if not row or len(sets[i]) != len(row) or i in sets[i]:
            reject("adjacency must have no islands, duplicate edges or self edges")
        for j in row:
            if j < 0 or j >= n or i not in sets[j]:
                reject("adjacency must be in-range and symmetric")
    if connected:
        todo, seen = [0], {0}
        while todo:
            for j in sets[todo.pop()]:
                if j not in seen:
                    seen.add(j); todo.append(j)
        if len(seen) != n:
            reject("adjacency must be connected")
    return W({i:sorted(row) for i,row in enumerate(sets)}, id_order=list(range(n)), silence_warnings=True)


@operation("GeoSpatialLocalHeteroscedasticity")
def local_heteroscedasticity(args):
    np = _np()
    from esda.losh import LOSH
    _crs(args["crs"])
    y = _array(args["values"], "values", ndim=1)
    if np.ptp(y) == 0:
        reject("LOSH is undefined for constant observations")
    w = _weights(args["neighbors"],len(y))
    ans = LOSH(connectivity=w,inference=None).fit(y,a=2)
    return _pack("esda.LOSH_a2_no_inference", {"Hi":"1","spatial_mean":args["value_unit"]},
                 crs=args["crs"], Hi=ans.Hi.tolist(), spatial_mean=ans.ylag.tolist(),
                 inference="not_requested")


@operation("GeoSpatialContiguousRegionalization")
def contiguous_regionalization(args):
    np = _np()
    import pandas as pd
    from spopt.region import Skater
    _crs(args["crs"])
    x = _array(args["attributes"], "attributes", ndim=2)
    if x.shape[1] > 8:
        reject("at most eight commensurate attributes are supported")
    w = _weights(args["neighbors"],len(x),connected=True)
    if args["regions"]*args["minimum_region_size"] > len(x):
        reject("requested region count and floor are infeasible")
    for i,row in enumerate(args["neighbors"]):
        if any(np.all(x[i] == x[j]) for j in row):
            reject("zero-dissimilarity graph edges are unsupported by sparse SKATER")
    names = ["x"+str(i) for i in range(x.shape[1])]
    model = Skater(pd.DataFrame(x,columns=names), w, names, n_clusters=args["regions"],
                   floor=args["minimum_region_size"], trace=False, islands="ignore")
    model.solve()
    labels = _canonical_labels(model.labels_)
    if len(set(labels)) != args["regions"]:
        reject("SKATER could not produce requested region count", "upstream_failure")
    for label in set(labels):
        members = {i for i,v in enumerate(labels) if v == label}
        if len(members) < args["minimum_region_size"]:
            reject("SKATER violated region size", "upstream_failure")
        seen, todo = {min(members)}, [min(members)]
        while todo:
            for j in args["neighbors"][todo.pop()]:
                if j in members and j not in seen:
                    seen.add(j); todo.append(j)
        if seen != members:
            reject("SKATER returned disconnected region", "upstream_failure")
    return _pack("spopt.SKATER_L1_heuristic", {"labels":"region_id"}, crs=args["crs"],
                 labels=labels, global_optimality="not_claimed")


@operation("GeoSpatialKnoxSpaceTimeInteraction")
def knox_space_time_interaction(args):
    from pointpats.spacetime import Knox
    _crs(args["crs"])
    xy = _points(args["points_xy_m"], "points_xy_m", minimum=3)
    t = _array(args["times_s"], "times_s", shape=(len(xy),))
    model = Knox(xy,t.reshape(-1,1),delta=args["distance_m"],tau=args["time_s"],
                 permutations=0,keep=False)
    return _pack("pointpats.Knox_observed_no_permutations",
                 {"space_time_pairs":"unordered_pair_count","observed":"pair_count","expected":"pair_count"},
                 crs=args["crs"], space_time_pairs=int(model.nst),
                 observed=model.observed.tolist(), expected=model.expected.tolist(),
                 inference="not_requested")


@operation("GeoSpatialRipleyKObservedWindow")
def ripley_k_observed_window(args):
    np = _np()
    from pointpats.distance_statistics import k
    _crs(args["crs"])
    xy = _points(args["points_xy_m"], "points_xy_m", minimum=3)
    _unique(xy,"events")
    if np.any(np.ptp(xy,axis=0) <= 0):
        reject("observed bounding rectangle must have positive area")
    support = _array(args["radii_m"], "radii_m", ndim=1, lower=1e-12)
    if not np.all(np.diff(support)>0):
        reject("radii must strictly increase")
    radii, values = k(xy,support=support,metric="euclidean",edge_correction=None)
    return _pack("pointpats.K_observed_bbox_uncorrected", {"radii_m":"m","K_m2":"m2"},
                 crs=args["crs"], radii_m=radii.tolist(), K_m2=values.tolist(),
                 bbox=[*xy.min(axis=0).tolist(),*xy.max(axis=0).tolist()],
                 edge_correction="none", window_policy="observed_bounding_box")


@operation("GeoSpatialRegionBoundarySilhouette")
def region_boundary_silhouette(args):
    np = _np()
    from esda.silhouettes import boundary_silhouette
    from sklearn.metrics.pairwise import euclidean_distances
    _crs(args["crs"])
    x = _array(args["attributes"], "attributes", ndim=2)
    labels = _array(args["labels"], "labels", shape=(len(x),), lower=0)
    if not np.equal(labels,np.floor(labels)).all() or not 2 <= len(set(labels)) < len(x):
        reject("require integer labels defining 2..n-1 regions")
    if any((labels == label).sum()<2 for label in set(labels)):
        reject("each region must have at least two members")
    w = _weights(args["neighbors"],len(x))
    # Upstream modifies numpy error mode; this context restores caller state.
    with np.errstate(all="raise"):
        result = boundary_silhouette(x,labels.astype(int),w,metric=euclidean_distances,drop_islands=True)
    return _pack("esda.boundary_silhouette", {"silhouette":"1"}, crs=args["crs"],
                 silhouette=_array(result,"silhouette",shape=(len(x),),lower=-1,upper=1).tolist(),
                 interior_policy="upstream_zero")


@operation("GeoSpatialLineworkPolygonTopology")
def linework_polygon_topology(args):
    import shapely
    _crs(args["crs"])
    lines = _geometries(args["lines_wkt"], {"LineString"})
    # Diagnostic extraction, not automatic noding, snapping or topology repair.
    polygons,cuts,dangles,invalid = shapely.polygonize_full(lines)
    parts = lambda g: [v.wkt for v in g.geoms]
    return _pack("shapely.polygonize_full", {"polygon_area_m2":"m2"}, crs=args["crs"],
                 polygons_wkt=parts(polygons), cut_edges_wkt=parts(cuts),
                 dangles_wkt=parts(dangles), invalid_rings_wkt=parts(invalid),
                 polygon_area_m2=[float(v.area) for v in polygons.geoms],
                 input_policy="already_noded_no_repair")


@operation("GeoSpatialChannelFrechetDeviation")
def channel_frechet_deviation(args):
    import shapely
    _crs(args["crs"])
    a,b = _geometries([args["reference_wkt"],args["survey_wkt"]],{"LineString"})
    value = float(shapely.frechet_distance(a,b))
    return _pack("shapely.discrete_frechet_distance", {"distance_m":"m"},
                 crs=args["crs"], distance_m=value, direction_policy="input_order_preserved",
                 sampling_policy="supplied_vertices_no_densification")


@operation("GeoSpatialEventKernelDensity")
def event_kernel_density(args):
    np = _np()
    from sklearn.neighbors import KernelDensity
    _crs(args["crs"])
    xy = _points(args["events_xy_m"],"events_xy_m")
    q = _points(args["query_xy_m"],"query_xy_m")
    model = KernelDensity(bandwidth=args["bandwidth_m"],algorithm="kd_tree",
                          kernel="gaussian",metric="euclidean",atol=0,rtol=0)
    logp = model.fit(xy).score_samples(q)
    return _pack("sklearn.KernelDensity_gaussian", {"density_m2_inverse":"1/m2","log_density":"ln(1/m2)"},
                 crs=args["crs"], query_xy_m=q.tolist(), density_m2_inverse=np.exp(logp).tolist(),
                 log_density=logp.tolist(), normalization="probability_not_event_intensity")


def _canonical_labels(values):
    mapping, out = {}, []
    for item in values:
        value = int(item)
        if value == -1:
            out.append(-1)
        else:
            if value not in mapping:
                mapping[value] = len(mapping)
            out.append(mapping[value])
    return out


@operation("GeoSpatialDensityConnectedSiteClusters")
def density_connected_site_clusters(args):
    from sklearn.cluster import DBSCAN
    _crs(args["crs"])
    xy = _points(args["points_xy_m"],"points_xy_m")
    _unique(xy,"sites")
    if args["minimum_samples"] > len(xy):
        reject("minimum_samples exceeds site count")
    labels = DBSCAN(eps=args["radius_m"],min_samples=args["minimum_samples"],
                    metric="euclidean",algorithm="kd_tree",n_jobs=1).fit_predict(xy)
    return _pack("sklearn.DBSCAN", {"labels":"cluster_id_minus_one_noise"},
                 crs=args["crs"], labels=_canonical_labels(labels),
                 border_tie_policy="input_order", noise_count=int((labels == -1).sum()))


def _land_grid(args, field_name):
    np = _np()
    from landlab import RasterModelGrid
    a = _array(args[field_name],field_name,ndim=2,lower=-20000,upper=1e8)
    meta = _grid(args,a.shape)
    if min(a.shape) < 3 or a.size > 1024:
        reject("Landlab grids require at least 3x3 and at most 1024 nodes", "resource_limit")
    x,y = args["origin_xy_m"]
    dx = args["cell_size_m"]
    g = RasterModelGrid(a.shape,xy_spacing=dx,
                        xy_of_lower_left=(x+dx/2,y-(a.shape[0]-.5)*dx))
    if args["boundary"] == "closed":
        g.set_closed_boundaries_at_grid_edges(True,True,True,True)
    elif args["boundary"] != "fixed_value":
        reject("unsupported boundary condition")
    return g,a,meta


def _add_node(g,name,array):
    np = _np()
    g.add_field(name,np.flipud(array).ravel().copy(),at="node")


def _node(g,name):
    np = _np()
    return np.flipud(g.at_node[name].reshape(g.shape)).tolist()


def _core_mask(g):
    np = _np()
    mask = np.zeros(g.number_of_nodes,dtype=bool)
    mask[g.core_nodes] = True
    return np.flipud(mask.reshape(g.shape)).tolist()


def _routing(g):
    from landlab.components import FlowAccumulator
    FlowAccumulator(g,flow_director="D8",runoff_rate=1.0).run_one_step()


@operation("GeoSpatialHillslopeDiffusionStep")
def hillslope_diffusion_step(args):
    from landlab.components import LinearDiffuser
    g,z,meta = _land_grid(args,"elevation_m")
    _add_node(g,"topographic__elevation",z)
    dt,k,dx = args["dt_s"],args["diffusivity_m2_s"],args["cell_size_m"]
    if dt*k/dx**2 > .2:
        reject("dt_s exceeds conservative explicit diffusion stability limit")
    LinearDiffuser(g,linear_diffusivity=k,method="simple",deposit=True).run_one_step(dt)
    return _pack("landlab.LinearDiffuser", {"elevation_m":"m","dt_s":"s"},
                 grid=meta,elevation_m=_node(g,"topographic__elevation"),
                 core_mask=_core_mask(g),boundary=args["boundary"],dt_s=dt)


@operation("GeoSpatialStreamPowerErosionStep")
def stream_power_erosion_step(args):
    np = _np()
    from landlab.components import FastscapeEroder
    g,z,meta = _land_grid(args,"elevation_m")
    _add_node(g,"topographic__elevation",z)
    _routing(g)
    FastscapeEroder(g,K_sp=args["erodibility_s_inverse"],m_sp=.5,n_sp=1,
                   threshold_sp=0,discharge_field="drainage_area",
                   erode_flooded_nodes=True).run_one_step(args["dt_s"])
    final = np.asarray(_node(g,"topographic__elevation"))
    if np.any(final > z+1e-8):
        reject("erosion-only step raised elevation", "upstream_failure")
    return _pack("landlab.FastscapeEroder_m0.5_n1", {"elevation_m":"m","erosion_m":"m","drainage_area_m2":"m2"},
                 grid=meta,elevation_m=final.tolist(),erosion_m=(z-final).tolist(),
                 drainage_area_m2=_node(g,"drainage_area"),core_mask=_core_mask(g),
                 boundary=args["boundary"],pit_policy="retain_no_fill")


@operation("GeoSpatialChannelChiCoordinate")
def channel_chi_coordinate(args):
    np = _np()
    from landlab.components import ChiFinder
    g,z,meta = _land_grid(args,"elevation_m")
    _add_node(g,"topographic__elevation",z)
    _routing(g)
    cf = ChiFinder(g,reference_concavity=.5,reference_area=args["reference_area_m2"],
                   min_drainage_area=args["minimum_area_m2"],use_true_dx=True)
    cf.calculate_chi()
    mask = np.flipud(cf.hillslope_mask.reshape(g.shape))
    vals = np.asarray(_node(g,"channel__chi_index"),dtype=object)
    vals[mask] = None
    return _pack("landlab.ChiFinder_true_link_length", {"chi_m":"m","drainage_area_m2":"m2"},
                 grid=meta,chi_m=vals.tolist(),channel_mask=(~mask).tolist(),
                 drainage_area_m2=_node(g,"drainage_area"),boundary=args["boundary"],
                 reference_concavity=.5,pit_policy="retain_no_fill")


@operation("GeoSpatialUnconfinedGroundwaterStep")
def unconfined_groundwater_step(args):
    np = _np()
    from landlab.components import GroundwaterDupuitPercolator
    g,top,meta = _land_grid(args,"elevation_m")
    base = _array(args["aquifer_base_m"],"aquifer_base_m",shape=top.shape)
    head = _array(args["water_table_m"],"water_table_m",shape=top.shape)
    if np.any(base >= head) or np.any(head >= top):
        reject("require aquifer_base < water_table < land_surface; no dry or flooded cells")
    k,n,r,dt,dx = (args[v] for v in ["conductivity_m_s","porosity","recharge_m_s","dt_s","cell_size_m"])
    if dt > .1*n*dx**2/(k*float((top-base).max())):
        reject("time step exceeds bounded diffusion safety criterion")
    gradients = max(float(np.abs(np.diff(head,axis=0)).max()),float(np.abs(np.diff(head,axis=1)).max()))/dx
    if dt * k * gradients / (n*dx) > .1 or dt*r/n > .1*float((top-head).min()):
        reject("step exceeds advection or recharge-to-surface safety criterion")
    _add_node(g,"topographic__elevation",top)
    _add_node(g,"aquifer_base__elevation",base)
    _add_node(g,"water_table__elevation",head)
    GroundwaterDupuitPercolator(g,hydraulic_conductivity=k,porosity=n,recharge_rate=r,
                                regularization_f=.01,courant_coefficient=.5,
                                vn_coefficient=.8).run_one_step(dt)
    final = np.asarray(_node(g,"water_table__elevation"))
    if np.any(final < base) or np.any(final > top):
        reject("water table left physical aquifer bounds", "upstream_failure")
    return _pack("landlab.GroundwaterDupuitPercolator_single_step",
                 {"water_table_m":"m","saturated_thickness_m":"m"},
                 grid=meta,water_table_m=final.tolist(),saturated_thickness_m=(final-base).tolist(),
                 core_mask=_core_mask(g),boundary=args["boundary"],dt_s=dt,
                 regularization_f=.01)


@operation("GeoSpatialOverlandFlowStep")
def overland_flow_step(args):
    np = _np()
    from landlab.components import OverlandFlow
    g,z,meta = _land_grid(args,"elevation_m")
    depth = _array(args["water_depth_m"],"water_depth_m",shape=z.shape,lower=1e-4,upper=100)
    dt,r,dx = args["dt_s"],args["rainfall_m_s"],args["cell_size_m"]
    if dt > .2*dx/math.sqrt(9.80665*(float(depth.max())+r*dt)):
        reject("step exceeds conservative shallow-water CFL bound")
    _add_node(g,"topographic__elevation",z)
    _add_node(g,"surface_water__depth",depth)
    component = OverlandFlow(g,h_init=0,alpha=.7,mannings_n=args["mannings_n"],
                            g=9.80665,theta=.8,rainfall_intensity=r,steep_slopes=False)
    component.run_one_step(dt)
    final = np.asarray(_node(g,"surface_water__depth"))
    if np.any(final <= 0):
        reject("step became dry; reduce timestep, no depth clipping is supplied", "upstream_failure")
    links = g.nodes_at_link
    # Return link end coordinates rather than confusing link flux with a cell raster.
    endpoints = [[[float(g.x_of_node[i]),float(g.y_of_node[i])] for i in pair] for pair in links]
    q = _array(g.at_link["surface_water__discharge"],"surface discharge")
    return _pack("landlab.OverlandFlow_deAlmeida",
                 {"water_depth_m":"m","link_discharge_m2_s":"m2/s_tail_to_head","link_endpoints_xy_m":"m"},
                 grid=meta,water_depth_m=final.tolist(),core_mask=_core_mask(g),
                 boundary=args["boundary"],dt_s=dt,
                 link_discharge_m2_s=q.tolist(),link_endpoints_xy_m=endpoints,
                 initial_discharge="zero_no_hidden_initial_water_layer")


@operation("GeoMarineCarbonateAccretion")
def marine_carbonate_accretion(args):
    np = _np()
    from landlab.components import CarbonateProducer
    g,z,meta = _land_grid(args,"elevation_m")
    sea = args["sea_level_m"]
    dt,rate = args["dt_years"],args["maximum_rate_m_year"]
    if np.any(z >= sea) or dt*rate >= float((sea-z).min()):
        reject("this fully submerged step must remain submerged; reduce dt or use a tidal/emergent model")
    _add_node(g,"topographic__elevation",z)
    g.at_grid["sea_level__elevation"] = sea
    comp = CarbonateProducer(g,max_carbonate_production_rate=rate,
                             extinction_coefficient=args["extinction_m_inverse"],
                             surface_light=args["surface_light"],
                             saturating_light=args["saturating_light"],tidal_range=0)
    comp.run_one_step(dt)
    out = np.asarray(_node(g,"topographic__elevation"))
    increment = out-z
    if np.any(increment < -1e-10) or np.any(increment > rate*dt+1e-10):
        reject("carbonate increment exceeds production bounds", "upstream_failure")
    return _pack("landlab.CarbonateProducer_fully_submerged",
                 {"elevation_m":"m","carbonate_added_m":"m","mean_production_m_year":"m/year","dt_years":"year"},
                 grid=meta,elevation_m=out.tolist(),carbonate_added_m=increment.tolist(),
                 mean_production_m_year=(increment/dt).tolist(),core_mask=_core_mask(g),
                 boundary=args["boundary"],dt_years=dt,tidal_range_m=0)


@operation("GeoRegolithProductionRate")
def regolith_production_rate(args):
    from landlab.components import ExponentialWeatherer
    g,h,meta = _land_grid(args,"soil_depth_m")
    if (h < 0).any():
        reject("soil depth must be nonnegative")
    _add_node(g,"soil__depth",h)
    ExponentialWeatherer(g,soil_production_maximum_rate=args["maximum_rate_m_year"],
                          soil_production_decay_depth=args["decay_depth_m"]).calc_soil_prod_rate()
    return _pack("landlab.ExponentialWeatherer", {"production_rate_m_year":"m/year"},
                 grid=meta,production_rate_m_year=_node(g,"soil_production__rate"),
                 core_mask=_core_mask(g),boundary=args["boundary"],
                 boundary_policy="rates_only_defined_at_core_nodes")


@operation("GeoLithosphereFlexure")
def lithosphere_flexure(args):
    from landlab.components import Flexure
    g,load,meta = _land_grid(args,"pressure_increment_pa")
    if load.size > 256:
        reject("flexure Green-function superposition is bounded to 256 nodes", "resource_limit")
    _add_node(g,"lithosphere__overlying_pressure_increment",load)
    comp = Flexure(g,eet=args["elastic_thickness_m"],youngs=args["youngs_modulus_pa"],
                   method="flexure",rho_mantle=args["mantle_density_kg_m3"],gravity=9.80665,n_procs=1)
    comp.update()
    return _pack("landlab.Flexure_elastic_plate", {"downward_deflection_m":"m_positive_down","alpha_m":"m"},
                 grid=meta,downward_deflection_m=_node(g,"lithosphere_surface__elevation_increment"),
                 alpha_m=float(comp.alpha),boundary="infinite_plate_zero_load_outside_sampled_grid",
                 sign_convention="positive_pressure_produces_positive_downward_deflection")


@operation("GeoSedimentTracerDiffusion")
def sediment_tracer_diffusion(args):
    np = _np()
    from landlab.components import DepthDependentDiffuser, ConcentrationTrackerForDiffusion
    g,z,meta = _land_grid(args,"elevation_m")
    h = _array(args["soil_depth_m"],"soil_depth_m",shape=z.shape,lower=1e-8)
    concentration = _array(args["concentration_kg_m3"],"concentration_kg_m3",shape=z.shape,lower=0)
    bedrock_conc = _array(args["bedrock_concentration_kg_m3"],"bedrock_concentration_kg_m3",shape=z.shape,lower=0)
    production = _array(args["production_m_year"],"production_m_year",shape=z.shape,lower=0)
    core = np.asarray(_core_mask(g))
    if np.any(production[~core] != 0):
        reject("closed guard nodes must have zero prescribed weathering production")
    dt,v,depth,dx = (args[k] for k in ["dt_years","transport_velocity_m_year","transport_decay_m","cell_size_m"])
    if dt*v*depth/dx**2 > .1:
        reject("diffusion step exceeds conservative stability bound")
    maxgrad = max(float(np.abs(np.diff(z,axis=0)).max()),float(np.abs(np.diff(z,axis=1)).max()))/dx
    maxout = 4*v*depth*maxgrad/dx
    if dt*maxout > .1*float(h.min()):
        reject("step may exhaust soil; clipping negative soil is not permitted")
    _add_node(g,"topographic__elevation",z)
    _add_node(g,"soil__depth",h)
    _add_node(g,"bedrock__elevation",z-h)
    _add_node(g,"soil_production__rate",production)
    diffuser = DepthDependentDiffuser(g,soil_transport_velocity=v,soil_transport_decay_depth=depth)
    tracker = ConcentrationTrackerForDiffusion(
        g,concentration_initial=np.flipud(concentration).ravel().copy(),
        concentration_in_bedrock=np.flipud(bedrock_conc).ravel().copy())
    oldmass = float((concentration*h)[core].sum()*dx**2)
    addedmass = float((bedrock_conc*production)[core].sum()*dt*dx**2)
    tracker.start_tracking()
    diffuser.run_one_step(dt)
    tracker.stop_tracking(dt)
    finalh = np.asarray(_node(g,"soil__depth"))
    finalc = np.asarray(_node(g,"sediment_property__concentration"))
    if np.any(finalh <= 0) or np.any(finalc < 0):
        reject("tracer step produced nonphysical concentration or soil depth", "upstream_failure")
    newmass = float((finalc*finalh)[core].sum()*dx**2)
    residual = newmass-oldmass-addedmass
    if abs(residual) > 1e-7*max(1.0,oldmass,addedmass):
        reject("closed-domain tracer mass balance failed", "upstream_failure")
    return _pack("landlab.ConcentrationTrackerForDiffusion_DepthDependentDiffuser",
                 {"elevation_m":"m","soil_depth_m":"m","concentration_kg_m3":"kg/m3",
                  "initial_mass_kg":"kg","final_mass_kg":"kg","weathering_input_kg":"kg","mass_residual_kg":"kg"},
                 grid=meta,elevation_m=_node(g,"topographic__elevation"),
                 soil_depth_m=finalh.tolist(),concentration_kg_m3=finalc.tolist(),
                 core_mask=core.tolist(),boundary=args["boundary"],
                 initial_mass_kg=oldmass,final_mass_kg=newmass,weathering_input_kg=addedmass,
                 mass_residual_kg=residual,sequence="start_tracking;diffuser.run_one_step;stop_tracking")


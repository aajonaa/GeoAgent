"""Fixed native kernels. No profile is shipped; no caller can choose a binary.

This is an INTERNAL private-worker runner, not the missing main/worker IPC.
It cannot run without an operator-reviewed native-profile.json installed next
to this source and containing the complete hashed native closure and receipt.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time

from .common import array, artifact, crs, fail, finish, grid_info, guard

EXPECTED_NATIVE = {"PDAL":"2.9.1", "GRASS":"8.5.0", "CBC":"2.10.12"}
PROFILE = Path(__file__).with_name("native-profile.json")


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda:stream.read(262144),b""):
            h.update(part)
    return h.hexdigest()


def binding(project):
    if os.name != "posix":
        fail("Fixed native workers require reviewed isolated POSIX CPU execution", "incompatible_dependency")
    if not PROFILE.is_file() or PROFILE.is_symlink():
        fail("Reviewed native profile and binary/license closure are not installed", "missing_dependency")
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    item = profile["projects"][project]
    if item["version"] != EXPECTED_NATIVE[project] or item["closure_complete"] is not True:
        fail("Unreviewed native release/closure", "incompatible_dependency")
    root = Path(item["root"])
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        fail("Invalid trusted native root", "invalid_path")
    root = root.resolve()
    files = item["files_sha256"]
    if item["executable"] not in files or item["build_receipt"] not in files:
        fail("Native binary and build receipt must both be hashed", "missing_dependency")
    for name, expected in files.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or len(expected) != 64:
            fail("Invalid native closure record", "invalid_path")
        path = root / relative
        if any(p.is_symlink() for p in [path,*path.parents] if p != root.parent):
            fail("Native closure contains a symlink", "invalid_path")
        if not path.is_file() or not path.resolve().is_relative_to(root) or sha(path) != expected:
            fail("Native closure hash mismatch", "incompatible_dependency")
    receipt = json.loads((root/item["build_receipt"]).read_text(encoding="utf-8"))
    if receipt.get("project") != project or receipt.get("version") != EXPECTED_NATIVE[project] or receipt.get("license_review_complete") is not True:
        fail("Missing reviewed native license/build receipt", "missing_dependency")
    return root/item["executable"], files[item["executable"]]


def _limits():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU,(120,120))
    resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE,(64*1024**2,64*1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))


def _run(binary, fixed_tail, work):
    env = {"PATH":str(binary.parent)+":/usr/bin:/bin", "LANG":"C", "LC_ALL":"C",
           "HOME":str(work), "TMPDIR":str(work), "XDG_CACHE_HOME":str(work),
           "MPLCONFIGDIR":str(work),"NUMBA_CACHE_DIR":str(work),
           "CUDA_VISIBLE_DEVICES":"", "NVIDIA_VISIBLE_DEVICES":"none",
           "ROCR_VISIBLE_DEVICES":"", "HIP_VISIBLE_DEVICES":"", "ONEAPI_DEVICE_SELECTOR":"*:cpu",
           "OMP_NUM_THREADS":"1", "OPENBLAS_NUM_THREADS":"1", "MKL_NUM_THREADS":"1",
           "NUMEXPR_NUM_THREADS":"1", "LANGCHAIN_TRACING_V2":"false","LANGSMITH_TRACING":"false",
           "PYTHONNOUSERSITE":"1", "PYTHONDONTWRITEBYTECODE":"1"}
    # argv is built only by fixed functions below; no user command/pipeline API.
    p = subprocess.Popen([str(binary),*fixed_tail],cwd=work,env=env,stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,shell=False,start_new_session=True,preexec_fn=_limits)
    sel = selectors.DefaultSelector()
    buffers = {"stdout":bytearray(),"stderr":bytearray()}
    for stream,label in ((p.stdout,"stdout"),(p.stderr,"stderr")):
        os.set_blocking(stream.fileno(),False); sel.register(stream,selectors.EVENT_READ,label)
    deadline = time.monotonic()+150
    try:
        while sel.get_map() or p.poll() is None:
            if time.monotonic() > deadline:
                fail("Native wall-clock budget exceeded", "resource_limit")
            for key,_ in sel.select(.05):
                block = os.read(key.fileobj.fileno(),8192)
                if not block:
                    sel.unregister(key.fileobj); continue
                buffers[key.data].extend(block)
                if len(buffers[key.data]) > 262144:
                    fail("Native stdout/stderr budget exceeded", "resource_limit")
            files = [q for q in work.rglob("*") if q.is_file()]
            if len(files) > 1024 or sum(q.stat().st_size for q in files) > 128*1024**2:
                fail("Native workspace artifact budget exceeded", "resource_limit")
        if p.wait() != 0:
            fail("Native exit status " + str(p.returncode) + ": " + bytes(buffers["stderr"])[-2048:].decode("utf-8","replace"), "upstream_failure")
        return bytes(buffers["stdout"]),bytes(buffers["stderr"])
    finally:
        if p.poll() is None:
            os.killpg(p.pid,signal.SIGKILL)
        p.wait(); sel.close(); p.stdout.close(); p.stderr.close()


def _csv(columns,rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream,lineterminator="\n")
    writer.writerow(columns); writer.writerows(rows)
    return stream.getvalue().encode("ascii")


def _cloud(args, extras):
    import numpy as np
    crs(args["crs"])
    points = array(args["points_xyz_m"])
    if points.ndim != 2 or points.shape[1] != 3 or not 4 <= len(points) <= 4096:
        fail("Expected 4..4096 XYZ points")
    if len({tuple(v) for v in points.tolist()}) != len(points):
        fail("Duplicate XYZ observations are outside this interface")
    columns = ["X","Y","Z","PointId"]+[dimension for _,dimension in extras]
    fields = [array(args[field],shape=(len(points),)) for field,_ in extras]
    rows = [[*point,i,*[float(v[i]) for v in fields]] for i,point in enumerate(points.tolist())]
    return points,columns,rows


def _pdal_column_units(fields):
    """Fixed per-column units; mixed native dimensions never share a unit."""
    known = {"X":"m", "Y":"m", "Z":"m", "PointId":"input_zero_based",
             "Classification":"dimensionless_label", "ClusterID":"dimensionless_label",
             "HeightAboveGround":"m", "Linearity":"dimensionless",
             "Planarity":"dimensionless", "Scattering":"dimensionless",
             "Verticality":"dimensionless"}
    if any(field not in known for field in fields):
        fail("Native output column has no reviewed unit", "invalid_result")
    return {field:known[field] for field in fields}


def _pdal_result(tool,args,stages,extra_inputs,output_fields,output_dir):
    import numpy as np
    points,columns,rows = _cloud(args,extra_inputs)
    binary,digest = binding("PDAL")
    with tempfile.TemporaryDirectory(prefix="spatial-pdal-") as temp:
        work = Path(temp)
        (work/"input.csv").write_bytes(_csv(columns,rows))
        fields = ["X","Y","Z","PointId",*output_fields]
        pipeline = [{"type":"readers.text","filename":str(work/"input.csv"),"separator":","},*stages,
                    {"type":"writers.text","filename":str(work/"result.csv"),"format":"csv","precision":17,
                     "order":",".join(fields),"keep_unspecified":False,"write_header":True}]
        (work/"pipeline.json").write_text(json.dumps(pipeline),encoding="utf-8")
        _run(binary,["pipeline",str(work/"pipeline.json"),"--metadata",str(work/"metadata.json")],work)
        output = work/"result.csv"
        if output.is_symlink() or not output.is_file() or output.stat().st_size > 8*1024**2:
            fail("Missing/oversized native cloud output", "invalid_result")
        parsed = list(csv.DictReader(io.StringIO(output.read_text(encoding="utf-8"))))
        if len(parsed) != len(points) or not parsed or set(parsed[0]) != set(fields):
            fail("Native cloud cardinality/dimensions changed", "invalid_result")
        data = [[float(row[f]) for f in fields] for row in parsed]
        values = array(data)
        ids = values[:,3]
        if set(ids.tolist()) != set(range(len(points))):
            fail("Native filter dropped/duplicated point identities", "invalid_result")
        values = values[np.argsort(ids)]
        if not np.array_equal(values[:,:3],points):
            fail("Filter unexpectedly changed source XYZ", "invalid_result")
        emitted = _csv(fields,values.tolist())
        manifest = [artifact(output_dir,"points.csv",emitted,"text/csv")]
        frame = dict(crs=args["crs"],horizontal_unit="m",vertical_unit="m",nodata=None,point_count=len(points))
        manifest.append(artifact(output_dir,"frame.json",json.dumps(frame).encode(),"application/json"))
        return finish(tool,dict(method=stages[-1]["type"],crs=args["crs"],columns=fields,rows=values.tolist(),
                 artifact_manifest=manifest,native_version="2.9.1",native_binary_sha256=digest,
                 units=_pdal_column_units(fields)))


def ground_classification(args,output_dir):
    tool="GeoSpatialPointCloudGroundClassification"; guard(tool,args)
    import numpy as np
    points,_,_ = _cloud(args,[])
    extent = np.ptp(points[:,:2],axis=0)/args["cell_m"]
    if np.prod(np.ceil(extent)+2) > 262144:
        fail("SMRF raster budget exceeded", "resource_limit")
    stage={"type":"filters.smrf","cell":args["cell_m"],"slope":args["slope"],
           "threshold":args["threshold_m"],"window":args["window_m"],"scalar":1.25,
           "returns":"first,last,intermediate,only","cut":0.0}
    return _pdal_result(tool,args,[stage],[],["Classification"],output_dir)


def height_above_ground(args,output_dir):
    tool="GeoSpatialPointCloudHeightAboveGround"; guard(tool,args)
    import numpy as np
    from scipy.spatial import ConvexHull
    points,_,_ = _cloud(args,[("classification","Classification")])
    classified = array(args["classification"],shape=(len(points),))
    ground = points[classified==2,:2]
    if len(ground) < max(3,args["neighbors"]) or np.linalg.matrix_rank(ground-ground[0]) != 2:
        fail("Ground support must span a 2D footprint")
    hull = ConvexHull(ground)
    other = points[classified!=2,:2]
    if len(other) and np.any(other@hull.equations[:,:2].T+hull.equations[:,2] > 0):
        fail("Non-ground points must lie in the original ground convex hull; no zero-fill extrapolation")
    stage={"type":"filters.hag_nn","count":args["neighbors"],"allow_extrapolation":False}
    return _pdal_result(tool,args,[stage],[("classification","Classification")],["Classification","HeightAboveGround"],output_dir)


def individual_tree_segmentation(args,output_dir):
    tool="GeoSpatialIndividualTreeSegmentation"; guard(tool,args)
    return _pdal_result(tool,args,[{"type":"filters.sort","dimension":"HeightAboveGround","order":"DESC"},
         {"type":"filters.litree","min_points":args["minimum_points"],"min_height":args["minimum_height_m"],"radius":args["radius_m"]}],
         [("height_above_ground_m","HeightAboveGround")],["HeightAboveGround","ClusterID"],output_dir)


def morphology_descriptors(args,output_dir):
    tool="GeoSpatialPointCloudMorphologyDescriptors"; guard(tool,args)
    if args["neighbors"] >= len(args["points_xyz_m"]):
        fail("Neighbor count must be smaller than point count")
    return _pdal_result(tool,args,[{"type":"filters.covariancefeatures","feature_set":"Dimensionality",
         "knn":args["neighbors"],"threads":1,"mode":"Raw","stride":1,"optimized":False}],[],
         ["Linearity","Planarity","Scattering","Verticality"],output_dir)


def _ascii(args,values):
    rows,cols=len(values),len(values[0]); x,y=args["origin_xy_m"]; d=args["cell_size_m"]
    header=f"north: {y:.17g}\nsouth: {y-rows*d:.17g}\neast: {x+cols*d:.17g}\nwest: {x:.17g}\nrows: {rows}\ncols: {cols}\n"
    return (header+"\n".join(" ".join(format(v,".17g") for v in row) for row in values)+"\n").encode("ascii")


def _grass_result(tool,args,output_dir):
    values=array(args["elevation_m"]); meta=grid_info(args,values.shape)
    binary,digest=binding("GRASS")
    worker=Path(__file__).with_name("grass_task.py")
    with tempfile.TemporaryDirectory(prefix="spatial-grass-") as temp:
        work=Path(temp)
        (work/"input.asc").write_bytes(_ascii(args,values.tolist()))
        (work/"request.json").write_text(json.dumps({"tool":tool,"args":args}),encoding="utf-8")
        _run(binary,["--tmp-project",args["crs"],"--exec",sys.executable,str(worker),str(work)],work)
        output=work/"result.asc"
        if output.is_symlink() or not output.is_file() or output.stat().st_size > 2*1024**2:
            fail("Invalid native raster output", "invalid_result")
        content=output.read_bytes(); lines=content.decode("ascii").splitlines()
        header={k.strip():float(v) for k,v in (line.split(":",1) for line in lines[:6])}
        expected={k.strip():float(v) for k,v in (line.split(":",1) for line in _ascii(args,values.tolist()).decode().splitlines()[:6])}
        if header != expected:
            fail("GRASS changed extent/shape; implicit resampling forbidden", "invalid_result")
        tokens=" ".join(lines[6:]).split()
        if len(tokens) != values.size:
            fail("GRASS raster shape changed", "invalid_result")
        numbers=[None if t=="*" else float(t) for t in tokens]
        valid=set(range(1,11)) if tool=="GeoSpatialGeomorphonLandforms" else {0,1}
        if any(v is not None and v not in valid for v in numbers):
            fail("Unexpected native raster category", "invalid_result")
        raster_values=[numbers[i:i+values.shape[1]] for i in range(0,len(numbers),values.shape[1])]
        manifest=[artifact(output_dir,"result.asc",content,"text/x-grass-ascii-grid")]
        sidecar={**meta,"nodata":"*","edge_policy":"native_truncated_neighborhood"}
        manifest.append(artifact(output_dir,"frame.json",json.dumps(sidecar).encode(),"application/json"))
        return finish(tool,dict(method="r.geomorphon" if len(valid)==10 else "r.viewshed_boolean",
                    grid=sidecar,values=raster_values,artifact_manifest=manifest,native_version="8.5.0",
                    native_binary_sha256=digest,units={"elevation":"m","result":"categorical"}))


def terrain_viewshed(args,output_dir):
    tool="GeoSpatialTerrainViewshed"; guard(tool,args)
    shape=array(args["elevation_m"]).shape
    r,c=args["observer_cell"]
    if r>=shape[0] or c>=shape[1]:
        fail("Observer cell outside raster")
    return _grass_result(tool,args,output_dir)


def geomorphon_landforms(args,output_dir):
    tool="GeoSpatialGeomorphonLandforms"; guard(tool,args)
    if args["skip_cells"] >= args["search_cells"]:
        fail("skip_cells must be smaller than search_cells")
    return _grass_result(tool,args,output_dir)


def _native_bytes(path, maximum):
    if not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
        fail("Expected an ordinary single-link native artifact", "invalid_result")
    if path.stat().st_size > maximum:
        fail("Native artifact exceeds its byte budget", "resource_limit")
    return path.read_bytes()


def _ordered_point_rows(blob, fields, count):
    """Check an owned CSV artifact and restore original point identities."""
    reader = csv.DictReader(io.StringIO(blob.decode("ascii")))
    if reader.fieldnames != fields:
        fail("Native point columns changed", "invalid_result")
    output = []
    for row in reader:
        if set(row) != set(fields) or any(value is None for value in row.values()):
            fail("Native point record shape changed", "invalid_result")
        values = [float(row[field]) for field in fields]
        if not all(math.isfinite(value) for value in values):
            fail("Non-finite native point output", "invalid_result")
        output.append(values)
        if len(output) > count:
            fail("Native point count increased", "invalid_result")
    index = fields.index("PointId")
    if len(output) != count or {row[index] for row in output} != set(range(count)):
        fail("Native point identities were lost or duplicated", "invalid_result")
    return sorted(output, key=lambda row:row[index])


def _pdal_execute(work, pipeline):
    # Internal helper only: every caller below constructs a literal stage list.
    binary, digest = binding("PDAL")
    (work/"pipeline.json").write_text(json.dumps(pipeline, allow_nan=False), encoding="utf-8")
    _run(binary, ["pipeline", str(work/"pipeline.json"), "--metadata", str(work/"metadata.json")], work)
    return digest


def _proper_rigid(matrix):
    import numpy as np
    value = array(matrix, shape=(4, 4))
    rotation = value[:3,:3]
    if not np.allclose(value[3], [0,0,0,1], atol=1e-10, rtol=0) or not np.allclose(
        rotation.T@rotation, np.eye(3), atol=1e-8, rtol=0
    ) or not math.isclose(float(np.linalg.det(rotation)), 1, abs_tol=1e-8, rel_tol=0):
        fail("Expected a finite proper rigid transform, not scale/reflection/shear")
    return value


def rigid_point_cloud_registration(args, output_dir):
    tool = "GeoSpatialRigidPointCloudRegistration"; guard(tool,args)
    import numpy as np
    from scipy.spatial import cKDTree
    crs(args["crs"])
    fixed = array(args["reference_xyz_m"]); moving = array(args["moving_xyz_m"])
    for cloud in (fixed,moving):
        if cloud.ndim != 2 or cloud.shape[1] != 3 or not 4 <= len(cloud) <= 2048:
            fail("Expected 4..2048 XYZ observations per cloud")
        if len({tuple(row) for row in cloud.tolist()}) != len(cloud) or np.linalg.matrix_rank(cloud-cloud.mean(axis=0)) < 2:
            fail("Each cloud must have unique, non-collinear observations")
    fields = ["X","Y","Z","PointId"]
    with tempfile.TemporaryDirectory(prefix="spatial-icp-") as temp:
        work = Path(temp)
        for name,values in (("fixed",fixed),("moving",moving)):
            (work/(name+".csv")).write_bytes(_csv(fields,[[*point,i] for i,point in enumerate(values.tolist())]))
        pipeline = [
            {"type":"readers.text","filename":str(work/"fixed.csv"),"separator":",","tag":"fixed"},
            {"type":"readers.text","filename":str(work/"moving.csv"),"separator":",","tag":"moving"},
            {"type":"filters.icp","inputs":["fixed","moving"],"max_iter":args["maximum_iterations"]},
            {"type":"writers.text","filename":str(work/"registered.csv"),"format":"csv","precision":17,
             "order":",".join(fields),"keep_unspecified":False,"write_header":True}]
        digest = _pdal_execute(work,pipeline)
        metadata_blob = _native_bytes(work/"metadata.json",1048576)
        metadata = json.loads(metadata_blob)
        native = metadata["stages"]["filters.icp"]
        if native.get("converged") is not True:
            fail("PDAL ICP did not declare convergence", "upstream_failure")
        coefficients = [float(value) for value in native["composed"].split()]
        if len(coefficients) != 16:
            fail("ICP did not provide the world-coordinate composed matrix", "invalid_result")
        transform = _proper_rigid(np.asarray(coefficients).reshape(4,4))
        blob = _native_bytes(work/"registered.csv",4*1024**2)
        rows = _ordered_point_rows(blob,fields,len(moving))
        xyz = array([row[:3] for row in rows])
        replay = moving@transform[:3,:3].T+transform[:3,3]
        replay_error = float(np.max(np.abs(xyz-replay)))
        if replay_error > 1e-6:
            fail("Serialized ICP transform does not replay output within 1e-6 m", "invalid_result")
        distances = cKDTree(fixed).query(xyz,k=1,workers=1)[0]
        frame = {"source_crs":args["crs"],"destination_crs":args["crs"],
                 "vertical_reference":args["vertical_reference"],"transform_convention":"row_major_homogeneous_moving_to_reference",
                 "point_identity":"moving_input_zero_based","nodata":None}
        manifest = [artifact(output_dir,"registered.csv",_csv(fields,rows),"text/csv"),
                    artifact(output_dir,"frame.json",json.dumps(frame).encode(),"application/json"),
                    artifact(output_dir,"icp.metadata.json",metadata_blob,"application/json")]
        return finish(tool,dict(method="PDAL.filters.icp",crs=args["crs"],vertical_reference=args["vertical_reference"],
            columns=fields,rows=rows,transform=transform.tolist(),converged=True,
            nearest_reference_rmse_m=float(np.sqrt(np.mean(distances**2))),transform_replay_error_m=replay_error,
            correspondence="nearest_reference_point_not_ground_truth_accuracy",artifact_manifest=manifest,
            native_version="2.9.1",native_binary_sha256=digest,
            units={"X":"m","Y":"m","Z":"m","PointId":"input_zero_based","translation":"m",
                   "rotation":"dimensionless","residual":"m"}))


def navigation_based_lidar_georeference(args, output_dir):
    tool = "GeoSpatialNavigationBasedLidarGeoreference"; guard(tool,args)
    import numpy as np
    scan = array(args["scan_xyzt"]); trajectory = array(args["trajectory"])
    if scan.ndim != 2 or scan.shape[1] != 4 or trajectory.ndim != 2 or trajectory.shape[1] != 8:
        fail("Expected scanner XYZ/time and trajectory time/lon/lat/height/roll/pitch/azimuth/wander columns")
    times = trajectory[:,0]
    if np.any(np.diff(times) <= 0):
        fail("Trajectory times must be strictly increasing")
    queries = scan[:,3]+args["time_offset_s"]
    if np.any(queries <= times[0]) or np.any(queries > times[-1]):
        fail("PDAL trajectory support is (first_time,last_time]; no extrapolation or unchanged out-of-domain points")
    if np.any(np.abs(trajectory[:,1]) > 180) or np.any(np.abs(trajectory[:,2]) >= 90):
        fail("Trajectory longitude/latitude outside declared non-polar WGS84 domain")
    if np.any(np.abs(trajectory[:,4:]) > 2*math.pi):
        fail("Trajectory attitude columns must be radians within +/-2*pi")
    transform = _proper_rigid(args["scan_to_imu"])
    fields = ["X","Y","Z","PointId","GpsTime"]
    with tempfile.TemporaryDirectory(prefix="spatial-georeference-") as temp:
        work = Path(temp)
        (work/"scan.csv").write_bytes(_csv(fields,[[*point[:3],i,point[3]] for i,point in enumerate(scan.tolist())]))
        nav = [[math.radians(row[1]),math.radians(row[2]),row[3],*row[4:],row[0]] for row in trajectory.tolist()]
        (work/"trajectory.csv").write_bytes(_csv(["X","Y","Z","Roll","Pitch","Azimuth","WanderAngle","GpsTime"],nav))
        pipeline = [
            {"type":"readers.text","filename":str(work/"scan.csv"),"separator":","},
            {"type":"filters.georeference","trajectory_file":str(work/"trajectory.csv"),
             "trajectory_options":{"type":"readers.text","separator":","},
             "scan2imu":" ".join(format(value,".17g") for value in transform.ravel()),
             "coordinate_system":"NED","time_offset":args["time_offset_s"],"reverse":False},
            {"type":"writers.text","filename":str(work/"georeferenced.csv"),"format":"csv","precision":17,
             "order":",".join(fields),"keep_unspecified":False,"write_header":True}]
        digest = _pdal_execute(work,pipeline)
        rows = _ordered_point_rows(_native_bytes(work/"georeferenced.csv",4*1024**2),fields,len(scan))
        if any(abs(row[0]) > 180 or abs(row[1]) > 90 or row[4] != scan[i,3] for i,row in enumerate(rows)):
            fail("Invalid WGS84 output or changed source timestamps", "invalid_result")
        frame = {"source_frame":"scanner_to_NED_IMU","destination_crs":"EPSG:4979",
                 "axis_order":["longitude","latitude","ellipsoidal_height"],
                 "trajectory_angle_conversion":"longitude_latitude_degrees_to_radians_explicit",
                 "supported_time_interval":"open_first_closed_last","nodata":None}
        manifest = [artifact(output_dir,"georeferenced.csv",_csv(fields,rows),"text/csv"),
                    artifact(output_dir,"frame.json",json.dumps(frame).encode(),"application/json")]
        return finish(tool,dict(method="PDAL.filters.georeference",source_frame="scanner_to_NED_IMU",
            destination_crs="EPSG:4979",axis_order=frame["axis_order"],columns=fields,rows=rows,
            trajectory_interval_s=[float(times[0]),float(times[-1])],supported_time_interval="open_first_closed_last",
            artifact_manifest=manifest,native_version="2.9.1",native_binary_sha256=digest,
            units={"X":"degree_longitude","Y":"degree_latitude","Z":"m_ellipsoidal",
                   "PointId":"input_zero_based","GpsTime":"s"}))


def _ply_mesh_summary(blob):
    """Bounded ASCII mesh validation/accounting; reconstruction remains PDAL."""
    if len(blob) > 32*1024**2:
        fail("PLY exceeds fixed byte budget", "resource_limit")
    lines = blob.decode("ascii").splitlines()
    if len(lines) < 10 or lines[:2] != ["ply","format ascii 1.0"]:
        fail("Expected ASCII PLY 1.0", "invalid_result")
    counts, properties, current = {}, {}, None
    header_end = None
    for i,line in enumerate(lines[2:130],2):
        tokens = line.split()
        if not tokens:
            fail("Empty PLY header record", "invalid_result")
        if tokens[0] in ("comment","obj_info"):
            continue
        if tokens[0] == "end_header":
            header_end = i+1; break
        if tokens[0] == "element" and len(tokens) == 3 and tokens[1] in ("vertex","face") and tokens[1] not in counts:
            current = tokens[1]; counts[current] = int(tokens[2]); properties[current] = []
        elif tokens[0] == "property" and current is not None:
            properties[current].append(tokens[1:])
        else:
            fail("Unexpected PLY header element", "invalid_result")
    if header_end is None or list(counts) != ["vertex","face"] or not 4 <= counts["vertex"] <= 50000 or not 1 <= counts["face"] <= 100000:
        fail("PLY vertex/face counts are missing or outside fixed budget", "invalid_result")
    props = properties["vertex"]
    if len(props) != 3 or [p[-1].lower() for p in props] != ["x","y","z"] or any(
        len(p) != 2 or p[0] not in ("float","double","float32","float64") for p in props
    ):
        fail("Only explicitly typed XYZ vertex columns are accepted", "invalid_result")
    face = properties["face"]
    if len(face) != 1 or len(face[0]) != 4 or face[0][0] != "list" or face[0][-1] not in ("vertex_indices","vertex_index"):
        fail("Expected one PLY face-index list", "invalid_result")
    integer_types = {"char","uchar","short","ushort","int","uint","int8","uint8","int16","uint16","int32","uint32"}
    if face[0][1] not in integer_types or face[0][2] not in integer_types:
        fail("Face list indices must use integer types", "invalid_result")
    data = lines[header_end:]
    if len(data) != counts["vertex"]+counts["face"]:
        fail("PLY record count differs from header", "invalid_result")
    vertices = []
    for line in data[:counts["vertex"]]:
        row = [float(v) for v in line.split()]
        if len(row) != 3 or not all(math.isfinite(v) and abs(v) <= 1e9 for v in row):
            fail("Non-finite/out-of-domain PLY vertex", "invalid_result")
        vertices.append(row)
    def cross(a,b):
        return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
    edges, area, volume = {}, 0.0, 0.0
    origin = vertices[0]
    for line in data[counts["vertex"]:]:
        row = [int(v) for v in line.split()]
        if len(row) != 4 or row[0] != 3 or len(set(row[1:])) != 3 or min(row[1:]) < 0 or max(row[1:]) >= len(vertices):
            fail("Expected valid nonrepeated triangular face indices", "invalid_result")
        a,b,c = [vertices[index] for index in row[1:]]
        normal = cross([b[j]-a[j] for j in range(3)],[c[j]-a[j] for j in range(3)])
        face_area = math.sqrt(sum(value*value for value in normal))/2
        if not face_area > 0:
            fail("Degenerate PLY triangle", "invalid_result")
        area += face_area
        aa,bb,cc = [[point[j]-origin[j] for j in range(3)] for point in (a,b,c)]
        bc = cross(bb,cc)
        volume += sum(aa[j]*bc[j] for j in range(3))/6
        for u,v in ((row[1],row[2]),(row[2],row[3]),(row[3],row[1])):
            key = (min(u,v),max(u,v)); count,balance = edges.get(key,(0,0))
            edges[key] = (count+1,balance+(1 if u < v else -1))
    closed = all(count == 2 for count,_ in edges.values())
    oriented = all(balance == 0 for _,balance in edges.values())
    return {"vertex_count":len(vertices),"triangle_count":counts["face"],"surface_area_m2":area,
            "closed_two_manifold_edges":closed,"consistent_edge_orientation":oriented,
            "oriented_volume_m3":volume if closed and oriented else None,
            "bounds_xyz_m":[[min(p[j] for p in vertices) for j in range(3)],
                            [max(p[j] for p in vertices) for j in range(3)]]}


def survey_poisson_surface(args, output_dir):
    tool = "GeoSpatialSurveyPoissonSurface"; guard(tool,args)
    import numpy as np
    crs(args["crs"])
    points = array(args["points_xyz_m"]); normals = array(args["oriented_unit_normals"],shape=points.shape)
    if points.ndim != 2 or points.shape[1] != 3 or not 6 <= len(points) <= 2048:
        fail("Expected 6..2048 oriented observations")
    if len({tuple(row) for row in points.tolist()}) != len(points) or np.linalg.matrix_rank(points-points.mean(axis=0)) < 2:
        fail("Unique non-collinear samples are required")
    if not np.allclose(np.linalg.norm(normals,axis=1),1,atol=1e-6,rtol=0):
        fail("Normals must already be unit length; no silent normalization")
    with tempfile.TemporaryDirectory(prefix="spatial-poisson-") as temp:
        work = Path(temp)
        (work/"oriented.csv").write_bytes(_csv(["X","Y","Z","NormalX","NormalY","NormalZ"],
                                              np.column_stack([points,normals]).tolist()))
        pipeline = [
            {"type":"readers.text","filename":str(work/"oriented.csv"),"separator":","},
            {"type":"filters.poisson","depth":args["octree_depth"],"density":False},
            {"type":"writers.ply","filename":str(work/"mesh.ply"),"storage_mode":"ascii","faces":True,
             "dims":"X=double,Y=double,Z=double","precision":17,"sized_types":False}]
        digest = _pdal_execute(work,pipeline)
        blob = _native_bytes(work/"mesh.ply",32*1024**2)
        summary = _ply_mesh_summary(blob)
        frame = {"source_crs":args["crs"],"destination_crs":args["crs"],"vertical_reference":args["vertical_reference"],
                 "geometry":"imputed_surface_not_original_point_identity","normals":"caller_declared_consistently_oriented",
                 "volume_interpretation":"oriented_mesh_integral_not_self_intersection_certification","nodata":None}
        manifest = [artifact(output_dir,"mesh.ply",blob,"application/x-ply"),
                    artifact(output_dir,"frame.json",json.dumps(frame).encode(),"application/json")]
        return finish(tool,dict(method="PDAL.filters.poisson",crs=args["crs"],vertical_reference=args["vertical_reference"],
            **summary,geometry=frame["geometry"],volume_interpretation=frame["volume_interpretation"],artifact_manifest=manifest,
            native_version="2.9.1",native_binary_sha256=digest,units={"coordinates":"m","surface_area":"m2","oriented_volume":"m3"}))


def _grass_numeric(blob, expected_header):
    lines = blob.decode("ascii").splitlines()
    if len(lines) < 7:
        fail("Native raster is missing its header or values", "invalid_result")
    header = {k.strip():float(v) for k,v in (line.split(":",1) for line in lines[:6])}
    if header != expected_header:
        fail("Native raster changed CRS-aligned extent/shape", "invalid_result")
    rows,cols = int(header["rows"]),int(header["cols"])
    tokens = " ".join(lines[6:]).split()
    if len(tokens) != rows*cols or "*" in tokens:
        fail("Solar output is incomplete; no implicit NoData fill", "invalid_result")
    values = [float(token) for token in tokens]
    if not all(math.isfinite(value) and value >= 0 for value in values):
        fail("Solar irradiance must be finite and nonnegative", "invalid_result")
    return [values[i:i+cols] for i in range(0,len(values),cols)]


def terrain_solar_irradiance(args, output_dir):
    tool = "GeoSpatialTerrainSolarIrradiance"; guard(tool,args)
    import numpy as np
    elevation = array(args["elevation_m"]); grid = grid_info(args,elevation.shape)
    inputs = {"elevation":elevation,
              "slope":array(args["slope_deg"],shape=elevation.shape,low=0,high=90),
              "aspect":array(args["aspect_ccw_from_east_deg"],shape=elevation.shape,low=0,high=360)}
    converted = {name:values.astype(np.float32).astype(float) for name,values in inputs.items()}
    rounding = {name:float(np.max(np.abs(values-converted[name]))) for name,values in inputs.items()}
    binary,digest = binding("GRASS")
    with tempfile.TemporaryDirectory(prefix="spatial-solar-") as temp:
        work = Path(temp)
        for field,name in (("elevation","input.asc"),("slope","solar-slope.asc"),("aspect","solar-aspect.asc")):
            (work/name).write_bytes(_ascii(args,converted[field].tolist()))
        (work/"request.json").write_text(json.dumps({"tool":tool,"args":args},allow_nan=False),encoding="utf-8")
        _run(binary,["--tmp-project",args["crs"],"--exec",sys.executable,str(Path(__file__).with_name("grass_task.py")),str(work)],work)
        header = {k.strip():float(v) for k,v in (line.split(":",1) for line in
                   _ascii(args,converted["elevation"].tolist()).decode().splitlines()[:6])}
        result,manifest = {},[]
        for name in ("beam","diffuse","reflected","global"):
            blob = _native_bytes(work/(name+".asc"),2*1024**2)
            result[name] = _grass_numeric(blob,header)
            manifest.append(artifact(output_dir,name+".asc",blob,"text/x-grass-ascii-grid"))
        total = np.asarray(result["beam"])+np.asarray(result["diffuse"])+np.asarray(result["reflected"])
        residual = float(np.max(np.abs(np.asarray(result["global"])-total)))
        bound = float(8*np.finfo(np.float32).eps*max(1.0,float(np.max(total))))
        if residual > bound:
            fail("Solar components fail native-float32 roundoff accounting", "invalid_result")
        frame = {**grid,"solar_clock":"local_apparent_solar_time","native_precision":"FCELL_float32_explicit",
                 "input_rounding_max":rounding,"elevation_reference":"mean_sea_level","terrain_shadow":True}
        manifest.append(artifact(output_dir,"frame.json",json.dumps(frame).encode(),"application/json"))
        return finish(tool,dict(method="GRASS.r.sun_instantaneous",grid=grid,irradiance_w_m2=result,
            day_of_year=args["day_of_year"],local_solar_time_h=args["local_solar_time_h"],
            solar_clock="local_apparent_solar_time",native_precision="FCELL_float32_explicit",input_rounding_max=rounding,
            component_residual_w_m2=residual,component_roundoff_bound_w_m2=bound,terrain_shadow=True,
            artifact_manifest=manifest,native_version="8.5.0",native_binary_sha256=digest,
            units={"irradiance":"W/m2","elevation_rounding":"m","angle_rounding":"degree","time":"local_solar_hour"}))


def _facility(args,coverage,output_dir):
    import numpy as np
    import pulp
    from spopt.locate import LSCP,PMedian
    cost=array(args["cost_matrix"],low=0)
    if cost.ndim!=2 or max(cost.shape)>64:
        fail("Cost matrix must be 1..64 demands by 1..64 candidates")
    binary,digest=binding("CBC")
    if coverage:
        model=LSCP.from_cost_matrix(cost,service_radius=args["service_radius"])
    else:
        weights=array(args["demand_weights"],shape=(len(cost),),low=0)
        if not np.any(weights>0) or args["facility_count"]>cost.shape[1]:
            fail("Positive total demand and feasible facility count required")
        model=PMedian.from_cost_matrix(cost,weights,p_facilities=args["facility_count"])
    # Export the actual spopt/PuLP model. Fixed CBC command avoids PuLP's
    # unconstrained process launcher and preserves native exit/status evidence.
    with tempfile.TemporaryDirectory(prefix="spatial-cbc-") as temp:
        work=Path(temp)
        variables,names,constraints,objective=model.problem.writeMPS(str(work/"model.mps"),rename=1)
        stdout,stderr=_run(binary,[str(work/"model.mps"),"-threads","1","-seconds","90","-ratioGap","0",
                           "-allowableGap","0","-solve","-solution",str(work/"result.sol"),"-quit"],work)
        solution=work/"result.sol"
        if not solution.is_file() or solution.is_symlink() or solution.stat().st_size>4*1024**2:
            fail("CBC produced no bounded solution evidence", "upstream_failure")
        solver=pulp.COIN_CMD(path=str(binary),msg=False,threads=1)
        status,values,reduced,prices,slacks,sol_status=solver.readsol_MPS(str(solution),model.problem,variables,names,constraints)
        manifest=[artifact(output_dir,"cbc.stdout.txt",stdout,"text/plain"),
                  artifact(output_dir,"cbc.stderr.txt",stderr,"text/plain"),
                  artifact(output_dir,"cbc.solution.txt",solution.read_bytes(),"text/plain")]
        result=dict(method="spopt.LSCP" if coverage else "spopt.PMedian",native_binary_sha256=digest,
                    native_version="2.10.12",status="not_proven_optimal",selected_facilities=[],
                    client_facilities=[],objective=None,artifact_manifest=manifest,
                    tie_policy="any_proven_optimum_no_lexicographic_claim",
                    units={"cost":args["cost_unit"],"objective":"facility_count" if coverage else args["cost_unit"]+"*demand_weight"})
        if status==pulp.LpStatusInfeasible and sol_status==pulp.LpSolutionInfeasible:
            result["status"]="infeasible"; return result
        if status!=pulp.LpStatusOptimal or sol_status!=pulp.LpSolutionOptimal:
            return result
        model.problem.assignVarsVals(values)
        facility_values=[float(v.value()) for v in model.fac_vars]
        if any(min(abs(v),abs(v-1))>1e-7 for v in facility_values):
            fail("CBC facility selection is not integral", "invalid_result")
        selected=[i for i,v in enumerate(facility_values) if v>.5]
        if not selected or (not coverage and len(selected)!=args["facility_count"]):
            fail("CBC facility cardinality failed", "invalid_result")
        if coverage:
            served=[[j for j in selected if cost[i,j]<=args["service_radius"]] for i in range(len(cost))]
            if any(not row for row in served):
                fail("CBC selected facilities leave uncovered demand", "invalid_result")
            objective_check=float(len(selected))
        else:
            served=[[min(selected,key=lambda j:(cost[i,j],j))] for i in range(len(cost))]
            objective_check=float(sum(weights[i]*cost[i,row[0]] for i,row in enumerate(served)))
        actual=float(pulp.value(model.problem.objective))
        if not math.isfinite(actual) or not math.isclose(actual,objective_check,rel_tol=1e-7,abs_tol=1e-7):
            fail("CBC objective does not match physical cost accounting", "invalid_result")
        result.update(status="proven_optimal",selected_facilities=selected,client_facilities=served,objective=actual)
        return result


def demand_weighted_facility_siting(args,output_dir):
    tool="GeoSpatialDemandWeightedFacilitySiting"; guard(tool,args)
    return finish(tool,_facility(args,False,output_dir))


def minimum_coverage_facility_set(args,output_dir):
    tool="GeoSpatialMinimumCoverageFacilitySet"; guard(tool,args)
    return finish(tool,_facility(args,True,output_dir))

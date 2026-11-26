"""Materialize four real native source adapters, not catalog registrations."""
from copy import deepcopy
import json
from pathlib import Path

GROUP=Path(__file__).resolve().parent
ROOT=GROUP.parents[4]
PREFIX=GROUP.relative_to(ROOT).as_posix()
PDAL_COMMIT="fceafbd400639f8376e3d4cd21230175d5b314d9"
GRASS_COMMIT="8d6ceba290a2f0059a7301b9d4944455f313da72"
IDS=["GeoSpatialRigidPointCloudRegistration","GeoSpatialNavigationBasedLidarGeoreference",
     "GeoSpatialSurveyPoissonSurface","GeoSpatialTerrainSolarIrradiance"]


def obj(props):
    return {"type":"object","additionalProperties":False,"properties":props,"required":list(props)}


def number(low=-1e9,high=1e9):
    return {"type":"number","minimum":low,"maximum":high}


def integer(low,high):
    return {"type":"integer","minimum":low,"maximum":high}


def arr(items,low,high):
    return {"type":"array","items":items,"minItems":low,"maxItems":high}


def const(value):
    return {"const":value}


def units(values):
    return obj({key:const(value) for key,value in values.items()})


def matrix(item=None):
    return arr(arr(item or number(),3,64),3,64)


def write(relative,value):
    path=ROOT/relative; path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,ensure_ascii=True,allow_nan=False)+"\n",encoding="utf-8")


def main():
    pending=json.loads((GROUP/"pending-contracts.json").read_text(encoding="utf-8"))
    examples=json.loads((GROUP/"pending-examples.json").read_text(encoding="utf-8"))
    snapshot=GROUP/"continuation-r7-prior-contracts.json"
    if not snapshot.exists():
        write(PREFIX+"/continuation-r7-prior-contracts.json",{"pending":pending,"examples":examples})
    template=deepcopy(pending["GeoSpatialPointCloudGroundClassification"])
    old_output=template["output_schema"]["properties"]
    base_output={key:deepcopy(old_output[key]) for key in
                 ("artifact_manifest","native_version","native_binary_sha256","artifacts","provenance")}
    base_output["artifact_manifest"]["maxItems"]=5
    crs={"type":"string","pattern":"^EPSG:[1-9][0-9]{2,5}$"}
    vertical={"type":"string","minLength":1,"maxLength":120}
    cloud=arr(arr(number(-1e8,1e8),3,3),4,2048)
    evidence=[]
    def add(tool,function,project,props,out,fixture,in_units,out_units,oracle,negative,source_files,artifacts):
        spec=deepcopy(template)
        spec.update(id=tool,status="source_revised_unverified",formal_eligible=False,catalog_registered=False,
                    metadata_profile="scientific",deployment="not_deployed",submission="not_submitted",model_workflow="not_run")
        spec["entrypoint"]["function"]=function
        spec["private_kernel"]={"module":"geological_agent.geology.expansion501_spatial_support.native","function":function}
        spec["input_schema"]=obj({**props,"units":units(in_units)})
        spec["output_schema"]=obj({**base_output,**out,"units":units(out_units)})
        spec["output_schema"]["properties"]["native_version"]=const("2.9.1" if project=="PDAL" else "8.5.0")
        commit=PDAL_COMMIT if project=="PDAL" else GRASS_COMMIT
        spec["source"]={"project":project,"url":source_files[0],"source_commit":commit,
                        "license":"BSD-3-Clause" if project=="PDAL" else "GPL-2.0-or-later"}
        spec["numeric_oracle"]=oracle; spec["negative_cases"]=negative
        spec["integration_gate"]=["parent_fixed_v2_profile_binding_and_correct_interpreter_dependencies",
            "native_binary_and_transitive_license_closure_not_available","independent_native_numerics_not_run",
            "private_helper_binding_to_v2_native_projects_not_yet_implemented"]
        pending[tool]=spec
        example={"tool_id":tool,"fixture_kind":"synthetic","status":"not_run",
                 "input":{**fixture,"units":in_units},"numeric_oracle":oracle}
        examples[tool]=example
        write("assets/expansion501-spatial/pending/"+tool+".json",example)
        evidence.append({"id":tool,"source_commit":commit,"official_sources":source_files,
            "native_version":"2.9.1" if project=="PDAL" else "8.5.0","license":spec["source"]["license"],
            "license_evidence_url":("https://github.com/PDAL/PDAL/blob/"+commit+"/LICENSE.txt") if project=="PDAL" else
                                   ("https://github.com/OSGeo/grass/blob/"+commit+"/COPYING"),
            "binary_sha256":None,"native_license_closure_complete":False,"artifact_rules":artifacts,
            "source_authored":True,"native_scientific_test_status":"not_run","formal_eligible":False})
    pdal="https://github.com/PDAL/PDAL/blob/"+PDAL_COMMIT+"/"
    points=[[500000,1000,0],[500003,1000,0],[500000,1004,0],[500000,1000,5]]
    add(IDS[0],"rigid_point_cloud_registration","PDAL",
        {"reference_xyz_m":cloud,"moving_xyz_m":cloud,"crs":crs,"vertical_reference":vertical,"maximum_iterations":integer(1,100)},
        {"method":const("PDAL.filters.icp"),"crs":crs,"vertical_reference":vertical,
         "columns":const(["X","Y","Z","PointId"]),"rows":arr(arr(number(),4,4),4,2048),
         "transform":arr(arr(number(),4,4),4,4),"converged":const(True),"nearest_reference_rmse_m":number(0),
         "transform_replay_error_m":number(0,1e-6),"correspondence":const("nearest_reference_point_not_ground_truth_accuracy")},
        {"reference_xyz_m":points,"moving_xyz_m":points,"crs":"EPSG:32631","vertical_reference":"synthetic_local_metre_datum","maximum_iterations":40},
        {"reference_xyz_m":"m","moving_xyz_m":"m"},
        {"X":"m","Y":"m","Z":"m","PointId":"input_zero_based","translation":"m","rotation":"dimensionless","residual":"m"},
        "Independent native oracle pending: identical asymmetric tetrahedra require identity transform and zero nearest-reference distance within 1e-6 m; small translated copy requires the inverse translation. Parser checks are not ICP acceptance.",
        ["collinear/duplicate clouds","geographic CRS","nonfinite coordinates","nonconverged native metadata","changed point identities","transform replay exceeds 1e-6 m"],
        [pdal+"doc/stages/filters.icp.md"],
        [{"glob":"registered.csv","validator_id":"csv"},{"glob":"frame.json","validator_id":"json"},{"glob":"icp.metadata.json","validator_id":"json"}])
    identity=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    add(IDS[1],"navigation_based_lidar_georeference","PDAL",
        {"scan_xyzt":arr(arr(number(-1e10,1e10),4,4),1,2048),"trajectory":arr(arr(number(-1e10,1e10),8,8),2,2048),
         "scan_to_imu":arr(arr(number(-1e6,1e6),4,4),4,4),"time_offset_s":number(-3600,3600),
         "gps_time_basis":const("same_continuous_GPS_seconds"),"trajectory_crs":const("EPSG:4979")},
        {"method":const("PDAL.filters.georeference"),"source_frame":const("scanner_to_NED_IMU"),"destination_crs":const("EPSG:4979"),
         "axis_order":const(["longitude","latitude","ellipsoidal_height"]),"columns":const(["X","Y","Z","PointId","GpsTime"]),
         "rows":arr(arr(number(-1e10,1e10),5,5),1,2048),"trajectory_interval_s":arr(number(-1e10,1e10),2,2),
         "supported_time_interval":const("open_first_closed_last")},
        {"scan_xyzt":[[0,0,0,100.5],[0,0,10,101]],"trajectory":[[100,3,0,1000,0,0,0,0],[101,3,0,1000,0,0,0,0]],
         "scan_to_imu":identity,"time_offset_s":0,"gps_time_basis":"same_continuous_GPS_seconds","trajectory_crs":"EPSG:4979"},
        {"scanner_xyz":"m","time":"s","trajectory_lon_lat":"degree","trajectory_height":"m_ellipsoidal","attitude":"radian","calibration_translation":"m"},
        {"X":"degree_longitude","Y":"degree_latitude","Z":"m_ellipsoidal","PointId":"input_zero_based","GpsTime":"s"},
        "Independent native oracle pending: stationary equatorial trajectory (lon 3 degrees, lat 0, height 1000 m), identity calibration and zero scanner vector give [3,0,1000]; NED down 10 m gives height 990 m. Require degree residual <=1e-9 and height <=1e-6 m. First-time query is a preserved negative, not clipped.",
        ["first-time/outside trajectory query","duplicate/decreasing trajectory time","degree/radian unit mismatch","improper calibration","nonfinite output","changed timestamp/identity"],
        [pdal+"filters/GeoreferenceFilter.cpp",pdal+"filters/private/georeference/Trajectory.cpp",pdal+"filters/private/georeference/LocalCartesian.cpp"],
        [{"glob":"georeferenced.csv","validator_id":"csv"},{"glob":"frame.json","validator_id":"json"}])
    sphere=[[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]]
    add(IDS[2],"survey_poisson_surface","PDAL",
        {"points_xyz_m":arr(arr(number(-1e8,1e8),3,3),6,2048),"oriented_unit_normals":arr(arr(number(-1,1),3,3),6,2048),
         "normals_consistently_oriented":const(True),"crs":crs,"vertical_reference":vertical,"octree_depth":integer(3,8)},
        {"method":const("PDAL.filters.poisson"),"crs":crs,"vertical_reference":vertical,"vertex_count":integer(4,50000),"triangle_count":integer(1,100000),
         "surface_area_m2":number(0,1e30),"closed_two_manifold_edges":{"type":"boolean"},"consistent_edge_orientation":{"type":"boolean"},
         "oriented_volume_m3":{"anyOf":[number(-1e30,1e30),{"type":"null"}]},"bounds_xyz_m":arr(arr(number(),3,3),2,2),
         "geometry":const("imputed_surface_not_original_point_identity"),"volume_interpretation":const("oriented_mesh_integral_not_self_intersection_certification")},
        {"points_xyz_m":sphere,"oriented_unit_normals":sphere,"normals_consistently_oriented":True,"crs":"EPSG:32631","vertical_reference":"synthetic_local_metre_datum","octree_depth":5},
        {"points_xyz_m":"m","normals":"dimensionless_unit_vectors"},{"coordinates":"m","surface_area":"m2","oriented_volume":"m3"},
        "Artifact-accounting oracle only: axis-aligned unit tetrahedron area=(3+sqrt(3))/2 and volume=1/6; open mesh volume must be null. Native Poisson shape accuracy has NO accepted tolerance/reference yet and remains a scientific acceptance blocker.",
        ["non-unit/inconsistent declared normals","duplicate/collinear samples","invalid/oversized PLY","nonfinite vertices","face-index escape","degenerate triangles"],
        [pdal+"doc/stages/filters.poisson.md",pdal+"doc/stages/writers.ply.md"],
        [{"glob":"mesh.ply","validator_id":"text_utf8"},{"glob":"frame.json","validator_id":"json"}])
    grid=deepcopy(pending["GeoSpatialTerrainViewshed"]["output_schema"]["properties"]["grid"])
    grid["properties"].pop("edge_policy",None)
    grid["required"]=[key for key in grid["required"] if key!="edge_policy"]
    grid["properties"]["nodata"]=const(None)
    zero=[[0]*3 for _ in range(3)]
    add(IDS[3],"terrain_solar_irradiance","GRASS",
        {"crs":crs,"origin_xy_m":arr(number(-1e8,1e8),2,2),"cell_size_m":number(.01,1e5),"elevation_m":matrix(number(-500,9000)),
         "slope_deg":matrix(number(0,90)),"aspect_ccw_from_east_deg":matrix(number(0,360)),"day_of_year":integer(1,365),
         "local_solar_time_h":number(0,24),"linke_turbidity":number(.01,20),"albedo":number(0,1),
         "native_precision":const("FCELL_float32_explicit"),"elevation_reference":const("mean_sea_level")},
        {"method":const("GRASS.r.sun_instantaneous"),"grid":grid,
         "irradiance_w_m2":obj({key:matrix(number(0,1e9)) for key in ("beam","diffuse","reflected","global")}),
         "day_of_year":integer(1,365),"local_solar_time_h":number(0,24),"solar_clock":const("local_apparent_solar_time"),
         "native_precision":const("FCELL_float32_explicit"),"input_rounding_max":obj({key:number(0) for key in ("elevation","slope","aspect")}),
         "component_residual_w_m2":number(0),"component_roundoff_bound_w_m2":number(0),"terrain_shadow":const(True)},
        {"crs":"EPSG:32631","origin_xy_m":[500000,30],"cell_size_m":10,"elevation_m":zero,"slope_deg":zero,"aspect_ccw_from_east_deg":zero,
         "day_of_year":80,"local_solar_time_h":0,"linke_turbidity":3,"albedo":0,"native_precision":"FCELL_float32_explicit","elevation_reference":"mean_sea_level"},
        {"coordinates":"m","elevation":"m_mean_sea_level","slope":"degree","aspect":"degree_ccw_from_east","time":"local_solar_hour","linke":"dimensionless","albedo":"dimensionless"},
        {"irradiance":"W/m2","elevation_rounding":"m","angle_rounding":"degree","time":"local_solar_hour"},
        "Independent native oracle pending: equatorial flat plane at local solar midnight has all four components zero; albedo=0 gives reflected=0; global equals beam+diffuse+reflected within the explicitly calculated FCELL roundoff bound. This is instantaneous W/m2, never daily irradiation.",
        ["CRS with degree/foot axes","shape mismatch","wrong aspect units","NoData output","changed affine/extent","negative/nonfinite irradiance","day outside 1..365"],
        ["https://grass.osgeo.org/grass85/manuals/r.sun.html","https://github.com/OSGeo/grass/blob/"+GRASS_COMMIT+"/raster/r.sun/main.c"],
        [{"glob":name+".asc","validator_id":"text_utf8"} for name in ("beam","diffuse","reflected","global")]+[{"glob":"frame.json","validator_id":"json"}])
    write(PREFIX+"/pending-contracts.json",pending); write(PREFIX+"/pending-examples.json",examples)
    write(PREFIX+"/continuation-r7-evidence.json",{"status":"source_revised_unverified","operations":evidence,
          "remote_uploads":0,"remote_environment_preparations":0,"native_scientific_tests_run":0,
          "remote_policy_gate":"denied_stop_no_alternate_transport","new_catalog_tools":0,"new_accepted":0,"new_deployed":0})
    remaining={
        "GeoSpatialLidarSensorTrajectoryRecovery":"Pinned trajectory Ceres solver summary is discarded; reviewed plugin/Ceres closure and a trustworthy convergence/identifiability acceptance criterion remain missing.",
        "GeoSpatialSIMWESedimentTransport":"Concentration particle/m3 versus mass-flux kg/(m*s) needs a reviewed physical definition and boundary/terminal-time mass-accounting reference; full stochastic state interface is incomplete.",
        "GeoSpatialAquiferSoluteTransport":"Pinned nonzero q terms have -q/nf on diagonal and +q/nf*cin on RHS; conventional source/sink semantics need independent physical resolution before conservative state claims.",
        "GeoSpatialRainfallErosivityFactor":"Chosen empirical formula, regional calibration domain and independent reference oracle are not established; no guessed formula or placeholder wrapper."}
    status=json.loads((GROUP/"resolution-status.json").read_text(encoding="utf-8"))
    status.update(status="source_revised_unverified",new_concrete_kernels=len(pending),scientific_adapters_still_incomplete=len(remaining),
                  unimplemented=remaining,still_integration_blocked=19,new_catalog_tools=0,new_accepted=0,new_deployed=0)
    write(PREFIX+"/resolution-status.json",status)
    adaptation=json.loads((GROUP/"adaptation-status.json").read_text(encoding="utf-8"))
    for row in adaptation["operations"]:
        if row["id"] in IDS:
            row.update(state="blocked",reason="Concrete bounded native kernel, closed pending schema and synthetic example authored; not registered. Fixed v2 binding, native closure and scientific acceptance are still missing.",
                       blockers=["v2_native_profile_binding_pending","native_binary_and_transitive_license_closure_missing","native_scientific_acceptance_not_run"])
        elif row["id"] in remaining:
            row.update(state="blocked",reason=remaining[row["id"]],blockers=["scientific_adapter_incomplete","reviewed_physical_or_native_evidence_missing"])
    write(PREFIX+"/adaptation-status.json",adaptation)
    for suffix,ids in (("pointcloud-cpu-pending",IDS[:3]),("terrain-location-cpu-pending",IDS[3:])):
        path=ROOT/"catalog/skills"/("expansion501-spatial-"+suffix)/"SKILL.md"
        content=path.read_text(encoding="utf-8")
        marker="\n# Local continuation r7\n"
        content=content.split(marker)[0]+marker+"\n"+"\n".join("- `"+tool+"`" for tool in ids)
        content+="\n\nSource-only pending adapters, not_deployed, not_submitted, model workflow not_run. No native numerical acceptance. No arbitrary pipeline/executable fields. Preserve exact units/CRS/affine and inspect continuation-r7-evidence.json before handoff.\n"
        path.write_text(content,encoding="utf-8")
    delivery=json.loads((GROUP/"delivery-files.json").read_text(encoding="utf-8"))
    added=[PREFIX+"/"+name for name in ("build_continuation_r7.py","continuation-r7-prior-contracts.json","continuation-r7-evidence.json",
           "acceptance/test_continuation_r7.py","acceptance/flow_continuation_r7.py")]
    added += ["assets/expansion501-spatial/pending/"+tool+".json" for tool in IDS]
    delivery["files"]=sorted(set(delivery["files"]+added))
    write(PREFIX+"/delivery-files.json",delivery)
    print(json.dumps({"pending_source_kernels":len(pending),"new_from_eight":4,"remaining_incomplete":4,
                      "integration_blocked":19,"new_registered":0,"new_accepted":0}))


if __name__=="__main__":
    main()

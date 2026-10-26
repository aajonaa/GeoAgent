"""Materialize pending source contracts only. Never registers pending kernels.

stdlib only. Existing catalog/requirements/research/failure reports are not
rewritten. The 19 adaptation rows remain blocked until genuine dispatch and
scientific acceptance are available.
"""
from copy import deepcopy
import json
from pathlib import Path

GROUP=Path(__file__).resolve().parent
ROOT=GROUP.parents[4]
PREFIX=GROUP.relative_to(ROOT).as_posix()
SUPPORT="geological_agent/geology/expansion501_spatial_support"
STATUS="source_authored_unregistered_acceptance_pending"
LANDLAB_COMMIT="575b4b7b424e9c74c55fc5cf334fbec6bea92723"
PDAL_COMMIT="fceafbd400639f8376e3d4cd21230175d5b314d9"
GRASS_COMMIT="8d6ceba290a2f0059a7301b9d4944455f313da72"
SPOPT_COMMIT="8d282940ab2827f84cb5f8319e396aa90ac686aa"
BASE=["numpy==2.1.3","scipy==1.15.3","pyproj==3.7.2","jsonschema==4.25.1"]
LANDLAB=BASE+["landlab==2.11.0","pandas==2.3.0","matplotlib==3.10.7","xarray==2026.9.0"]
MILP=BASE+["spopt==0.8.0","PuLP==3.3.0","libpysal==4.15.0","geopandas==1.1.2","shapely==2.1.2","pandas==2.3.0"]


def obj(properties):
    return {"type":"object","properties":properties,"required":list(properties),"additionalProperties":False}


def num(low=-1e100,high=1e100):
    return {"type":"number","minimum":low,"maximum":high}


def integer(low=0,high=4096):
    return {"type":"integer","minimum":low,"maximum":high}


def arr(item,low=1,high=4096):
    return {"type":"array","items":item,"minItems":low,"maxItems":high}


def const(value):
    return {"const":value}


def matrix(item=None,low=3,high=64):
    return arr(arr(item or num(-12000,10000),low,high),low,high)


def units(values):
    return obj({k:const(v) for k,v in values.items()})


def filled(v,n=5,m=None):
    return [[v for _ in range(m or n)] for _ in range(n)]


def write(path,value):
    path=ROOT/path
    path.parent.mkdir(parents=True,exist_ok=True)
    text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=True,indent=2)+"\n"
    path.write_text(text,encoding="utf-8",newline="\n")


def main():
    catalog=json.loads((GROUP/"catalog-additions.json").read_text(encoding="utf-8"))
    sample=next(t for t in catalog["tools"] if t["id"]=="GeoSpatialOverlandFlowStep")
    provenance=deepcopy(sample["output_schema"]["properties"]["provenance"])
    grid=deepcopy(sample["output_schema"]["properties"]["grid"])
    geo={"crs":{"type":"string","pattern":"^EPSG:[1-9][0-9]{2,6}$"},
         "origin_xy_m":arr(num(-1e8,1e8),2,2),"cell_size_m":num(1e-3,1e5),
         "nodata_policy":const("reject_missing")}
    geofix={"crs":"EPSG:32631","origin_xy_m":[500000,1000],"cell_size_m":1,"nodata_policy":"reject_missing"}
    geounits={"origin_xy_m":"m","cell_size_m":"m"}
    manifest=arr(obj({"name":{"type":"string","pattern":"^[A-Za-z0-9_.-]+$"},"bytes":integer(0,67108864),
                      "sha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"media_type":{"type":"string"}}),1,4)
    native_out={"native_version":{"type":"string"},"native_binary_sha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"artifact_manifest":manifest}
    pending={}; examples={}; evidence=[]
    def add(tool,function,module,project,requirements,props,result,example,in_units,out_units,oracle,url,commit,license_name,negative):
        properties={**props,"units":units(in_units)}
        example={**example,"units":in_units}
        output={**result,"units":units(out_units),"artifacts":arr({"type":"string"},0,4 if module=="native" else 0),"provenance":provenance}
        pending[tool]={"id":tool,"status":STATUS,"formal_eligible":False,"metadata_profile":"scientific",
             "catalog_registered":False,"deployment":"not_deployed","submission":"not_submitted","model_workflow":"not_run",
             "requirements":requirements,"input_schema":obj(properties),"output_schema":obj(output),
             "entrypoint":{"module":"geological_agent.geology.expansion501_spatial","function":function,"argument_parameter":"args",
                           "output_directory_parameter":"output_dir" if module=="native" else None},
             "private_kernel":{"module":"geological_agent.geology.expansion501_spatial_support."+module,"function":function},
             "source":{"project":project,"url":url,"source_commit":commit,"license":license_name},
             "numeric_oracle":oracle,"negative_cases":negative,"integration_gate":"parent_fixed_private_cpu_v2_and_actual_identity_receipt_and_CPU_acceptance"}
        examples[tool]={"fixture_kind":"synthetic","status":"not_run","input":example,"numeric_oracle":oracle}
        write("assets/expansion501-spatial/pending/"+tool+".json",examples[tool])
        evidence.append({"id":tool,"url":url,"source_commit":commit,"license":license_name,"requirements":requirements,
                         "source_state":STATUS,"native_binary_sha256":None,"transitive_license_closure":"pending"})
    u={**geounits,"bed_elevation_m":"m","mean_sea_level_m":"m","range_m":"m","period_s":"s","mannings_n":"s/m^(1/3)","scale_velocity_m_s":"m/s","minimum_depth_m":"m"}
    cycle=obj({"mean_sea_level_m":num(-1e4,1e4),"range_m":num(0,30),"period_s":num(60,172800)})
    status=filled(4,3,5); status[1]=[4,0,0,0,1]
    tidal_row=obj({"start_s":num(0),"end_s":num(0),"mean_depth_m":matrix(num(0)),"regularized_mask":matrix({"type":"boolean"}),
                   "flood_velocity_m_s":arr(num(),1,8192),"ebb_velocity_m_s":arr(num(),1,8192),
                   "boundary_inflow_m3_s":num(),"inundation_m3_s":num(0),"balance_residual_m3_s":num()})
    add("GeoTidalCycleFlow","tidal_cycle_flow","landlab_state","landlab",LANDLAB,
        {**geo,"bed_elevation_m":matrix(),"boundary_status":matrix({"enum":[0,1,4]}),"cycles":arr(cycle,1,16),
         "mannings_n":num(.001,1),"scale_velocity_m_s":num(.001,100),"minimum_depth_m":num(1e-4,1)},
        {"method":const("landlab.TidalFlowCalculator"),"grid":grid,"cycles":arr(tidal_row,1,16),
         "link_endpoints_xy_m":arr(arr(arr(num(-1e8,1e8),2,2),2,2),1,8192),
         "interpretation":const("independent_half_cycle_averages_not_transient_time_integration")},
        {**geofix,"cell_size_m":2,"bed_elevation_m":filled(-50,3,5),"boundary_status":status,
         "cycles":[{"mean_sea_level_m":0,"range_m":2,"period_s":40000}],"mannings_n":.01,"scale_velocity_m_s":1,"minimum_depth_m":.01},
        u,{"time":"s","depth":"m","velocity":"m/s","volume_rate":"m3/s"},
        "Three core cells, area 4 m2 each, tidal range 2 m / half-period 20000 s: boundary inflow 0.0012 m3/s. Ebb=-flood. Zero range gives zero velocity. Raising both bed and MSL equally must leave all fields unchanged.",
        "https://github.com/landlab/landlab/blob/"+LANDLAB_COMMIT+"/src/landlab/components/tidal_flow/tidal_flow_calculator.py",LANDLAB_COMMIT,"MIT",
        ["all boundaries closed","interior non-core","nonfinite","wrong CRS or units","zero period"])
    bed_props={**geo,"bedrock_elevation_m":matrix(),"soil_depth_m":matrix(num(0,100)),"critical_cells":arr(arr(integer(0,63),2,2),0,64),
         "dt_years":num(1e-6,100),"friction_slope":num(.01,10),"deposition_slope":num(.01,10),"cohesion_pa":num(0,1e8),
         "rock_density_kg_m3":num(1000,10000),"fines_fraction":num(0,1),"porosity":num(0,.9)}
    add("GeoBedrockLandslideEvolution","bedrock_landslide_evolution","landlab_state","landlab",LANDLAB,bed_props,
        {"method":const("landlab.BedrockLandslider_prescribed_events"),"grid":grid,"bedrock_elevation_m":matrix(),
         "soil_depth_m":matrix(num(0)),"elevation_m":matrix(),"erosion_m":matrix(num(0)),"deposition_m":matrix(num(0)),
         "dt_years":num(0),"suspended_rate_m3_year":num(0),"suspended_volume_m3":num(0),"exported_volume_m3":num(0),
         "solid_volume_residual_m3":num(),"boundary":const("fixed_value_no_boundary_landslides"),
         "routing":const("D8_DepressionFinderAndRouter_plus_separate_slope_weighted_MFD")},
        {**geofix,"bedrock_elevation_m":filled(10),"soil_depth_m":filled(1),"critical_cells":[],"dt_years":2,
         "friction_slope":1,"deposition_slope":1,"cohesion_pa":10000,"rock_density_kg_m3":2700,"fines_fraction":.2,"porosity":.3},
        {**geounits,"bedrock_elevation_m":"m","soil_depth_m":"m","dt_years":"year","friction_slope":"m/m","deposition_slope":"m/m", "cohesion_pa":"Pa","rock_density_kg_m3":"kg/m3","fines_fraction":"1","porosity":"1"},
        {"elevation":"m","time":"year","volume":"m3_solid","suspended_rate":"m3_solid/year"},
        "No prescribed events: terrain unchanged, all yields zero. Forced toe at elevation 0 below plateau 10 with friction slope 1: adjacent cardinal erosion plane 5.5 m, diagonal 5.5*sqrt(2). Use fines=1 to avoid deposition masking the plane; dt=2 requires suspended_volume=2*raw_rate.",
        "https://github.com/landlab/landlab/blob/"+LANDLAB_COMMIT+"/src/landlab/components/bedrock_landslider/bedrock_landslider.py",LANDLAB_COMMIT,"MIT",
        ["boundary trigger","negative soil","duplicate trigger","porosity>=1","wrong CRS/unit"])
    parcel=obj({"link":integer(0,254),"location_fraction":num(0,.999999999),"diameter_m":num(1e-5,10),"volume_m3":num(1e-9,1e6),"density_kg_m3":num(1001,10000),"abrasion_m_inverse":num(0,.1)})
    parcel_out=obj({"link":{"anyOf":[integer(0,254),{"type":"null"}]},"location_fraction":{"anyOf":[num(0,1),{"type":"null"}]},
                    "diameter_m":num(0),"volume_m3":num(0),"active":{"type":"boolean"},"exported":{"type":"boolean"}})
    history=obj({"time_s":num(0),"parcels":arr(parcel_out,1,256),"retained_mass_kg":num(0),"exported_mass_kg":num(0),
                 "abrasion_loss_kg":num(),"elevation_m":arr(num(),2,256)})
    add("GeoRiverSedimentParcelTransport","river_sediment_parcel_transport","landlab_state","landlab",LANDLAB,
        {"crs":geo["crs"],"nodes_xy_m":arr(arr(num(-1e8,1e8),2,2),2,256),"links":arr(arr(integer(0,255),2,2),1,255),
         "outlet_node":integer(0,255),"bedrock_elevation_m":arr(num(-12000,10000),2,256),"reach_length_m":arr(num(.001,1e6),1,255),
         "channel_width_m":arr(num(.001,1e4),1,255),"flow_depth_m":arr(num(0,100),1,255),"parcels":arr(parcel,1,256),
         "steps_s":arr(num(1e-6,3600),1,16),"porosity":num(0,.9),"fluid_density_kg_m3":num(900,1200),"minimum_slope":num(1e-8,.1)},
        {"method":const("landlab.NetworkSedimentTransporter_WilcockCrowe"),"crs":geo["crs"],"history":arr(history,1,17),
         "initial_mass_kg":num(0),"requested_duration_s":num(0),"actual_duration_s":num(0),
         "termination":{"enum":["all_parcels_exported","requested_steps_completed"]},"routing":const("fixed_initial_downhill_tree"),"active_layer":const("Constant10cm")},
        {"crs":"EPSG:32631","nodes_xy_m":[[500000,1000],[500100,1000],[500200,1000],[500300,1000]],"links":[[0,1],[1,2],[2,3]],
         "outlet_node":3,"bedrock_elevation_m":[3,2,1,0],"reach_length_m":[100]*3,"channel_width_m":[15]*3,"flow_depth_m":[0]*3,
         "parcels":[{"link":i,"location_fraction":.25,"diameter_m":.05,"volume_m3":1,"density_kg_m3":2650,"abrasion_m_inverse":0} for i in range(3)],
         "steps_s":[1,2],"porosity":.3,"fluid_density_kg_m3":1000,"minimum_slope":1e-4},
        {"nodes_xy_m":"m","bedrock_elevation_m":"m","reach_length_m":"m","channel_width_m":"m","flow_depth_m":"m","steps_s":"s","parcel_diameter":"m","parcel_volume":"m3","density":"kg/m3","abrasion":"1/m","porosity":"1","minimum_slope":"m/m"},
        {"coordinates":"m","time":"s","mass":"kg","volume":"m3","diameter":"m"},
        "Zero flow implies zero shear and transport; three 1 m3 parcels of density 2650 retain 7950 kg, zero export/abrasion, unchanged link/location/diameter at times [0,1,3]. Reordered node/link input must preserve physical output identities.",
        "https://github.com/landlab/landlab/blob/"+LANDLAB_COMMIT+"/src/landlab/components/network_sediment_transporter/network_sediment_transporter.py",LANDLAB_COMMIT,"MIT",
        ["cyclic/disconnected tree","ambiguous downhill receiver","reach shorter than chord","density <= fluid","negative flow depth","wrong units"])
    cloud={"crs":geo["crs"],"points_xyz_m":arr(arr(num(-1e8,1e8),3,3),4,4096),"feature_unit":const("dimensionless")}
    cloud_result={"method":{"type":"string"},"crs":geo["crs"],"columns":arr({"type":"string"},5,8),"rows":arr(arr(num(),5,8),4,4096),**native_out}
    native_units={"X":"m","Y":"m","Z":"m","PointId":"input_zero_based"}
    cloudfix={"crs":"EPSG:32631","feature_unit":"dimensionless"}
    def pdal(tool,function,stage,props,example,oracle,negative):
        feature_units={
            "filters.smrf":{"Classification":"dimensionless_label"},
            "filters.hag_nn":{"Classification":"dimensionless_label","HeightAboveGround":"m"},
            "filters.litree":{"HeightAboveGround":"m","ClusterID":"dimensionless_label"},
            "filters.covariancefeatures":{"Linearity":"dimensionless","Planarity":"dimensionless",
                                          "Scattering":"dimensionless","Verticality":"dimensionless"}}[stage]
        add(tool,function,"native","PDAL",BASE,{**cloud,**props},cloud_result,{**cloudfix,**example},
            {"points_xyz_m":"m",**({"height_above_ground_m":"m"} if "height_above_ground_m" in props else {})},{**native_units,**feature_units},oracle,
            "https://github.com/PDAL/PDAL/blob/"+PDAL_COMMIT+"/doc/stages/"+stage+".md",PDAL_COMMIT,"BSD-3-Clause",negative)
    pdal("GeoSpatialPointCloudGroundClassification","ground_classification","filters.smrf",
         {"cell_m":num(.01,100),"slope":num(.001,5),"threshold_m":num(.001,20),"window_m":num(.1,100)},
         {"points_xyz_m":[[x,y,0] for x in range(5) for y in range(5)],"cell_m":1,"slope":.15,"threshold_m":.5,"window_m":3},
         "A flat single-return plane has zero terrain residual: classify all 25 points as ground=2 without changing XYZ or point identity.",
         ["raster memory budget","duplicate XYZ","degree CRS","nonfinite","caller pipeline/executable key"])
    pdal("GeoSpatialPointCloudHeightAboveGround","height_above_ground","filters.hag_nn",
         {"classification":arr(integer(0,255),4,4096),"neighbors":integer(1,32)},
         {"points_xyz_m":[[0,0,10],[2,0,10],[0,2,10],[2,2,10],[1,1,13]],"classification":[2,2,2,2,1],"neighbors":4},
         "Ground is constant z=10: four ground heights are 0 and the interior z=13 return has HAG=3 m. Outside-support query must reject rather than accept PDAL zero fill.",
         ["no ground","collinear ground","outside convex hull","neighbors exceed ground","wrong CRS"])
    # Preserve the legacy input declaration; output units are per column above.
    pending["GeoSpatialPointCloudHeightAboveGround"]["input_schema"]["properties"]["feature_unit"]=const("m")
    examples["GeoSpatialPointCloudHeightAboveGround"]["input"]["feature_unit"]="m"
    pdal("GeoSpatialIndividualTreeSegmentation","individual_tree_segmentation","filters.litree",
         {"height_above_ground_m":arr(num(0,150),4,4096),"minimum_points":integer(2,1000),"minimum_height_m":num(0,100),"radius_m":num(.1,100)},
         {"points_xyz_m":[[0,0,10],[.1,0,9],[0,.1,9],[20,0,10],[20.1,0,9],[20,.1,9]],"height_above_ground_m":[10,9,9,10,9,9],"minimum_points":2,"minimum_height_m":3,"radius_m":2},
         "Two compact three-return crowns separated by 20 m, radius 2 m: two nonzero clusters, no cluster spans both crowns; labels themselves are arbitrary. Source IDs/XYZ must survive the required height sort.",
         ["negative HAG","length mismatch","nonfinite","untrusted pipeline key"])
    pdal("GeoSpatialPointCloudMorphologyDescriptors","morphology_descriptors","filters.covariancefeatures",
         {"neighbors":integer(3,64)}, {"points_xyz_m":[[x,0,0] for x in range(7)],"neighbors":4},
         "Collinear distinct points have rank-one covariance: Linearity=1, Planarity=0, Scattering=0 under Raw eigenvalues. Verticality in an eigenspace tie is not assigned an invented unique oracle.",
         ["neighbors >= point count","duplicate observations","nonfinite","user feature_set/mode key"])
    grass_grid=deepcopy(grid); grass_grid["properties"]["nodata"]=const("*")
    grass_grid["properties"]["edge_policy"]=const("native_truncated_neighborhood"); grass_grid["required"].append("edge_policy")
    grass_result={"method":{"type":"string"},"grid":grass_grid,"values":matrix({"anyOf":[integer(0,10),{"type":"null"}]}),**native_out}
    def grass(tool,function,module,props,example,oracle,negative):
        add(tool,function,"native","GRASS",BASE,{**geo,"elevation_m":matrix(),**props},grass_result,{**geofix,"elevation_m":filled(0,7),**example},
            {**geounits,"elevation_m":"m"},{"elevation":"m","result":"categorical"},oracle,
            "https://grass.osgeo.org/grass85/manuals/"+module+".html",GRASS_COMMIT,"GPL-2.0-or-later",negative)
    grass("GeoSpatialTerrainViewshed","terrain_viewshed","r.viewshed",
          {"observer_cell":arr(integer(0,63),2,2),"observer_height_m":num(.01,1000),"target_height_m":num(0,1000)},
          {"observer_cell":[3,3],"observer_height_m":2,"target_height_m":0},
          "Flat zero-elevation plane with observer 2 m above ground and no curvature/refraction flags: all cells visible=1. Preserve exact extent, spacing, CRS and explicit native nulls.",
          ["out-of-grid observer","degree CRS","missing cells","native altered header"])
    grass("GeoSpatialGeomorphonLandforms","geomorphon_landforms","r.geomorphon",
          {"search_cells":integer(1,32),"skip_cells":integer(0,31),"flat_angle_deg":num(.001,45)},
          {"search_cells":2,"skip_cells":0,"flat_angle_deg":1},
          "A constant plane has zero zenith/nadir deviations: interior cells are flat class 1. Edge-limited neighborhoods/nulls remain explicit, not zero-filled.",
          ["skip>=search","wrong angle unit","untrusted flags","native shape change"])
    facility_result={"method":{"type":"string"},"status":{"enum":["proven_optimal","infeasible","not_proven_optimal"]},
        "selected_facilities":arr(integer(0,63),0,64),"client_facilities":arr(arr(integer(0,63),1,64),0,64),
        "objective":{"anyOf":[num(0),{"type":"null"}]},"tie_policy":const("any_proven_optimum_no_lexicographic_claim"),**native_out}
    costs=[[0,2,7],[2,0,5],[7,5,0]]
    for tool,function,coverage in (("GeoSpatialDemandWeightedFacilitySiting","demand_weighted_facility_siting",False),
                                  ("GeoSpatialMinimumCoverageFacilitySet","minimum_coverage_facility_set",True)):
        props={"cost_matrix":matrix(num(0,1e9),1,64),"cost_unit":const("m")}
        ex={"cost_matrix":costs,"cost_unit":"m"}
        if coverage:
            props["service_radius"]=num(0,1e9); ex["service_radius"]=2
        else:
            props.update(demand_weights=arr(num(0,1e9),1,64),facility_count=integer(1,64))
            ex.update(demand_weights=[1,2,1],facility_count=1)
        add(tool,function,"native","spopt",MILP,props,facility_result,ex,
            {"cost_matrix":"m",**({"service_radius":"m"} if coverage else {"demand_weights":"people"})},
            {"cost":"m","objective":"facility_count" if coverage else "m*demand_weight"},
            "Hand enumeration: minimum cover with radius 2 needs facility 2 plus either 0 or 1, objective 2. All-positive cost matrix with radius 0 is infeasible." if coverage else
            "For p=1, candidate objectives are [11,7,17] weighted metres; unique optimum is facility 1, objective 7. Stopped integer-feasible status is NOT an optimality certificate.",
            "https://github.com/pysal/spopt/blob/"+SPOPT_COMMIT+"/spopt/locate/"+("coverage.py" if coverage else "p_median.py"),SPOPT_COMMIT,"BSD-3-Clause",
            ["negative costs","nonfinite","untrusted solver/path/options","infeasible or stopped solution must not be returned as proven optimal"])
    # Public names differ from internal helper names for three PDAL operations.
    for tool,name in (("GeoSpatialPointCloudGroundClassification","point_cloud_ground_classification"),
                      ("GeoSpatialPointCloudHeightAboveGround","point_cloud_height_above_ground"),
                      ("GeoSpatialPointCloudMorphologyDescriptors","point_cloud_morphology_descriptors")):
        pending[tool]["entrypoint"]["function"]=name
    for tool,example in examples.items():
        write("assets/expansion501-spatial/pending/"+tool+".json",example)
    write(PREFIX+"/pending-contracts.json",pending)
    write(PREFIX+"/pending-examples.json",examples)
    write(PREFIX+"/resolution-evidence.json",{"status":STATUS,"operations":evidence,
        "additional_sources":[
          {"project":"PuLP","version":"3.3.0","source_commit":None,"license":"MIT","url":"https://github.com/coin-or/pulp/releases/tag/3.3.0","license_url":"https://raw.githubusercontent.com/coin-or/pulp/3.3.0/LICENSE","status_evidence":"https://raw.githubusercontent.com/coin-or/pulp/3.3.0/pulp/apis/coin_api.py"},
          {"project":"CBC","version":"2.10.12","source_commit":None,"license":"EPL-2.0","url":"https://github.com/coin-or/Cbc/releases/tag/releases%2F2.10.12","license_url":"https://raw.githubusercontent.com/coin-or/Cbc/releases/2.10.12/LICENSE"}],
        "license_closure_complete":False,"native_binary_hashes":None,"source_release_binary_correspondence":"not_established"})
    write(PREFIX+"/requirements/pending-landlab-state.txt","\n".join(LANDLAB)+"\n")
    write(PREFIX+"/requirements/pending-pdal-grass.txt","\n".join(BASE)+"\n")
    write(PREFIX+"/requirements/pending-milp.txt","\n".join(MILP)+"\n")
    gaps={
        "GeoSpatialRigidPointCloudRegistration":"ICP API is confirmed; moving/fixed identity preservation, composed-transform content checks and convergence/fitness contracts are not yet implemented.",
        "GeoSpatialLidarSensorTrajectoryRecovery":"trajectory stage confirmed; exact output dimensions, scan-angle/time conventions and Ceres plugin identity still require a reviewed complete fixture/closure.",
        "GeoSpatialNavigationBasedLidarGeoreference":"georeference stage confirmed; exact trajectory reader/record transport, time support, NED calibration and geographic output contract are not yet implemented.",
        "GeoSpatialSurveyPoissonSurface":"Poisson stage confirmed; oriented-normal validation, bounded mesh face/content checks and bundled Poisson license/build closure are not yet implemented.",
        "GeoSpatialTerrainSolarIrradiance":"No complete fixed r.sun atmospheric/time/irradiance input and output contract authored; not registered.",
        "GeoSpatialSIMWESedimentTransport":"SIMWE confirmed; stochastic walker/time/concentration/erosion-deposition state and boundary mass accounting are not yet implemented.",
        "GeoSpatialAquiferSoluteTransport":"Native solute entry confirmed; active/Dirichlet/transmission status, source/sink units and conservative temporal state transport are not yet implemented.",
        "GeoSpatialRainfallErosivityFactor":"Native r.usler input/output units confirmed; chosen regional empirical relation, applicability domain and independent formula oracle remain unresolved."}
    adaptation=json.loads((GROUP/"adaptation-status.json").read_text(encoding="utf-8"))
    prior=[]
    for row in adaptation["operations"]:
        tool=row["id"]
        if tool in pending or tool in gaps:
            prior.append(deepcopy(row))
            row["state"]="blocked"
            row["reason"]=("Concrete private kernel, closed pending contracts and synthetic examples authored, but NOT catalog registered or integrated. " if tool in pending else gaps[tool]+" ")+"Main-runtime fixed private dispatch and correct-interpreter dependency guard remain unimplemented; acceptance pending."
            row["blockers"]=["parent_fixed_private_cpu_v2_not_implemented","scientific_numeric_acceptance_not_run"]
            if tool in gaps: row["blockers"].append("scientific_adapter_incomplete")
            elif pending[tool]["private_kernel"]["module"].endswith("native"):
                row["blockers"].append("native_binary_hash_and_transitive_license_closure_missing")
            else: row["blockers"].append("exact_local_scientific_dependencies_unavailable")
    snapshot=GROUP/"resolution-r1-prior-status.json"
    if not snapshot.exists(): write(PREFIX+"/resolution-r1-prior-status.json",{"operations":prior})
    write(PREFIX+"/adaptation-status.json",adaptation)
    write(PREFIX+"/resolution-status.json",{"status":STATUS,"assigned_blocked":19,"new_concrete_kernels":len(pending),
          "scientific_adapters_still_incomplete":len(gaps),"still_integration_blocked":19,"new_catalog_tools":0,
          "new_accepted":0,"new_deployed":0,"unimplemented":gaps,"existing_catalog_tools_untouched":True,
          "policy_denied_remote_actions_retried":False,"main_environment_modified":False})
    sections={"stateful-cpu-pending":[k for k,v in pending.items() if v["source"]["project"]=="landlab"],
              "pointcloud-cpu-pending":[k for k,v in pending.items() if v["source"]["project"]=="PDAL"],
              "terrain-location-cpu-pending":[k for k,v in pending.items() if v["source"]["project"] in {"GRASS","spopt"}]}
    skill_paths=[]
    for suffix,ids in sections.items():
        path="catalog/skills/expansion501-spatial-"+suffix+"/SKILL.md"; skill_paths.append(path)
        content="---\nname: expansion501-spatial-"+suffix+"\ndescription: Pending fixed CPU source adapters; unavailable until parent integration and acceptance.\n---\n\n"
        content+="# Availability and delivery\nSource-authored only; not_deployed; not_submitted; model workflow not_run. Not catalog registered. Receiving AI Lab certification is not established.\n\n"
        content+="# Scientific tasks\n"+"\n".join("- `"+i+"`" for i in ids)+"\n\n"
        content+="# Inputs and units\nUse the exact closed pending-contracts.json schemas. Synthetic examples are under assets/expansion501-spatial/pending/. No silent CRS, affine, datum, NoData or boundary changes.\n\n"
        content+="# Model workflow\nnot_run. Request actual observations, units and boundary/state assumptions; never portray synthetic fixtures as survey data.\n\n"
        content+="# Execution and handoff\nParent must implement trusted fixed-private-CPU dispatch and dependency attestation first. Caller executable paths, shell, JSON pipelines, installations and profile selection are forbidden.\n\n"
        content+="# Outputs and provenance\nTyped results and copied, bounded artifact manifests where applicable. Shared contracts must create final hashes/provenance after verified transport. Raw private-kernel results alone are not integrated results.\n\n"
        content+="# Errors and limitations\nFail on missing/incompatible dependencies, non-finite data, physical-domain errors, native exit/identity/content failures. Never accept an incumbent as proven optimal. All science/numerical/platform certification gates remain pending.\n\n"
        content+="# Acceptance\nIndependent analytic oracles and negatives are authored; see acceptance/test_resolution_r1.py. No native execution or numerical pass is claimed.\n"
        write(path,content)
    files=[SUPPORT+"/"+name for name in ("common.py","landlab_state.py","native.py","grass_task.py")]
    files += [PREFIX+"/"+name for name in ("build_resolution.py","pending-contracts.json","pending-examples.json","resolution-evidence.json",
        "resolution-status.json","resolution-r1-prior-status.json","shared-interface-proposal.md","acceptance/test_resolution_r1.py","acceptance/flow_resolution_r1.py",
        "unitfix-handoff.md","acceptance/test_units_r2.py","acceptance/flow_units_r2.py",
        "requirements/pending-landlab-state.txt","requirements/pending-pdal-grass.txt","requirements/pending-milp.txt")]
    files += ["assets/expansion501-spatial/pending/"+tool+".json" for tool in pending]+skill_paths
    delivery=json.loads((GROUP/"delivery-files.json").read_text(encoding="utf-8"))
    delivery["files"]=sorted(set(delivery["files"]+files))
    write(PREFIX+"/delivery-files.json",delivery)
    print(json.dumps({"pending_kernels":len(pending),"incomplete":len(gaps),"registered_new":0,"remaining_integration_blocked":19}))
    # A versioned, stdlib-only extension preserves the eleven original kernels.
    import runpy
    runpy.run_path(str(GROUP/"build_continuation_r7.py"),run_name="__main__")


if __name__=="__main__":
    main()

"""Explicit Landlab state adapters. Pending fixed private dispatch/acceptance."""
from __future__ import annotations

from .common import array, crs, fail, finish, guard, links_xy, node_field, raster, raster_grid


def tidal_cycle_flow(args):
    tool = "GeoTidalCycleFlow"
    guard(tool, args)
    import numpy as np
    from landlab.components import TidalFlowCalculator
    grid, bed, meta = raster_grid(args, "bed_elevation_m")
    status = array(args["boundary_status"], shape=bed.shape)
    perimeter = np.ones(bed.shape, dtype=bool)
    perimeter[1:-1, 1:-1] = False
    if not np.all(status[~perimeter] == 0) or not np.isin(status[perimeter], [1, 4]).all():
        fail("Interior must be core=0; perimeter must explicitly be open=1 or closed=4")
    if not np.any(status[perimeter] == 1):
        fail("At least one open tidal boundary is required")
    grid.status_at_node[:] = np.flipud(status).ravel().astype(np.uint8)
    node_field(grid, "topographic__elevation", bed)
    rows, elapsed = [], 0.0
    core = grid.status_at_node == 0
    tail, head = grid.nodes_at_link.T
    if not np.any(core[tail] != core[head]):
        fail("No core-to-boundary link")
    for forcing in args["cycles"]:
        # A declared datum translation, not a change to the upstream algorithm.
        # v2.11.0 inundation uses elevation relative to MSL even when its depth
        # routine accepts an absolute MSL. Keep BOTH routines in the same datum.
        grid.at_node["topographic__elevation"][:] = np.flipud(
            bed - forcing["mean_sea_level_m"]).ravel()
        model = TidalFlowCalculator(
            grid, tidal_range=forcing["range_m"], tidal_period=forcing["period_s"],
            roughness=args["mannings_n"], mean_sea_level=0.0,
            scale_velocity=args["scale_velocity_m_s"], min_water_depth=args["minimum_depth_m"])
        model.run_one_step()
        depth = grid.at_node["mean_water__depth"]
        flood = grid.at_link["flood_tide_flow__velocity"]
        ebb = grid.at_link["ebb_tide_flow__velocity"]
        inundation = model.calc_tidal_inundation_rate()
        for value in (depth, flood, ebb, inundation):
            if not np.isfinite(value).all():
                fail("Tidal solve is not finite", "upstream_failure")
        link_depth = np.minimum(depth[tail], depth[head])
        q = flood * link_depth * args["cell_size_m"]
        boundary_inflow = float(np.sum(q * (core[head].astype(int) - core[tail].astype(int))))
        forcing_rate = float(np.sum(inundation[core]) * args["cell_size_m"]**2)
        residual = boundary_inflow - forcing_rate
        if abs(residual) > 1e-9 * max(1.0, abs(forcing_rate)):
            fail("Tidal boundary flux does not balance inundation", "upstream_failure")
        rows.append(dict(start_s=elapsed, end_s=elapsed + forcing["period_s"],
                         mean_depth_m=raster(grid, "mean_water__depth"),
                         regularized_mask=np.flipud((depth <= args["minimum_depth_m"]).reshape(bed.shape)).tolist(),
                         flood_velocity_m_s=flood.tolist(), ebb_velocity_m_s=ebb.tolist(),
                         boundary_inflow_m3_s=boundary_inflow, inundation_m3_s=forcing_rate,
                         balance_residual_m3_s=residual))
        elapsed += forcing["period_s"]
    return finish(tool, dict(method="landlab.TidalFlowCalculator", grid=meta,
                  cycles=rows, link_endpoints_xy_m=links_xy(grid),
                  interpretation="independent_half_cycle_averages_not_transient_time_integration",
                  units={"time":"s", "depth":"m", "velocity":"m/s", "volume_rate":"m3/s"}))


def bedrock_landslide_evolution(args):
    tool = "GeoBedrockLandslideEvolution"
    guard(tool, args)
    import numpy as np
    from landlab.components import BedrockLandslider, FlowAccumulator
    grid, bed, meta = raster_grid(args, "bedrock_elevation_m")
    soil = array(args["soil_depth_m"], shape=bed.shape, low=0)
    node_field(grid, "bedrock__elevation", bed)
    node_field(grid, "soil__depth", soil)
    node_field(grid, "topographic__elevation", bed + soil)
    # Separate upstream routers retain their native field shapes. No hand-coded
    # D8/MFD algorithm and no silent DEM fill or post-run clipping.
    FlowAccumulator(grid, flow_director="FlowDirectorD8",
                    depression_finder="DepressionFinderAndRouter").run_one_step()
    hill, _, _ = raster_grid(args, "bedrock_elevation_m")
    node_field(hill, "topographic__elevation", bed + soil)
    FlowAccumulator(hill, flow_director="FlowDirectorMFD", diagonals=True,
                    partition_method="slope").run_one_step()
    for target, source in (
        ("hill_flow__receiver_node", "flow__receiver_node"),
        ("hill_flow__receiver_proportions", "flow__receiver_proportions"),
        ("hill_topographic__steepest_slope", "topographic__steepest_slope"),
    ):
        grid.add_field(target, hill.at_node[source].copy(), at="node")
    nodes = []
    for r, c in args["critical_cells"]:
        if not (0 < r < bed.shape[0]-1 and 0 < c < bed.shape[1]-1):
            fail("Prescribed critical cells must be interior")
        nodes.append((bed.shape[0]-1-r)*bed.shape[1] + c)
    if len(nodes) != len(set(nodes)):
        fail("Critical cells must be unique")
    model = BedrockLandslider(
        grid, angle_int_frict=args["friction_slope"],
        threshold_slope=args["deposition_slope"], cohesion_eff=args["cohesion_pa"],
        rho_r=args["rock_density_kg_m3"], fraction_fines_LS=args["fines_fraction"],
        phi=args["porosity"], seed=None, critical_sliding_nodes=nodes,
        landslides_on_boundary_nodes=False, max_pixelsize_landslide=grid.number_of_nodes,
        verbose_landslides=False)
    rate, exported = model.run_one_step(args["dt_years"])
    # Source lines 573..576 divide suspended yield by dt, despite the public
    # return description calling it volume. Preserve raw rate and convert once.
    suspended = float(rate) * args["dt_years"]
    final_soil = array(grid.at_node["soil__depth"], low=0)
    final_bed = array(grid.at_node["bedrock__elevation"])
    initial_bed = np.flipud(bed).ravel()
    initial_soil = np.flipud(soil).ravel()
    released = float(np.sum(initial_bed-final_bed +
                            (1-args["porosity"])*(initial_soil-final_soil)) * args["cell_size_m"]**2)
    residual = released - suspended - float(exported)
    if min(float(rate), float(exported)) < 0 or abs(residual) > 1e-8 * max(1.0, abs(released)):
        fail("Landslide solid-volume accounting failed", "upstream_failure")
    return finish(tool, dict(method="landlab.BedrockLandslider_prescribed_events",
                  grid=meta, bedrock_elevation_m=raster(grid,"bedrock__elevation"),
                  soil_depth_m=raster(grid,"soil__depth"), elevation_m=raster(grid,"topographic__elevation"),
                  erosion_m=raster(grid,"landslide__erosion"), deposition_m=raster(grid,"landslide__deposition"),
                  dt_years=args["dt_years"], suspended_rate_m3_year=float(rate),
                  suspended_volume_m3=suspended, exported_volume_m3=float(exported),
                  solid_volume_residual_m3=residual,
                  boundary="fixed_value_no_boundary_landslides",
                  routing="D8_DepressionFinderAndRouter_plus_separate_slope_weighted_MFD",
                  units={"elevation":"m", "time":"year", "volume":"m3_solid", "suspended_rate":"m3_solid/year"}))


def river_sediment_parcel_transport(args):
    tool = "GeoRiverSedimentParcelTransport"
    guard(tool, args)
    import numpy as np
    from landlab import NetworkModelGrid
    from landlab.data_record import DataRecord
    from landlab.components import FlowDirectorSteepest, NetworkSedimentTransporter
    crs(args["crs"])
    xy = array(args["nodes_xy_m"])
    bed = array(args["bedrock_elevation_m"], shape=(len(xy),))
    links = np.asarray(args["links"], dtype=int)
    if xy.ndim != 2 or xy.shape[1] != 2 or len({tuple(p) for p in xy}) != len(xy):
        fail("Distinct XY nodes are required")
    if links.shape != (len(xy)-1,2) or np.any(links < 0) or np.any(links >= len(xy)):
        fail("A bounded connected tree is required")
    pairs = [frozenset(pair) for pair in links.tolist()]
    if any(len(p) != 2 for p in pairs) or len(set(pairs)) != len(pairs):
        fail("Self/duplicate links are forbidden")
    adjacency = [set() for _ in xy]
    for u,v in links:
        adjacency[u].add(int(v)); adjacency[v].add(int(u))
    outlet = args["outlet_node"]
    if outlet >= len(xy):
        fail("Invalid outlet node")
    visited, queue = {outlet}, [outlet]
    while queue:
        for v in adjacency[queue.pop()]:
            if v not in visited:
                visited.add(v); queue.append(v)
    if len(visited) != len(xy):
        fail("Disconnected network")
    for i in range(len(xy)):
        lower = [j for j in adjacency[i] if bed[j] < bed[i]]
        if len(lower) != (0 if i == outlet else 1):
            fail("Bedrock must define one strictly downhill receiver per non-outlet node")
    nmg = NetworkModelGrid((xy[:,1], xy[:,0]), links, xy_axis_units="m")
    lookup = {tuple(point):i for i,point in enumerate(xy.tolist())}
    node_old = np.asarray([lookup[(float(x),float(y))] for x,y in zip(nmg.x_of_node,nmg.y_of_node)])
    node_new = np.argsort(node_old)
    edge_lookup = {p:i for i,p in enumerate(pairs)}
    link_old = np.asarray([edge_lookup[frozenset(node_old[pair].tolist())] for pair in nmg.nodes_at_link])
    link_new = np.argsort(link_old)
    nmg.status_at_node[node_new[outlet]] = nmg.BC_NODE_IS_FIXED_VALUE
    nmg.add_field("bedrock__elevation",bed[node_old].copy(),at="node")
    nmg.add_field("topographic__elevation",bed[node_old].copy(),at="node")
    for key, field in (("reach_length_m","reach_length"),("channel_width_m","channel_width"),("flow_depth_m","flow_depth")):
        values = array(args[key], shape=(len(links),), low=0)
        if key != "flow_depth_m" and np.any(values <= 0):
            fail("Reach dimensions must be positive")
        if key == "reach_length_m" and np.any(values < np.linalg.norm(xy[links[:,0]]-xy[links[:,1]],axis=1)):
            fail("Reach length cannot be shorter than endpoint distance")
        nmg.add_field(field,values[link_old].copy(),at="link")
    director = FlowDirectorSteepest(nmg)
    director.run_one_step()
    parcels = args["parcels"]
    if any(p["link"] >= len(links) or p["density_kg_m3"] <= args["fluid_density_kg_m3"] for p in parcels):
        fail("Invalid parcel link or buoyant sediment density")
    ids = np.asarray([link_new[p["link"]] for p in parcels],dtype=int)
    static = {"starting_link":ids,"abrasion_rate":np.asarray([p["abrasion_m_inverse"] for p in parcels]),
              "density":np.asarray([p["density_kg_m3"] for p in parcels])}
    dynamic = {"time_arrival_in_link":np.zeros(len(parcels)),"active_layer":np.ones(len(parcels)),
               "location_in_link":np.asarray([p["location_fraction"] for p in parcels]),
               "D":np.asarray([p["diameter_m"] for p in parcels]),
               "volume":np.asarray([p["volume_m3"] for p in parcels])}
    variables = {key:(["item_id"],val) for key,val in static.items()}
    variables.update({key:(["item_id","time"],val[:,None]) for key,val in dynamic.items()})
    record = DataRecord(nmg,items={"grid_element":"link","element_id":ids[:,None]},time=[0.0],
                        data_vars=variables,dummy_elements={"link":[NetworkSedimentTransporter.OUT_OF_NETWORK]})
    model = NetworkSedimentTransporter(nmg,record,director,bed_porosity=args["porosity"],
                   fluid_density=args["fluid_density_kg_m3"],transport_method="WilcockCrowe",
                   active_layer_method="Constant10cm",slope_threshold=args["minimum_slope"],g=9.80665)
    initial_mass = float(np.dot(dynamic["volume"],static["density"]))
    history = []
    def snapshot():
        ds = record.dataset
        current = np.asarray(ds.element_id.values[:,-1],dtype=int)
        outside = current == model.OUT_OF_NETWORK
        volumes = array(ds.volume.values[:,-1], low=0)
        diameters = array(ds.D.values[:,-1], low=0)
        masses = volumes * static["density"]
        locations = ds.location_in_link.values[:,-1]
        rows = []
        for i in range(len(parcels)):
            if not outside[i] and (not 0 <= current[i] < len(links) or not np.isfinite(locations[i]) or not 0 <= locations[i] <= 1):
                fail("Invalid parcel state", "upstream_failure")
            rows.append(dict(link=None if outside[i] else int(link_old[current[i]]),
                location_fraction=None if outside[i] else float(locations[i]),
                diameter_m=float(diameters[i]),volume_m3=float(volumes[i]),
                active=bool(ds.active_layer.values[i,-1]),exported=bool(outside[i])))
        loss = initial_mass-float(masses.sum())
        if loss < -1e-10*max(1,initial_mass):
            fail("Parcel mass increased without a source", "upstream_failure")
        history.append(dict(time_s=float(model.time),parcels=rows,
               retained_mass_kg=float(masses[~outside].sum()),exported_mass_kg=float(masses[outside].sum()),
               abrasion_loss_kg=loss,
               elevation_m=array(nmg.at_node["topographic__elevation"])[node_new].tolist()))
        return bool(outside.all())
    finished = snapshot()
    for dt in args["steps_s"]:
        if finished:
            break
        model.run_one_step(dt)
        finished = snapshot()
    return finish(tool,dict(method="landlab.NetworkSedimentTransporter_WilcockCrowe",crs=args["crs"],
        history=history,initial_mass_kg=initial_mass,requested_duration_s=sum(args["steps_s"]),
        actual_duration_s=float(model.time),termination="all_parcels_exported" if finished else "requested_steps_completed",
        routing="fixed_initial_downhill_tree",active_layer="Constant10cm",
        units={"coordinates":"m","time":"s","mass":"kg","volume":"m3","diameter":"m"}))

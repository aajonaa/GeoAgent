"""Fixed GRASS session leaf. Invoked only by the reviewed private worker."""
import json
from pathlib import Path
import sys


def main():
    import grass.script as gs
    work=Path(sys.argv[1]).resolve()
    request=json.loads((work/"request.json").read_text(encoding="utf-8"))
    tool,args=request["tool"],request["args"]
    if tool not in {"GeoSpatialTerrainViewshed","GeoSpatialGeomorphonLandforms","GeoSpatialTerrainSolarIrradiance"}:
        raise ValueError("No such fixed GRASS leaf")
    gs.run_command("r.in.ascii",input=str(work/"input.asc"),output="elevation",
                   type="FCELL" if tool=="GeoSpatialTerrainSolarIrradiance" else "DCELL",quiet=True)
    gs.run_command("g.region",raster="elevation",quiet=True)
    if tool=="GeoSpatialTerrainSolarIrradiance":
        gs.run_command("r.in.ascii",input=str(work/"solar-slope.asc"),output="slope",type="FCELL",quiet=True)
        gs.run_command("r.in.ascii",input=str(work/"solar-aspect.asc"),output="aspect",type="FCELL",quiet=True)
        gs.run_command("r.sun",elevation="elevation",slope="slope",aspect="aspect",
              day=args["day_of_year"],time=args["local_solar_time_h"],linke_value=args["linke_turbidity"],
              albedo_value=args["albedo"],solar_constant=1367.0,distance_step=1.0,nprocs=1,
              beam_rad="beam",diff_rad="diffuse",refl_rad="reflected",glob_rad="global",quiet=True)
        for name in ("beam","diffuse","reflected","global"):
            gs.run_command("r.out.ascii",input=name,output=str(work/(name+".asc")),precision=17,null_value="*",quiet=True)
        return
    if tool=="GeoSpatialTerrainViewshed":
        r,c=args["observer_cell"]; x,y=args["origin_xy_m"]; d=args["cell_size_m"]
        gs.run_command("r.viewshed",input="elevation",output="result",flags="b",
              coordinates=(x+(c+.5)*d,y-(r+.5)*d),observer_elevation=args["observer_height_m"],
              target_elevation=args["target_height_m"],memory=128,directory=str(work),quiet=True)
    else:
        gs.run_command("r.geomorphon",elevation="elevation",forms="result",search=args["search_cells"],
              skip=args["skip_cells"],flat=args["flat_angle_deg"],dist=0,comparison="anglev1",quiet=True)
    gs.run_command("r.out.ascii",input="result",output=str(work/"result.asc"),precision=17,null_value="*",quiet=True)


if __name__=="__main__":
    main()

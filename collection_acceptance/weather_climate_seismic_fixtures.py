"""Generate explicitly synthetic, offline fixtures; never overwrite inputs."""
import json
from pathlib import Path

PAYLOADS = json.loads(r'''{"synthetic_wrf":{"shape":[2,3],"values":[0,2,4,10,12,14],"synthetic":true,"fixture_id":"synthetic_wrf"},"synthetic_rainymotion":{"observed_mm_h":[0,2,3,0],"forecast_mm_h":[0,1,0,4],"synthetic":true,"fixture_id":"synthetic_rainymotion"},"synthetic_metsim":{"shortwave_w_m2":[0,200,200],"temperature_degC":[20,20,20],"daylength_s":[43200,0,43200],"synthetic":true,"fixture_id":"synthetic_metsim"},"synthetic_melodist":{"daily_precipitation_mm":[24,48],"synthetic":true,"fixture_id":"synthetic_melodist"},"synthetic_improver":{"values":[-5,0,5,10,15],"synthetic":true,"fixture_id":"synthetic_improver"},"synthetic_skdownscale":{"historical_model":[0,1,2,3,4],"historical_observed":[10,12,14,16,18],"future_model":[-1,0,1.5,4,6],"synthetic":true,"fixture_id":"synthetic_skdownscale"},"synthetic_jams":{"vapour_pressure_pa":[611.21,1222.42],"synthetic":true,"fixture_id":"synthetic_jams"},"synthetic_xgcm":{"values":[0,2,6,12],"synthetic":true,"fixture_id":"synthetic_xgcm"},"synthetic_climpred":{"forecast":[[0,2],[2,4],[4,6]],"observed":[1,3,5],"synthetic":true,"fixture_id":"synthetic_climpred"},"synthetic_climlab":{"thickness":[1,10,100],"synthetic":true,"fixture_id":"synthetic_climlab"},"synthetic_aospy":{"sigma_b":[0,0.5,1],"pressure_a_pa":[0,0,0],"surface_pressure_pa":[100000,90000],"synthetic":true,"fixture_id":"synthetic_aospy"},"synthetic_oocgcm":{"potential_temperature_degC":[0,15],"salinity_psu":[35,33],"synthetic":true,"fixture_id":"synthetic_oocgcm"},"synthetic_ocgis":{"temperature_degF":[90,75,90],"relative_humidity_percent":[70,70,30],"synthetic":true,"fixture_id":"synthetic_ocgis"},"synthetic_pyrocko":{"strike_deg":0,"dip_deg":90,"rake_deg":0,"scalar_moment_nm":1000000000000000,"synthetic":true,"fixture_id":"synthetic_pyrocko"},"synthetic_rsudp":{"samples":[-3,-1,1,3],"synthetic":true,"fixture_id":"synthetic_rsudp"},"synthetic_seismic_zfp":{"shape":[4,4,8],"values":[0,1,2,3,4,5,6,7,1,2,3,4,5,6,7,8,2,3,4,5,6,7,8,9,3,4,5,6,7,8,9,10,1,2,3,4,5,6,7,8,2,3,4,5,6,7,8,9,3,4,5,6,7,8,9,10,4,5,6,7,8,9,10,11,2,3,4,5,6,7,8,9,3,4,5,6,7,8,9,10,4,5,6,7,8,9,10,11,5,6,7,8,9,10,11,12,3,4,5,6,7,8,9,10,4,5,6,7,8,9,10,11,5,6,7,8,9,10,11,12,6,7,8,9,10,11,12,13],"synthetic":true,"fixture_id":"synthetic_seismic_zfp"}}''')


BAD_PAYLOADS = json.loads(r'''{"synthetic_bad_wrf_axis":{"shape":[1],"values":[0]},"synthetic_bad_rainymotion_lengths":{"observed_mm_h":[1,2],"forecast_mm_h":[1]},"synthetic_bad_metsim_lengths":{"shortwave_w_m2":[200],"temperature_degC":[20,21],"daylength_s":[43200]},"synthetic_bad_melodist_count":{"daily_precipitation_mm":[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1]},"synthetic_bad_improver_count":{"values":[]},"synthetic_bad_skdownscale_count":{"historical_model":[0,1,2,3],"historical_observed":[1,2,3,4],"future_model":[1]},"synthetic_bad_jams_pressure":{"vapour_pressure_pa":[0]},"synthetic_bad_xgcm_count":{"values":[1]},"synthetic_bad_climpred_members":{"forecast":[[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1]],"observed":[1]},"synthetic_bad_climlab_thickness":{"thickness":[0]},"synthetic_bad_aospy_levels":{"sigma_b":[0,1,0.5],"pressure_a_pa":[0,0,0],"surface_pressure_pa":[100000]},"synthetic_bad_oocgcm_salinity":{"potential_temperature_degC":[15],"salinity_psu":[45]},"synthetic_bad_ocgis_humidity":{"temperature_degF":[90],"relative_humidity_percent":[101]},"synthetic_bad_pyrocko_moment":{"strike_deg":0,"dip_deg":90,"rake_deg":0,"scalar_moment_nm":-1},"synthetic_bad_rsudp_count":{"samples":[]},"synthetic_bad_seismic_shape":{"shape":[3,4,8],"values":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]}}''')

def create(root: Path):
    directory = Path(root) / "assets" / "earth-collection" / "weather_climate_seismic"
    directory.mkdir(parents=True, exist_ok=True)
    generated = []
    for name, payload in PAYLOADS.items():
        path = directory / (name + ".json")
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n")
        generated.append(path)
    for name, payload in BAD_PAYLOADS.items():
        with (directory / (name + ".json")).open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, sort_keys=True, allow_nan=False) + "\n")
    bad = {
        "synthetic_bad_json.json": '{"broken":',
        "synthetic_bad_duplicate.json": '{"values":[1],"values":[2]}',
        "synthetic_bad_nonfinite.json": '{"values":[NaN]}',
        "synthetic_bad_shape.json": '{"shape":[512,512,512],"values":[0]}',
        "synthetic_bad_empty.json": '{}',
        "synthetic_bad_utf8.json": b"\xff",
    }
    for name, content in bad.items():
        with (directory / name).open("xb") as handle:
            handle.write(content if isinstance(content, bytes) else content.encode("utf-8"))
    with (directory / "synthetic_bad_too_large.json").open("xb") as handle:
        handle.write(b" " * (8 * 1024 * 1024 + 1))
    with (directory / "README.txt").open("x", encoding="ascii") as handle:
        handle.write("All files here are generated SYNTHETIC acceptance data, not observations.\n")
        handle.write("No external sources, real stations, model weights, or services are used.\n")
    return generated

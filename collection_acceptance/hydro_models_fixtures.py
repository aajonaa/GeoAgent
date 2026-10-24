from pathlib import Path
from .hydro_models_fixtures_baseline import *
from .hydro_models_fixtures_baseline import create as baseline_create
PAYLOADS={'assets/earth-collection/hydro_cpu_profiles/pyflo_curve_number_runoff.json': b'{"rainfall_inches":[0.0,1.0,2.0],"synthetic":true}\n', 'assets/earth-collection/hydro_cpu_profiles/pysteps_precipitation_advection.json': b'{"east_velocity_pixels_step":[[1.0,1.0,1.0,1.0,1.0],[1.0,1.0,1.0,1.0,1.0],[1.0,1.0,1.0,1.0,1.0]],"precipitation_mm_hour":[[0.0,0.0,0.0,0.0,0.0],[0.0,0.0,8.0,0.0,0.0],[0.0,0.0,0.0,0.0,0.0]],"south_velocity_pixels_step":[[0.0,0.0,0.0,0.0,0.0],[0.0,0.0,0.0,0.0,0.0],[0.0,0.0,0.0,0.0,0.0]],"synthetic":true}\n', 'assets/earth-collection/hydro_cpu_profiles/catchmod_linear_store_step.json': b'{"synthetic": true, "initial_outflow_mm_day": [1.0, 3.0, 0.5], "inflow_mm_day": [10.0, 0.0, 0.5]}', 'assets/earth-collection/hydro_cpu_profiles/superflex_unit_hydrograph.json': b'{"effective_rainfall_mm_step":[10.0,0.0,0.0,0.0],"synthetic":true}\n', 'assets/earth-collection/hydro_cpu_profiles/hydpy_flow_scores.json': b'{"observed_m3_s":[1.0,2.0,3.0,4.0],"simulated_m3_s":[2.0,4.0,6.0,8.0],"synthetic":true}\n', 'assets/earth-collection/hydro_cpu_profiles/pydem_terrain_derivatives.json': b'{"elevation_m":[[14.0,13.0,12.0,11.0,10.0],[14.0,13.0,12.0,11.0,10.0],[14.0,13.0,12.0,11.0,10.0],[14.0,13.0,12.0,11.0,10.0],[14.0,13.0,12.0,11.0,10.0]],"synthetic":true}\n'}
def create(root):
    baseline_create(root)
    for name,raw in PAYLOADS.items():
        p=Path(root)/name
        p.parent.mkdir(parents=True,exist_ok=True)
        if p.exists():
            assert p.read_bytes()==raw
        else:
            with p.open("xb") as f:f.write(raw)

import json
from pathlib import Path

EXAMPLES = {'EarthWflowKinematicWaveReachStep': {'upstream_inflow_m3_s': 2, 'previous_outflow_m3_s': 1, 'lateral_inflow_m2_s': 0.0005, 'alpha': 0.02, 'beta': 1, 'timestep_seconds': 60, 'reach_length_m': 100}}

def prepare(task_root):
    target = Path(task_root) / 'assets/earth-collection/wflow43/synthetic-si-example.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as stream:
        json.dump({'data_kind': 'synthetic_analytic_fixture_not_real_catchment_data', 'operations': EXAMPLES}, stream, allow_nan=False)
    return EXAMPLES

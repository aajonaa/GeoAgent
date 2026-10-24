"""Parent can merge these numerical/content checks without changing old assertions."""
import copy
import hashlib
import json
from pathlib import Path


ASSET_PREFIX = 'assets/earth-collection/native_hydro'


def create(root):
    directory = Path(root) / ASSET_PREFIX
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'synthetic_catchmod_linear.json'
    with path.open('x', encoding='utf-8') as out:
        json.dump({'synthetic': True, 'initial_outflow_mm_day': [1., 3., 0.5],
                   'inflow_mm_day': [10., 0., 0.5]}, out)
    return [ASSET_PREFIX + '/' + path.name]


def check(name, result, args, output_dir=None):
    if name != 'EarthCatchmodLinearStoreStep':
        raise ValueError('Unknown native_hydro operation')
    import numpy as np
    from scipy.integrate import solve_ivp
    source = json.loads(Path(args['data_path']).read_text(encoding='utf-8'))
    initial = np.array(source['initial_outflow_mm_day'])
    inflow = np.array(source['inflow_mm_day'])
    constant = args['linear_storage_days']
    assert result['scenario_count'] == len(initial)
    for i in range(len(initial)):
        def rhs(t, y):
            return [inflow[i] - y[0]/constant, y[0]/constant]
        solution = solve_ivp(rhs, (0., 1.), [constant*initial[i], 0.], rtol=2e-12, atol=1e-12)
        assert solution.success
        np.testing.assert_allclose(result['mean_outflow_mm_day'][i], solution.y[1,-1], rtol=1e-8, atol=1e-10)
        np.testing.assert_allclose(result['end_outflow_mm_day'][i], solution.y[0,-1]/constant, rtol=1e-8, atol=1e-10)
    np.testing.assert_allclose(result['initial_storage_mm'], initial*constant, rtol=1e-12)
    np.testing.assert_allclose(result['final_storage_mm'], np.array(result['end_outflow_mm_day'])*constant, rtol=1e-12)
    residual = initial*constant+inflow-np.array(result['mean_outflow_mm_day'])-np.array(result['final_storage_mm'])
    np.testing.assert_allclose(result['mass_balance_residual_mm'], residual, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(residual, 0., atol=1e-10)
    assert result['units'] == {'mean_outflow_mm_day':'mm/day', 'end_outflow_mm_day':'mm/day',
                               'initial_storage_mm':'mm', 'final_storage_mm':'mm',
                               'mass_balance_residual_mm':'mm', 'scenario_count':'scenarios'}


def immutable_case(invoke, args):
    path = Path(args['data_path'])
    before = hashlib.sha256(path.read_bytes()).digest()
    original = copy.deepcopy(args)
    result = invoke('EarthCatchmodLinearStoreStep', args, None)
    assert args == original
    assert hashlib.sha256(path.read_bytes()).digest() == before
    check('EarthCatchmodLinearStoreStep', result, args)
    return result


import hashlib,json,math
KEYS = ('upstream_inflow_m3_s', 'previous_outflow_m3_s', 'lateral_inflow_m2_s', 'alpha', 'beta', 'timestep_seconds', 'reach_length_m')
PINS = {'numba': '0.68.0', 'numpy': '2.1.3', 'llvmlite': '0.50.0', 'jsonschema': '4.25.1', 'pydantic': '2.13.5', 'typing-extensions': '4.16.0', 'langgraph': '1.2.12'}
UNITS = {'outflow_m3_s': 'm3/s', 'previous_area_m2': 'm2', 'new_area_m2': 'm2', 'previous_storage_m3': 'm3', 'new_storage_m3': 'm3', 'upstream_volume_m3': 'm3', 'lateral_volume_m3': 'm3', 'outflow_volume_m3': 'm3', 'continuity_residual_m3': 'm3', 'continuity_tolerance_m3': 'm3', 'alpha': 'm^(2-3*beta) s^beta', 'beta': '1', 'timestep_seconds': 's', 'reach_length_m': 'm', 'lateral_inflow_m2_s': 'm2/s', 'upstream_inflow_m3_s': 'm3/s', 'previous_outflow_m3_s': 'm3/s'}

def oracle(args):
    qi, qo, q, alpha, beta, dt, dx = (float(args[k]) for k in KEYS)
    if qi + qo + q == 0:
        return 0.0
    if beta == 1:
        return ((dt / dx) * qi + alpha * qo + dt * q) / ((dt / dx) + alpha)
    target = dt / dx * qi + alpha * qo ** beta + dt * q
    lo, hi = 0.0, max(qo, qi + q * dx, 1e-30)
    for _ in range(180):
        mid = (lo + hi) / 2
        if dt / dx * mid + alpha * mid ** beta < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2

def check(name, result, args, output_dir=None):
    assert name == 'EarthWflowKinematicWaveReachStep'
    qi,qo,q,a,b,dt,dx = (float(args[k]) for k in KEYS)
    out = result['outflow_m3_s']
    assert math.isclose(out, oracle(args), rel_tol=1e-9, abs_tol=1e-10)
    residual = dx*a*(out**b-qo**b)+dt*(out-qi-q*dx)
    tolerance = max(1e-12*dx, 1e-10*max(1.,abs(dx*a*qo**b)+abs(qi*dt)+abs(q*dx*dt),abs(dx*a*out**b)+abs(out*dt)))
    assert abs(residual) <= tolerance
    assert math.isclose(result['continuity_tolerance_m3'], tolerance, rel_tol=1e-14)
    assert result['units'] == UNITS and result['alpha_units'] == 'm^(2-3*beta) s^beta'
    assert result['artifacts'] == [] and result['provenance']['output_sha256'] == {}
    assert result['provenance']['installed_versions'] == PINS
    assert result['provenance']['source_mode'] == 'vendored_source'
    assert result['provenance']['input_sha256'] == hashlib.sha256(json.dumps(args,sort_keys=True,ensure_ascii=True,allow_nan=False).encode()).hexdigest()

"""Independent synthetic references: rational circular convolution, no SciPy/PyLops."""
from fractions import Fraction as Q


def marchenko_reference():
    # dt=dr=1, one collocated trace, nt=8, direct impulse at t=3.
    # Two different reflection lags force a NONZERO downgoing coda.
    nt, travel, a, b = 8, 3, Q(1, 4), Q(1, 8)
    n, center = 2 * nt - 1, nt - 1
    active = list(range(center - travel + 1, center + travel))
    fd = [Q(0)] * n
    fd[center - travel] = Q(1)
    def reflection(v):
        return [a * v[(i - 1) % n] + b * v[(i - 2) % n] for i in range(n)]
    def correlation(v):
        return [a * v[(i + 1) % n] + b * v[(i + 2) % n] for i in range(n)]
    rfd = reflection(fd)
    k = len(active)
    rows = []
    for block in range(2):
        for i in active:
            row = []
            for colblock in range(2):
                for j in active:
                    if block == colblock:
                        value = Q(int(i == j))
                    else:
                        basis = [Q(0)] * n
                        basis[j] = Q(1)
                        value = -(reflection(basis)[i] if block == 0 else correlation(basis)[i])
                    row.append(value)
            rows.append(row + [rfd[i] if block == 0 else Q(0)])
    # Exact rational elimination of the tiny independent coupled system.
    for column in range(2 * k):
        pivot = next(i for i in range(column, 2 * k) if rows[i][column] != 0)
        rows[column], rows[pivot] = rows[pivot], rows[column]
        scale = rows[column][column]
        rows[column] = [v / scale for v in rows[column]]
        for i in range(2 * k):
            if i != column:
                scale = rows[i][column]
                rows[i] = [v - scale * p for v, p in zip(rows[i], rows[column])]
    fm, coda = [Q(0)] * n, [Q(0)] * n
    for i, sample in enumerate(active):
        fm[sample], coda[sample] = rows[i][-1], rows[k + i][-1]
    fp = [f + c for f, c in zip(fd, coda)]
    gm = [r - f for r, f in zip(reflection(fp), fm)]
    gp = list(reversed([f - c for f, c in zip(fp, correlation(fm))]))
    for i in active:
        assert fm[i] == reflection(fp)[i]
        assert coda[i] == correlation(fm)[i]
    direct = [0.0] * nt
    direct[travel] = 1.0
    response = [0.0, float(a), float(b)] + [0.0] * (nt - 3)
    args = {"reflection_response": [[response]], "direct_arrival": [direct],
            "traveltime_s": [3.0], "dt_s": 1.0, "receiver_spacing_m": 1.0,
            "max_iterations": 100,
            "reflection_convention": "twice_monopole_vertical_velocity_density"}
    return args, {
        "focusing_upgoing": [fm], "focusing_downgoing": [fp],
        "green_upgoing": [gm], "green_downgoing": [gp]}, coda


def crosshole_reference():
    # Synthetic flat interface at elevation -20 m. A 20 m horizontal ray
    # entirely within either layer has exact t=distance/velocity. Slow-layer
    # sensors are >=10 m below the faster layer, so a detour cannot beat the
    # direct 20/2000 s path. No upstream forward model supplies these times.
    levels = [-35.0, -30.0, -10.0, -5.0]
    times = [20.0 / 2000.0, 20.0 / 2000.0, 20.0 / 3000.0, 20.0 / 3000.0]
    return {
        "x_nodes_m": [0.0, 10.0, 20.0],
        "elevation_nodes_m": [-40.0, -35.0, -30.0, -20.0, -10.0, -5.0, 0.0],
        "sensors_x_elevation_m": [[0.0, y] for y in levels] + [[20.0, y] for y in levels],
        "source_indices": [0, 1, 2, 3], "receiver_indices": [4, 5, 6, 7],
        "traveltime_s": times, "uncertainty_s": [1e-5] * 4,
        "initial_velocity_m_s": 2500.0, "velocity_bounds_m_s": [1000.0, 4000.0],
        "regularization": 1e-4, "max_iterations": 20,
    }


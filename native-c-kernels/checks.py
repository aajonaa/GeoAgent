"""Independent numerical oracles, only imported by tests/preparation."""
import cmath
import math


def dft(samples):
    n = len(samples)
    return [sum(x*cmath.exp(-2j*math.pi*k*t/n) for t, x in enumerate(samples)) for k in range(n)]


def directional_semivariogram(args):
    # Independent pair enumeration of the documented cylindrical search,
    # not imported by adapters or the fixed runtime entrypoint.
    axes = "xyz"
    primary = axes.index(args.get("axis", "x"))
    points = list(zip(args["x_m"], args["y_m"], args["z_m"]))
    result = []
    for lag in range(args["lag_count"]):
        center = args["first_lag_m"]+lag*args["lag_separation_m"]
        differences = []
        for i, first in enumerate(points):
            for j, second in enumerate(points):
                delta = [first[k]-second[k] for k in range(3)]
                transverse = math.sqrt(sum(delta[k]**2 for k in range(3) if k != primary))
                distance = math.sqrt(sum(x*x for x in delta))
                if delta[primary] >= 0 and transverse <= args["bandwidth_m"] and center-args["lag_width_m"]/2 <= distance < center+args["lag_width_m"]/2:
                    differences.append((args["values"][i]-args["values"][j])**2)
        result.append(sum(differences)/(2*len(differences)) if differences else 0.0)
    return result


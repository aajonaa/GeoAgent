"""Explicit synthetic acceptance fixtures, never geological observations."""
import math
from copy import deepcopy
from specs import SPECS, VIC, FFT, HPGL


def examples():
    return {name: deepcopy(spec["example_arguments"]) for name, spec in SPECS.items()}


def harmonic_trace(n=32, dt=0.01):
    return {"samples": [2+3*math.cos(2*math.pi*3*k/n)+0.5*math.sin(2*math.pi*5*k/n) for k in range(n)], "sampling_interval_s": dt, "amplitude_unit": "m/s"}


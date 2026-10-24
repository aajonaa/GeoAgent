"""Shared collection interface for the unchanged original Wflow reach kernel.

The hash-bound kernel and its original GPL source/license are retained in the
vendor package. This is not a complete Wflow/PCRaster or Wflow.jl installation.
"""
from .collection_contracts import operation
from .collection_vendor.approved_wflow43 import kernel_adapter as original_interface

UNITS = {
    "outflow_m3_s": "m3/s", "previous_area_m2": "m2", "new_area_m2": "m2",
    "previous_storage_m3": "m3", "new_storage_m3": "m3", "upstream_volume_m3": "m3",
    "lateral_volume_m3": "m3", "outflow_volume_m3": "m3", "continuity_residual_m3": "m3",
    "continuity_tolerance_m3": "m3", "alpha": "m^(2-3*beta) s^beta", "beta": "1",
    "timestep_seconds": "s", "reach_length_m": "m", "lateral_inflow_m2_s": "m2/s",
    "upstream_inflow_m3_s": "m3/s", "previous_outflow_m3_s": "m3/s",
}


@operation("EarthWflowKinematicWaveReachStep")
def reach_step(args):
    result = original_interface.reach_step(args=args)
    result["units"] = dict(UNITS)
    return result

"""Bounded original Wflow kernel prototype, NOT a collection-catalog integration.

The original GPL kernel and full source travel alongside this interface. No
Wflow/PCRaster installation, full catchment model or Wflow.jl equivalence is
claimed. The shared collection decorator/catalog gate remains pending.
"""
import hashlib
import importlib.metadata
import importlib.util
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = json.loads((HERE / "operation.json").read_text(encoding="utf-8"))
NAME = "EarthWflowKinematicWaveReachStep"
_BACKEND = None


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def get_backend():
    global _BACKEND
    for requirement in SPEC["metadata"]["upstream"]["requirements"]:
        name, version = requirement.split("==")
        if importlib.metadata.version(name) != version:
            raise ImportError("Exact CPU profile mismatch: " + requirement)
    for relative, sha in SPEC["source_receipt"]["files_sha256"].items():
        if digest(HERE / relative) != sha:
            raise ImportError("Original source/license hash mismatch: " + relative)
    if _BACKEND is None:
        path = HERE / "vendor/original_kinematic_wave.py"
        spec = importlib.util.spec_from_file_location("verified_wflow_kinematic", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _BACKEND = module.kinematic_wave
    return _BACKEND


def reach_step(args):
    from jsonschema import Draft202012Validator
    if isinstance(args, str):
        args = json.loads(args)
    Draft202012Validator(SPEC["input_schema"]).validate(args)
    for name, value in args.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(name + " must be a finite SI numeric value")
    before = json.dumps(args, sort_keys=True, separators=(",", ":"), allow_nan=False)
    qi = float(args["upstream_inflow_m3_s"])
    qo = float(args["previous_outflow_m3_s"])
    q = float(args["lateral_inflow_m2_s"])
    alpha = float(args["alpha"])
    beta = float(args["beta"])
    dt = float(args["timestep_seconds"])
    dx = float(args["reach_length_m"])
    if qi == 0 and qo == 0 and q > 0 and beta < 1:
        raise ValueError("Original beta<1 kernel cannot initialize a dry reach with positive lateral inflow")
    result = float(get_backend()(qi, qo, q, alpha, beta, dt, dx))
    if not math.isfinite(result) or result < 0:
        raise RuntimeError("Original kernel returned a nonfinite or negative flow")
    old_area = alpha * qo ** beta
    new_area = alpha * result ** beta
    old_volume = old_area * dx
    new_volume = new_area * dx
    upstream_volume = qi * dt
    lateral_volume = q * dx * dt
    outflow_volume = result * dt
    residual = new_volume + outflow_volume - old_volume - upstream_volume - lateral_volume
    scale = max(1.0, abs(old_volume) + abs(upstream_volume) + abs(lateral_volume),
                abs(new_volume) + abs(outflow_volume))
    tolerance = max(1e-12 * dx, 1e-10 * scale)
    if not math.isfinite(residual) or abs(residual) > tolerance:
        raise RuntimeError("Original kernel did not meet the declared finite-volume continuity tolerance")
    if json.dumps(args, sort_keys=True, separators=(",", ":"), allow_nan=False) != before:
        raise RuntimeError("Input arguments changed")
    return {
        "outflow_m3_s": result,
        "previous_area_m2": old_area,
        "new_area_m2": new_area,
        "previous_storage_m3": old_volume,
        "new_storage_m3": new_volume,
        "upstream_volume_m3": upstream_volume,
        "lateral_volume_m3": lateral_volume,
        "outflow_volume_m3": outflow_volume,
        "continuity_residual_m3": residual,
        "continuity_tolerance_m3": tolerance,
        "alpha_units": "m^(2-3*beta) s^beta",
        "beta_units": "1",
        "backend": "original Wflow kinematic_wave; original numba nopython CPU JIT retained",
        "artifacts": [],
        "provenance": {
            "upstream_url": SPEC["metadata"]["upstream"]["url"],
            "source_mode": "vendored_source",
            "installed_versions": {r.split("==")[0]: importlib.metadata.version(r.split("==")[0])
                                   for r in SPEC["metadata"]["upstream"]["requirements"]},
            "input_sha256": hashlib.sha256(before.encode()).hexdigest(),
            "output_sha256": {},
            "original_files_sha256": SPEC["source_receipt"]["files_sha256"],
            "adapter_sha256": digest(__file__),
            "collection_catalog_binding_accepted": False,
            "full_legacy_engine_installed": False,
        },
    }


def native_executor():
    """Real shared ToolExecutor, but explicit local registration, not canonical.

    This prototype intentionally does not bypass or claim to satisfy the pending
    collection SDK metadata gate. Its exact executing-interpreter dependencies
    are checked above; it has no remote worker, runtime installation or pin strip.
    """
    from jsonschema import ValidationError
    from geological_agent.tools import Tool, ToolDefinition, ToolExecutor, ToolFailure, ToolOutput, ToolRegistry

    def handler(args, context):
        try:
            return ToolOutput(reach_step(args=args))
        except (ValueError, TypeError, ValidationError) as exc:
            raise ToolFailure("invalid_arguments", str(exc), retryable=True) from exc
        except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
            raise ToolFailure("incompatible_dependency", str(exc)) from exc
        except RuntimeError as exc:
            raise ToolFailure("invalid_result", str(exc)) from exc

    registry = ToolRegistry()
    registry.register(Tool(ToolDefinition(NAME, SPEC["description"],
        "One SI implicit reach step; not a full basin model.", SPEC["input_schema"],
        SPEC["output_schema"]), handler, pure=True))
    return ToolExecutor(registry)

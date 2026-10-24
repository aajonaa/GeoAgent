"""No user callbacks: original PyGLUE + RRMPG ABC + SPOTPY NSE only."""
import math
from dataclasses import dataclass

from ...collection_contracts import operation, reject


class _LegacyArguments(dict):
    """Transport-only Python-2 mapping compatibility; no algorithm edits."""
    def copy(self):
        return _LegacyArguments(self)

    def iteritems(self):
        return self.items()


@dataclass(frozen=True)
class _FixedParameter:
    name: str
    value: float

    def get_value(self):
        return self.value


@operation("EarthPyGLUEABCEnsemble")
def pyglue_abc_ensemble(args):
    import numpy as np
    from .vendor.glue_evaluator import GLUEEvaluatorKernel
    from .vendor.rrmpg_abc import run_abcmodel
    from .vendor.spotpy_nse import nashsutcliffe
    rain = np.asarray(args["precipitation_mm"], dtype=np.float64)
    observed = np.asarray(args["observed_runoff_mm"], dtype=np.float64)
    if rain.ndim != 1 or observed.shape != rain.shape or not 4 <= len(rain) <= 512:
        reject("Supply equally sized 4 to 512 step precipitation and observed-runoff arrays")
    if not np.isfinite(rain).all() or not np.isfinite(observed).all() or (rain < 0).any() or (observed < 0).any():
        reject("All precipitation and observed runoff must be finite nonnegative depths")
    if rain[0] != 0 or observed[0] != 0:
        reject("Original ABC t=0 is an initial-state slot; both t=0 forcing and runoff placeholders must be zero")
    if float(np.var(observed[1:])) <= 1e-15:
        reject("NSE requires nonconstant actual observations after the initial-state slot")
    initial = float(args["initial_storage_mm"])
    threshold = float(args["minimum_nse"])
    if not math.isfinite(initial) or initial < 0 or not math.isfinite(threshold) or not -1000 <= threshold <= 1:
        reject("Initial storage and NSE threshold must satisfy their finite physical bounds")
    rows = args["parameter_sets"]
    if not 1 <= len(rows) <= 64:
        reject("Supply 1 to 64 fixed parameter sets; no runtime sampler or callback is accepted")
    seen = set()
    for row in rows:
        triple = tuple(float(row[key]) for key in ["a", "b", "c"])
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in triple) or triple[0] + triple[1] > 1:
            reject("Original ABC parameters require a,b,c in [0,1] and a+b<=1")
        if triple in seen:
            reject("Duplicate parameter sets are not distinct ensemble members")
        seen.add(triple)
    output, accepted = [], []
    dtype = np.dtype([("a", np.float64), ("b", np.float64), ("c", np.float64)])
    for run_id, row in enumerate(rows):
        proof = {}
        def fixed_model(a, b, c):
            parameters = np.array([(a, b, c)], dtype=dtype)[0]
            qsim, storage = run_abcmodel(rain.copy(), initial, parameters)
            if not np.isfinite(qsim).all() or not np.isfinite(storage).all():
                reject("Original ABC simulation returned non-finite values", "invalid_result")
            proof["qsim"], proof["storage"] = qsim.tolist(), storage.tolist()
            return {"observations": observed[1:].tolist(), "simulated": qsim[1:].tolist(), "minimum": threshold}

        def fixed_nse_rule(evaluation, simulation, minimum):
            score = float(nashsutcliffe(evaluation, simulation))
            if not math.isfinite(score):
                reject("Original SPOTPY NSE returned a non-finite score", "invalid_result")
            proof["nse"] = score
            return bool(score >= minimum)

        parameters = [_FixedParameter(key, float(row[key])) for key in ["a", "b", "c"]]
        arguments = _LegacyArguments(evaluation="observations", simulation="simulated", minimum="minimum")
        evaluator = GLUEEvaluatorKernel(model=fixed_model, GLUEparams=parameters, stdparams={}, rules=[fixed_nse_rule], ruleargs=[arguments], mp=False)
        evaluated = evaluator.run_and_evaluate(run_id)
        if evaluated[0] != run_id or evaluated[1] != {key: float(row[key]) for key in ["a", "b", "c"]} or set(proof) != {"qsim", "storage", "nse"}:
            reject("Original PyGLUE did not complete the fixed model and objective; a swallowed model error is not a valid non-behavioural run", "upstream_failure")
        behavioural = bool(evaluated[2])
        if behavioural != (proof["nse"] >= threshold):
            reject("Original evaluator and recorded NSE evidence disagree", "invalid_result")
        qsim, storage = proof["qsim"], proof["storage"]
        balance = float(rain[1:].sum()) - sum(qsim[1:]) - float(row["b"]) * float(rain[1:].sum()) - (storage[-1] - initial)
        output.append({"run_id": run_id, "parameters": {key: float(row[key]) for key in ["a", "b", "c"]}, "nse": proof["nse"], "behavioural": behavioural,
                       "runoff_mm": qsim, "storage_mm": storage, "water_balance_residual_mm": balance})
        if behavioural:
            accepted.append(run_id)
    return {"runs": output, "accepted_run_ids": accepted, "evaluated_count": len(output), "behavioural_count": len(accepted),
            "units": {"runoff_mm": "mm/step", "storage_mm": "mm", "water_balance_residual_mm": "mm", "nse": "dimensionless"},
            "scope": "Original PyGLUE evaluator with a fixed original RRMPG educational ABC model and SPOTPY NSE. User supplies the ensemble. No arbitrary model, callback, Monte Carlo sampler, pickle, confidence interval or posterior-probability claim.",
            "initial_state_semantics": "Original ABC t=0 stores initial state and zero runoff. NSE evaluates actual observation slots t>=1 only."}


"""Shared-probe oracle: six frozen oracles plus independent fixed PyGLUE maths."""
import math

from geological_agent.geology.collection_offline_originals.checks import check as original_check


def check(name, result, args, directory=None):
    if name != "EarthPyGLUEABCEnsemble":
        return original_check(name, result, args, directory)
    assert result["evaluated_count"] == len(args["parameter_sets"])
    observed = args["observed_runoff_mm"][1:]
    mean = sum(observed) / len(observed)
    accepted = []
    for index, (run, params) in enumerate(zip(result["runs"], args["parameter_sets"])):
        storage = args["initial_storage_mm"]
        expected_q, expected_s = [0], [storage]
        for rain in args["precipitation_mm"][1:]:
            expected_q.append((1 - params["a"] - params["b"]) * rain + params["c"] * storage)
            storage = (1 - params["c"]) * storage + params["a"] * rain
            expected_s.append(storage)
        assert run["run_id"] == index
        assert len(run["runoff_mm"]) == len(expected_q) and len(run["storage_mm"]) == len(expected_s)
        assert all(math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12) for actual, expected in zip(run["runoff_mm"], expected_q))
        assert all(math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12) for actual, expected in zip(run["storage_mm"], expected_s))
        score = 1 - sum((obs - sim) ** 2 for obs, sim in zip(observed, expected_q[1:])) / sum((obs - mean) ** 2 for obs in observed)
        assert math.isclose(run["nse"], score, rel_tol=1e-12, abs_tol=1e-12)
        assert run["behavioural"] == (score >= args["minimum_nse"])
        assert abs(run["water_balance_residual_mm"]) < 1e-10
        if run["behavioural"]:
            accepted.append(index)
    assert result["accepted_run_ids"] == accepted and result["behavioural_count"] == len(accepted)
    assert result["units"]["nse"] == "dimensionless" and result["units"]["storage_mm"] == "mm"
    assert result["artifacts"] == [] and result["provenance"]["output_sha256"] == {}


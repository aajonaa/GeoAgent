"""Deployment-controlled limits for the single-process task broker."""
import os


def _limit(name, default):
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{name} must be an integer from 1 to 200') from exc
    if not 1 <= value <= 200:
        raise ValueError(f'{name} must be an integer from 1 to 200')
    return value


def read_capacity():
    return {
        'max_active_runs': _limit('GEOTOOL_TEAM_MAX_ACTIVE_RUNS', 2),
        'model_slots': _limit('GEOTOOL_TEAM_MODEL_SLOTS', 2),
    }

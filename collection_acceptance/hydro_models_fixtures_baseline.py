"""Synthetic, deterministic fixtures. No field observations or external resources."""

import json
from pathlib import Path


ASSET_PREFIX = "assets/earth-collection/hydro_models"
PAYLOADS = {
    "synthetic_pet.json": {"synthetic": True, "temperature_c": [20., 10., -30.],
                           "temperature_range_c": [10., 4., 2.], "latitude_radians": [0., 0., 0.]},
    "synthetic_flow_scores.json": {"synthetic": True, "observed_m3_s": [1., 2., 3., 4.],
                                   "simulated_m3_s": [2., 4., 6., 8.]},
    "synthetic_abc.json": {"synthetic": True, "precipitation_mm_step": [99., 10., 0., 5.]},
    "synthetic_duration.json": {"synthetic": True, "discharge_m3_s": [4., 1., 4., 2.]},
    "synthetic_advection.json": {
        "synthetic": True, "precipitation_mm_hour": [[0., 0., 0., 0., 0.], [0., 0., 8., 0., 0.],
                                                      [0., 0., 0., 0., 0.]],
        "east_velocity_pixels_step": [[1.] * 5 for _ in range(3)],
        "south_velocity_pixels_step": [[0.] * 5 for _ in range(3)]},
    "synthetic_cmf.json": {"synthetic": True, "wetness": [0.25, 0.5, 0.75, 1.]},
    "synthetic_solar.json": {"synthetic": True, "latitude_degrees": [0., 0., 45.],
                            "julian_day": [1., 1., 172.], "hours_from_solar_noon": [0., 12., 0.]},
    "synthetic_dem.json": {"synthetic": True, "elevation_m": [[14., 13., 12., 11., 10.] for _ in range(5)]},
    "synthetic_exphydro.json": {"synthetic": True, "precipitation_mm_day": [2., 3., 4.],
                               "pet_mm_day": [2., 2., 2.], "temperature_c": [-2., 5., 10.],
                               "snow_storage_mm": [10., 10., 0.], "soil_storage_mm": [0., 50., 110.]},
    "synthetic_infiltration.json": {"synthetic": True, "rainfall_mm_hour": [2., 0., 100.]},
    "synthetic_routing.json": {"synthetic": True, "effective_rainfall_mm_step": [10., 0., 0., 0.]},
    "synthetic_ensemble.json": {"synthetic": True, "reference_m3_s": [10., 20., 30.],
                                "ensemble_m3_s": [[11., 22., 30.], [9., 18., 34.]]},
    "synthetic_curve_number.json": {"synthetic": True, "rainfall_inches": [0., 1., 2.]},
    "synthetic_bad_negative.json": {"synthetic": True, "precipitation_mm_step": [0., -1.]},
    "synthetic_bad_ragged.json": {"synthetic": True, "elevation_m": [[1., 2., 3.], [2.], [3., 4., 5.]]},
    "synthetic_bad_constant.json": {"synthetic": True, "observed_m3_s": [2., 2.], "simulated_m3_s": [1., 2.]},
    "synthetic_bad_unknown.json": {"synthetic": True, "rainfall_inches": [1.], "script": "disallowed"},
}
RAW_PAYLOADS = {
    "synthetic_bad_nonfinite.json": b'{"synthetic":true,"rainfall_inches":[NaN]}\n',
    "synthetic_bad_duplicate.json": b'{"rainfall_inches":[1],"rainfall_inches":[2]}\n',
    "synthetic_bad_oversize.json": b" " * 2_097_153,
}


def payload_bytes(name):
    if name in RAW_PAYLOADS:
        return RAW_PAYLOADS[name]
    return (json.dumps(PAYLOADS[name], sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def create(root: Path):
    """Create only beneath the declared asset prefix, preserving existing files."""
    root = Path(root).resolve()
    directory = root / ASSET_PREFIX
    # Refuse existing links or redirected parents rather than following them outside the asset tree.
    cursor = root
    for component in ASSET_PREFIX.split("/"):
        cursor = cursor / component
        if cursor.is_symlink() or (hasattr(cursor, "is_junction") and cursor.is_junction()):
            raise ValueError("Synthetic fixture parents must not be links")
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in (*PAYLOADS, *RAW_PAYLOADS):
        target = directory / name
        try:
            with target.open("xb") as stream:
                stream.write(payload_bytes(name))
        except FileExistsError:
            pass
        paths.append(f"{ASSET_PREFIX}/{name}")
    return paths

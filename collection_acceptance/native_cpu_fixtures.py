"""Explicit in-memory synthetic contract fixtures; no fake field observations."""
from copy import deepcopy
import json
from pathlib import Path


def create(root):
    catalog = json.loads((Path(root)/"catalog/registry.json").read_text(encoding="utf-8"))
    names = {"HydroVICPrecipitationPhase", "SeismicMadagascarFFT", "GeoHPGLDirectionalSemivariogram"}
    return {"kind": "explicit_synthetic_in_memory_acceptance", "files": [], "examples": {row["id"]: deepcopy(row["example_arguments"]) for row in catalog["tools"] if row["id"] in names}}


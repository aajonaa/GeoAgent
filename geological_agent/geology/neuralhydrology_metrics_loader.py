"""Load reviewed, unmodified NeuralHydrology metrics without its tester package.

No formulas are copied or substituted.  The release's metrics.py is executed
under a private module name so evaluation/__init__.py is never imported.
"""
from functools import lru_cache
import hashlib
from importlib import metadata, util
from pathlib import Path

RELEASE = "1.13.0"
METRICS_SHA256 = "f39476b72004894d3fbc2db6a8bdd23b13ddece2ad6e2fb2e7fdef8e37a4673b"


@lru_cache(maxsize=1)
def load_reviewed_metrics():
    distribution = metadata.distribution("neuralhydrology")
    if distribution.version != RELEASE:
        raise ImportError("NeuralHydrology metrics require reviewed release " + RELEASE)
    path = Path(distribution.locate_file("neuralhydrology/evaluation/metrics.py"))
    if path.is_symlink() or not path.is_file():
        raise ImportError("Reviewed NeuralHydrology metrics file is unavailable")
    if hashlib.sha256(path.read_bytes()).hexdigest() != METRICS_SHA256:
        raise ImportError("Reviewed NeuralHydrology metrics source hash mismatch")
    spec = util.spec_from_file_location("_geoagent_reviewed_neuralhydrology_metrics_1_13_0", path)
    if spec is None or spec.loader is None:
        raise ImportError("Reviewed NeuralHydrology metrics loader unavailable")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("kge", "nse", "mse", "rmse", "_mask_valid", "_validate_inputs"):
        if not callable(getattr(module, name, None)):
            raise ImportError("Reviewed NeuralHydrology metric function is missing: " + name)
    return module


"""Fixed HydroShare original-source worker, never a user script or installer."""
import os
import sys
from pathlib import Path


def main():
    assert os.environ.get("CUDA_VISIBLE_DEVICES") == "" and os.environ.get("NVIDIA_VISIBLE_DEVICES") == "none"
    assert os.environ.get("PROJ_NETWORK") == "OFF"
    work = Path.cwd().resolve()
    for name in ["MPLCONFIGDIR", "NUMBA_CACHE_DIR", "XDG_CACHE_HOME"]:
        assert Path(os.environ[name]).resolve().is_relative_to(work)
    for name in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "GDAL_NUM_THREADS", "NUMBA_NUM_THREADS"]:
        assert os.environ[name] == "1"
    import hashlib
    import importlib.metadata
    import importlib.util
    import json
    import socket
    packages = {name: importlib.metadata.version(name) for name in ["GDAL", "numpy"]}
    assert packages == {"GDAL": "3.13.3", "numpy": "2.2.6"}
    path = Path(sys.argv[1]).resolve(strict=True)
    assert path == work / "input.tif" and not path.is_symlink() and path.stat().st_size <= 2 * 1024 * 1024
    with path.open("rb") as stream:
        assert stream.read(4) in {b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"}
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    def no_network(*args, **kwargs):
        raise RuntimeError("Network is disabled for this fixed original-source worker")
    socket.socket.connect = no_network
    socket.create_connection = no_network
    from osgeo import gdal
    dataset = gdal.OpenEx(str(path), gdal.OF_RASTER | gdal.OF_READONLY, allowed_drivers=["GTiff"])
    assert dataset is not None and dataset.RasterXSize * dataset.RasterYSize * dataset.RasterCount <= 262144
    dataset = None
    source = Path(__file__).with_name("vendor") / "hydroshare_kernel.py"
    spec = importlib.util.spec_from_file_location("fixed_hydroshare_original_kernel", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bands = module.get_band_info(str(path))
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    assert before == after and not list(work.glob("*.aux.xml"))
    result = {"bands": bands, "input_sha256_before": before, "input_sha256_after": after,
              "native_environment": {"packages": packages, "python": sys.executable, "kernel_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                                     "worker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "gdal_version": gdal.VersionInfo("--version"),
                                     "gpu_used": False, "runtime_installation": False, "network_used": False}}
    print(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())


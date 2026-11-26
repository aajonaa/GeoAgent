"""Clearly synthetic fixtures in the isolated candidate only, never live data."""
import json
import os
from pathlib import Path


def pytest_configure(config):
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "" or os.environ.get("NVIDIA_VISIBLE_DEVICES") != "none":
        raise RuntimeError("This acceptance must disable every GPU")
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from obspy import Stream, Trace, UTCDateTime
    root = Path(os.environ["EARTH_WAVE1_CANDIDATE"])
    fixtures = root / "assets" / "earth-python-wave1"
    fixtures.mkdir(parents=True, exist_ok=True)
    for name in ("points.geojson", "raster.tif", "waveform.mseed"):
        if (fixtures / name).exists():
            raise RuntimeError("Refusing to replace an existing fixture: " + name)
    (fixtures / "points.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"label": "SYNTHETIC CONTRACT FIXTURE"}, "geometry": {"type": "Point", "coordinates": [0, 0]}},
        {"type": "Feature", "properties": {"label": "SYNTHETIC CONTRACT FIXTURE"}, "geometry": {"type": "Point", "coordinates": [1, 1]}}
    ]}), encoding="utf-8")
    data = np.arange(16, dtype="float32").reshape(4, 4)
    data[0, 0] = -9999
    with rasterio.open(fixtures / "raster.tif", "w", driver="GTiff", width=4, height=4, count=1,
                       dtype="float32", crs="EPSG:3857", transform=from_origin(0, 40, 10, 10), nodata=-9999) as output:
        output.write(data, 1)
        output.update_tags(description="SYNTHETIC CONTRACT FIXTURE; NOT RESEARCH OBSERVATIONS")
    time = np.arange(4000) / 100
    trace = Trace(np.asarray(np.sin(2 * np.pi * time) + 0.5 * np.sin(20 * np.pi * time), dtype="float64"))
    trace.stats.update({"network": "XX", "station": "SYNTH", "channel": "BHZ", "sampling_rate": 100,
                        "starttime": UTCDateTime("2020-01-01T00:00:00Z")})
    Stream([trace]).write(str(fixtures / "waveform.mseed"), format="MSEED", encoding="FLOAT64")
    (fixtures / "EARTH_WAVE1_SYNTHETIC.txt").write_text(
        "points.geojson, raster.tif and waveform.mseed are synthetic interface/numerical fixtures, not real survey data.\n", encoding="utf-8")

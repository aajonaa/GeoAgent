"""Explicitly synthetic, deterministic CPU acceptance inputs, never real research data."""
from pathlib import Path


def create(root):
    import numpy as np
    import pandas as pd
    import rasterio
    from rasterio.transform import from_origin
    import xarray as xr
    target = Path(root) / "assets" / "offline-originals"
    target.mkdir(parents=True, exist_ok=False)
    values = np.arange(25, dtype="float32").reshape(5, 5)
    for filename, crs in [("projected.tif", "EPSG:32650"), ("geographic.tif", "EPSG:4326")]:
        with rasterio.open(target / filename, "w", driver="GTiff", width=5, height=5, count=1, dtype="float32", crs=crs, transform=from_origin(0, 5, 1, 1), nodata=-9999) as output:
            output.write(values, 1)
            output.set_band_unit(1, "m")
            output.update_tags(SYNTHETIC_ACCEPTANCE_FIXTURE="not research data")
    times = pd.date_range("2020-01-01", periods=24, freq="MS")
    monthly = np.arange(24 * 2 * 2, dtype=float).reshape(24, 2, 2) + 270
    dataset = xr.Dataset({"t2m": (("time", "latitude", "longitude"), monthly, {"units": "K"})},
                         coords={"time": times, "latitude": [39.9, 40.0], "longitude": [116.4, 116.5]}, attrs={"fixture": "synthetic acceptance only"})
    dataset.to_netcdf(target / "monthly.nc", engine="scipy", format="NETCDF3_64BIT")
    dataset = xr.Dataset({"height": (("y", "x"), [[1.0, 2.0], [3.0, 4.0]], {"units": "m"})},
                         coords={"lat": ("y", [10.0, 20.0]), "lon": ("x", [350.0, 355.0])}, attrs={"fixture": "synthetic acceptance only"})
    dataset.to_netcdf(target / "land-grid.nc", engine="scipy", format="NETCDF3_64BIT")
    return {"kind": "explicit synthetic acceptance fixtures", "directory": str(target), "real_research_data": False}


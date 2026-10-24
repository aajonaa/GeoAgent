"""Explicitly synthetic independent-acceptance inputs, never user research evidence."""
import json
from pathlib import Path


def create(root):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    target = Path(root) / "assets/earth-collection/spatial"
    target.mkdir(parents=True, exist_ok=False)
    dem = np.arange(25, 0, -1, dtype="float32").reshape(5, 5)
    spike = dem.copy()
    spike[2, 2] = 100
    mask = np.zeros((5, 5), dtype="float32")
    mask[2, 2] = 1
    for name, data in [("dem", dem), ("spike-dem", spike), ("extensive", np.arange(1, 17, dtype="float32").reshape(4, 4)), ("region-mask", mask)]:
        with rasterio.open(target / (name + ".tif"), "w", driver="GTiff", width=data.shape[1], height=data.shape[0], count=1, dtype="float32", crs="EPSG:32650", transform=from_origin(500000, 4400000, 10, 10)) as dst:
            dst.write(data, 1)
    features = [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[x, 30], [x+1, 30], [x+1, 31], [x, 31], [x, 30]]]}, "properties": {"value": value}} for x, value in [(110, 2), (111, 4)]]
    (target / "polygons.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    (target / "table.csv").write_text('x,y,label\n0,1,sample-a\n1,2,sample-b\n2,3,"<script>alert(1)</script>"\n', encoding="utf-8")
    (target / "README.txt").write_text("Synthetic acceptance fixtures only; not real mining, environmental, or geological observations.\n", encoding="utf-8")


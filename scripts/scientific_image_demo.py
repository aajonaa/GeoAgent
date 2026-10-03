"""Acquire a reproducible REAL Sentinel-2 subset, not synthetic science data.

Run on the analysis host: python scripts/scientific_image_demo.py NEW_DIRECTORY
This downloads only COG windows. It does not start a model or touch user state.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import requests
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform
from rasterio.windows import Window


ITEM_URL = "https://earth-search.aws.element84.com/v1/collections/sentinel-2-c1-l2a/items/S2C_T50TMK_20250831T030615_L2A"


def acquire(root):
    response = requests.get(ITEM_URL, timeout=30)
    response.raise_for_status()
    item = response.json()
    root.mkdir(parents=True, exist_ok=False)
    (root / "sentinel-stac.json").write_bytes(response.content)
    arrays, scales, offsets, sources = [], [], [], []
    window = grid = crs = None
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_TIMEOUT="30", GDAL_HTTP_MAX_RETRY="1"):
        for role in ("red", "green", "blue", "nir"):
            asset = item["assets"][role]
            if not asset["href"].startswith("https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/"):
                raise ValueError("Unexpected data host; inspect the STAC item before acquisition")
            calibration = asset["raster:bands"][0]
            with rasterio.open(asset["href"]) as src:
                if window is None:
                    x, y = transform("EPSG:4326", src.crs, [116.55], [39.75])
                    row, col = src.index(x[0], y[0])
                    window = Window(col - 256, row - 256, 512, 512)
                    if window.col_off < 0 or window.row_off < 0 or window.col_off + 512 > src.width or window.row_off + 512 > src.height:
                        raise ValueError("Study window leaves the source tile")
                    grid, crs = src.window_transform(window), src.crs
                if src.window_transform(window) != grid or src.crs != crs:
                    raise ValueError("Spectral assets are not on a shared 10-metre grid")
                arrays.append(src.read(1, window=window))
                scales.append(calibration["scale"])
                offsets.append(calibration["offset"])
                sources.append({"role":role,"url":asset["href"],"scale":calibration["scale"],"offset":calibration["offset"],
                                "declared_source_checksum":asset.get("file:checksum"),
                                "checksum_scope":"STAC-provided full-object checksum; not independently verified for a range-read subset"})
            print("Read real band:", role, flush=True)
        profile = dict(driver="GTiff", width=512, height=512, crs=crs, transform=grid, compress="deflate")
        with rasterio.open(root / "beijing-sentinel-rgbnir.tif", "w", count=4, dtype="uint16", nodata=0, **profile) as dst:
            dst.write(np.stack(arrays)); dst.scales = tuple(scales); dst.offsets = tuple(offsets)
            dst.descriptions = ("red B04", "green B03", "blue B02", "nir B08")
            dst.update_tags(source_item=item["id"], acquisition_time=item["properties"]["datetime"],
                            attribution="Contains modified Copernicus Sentinel data (2025)")
        scl_asset = item["assets"]["scl"]
        with rasterio.open(scl_asset["href"]) as src, WarpedVRT(src, crs=crs, transform=grid, width=512, height=512,
                                                              resampling=Resampling.nearest) as aligned:
            scl = aligned.read(1)
        valid = np.isin(scl, [4,5,6]).astype("uint8")
        with rasterio.open(root / "beijing-clear-mask.tif", "w", count=1, dtype="uint8", nodata=0, **profile) as dst:
            dst.write(valid, 1)
            dst.update_tags(method="SCL classes 4 vegetation, 5 non-vegetated, 6 water; nearest-neighbour 20m to 10m; other classes excluded")
        sources.append({"role":"quality_mask","url":scl_asset["href"],"processing":"20m SCL to 10m nearest-neighbour; include classes 4,5,6 only"})
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}
    provenance = {"real_data":True,"source_item":item["id"],"item_url":ITEM_URL,
                  "acquisition_time":item["properties"]["datetime"],"downloaded_at":datetime.now(timezone.utc).isoformat(),
                  "attribution":"Contains modified Copernicus Sentinel data (2025)",
                  "center_lon_lat":[116.55,39.75],"shape":[512,512],"crs":str(crs),"transform":list(grid)[:6],
                  "source_window":[window.col_off,window.row_off,512,512],"sources":sources,"local_sha256":files,
                  "mask_valid_fraction":float(valid.mean()),
                  "limitations":["A 5.12 km subset is not representative of all Beijing.",
                                  "SCL is an automated quality classification, not perfect cloud validation.",
                                  "The original published full-scene checksums were not verified by these window reads."]}
    (root / "sources.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    prompt = ("请分析真实 Sentinel-2 子集 beijing-sentinel-rgbnir.tif 的 NDVI，并展示原图与分析图层。"
              "先读取 sources.json 确认来源。第1、2、3、4波段分别为红、绿、蓝、近红外；"
              "GeoTIFF已经记录scale=0.0001、offset=-0.1，只应用一次。"
              "使用 beijing-clear-mask.tif（SCL 4/5/6类有效），输出到新的 beijing-ndvi 目录。"
              "请使用专业图像工具，提供有效像素数、均值、数值区间统计和下载文件；"
              "解释这只是北京附近5.12km子集，分级不是土地覆盖分类。")
    (root / "demo-prompt.txt").write_text(prompt, encoding="utf-8")
    print(json.dumps({"directory":str(root),"item":item["id"],"mask_valid_fraction":float(valid.mean()),"files":files},indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    acquire(parser.parse_args().directory)

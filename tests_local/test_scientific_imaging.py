"""Synthetic numerical fixtures, never represented as real geological data."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from PIL import Image, ImageDraw
from jsonschema import validate

from geological_agent.bootstrap import build_registry
from geological_agent.scientific_imaging import operate, OUTPUT_SCHEMA, axis_converter
from geological_agent.tools import ToolFailure
from test_team import group


def raster(path, arrays, *, transform=None, crs="EPSG:32650", scale=1, offset=0):
    arrays=np.asarray(arrays,dtype="float32")
    with rasterio.open(path,"w",driver="GTiff",width=arrays.shape[2],height=arrays.shape[1],count=len(arrays),dtype="float32",
                       crs=crs,transform=transform or from_origin(500000,4400000,10,10),nodata=-9999) as ds:
        ds.write(arrays); ds.scales=(scale,)*len(arrays); ds.offsets=(offset,)*len(arrays)


def ndvi(tmp_path, **changes):
    args={"path":"bands.tif","output_dir":"ndvi","index":"NDVI","bands":{"red":1,"nir":2},"calibration_source":"Synthetic fixture"}
    args.update(changes)
    return operate("GeoRasterIndexAnalysis",args,workspace=tmp_path)


def test_index_full_resolution_calibration_mask_and_provenance(tmp_path):
    raster(tmp_path/"bands.tif",[[[200,100],[-9999,0]],[[600,300],[400,0]]],scale=.001,offset=.1)
    before=(tmp_path/"bands.tif").read_bytes()
    out=ndvi(tmp_path)
    validate(out,OUTPUT_SCHEMA)
    with rasterio.open(tmp_path/"ndvi/values.tif") as ds:
        values=ds.read(1,masked=True)
        assert values[0,0] == pytest.approx(.4)
        assert values[0,1] == pytest.approx(1/3)
        assert values.mask[1,0]
        assert values[1,1] == pytest.approx(0)
        assert ds.crs.to_epsg()==32650
        assert ds.transform==from_origin(500000,4400000,10,10)
    assert out["statistics"]["valid_pixels"]==3
    assert out["statistics"]["valid_area_m2"]==300
    assert before==(tmp_path/"bands.tif").read_bytes()
    for item in out["outputs"]:
        assert hashlib.sha256((tmp_path/item["path"]).read_bytes()).hexdigest()==item["sha256"]
    with pytest.raises(ToolFailure,match="existing"):
        ndvi(tmp_path)


def test_index_zero_negative_and_geographic_area(tmp_path):
    raster(tmp_path/"bands.tif",[[[0,-1],[1,1]],[[0,1],[3,1]]],crs="EPSG:4326",transform=from_origin(116,40,.01,.01))
    out=ndvi(tmp_path)
    assert out["statistics"]["valid_pixels"]==2
    assert out["statistics"]["valid_area_m2"] is None
    assert out["statistics"]["mean"]==pytest.approx(.25)


def test_reject_guessed_roles_misaligned_mask_and_nonfinite(tmp_path):
    raster(tmp_path/"bands.tif",np.ones((2,2,2)))
    with pytest.raises(ToolFailure,match="distinct"):
        ndvi(tmp_path,bands={"red":1,"nir":1})
    raster(tmp_path/"mask.tif",np.ones((1,2,2)),transform=from_origin(500001,4400000,10,10))
    with pytest.raises(ToolFailure,match="same CRS"):
        ndvi(tmp_path,valid_mask_path="mask.tif")
    with pytest.raises(ToolFailure):
        ndvi(tmp_path,breaks=[float("nan")])
    assert not (tmp_path/"ndvi").exists()


def test_change_reuses_scientific_values_not_png(tmp_path):
    raster(tmp_path/"a.tif",[[[1,2],[3,-9999]]])
    raster(tmp_path/"b.tif",[[[2,1],[3,4]]])
    out=operate("GeoRasterChangeAnalysis",{"before_path":"a.tif","after_path":"b.tif","output_dir":"change","threshold":.5,"value_unit":"K"},workspace=tmp_path)
    assert out["statistics"]["mean"]==0
    assert out["statistics"]["valid_pixels"]==3
    with rasterio.open(tmp_path/"change/values.tif") as ds:
        assert ds.read(1)[0].tolist()==[1,-1]


def test_map_candidates_pixels_ties_roi_and_component_filter(tmp_path):
    image=Image.new("RGB",(30,20),"white")
    draw=ImageDraw.Draw(image); draw.rectangle((2,2,10,10),fill=(200,20,20)); draw.rectangle((15,2,23,10),fill=(20,20,200))
    image.save(tmp_path/"map.png")
    args={"path":"map.png","output_dir":"map","roi":[0,0,30,20],"classes":[{"label":"A","rgb":[200,20,20],"tolerance":0},{"label":"B","rgb":[20,20,200],"tolerance":0}]}
    out=operate("GeoMapColorExtract",args,workspace=tmp_path)
    assert out["statistics"]["candidate_regions"]==2
    assert out["statistics"]["matched_pixels"]==162
    vectors=json.loads((tmp_path/"map/regions.pixel.json").read_text())
    assert "NOT RFC7946" in vectors["coordinate_space"]
    assert len(vectors["features"])==2
    args["output_dir"]="tied"; args["classes"][1]["rgb"]=[200,20,20]
    with pytest.raises(ToolFailure,match="No regions"):
        operate("GeoMapColorExtract",args,workspace=tmp_path)


def test_curve_calibration_no_interpolation_and_log_axis(tmp_path):
    image=Image.new("RGB",(50,50),"white"); draw=ImageDraw.Draw(image)
    for col in range(5,45):
        if col!=20: draw.point((col,49-col),fill=(0,80,180))
    image.save(tmp_path/"plot.png")
    args={"path":"plot.png","output_dir":"curve","roi":[5,5,45,45],"rgb":[0,80,180],"tolerance":0,
          "x_axis":{"pixel_start":5,"pixel_end":44,"value_start":0,"value_end":39,"scale":"linear","unit":"s"},
          "y_axis":{"pixel_start":44,"pixel_end":5,"value_start":0,"value_end":39,"scale":"linear","unit":"m"}}
    out=operate("GeoPlotDigitize",args,workspace=tmp_path)
    assert out["statistics"]["extracted_columns"]==39
    assert out["statistics"]["unmatched_columns"]==1
    assert out["statistics"]["interpolated_points"]==0
    rows=(tmp_path/"curve/curve.csv").read_text().splitlines()
    assert len(rows)==40 and rows[1].split(",")[2:4]==["0.0","0.0"]
    f=axis_converter({"pixel_start":0,"pixel_end":10,"value_start":1,"value_end":100,"scale":"log10"},0,10)
    assert f(5)==pytest.approx(10)


def test_native_discovery_and_all_skill_tool_references():
    registry, skills, _=build_registry()
    for sid in ("scientific_raster_analysis","map_color_digitization","plot_curve_digitization"):
        for name in skills.load(sid).tool_names:
            assert registry.get(name).definition.input_schema["type"]=="object"


def test_scientific_viewer_receipt_hash_ownership_and_exact_pixel(group,tmp_path):
    app,clients=group; alice=clients["alice"]; store=app.state.store; uid=store.user("alice")["id"]
    raster(tmp_path/"bands.tif",[[[1,1],[1,1]],[[3,3],[3,3]]])
    result=ndvi(tmp_path)
    files={p.relative_to(tmp_path).as_posix():p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    cid=alice.post("/api/conversations").json()["id"]
    generation=store.snapshot(uid,cid,files); rid=store.begin(uid,cid,"Synthetic scientific viewer")
    store.event(rid,{"kind":"tool_result","result":{"status":"ok","name":"GeoRasterIndexAnalysis","call_id":"native-1","data":result}})
    store.finish(rid,status="completed",generation=generation)
    route=f"/api/runs/{rid}/scientific-images"
    shown=alice.get(route)
    assert shown.status_code==200 and len(shown.json()["analyses"])==1
    pixel=alice.get(f"/api/runs/{rid}/scientific-pixel",params={"manifest":result["manifest_path"],"column":1,"row":0})
    assert pixel.status_code==200 and pixel.json()["value"]==.5
    assert clients["bob"].get(route).status_code==404
    assert clients["admin"].get(route).status_code==404
    # A newer snapshot is not permitted to relabel this run's results.
    store.snapshot(uid,cid,{"unrelated.txt":b"new"})
    assert alice.get(route).json()["generation"]==generation


def test_scientific_frontend_syntax():
    node=shutil.which("node")
    if not node: pytest.skip("Node is required for browser-module syntax check")
    script=Path(__file__).resolve().parents[1]/"geological_agent/team/web/scientific-viewer.js"
    subprocess.run([node,"--check",str(script)],check=True)


def test_scientific_assets_are_professional_and_use_canonical_native_handlers():
    from geological_agent.scientific_imaging import SCHEMAS, DESCRIPTIONS
    from geological_agent.geology.source_registry import source_tools
    from geological_agent.team.library import LibraryCatalog
    from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog, ROOT
    from source_asset_checks.run import check_assets
    assets = LibraryCatalog()
    specifications = source_tools()
    for name, schema in SCHEMAS.items():
        spec = specifications[name]
        assert spec['input_schema'] == schema
        assert spec['output_schema'] == OUTPUT_SCHEMA
        assert spec['function_definition']['function']['parameters'] == schema
        assert spec['description'] == DESCRIPTIONS[name]
        assert assets.tools[name]['scope'] == 'professional'
        assert assets.tools[name]['status'] == 'registered'
        assert assets.tools[name]['example_arguments'] is not None
        assert all(field.get('description') for field in schema['properties'].values())
        assert all(field.get('description') for field in OUTPUT_SCHEMA['properties'].values())
    for sid in ('scientific_raster_analysis', 'map_color_digitization', 'plot_curve_digitization'):
        assert assets.skills[sid]['scope'] == 'professional'
        assert assets.skills[sid]['status'] == 'registered'
        _, loader, _ = build_registry()
        body = (ROOT/'catalog/skills'/sid.replace('_','-')/'SKILL.md').read_text(encoding="utf-8").split("---", 2)[-1].strip()
        assert loader.load(sid).instructions == body
    rows = check_assets(catalog(), specifications)
    assert len(rows) == 34 and all(row['status'] == 'passed' for row in rows), rows


def test_native_catalog_drift_is_rejected_without_a_replacement_handler(monkeypatch):
    from copy import deepcopy
    from geological_agent.geology import source_registry
    from geological_agent.scientific_imaging import register_scientific_image_tools
    from geological_agent.tools import ToolRegistry
    registry = ToolRegistry()
    register_scientific_image_tools(registry)
    original = registry.get('GeoRasterIndexAnalysis')
    spec = deepcopy(source_registry.source_tools()['GeoRasterIndexAnalysis'])
    spec['input_schema']['properties']['index']['enum'] = ['FAKE_INDEX']
    monkeypatch.setattr(source_registry, 'source_tools', lambda: {'GeoRasterIndexAnalysis': spec})
    with pytest.raises(ValueError, match='contract drift'):
        source_registry.register(registry)
    assert registry.get('GeoRasterIndexAnalysis') is original

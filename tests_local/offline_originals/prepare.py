"""Select licensed original kernels from the ZIP without bulk extraction."""
from pathlib import Path
import ast
import hashlib
import json
import sys
import traceback
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT.parent / "earth-python-intake-20261021" / "orchestration"))
from flowing import Flow, task
from specs import DEFINITIONS

ARCHIVE = Path(r"D:\Downloads\地学Python工具集.zip\地学Python工具集.zip")
IDS = {10, 26, 31, 84, 100, 124, 126}
REVISION = "r3"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def immutable_write(destination, raw):
    if destination.exists():
        if not destination.is_file() or destination.is_symlink() or destination.read_bytes() != raw:
            raise RuntimeError("Existing preparation evidence differs: " + str(destination))
    else:
        destination.write_bytes(raw)


def generated_initializer(destination, raw):
    """Only the known generated initializer may reuse equivalent CRLF bytes."""
    if destination != HERE / "vendor" / "__init__.py":
        raise ValueError("Initializer compatibility is restricted to the generated vendor marker")
    if destination.exists():
        if destination.is_symlink() or not destination.is_file() or destination.read_bytes().replace(b"\r\n", b"\n") != raw:
            raise RuntimeError("Generated vendor initializer content differs: " + str(destination))
    else:
        destination.write_bytes(raw)


@task
def select_sources():
    inventory = json.loads((ROOT / "identity-r2" / "archive-inventory.json").read_text(encoding="utf-8"))
    rows = [row for row in inventory["projects"] if row["id"] in IDS]
    assert len(rows) == 7 and len({row["id"] for row in rows}) == 7
    originals = HERE / "originals"
    originals.mkdir(exist_ok=True)
    vendor = HERE / "vendor"
    vendor.mkdir(exist_ok=True)
    generated_initializer(vendor / "__init__.py", b'"""Verbatim selected original kernels and original license notices."""\n')
    selected = {10: ["geonotebook/annotations.py", "geonotebook/utils.py"],
                26: ["earthsim/analysis.py"], 31: ["ERA5-Land MONTHLY - Download, Mapping and Time serie extraction.ipynb"],
                84: ["pyGLUE/GLUEmp.py"], 100: ["hs_file_types/raster_meta_extract.py"],
                124: ["pangaea/xlsm.py"], 126: ["pyowm/utils/measurables.py"]}
    result = []
    with zipfile.ZipFile(ARCHIVE) as archive:
        for row in rows:
            target = originals / str(row["id"])
            target.mkdir(exist_ok=True)
            files = []
            prefix = row["archive_prefix"] + "/"
            for relative in selected[row["id"]]:
                member = prefix + relative
                info = archive.getinfo(member)
                notebook_source = row["id"] == 31 and relative == selected[31][0]
                limit = 16 * 1024 * 1024 if notebook_source else 2_000_000
                assert info.file_size <= limit, "Selected original source exceeds its source-only bound: " + member
                raw = archive.read(info)
                assert len(raw) == info.file_size, "Incomplete source bytes"
                destination = target / Path(relative).name
                immutable_write(destination, raw)
                files.append({"archive_member": member, "file": destination.relative_to(HERE).as_posix(), "sha256": sha(raw)})
            licenses = []
            for index, member in enumerate(row["license_paths"]):
                if not member.startswith(prefix) or "/" in member[len(prefix):]:
                    continue
                raw = archive.read(member)
                destination = target / ("LICENSE-" + str(index) + ".txt")
                immutable_write(destination, raw)
                licenses.append({"archive_member": member, "file": destination.relative_to(HERE).as_posix(), "sha256": sha(raw)})
            assert licenses, "Original root license is required"
            result.append({"project_id": row["id"], "name": row["name"], "upstream_url": row["upstream_url"],
                           "source_commit": row["source_revision_git_head"], "sources": files, "licenses": licenses})
    return result


def normalized(path):
    return (HERE / path).read_bytes().decode("utf-8-sig").replace("\r\r\n", "\n").replace("\r\n", "\n")


def pieces(source, class_name=None, names=()):
    tree = ast.parse(source)
    nodes = tree.body if class_name is None else next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name).body
    selected = [node for node in nodes if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in selected} == set(names)
    lines = source.splitlines(keepends=True)
    output = []
    for node in selected:
        start = min([node.lineno, *[decorator.lineno for decorator in node.decorator_list]])
        text = "".join(lines[start - 1:node.end_lineno])
        output.append({"name": node.name, "line_start": start, "line_end": node.end_lineno, "normalized_source_sha256": sha(text.encode()), "text": text})
    return output


@task(depends_on=[select_sources])
def preserve_kernels(select_sources):
    rows = {row["project_id"]: row for row in select_sources}
    records = []
    def emit(project, filename, header, extracts, footer=""):
        path = HERE / "vendor" / filename
        body = header + "\n" + "\n".join(item["text"] for item in extracts) + footer
        path.write_text(body, encoding="utf-8", newline="\n")
        records.append({"project_id": project, "file": path.relative_to(HERE).as_posix(), "sha256": sha(body.encode()),
                        "excerpts": [{key: value for key, value in item.items() if key != "text"} for item in extracts]})
    source = normalized(rows[126]["sources"][0]["file"])
    emit(126, "pyowm_kernel.py", '# Original PyOWM kernel. MIT license retained in originals/126.\n', pieces(source, names=["metric_wind_dict_to_beaufort"]))
    source = normalized(rows[26]["sources"][0]["file"])
    emit(26, "earthsim_kernel.py", '# Original EarthSim method. BSD-3-Clause notice in originals/26.\nimport numpy as np\n\nclass LineCrossSectionKernel:\n', pieces(source, "LineCrossSection", ["_gen_samples"]))
    source = normalized(rows[124]["sources"][0]["file"])
    emit(124, "pangaea_kernel.py", '# Original Pangaea geographic accessor methods. BSD-3-Clause in originals/124.\nimport numpy as np\n\nclass LSMGridKernel:\n', pieces(source, "LSMGridReader", ["__init__", "y_inverted", "_raw_coords", "latlon", "center", "_getvar"]))
    annotations = normalized(rows[10]["sources"][0]["file"])
    transforms = normalized(rows[10]["sources"][1]["file"])
    transform_piece = pieces(transforms, names=["transform_coordinates"])
    window_piece = pieces(annotations, "Annotation", ["get_data_window"])
    subset_piece = pieces(annotations, "Polygon", ["subset"])
    module = HERE / "vendor" / "geonotebook_kernel.py"
    text = ('# Original GeoNotebook methods. Apache-2.0 license in originals/10.\nimport numpy as np\nfrom rasterio.crs import CRS\nfrom rasterio.features import rasterize\nfrom rasterio.warp import transform\nfrom shapely.geometry import Polygon as sPolygon\n\n'
            + transform_piece[0]["text"] + '\nclass AnnotationWindowKernel:\n' + window_piece[0]["text"]
            + '\nclass PolygonSubsetKernel:\n' + subset_piece[0]["text"])
    module.write_text(text, encoding="utf-8", newline="\n")
    records.append({"project_id": 10, "file": module.relative_to(HERE).as_posix(), "sha256": sha(text.encode()), "excerpts": [{k: v for k, v in item.items() if k != "text"} for item in transform_piece + window_piece + subset_piece]})
    notebook = json.loads(normalized(rows[31]["sources"][0]["file"]))
    statements = []
    expected = {
        8: "ds_by_month = xarray_src.groupby('time.month').mean('time')",
        10: 'time_serie = xarray_src[param].sel(longitude=lon, latitude=lat, method="nearest", tolerance=0.051)',
    }
    for index, marker in [(8, "ds_by_month ="), (10, "time_serie =")]:
        assert notebook["cells"][index]["cell_type"] == "code", "Reviewed ERA5 cell changed type"
        cell = "".join(notebook["cells"][index]["source"])
        assert len(cell.encode("utf-8")) <= 128 * 1024, "Reviewed code cell exceeds its fixed extraction bound"
        hits = [(number, line) for number, line in enumerate(cell.splitlines(), 1) if line.startswith(marker)]
        assert len(hits) == 1
        number, line = hits[0]
        assert ast.dump(ast.parse(line), include_attributes=False) == ast.dump(ast.parse(expected[index]), include_attributes=False), "Reviewed original ERA5 statement changed"
        statements.append({"name": marker, "cell": index, "line_start": number, "line_end": number, "normalized_source_sha256": sha(line.encode()), "text": "    " + line + "\n"})
    emit(31, "era5_kernel.py", '# Original ERA5-tools monthly notebook statements. GPL-3.0 in originals/31.\ndef monthly_climate(xarray_src, param, lon, lat):\n', statements, '\n    return ds_by_month, time_serie\n')
    source = normalized(rows[100]["sources"][0]["file"])
    emit(100, "hydroshare_kernel.py", '# Original HydroShare get_band_info. BSD-3-Clause in originals/100.\nfrom osgeo import gdal\nfrom osgeo.gdalconst import GA_ReadOnly\nimport numpy\n', pieces(source, names=["get_band_info"]), '\nif __name__ == "__main__":\n    import sys, json\n    print(json.dumps(get_band_info(sys.argv[1]), allow_nan=False))\n')
    return {"sources": select_sources, "kernels": records}


@task(depends_on=[preserve_kernels])
def write_proposals(preserve_kernels):
    sources = {row["project_id"]: row for row in preserve_kernels["sources"]}
    kernels = {row["project_id"]: row for row in preserve_kernels["kernels"]}
    for spec in DEFINITIONS:
        original = sources[spec["project_id"]]
        kernel = kernels[spec["project_id"]]
        spec.update({"upstream_url": original["upstream_url"], "source_commit": original["source_commit"], "vendor_files": [kernel], "license_files": original["licenses"], "original_files": original["sources"]})
        if spec["project_id"] == 100:
            spec["activation"] = "pending_exact_native_GDAL_profile_and_parent_acceptance"
    blocked = [{"project_id": 84, "name": "pyGLUE", "status": "original_framework_only_not_registered", "new_tool_count": 0,
                "source": sources[84], "evidence": {"file": "pyGLUE/GLUEmp.py", "symbols": ["GLUEEvaluator.evaluate", "GLUEEvaluator.run_and_evaluate", "GLUEFramework.run_GLUE"],
                "reason": "Original source provides arbitrary external model/rule callbacks and Python-2 iteritems/pickling framework, not a self-contained domain objective or likelihood. Exposing callbacks, pickles, metadata, or a newly invented likelihood would not be a bounded original scientific operation."},
                "next_action": "Requires separately authorized and evidenced model/likelihood integration or maintained alternative; no substitute is silently counted as pyGLUE."}]
    result = {"scope": "Exclusive offline original-source sidecar; no existing source/catalog/service modifications", "complete": False,
              "projects_reviewed": 7, "proposed_operations": 6, "activated_tools": 0, "operations": DEFINITIONS, "blocked": blocked,
              "provenance": preserve_kernels, "parent_integration": "not_run", "registered_runtime_acceptance": "not_run", "deployed": False, "pushed": False, "gpu_used": False}
    (HERE / "manifest.json").write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return {"manifest": str(HERE / "manifest.json"), "proposed": 6, "blocked": 1, "activated": 0}


def main():
    flow = Flow(write_proposals, max_workers=1, journal_path=str(HERE / ("prepare-" + REVISION + "-flow.jsonl")))
    try:
        results = flow.run()
        summary = flow.summary()
        print(summary)
        try:
            value = flow.value(write_proposals)
        except KeyError:
            receipt = {"complete": False, "exit_code": 1, "flow_summary": summary,
                       "tasks": {name: {"status": str(getattr(result, "status", "unknown")), "error": str(getattr(result, "error", ""))} for name, result in results.items()}}
            (HERE / ("preparation-failure-" + REVISION + ".json")).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            return 1
        print(json.dumps(value, ensure_ascii=True))
        return 0
    except Exception as error:
        (HERE / ("preparation-failure-" + REVISION + ".json")).write_text(json.dumps({"complete": False, "exit_code": 1, "error": str(error), "traceback": traceback.format_exc()}, indent=2) + "\n", encoding="utf-8")
        return 1


if __name__ == "__main__":
    sys.exit(main())



"""Read-only evidence and immutable generation views; restore creates a new snapshot."""
import hashlib
import json
import re
from io import BytesIO
from pathlib import PurePosixPath

from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse

from .citations import answer_citations

_IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.svg')
_GENERATION = re.compile(r'[a-f0-9]{32}')


def _file_rows(files, origins):
    return [{'name': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
             'origin': origins.get(name)} for name, raw in sorted(files.items())]


def _manifest_metadata(files):
    records = {}
    budget = 4 * 1024 * 1024
    for name, raw in sorted(files.items()):
        if not name.lower().endswith('.json') or len(raw) > 2 * 1024 * 1024 or budget <= 0:
            continue
        budget -= len(raw)
        try:
            doc = json.loads(raw)
        except (ValueError, UnicodeError):
            continue
        if not isinstance(doc, dict):
            continue
        schema = doc.get('schema') if doc.get('schema') == 'geoagent.scientific-image/v1' else doc.get('schema_version')
        outputs = doc.get('outputs')
        if schema not in ('geoagent.scientific-image/v1', 1) or not isinstance(outputs, list):
            continue
        valid = True
        for output in outputs:
            if not isinstance(output, dict) or not isinstance(output.get('path'), str):
                valid = False
                break
            raw_output = files.get(output['path'])
            if raw_output is None or hashlib.sha256(raw_output).hexdigest() != output.get('sha256'):
                valid = False
                break
        if valid:
            records[name] = doc
    return records


def _raster_metadata(raw):
    try:
        import rasterio
        from rasterio.io import MemoryFile
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR'), MemoryFile(raw) as memory, memory.open() as ds:
            band_units = list(ds.units)
            common_unit = band_units[0] if band_units and all(unit == band_units[0] for unit in band_units) else None
            return {'width': ds.width, 'height': ds.height,
                    'coordinate_reference': str(ds.crs) if ds.crs else None,
                    'transform': [ds.transform.c, ds.transform.a, ds.transform.b,
                                  ds.transform.f, ds.transform.d, ds.transform.e],
                    'units': common_unit, 'band_units': band_units if len(band_units) > 1 else None}
    except Exception:
        return {}


def _figure_metadata(name, raw, origin, manifests):
    suffix = PurePosixPath(name).suffix.lower()
    result = {'name': name, 'width': None, 'height': None, 'source': None,
              'coordinate_reference': None, 'source_coordinate_reference': None,
              'transform': None, 'units': None, 'band_units': None, 'cartographic_scale': None, 'manifest': None}
    if suffix not in _IMAGE_SUFFIXES:
        return result
    source = origin.get('origin') if isinstance(origin, dict) else None
    result['source'] = source
    if suffix in ('.tif', '.tiff'):
        result.update(_raster_metadata(raw))
    if result['width'] is None and suffix not in ('.svg',):
        try:
            from PIL import Image
            with Image.open(BytesIO(raw)) as image:
                result.update(width=image.width, height=image.height)
        except Exception:
            pass
    for manifest_name, doc in manifests.items():
        if doc.get('schema') == 'geoagent.scientific-image/v1':
            outputs = [item for item in doc.get('outputs', []) if item.get('path') == name]
            if not outputs:
                continue
            grid = doc.get('grid') if isinstance(doc.get('grid'), dict) else {}
            parameters = doc.get('parameters') if isinstance(doc.get('parameters'), dict) else {}
            inputs = doc.get('inputs') if isinstance(doc.get('inputs'), list) else []
            calibration = parameters.get('calibration') if isinstance(parameters.get('calibration'), dict) else {}
            result.update(manifest=manifest_name,
                          coordinate_reference=grid.get('crs'), transform=grid.get('transform'),
                          units=parameters.get('value_unit') or calibration.get('unit'),
                          cartographic_scale=doc.get('cartographic_scale'))
            if inputs and isinstance(inputs[0], dict):
                result['source'] = inputs[0].get('path') or result['source']
            break
        outputs = doc.get('outputs', [])
        if not outputs or not isinstance(outputs[0], dict) or outputs[0].get('path') != name:
            continue
        source_info = doc.get('source') if isinstance(doc.get('source'), dict) else {}
        processing = doc.get('processing') if isinstance(doc.get('processing'), dict) else {}
        result.update(manifest=manifest_name, source=source_info.get('path') or result['source'],
                      source_coordinate_reference=source_info.get('crs'),
                      coordinate_reference=processing.get('coordinate_reference'),
                      width=processing.get('width') or result['width'],
                      height=processing.get('height') or result['height'],
                      units=processing.get('unit'), cartographic_scale=processing.get('cartographic_scale'))
        break
    return result


def generation_view(store, uid, cid, generation):
    if not store.generation_exists(uid, cid, generation):
        raise KeyError('Generation not found')
    files = store.files(uid, cid, generation)
    origins = store.file_origins(uid, cid, generation)
    manifests = _manifest_metadata(files)
    summary = store.generation(uid, cid, generation)
    summary.update(file_count=len(files), bytes=sum(len(raw) for raw in files.values()))
    return {'conversation_id': cid, **summary, 'files': _file_rows(files, origins),
            'figures': [_figure_metadata(name, raw, origins.get(name), manifests)
                        for name, raw in sorted(files.items())
                        if PurePosixPath(name).suffix.lower() in _IMAGE_SUFFIXES]}


def compare_generations(store, uid, cid, left, right):
    before, after = {}, {}
    for generation, target in ((left, before), (right, after)):
        if not store.generation_exists(uid, cid, generation):
            raise KeyError('Generation not found')
        target.update(store.files(uid, cid, generation))
    changes = []
    for name in sorted(before.keys() | after.keys()):
        first, second = before.get(name), after.get(name)
        status = 'added' if first is None else 'removed' if second is None else (
            'unchanged' if hashlib.sha256(first).digest() == hashlib.sha256(second).digest() else 'modified')
        changes.append({'name': name, 'status': status,
                        'left_sha256': hashlib.sha256(first).hexdigest() if first is not None else None,
                        'right_sha256': hashlib.sha256(second).hexdigest() if second is not None else None,
                        'left_bytes': len(first) if first is not None else None,
                        'right_bytes': len(second) if second is not None else None})
    return {'conversation_id': cid, 'left': left, 'right': right, 'changes': changes,
            'counts': {status: sum(item['status'] == status for item in changes)
                       for status in ('added', 'removed', 'modified', 'unchanged')}}


def generation_evidence(store, uid, cid, generation):
    if not store.generation_exists(uid, cid, generation):
        raise KeyError('Generation not found')
    items = []
    for run in store.runs(uid, cid):
        if run.get('generation') != generation or not str(run.get('answer') or '').strip():
            continue
        citations = answer_citations(store, uid, run)
        if citations['items'] or citations['unavailable_ids']:
            items.append({'run_id': run['id'], 'answer': run['answer'], 'status': run['status'],
                          'relation': 'saved_citation_only', **citations})
    return {'conversation_id': cid, 'generation': generation, 'items': items,
            'note': '仅展示答复中实际保存的引用 ID 与原文片段；支持或反驳关系未自动判定。'}


def install_generation_routes(app, auth, store, guard, jobs):
    def response(value):
        return JSONResponse(value, headers={'Cache-Control': 'private, no-store'})

    def owned_generation(cid, generation, uid):
        if not isinstance(generation, str) or not _GENERATION.fullmatch(generation):
            raise HTTPException(400, 'Invalid generation identifier')
        try:
            return generation_view(store, uid, cid, generation)
        except KeyError as exc:
            raise HTTPException(404, 'Generation not found') from exc

    @app.get('/api/conversations/{cid}/generations')
    def generations(cid: str, request: Request):
        uid = auth(request)['id']
        try:
            return response({'conversation_id': cid, 'items': store.generations(uid, cid)})
        except KeyError as exc:
            raise HTTPException(404, 'Conversation not found') from exc

    @app.get('/api/conversations/{cid}/generation')
    def generation(cid: str, request: Request, id: str = Query(..., min_length=32, max_length=32)):
        return response(owned_generation(cid, id, auth(request)['id']))

    @app.get('/api/conversations/{cid}/generation-compare')
    def compare(cid: str, request: Request, left: str = Query(..., min_length=32, max_length=32),
                right: str = Query(..., min_length=32, max_length=32)):
        uid = auth(request)['id']
        try:
            return response(compare_generations(store, uid, cid, left, right))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get('/api/conversations/{cid}/generation-evidence')
    def evidence(cid: str, request: Request, generation: str = Query(..., min_length=32, max_length=32)):
        uid = auth(request)['id']
        try:
            return response(generation_evidence(store, uid, cid, generation))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post('/api/conversations/{cid}/generation-restore')
    async def restore(cid: str, request: Request, generation: str = Query(..., min_length=32, max_length=32)):
        uid = auth(request, mutate=True)['id']
        if not _GENERATION.fullmatch(generation):
            raise HTTPException(400, 'Invalid generation identifier')
        try:
            store.conversation(uid, cid)
        except KeyError as exc:
            raise HTTPException(404, 'Conversation not found') from exc
        with guard:
            if any(job['uid'] == uid for job in jobs.values()):
                raise HTTPException(409, 'Wait for your active task before restoring files')
            try:
                restored = store.restore(uid, cid, generation)
            except KeyError as exc:
                raise HTTPException(404, 'Generation not found') from exc
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
        return response({'generation': restored, 'source_generation': generation,
                         'message': '已恢复为新版本；历史版本未被改写。'})

"""One curated fixture, ordinary agent runs, and an independent bounded check."""
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sqlite3
import time
from functools import lru_cache

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

CASE_ID = 'curve-linear-v1'
DATA = Path(__file__).parent / 'case_data' / CASE_ID
WEB = Path(__file__).parent / 'web'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fixture():
    manifest = json.loads((DATA / 'manifest.json').read_text(encoding='utf-8'))
    files = {}
    for name, digest in manifest['files'].items():
        if name not in ('image.png', 'request.json', 'truth.json'):
            raise ValueError('Unexpected curated fixture file')
        raw = (DATA / name).read_bytes()
        if sha(raw) != digest:
            raise ValueError('Curated fixture integrity check failed: ' + name)
        files[name] = raw
    return manifest, files


@lru_cache(maxsize=1)
def availability():
    try:
        from .case_catalog import runtime_bundle
        from jsonschema import Draft202012Validator
        registry, loader, _ = runtime_bundle()
        spec = registry.get('GeoPlotDigitize').definition
        skill = loader.load('plot_curve_digitization')
        if 'GeoPlotDigitize' not in skill.tool_names:
            raise ValueError('Skill does not expose the required native operation')
        _, files = fixture()
        args = json.loads(files['request.json'])['arguments']
        Draft202012Validator(spec.input_schema).validate(args)
        # These are the existing native operation's CPU dependencies.
        import numpy, PIL  # noqa: F401
        return {'ready': True, 'message': '专业工具和 CPU 依赖已就绪'}
    except Exception as exc:
        return {'ready': False, 'message': '案例环境未就绪：' + type(exc).__name__}


def task_prompt():
    return ('请完成“已标定曲线数字化”案例。image.png 和 request.json 已放在当前对话工作区。'
            '这是明确标记的合成验证数据，不是实测矿产或论文观测数据。'
            '先读取 request.json，按照曲线数字化 Skill 的指导，'
            '严格按原请求的 ROI、RGB、容差、坐标锚点及 Ma／mg/kg 单位执行；输出目录为 out。'
            '使用专业曲线提取操作，不用 Python 重写提取算法，不联网、不调用视觉模型猜测参数。'
            '展示真实生成的原图、提取点叠加图和重建曲线，提供 CSV 及来源清单的下载链接。'
            '简洁说明提取点数、单位及缺失或歧义列；不得插值补点。不要声称已通过自动核对，'
            '核对由页面独立执行。')


def compare(files, events):
    """No model call; compare this run's actual saved files to frozen truth."""
    manifest, original = fixture()
    truth = json.loads(original['truth.json'])
    request = json.loads(original['request.json'])
    checks = []

    def check(name, ok):
        checks.append({'name': name, 'passed': bool(ok)})

    for name in ('image.png', 'request.json'):
        check('原始输入未改变：' + name, files.get(name) == original[name])
    starts = {e.get('id'): e for e in events if e.get('kind') == 'tool_start'}
    proof = []
    for event in events:
        result = event.get('result', {})
        start = starts.get(event.get('id'), {})
        args = start.get('arguments')
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = None
        if (event.get('kind') == 'tool_result' and event.get('name') == 'GeoPlotDigitize'
                and result.get('status') == 'ok' and args == request['arguments']):
            proof.append(result)
    check('原生专业工具成功执行且参数与案例一致', bool(proof))
    for name in ('source.png', 'overlay.png', 'reconstructed.png', 'curve.csv', 'analysis.geoanalysis.json'):
        check('实际产物：' + name, bool(files.get('out/' + name)))
    try:
        rows = list(csv.DictReader(io.StringIO(files['out/curve.csv'].decode('utf-8-sig'))))
        points = truth['points']
        check('CSV 点数与字段', len(rows) == len(points) and bool(rows)
              and list(rows[0]) == list(points[0]))
        for row, expected in zip(rows, points):
            for key, value in expected.items():
                if isinstance(value, (int, float)):
                    actual = float(row[key])
                    ok = (math.isfinite(actual) and (actual == value if key in ('pixel_column', 'pixel_row')
                          else abs(actual - value) <= 1e-10 + 1e-12 * abs(value)))
                else:
                    ok = row[key] == value
                check('点 ' + str(expected['pixel_column']) + ' / ' + key, ok)
        from PIL import Image
        for name, key in (('source.png', 'source_pixels'), ('overlay.png', 'overlay_pixels')):
            with Image.open(io.BytesIO(files['out/' + name])) as image:
                actual = image.convert('RGBA')
                expected = truth[key]
                check(name + ' 完整像素', actual.size == (len(expected[0]), len(expected))
                      and list(actual.getdata()) == [tuple(pixel) for line in expected for pixel in line])
        with Image.open(io.BytesIO(files['out/reconstructed.png'])) as image:
            image = image.convert('RGBA')
            check('重建图尺寸', image.size == (900, 520))
            dots = {(x, y) for y in range(image.height) for x in range(image.width)
                    if image.getpixel((x, y)) == (38, 120, 96, 255)}
            l, t, r, b = request['arguments']['roi']
            expected_dots = set()
            for point in points:
                x = math.floor(65 + (point['pixel_column'] - l) / max(1, r - l - 1) * 805)
                y = math.floor(35 + (point['pixel_row'] - t) / max(1, b - t - 1) * 425)
                expected_dots.update((x + dx, y + dy) for dx, dy in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)))
            close = lambda point, others: any((point[0]+dx, point[1]+dy) in others
                                              for dx in (-1, 0, 1) for dy in (-1, 0, 1))
            check('重建点位置（原协议 1 像素显示容差）', all(close(p, dots) for p in expected_dots))
            check('重建图无额外点或补线', all(close(p, expected_dots) for p in dots))
        actual_manifest = json.loads(files['out/analysis.geoanalysis.json'])
        stats = {'extracted_columns': len(points), 'ambiguous_columns': truth['ambiguous'],
                 'unmatched_columns': truth['missing'], 'x_unit': request['arguments']['x_axis']['unit'],
                 'y_unit': request['arguments']['y_axis']['unit'], 'interpolated_points': 0}
        check('点数、缺失列、歧义列及无插值统计', actual_manifest['statistics'] == stats
              and any(result.get('data', {}).get('statistics') == stats for result in proof))
        # Bind the downloaded products to the receipt emitted by the tool, not prose.
        check('来源清单与原生调用回执绑定', any(
            result.get('data', {}).get('manifest_path') == 'out/analysis.geoanalysis.json' for result in proof))
        outputs = actual_manifest['outputs']
        check('全部产物哈希', len(outputs) == 4 and all(
            item['path'] in files and sha(files[item['path']]) == item['sha256'] for item in outputs))
        check('原生回执中全部产物哈希', any(
            len(result.get('data', {}).get('outputs', [])) == 5 and all(
                item['path'] in files and sha(files[item['path']]) == item['sha256']
                for item in result['data']['outputs']) for result in proof))
        check('原请求参数完整保留', actual_manifest['parameters'] == request['arguments'])
    except (KeyError, ValueError, TypeError, OSError, csv.Error):
        check('结果结构与产物可读取', False)
    return {'status': 'passed' if all(c['passed'] for c in checks) else 'failed',
            'checks': checks, 'passed': sum(c['passed'] for c in checks), 'total': len(checks),
            'scope': '仅本合成案例的工具执行、数值、单位、图片和产物；不代表 AI Lab 正式接收或整个 Skill 全量验收。',
            'fixture_version': manifest['version'], 'checked_at': time.time()}


def install_case_routes(app, auth, body, store, guard, jobs):
    db = sqlite3.connect(store.root / 'case-experience.sqlite3', check_same_thread=False)
    db.execute('CREATE TABLE IF NOT EXISTS loads(uid TEXT, token TEXT, cid TEXT, version TEXT, PRIMARY KEY(uid,token))')
    db.execute('CREATE TABLE IF NOT EXISTS checks(uid TEXT,cid TEXT,rid TEXT,generation TEXT,report TEXT,created REAL)')
    if 'case_id' not in {r[1] for r in db.execute('PRAGMA table_info(loads)')}:
        db.execute("ALTER TABLE loads ADD COLUMN case_id TEXT NOT NULL DEFAULT 'curve-linear-v1'")
    db.commit()
    from .case_catalog import CaseCatalog
    library = CaseCatalog()
    app.state.case_catalog = library

    async def load_catalog_case(case_id, request):
        uid = auth(request, mutate=True)['id']
        item = library.get(case_id)
        data = await body(request)
        token = data.get('request_id')
        if not isinstance(token, str) or not re.fullmatch(r'[a-f0-9-]{32,36}', token):
            raise HTTPException(400, 'A valid load request ID is required')
        checked = library.preflight(case_id)
        if not checked['ready']:
            raise HTTPException(409, '；'.join(checked['issues']))
        files = library.files(item)
        with guard:
            if any(job['uid'] == uid for job in jobs.values()):
                raise HTTPException(409, '请等待当前任务结束后加载案例')
            old = db.execute('SELECT cid,case_id FROM loads WHERE uid=? AND token=?', (uid,token)).fetchone()
            if old:
                if old[1] != case_id:
                    raise HTTPException(409, '加载请求已绑定其他案例，请重新发起')
                conv = store.conversation(uid,old[0])
            else:
                conv = store.create_conversation(uid); cid = conv['id']
                origins = {name:{'origin':'user_supplied','sha256':sha(raw),
                    'scope':'Curated validation input chosen by user; not independently authenticated geological observations',
                    'case_id':case_id,'case_version':item['version']} for name,raw in files.items()}
                try:
                    store.snapshot(uid,cid,files,origins=origins)
                    with store.lock,store.db:
                        store.db.execute('UPDATE conversations SET title=? WHERE id=? AND uid=?',('案例体验 · '+item['title'],cid,uid))
                    with db:
                        db.execute('INSERT INTO loads(uid,token,cid,version,case_id) VALUES (?,?,?,?,?)',(uid,token,cid,item['version'],case_id))
                except Exception:
                    with store.lock,store.db:
                        store.db.execute('DELETE FROM generation_audit WHERE cid=?',(cid,))
                        store.db.execute('DELETE FROM file_origins WHERE cid=?',(cid,))
                        store.db.execute('DELETE FROM files WHERE cid=?',(cid,))
                        store.db.execute('DELETE FROM conversations WHERE id=? AND uid=?',(cid,uid))
                    raise
        return {'conversation_id':conv['id'],'case_id':case_id,'prompt':library.prompt(item),
                'message':'案例和输入已准备。点击发送后使用当前模型；该案例尚未完成在线独立验收。'}

    @app.post('/api/cases/preflight')
    def preflight_all(request: Request):
        auth(request,mutate=True)
        library.preflight.cache_clear()
        return library.catalog()

    @app.get('/case-assets/{name}')
    def asset(name: str):
        if name not in ('case-experience.js', 'case-experience.css'):
            raise HTTPException(404)
        return FileResponse(WEB / name)

    @app.get('/api/cases')
    def cases(request: Request):
        auth(request)
        return library.catalog()

    @app.post('/api/cases/{case_id}/load')
    async def load(case_id: str, request: Request):
        uid = auth(request, mutate=True)['id']
        if case_id != CASE_ID:
            return await load_catalog_case(case_id, request)
        data = await body(request)
        token = data.get('request_id')
        if not isinstance(token, str) or not re.fullmatch(r'[a-f0-9-]{32,36}', token):
            raise HTTPException(400, 'A valid load request ID is required')
        manifest, original = fixture()
        if not availability()['ready']:
            raise HTTPException(503, '案例所需专业工具或 CPU 依赖尚未就绪')
        with guard:
            if any(job['uid'] == uid for job in jobs.values()):
                raise HTTPException(409, '请等待当前任务结束后加载案例')
            old = db.execute('SELECT cid,version,case_id FROM loads WHERE uid=? AND token=?', (uid, token)).fetchone()
            if old:
                if old[2] != CASE_ID:
                    raise HTTPException(409, '加载请求已绑定其他案例，请重新发起')
                conv = store.conversation(uid, old[0])
            else:
                conv = store.create_conversation(uid)
                cid = conv['id']
                files = {k: original[k] for k in ('image.png', 'request.json')}
                origins = {k: {'origin': 'user_supplied', 'sha256': sha(raw),
                              'scope': 'User selected curated synthetic validation fixture; not measured geological data',
                              'case_id': CASE_ID, 'case_version': manifest['version']} for k, raw in files.items()}
                try:
                    store.snapshot(uid, cid, files, origins=origins)
                    with store.lock, store.db:
                        store.db.execute('UPDATE conversations SET title=? WHERE id=? AND uid=?',
                                         ('案例体验 · 曲线数字化', cid, uid))
                    with db:
                        db.execute('INSERT INTO loads(uid,token,cid,version,case_id) VALUES (?,?,?,?,?)', (uid, token, cid, manifest['version'], CASE_ID))
                except Exception:
                    # Only roll back the newly created, never-run empty case conversation.
                    with store.lock, store.db:
                        store.db.execute('DELETE FROM generation_audit WHERE cid=?', (cid,))
                        store.db.execute('DELETE FROM file_origins WHERE cid=?', (cid,))
                        store.db.execute('DELETE FROM files WHERE cid=?', (cid,))
                        store.db.execute('DELETE FROM conversations WHERE id=? AND uid=?', (cid, uid))
                    raise
        return {'conversation_id': conv['id'], 'prompt': task_prompt(), 'case_id': CASE_ID,
                'message': '案例已加载；点击发送后使用当前所选模型执行。'}

    @app.get('/api/conversations/{cid}/case')
    def status(cid: str, request: Request):
        uid = auth(request)['id']
        store.conversation(uid, cid)
        row = db.execute('SELECT version,case_id FROM loads WHERE uid=? AND cid=?', (uid, cid)).fetchone()
        if not row:
            return {'case': None}
        latest = db.execute('SELECT report FROM checks WHERE uid=? AND cid=? ORDER BY created DESC LIMIT 1', (uid, cid)).fetchone()
        report = json.loads(latest[0]) if latest else None
        runs = store.runs(uid, cid)
        if report and (report['generation'] != store.conversation(uid, cid)['generation']
                       or not runs or report['run_id'] != runs[-1]['id']):
            report = None
        return {'case': row[1], 'title': library.get(row[1])['title'], 'version': row[0], 'check_available': row[1] == CASE_ID, 'report': report}

    @app.post('/api/conversations/{cid}/case/check')
    def validate(cid: str, request: Request):
        uid = auth(request, mutate=True)['id']
        conv = store.conversation(uid, cid)
        with guard:
            if not db.execute('SELECT 1 FROM loads WHERE uid=? AND cid=?', (uid, cid)).fetchone():
                raise HTTPException(404, 'This conversation has no curated case')
            selected = db.execute('SELECT case_id FROM loads WHERE uid=? AND cid=?', (uid,cid)).fetchone()[0]
            if selected != CASE_ID:
                raise HTTPException(409, '此案例尚未接入在线独立比较器；不能将执行完成标记为独立验收通过')
            runs = store.runs(uid, cid)
            if not runs:
                raise HTTPException(409, '请先发送案例任务并等待执行完成')
            run = runs[-1]
            if run['status'] != 'completed':
                raise HTTPException(409, '最新任务尚未成功完成；不能标记核对通过')
            generation = run.get('generation')
            if not generation or generation != conv['generation']:
                raise HTTPException(409, '文件已变化，请重新运行案例后再核对')
            events, cursor = [], 0
            while True:
                page = store.events(uid, run['id'], cursor)
                if not page:
                    break
                events.extend(row['data'] if isinstance(row.get('data'), dict) else row for row in page)
                cursor = page[-1]['id']
            report = compare(store.files(uid, cid, generation), events)
            report.update(run_id=run['id'], generation=generation)
            with db:
                db.execute('INSERT INTO checks VALUES (?,?,?,?,?,?)',
                           (uid, cid, run['id'], generation, json.dumps(report, ensure_ascii=False), time.time()))
            return report

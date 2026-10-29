"""Read-only workspace inventory. Explicit admin access; no filesystem scanning in HTTP."""
import json
import os
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse


def load_inventory(path):
    path = Path(path)
    if not path.is_file():
        raise HTTPException(503, '数据盘点快照尚未配置。')
    if path.stat().st_size > 4 * 1024 * 1024:
        raise HTTPException(503, '数据盘点快照超过大小限制。')
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        assert data['schema_version'] == 1
        assert isinstance(data['as_of'], str) and len(data['as_of']) > 10
        assert isinstance(data['datasets'], list) and data['datasets']
        ids = set()
        for row in data['datasets']:
            assert row['id'] not in ids
            ids.add(row['id'])
            assert all(isinstance(row[k], str) for k in ('id', 'name', 'unit'))
            assert type(row['count']) is int and row['count'] >= 0
            assert type(row['bytes']) is int and row['bytes'] >= 0
            for group in ('groups', 'formats', 'relevance', 'statuses'):
                if group in row:
                    assert isinstance(row[group], list)
                    assert all(isinstance(x['name'], str) and type(x['count']) is int and x['count'] >= 0 for x in row[group])
            if 'verified' in row:
                assert type(row['verified']) is int and 0 <= row['verified'] <= row['count']
            if 'statuses' in row:
                assert sum(x['count'] for x in row['statuses']) == row['count']
        return data
    except (ValueError, KeyError, TypeError, AssertionError, UnicodeError):
        raise HTTPException(503, '数据盘点快照校验失败，请重新生成。') from None


def install_data_inventory_routes(app, auth, state_root):
    @app.get('/api/data-inventory')
    def inventory(request: Request):
        # Workspace inventories include private source locations. Never expose
        # these through a public static asset or another user's knowledge API.
        auth(request, admin=True)
        path = Path(os.environ.get('GEOTOOL_DATA_INVENTORY', str(Path(state_root) / 'data-inventory.json')))
        return JSONResponse(load_inventory(path), headers={'Cache-Control': 'no-store'})

    @app.get('/data-inventory-assets/{name}')
    def assets(name: str):
        if name not in ('data-inventory.js', 'data-inventory.css'):
            raise HTTPException(404)
        return FileResponse(Path(__file__).parent / 'web' / name)

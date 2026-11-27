"""Conversation CRUD, file upload/download, release ledger, and UI asset routes for team server."""
import hashlib
import html
import json
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response

from .protocol import MAX_FILE, relative_name

_BUNDLE_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$')
_ALLOWED_BUNDLE_EXTS = frozenset(('.js', '.css', '.json', '.map'))
_BUNDLE_MEDIA_TYPES = {
    '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.map': 'application/json; charset=utf-8',
}

_ALLOWED_ASSETS = frozenset((
    'password-auth.js', 'admin-usage.js', 'admin-usage.css', 'shared-knowledge.js',
    'shared-knowledge.css', 'admin-users.js', 'admin-users.css', 'email-auth.js',
    'profile.js', 'profile.css', 'registration.js', 'registration.css', 'app.js',
    'drafts.js', 'research-plan.js', 'recovery.js', 'versions.js', 'versions.css',
    'style.css', 'defaults.js', 'defaults.css', 'memorax.js', 'memorax.css',
    'hitl.js', 'library.js', 'library.css', 'model-profiles.css', 'knowledge.js',
    'knowledge.css', 'images.js', 'images.css', 'presentation.js', 'presentation.css',
    'presentation-state.js', 'timeline.js', 'timeline.css', 'citations.js',
    'citations.css', 'bogao-wordmark.svg', 'bogao-symbol.svg',
))


def install_conversation_and_asset_routes(
    app,
    *,
    store,
    auth,
    limited_body,
    guard,
    jobs,
    assets,
    release_build,
    archival_run_view,
):
    @app.get('/api/conversations')
    def conversations(request: Request):
        return store.conversations(auth(request)['id'])

    @app.get('/api/active-tasks')
    def active_tasks(request: Request):
        uid = auth(request)['id']
        tasks = [{key: run[key] for key in ('id', 'cid', 'title', 'query', 'status', 'created', 'elapsed_seconds')}
                 for run in store.active_runs(uid)]
        return {'tasks': tasks, 'requests': store.pending_inputs(uid)}

    @app.post('/api/conversations')
    def new_conversation(request: Request):
        return store.create_conversation(auth(request, mutate=True)['id'])

    @app.get('/api/conversations/{cid}')
    def conversation(cid: str, request: Request):
        uid = auth(request)['id']
        return {**store.conversation(uid, cid),
                'runs': [archival_run_view(uid, run) for run in store.runs(uid, cid)]}

    @app.get('/api/conversations/{cid}/files')
    def files(cid: str, request: Request):
        uid = auth(request)['id']
        conv = store.conversation(uid, cid)
        return {'generation': conv['generation'], 'files': store.file_manifest(uid, cid)}

    @app.get('/api/conversations/{cid}/download')
    def download(cid: str, request: Request, name: str, generation: str = ''):
        uid = auth(request)['id']
        name = relative_name(name)
        raw = store.file(uid, cid, name, generation or None)
        if raw is None:
            raise HTTPException(404, 'File not found')
        return Response(raw, media_type='application/octet-stream', headers={
            'Content-Disposition': "attachment; filename*=UTF-8''" + quote(name.split('/')[-1], safe='')})

    @app.post('/api/conversations/{cid}/upload')
    async def upload(cid: str, request: Request, name: str):
        uid = auth(request, mutate=True)['id']
        store.conversation(uid, cid)
        name, raw = relative_name(name), await limited_body(request, MAX_FILE)
        with guard:
            if any(j['uid'] == uid for j in jobs.values()):
                raise HTTPException(409, 'Wait for your active task before changing its files')
            current = store.files(uid, cid)
            current[name] = raw
            generation = store.snapshot(uid, cid, current, origins={
                name: {"origin": "user_supplied", "sha256": hashlib.sha256(raw).hexdigest(),
                       "scope": "uploaded by the authenticated caller; not independently verified"}}, action='upload')
        return {'ok': True, 'generation': generation}

    @app.get('/api/admin/releases')
    def release_history(request: Request):
        auth(request, admin=True)
        build = release_build
        try:
            ledger = json.loads((store.root / 'release-history.json').read_bytes())
            if ledger.get('schema') != 1 or not isinstance(ledger.get('entries'), list):
                raise ValueError('Unsupported release history')
            entries = ledger['entries']
            current = next((entry for entry in entries if entry['build'][:12] == build), None)
        except FileNotFoundError:
            entries, current = [], None
        except (AttributeError, KeyError, OSError, TypeError, ValueError):
            raise HTTPException(503, '版本记录暂时无法读取') from None
        return {'build': build, 'version': current['version'] if current else None,
                'entries': list(reversed(entries))}

    @app.get('/admin/usage')
    @app.get('/admin/users')
    @app.get('/')
    def index():
        verification = app.state.verification_service
        registration = app.state.registration_service
        profile_service = app.state.profile_service
        email_service = app.state.email_service
        settings = verification.settings if verification is not None else None
        config = {'mode': registration.policy.mode,
                  'email_enabled': email_service is not None,
                  'phone_binding_enabled': profile_service.policy.phone_binding_enabled,
                  'digits': settings.digits if settings else 6,
                  'cooldown': settings.cooldown if settings else 60,
                  'allowed_regions': settings.allowed_regions if settings else ('CN',),
                  'default_region': settings.default_region if settings else None}
        page = (assets / 'index.html').read_text(encoding='utf-8')
        return Response(page.replace('__REGISTRATION_UI_CONFIG__', html.escape(json.dumps(config), quote=True)), media_type='text/html')

    @app.get('/assets/bundles/{name}')
    def bundle_asset(name: str):
        if not _BUNDLE_NAME_RE.match(name) or '..' in name:
            raise HTTPException(404)
        bundle_root = (assets / 'bundles').resolve()
        candidate = (bundle_root / name).resolve()
        if (
            candidate.parent != bundle_root
            or candidate.suffix not in _ALLOWED_BUNDLE_EXTS
            or not candidate.is_file()
        ):
            raise HTTPException(404)
        return FileResponse(candidate, media_type=_BUNDLE_MEDIA_TYPES[candidate.suffix])

    @app.get('/assets/{name}')
    def asset(name: str):
        if name not in _ALLOWED_ASSETS:
            raise HTTPException(404)
        return FileResponse(assets / name)

    @app.get('/vendor/katex.min.js')
    def math_renderer():
        return FileResponse(Path(__file__).parent.parent / 'web/vendor/katex.min.js')

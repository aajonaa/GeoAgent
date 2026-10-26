"""Research-group accounts, owner-scoped HTTP/SSE, and isolated native runs."""
import argparse
import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import replace
import getpass
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import secrets
import sqlite3
from threading import BoundedSemaphore, Event, RLock, Thread
import time
from urllib.parse import quote

import httpx

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from ..llm import LocalChatClient
from ..tracing import configured_trace
from .isolation import Cancelled, SandboxRunner
from .protocol import MAX_FILE, relative_name, scrub
from .pdf_imports import MAX_PDF
from .store import SESSION_SECONDS, Store
from .model_settings import EndpointPolicy, SessionModels, builtin_profile, profile_client, probe_model, redact, trace_credentials, provider_error_details, model_endpoint_error
from .trusted import TrustedLocalRunner
from .model_vault import ModelVaultError
from .streaming import RunProgress, consume_model_stream

COOKIE = 'geotool_team_session'


def create_app(root=None, *, runner=None, model_factory=None, trace_factory=None, profile_factory=None, memory_client_factory=None, memory_summarizer=None):
    root = Path(root or os.environ.get('GEOTOOL_TEAM_STATE', Path.home() / '.local/state/geotoolagent-team'))
    store = Store(root)
    mode = os.environ.get('GEOTOOL_TEAM_EXECUTION', 'sandbox')
    if mode not in ('sandbox', 'trusted'):
        raise ValueError('GEOTOOL_TEAM_EXECUTION must be sandbox or trusted; automatic fallback is forbidden')
    if runner is None:
        runner = TrustedLocalRunner(store.root / 'trusted-jobs') if mode == 'trusted' else SandboxRunner()
    isolated = getattr(runner, 'isolated', False)
    builtin = builtin_profile()
    secret_values = trace_credentials(builtin)
    policy = EndpointPolicy(builtin.base_url, os.environ.get('GEOTOOL_MODEL_ALLOWED_ORIGINS', '').split(','))
    model_settings = SessionModels(store, builtin, policy)
    probing = set()

    def new_model(profile, *, probe=False):
        if profile.source == 'builtin' and model_factory is not None:
            return model_factory()
        if profile.source == 'custom' and profile_factory is not None:
            return profile_factory(profile, probe=probe)
        return profile_client(profile, policy, probe=probe)

    async def expire_model_settings():
        while True:
            await asyncio.sleep(60)
            model_settings.prune()
    guard, jobs, buckets = RLock(), {}, {}
    model_slots, auth_slots = BoundedSemaphore(2), BoundedSemaphore(2)
    assets = Path(__file__).parent / 'web'
    secure_cookie = os.environ.get('GEOTOOL_TEAM_SECURE_COOKIE', 'false').lower() == 'true'

    @asynccontextmanager
    async def lifespan(app):
        for rid in store.recover():
            await asyncio.to_thread(runner.stop, rid)
        expiry_task = asyncio.create_task(expire_model_settings())
        try:
            yield
        finally:
            await asyncio.to_thread(conversation_memory.close)
            expiry_task.cancel()
            with suppress(asyncio.CancelledError):
                await expiry_task
            model_settings.clear()
        with guard:
            pending = list(jobs.values())
        for job in pending:
            job['cancel'].set()
        for job in pending:
            await asyncio.to_thread(job['thread'].join, 8)

    app = FastAPI(title='GeoToolAgent Research Group', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.jobs, app.state.runner = store, jobs, runner
    app.state.model_settings = model_settings

    def safe(value):
        return scrub(value, secret_values)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({'detail': 'Resource not found'}, status_code=404)

    @app.exception_handler(PermissionError)
    async def unauthorized(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=401)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({'detail': safe(str(exc))}, status_code=400)

    from ..svg_preview import SVG_CSP

    @app.middleware('http')
    async def boundary(request, call_next):
        origin = request.headers.get('origin')
        if request.url.hostname not in ('localhost', '127.0.0.1') or (origin and origin.rstrip('/') != str(request.base_url).rstrip('/')):
            return JSONResponse({'detail': 'Use your private SSH tunnel and same-origin requests'}, status_code=403)
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': 'Cross-site request rejected'}, status_code=403)
        # Only the authenticated PDF byte-upload route accepts the PDF limit.
        # Its handler additionally bounds actual streamed bytes and declared size.
        pdf_upload = request.method == 'PUT' and re.fullmatch(
            r'/api/knowledge/pdf/jobs/[a-f0-9]{32}/file', request.url.path)
        request_limit = MAX_PDF if pdf_upload else MAX_FILE
        try:
            if int(request.headers.get('content-length', '0')) > request_limit:
                return JSONResponse({'detail': f'Request exceeds {request_limit // (1024 * 1024)} MiB'}, status_code=413)
        except ValueError:
            return JSONResponse({'detail': 'Invalid content length'}, status_code=400)
        response = await call_next(request)
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
            'Content-Security-Policy': (SVG_CSP if response.headers.get('content-type', '').split(';')[0].strip() == 'image/svg+xml' else "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")})
        return response

    def auth(request, *, mutate=False, admin=False):
        model_settings.prune()
        user = store.authenticate(request.cookies.get(COOKIE, ''))
        if mutate and not secrets.compare_digest(request.headers.get('x-csrf-token', ''), user['csrf']):
            raise HTTPException(403, 'CSRF validation failed')
        if admin and user['role'] != 'admin':
            raise HTTPException(403, 'Administrator access required')
        return user

    async def body(request):
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            raise HTTPException(415, 'Use application/json')
        raw = await limited_body(request, 256 * 1024)
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise HTTPException(400, 'Invalid JSON')
        if not isinstance(value, dict):
            raise HTTPException(400, 'Expected a JSON object')
        return value

    async def limited_body(request, limit):
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, 'Request body limit exceeded')
            chunks.append(chunk)
        return b''.join(chunks)

    def rate_limit(request, username):
        now = time.monotonic()
        keys = [('ip', request.client.host if request.client else 'unknown', 30), ('name', str(username).lower(), 8)]
        with guard:
            expired = [key for key, values in buckets.items() if not values or values[-1] < now - 60]
            for key in expired:
                del buckets[key]
            for kind, value, limit in keys:
                key = kind + ':' + value
                attempts = [t for t in buckets.get(key, []) if t > now - 60]
                if len(attempts) >= limit or len(buckets) > 2048:
                    raise HTTPException(429, 'Too many sign-in attempts. Please wait a minute.')
                buckets[key] = attempts + [now]

    async def expensive_auth(function, *args, **kwargs):
        if not auth_slots.acquire(blocking=False):
            raise HTTPException(429, 'Sign-in service is busy; try again shortly')
        try:
            return await asyncio.to_thread(function, *args, **kwargs)
        finally:
            auth_slots.release()

    @app.get('/api/me')
    def me(request: Request):
        user = auth(request)
        return {**user, 'release': os.environ.get('GEOTOOL_RELEASE', 'team-candidate'),
                'trace_content_enabled': os.environ.get('GEOTOOL_LANGSMITH_CAPTURE_CONTENT', '').lower() == 'true',
                'execution': getattr(runner, 'description', 'test runner'), 'isolated': isolated,
                'execution_notice': ('System sandbox enabled' if isolated else 'Trusted members only: OS isolation is disabled; generated code runs with the service account permissions'),
                'publication': 'progress events + reviewed final answer'}

    @app.post('/api/login')
    async def login(request: Request):
        data = await body(request)
        username, password = data.get('username', ''), data.get('password', '')
        if not isinstance(username, str) or not isinstance(password, str):
            raise HTTPException(400, 'Invalid credentials format')
        rate_limit(request, username)
        token, csrf = await expensive_auth(store.login, username, password)
        response = JSONResponse({'ok': True, 'csrf': csrf})
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict', secure=secure_cookie, max_age=SESSION_SECONDS, path='/')
        return response

    @app.post('/api/register')
    async def register(request: Request):
        data = await body(request)
        if not all(isinstance(data.get(k), str) for k in ('username', 'password', 'invite')):
            raise HTTPException(400, 'Username, password and invitation are required')
        rate_limit(request, data['username'])
        try:
            await expensive_auth(store.create_user, data['username'], data['password'], invite=data['invite'])
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Username is unavailable')
        return {'ok': True}

    @app.post('/api/logout')
    def logout(request: Request):
        auth(request, mutate=True)
        model_settings.forget(request.cookies.get(COOKIE, ''))
        store.logout(request.cookies.get(COOKIE, ''))
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE, path='/')
        return response

    @app.post('/api/password')
    async def password(request: Request):
        user = auth(request, mutate=True)
        data = await body(request)
        rate_limit(request, user['username'])
        await expensive_auth(store.change_password, user['id'], data.get('old', ''), data.get('new', ''))
        model_settings.prune()
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE, path='/')
        return response

    @app.get('/api/settings/model-defaults')
    def get_model_defaults(request: Request):
        auth(request)
        return model_settings.get_defaults(request.cookies.get(COOKIE, ''))

    @app.put('/api/settings/model-defaults')
    async def save_model_defaults(request: Request):
        auth(request, mutate=True)
        return model_settings.save_defaults(request.cookies.get(COOKIE, ''), await body(request))

    @app.get('/api/model-settings')
    def get_model_settings(request: Request):
        auth(request)
        try:
            public = model_settings.public(request.cookies.get(COOKIE, ''))
        except ModelVaultError as exc:
            return {**builtin.public(), 'storage': 'account_unavailable',
                    'storage_error': str(exc), 'saved_profiles': [],
                    'builtin': builtin.public()}
        return {**public, 'builtin': builtin.public()}

    @app.delete('/api/model-settings')
    def delete_model_settings(request: Request):
        auth(request, mutate=True)
        profile = model_settings.delete(request.cookies.get(COOKIE, ''))
        return {**profile.public(), 'builtin': builtin.public()}

    @app.put('/api/model-settings')
    async def save_model_settings(request: Request):
        auth(request, mutate=True)
        profile = model_settings.save(request.cookies.get(COOKIE, ''), await body(request))
        return {**profile.public(), 'builtin': builtin.public()}

    @app.post('/api/model-settings/activate')
    async def activate_model_settings(request: Request):
        auth(request, mutate=True)
        data = await body(request)
        if set(data) != {'profile_id'}:
            raise ValueError('Choose one saved connection')
        profile = model_settings.activate(request.cookies.get(COOKIE, ''), data['profile_id'])
        return {**profile.public(), 'builtin': builtin.public()}

    @app.delete('/api/model-settings/profiles/{profile_id}')
    async def delete_model_profile(profile_id: str, request: Request):
        auth(request, mutate=True)
        data = await body(request)
        if set(data) != {'revision'}:
            raise ValueError('Connection revision is required')
        profile = model_settings.remove(request.cookies.get(COOKIE, ''), profile_id, data['revision'])
        return {**profile.public(), 'builtin': builtin.public()}

    @app.post('/api/model-settings/test')
    async def test_model_settings(request: Request):
        user = auth(request, mutate=True)
        profile = model_settings.parse(request.cookies.get(COOKIE, ''), await body(request))
        with guard:
            if user['id'] in probing or not model_slots.acquire(blocking=False):
                raise HTTPException(429, 'A connection test or both model slots are busy; try again later')
            probing.add(user['id'])

        def check():
            client = None
            try:
                client = new_model(profile, probe=True)
                return probe_model(client)
            finally:
                if client is not None:
                    client.close()

        try:
            return await asyncio.to_thread(check)
        except Exception as exc:
            # Return only credential-masked, whitelisted provider diagnostics.
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            details = provider_error_details(exc, trace_credentials(profile))
            return JSONResponse({'ok': False, 'error': type(exc).__name__, 'http_status': status,
                'provider_error': details,
                'message': '连接或原生工具调用检查未通过。请核对 Endpoint、Token、Model ID，以及模型对 required/auto 工具调用的支持。' +
                           (' Provider: ' + str(details['message']) if details.get('message') else '')}, status_code=400)
        finally:
            with guard:
                probing.discard(user['id'])
            model_slots.release()

    @app.post('/api/admin/invites')
    def invite(request: Request):
        auth(request, mutate=True, admin=True)
        return {'token': store.invite(), 'expires_in': 86400, 'role': 'member'}

    @app.get('/api/conversations')
    def conversations(request: Request):
        return store.conversations(auth(request)['id'])

    @app.post('/api/conversations')
    def new_conversation(request: Request):
        return store.create_conversation(auth(request, mutate=True)['id'])

    @app.get('/api/conversations/{cid}')
    def conversation(cid: str, request: Request):
        uid = auth(request)['id']
        return {**store.conversation(uid, cid), 'runs': store.runs(uid, cid)}

    @app.get('/api/conversations/{cid}/files')
    def files(cid: str, request: Request):
        uid = auth(request)['id']
        conv = store.conversation(uid, cid)
        return {'generation': conv['generation'], 'files': [{'name': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                for name, raw in store.files(uid, cid).items()]}

    @app.get('/api/conversations/{cid}/download')
    def download(cid: str, request: Request, name: str, generation: str = ''):
        uid = auth(request)['id']
        name = relative_name(name)
        available = store.files(uid, cid, generation or None)
        if name not in available:
            raise HTTPException(404, 'File not found')
        return Response(available[name], media_type='application/octet-stream', headers={
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
                       "scope": "uploaded by the authenticated caller; not independently verified"}})
        return {'ok': True, 'generation': generation}

    def model_call(request, cancel, profile, progress):
        run_secrets = (*secret_values, *trace_credentials(profile, {}))
        call = progress.begin_model()
        while not model_slots.acquire(timeout=0.2):
            if cancel.is_set():
                raise Cancelled('Stopped while waiting for the shared model')
        result = queue.Queue(maxsize=1)

        def invoke():
            client = None
            try:
                client = new_model(profile)
                # Protocol values are executable data, not a logging copy.
                # Credentials are transport headers; traces, UI and exceptions
                # are masked separately at their existing publication boundaries.
                result.put((True, consume_model_stream(client, request, progress, call, cancel)))
            except Exception as exc:
                if isinstance(exc, httpx.HTTPError):
                    exc = RuntimeError(model_endpoint_error(exc, run_secrets))
                else:
                    exc.args = tuple(redact(arg, run_secrets) for arg in exc.args)
                result.put((False, exc))
            finally:
                try:
                    if client is not None:
                        client.close()
                finally:
                    model_slots.release()

        Thread(target=invoke, daemon=True).start()
        while True:
            if cancel.is_set():
                raise Cancelled('Stopped by user; the in-flight model request is being drained')
            try:
                ok, value = result.get(timeout=0.2)
            except queue.Empty:
                continue
            if not ok:
                raise value
            return value

    def summarize_conversation(request, profile, cancel):
        if memory_summarizer is not None:
            return memory_summarizer(request, profile, cancel)
        while not model_slots.acquire(timeout=0.2):
            if cancel.is_set():
                raise Cancelled('Memory summarization cancelled')
        client = None
        try:
            if cancel.is_set():
                raise Cancelled('Memory summarization cancelled')
            client = new_model(replace(profile, max_output_tokens=min(2048, profile.max_output_tokens)))
            progress = RunProgress(lambda event: None, trace_credentials(profile, {}))
            call = progress.begin_model()
            return consume_model_stream(client, request, progress, call, cancel)
        finally:
            try:
                if client is not None:
                    client.close()
            finally:
                model_slots.release()

    def execute(uid, cid, rid, query, cancel, profile):
        run_secrets = (*secret_values, *trace_credentials(profile, {}))
        run_safe = lambda value: scrub(redact(value, run_secrets), run_secrets)
        progress = RunProgress(lambda data: store.event(rid, data), run_secrets)
        trace_path = store.root / 'traces' / (rid + '.jsonl')
        trace_path.parent.mkdir(mode=0o700, exist_ok=True)
        inner = trace_factory(trace_path) if trace_factory else configured_trace(trace_path, secrets=run_secrets)
        if hasattr(inner, 'set_model'):
            inner.set_model(profile.model, 'vllm' if profile.source == 'builtin' else 'openai-compatible')

        def on_trace(kind, fields):
            fields = redact(fields, run_secrets)
            inner.emit(kind, **fields)
            clean = run_safe(fields)
            progress.observe(kind, clean)
            # Only provider-returned process text, after the existing credential
            # redaction. Never publish prompts, rejected answers or review drafts.
            from .timeline import process_event
            display_fields = {**clean, 'phase': progress.model_phase} if kind == 'model_responded' else clean
            display_event = None if kind == 'model_responded' and progress.streamed_process else process_event(kind, display_fields)
            if display_event is not None:
                store.event(rid, display_event)
            if kind == 'tool_requested':
                call = clean['call']
                store.event(rid, {'kind': 'tool_start', 'id': call['id'], 'name': call['name'], 'arguments': call['arguments']})
            elif kind in ('tool_completed', 'tool_failed'):
                result = clean['result']
                store.event(rid, {'kind': 'tool_result', 'id': result['call_id'], 'name': result['name'], 'result': result,
                                  'duration_seconds': progress.tool_durations.get(result['call_id'])})
            elif kind == 'context_compacted':
                store.event(rid, {'kind': 'context_compacted', 'before_chars': fields['before_chars'],
                                 'after_chars': fields['after_chars'], 'phase': fields['phase'],
                                 'strategies': fields['strategies']})
            elif kind == 'knowledge_completed':
                # Preserve the retrieval receipt, not a model-written bibliography.
                payload = clean.get('result', {})
                store.event(rid, {'kind': 'knowledge_sources',
                                 'references': payload.get('references', [])})
            elif kind in ('model_requested', 'completion_review_requested', 'completion_rejected', 'model_protocol_error', 'completion_review_protocol_error'):
                labels = {'model_requested': 'Compacting context' if fields.get('phase') == 'context_compaction' else 'Preparing answer' if fields.get('phase') == 'final_answer' else 'Model is working',
                          'completion_review_requested': 'Checking the result', 'completion_rejected': 'Correcting the result',
                          'model_protocol_error': 'Correcting a model response', 'completion_review_protocol_error': 'Retrying the completion check'}
                store.event(rid, {'kind': 'status', 'message': labels[kind], 'turn': fields.get('turn'), 'phase': fields.get('phase')})

        try:
            store.event(rid, {'kind': 'status', 'message': 'Starting an isolated task environment' if isolated else 'Running in the service account environment (OS isolation disabled)'})
            query_context = conversation_memory.context(uid, cid, query, profile)
            memory = memory_service.recall(uid, cid, query, supported=bool(getattr(runner, 'memory_snapshot_enabled', False)))
            if memory['status'] != 'disabled':
                store.event(rid, {'kind': 'memory_status', 'status': memory['status'],
                                  'count': len(memory['records']), 'project_id': memory.get('project_id')})
            result = runner.run(rid, query_context, store.files(uid, cid), cancel,
                                lambda request, event: model_call(request, event, profile, progress), on_trace,
                                diagnostics=store.root / 'traces' / (rid + '.stderr.log'),
                                settings={**profile.runtime_settings(), **({'memory_enabled': True} if memory['records'] else {})},
                                **({'memory_records': memory['records']} if memory['records'] else {}),
                                **({'input_origins': store.file_origins(uid, cid)}
                                   if getattr(runner, 'provenance_enabled', False) else {}),
                                **({'context_scope': {'owner_id': uid, 'conversation_id': cid}}
                                   if getattr(runner, 'context_archive_enabled', False) else {}))
            if cancel.is_set():
                raise Cancelled('Stopped before file commit; the previous files are unchanged')
            progress.switch('publishing')
            with guard:
                generation = store.snapshot(uid, cid, result['files'], origins=result.get('file_origins'))
                progress.close()
                store.finish(rid, status=result['status'], answer=run_safe(result['answer']), reason=run_safe(result.get('reason', '')),
                             generation=generation, turns=result.get('turns', 0))
        except Cancelled as exc:
            progress.close()
            inner.emit('team_cancelled', error=run_safe(str(exc)))
            store.finish(rid, status='stopped', reason=run_safe(str(exc)))
        except Exception as exc:
            progress.close()
            reason = run_safe(f'{type(exc).__name__}: {exc}')
            inner.emit('team_failed', error=reason)
            store.finish(rid, status='failed', reason=reason)
        finally:
            with guard:
                jobs.pop(rid, None)
            with suppress(Exception):
                conversation_memory.submit(uid, profile)

    def launch(uid, cid, query, profile, *, expected_input=None):
        store.conversation(uid, cid)
        if not isinstance(query, str) or not query.strip() or len(query) > 20000:
            raise HTTPException(400, 'Provide a task of 1 to 20,000 characters')
        with guard:
            if len(jobs) >= 2:
                raise HTTPException(409, 'Both execution slots are busy; try again when a task finishes')
            # A human-input reply resumes an existing graph, not a fresh task.
            with store.lock:
                pending = store.db.execute("SELECT origin_rid,payload FROM input_requests WHERE cid=? AND state='pending'", (cid,)).fetchone()
                if pending:
                    prior = [json.loads(row[0]) for row in store.db.execute("SELECT data FROM events WHERE rid=? ORDER BY seq", (pending[0],))]
                    expected = next((item['profile'] for item in prior if item.get('kind') == 'model_config'), builtin.identity())
                    payload = json.loads(pending["payload"])
                    protocol_recovery = (payload.get("reason_type") == "model_protocol" and
                                         payload.get("recovery_origin") == "runtime")
                    # Older events store identity only; newer snapshots also
                    # contain execution limits. Compare the same identity keys.
                    expected_identity = {key: expected.get(key) for key in profile.identity()}
                    if profile.identity() != expected_identity and not protocol_recovery:
                        raise HTTPException(409, '这段任务仍在等待回复。请恢复原来的模型配置再继续，或新建对话使用新模型。已记住的配置会自动恢复；仅本次登录的配置需重新填写。')
            try:
                rid = store.begin(uid, cid, query.strip(), expected_input=expected_input)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            store.event(rid, {'kind': 'model_config', 'profile': profile.run_snapshot(), 'context_budget': profile.context_budget()})
            conversation_memory.capture(uid, cid, rid)
            cancel = Event()
            thread = Thread(target=execute, args=(uid, cid, rid, query.strip(), cancel, profile), daemon=True)
            jobs[rid] = {'uid': uid, 'cancel': cancel, 'thread': thread}
            thread.start()
        return {'id': rid}

    @app.post('/api/conversations/{cid}/runs')
    async def start(cid: str, request: Request):
        uid = auth(request, mutate=True)['id']
        data = await body(request)
        profile = model_settings.get(request.cookies.get(COOKIE, ''))
        return launch(uid, cid, data.get('query', ''), profile)

    def pending_input(uid, request_id, cid, rid):
        if not all(isinstance(value, str) and value for value in (request_id, cid, rid)):
            raise HTTPException(400, 'Provide the conversation, run, and question identifiers')
        try:
            return store.input_request(uid, request_id, cid=cid, rid=rid, pending=True)
        except KeyError as exc:
            raise HTTPException(404, 'Input request not found') from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post('/api/hitl/requests/{request_id}/reply')
    async def reply_to_input(request_id: str, request: Request):
        uid = auth(request, mutate=True)['id']
        data = await body(request)
        if set(data) != {'cid', 'rid', 'text'}:
            raise HTTPException(400, 'Expected cid, rid, and text')
        profile = model_settings.get(request.cookies.get(COOKIE, ''))
        with guard, store.lock:
            pending_input(uid, request_id, data['cid'], data['rid'])
            return launch(uid, data['cid'], data['text'], profile,
                          expected_input=(request_id, data['rid']))

    @app.post('/api/hitl/requests/{request_id}/upload')
    async def upload_for_input(request_id: str, request: Request, cid: str, rid: str, name: str):
        uid = auth(request, mutate=True)['id']
        # Authenticate ownership before consuming a potentially large file.
        pending_input(uid, request_id, cid, rid)
        name, raw = relative_name(name), await limited_body(request, MAX_FILE)
        with guard, store.lock:
            pending_input(uid, request_id, cid, rid)
            if any(job['uid'] == uid for job in jobs.values()):
                raise HTTPException(409, 'Wait for your active task before changing its files')
            current = store.files(uid, cid)
            current[name] = raw
            generation = store.snapshot(uid, cid, current, origins={
                name: {"origin": "user_supplied", "sha256": hashlib.sha256(raw).hexdigest(),
                       "scope": "uploaded by the authenticated caller; not independently verified"}})
        return {'ok': True, 'name': name, 'generation': generation}

    @app.get('/api/runs/{rid}')
    def run(rid: str, request: Request):
        return store.run(auth(request)['id'], rid)

    @app.post('/api/runs/{rid}/stop')
    def stop(rid: str, request: Request):
        uid = auth(request, mutate=True)['id']
        store.run(uid, rid)
        with guard:
            job = jobs.get(rid)
            if job:
                job['cancel'].set()
                store.event(rid, {'kind': 'status', 'message': 'Stopping the task; keeping the last committed files'})
        return {'ok': True}

    @app.get('/api/runs/{rid}/history')
    def run_history(rid: str, request: Request, after: int = 0, through: int | None = None, limit: int = 60):
        return store.history(auth(request)['id'], rid, after=after, through=through, limit=limit)

    @app.get('/api/runs/{rid}/events')
    async def events(rid: str, request: Request, after: int = 0):
        uid = auth(request)['id']
        store.run(uid, rid)
        try:
            after = max(after, int(request.headers.get('last-event-id', '0')))
        except ValueError:
            raise HTTPException(400, 'Invalid event cursor')

        async def stream():
            cursor, ticks = after, 0
            while not await request.is_disconnected():
                try:
                    # Logout/expiry invalidates existing streams, not just new requests.
                    store.authenticate(request.cookies.get(COOKIE, ''))
                except PermissionError:
                    return
                rows = store.events(uid, rid, cursor)
                for row in rows:
                    cursor = row['id']
                    yield 'id: ' + str(cursor) + '\ndata: ' + json.dumps(row['data'], ensure_ascii=False) + '\n\n'
                run = store.run(uid, rid)
                if run['status'] not in ('running', 'stopping') and not rows:
                    return
                ticks += 1
                if ticks % 40 == 0:
                    yield ': keep-alive\n\n'
                await asyncio.sleep(0.25)
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no'})

    @app.get('/')
    def index():
        return FileResponse(assets / 'index.html')

    @app.get('/assets/{name}')
    def asset(name: str):
        if name not in ('app.js', 'style.css', 'defaults.js', 'defaults.css', 'memorax.js', 'memorax.css', 'hitl.js', 'library.js', 'library.css', 'model-profiles.css', 'knowledge.js', 'knowledge.css', 'images.js', 'images.css', 'presentation.js', 'presentation.css', 'presentation-state.js', 'timeline.js', 'timeline.css', 'citations.js', 'citations.css'):
            raise HTTPException(404)
        return FileResponse(assets / name)

    @app.get('/vendor/katex.min.js')
    def math_renderer():
        return FileResponse(Path(__file__).parent.parent / 'web/vendor/katex.min.js')

    from .hitl import install_input_routes
    install_input_routes(app)
    from .library import install_library_routes
    install_library_routes(app, auth, human_input=bool(getattr(runner, 'hitl_enabled', False)))
    from .knowledge import install_knowledge_routes
    install_knowledge_routes(app, auth, body)
    from .images import install_image_routes
    install_image_routes(app, auth, store)
    from .presentation import install_presentation_routes
    install_presentation_routes(app, auth, store)
    from .memorax import install_memory_routes
    memory_service = install_memory_routes(app, auth, body, store, client_factory=memory_client_factory)
    from .conversation_memory import ConversationMemory
    conversation_memory = ConversationMemory(store, memory_service, summarize_conversation)
    app.state.conversation_memory = conversation_memory

    @app.get('/api/settings/memory/status')
    def automatic_memory_status(request: Request):
        return conversation_memory.status(auth(request)['id'])

    @app.get('/api/conversations/{cid}/memory/summary')
    def conversation_summary(cid: str, request: Request):
        return conversation_memory.snapshot(auth(request)['id'], cid)
    return app


def main():
    parser = argparse.ArgumentParser(description='Private research-group GeoToolAgent')
    parser.add_argument('--state', default=os.environ.get('GEOTOOL_TEAM_STATE', str(Path.home() / '.local/state/geotoolagent-team')))
    commands = parser.add_subparsers(dest='command', required=True)
    admin = commands.add_parser('create-admin')
    admin.add_argument('--username', required=True)
    disable = commands.add_parser('disable-user')
    disable.add_argument('--username', required=True)
    serve = commands.add_parser('serve')
    serve.add_argument('--port', type=int, default=50014)
    args = parser.parse_args()
    os.umask(0o077)
    if args.command == 'create-admin':
        password = getpass.getpass('Administrator password (12+ characters): ')
        if password != getpass.getpass('Confirm password: '):
            raise SystemExit('Passwords do not match')
        Store(args.state).create_user(args.username, password, role='admin', initial_admin=True)
        print('Administrator created. Use the normal sign-in page; no access key is required.')
    elif args.command == 'disable-user':
        Store(args.state).disable(args.username)
        print('Member disabled and sessions revoked.')
    else:
        import uvicorn
        # One broker process owns the job table. Do not start multiple ASGI workers.
        uvicorn.run(create_app(args.state), host='127.0.0.1', port=args.port, proxy_headers=False)


if __name__ == '__main__':
    main()

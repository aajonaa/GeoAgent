"""Research-group accounts, owner-scoped HTTP/SSE, and isolated native runs."""
import argparse
import asyncio
from contextlib import asynccontextmanager, suppress
from contextvars import copy_context
from dataclasses import replace
import getpass
import hashlib
import html
import json
import logging
import os
from pathlib import Path
import queue
import re
import secrets
import sqlite3
from threading import BoundedSemaphore, Event, Lock, RLock, Thread
import time
import uuid
from urllib.parse import parse_qsl, quote, urlsplit

import httpx

from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool
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
from .streaming import RunProgress, consume_model_stream, retry_model_connection

from .capacity import read_capacity
from .reconciliation import Reconciler
from .recovery import Recovery, BrokerOwnershipError
from .shutdown import ShutdownCoordinator, lifecycle_server, observed_model_client

COOKIE = 'geotool_team_session'


class _ModelSlotLease:
    """One request's ownership of the existing shared semaphore, never a new pool."""

    def __init__(self, semaphore):
        self._semaphore = semaphore
        self._lock = Lock()
        self._state = 'new'

    def acquire(self, *args, **kwargs):
        # Only the initiating caller acquires; no worker exists at this stage.
        with self._lock:
            if self._state != 'new':
                raise RuntimeError('Model slot lease was already acquired')
        acquired = self._semaphore.acquire(*args, **kwargs)
        if acquired:
            with self._lock:
                self._state = 'reserved'
        return acquired

    def claim(self):
        with self._lock:
            if self._state != 'reserved':
                return False
            self._state = 'running'
            return True

    def _release(self, expected):
        with self._lock:
            if self._state != expected:
                return False
            self._semaphore.release()
            self._state = 'released'
            return True

    def abort_start(self):
        return self._release('reserved')

    def release(self):
        return self._release('running')


class _TaskStartup:
    """Per-run claim/abort fence; it does not count or allocate execution slots."""

    def __init__(self, uid, rid):
        self.uid, self.rid = uid, rid
        self._lock = Lock()
        self._state = 'reserved'

    def claim(self):
        with self._lock:
            if self._state != 'reserved':
                return False
            self._state = 'worker_owned'
            return True

    def _abort(self, expected):
        with self._lock:
            if self._state != expected:
                return False
            self._state = 'aborted'
            return True

    def abort_start(self):
        return self._abort('reserved')

    def fail_initialization(self):
        return self._abort('worker_owned')

    def is_aborted(self):
        with self._lock:
            return self._state == 'aborted'


class _TaskStartupError(HTTPException):
    """Readable legacy detail plus metadata for startup-failure reconciliation."""

    def __init__(self, code, rid, pending=None):
        messages = {
            'startup_reconciliation_pending': 'Task did not start; startup reconciliation is pending. Retry when storage is available.',
            'task_state_reconciliation_pending': 'The previous task has ended; its state is being reconciled.',
            'task_startup_failed': 'Task did not start; its startup failure was recorded.',
            'task_start_outcome_unknown': 'The startup response failed after worker ownership was handed off. Query this run before retrying.',
        }
        super().__init__(503, messages[code] + ' Run: ' + rid)
        self.payload = {'detail': self.detail, 'code': code, 'run_id': rid}
        if pending is not None:
            self.payload['reconciliation_pending'] = pending



_PLAN_TEXT_LIMITS = {'objective': 500, 'scope': 1000, 'materials': 1000, 'tools': 500, 'deliverables': 1000}


def _confirmed_research_plan(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {*_PLAN_TEXT_LIMITS, 'acceptance'}:
        raise HTTPException(400, 'Invalid confirmed research plan')
    plan = {}
    for field, limit in _PLAN_TEXT_LIMITS.items():
        text = value[field]
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > limit:
            raise HTTPException(400, 'Invalid confirmed research plan')
        plan[field] = text.strip()
    acceptance = value['acceptance']
    if not isinstance(acceptance, list) or not 1 <= len(acceptance) <= 5:
        raise HTTPException(400, 'Invalid confirmed acceptance criteria')
    plan['acceptance'] = []
    for item in acceptance:
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > 300:
            raise HTTPException(400, 'Invalid confirmed acceptance criteria')
        plan['acceptance'].append(item.strip())
    return plan


_RECOVERY_ACTIONS = {
    'follow_up': ({'completed'}, '请基于上一轮答复和已保存成果，进一步说明关键结论、支持依据、局限和仍待研究的问题。'),
    'derive': ({'completed'}, '请基于本轮已保存的答复和成果，整理一份新的研究内容，包含目标、方法、结果、证据和局限。引用已有文件名，不要删除或改写原成果；新增文件使用新名称。'),
    'resume': ({'stopped', 'cancelled', 'incomplete', 'budget_exhausted', 'interrupted'},
               '请先读取同一对话中上一轮运行的执行详情和已保存文件，核对已完成与未完成步骤，再从中断位置继续。不要重复已确认完成的工具调用，不要删除或改写原成果；新增文件使用新名称。'),
    'retry': ({'failed'},
              '请保留同一对话中的原始问题、执行上下文和已保存文件，重试上次失败的任务。先判断哪些结果可以复用，避免重复已完成工作；不要删除或改写原成果，新增文件使用新名称。'),
}


def _terminal_recovery_prompt(run, action):
    spec = _RECOVERY_ACTIONS.get(action) if isinstance(action, str) else None
    if spec is None:
        raise HTTPException(400, 'Invalid terminal recovery action')
    statuses, prompt = spec
    if run['status'] not in statuses:
        raise HTTPException(409, 'This recovery action does not match the run status')
    return prompt


_RECOVERY_CONTEXT_LIMIT = 12000
_RECOVERY_EVENT_FIELDS = {
    'status': ('message', 'phase', 'turn'),
    'tool_start': ('name', 'arguments'),
    'tool_result': ('name', 'result'),
    'knowledge_sources': ('sources',),
    'plan_confirmed': ('plan',),
    'skill_selected': ('skill',),
    'finished': ('status', 'reason', 'answer'),
}


_LEGACY_DEADLINE_REASON = 'TimeoutError: Managed task execution deadline exceeded'
_MANAGED_DEADLINE_REASON = '任务已达到执行时限。完整调研报告未完成。'


def _public_receipt_url(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or re.search(r'[\s\\\x00-\x1f\x7f]', value):
        return ''
    try:
        url = urlsplit(value)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
            return ''
        fields = parse_qsl(url.query, max_num_fields=60, keep_blank_values=True)
        if any(re.search(r'token|key|secret|password|signature|authorization|credential|^sig$', key, re.I)
               for key, _ in fields):
            return ''
        return quote(url._replace(fragment='').geturl(), safe="/:?&=%+#@,;!$'*~_-")
    except ValueError:
        return ''


def _receipt_label(value, default):
    if not isinstance(value, str):
        return default
    return ' '.join(re.sub(r'[\[\]<>]', ' ', value).split())[:180] or default


def _deadline_evidence(events):
    candidates, fetched, knowledge = {}, {}, {}
    for event in events:
        if event.get('kind') == 'knowledge_sources':
            for ref in event.get('references') or ():
                if isinstance(ref, dict) and re.fullmatch(r'K[0-9a-f]{16,64}_[0-9]+', str(ref.get('citation_id', ''))):
                    knowledge[ref['citation_id']] = _receipt_label(ref.get('title'), '知识库原文片段')
            continue
        receipt = event.get('result')
        if not isinstance(receipt, dict) or receipt.get('status') != 'ok':
            continue
        data = receipt.get('data')
        if not isinstance(data, dict):
            continue
        name = receipt.get('name') or event.get('name')
        if name == 'web_fetch' and isinstance(data.get('content'), str) and data['content'].strip():
            url = _public_receipt_url(data.get('url'))
            if url:
                fetched.setdefault(url, _receipt_label(data.get('title'), ''))
        if name == 'web_search':
            for item in data.get('results') or ():
                if isinstance(item, dict) and (url := _public_receipt_url(item.get('url'))):
                    candidates.setdefault(url, _receipt_label(item.get('title'), urlsplit(url).hostname))

    sections = []
    if fetched:
        links = [f"- [{title or candidates.get(url) or urlsplit(url).hostname}]({url})"
                 for url, title in list(fetched.items())[:8]]
        sections.append('### 已读取的网页\n\n' + '\n'.join(links))
    if knowledge:
        links = [f'- {title} [{cid}]' for cid, title in list(knowledge.items())[:8]]
        sections.append('### 已召回的知识库片段\n\n' + '\n'.join(links))
    leads = [(url, title) for url, title in candidates.items() if url not in fetched][:8]
    if leads:
        sections.append('### 检索候选（尚未核对）\n\n' + '\n'.join(f'- [{title}]({url})' for url, title in leads))
    if not sections:
        return ''
    intro = '## 超时前已保存的资料\n\n以下资料来自本轮已保存的回执，尚未形成经审核的调研结论。'
    return intro + '\n\n' + '\n\n'.join(sections)



def create_app(root=None, *, runner=None, model_factory=None, trace_factory=None, profile_factory=None, memory_client_factory=None, memory_summarizer=None, verification_factory=None, registration_policy=None, profile_policy=None, email_factory=None):
    root = Path(root or os.environ.get('GEOTOOL_TEAM_STATE', Path.home() / '.local/state/geotoolagent-team'))
    store = Store(root)
    mode = os.environ.get('GEOTOOL_TEAM_EXECUTION', 'sandbox')
    if mode not in ('sandbox', 'trusted'):
        raise ValueError('GEOTOOL_TEAM_EXECUTION must be sandbox or trusted; automatic fallback is forbidden')
    cpu_bridge_mode = os.environ.get('GEOTOOL_ISOLATED_CPU_PROCESS_OWNERSHIP', '0')
    if cpu_bridge_mode not in ('0', '1'):
        raise ValueError('GEOTOOL_ISOLATED_CPU_PROCESS_OWNERSHIP must be 0 or 1')
    if cpu_bridge_mode == '1' and (mode != 'sandbox' or os.environ.get('GEOTOOL_SANDBOX_PROCESS_OWNERSHIP') != '1'):
        raise ValueError('The isolated CPU candidate requires managed Sandbox execution')
    if runner is None:
        if cpu_bridge_mode == '1':
            from .cpu_bridge import IsolatedCpuBridgeRunner
            runner = IsolatedCpuBridgeRunner(cpu_profiles=os.environ['GEOTOOL_ISOLATED_CPU_PROFILES'], ownership_only=True)
        else:
            runner = TrustedLocalRunner(store.root / 'trusted-jobs') if mode == 'trusted' else SandboxRunner(
                ownership_only=os.environ.get('GEOTOOL_SANDBOX_PROCESS_OWNERSHIP') == '1')
    execution_policy = os.environ.get('GEOTOOL_EXECUTION_POLICY', 'standard')
    if execution_policy not in ('standard', 'restricted'):
        raise ValueError('GEOTOOL_EXECUTION_POLICY must be standard or restricted')
    if execution_policy == 'restricted' and (mode != 'sandbox'
            or not isinstance(runner, SandboxRunner)
            or os.environ.get('GEOTOOL_SANDBOX_PROCESS_OWNERSHIP') != '1'
            or getattr(runner, 'allow_dynamic_python', True)):
        raise ValueError('Restricted execution requires managed Sandbox and disabled dynamic Python')
    isolated = getattr(runner, 'isolated', False)
    recovery = Recovery(store, getattr(runner, 'recovery_scope', 'external_unknown'))
    shutdown = ShutdownCoordinator(recovery)
    process_ownership = None
    ownership_mode = os.environ.get('GEOTOOL_TRUSTED_PROCESS_OWNERSHIP', '0')
    sandbox_ownership_mode = os.environ.get('GEOTOOL_SANDBOX_PROCESS_OWNERSHIP', '0')
    if sandbox_ownership_mode not in ('0', '1'):
        raise ValueError('GEOTOOL_SANDBOX_PROCESS_OWNERSHIP must be 0 or 1')
    if ownership_mode not in ('0', '1'):
        raise ValueError('GEOTOOL_TRUSTED_PROCESS_OWNERSHIP must be 0 or 1')
    if ownership_mode == '1' or sandbox_ownership_mode == '1':
        if not isinstance(runner, (TrustedLocalRunner, SandboxRunner)):
            raise ValueError('Candidate process ownership requires a supported Runner')
        from .process_ownership import ProcessOwnership
        process_ownership = ProcessOwnership(recovery, os.environ['GEOTOOL_TRUSTED_PROCESS_CGROUP'])
        runner.process_ownership = recovery.process_resources = shutdown.process_resources = process_ownership
    builtin = builtin_profile()
    secret_values = trace_credentials(builtin)
    from .usage_audit import UsageAudit, current_context
    usage_audit = UsageAudit(store.root, secret_values)
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
    terminal_failures = {}
    startup_failures = {}  # Failed persistence only; never an execution-capacity counter.
    capacity = read_capacity()
    model_slots, auth_slots = BoundedSemaphore(capacity['model_slots']), BoundedSemaphore(2)
    # A locally terminal task with unconfirmed remote completion keeps one
    # slot out of circulation. Its signed receipt stays available for audit.
    shutdown.resources.reserve_slots = lambda: (
        len(shutdown.resources.quarantined) < capacity['model_slots'] - 1
        and model_slots.acquire(blocking=False)
    )
    assets = Path(__file__).parent / 'web'
    release_build = os.environ.get('GEOTOOL_RELEASE', 'team-candidate')
    # The managed launcher keeps the build hash outside the package and release label.
    deployment_root = assets.resolve().parents[3]
    try:
        deployment = json.loads((deployment_root / 'config.json').read_bytes())
        digest = deployment.get('source_sha256')
        if (deployment.get('root') == str(deployment_root)
                and deployment.get('state') == str(store.root)
                and isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest)):
            release_build = digest[:12]
    except (AttributeError, OSError, ValueError):
        pass
    secure_cookie = os.environ.get('GEOTOOL_TEAM_SECURE_COOKIE', 'false').lower() == 'true'

    @asynccontextmanager
    async def lifespan(app):
        first = shutdown.enter()
        owns_execution = activate_recovery()
        if owns_execution and first:
            reconciler.start()
            reconciler.attempt('__recovery_scan__', wait=True)
        expiry_task = asyncio.create_task(expire_model_settings())
        try:
            yield
        finally:
            last = shutdown.leave()
            expiry_task.cancel()
            try:
                await expiry_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                shutdown._event('expiry_close_error', error_type=type(exc).__name__)
            if last:
                shutdown.begin('lifespan')
                await shutdown.wait()

    app = FastAPI(title='GeoToolAgent Research Group', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.jobs, app.state.runner = store, jobs, runner
    app.state.terminal_failures = terminal_failures
    app.state.startup_failures = startup_failures
    app.state.recovery = recovery
    app.state.shutdown = shutdown
    app.state.process_ownership = process_ownership
    app.state.model_settings = model_settings
    app.state.capacity = capacity

    def safe(value):
        return scrub(value, secret_values)

    def _recovery_event_context(event):
        data = event['data']
        kind = data.get('kind')
        if kind not in _RECOVERY_EVENT_FIELDS:
            return None
        item = {'seq': event['id'], 'kind': kind}
        for field in _RECOVERY_EVENT_FIELDS[kind]:
            if field not in data:
                continue
            value = safe(data[field])
            encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
            item[field] = value if len(encoded) <= 1600 else {'preview': encoded[:1600] + '…'}
        return item

    def _terminal_recovery_context(uid, run):
        first = store.history(uid, run['id'], limit=60)
        events = list(first['events'])
        if first['has_more']:
            tail = store.history(uid, run['id'], after=max(0, first['through'] - 60),
                                 through=first['through'], limit=60)
            seen = {event['id'] for event in events}
            events.extend(event for event in tail['events'] if event['id'] not in seen)
        activity = safe(run.get('activity') or {})
        encoded_activity = json.dumps(activity, ensure_ascii=False, separators=(',', ':'))
        source = {
            'run_id': run['id'],
            'status': run['status'],
            'query': (run.get('query') or '')[:3000],
            'reason': (run.get('reason') or '')[:800],
            'answer': (run.get('answer') or '')[:3000],
            'generation': run.get('generation') or '',
            'activity': activity if len(encoded_activity) <= 1600 else {'preview': encoded_activity[:1600] + '…'},
            'events': [item for event in events if (item := _recovery_event_context(event)) is not None],
        }
        while len(json.dumps(source, ensure_ascii=False, separators=(',', ':'))) > _RECOVERY_CONTEXT_LIMIT and len(source['events']) > 1:
            source['events'].pop(len(source['events']) // 2)
        return safe(source)

    def _terminal_recovery_source(uid, cid, rid, action):
        if not isinstance(rid, str) or not re.fullmatch(r'[a-f0-9]{32}', rid):
            raise HTTPException(400, 'Invalid source run identifier')
        try:
            run = store.run(uid, rid)
        except KeyError as exc:
            raise HTTPException(404, 'Source run not found') from exc
        if run['cid'] != cid:
            raise HTTPException(409, 'Source run belongs to another conversation')
        run = archival_run_view(uid, run)
        _terminal_recovery_prompt(run, action)
        return run

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({'detail': 'Resource not found'}, status_code=404)

    @app.exception_handler(PermissionError)
    async def unauthorized(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=401)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({'detail': safe(str(exc))}, status_code=400)

    @app.exception_handler(_TaskStartupError)
    async def startup_error(request, exc):
        return JSONResponse(exc.payload, status_code=exc.status_code)

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
        if recovery.standby and request.method not in ('GET', 'HEAD') and request.url.path not in ('/api/login', '/api/logout'):
            try:
                auth(request, mutate=True)
            except HTTPException as exc:
                return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
            except PermissionError:
                return JSONResponse({'detail': 'Please sign in'}, status_code=401)
            return JSONResponse({'detail': 'This application view does not own task execution; use the active broker'}, status_code=503)
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

    async def body(request, limit=256 * 1024):
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            raise HTTPException(415, 'Use application/json')
        raw = await limited_body(request, limit)
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
        username=username.strip()
        rate_limit(request, username)
        token, csrf = await expensive_auth(store.login, username, password)
        response = JSONResponse({'ok': True, 'csrf': csrf})
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict', secure=secure_cookie, max_age=SESSION_SECONDS, path='/')
        return response

    @app.post('/api/register')
    async def register(request: Request):
        from .registration_service import RegistrationError
        from .verification_service import ServiceError
        from .registration_api import registration_response, registration_error
        from .verification_policy import client_ip
        try:
            registration.ensure_enabled()
            data = await body(request, limit=registration.policy.body_limit)
            rate_limit(request, data.get('username', ''))
            verification.edge_check(client_ip(request.client.host if request.client else None,
                                             request.headers.get('x-forwarded-for'), verification.settings))
            result = await expensive_auth(registration.register, data)
        except (RegistrationError, ServiceError) as exc:
            return registration_error(exc.code, exc.http_status)
        except HTTPException:
            raise
        except Exception:
            return registration_error('registration_unavailable', 503)
        # The business transaction has committed before any login/Cookie action.
        token = csrf = None
        try:
            token, csrf = await expensive_auth(store.login, result.username, data['password'])
        except Exception:
            # Keep committed account/facts; caller can use the existing login API.
            pass
        try:
            return registration_response(result, cookie_name=COOKIE, secure_cookie=secure_cookie, token=token, csrf=csrf)
        except Exception:
            # Lost response must not delete an account or retry its creation.
            return registration_error('registration_unavailable', 503)

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
        require_recovery_admission()
        profile = model_settings.parse(request.cookies.get(COOKIE, ''), await body(request))
        cancel = Event()
        record = shutdown.model_registered('probe', cancel, uid=user['id'])
        lease = _ModelSlotLease(model_slots)
        try:
            with guard:
                shutdown.require_admission()
                if user['id'] in probing or not lease.acquire(blocking=False):
                    raise HTTPException(429, f"A connection test or all {capacity['model_slots']} model slots are busy; try again later")
                probing.add(user['id'])
        except BaseException:
            shutdown.model_finished(record, lease_released=None)
            raise

        def check():
            if not lease.claim():
                return None
            client = None
            try:
                shutdown.model_started(record)
                client = new_model(profile, probe=True)
                client = usage_audit.client(client,uid=user['id'],category='connection_test',model=profile.model)
                observed = observed_model_client(client, record)
                class ProbeView:
                    def invoke(self, request):
                        if cancel.is_set():
                            raise Cancelled('Connection test cancelled before its next model request')
                        return observed.invoke(request)
                return probe_model(ProbeView())
            finally:
                try:
                    if client is not None:
                        try:
                            client.close()
                        except BaseException as exc:
                            record['cleanup_error_type'] = type(exc).__name__
                            raise
                finally:
                    with guard:
                        probing.discard(user['id'])
                    released = lease.release()
                    shutdown.model_finished(record, lease_released=released)

        def abort_check_start():
            if lease.abort_start():
                with guard:
                    probing.discard(user['id'])
                shutdown.model_finished(record, lease_released=True)

        def check_done(future):
            if future.cancelled():
                try:
                    cancel.set()
                except Exception as exc:
                    shutdown._event('probe_waiter_cancel_error', model_call_id=record['id'], error_type=type(exc).__name__)
                finally:
                    abort_check_start()
            else:
                future.exception()

        try:
            try:
                future = asyncio.get_running_loop().run_in_executor(None, copy_context().run, check)
            except BaseException:
                abort_check_start()
                raise
            future.add_done_callback(check_done)
            return await future
        except Exception as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            details = provider_error_details(exc, trace_credentials(profile))
            return JSONResponse({'ok': False, 'error': type(exc).__name__, 'http_status': status,
                'provider_error': details,
                'message': '连接或原生工具调用检查未通过。请核对 Endpoint、Token、Model ID，以及模型对 required/auto 工具调用的支持。' +
                           (' Provider: ' + str(details['message']) if details.get('message') else '')}, status_code=400)

    @app.post('/api/admin/invites')
    def invite(request: Request):
        auth(request, mutate=True, admin=True)
        return {'token': store.invite(), 'expires_in': 86400, 'role': 'member', 'max_uses': 50, 'used_count': 0, 'remaining': 50}

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

    def managed_deadline_outcome(uid, rid):
        try:
            evidence = _deadline_evidence(store.receipt_events(uid, rid))
        except Exception as exc:
            logging.getLogger(__name__).warning('Deadline receipt recovery failed: run=%s error_type=%s',
                                                rid, type(exc).__name__)
            evidence = ''
        return {'status': 'budget_exhausted', 'reason': _MANAGED_DEADLINE_REASON, 'answer': evidence}

    def archival_run_view(uid, run):
        if run['status'] == 'failed' and run['reason'] == _LEGACY_DEADLINE_REASON:
            recovered = managed_deadline_outcome(uid, run['id'])
            return {**run, **recovered, 'answer': run['answer'] or recovered['answer']}
        return run

    @app.get('/api/conversations/{cid}')
    def conversation(cid: str, request: Request):
        uid = auth(request)['id']
        return {**store.conversation(uid, cid),
                'runs': [archival_run_view(uid, run) for run in store.runs(uid, cid)]}

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

    def model_call(request, cancel, profile, progress, *, uid=None, rid=None):
        def on_retry(number):
            if rid is not None:
                store.event(rid, {'kind': 'status', 'message': 'Retrying a model connection',
                                  'attempt': number})

        return retry_model_connection(
            lambda: model_attempt(request, cancel, profile, progress, uid=uid, rid=rid), cancel, on_retry)

    def model_attempt(request, cancel, profile, progress, *, uid=None, rid=None):
        shutdown.require_admission()
        run_secrets = (*secret_values, *trace_credentials(profile, {}))
        call = progress.begin_model()
        lease = _ModelSlotLease(model_slots)
        result = queue.Queue(maxsize=1)
        record = shutdown.model_registered('task_model', cancel, uid=uid, run_id=rid)

        def invoke():
            if not lease.claim():
                return
            client = None
            try:
                shutdown.model_started(record)
                client = usage_audit.client(new_model(profile),uid=uid,rid=rid,category='task',model=profile.model)
                result.put((True, consume_model_stream(observed_model_client(client, record), request, progress, call, cancel), False))
            except Exception as exc:
                retryable = isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))
                if isinstance(exc, httpx.HTTPStatusError):
                    retryable = exc.response.status_code in (502, 503, 504)
                if isinstance(exc, httpx.HTTPError):
                    exc = RuntimeError(model_endpoint_error(exc, run_secrets))
                else:
                    exc.args = tuple(redact(arg, run_secrets) for arg in exc.args)
                result.put((False, exc, retryable and not call.get('received_response')))
            finally:
                try:
                    if client is not None:
                        try:
                            client.close()
                        except BaseException as exc:
                            record['cleanup_error_type'] = type(exc).__name__
                            raise
                finally:
                    released = lease.release()
                    shutdown.model_finished(record, lease_released=released)

        try:
            while not lease.acquire(timeout=0.2):
                if cancel.is_set() or shutdown.admission_closed:
                    raise Cancelled('Stopped while waiting for the shared model')
        except BaseException:
            shutdown.model_finished(record, lease_released=None)
            raise
        try:
            Thread(target=invoke, daemon=True).start()
        except BaseException:
            if lease.abort_start():
                shutdown.model_finished(record, lease_released=True)
            raise
        while True:
            if cancel.is_set():
                raise Cancelled('Stopped by user; the in-flight model request is being drained')
            try:
                return result.get(timeout=0.2)
            except queue.Empty:
                continue

    def summarize_conversation(request, profile, cancel):
        require_recovery_admission()
        record = shutdown.model_registered('summary', cancel)
        if memory_summarizer is not None:
            try:
                shutdown.model_started(record)
                value = memory_summarizer(request, profile, cancel)
                record['completion'] = 'trusted_function_returned'
                return value
            finally:
                shutdown.model_finished(record, lease_released=None)
        lease = _ModelSlotLease(model_slots)
        try:
            while not lease.acquire(timeout=0.2):
                if cancel.is_set() or shutdown.admission_closed:
                    raise Cancelled('Memory summarization cancelled')
        except BaseException:
            shutdown.model_finished(record, lease_released=None)
            raise
        lease.claim()
        client = None
        try:
            shutdown.model_started(record)
            if cancel.is_set():
                raise Cancelled('Memory summarization cancelled')
            client = new_model(replace(profile, max_output_tokens=min(2048, profile.max_output_tokens)))
            scope = current_context()
            client = usage_audit.client(client,uid=scope.get('uid'),rid=scope.get('rid'),category='summary',model=profile.model)
            progress = RunProgress(lambda event: None, trace_credentials(profile, {}))
            call = progress.begin_model()
            return consume_model_stream(observed_model_client(client, record), request, progress, call, cancel)
        finally:
            try:
                if client is not None:
                    try:
                        client.close()
                    except BaseException as exc:
                        record['cleanup_error_type'] = type(exc).__name__
                        raise
            finally:
                released = lease.release()
                shutdown.model_finished(record, lease_released=released)

    def release_job(record):
        if process_ownership is not None and record['kind'].removeprefix('cold_') != 'startup':
            run_evidence = recovery._load(record['rid'])
            if run_evidence.get('process_execution') or run_evidence.get('process_coverage') == 'sandbox_tools_v1':
                if run_evidence.get('phase') != 'settled':
                    recovery.committed(record)
                process_ownership.reconcile(record['uid'], record['rid'])
        job = jobs.get(record['rid'])
        if job is not None and job.get('startup') is record['startup']:
            jobs.pop(record['rid'])
        record['cleanup_done'] = True

    def recover_numeric_answer(uid, rid, note):
        from ..agent.semantic_recovery import numeric_results_from_receipts
        try:
            task = store.run(uid, rid)['query']
            receipts = [event['result'] for event in store.receipt_events(uid, rid)
                        if event.get('kind') == 'tool_result' and isinstance(event.get('result'), dict)]
            results = numeric_results_from_receipts(receipts, task)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                'Partial work recovery unavailable: run=%s error_type=%s', rid, type(exc).__name__)
            return ''
        if not results:
            return ''
        return "## 已保存的工具结果\n\n" + "\n".join("- " + item for item in results) + "\n\n" + note

    def persist_record(record):
        rid, uid = record['rid'], record['uid']
        cold = record['kind'].startswith('cold_')
        if cold:
            recovery.recheck(record)
            if (record['kind'] == 'cold_terminal'
                    and record.get('_cold_source', {}).get('phase') == 'authorized'
                    and record.get('target_status') == 'interrupted'
                    and not record['outcome'].get('answer')):
                answer = recover_numeric_answer(uid, rid, "服务中断，以上仅为中断前已经保存的工具回执。")
                if answer:
                    record['outcome'] = {**record['outcome'], 'answer': answer}
        try:
            recovery.freeze(record)
        except Exception as exc:
            # SQLite itself can still provide an atomic durable terminal.
            record['_evidence_errors'] = record.get('_evidence_errors', 0) + 1
            if record['_evidence_errors'] <= 2:
                logging.getLogger(__name__).error('Run recovery evidence pending: run=%s error_type=%s', rid, type(exc).__name__)
        kind = record['kind'].removeprefix('cold_')
        if kind == 'startup':
            if not cold and not record['startup'].is_aborted():
                raise RuntimeError('Cannot reconcile a worker-owned startup')
            status = store.fail_start(uid, rid, reason=record['reason'])
        else:
            job = jobs.get(rid)
            if (not record['execution_done'] or (job is not None and not job.get('execution_done'))
                    or (job is not None and record.get('startup') is not None and job.get('startup') is not record['startup'])):
                return False
            store.run(uid, rid)  # Recheck owner before any terminal write.
            if kind == 'input_cancel':
                status = store.cancel_input(uid, record['request_id'], _retry=True)
            else:
                payload = record['outcome']
                if record['files'] is None:
                    status = store.finish(rid, **payload)
                else:
                    try:
                        status = store.publish(uid, record['cid'], rid, record['files'],
                            base_generation=record['base_generation'], origins=record['origins'], **payload)
                    except ValueError:
                        # A deterministic publication rejection retains existing files.
                        record['outcome'] = {'status': 'failed', 'reason': 'Result files could not be published; the committed conversation files were retained.'}
                        answer = recover_numeric_answer(uid, rid, "本轮文件未能提交，以上仅为已保存的工具回执。")
                        if answer:
                            record['outcome']['answer'] = answer
                        record['target_status'] = 'failed'
                        record['files'] = None
                        record['_durable'] = False
                        with suppress(Exception):
                            recovery.freeze(record)
                        status = store.finish(rid, **record['outcome'])
        record['persistent_status'] = status
        record['persisted'] = True
        record['files'] = None  # Release result blobs after a real commit.
        try:
            recovery.committed(record)
        except Exception as exc:
            logging.getLogger(__name__).error('Committed run recovery cleanup pending: run=%s error_type=%s', rid, type(exc).__name__)
        return True

    def queue_record(record):
        if record['kind'] == 'startup':
            if not record['startup'].is_aborted():
                raise RuntimeError('Cannot queue a worker-owned startup')
        else:
            job = jobs.get(record['rid'])
            if (not record['execution_done'] or (job is not None and not job.get('execution_done'))
                    or (job is not None and record.get('startup') is not None and job.get('startup') is not record['startup'])):
                raise RuntimeError('Cannot queue terminal reconciliation for active execution')
        reconciler.add(record)

    def retry_record(record):
        if record['kind'] == 'recovery_scan':
            processes_ready = process_ownership.scan_step() if process_ownership is not None else True
            runs_ready = recovery.scan_step(queue_record)
            models_ready = shutdown.resources.scan_step()
            return processes_ready and runs_ready and models_ready
        if process_ownership is not None and record['kind'].removeprefix('cold_') != 'startup':
            run_evidence = recovery._load(record['rid'])
            if run_evidence.get('process_coverage') == 'sandbox_tools_v1':
                if not process_ownership.stop_run(record['uid'], record['rid'])['cleanup_verified']:
                    return False
            else:
                execution = process_ownership.for_run(record['uid'], record['rid'])
                if execution is not None and not process_ownership.cleanup(execution)['cleanup_verified']:
                    return False
        with guard, store.lock:
            record['attempts'] += 1
            timeout = store.db.execute('PRAGMA busy_timeout').fetchone()[0]
            store.db.execute('PRAGMA busy_timeout='+str(min(timeout, 100)))
            try:
                if not record.get('persisted') and not persist_record(record):
                    return False
                if not record.get('cleanup_done'):
                    job = jobs.get(record['rid'])
                    if record['kind'] != 'startup' and job is not None and job['thread'].is_alive():
                        return False
                    release_job(record)
                startup_failures.pop(record['rid'], None)
                terminal_failures.pop(record['rid'], None)
            finally:
                store.db.execute('PRAGMA busy_timeout='+str(timeout))

        if record.get('profile') is not None and record.get('memory_submit_pending'):
            record['memory_submit_pending'] = False
            with suppress(Exception):
                conversation_memory.submit(record['uid'], record['profile'])
        return True

    reconciler = Reconciler(retry_record)
    app.state.reconciler = reconciler
    scan_record = {'rid': '__recovery_scan__', 'uid': None, 'kind': 'recovery_scan',
                   'target_status': None, 'attempts': 0}

    def activate_recovery():
        if not recovery.activate():
            return False
        if process_ownership is not None:
            process_ownership.initialize()
        if (not recovery.scan_complete or not shutdown.resources.scan_complete
                or (process_ownership is not None and not process_ownership.snapshot()['ready'])) and '__recovery_scan__' not in reconciler.snapshot():
            reconciler.add(scan_record)
        return True

    def require_recovery_admission():
        shutdown.require_admission()
        try:
            if not activate_recovery():
                raise HTTPException(503, 'Another application view in this process owns task execution')
            if (not recovery.scan_complete or not shutdown.resources.scan_complete
                    or (process_ownership is not None and not process_ownership.snapshot()['ready'])):
                reconciler.attempt('__recovery_scan__', wait=True)
        except BrokerOwnershipError:
            raise HTTPException(503, 'Another broker owns this application state') from None
        if (not recovery.snapshot()['ready'] or not shutdown.resources.snapshot()['ready']
                or (process_ownership is not None and not process_ownership.snapshot()['ready'])):
            raise HTTPException(503, 'Task recovery is verifying previous execution resources; new execution is quarantined')


    def compensate_startup(startup, reason):
        if not startup.is_aborted():
            raise RuntimeError('Cannot compensate a worker-owned startup')
        with guard:
            record = startup_failures.setdefault(startup.rid, {
                'rid': startup.rid, 'uid': startup.uid, 'reason': reason, 'startup': startup,
                'kind': 'startup', 'target_status': 'failed', 'attempts': 0,
                'persisted': False, 'cleanup_done': False, 'files': None})
            record['attempts'] += 1
            fatal = None
            ok = True
            try:
                persist_record(record)
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    fatal = exc
                record['error_type'] = type(exc).__name__
                ok = False
            try:
                release_job(record)
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    fatal = exc
                record['error_type'] = type(exc).__name__
                ok = False
            if not ok:
                logging.getLogger(__name__).error('Task startup reconciliation pending: run=%s error_type=%s',
                    startup.rid, record.get('error_type'))
                queue_record(record)
                if fatal is not None:
                    raise fatal
                return False, None
            startup_failures.pop(startup.rid, None)
            return True, record['persistent_status']

    def reconcile_startups(uid):
        # Never wait on an in-flight callback while holding guard/Store.lock.
        for rid, item in reconciler.snapshot(uid).items():
            if not reconciler.attempt(rid, wait=True):
                code = 'startup_reconciliation_pending' if item['kind'] == 'startup' else 'task_state_reconciliation_pending'
                raise _TaskStartupError(code, rid, pending=True)

    def check_pending(uid):
        # Recheck after acquiring guard: pending may appear after HTTP preflight.
        for rid, item in reconciler.snapshot(uid).items():
            code = 'startup_reconciliation_pending' if item['kind'] == 'startup' else 'task_state_reconciliation_pending'
            raise _TaskStartupError(code, rid, pending=True)

    def cancel_input(uid, request_id):
        reconcile_startups(uid)
        with guard, store.lock:
            question = store.input_request(uid, request_id, pending=True)
            check_pending(uid)
            rid = question['origin_rid']
            record = {'rid': rid, 'uid': uid, 'kind': 'input_cancel', 'target_status': 'stopped',
                      'execution_done': True, 'cleanup_done': True, 'attempts': 1,
                      'persisted': False, 'request_id': request_id, 'files': None}
            try:
                persist_record(record)
            except Exception:
                terminal_failures[rid] = record
                queue_record(record)
                raise _TaskStartupError('task_state_reconciliation_pending', rid, pending=True)

    app.state.cancel_input = cancel_input

    def skill_receipt(fields, manual_skill):
        skill_id = fields.get('skill_id')
        if not isinstance(skill_id, str) or not skill_id:
            return None
        manual = bool(manual_skill and manual_skill['id'] == skill_id)
        if manual:
            name = manual_skill['name']
        else:
            name = fields.get('skill_name')
            if not name:
                name = (library_assets().selection(skill_id) or {}).get('name', skill_id)
        return {'kind': 'skill_loaded', 'id': skill_id, 'name': name,
                'source': 'manual' if manual else 'automatic'}

    def execute(uid, cid, rid, query, cancel, profile, startup, skill=None, mode='agent', recovery_source=None):
        if not startup.claim():
            return  # A late thread cannot execute an already compensated run.
        try:
            from .trusted_process import long_run_requested
            from ..agent.execution_contract import obligations
            from ..agent.semantic_recovery import observed_numeric_result
            run_secrets = (*secret_values, *trace_credentials(profile, {}))
            run_safe = lambda value: scrub(redact(value, run_secrets), run_secrets)
            progress = RunProgress(lambda data: store.event(rid, data), run_secrets)
            trace_path = store.root / 'traces' / (rid + '.jsonl')
            trace_path.parent.mkdir(mode=0o700, exist_ok=True)
            inner = trace_factory(trace_path) if trace_factory else configured_trace(trace_path, secrets=run_secrets)
            if hasattr(inner, 'set_model'):
                inner.set_model(profile.model, 'vllm' if profile.source == 'builtin' and profile.base_url.startswith('http://127.0.0.1:') else 'openai-compatible')
            if shutdown.admission_closed:
                raise Cancelled('Service shutdown prevented task initialization')
            recovery.authorize(uid, rid)
            shutdown.execution_authorized(rid)
        except BaseException as exc:
            if startup.fail_initialization():
                compensate_startup(startup, f'Task initialization failed ({type(exc).__name__}); execution did not begin.')
            if not isinstance(exc, Exception):
                raise
            return

        long_run = (getattr(runner, 'process_ownership', None) is not None
                    and long_run_requested(query, mode))
        confirmed = []

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
                if kind == 'tool_completed' and len(confirmed) < 3:
                    requested = obligations({'task': query}, (result['name'],))[2]
                    summary = observed_numeric_result(result, requested)
                    if summary and summary not in confirmed:
                        confirmed.append(summary)
            elif kind == 'skill_loaded':
                receipt = skill_receipt(clean, skill)
                if receipt is not None:
                    store.event(rid, run_safe(receipt))
            elif kind == 'context_compacted':
                store.event(rid, {'kind': 'context_compacted', 'before_chars': fields['before_chars'],
                                 'after_chars': fields['after_chars'], 'phase': fields['phase'],
                                 'strategies': fields['strategies']})
            elif kind == 'knowledge_requested':
                store.event(rid, {'kind': 'knowledge_start'})
            elif kind in ('knowledge_completed', 'knowledge_failed'):
                # Preserve the retrieval receipt, not a model-written bibliography.
                payload = clean.get('result', {})
                store.event(rid, {'kind': 'knowledge_sources',
                                 'status': payload.get('status'),
                                 'duration_ms': payload.get('duration_ms'),
                                 'references': payload.get('references', [])})
            elif kind in ('model_requested', 'completion_review_requested', 'completion_rejected', 'model_protocol_error', 'completion_review_protocol_error'):
                labels = {'model_requested': 'Compacting context' if fields.get('phase') == 'context_compaction' else 'Preparing answer' if fields.get('phase') == 'final_answer' else 'Model is working',
                          'completion_review_requested': 'Checking the result', 'completion_rejected': 'Correcting the result',
                          'model_protocol_error': 'Correcting a model response', 'completion_review_protocol_error': 'Retrying the completion check'}
                store.event(rid, {'kind': 'status', 'message': labels[kind], 'turn': fields.get('turn'), 'phase': fields.get('phase')})

        files, origins, base_generation = None, None, None
        successful_return = False
        runner_entered = False
        fatal_error = None
        try:
            store.event(rid, {'kind': 'status', 'message': 'Starting an isolated task environment' if isolated else 'Running in the service account environment (OS isolation disabled)'})
            if long_run:
                store.event(rid, {'kind': 'status', 'message': '长任务执行已启用'})
            query_context = conversation_memory.context(uid, cid, query, profile, recovery_source=recovery_source)
            memory = memory_service.recall(uid, cid, query, supported=bool(getattr(runner, 'memory_snapshot_enabled', False)))
            if memory['status'] != 'disabled':
                store.event(rid, {'kind': 'memory_status', 'status': memory['status'],
                                  'count': len(memory['records']), 'project_id': memory.get('project_id')})
            base_generation = store.conversation(uid, cid)['generation']
            runner_entered = True
            result = runner.run(rid, query_context, store.files(uid, cid, base_generation), cancel,
                                lambda request, event: model_call(request, event, profile, progress, uid=uid, rid=rid), on_trace,
                                diagnostics=store.root / 'traces' / (rid + '.stderr.log'),
                                **({'skill_id': skill['id']} if skill else {}),
                                **({'read_only': True} if mode == 'ask' else {}),
                                settings={**profile.runtime_settings(), 'max_model_turns': None,
                                          **({'memory_enabled': True} if memory['records'] else {})},
                                **({'long_run': True} if long_run else {}),
                                **({'memory_records': memory['records']} if memory['records'] else {}),
                                **({'input_origins': store.file_origins(uid, cid, base_generation)}
                                   if getattr(runner, 'provenance_enabled', False) else {}),
                                **({'context_scope': {'owner_id': uid, 'conversation_id': cid}}
                                   if getattr(runner, 'context_archive_enabled', False) else {}),
                                **({'process_scope': {'uid': uid, 'cid': cid}}
                                   if process_ownership is not None else {}))
            if mode == 'agent':
                files, origins = dict(result['files']), result.get('file_origins')
            outcome = {'status': result['status'], 'answer': run_safe(result['answer']),
                       'reason': run_safe(result.get('reason', '')), 'turns': result.get('turns', 0)}
            successful_return = True
        except Cancelled as exc:
            outcome = {'status': 'stopped', 'reason': run_safe(str(exc))}
        except Exception as exc:
            outcome = {'status': 'failed', 'reason': run_safe(f'{type(exc).__name__}: {exc}')}
            if confirmed:
                outcome['answer'] = run_safe("## 中断前已取得的工具结果\n\n" +
                    "\n".join("- " + item for item in confirmed) +
                    "\n\n任务在后续步骤中断，以上为已收到的工具回执。")

        except BaseException as exc:
            fatal_error = exc
            outcome = {'status': 'failed', 'reason': 'Execution ended with '+type(exc).__name__}

        # Diagnostics must not prevent recording the actual execution outcome.
        for operation in [lambda: progress.switch('publishing') if successful_return and not cancel.is_set() else None, progress.close, lambda: inner.emit('team_cancelled' if outcome['status'] == 'stopped' else 'team_failed',
                error=outcome.get('reason', '')) if not successful_return else None]:
            try:
                operation()
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    fatal_error = exc
                logging.getLogger(__name__).warning('Task diagnostic failed: run=%s error_type=%s', rid, type(exc).__name__)
        if process_ownership is not None and not runner_entered:
            # Context/recall/file initialization failed before Runner could create
            # any execution. Persist that non-execution fact; never replay work.
            try:
                execution = process_ownership.prepare(uid, cid, rid,
                    local_scope_certified=runner.process_scope_certified)
                process_ownership.cleanup(execution)
            except Exception as exc:
                logging.getLogger(__name__).error('Managed non-start evidence pending: run=%s error_type=%s', rid, type(exc).__name__)
        with guard:
            if successful_return and cancel.is_set():
                outcome = {'status': 'stopped', 'reason': 'Stopped before file commit; the previous files are unchanged'}
                files, origins = None, None
            job = jobs.get(rid)
            if job is not None and job.get('startup') is startup:
                job['execution_done'] = True
            record = {'rid': rid, 'uid': uid, 'cid': cid, 'startup': startup,
                      'kind': 'terminal', 'target_status': outcome['status'], 'execution_done': True,
                      'outcome': outcome, 'files': files, 'origins': origins,
                      'base_generation': base_generation, 'profile': profile, 'memory_submit_pending': False, 'attempts': 1,
                      'persisted': False, 'cleanup_done': False}
            terminal_failures[rid] = record
            try:
                persist_record(record)
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    fatal_error = exc
                record['error_type'] = type(exc).__name__
                logging.getLogger(__name__).error('Task terminal reconciliation pending: run=%s error_type=%s', rid, type(exc).__name__)
                queue_record(record)
        try:
            if record['persisted']:
                with suppress(Exception):
                    conversation_memory.submit(uid, profile)
            else:
                record['memory_submit_pending'] = True
        finally:
            with guard:
                try:
                    release_job(record)
                except Exception as exc:
                    record['error_type'] = type(exc).__name__
                    queue_record(record)
                if record['persisted'] and record['cleanup_done']:
                    terminal_failures.pop(rid, None)
        if fatal_error is not None:
            raise fatal_error

    def launch(uid, cid, query, profile, *, expected_input=None, skill_id=None, mode='agent', plan=None,
               source_run_id=None, recovery_action=None):
        store.conversation(uid, cid)
        if not isinstance(query, str) or not query.strip() or len(query) > 20000:
            raise HTTPException(400, 'Provide a task of 1 to 20,000 characters')
        if mode not in ('ask', 'agent'):
            raise HTTPException(400, 'Choose Ask or Agent mode')
        plan = _confirmed_research_plan(plan)
        if mode == 'ask' and (skill_id is not None or plan is not None):
            raise HTTPException(400, 'Switch to Agent mode to use a skill or confirmed plan')
        if expected_input is not None and plan is not None:
            raise HTTPException(400, 'A confirmed plan applies only to a new task')
        if (source_run_id is None) != (recovery_action is None):
            raise HTTPException(400, 'Provide both source run and recovery action')
        recovery_run = recovery_source = None
        if source_run_id is not None:
            if expected_input is not None or mode != 'agent':
                raise HTTPException(400, 'Terminal recovery requires a new Agent task')
            recovery_run = _terminal_recovery_source(uid, cid, source_run_id, recovery_action)
            recovery_source = _terminal_recovery_context(uid, recovery_run)
        require_recovery_admission()
        if expected_input is None:
            reconcile_startups(uid)
        with guard:
            shutdown.require_admission()
            if (not recovery.snapshot()['ready'] or not shutdown.resources.snapshot()['ready']
                    or (process_ownership is not None and not process_ownership.snapshot()['ready'])):
                raise HTTPException(503, 'Task recovery is quarantining unresolved execution')
            check_pending(uid)
            active_job = next((job for job in jobs.values() if job['uid'] == uid), None)
            if active_job is not None:
                raise HTTPException(409, 'You already have an active task; wait for it to finish',
                                    headers={'X-Active-Conversation': active_job['cid']})
            if len(jobs) >= capacity['max_active_runs']:
                raise HTTPException(409, f"All {capacity['max_active_runs']} execution slots are busy; try again when a task finishes")
            # A human-input reply resumes an existing graph, not a fresh task.
            with store.lock:
                pending = store.db.execute("SELECT origin_rid,payload FROM input_requests WHERE cid=? AND state='pending'", (cid,)).fetchone()
                if pending:
                    if mode == 'ask':
                        raise HTTPException(409, 'Reply to the pending task before switching modes')
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
            skill = None
            if skill_id is not None:
                if pending:
                    raise HTTPException(409, 'Reply to the pending request before selecting another skill')
                if not isinstance(skill_id, str) or len(skill_id) > 128:
                    raise HTTPException(400, 'Invalid skill selection')
                skill = library_assets().selection(skill_id)
                if skill is None:
                    raise HTTPException(400, 'The selected skill is unavailable')
            # Allocate the ID before persistence so a committed begin followed by
            # a return-boundary exception can still be reconciled unambiguously.
            startup = _TaskStartup(uid, uuid.uuid4().hex)
            rid = startup.rid
            try:
                recovery.prepare(uid, cid, rid)
                store.begin(uid, cid, query.strip(), expected_input=expected_input, _rid=rid)
                if recovery_run is not None:
                    store.event(rid, {'kind': 'recovery_source', 'run_id': recovery_run['id'],
                                      'action': recovery_action})
                if plan is not None:
                    store.event(rid, {'kind': 'plan_confirmed', 'plan': plan})
                store.event(rid, {'kind': 'model_config', 'profile': profile.run_snapshot(), 'context_budget': profile.context_budget()})
                store.event(rid, {'kind':'run_mode', 'mode':mode})
                if skill:
                    store.event(rid, {'kind': 'skill_selected', 'skill': skill})
                execution_query = query.strip()
                if plan is not None:
                    execution_query += '\n\n用户已确认的研究计划与验收标准：\n' + json.dumps(plan, ensure_ascii=False)
                conversation_memory.capture(uid, cid, rid)
                cancel = Event()
                thread = Thread(target=execute, args=(uid, cid, rid, execution_query, cancel, profile, startup,
                                                       skill, mode, recovery_source), daemon=True)
                jobs[rid] = {'uid': uid, 'cid': cid, 'cancel': cancel, 'thread': thread, 'startup': startup}
                shutdown.track_worker(rid, uid, cancel, thread, startup)
                try:
                    thread.start()
                finally:
                    shutdown.handoff_finished(rid)
            except BaseException as exc:
                if startup.abort_start():
                    ok, status = compensate_startup(startup,
                        f'Task startup failed ({type(exc).__name__}); execution did not begin.')
                    if not isinstance(exc, Exception):
                        raise
                    if not ok:
                        raise _TaskStartupError('startup_reconciliation_pending', rid, pending=True) from exc
                    if status is None:
                        if isinstance(exc, ValueError):
                            raise HTTPException(409, str(exc)) from exc
                        raise  # No durable reservation; retain the original error contract.
                    raise _TaskStartupError('task_startup_failed', rid, pending=False) from exc
                # start() can raise after a real worker has claimed ownership.
                # The worker (including its initialization failure path) owns cleanup.
                if not isinstance(exc, Exception):
                    raise
                raise _TaskStartupError('task_start_outcome_unknown', rid) from exc
        return {'id': rid}

    @app.post('/api/conversations/{cid}/runs')
    async def start(cid: str, request: Request):
        # Authentication and durable admission use synchronous SQLite/filesystem
        # operations. Keep them off the ASGI loop; launch's existing guard still
        # owns reservation, capacity checks, and startup compensation atomically.
        user = await run_in_threadpool(auth, request, mutate=True)
        data = await body(request)
        profile = await run_in_threadpool(model_settings.get, request.cookies.get(COOKIE, ''))
        return await run_in_threadpool(launch, user['id'], cid, data.get('query', ''), profile,
                                       skill_id=data.get('skill_id'), mode=data.get('mode', 'agent'),
                                       plan=data.get('plan'), source_run_id=data.get('source_run_id'),
                                       recovery_action=data.get('recovery_action'))

    def pending_input(uid, request_id, cid, rid):
        if not all(isinstance(value, str) and value for value in (request_id, cid, rid)):
            raise HTTPException(400, 'Provide the conversation, run, and question identifiers')
        try:
            value = store.input_request(uid, request_id, cid=cid, rid=rid, pending=True)
            check_pending(uid)
            return value
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
        reconcile_startups(uid)
        with guard, store.lock:
            pending_input(uid, request_id, data['cid'], data['rid'])
            return launch(uid, data['cid'], data['text'], profile,
                          expected_input=(request_id, data['rid']))

    @app.post('/api/hitl/requests/{request_id}/upload')
    async def upload_for_input(request_id: str, request: Request, cid: str, rid: str, name: str):
        uid = auth(request, mutate=True)['id']
        # Authenticate ownership before consuming a potentially large file.
        reconcile_startups(uid)
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
                       "scope": "uploaded by the authenticated caller; not independently verified"}}, action='upload')
        return {'ok': True, 'name': name, 'generation': generation}

    @app.get('/api/runs/{rid}')
    def run(rid: str, request: Request):
        uid = auth(request)['id']
        try:
            value = store.run(uid, rid)
        except sqlite3.Error:
            raise HTTPException(503, 'Task state is temporarily unavailable; retry shortly')
        recovered = recovery.for_run(uid, rid)
        if recovered is not None:
            value['recovery'] = recovered
        pending = reconciler.snapshot(uid, rid).get(rid)
        if pending is not None:
            value['persistence'] = {key: pending[key] for key in ['kind', 'target_status', 'retry_count', 'attempts', 'persisted']}
            value['persistence']['state'] = 'pending'
        return archival_run_view(uid, value)

    @app.post('/api/runs/{rid}/recovery')
    async def prepare_terminal_recovery(rid: str, request: Request):
        uid = auth(request, mutate=True)['id']
        data = await body(request)
        if set(data) != {'action'}:
            raise HTTPException(400, 'Expected one terminal recovery action')
        try:
            run = store.run(uid, rid)
        except KeyError as exc:
            raise HTTPException(404, 'Run not found') from exc
        run = _terminal_recovery_source(uid, run['cid'], rid, data['action'])
        return {
            'action': data['action'],
            'query': _terminal_recovery_prompt(run, data['action']),
            'mode': 'agent',
            'conversation_id': run['cid'],
            'source_run_id': rid,
            'execution': 'new_run',
            'message': '已准备续写草稿。确认研究计划并发送后，将在同一对话新建运行；原运行和成果版本保留。',
        }

    @app.post('/api/runs/{rid}/stop')
    def stop(rid: str, request: Request, tool_invocation_id: str | None = None):
        uid = auth(request, mutate=True)['id']
        if tool_invocation_id is not None:
            store.run(uid, rid)  # Original authorization precedes any resource lookup/signal.
            if not isinstance(runner, SandboxRunner) or process_ownership is None:
                raise HTTPException(400, 'This run has no managed ToolCall stop capability')
            try:
                process_ownership.tool_execution(uid, rid, tool_invocation_id)
            except Exception:
                raise HTTPException(404, 'ToolCall not found')
            receipt = runner.stop(rid, tool_invocation_id)
            return {'ok': True, 'tool_invocation_id': tool_invocation_id,
                    'cleanup_verified': receipt['cleanup_verified']}
        with guard, store.lock:
            state = store.run(uid, rid)
            job = jobs.get(rid)
            if (job is not None and not job.get('execution_done') and not job['cancel'].is_set()
                    and state['status'] in ('running', 'stopping')):
                job['cancel'].set()
                store.event(rid, {'kind': 'status', 'message': 'Stopping the task; keeping the last committed files'})
        if process_ownership is not None:
            # Ownership/auth checks above precede any physical operation; no
            # global lock is held during bounded process cleanup.
            process_ownership.stop_run(uid, rid)
            if '__recovery_scan__' not in reconciler.snapshot():
                reconciler.add(scan_record)
        return {'ok': True}

    @app.get('/api/runs/{rid}/history')
    def run_history(rid: str, request: Request, after: int = 0, through: int | None = None, limit: int = 60):
        uid = auth(request)['id']
        page = store.history(uid, rid, after=after, through=through, limit=limit)
        if after == 0:
            run = store.run(uid, rid)
            activity = run['activity']
            if 'loaded_skills' not in activity and activity.get('mode') != 'ask':
                # Older runs wrote skill activations only to their private trace.
                receipts = {}
                trace_path = store.root / 'traces' / (rid + '.jsonl')
                try:
                    with trace_path.open(encoding='utf-8', errors='replace') as stream:
                        for line in stream:
                            if '"skill_loaded"' not in line:
                                continue
                            try:
                                event = json.loads(line)
                            except ValueError:
                                continue
                            if isinstance(event, dict) and event.get('event') == 'skill_loaded':
                                receipt = skill_receipt(event, activity.get('skill'))
                                if receipt is not None:
                                    receipts[receipt['id']] = receipt
                except FileNotFoundError:
                    pass
                page['loaded_skills'] = list(receipts.values())
        return page

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
        # Public presentation settings only; never keys, provider data or OTPs.
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

    @app.get('/assets/{name}')
    def asset(name: str):
        if name not in ('password-auth.js', 'admin-usage.js', 'admin-usage.css', 'shared-knowledge.js', 'shared-knowledge.css', 'admin-users.js', 'admin-users.css', 'email-auth.js', 'profile.js', 'profile.css', 'registration.js', 'registration.css', 'app.js', 'drafts.js', 'research-plan.js', 'recovery.js', 'versions.js', 'versions.css', 'style.css', 'defaults.js', 'defaults.css', 'memorax.js', 'memorax.css', 'hitl.js', 'library.js', 'library.css', 'model-profiles.css', 'knowledge.js', 'knowledge.css', 'images.js', 'images.css', 'presentation.js', 'presentation.css', 'presentation-state.js', 'timeline.js', 'timeline.css', 'citations.js', 'citations.css', 'bogao-wordmark.svg', 'bogao-symbol.svg'):
            raise HTTPException(404)
        return FileResponse(assets / name)

    @app.get('/vendor/katex.min.js')
    def math_renderer():
        return FileResponse(Path(__file__).parent.parent / 'web/vendor/katex.min.js')

    app.state.usage_audit = usage_audit
    from .admin_usage import install_usage_routes
    install_usage_routes(app, auth, store, usage_audit)
    from .shared_knowledge import install_shared_routes
    install_shared_routes(app, auth, body, usage_audit)
    from .admin_users import install_admin_user_routes
    install_admin_user_routes(app, auth, store)
    from .case_experience import install_case_routes
    install_case_routes(app, auth, body, store, guard, jobs)
    from .hitl import install_input_routes
    install_input_routes(app)
    from .library import install_library_routes
    library_assets = install_library_routes(app, auth, human_input=bool(getattr(runner, 'hitl_enabled', False)))
    from .knowledge import install_knowledge_routes
    install_knowledge_routes(app, auth, body)
    from .data_inventory import install_data_inventory_routes
    install_data_inventory_routes(app, auth, store.root)
    from .knowledge_corpus import install_corpus_routes
    install_corpus_routes(app, auth)
    from .knowledge_graph import install_graph_routes
    install_graph_routes(app, auth)
    from .images import install_image_routes
    install_image_routes(app, auth, store)
    from .presentation import install_presentation_routes
    install_presentation_routes(app, auth, store)
    from .versions import install_generation_routes
    install_generation_routes(app, auth, store, guard, jobs)
    from .memorax import install_memory_routes
    memory_service = install_memory_routes(app, auth, body, store, client_factory=memory_client_factory)
    from .conversation_memory import ConversationMemory
    conversation_memory = ConversationMemory(store, memory_service, summarize_conversation)
    app.state.conversation_memory = conversation_memory

    def cleanup_shutdown_worker(row):
        if process_ownership is not None:
            run_data = recovery._load(row['id'])
            if run_data.get('process_coverage') == 'sandbox_tools_v1':
                return runner.stop(row['id'])
            execution = process_ownership.for_run(row['uid'], row['id'])
            if execution is not None:
                return process_ownership.cleanup(execution)
        if shutdown._worker_ended(row):
            return True
        startup = row['startup']
        if startup.uid != row['uid'] or startup.rid != row['id']:
            raise RuntimeError('Worker cleanup ownership mismatch')
        data = recovery.current.get(row['id']) or recovery._load(row['id'])
        if data['uid'] != row['uid'] or data['owner'] != recovery.owner:
            raise RuntimeError('Worker cleanup evidence mismatch')
        runner.stop(row['id'])
        return True

    def coordinate_shutdown():
        deadline = min(shutdown.deadline, time.monotonic() + shutdown.limits['final'])
        while time.monotonic() < deadline:
            pending = [rid for rid in reconciler.snapshot() if rid != '__recovery_scan__']
            if not pending:
                return True
            for rid in pending[:4]:
                reconciler.attempt(rid, wait=False)
            with reconciler.condition:
                reconciler.condition.wait(min(0.05, max(0, deadline - time.monotonic())))
        return not any(rid != '__recovery_scan__' for rid in reconciler.snapshot())

    def preserve_shutdown_pending():
        with guard:
            with reconciler.condition:
                pending = list(reconciler.pending.values())
            for record in pending:
                if record['kind'] != 'recovery_scan' and not record.get('persisted'):
                    recovery.freeze(record)
            return all(record['kind'] == 'recovery_scan' or record.get('persisted') or record.get('_durable') for record in pending)

    shutdown.configure(reconciler=reconciler, memory_close=lambda: conversation_memory.close(),
        memory_thread=lambda: getattr(conversation_memory, 'thread', None),
        clear_settings=lambda: model_settings.clear(), cleanup_worker=cleanup_shutdown_worker,
        coordinate=coordinate_shutdown, preserve_pending=preserve_shutdown_pending,
        sqlite_close=lambda: store.db.close())


    @app.get('/api/settings/memory/status')
    def automatic_memory_status(request: Request):
        return conversation_memory.status(auth(request)['id'])

    @app.get('/api/conversations/{cid}/memory/summary')
    def conversation_summary(cid: str, request: Request):
        return conversation_memory.snapshot(auth(request)['id'], cid)
    from .verification_api import install_verification_routes
    verification = verification_factory(store) if verification_factory else None
    install_verification_routes(app, verification)
    app.state.verification_service = verification
    from .registration_service import RegistrationService
    registration = RegistrationService(store, verification, policy=registration_policy)
    app.state.registration_service = registration
    from .profile_service import ProfileService
    from .profile_api import install_profile_routes
    profile_service = ProfileService(store, verification, policy=profile_policy)
    install_profile_routes(app, profile_service, auth, body, expensive_auth, rate_limit, cookie_name=COOKIE)
    app.state.profile_service = profile_service
    email_service = email_factory(store) if email_factory is not None else None
    app.state.email_service = email_service
    if email_service is not None:
        from .email_api import install_email_routes
        install_email_routes(app, email_service, body, expensive_auth, rate_limit, cookie_name=COOKIE, secure_cookie=secure_cookie, auth=auth)
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
        app = create_app(args.state)
        owned_server = lifecycle_server(uvicorn.Config(app, host='127.0.0.1', port=args.port, proxy_headers=False), app)
        try:
            owned_server.run()
        finally:
            app.state.shutdown.close_store()


if __name__ == '__main__':
    main()

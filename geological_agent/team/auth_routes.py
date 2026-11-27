"""Authentication, session, invitation, and model-settings HTTP routes for team server."""
import asyncio
from contextvars import copy_context
import os
from threading import Event

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
import httpx

from .isolation import Cancelled
from .model_settings import probe_model, provider_error_details, trace_credentials
from .model_vault import ModelVaultError
from .server_helpers import _ModelSlotLease
from .shutdown import observed_model_client
from .store import SESSION_SECONDS


def install_auth_and_model_routes(
    app,
    *,
    store,
    auth,
    body,
    rate_limit,
    expensive_auth,
    model_settings,
    builtin,
    cookie_name,
    secure_cookie,
    isolated,
    runner,
    require_recovery_admission,
    guard,
    shutdown,
    model_slots,
    probing,
    capacity,
    new_model,
    usage_audit,
):
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
        username = username.strip()
        rate_limit(request, username)
        token, csrf = await expensive_auth(store.login, username, password)
        response = JSONResponse({'ok': True, 'csrf': csrf})
        response.set_cookie(cookie_name, token, httponly=True, samesite='strict', secure=secure_cookie, max_age=SESSION_SECONDS, path='/')
        return response

    @app.post('/api/register')
    async def register(request: Request):
        from .registration_service import RegistrationError
        from .verification_service import ServiceError
        from .registration_api import registration_response, registration_error
        from .verification_policy import client_ip
        registration = app.state.registration_service
        verification = app.state.verification_service
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
        token = csrf = None
        try:
            token, csrf = await expensive_auth(store.login, result.username, data['password'])
        except Exception:
            pass
        try:
            return registration_response(result, cookie_name=cookie_name, secure_cookie=secure_cookie, token=token, csrf=csrf)
        except Exception:
            return registration_error('registration_unavailable', 503)

    @app.post('/api/logout')
    def logout(request: Request):
        auth(request, mutate=True)
        model_settings.forget(request.cookies.get(cookie_name, ''))
        store.logout(request.cookies.get(cookie_name, ''))
        response = JSONResponse({'ok': True})
        response.delete_cookie(cookie_name, path='/')
        return response

    @app.post('/api/password')
    async def password(request: Request):
        user = auth(request, mutate=True)
        data = await body(request)
        rate_limit(request, user['username'])
        await expensive_auth(store.change_password, user['id'], data.get('old', ''), data.get('new', ''))
        model_settings.prune()
        response = JSONResponse({'ok': True})
        response.delete_cookie(cookie_name, path='/')
        return response

    @app.get('/api/settings/model-defaults')
    def get_model_defaults(request: Request):
        auth(request)
        return model_settings.get_defaults(request.cookies.get(cookie_name, ''))

    @app.put('/api/settings/model-defaults')
    async def save_model_defaults(request: Request):
        auth(request, mutate=True)
        return model_settings.save_defaults(request.cookies.get(cookie_name, ''), await body(request))

    @app.get('/api/model-settings')
    def get_model_settings(request: Request):
        auth(request)
        try:
            public = model_settings.public(request.cookies.get(cookie_name, ''))
        except ModelVaultError as exc:
            return {**builtin.public(), 'storage': 'account_unavailable',
                    'storage_error': str(exc), 'saved_profiles': [],
                    'builtin': builtin.public()}
        return {**public, 'builtin': builtin.public()}

    @app.delete('/api/model-settings')
    def delete_model_settings(request: Request):
        auth(request, mutate=True)
        profile = model_settings.delete(request.cookies.get(cookie_name, ''))
        return {**profile.public(), 'builtin': builtin.public()}

    @app.put('/api/model-settings')
    async def save_model_settings(request: Request):
        auth(request, mutate=True)
        profile = model_settings.save(request.cookies.get(cookie_name, ''), await body(request))
        return {**profile.public(), 'builtin': builtin.public()}

    @app.post('/api/model-settings/activate')
    async def activate_model_settings(request: Request):
        auth(request, mutate=True)
        data = await body(request)
        if set(data) != {'profile_id'}:
            raise ValueError('Choose one saved connection')
        profile = model_settings.activate(request.cookies.get(cookie_name, ''), data['profile_id'])
        return {**profile.public(), 'builtin': builtin.public()}

    @app.delete('/api/model-settings/profiles/{profile_id}')
    async def delete_model_profile(profile_id: str, request: Request):
        auth(request, mutate=True)
        data = await body(request)
        if set(data) != {'revision'}:
            raise ValueError('Connection revision is required')
        profile = model_settings.remove(request.cookies.get(cookie_name, ''), profile_id, data['revision'])
        return {**profile.public(), 'builtin': builtin.public()}

    @app.post('/api/model-settings/test')
    async def test_model_settings(request: Request):
        user = auth(request, mutate=True)
        require_recovery_admission()
        profile = model_settings.parse(request.cookies.get(cookie_name, ''), await body(request))
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
                client = usage_audit.client(client, uid=user['id'], category='connection_test', model=profile.model)
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

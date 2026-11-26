"""Opt-in advisory APIs. Existing register/login routes are untouched."""
import asyncio
import json
from fastapi import Request
from fastapi.responses import JSONResponse

from .verification_service import ServiceError, InvitationState
from .verification_policy import client_ip


def install_verification_routes(app,service):
    async def invoke(request,operation):
        try:
            if service is None:raise ServiceError('sms_unavailable',503)
            ip=client_ip(request.client.host if request.client else None,request.headers.get('x-forwarded-for'),service.settings)
            service.edge_check(ip)
            if request.headers.get('content-type','').split(';')[0]!='application/json':
                raise ServiceError('invalid_request',415)
            raw=bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw)>service.settings.body_limit:raise ServiceError('request_too_large',413)
            try:data=json.loads(raw)
            except (ValueError,UnicodeError):raise ServiceError('invalid_request',400) from None
            keys={'invitation':{'invite'},'send':{'invite','phone','request_id'},'verify':{'invite','phone','verification_id','code','purpose'}}[operation]
            required=keys-({'purpose'} if operation=='verify' else set())
            if not isinstance(data,dict) or set(data)-keys or not required.issubset(data) or any(not isinstance(v,str) for v in data.values()):
                raise ServiceError('invalid_request',400)
            if len(data['invite'])>64:raise ServiceError('invalid_request',400)
            if operation=='invitation':
                valid=await asyncio.to_thread(service.invitation_state,data['invite'])
                result={'valid':valid==InvitationState.VALID,'advisory':True}
            elif operation=='send':
                result=await asyncio.to_thread(service.send,data['invite'],data['phone'],data['request_id'],ip)
            else:
                result=await asyncio.to_thread(service.verify,data['invite'],data['phone'],data['verification_id'],data['code'],purpose=data.get('purpose','register'))
            return JSONResponse(result,status_code=202 if operation=='send' else 200,headers={'Cache-Control':'no-store'})
        except ServiceError as exc:
            headers={'Cache-Control':'no-store'}
            if exc.retry_after is not None:headers['Retry-After']=str(exc.retry_after)
            return JSONResponse({'detail':'Verification request could not be completed','code':exc.code},status_code=exc.http_status,headers=headers)
        except Exception:
            # No exception text, request body, OTP, keys, provider details or traceback.
            return JSONResponse({'detail':'Verification request could not be completed','code':'verification_unavailable'},status_code=503,headers={'Cache-Control':'no-store'})

    @app.post('/api/auth/invitations/validate')
    async def validate(request:Request):return await invoke(request,'invitation')

    @app.post('/api/auth/sms/send')
    async def send(request:Request):return await invoke(request,'send')

    @app.post('/api/auth/sms/verify')
    async def verify(request:Request):return await invoke(request,'verify')

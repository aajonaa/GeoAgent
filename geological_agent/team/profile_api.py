"""Authenticated own-profile routes; existing Cookie/CSRF and auth CPU limits."""
import asyncio
from fastapi import Request,HTTPException
from fastapi.responses import JSONResponse
from .profile_service import ProfileError
from .verification_service import ServiceError
from .verification_policy import client_ip


def install_profile_routes(app,service,auth,body,expensive_auth,rate_limit,*,cookie_name):
    async def invoke(request,operation):
        user=auth(request,mutate=operation!='read')
        session=request.cookies.get(cookie_name,'')
        try:
            if request.query_params:raise ProfileError('invalid_request',400)
            if operation=='read':
                async for chunk in request.stream():
                    if chunk:raise ProfileError('invalid_request',400)
                result=await asyncio.to_thread(service.read,session)
            else:
                data=await body(request,limit=service.policy.body_limit)
                required={'update':{'organization'},'reauthenticate':{'phone','password'},'send':{'phone','authorization','request_id'},'confirm':{'phone','authorization','verification_id','code'}}[operation]
                if set(data)!=required or any(not isinstance(v,str) for k,v in data.items() if not (operation=='update' and k=='organization' and v is None)):
                    raise ProfileError('invalid_request',400)
                if operation=='update':result=await asyncio.to_thread(service.update_organization,session,**data)
                else:
                    v=service.verification
                    if v is not None:
                        ip=client_ip(request.client.host if request.client else None,request.headers.get('x-forwarded-for'),v.settings)
                        v.edge_check(ip)
                    else:ip='unknown'
                    if operation=='reauthenticate':
                        rate_limit(request,user['username'])
                        result=await expensive_auth(service.reauthenticate,session,**data)
                    elif operation=='send':result=await asyncio.to_thread(service.send_phone,session,ip=ip,**data)
                    else:result=await asyncio.to_thread(service.confirm_phone,session,**data)
            return JSONResponse(result,status_code=202 if operation=='send' else 200,headers={'Cache-Control':'no-store'})
        except (ProfileError,ServiceError) as exc:
            headers={'Cache-Control':'no-store'}
            if getattr(exc,'retry_after',None) is not None:headers['Retry-After']=str(exc.retry_after)
            return JSONResponse({'detail':'Profile request could not be completed','code':exc.code},status_code=exc.http_status,headers=headers)
        except (HTTPException,PermissionError):raise
        except Exception:
            # Authentication material, phone/code/proof and SQL exceptions never logged/reflected.
            return JSONResponse({'detail':'Profile request could not be completed','code':'profile_unavailable'},status_code=503,headers={'Cache-Control':'no-store'})

    @app.get('/api/profile')
    async def profile(request:Request):return await invoke(request,'read')

    @app.patch('/api/profile')
    async def update_profile(request:Request):return await invoke(request,'update')

    @app.post('/api/profile/phone/reauthenticate')
    async def reauthenticate(request:Request):return await invoke(request,'reauthenticate')

    @app.post('/api/profile/phone/send')
    async def send_phone(request:Request):return await invoke(request,'send')

    @app.post('/api/profile/phone/confirm')
    async def confirm_phone(request:Request):return await invoke(request,'confirm')

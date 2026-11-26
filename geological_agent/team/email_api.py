"""Same-origin email endpoints using the application's existing Cookie/CSRF model."""
import asyncio
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from .email_service import EmailError
from .registration_api import registration_response
from .store import SESSION_SECONDS, digest


def install_email_routes(app, service, body, expensive_auth, rate_limit, *, cookie_name, secure_cookie, auth):
    slots = asyncio.Semaphore(4)

    async def invoke(request, operation):
        try:
            if request.query_params:
                raise EmailError('invalid_request')
            data = await body(request, limit=8192)
            shapes = {'invite':{'invite'}, 'send':{'email','purpose','request_id'},
                      'register':{'email','username','organization','research_area','gender','age','invite','verification_id','code','request_id','password','confirm_password'},
                      'login':{'email','verification_id','code'},
                      'password':{'email','verification_id','code','password','confirm_password'}}
            expected=shapes[operation]
            if operation=='send' and data.get('purpose')=='register':
                expected=expected|{'invite'}
            if set(data)!=expected or any((type(v) is not int if operation=='register' and k=='age' else not isinstance(v,str)) for k,v in data.items()):
                raise EmailError('invalid_request')
            rate_limit(request,'email:'+digest(data.get('email','invitation')))
            if operation=='invite':
                result=await asyncio.to_thread(service.invitation,data['invite'])
                return JSONResponse(result,headers={'Cache-Control':'no-store'})
            if operation=='send':
                async with slots:
                    result=await asyncio.to_thread(service.send,**data,ip=request.client.host if request.client else 'unknown')
                return JSONResponse(result,status_code=202,headers={'Cache-Control':'no-store'})
            if operation=='register':
                outcome=await expensive_auth(service.register,data)
                token,csrf=outcome['session'] or (None,None)
                return registration_response(outcome['result'],cookie_name=cookie_name,secure_cookie=secure_cookie,token=token,csrf=csrf)
            if operation=='password':
                current=None
                if request.cookies.get(cookie_name):
                    try:current=auth(request,mutate=True)
                    except PermissionError:pass
                uid=await expensive_auth(service.reset_password,**data,expected_uid=current['id'] if current else None)
                audit=getattr(app.state,'usage_audit',None)
                if audit:audit.record(uid,'password_changed',method='email_otp')
                response=JSONResponse({'ok':True},headers={'Cache-Control':'no-store'})
                if request.cookies.get(cookie_name):response.delete_cookie(cookie_name,path='/')
                return response
            token,csrf=await expensive_auth(service.login,**data)
            response=JSONResponse({'ok':True,'csrf':csrf},headers={'Cache-Control':'no-store'})
            response.set_cookie(cookie_name,token,httponly=True,samesite='strict',secure=secure_cookie,max_age=SESSION_SECONDS,path='/')
            return response
        except EmailError as exc:
            headers={'Cache-Control':'no-store'}
            if exc.retry_after is not None:
                headers['Retry-After']=str(exc.retry_after)
            return JSONResponse({'detail':'Email verification could not be completed','code':exc.code},status_code=exc.status,headers=headers)
        except HTTPException:
            raise
        except Exception:
            return JSONResponse({'detail':'Email verification is temporarily unavailable','code':'email_unavailable'},status_code=503,headers={'Cache-Control':'no-store'})

    @app.post('/api/auth/email/invitation')
    async def invitation(request:Request):return await invoke(request,'invite')

    @app.post('/api/auth/email/send')
    async def send(request:Request):return await invoke(request,'send')

    @app.post('/api/auth/email/register')
    async def register(request:Request):return await invoke(request,'register')

    @app.post('/api/auth/email/login')
    async def login(request:Request):return await invoke(request,'login')

    @app.get('/api/auth/email/account')
    def password_account(request:Request):
        user=auth(request)
        if request.query_params:raise HTTPException(400,'This endpoint only returns the current account')
        with service.lock:
            row=service.db.execute('SELECT email FROM email_identities WHERE user_id=?',(user['id'],)).fetchone()
        return JSONResponse({'user_id':user['id'],'username':user['username'],'email':row['email'] if row else None,
                             'email_verified':bool(row)},headers={'Cache-Control':'no-store'})

    @app.post('/api/auth/email/password')
    async def password(request:Request):return await invoke(request,'password')

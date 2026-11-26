"""Only response formatting; the existing Store.login creates all Sessions."""
from fastapi.responses import JSONResponse
from .store import SESSION_SECONDS


def registration_response(result,*,cookie_name,secure_cookie,token=None,csrf=None):
    content={'ok':True,'registered':True,'authenticated':token is not None}
    if token is not None:
        content.update({'user':{'id':result.user_id,'username':result.username,'role':'member'},'csrf':csrf})
    else:
        content['next']='login'
    response=JSONResponse(content,status_code=201 if result.created else 200,headers={'Cache-Control':'no-store'})
    if token is not None:
        response.set_cookie(cookie_name,token,httponly=True,samesite='strict',secure=secure_cookie,max_age=SESSION_SECONDS,path='/')
    return response


def registration_error(code,status_code):
    return JSONResponse({'detail':'Registration request could not be completed','code':code},status_code=status_code,headers={'Cache-Control':'no-store'})

"""Administrative HTTP boundary; browser auth and legacy scripts are separated."""
from pathlib import Path
from typing import Literal
from datetime import date, datetime, timezone, timedelta
from domain.revision import revision
from fastapi import APIRouter,Depends,Request,Query,Response
from fastapi.responses import FileResponse
from security.auth import admin_service,check_origin,require_browser,permission
from security.logging import request_id,safe_event
from security.frontend import FRONTEND_CSP
from domain.admin import Login,CreateUser,UpdateUser,ChangePassword,ReviewVoucher,Strict
from pydantic import Field
from api.dependencies import services
from api.commercial import operation,Identifier
from services.admin_service import AdminError
from persistence.runtime_repository import RuntimeConflict
router=APIRouter()
auth=APIRouter(prefix='/api/admin/auth',tags=['admin-auth'])
@auth.post('/login')
def login(body:Login,request:Request):
    check_origin(request)
    service=admin_service(request)
    try: token=service.login(body.username,body.password.get_secret_value(),request_id.get())
    except AdminError:
        safe_event('admin_login_rejected')
        raise
    response=Response(status_code=204)
    response.set_cookie(service.settings.cookie_name,token,max_age=service.settings.lifetime,
        httponly=True,secure=service.settings.secure,samesite='strict',path='/api/admin')
    safe_event('admin_login_success')
    return response
@auth.get('/me')
def me(principal=Depends(require_browser)): return principal.public()
@auth.get('/csrf')
def csrf(request:Request,principal=Depends(require_browser)):
    if request.headers.get('sec-fetch-site')=='cross-site': raise AdminError('admin_origin',403)
    if request.headers.get('origin'): check_origin(request)
    service=admin_service(request)
    _,csrf=service.session(request.cookies.get(service.settings.cookie_name))
    return {'csrf_token':csrf}
@auth.post('/logout')
def logout(request:Request,principal=Depends(require_browser)):
    service=admin_service(request)
    service.repository.revoke(principal.session_hash,principal.actor,request_id.get())
    response=Response(status_code=204)
    response.delete_cookie(service.settings.cookie_name,path='/api/admin',secure=service.settings.secure,httponly=True,samesite='strict')
    return response
@auth.put('/password')
def my_password(body:ChangePassword,request:Request,principal=Depends(require_browser)):
    operation(lambda:admin_service(request).change_password(principal.id,body.password.get_secret_value(),principal.actor,request_id.get()))
    return {'status':'ok','sessions_revoked':True}
router.include_router(auth)
@router.get('/api/admin/roles')
def roles(principal=Depends(permission('users.read'))):
    from security.admin_policy import ROLES
    return {name:sorted(perms) for name,perms in ROLES.items()}
@router.get('/api/admin/users')
def users(request:Request,limit:int=Query(100,ge=1,le=100),offset:int=Query(0,ge=0,le=10000),principal=Depends(permission('users.read'))):
    return admin_service(request).repository.list_users(limit,offset)
@router.get('/api/admin/users/{identifier}')
def get_user(identifier:Identifier,request:Request,response:Response,principal=Depends(permission('users.read'))):
    result=operation(lambda:admin_service(request).repository.get_user(identifier))
    response.headers['ETag']=revision(result)
    return result
@router.post('/api/admin/users',status_code=201)
def create_user(body:CreateUser,request:Request,principal=Depends(permission('users.write'))):
    return operation(lambda:admin_service(request).create(body,principal.actor,request_id.get()))
@router.put('/api/admin/users/{identifier}')
def change_user(identifier:Identifier,body:UpdateUser,request:Request,principal=Depends(permission('users.write'))):
    return operation(lambda:admin_service(request).repository.change_user(identifier,body.model_dump(),principal.actor,request_id.get(),expected=request.headers.get('if-match')))
@router.put('/api/admin/users/{identifier}/password')
def change_password(identifier:Identifier,body:ChangePassword,request:Request,principal=Depends(permission('users.write'))):
    operation(lambda:admin_service(request).change_password(identifier,body.password.get_secret_value(),principal.actor,request_id.get()))
    return {'status':'ok','sessions_revoked':True}
@router.get('/api/admin/users/{identifier}/sessions')
def active_sessions(identifier:Identifier,request:Request,principal=Depends(permission('sessions.revoke'))):
    return admin_service(request).repository.sessions(identifier)
@router.post('/api/admin/users/{identifier}/sessions/revoke-all')
def revoke_all(identifier:Identifier,request:Request,principal=Depends(permission('sessions.revoke'))):
    operation(lambda:admin_service(request).repository.revoke_user(identifier,principal.actor,request_id.get()))
    return {'status':'ok'}
class RevokeSession(Strict):
    session_id:str=Field(pattern=r'^[a-f0-9]{32}$')
@router.post('/api/admin/users/{identifier}/sessions/revoke')
def revoke_session(identifier:Identifier,body:RevokeSession,request:Request,principal=Depends(permission('sessions.revoke'))):
    operation(lambda:admin_service(request).repository.revoke_one(identifier,body.session_id,principal.actor,request_id.get()))
    return {'status':'ok'}
@router.get('/api/admin/leads')
def leads(request:Request,limit:int=Query(100,ge=1,le=100),offset:int=Query(0,ge=0,le=10000),principal=Depends(permission('leads.read'))):
    return services(request).session.repository.list_operational('leads',limit,offset)
@router.get('/api/admin/vouchers')
def vouchers(request:Request,limit:int=Query(100,ge=1,le=100),offset:int=Query(0,ge=0,le=10000),status:Literal['pending_review','approved','rejected']|None=None,principal=Depends(permission('vouchers.read'))):
    return services(request).session.repository.list_operational('vouchers',limit,offset,status)
@router.post('/api/admin/vouchers/{identifier}/review')
def review(identifier:Identifier,body:ReviewVoucher,request:Request,principal=Depends(permission('vouchers.review'))):
    try:
        return services(request).session.repository.review_voucher(identifier,body.status,body.review_note,principal.actor,request_id.get())
    except RuntimeConflict as exc: raise AdminError('admin_voucher_transition',exc.status) from exc
@router.get('/api/admin/audit')
def audit(request:Request,limit:int=Query(100,ge=1,le=100),offset:int=Query(0,ge=0,le=10000),actor_user_id:str|None=Query(None,max_length=128),action:str|None=Query(None,max_length=64),resource_type:str|None=Query(None,max_length=64),resource_id:str|None=Query(None,max_length=128),since:date|None=None,until:date|None=None,principal=Depends(permission('audit.read'))):
    zone=timezone(timedelta(hours=-5))
    filters={'actor_user_id':actor_user_id,'action':action,'resource_type':resource_type,'resource_id':resource_id,'since':datetime.combine(since,datetime.min.time(),zone).timestamp() if since else None,'until':datetime.combine(until,datetime.max.time(),zone).timestamp() if until else None}
    return admin_service(request).audit(services(request).session.repository,limit,offset,filters)
@router.get('/admin/',include_in_schema=False)
def admin_page():
    return FileResponse(Path(__file__).resolve().parents[1]/'static/admin/index.html',headers={'Content-Security-Policy':FRONTEND_CSP,'Cache-Control':'no-store'})

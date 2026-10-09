"""Centralized cookie authentication, CSRF and explicitly temporary Bearer adapter."""
import hashlib,secrets
from fastapi import Depends,HTTPException,Request
from fastapi.security import HTTPAuthorizationCredentials,HTTPBearer
from api.dependencies import services
from commercial_runtime import admin_token
from security.logging import safe_event
from security.admin_policy import AdminPrincipal
from services.admin_service import AdminError
security=HTTPBearer(auto_error=False)
def admin_service(request:Request):
    selected=getattr(request.app.state,'admin_service',None) or services(request).admin
    if selected is None: raise HTTPException(503,'Administración no disponible')
    return selected

def check_origin(request):
    if admin_service(request).settings.secure and request.url.scheme!='https': raise AdminError('admin_https',403)
    origin=request.headers.get('origin')
    if not origin or origin not in request.app.state.security_settings.allowed_origins:
        raise AdminError('admin_origin',403)
    if request.headers.get('sec-fetch-site') in ('cross-site','none'): raise AdminError('admin_origin',403)

def require_browser(request:Request):
    service=admin_service(request)
    if service.settings.secure and request.url.scheme!='https': raise AdminError('admin_https',403)
    principal,csrf=service.session(request.cookies.get(service.settings.cookie_name))
    if request.method not in ('GET','HEAD','OPTIONS'):
        check_origin(request)
        candidate=request.headers.get('x-csrf-token','')
        if len(candidate)>128 or not secrets.compare_digest(csrf,candidate): raise AdminError('admin_csrf',403)
    return principal

def require_admin(request:Request,credentials:HTTPAuthorizationCredentials|None=Depends(security)):
    service=admin_service(request)
    if service.settings.secure and request.url.scheme!='https': raise AdminError('admin_https',403)
    # Never fall back to a Bearer credential when a browser cookie is present.
    if service.settings.cookie_name in request.cookies: return require_browser(request)
    if not service.settings.legacy_enabled: raise AdminError('admin_session',401)
    configured=getattr(request.app.state,'admin_api_token',None)
    configured=admin_token() if configured is None else configured
    if not configured: raise HTTPException(503,'Administración no disponible')
    candidate=credentials.credentials if credentials and credentials.scheme.lower()=='bearer' else ''
    if len(candidate)>512 or not secrets.compare_digest(hashlib.sha256(candidate.encode()).digest(),hashlib.sha256(configured.encode()).digest()):
        safe_event('admin_auth_rejected')
        raise HTTPException(401,'Credencial administrativa inválida',headers={'WWW-Authenticate':'Bearer'})
    safe_event('admin_legacy_token_used')
    return AdminPrincipal(None,'Compatibilidad Bearer','superadmin')

def permission(name):
    from security.admin_policy import ALL
    if name not in ALL: raise ValueError('Unknown permission')
    def authorize(principal=Depends(require_admin)):
        if name not in principal.permissions:
            safe_event('admin_permission_rejected')
            raise AdminError('admin_forbidden',403)
        return principal
    return authorize

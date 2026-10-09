"""Middleware ASGI sin buffers de respuesta: SSE conserva streaming y cancelación."""
import asyncio
import time
import uuid
from threading import RLock
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from security.config import SecuritySettings
from security.rate_limit import MemoryRateLimitStore, endpoint_group
from security.logging import request_id, safe_event, configure_logging

HEADERS = {
    'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer',
    'Content-Security-Policy': "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
    'Permissions-Policy': 'microphone=(self), camera=(), geolocation=(), payment=()',
}
MESSAGES = {400:'Solicitud inválida', 401:'Credencial requerida o inválida', 403:'Acceso no permitido',
    404:'Recurso no encontrado', 409:'Conflicto de configuración', 413:'Solicitud demasiado grande',
    422:'Campos inválidos', 429:'Demasiadas solicitudes; intenta más tarde', 500:'Error interno',
    502:'Proveedor no disponible', 503:'Servicio no disponible', 504:'Tiempo de espera agotado'}

SESSION_ERRORS = {
    'session_busy':'La sesión tiene una consulta en curso; espera o solicita reemplazo.',
    'session_exists':'La identidad solicitada ya existe; requiere su credencial.',
    'session_expired':'La sesión expiró; inicia una sesión nueva.',
    'session_not_found':'Credencial de sesión requerida o inválida.',
    'session_unauthorized':'Credencial de sesión requerida o inválida.',
    'interaction_cancelled':'La interacción fue cancelada o expiró.',
    'interaction_already_processed':'Esta interacción ya fue procesada; no se repiten sus acciones.',
    'idempotency_conflict':'La clave de reintento pertenece a otra operación.',
    'lead_already_associated':'La sesión ya tiene un prospecto asociado.',
    'lead_mismatch':'El prospecto no coincide con la sesión.',
    'lead_program_mismatch':'El programa o modalidad no coincide con el prospecto asociado.',
}

def error_response(status, code=None, headers=None):
    return JSONResponse({'status':'error', 'code':code or f'http_{status}',
        'message':MESSAGES.get(status, 'No se pudo completar la solicitud'), 'request_id':request_id.get()},
        status_code=status, headers=headers)

class ActiveRequests:
    def __init__(self):
        self.counts = {}
        self.lock = RLock()
    def enter(self, group, limit):
        with self.lock:
            if self.counts.get(group, 0) >= limit: return False
            self.counts[group] = self.counts.get(group, 0) + 1
            return True
    def leave(self, group):
        with self.lock: self.counts[group] -= 1

class ControlledCORSMiddleware(CORSMiddleware):
    def preflight_response(self, request_headers):
        response = super().preflight_response(request_headers)
        if response.status_code == 400:
            headers = {k:v for k,v in response.headers.items() if k.startswith('access-control-') or k == 'vary'}
            return error_response(400, 'cors_preflight_rejected', headers)
        return response

class SecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        state = scope['app'].state
        config = state.security_settings
        correlation = uuid.uuid4().hex
        token = request_id.set(correlation)
        started = False
        active = None
        begin = time.monotonic()
        header_pairs = scope.get('headers', [])
        headers = {k.lower():v for k,v in header_pairs}
        origin = headers.get(b'origin', b'').decode('latin-1')
        group = endpoint_group(scope['path'])

        async def safe_send(message):
            nonlocal started
            if message['type'] == 'http.response.start':
                started = True
                outgoing = list(message.get('headers', []))
                existing = {key.lower() for key,value in outgoing}
                for key,value in {**HEADERS, 'X-Request-ID':correlation}.items():
                    if key == 'Content-Security-Policy' and scope['path'] in ('/docs','/redoc'):
                        value = "default-src 'none'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
                    if key.lower().encode() not in existing: outgoing.append((key.lower().encode(),value.encode()))
                if origin in config.allowed_origins and b'access-control-allow-origin' not in existing:
                    outgoing.extend([(b'access-control-allow-origin',origin.encode()), (b'vary',b'Origin')])
                if scope['scheme'] == 'https':
                    outgoing.append((b'strict-transport-security', b'max-age=31536000'))
                if group in ('chat','leads','vouchers','admin','admin_login','reset') or scope['path']=='/reset-session':
                    outgoing = [(k,v) for k,v in outgoing if k.lower()!=b'cache-control']
                    outgoing.append((b'cache-control', b'no-store'))
                message = {**message, 'headers':outgoing}
                safe_event('request_completed', status=message['status'], group=group or 'other',
                           duration_ms=round((time.monotonic()-begin)*1000))
            await send(message)

        async def reject(status, code=None, retry=None):
            await error_response(status, code, {'Retry-After':str(retry)} if retry else None)(scope, receive, safe_send)

        try:
            if sum(len(k)+len(v) for k,v in header_pairs) > 16384:
                return await reject(400, 'headers_too_large')
            if origin and origin not in config.allowed_origins:
                return await reject(403, 'origin_not_allowed')
            if scope['method'] != 'OPTIONS' and group:
                peer = (scope.get('client') or ('unknown',))[0]
                policy = config.policies[group]
                retry = state.rate_limiter.consume(group + ':' + peer, policy.limit, policy.window)
                if retry: return await reject(429, 'rate_limited', retry)
            active_group = 'chat' if group == 'chat' else 'vouchers' if group == 'vouchers' else None
            if scope['path']=='/api/admin/branding-assets' and scope['method']=='POST':active_group='vouchers'
            if scope['path']=='/api/admin/voice-preview' and scope['method']=='POST':active_group='chat'
            if active_group:
                limit = config.max_active_ai if active_group == 'chat' else config.max_active_uploads
                if not state.active_requests.enter(active_group, limit):
                    return await reject(429, 'capacity_limited', 2)
                active = active_group
            branding_upload = scope['path']=='/api/admin/branding-assets' and scope['method']=='POST'
            limit = 3*1024*1024 if branding_upload else config.upload_request_max_bytes if group == 'vouchers' else config.admin_max_bytes if group == 'admin' else config.json_max_bytes
            lengths = [v for k,v in header_pairs if k.lower() == b'content-length']
            if len(lengths) > 1 or (lengths and (len(lengths[0]) > 16 or not lengths[0].isdigit())):
                return await reject(400, 'invalid_content_length')
            if lengths and int(lengths[0]) > limit: return await reject(413)
            if headers.get(b'content-encoding', b'identity') != b'identity':
                return await reject(400, 'content_encoding_not_supported')
            body = bytearray()
            async with asyncio.timeout(config.body_timeout):
                while True:
                    message = await receive()
                    if message['type'] == 'http.disconnect': return
                    chunk = message.get('body', b'')
                    if len(body)+len(chunk) > limit: return await reject(413)
                    body.extend(chunk)
                    if not message.get('more_body'): break
            delivered = False
            async def replay_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type':'http.request', 'body':bytes(body), 'more_body':False}
                return await receive()
            await self.app(scope, replay_receive, safe_send)
        except asyncio.CancelledError:
            safe_event('request_cancelled', group=group or 'other')
            raise
        except TimeoutError as exc:
            safe_event('request_timeout', error=exc)
            if not started: await reject(504)
        except Exception as exc:
            safe_event('request_failed', error=exc)
            if not started: await reject(500)
        finally:
            if active: state.active_requests.leave(active)
            request_id.reset(token)

def install_security(app, config=None):
    configure_logging()
    config = config or SecuritySettings.from_env()
    app.state.security_settings = config
    app.state.rate_limiter = MemoryRateLimitStore(config.limiter_max_keys)
    app.state.active_requests = ActiveRequests()
    app.add_middleware(ControlledCORSMiddleware, allow_origins=list(config.allowed_origins), allow_credentials=False,
        allow_methods=['GET','POST','PUT','OPTIONS'], allow_headers=['Content-Type','Authorization','X-Request-ID','X-Session-Token','Idempotency-Key','If-None-Match','X-CSRF-Token','If-Match'],
        expose_headers=['X-Request-ID','X-Operation-ID','Retry-After','ETag'])
    app.add_middleware(SecurityMiddleware)

    from domain.errors import DomainError
    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        if exc.code.startswith('admin_') or exc.code=='weak_password' or exc.code in {'lead_changed','lead_transition','lead_not_found','task_transition','task_not_found','assignee_invalid','loss_note_required','idempotency_required'}:
            messages={'admin_record_changed':'Este registro fue modificado por otro usuario. Recarga antes de guardar.','admin_credentials':'Credenciales incorrectas','weak_password':'La contraseña no cumple la política de seguridad'}
            return JSONResponse({'status':'error','code':exc.code,'message':messages.get(exc.code,MESSAGES.get(exc.status,'Solicitud inválida')),'request_id':request_id.get()},status_code=exc.status,headers={'Retry-After':str(getattr(exc,'retry',None) or 2)} if exc.status==429 else None)
        if exc.code in SESSION_ERRORS:
            return JSONResponse({'status':'error','code':exc.code,'message':SESSION_ERRORS[exc.code],
                'request_id':request_id.get()}, status_code=exc.status)
        return error_response(exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_fields(request, exc):
        return error_response(422, 'validation_error')  # No reflejar input, ctx ni excepción Pydantic.

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        if isinstance(exc.detail,str) and exc.detail in SESSION_ERRORS:
            return JSONResponse({'status':'error','code':exc.detail,'message':SESSION_ERRORS[exc.detail],
                'request_id':request_id.get()}, status_code=exc.status_code, headers=exc.headers)
        response = error_response(exc.status_code, headers=exc.headers)
        # Detalles 4xx emitidos exclusivamente por código propio, nunca mensajes de proveedor.
        if exc.status_code in (400,401,403,404,409) and isinstance(exc.detail,str):
            # Sólo preservar conflictos de negocio conocidos; no rutas ni valores arbitrarios.
            if exc.detail.startswith(('Tarifas/campañas superpuestas:', 'El identificador ya existe',
                                      'Selecciona otro avatar', 'Debe seleccionarse', 'Avatar seleccionado',
                                      'Un avatar deshabilitado', 'Alias de programa', 'La tarifa utiliza')):
                import json
                data = dict(status='error', code=f'http_{exc.status_code}', message=exc.detail, request_id=request_id.get())
                response = JSONResponse(data, status_code=exc.status_code, headers=exc.headers)
        return response


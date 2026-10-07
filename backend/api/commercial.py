"""Rutas administrativas separadas y bloqueadas sin credencial explícita."""
import secrets
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError
from commercial_runtime import admin_token, get_repository
from persistence.models import ProgramRecord, PriceRecord, CampaignRecord, AvatarRecord, SettingsRecord
from services.commercial_service import CommercialService
from services.avatar_service import AvatarService

public_router = APIRouter()
security = HTTPBearer(auto_error=False)

def service(request: Request):
    return getattr(request.app.state, 'commercial_service', None) or CommercialService(get_repository())

def require_admin(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(security)):
    token = getattr(request.app.state, 'admin_api_token', None)
    token = admin_token() if token is None else token
    if not token:
        raise HTTPException(503, 'Administración deshabilitada: falta configurar ADMIN_API_TOKEN')
    if not credentials or credentials.scheme.lower() != 'bearer' or not secrets.compare_digest(credentials.credentials.encode('utf-8'), token.encode('utf-8')):
        raise HTTPException(401, 'Credencial administrativa inválida', headers={'WWW-Authenticate': 'Bearer'})
    return 'admin-token'

admin_router = APIRouter(prefix='/api/admin', dependencies=[Depends(require_admin)], tags=['commercial-admin'])

def operation(callback):
    try:
        return callback()
    except ValidationError as exc:
        raise HTTPException(422, 'Configuración inválida: ' + '; '.join(e['msg'] for e in exc.errors())) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

@public_router.get('/api/config')
def public_config(commercial: CommercialService = Depends(service)):
    return AvatarService(commercial.repository).public_config()

def register_resource(resource, model):
    # Los nombres de recursos son constantes; no hay nombres SQL provenientes del cliente.
    def list_records(commercial: CommercialService = Depends(service)):
        return commercial.list(resource)
    def get_record(identifier: str, commercial: CommercialService = Depends(service)):
        record = commercial.get(resource, identifier)
        if record is None:
            raise HTTPException(404, 'Registro inexistente')
        return record
    def create_record(body: model, commercial: CommercialService = Depends(service)):
        return operation(lambda: commercial.save(resource, body.model_dump(mode='json'), create=True))
    def update_record(identifier: str, body: model, commercial: CommercialService = Depends(service)):
        if body.id != identifier:
            raise HTTPException(422, 'ID del cuerpo diferente del ID de la ruta')
        if commercial.get(resource, identifier) is None:
            raise HTTPException(404, 'Registro inexistente')
        return operation(lambda: commercial.save(resource, body.model_dump(mode='json')))
    admin_router.add_api_route('/' + resource, list_records, methods=['GET'], name='list_' + resource)
    admin_router.add_api_route('/' + resource + '/{identifier}', get_record, methods=['GET'], name='get_' + resource)
    admin_router.add_api_route('/' + resource, create_record, methods=['POST'], status_code=201, name='create_' + resource)
    admin_router.add_api_route('/' + resource + '/{identifier}', update_record, methods=['PUT'], name='update_' + resource)

for resource, model in [('programs', ProgramRecord), ('prices', PriceRecord), ('campaigns', CampaignRecord), ('avatars', AvatarRecord)]:
    register_resource(resource, model)

@admin_router.post('/avatars/{identifier}/activate')
def activate(identifier: str, commercial: CommercialService = Depends(service)):
    return operation(lambda: commercial.activate_avatar(identifier))

@admin_router.get('/settings')
def settings(commercial: CommercialService = Depends(service)):
    return commercial.settings()

@admin_router.put('/settings')
def save_settings(body: SettingsRecord, commercial: CommercialService = Depends(service)):
    return operation(lambda: commercial.save_settings(body.model_dump(mode='json')))

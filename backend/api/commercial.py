"""Rutas administrativas separadas y bloqueadas sin credencial explícita."""
from fastapi import APIRouter, Depends, HTTPException, Request, Path, Response
from typing import Annotated
from pydantic import ValidationError
from api.dependencies import services
from security.auth import require_admin, permission
from persistence.models import ProgramRecord, PriceRecord, CampaignRecord, AvatarRecord, SettingsRecord
from services.commercial_service import CommercialService
from security.logging import request_id
from domain.revision import revision

Identifier = Annotated[str, Path(min_length=1, max_length=128, pattern=r'^[a-zA-Z0-9_-]+$')]

def service(request: Request):
    return getattr(request.app.state, 'commercial_service', None) or services(request).commercial

admin_router = APIRouter(prefix='/api/admin', dependencies=[Depends(require_admin)], tags=['commercial-admin'])

def operation(callback):
    try:
        return callback()
    except ValidationError as exc:
        raise HTTPException(422, 'Configuración inválida: ' + '; '.join(e['msg'] for e in exc.errors())) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

def register_resource(resource, model):
    # Los nombres de recursos son constantes; no hay nombres SQL provenientes del cliente.
    def list_records(commercial: CommercialService = Depends(service)):
        return commercial.list(resource)
    def get_record(identifier: Identifier, response: Response, commercial: CommercialService = Depends(service)):
        record = commercial.get(resource, identifier)
        if record is None:
            raise HTTPException(404, 'Registro inexistente')
        response.headers['ETag'] = revision(record)
        return record
    def create_record(body: model, commercial: CommercialService = Depends(service), principal=Depends(permission(resource+'.write'))):
        return operation(lambda: commercial.save(resource, body.model_dump(mode='json'), principal.actor, create=True, request_id=request_id.get()))
    def update_record(identifier: Identifier, body: model, request: Request, commercial: CommercialService = Depends(service), principal=Depends(permission(resource+'.write'))):
        if body.id != identifier:
            raise HTTPException(422, 'ID del cuerpo diferente del ID de la ruta')
        if commercial.get(resource, identifier) is None:
            raise HTTPException(404, 'Registro inexistente')
        return operation(lambda: commercial.save(resource, body.model_dump(mode='json'), principal.actor, request_id=request_id.get(), expected=request.headers.get('if-match')))
    admin_router.add_api_route('/' + resource, list_records, methods=['GET'], name='list_' + resource, dependencies=[Depends(permission(resource+'.read'))])
    admin_router.add_api_route('/' + resource + '/{identifier}', get_record, methods=['GET'], name='get_' + resource, dependencies=[Depends(permission(resource+'.read'))])
    admin_router.add_api_route('/' + resource, create_record, methods=['POST'], status_code=201, name='create_' + resource)
    admin_router.add_api_route('/' + resource + '/{identifier}', update_record, methods=['PUT'], name='update_' + resource)

for resource, model in [('programs', ProgramRecord), ('prices', PriceRecord), ('campaigns', CampaignRecord), ('avatars', AvatarRecord)]:
    register_resource(resource, model)

@admin_router.post('/avatars/{identifier}/activate')
def activate(identifier: Identifier, request: Request, commercial: CommercialService = Depends(service), principal=Depends(permission('avatars.write'))):
    return operation(lambda: commercial.activate_avatar(identifier, principal.actor, request_id=request_id.get(), expected=request.headers.get('if-match')))

@admin_router.get('/settings', dependencies=[Depends(permission('settings.read'))])
def settings(response: Response, commercial: CommercialService = Depends(service)):
    result = commercial.settings()
    response.headers['ETag'] = revision(result)
    return result

@admin_router.put('/settings')
def save_settings(body: SettingsRecord, request: Request, commercial: CommercialService = Depends(service), principal=Depends(permission('settings.write'))):
    return operation(lambda: commercial.save_settings(body.model_dump(mode='json'), principal.actor, request_id=request_id.get(), expected=request.headers.get('if-match')))

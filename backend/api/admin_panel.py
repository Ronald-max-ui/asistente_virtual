"""Small authenticated panel adapter; installed files only, atomic campaign editing."""
from fastapi import APIRouter,Depends,Request,Query
from fastapi.responses import FileResponse
from pydantic import Field
from domain.admin import Strict
from persistence.models import CampaignRecord,PriceRecord
from security.auth import require_admin,permission
from api.dependencies import services
from api.commercial import service,operation,Identifier
from services.admin_panel_service import AdminPanelService
from security.logging import request_id
from typing import Literal
router=APIRouter(prefix='/api/admin/panel',dependencies=[Depends(require_admin)])
def panel(request:Request):
    app=services(request)
    return AdminPanelService(service(request),app.pricing,app.session.repository,app.health)
@router.get('/context')
def context(request:Request,principal=Depends(require_admin)):
    return panel(request).context(principal.permissions)
@router.get('/dashboard')
def dashboard(request:Request,principal=Depends(require_admin)):
    result=panel(request).dashboard(principal.permissions)
    if getattr(request.app.state,'prewarm_status','disabled') in ('warming','invalid'):result['operational']=False
    return result
@router.get('/base-price')
def base_price(request:Request,program:str=Query(max_length=64),concept:Literal['inscripcion','matricula','mensualidad','mensualidad_contado','pago_contado','ciclo_completo','descuento']='inscripcion',modality:str|None=Query(None,max_length=64),shift:str|None=Query(None,max_length=64),principal=Depends(permission('prices.read'))):
    return operation(lambda:services(request).pricing.resolve_base(program,concept,modality,shift))
class CampaignOffer(Strict):
    campaign:CampaignRecord
    price:PriceRecord
    create:bool=False
    campaign_revision:str|None=Field(None,max_length=128)
    price_revision:str|None=Field(None,max_length=128)
@router.post('/campaign-offer',dependencies=[Depends(permission('prices.write'))])
def campaign_offer(body:CampaignOffer,request:Request,principal=Depends(permission('campaigns.write'))):
    return operation(lambda:service(request).save_campaign_offer(body.campaign.model_dump(mode='json'),body.price.model_dump(mode='json'),principal.actor,request_id.get(),create=body.create,expected_campaign=body.campaign_revision,expected_price=body.price_revision))
@router.get('/vouchers/{identifier}/file')
def voucher_file(identifier:Identifier,request:Request,principal=Depends(permission('vouchers.read'))):
    path,mime=panel(request).voucher_file(identifier,services(request).vouchers.directory)
    return FileResponse(path,media_type=mime,filename='comprobante'+path.suffix,content_disposition_type='inline',headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; frame-ancestors 'self'"})

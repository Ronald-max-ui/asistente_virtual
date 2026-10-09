"""Scoped administrative API; PII searches are POST bodies, never querystrings."""
from typing import Literal
from fastapi import APIRouter,Depends,Request,Response,Query
from api.dependencies import services
from api.commercial import Identifier
from security.auth import permission,admin_service
from security.inputs import validated_key
from security.logging import request_id
from services.lead_operations_service import LeadOperationsService
from persistence.lead_operations_repository import LeadOperationsRepository
from domain.lead_operations import Search,UpdateTracking,Activity,CreateTask,CompleteTask
from domain.errors import DomainError
router=APIRouter(prefix='/api/admin/operations')
def service(request):return LeadOperationsService(LeadOperationsRepository(services(request).session.repository),admin_service(request).repository)
def mutation(id,kind,body,request,actor,task=None):
    key=validated_key(request.headers.get('Idempotency-Key'))
    if not key:raise DomainError('idempotency_required',422)
    return service(request).mutate(id,kind,body,actor,request_id.get(),request.headers.get('if-match'),key,task)
@router.post('/leads/search')
def search(body:Search,request:Request,principal=Depends(permission('leads.read'))):return service(request).search(body,principal.actor)
@router.get('/assignees')
def assignees(request:Request,principal=Depends(permission('leads.read'))):return service(request).assignees()
@router.get('/leads/{id}')
def profile(id:Identifier,request:Request,response:Response,principal=Depends(permission('leads.read'))):
    result=service(request).profile(id,principal.permissions);response.headers['ETag']=result['etag'];return result
@router.get('/leads/{id}/activities')
def activity_history(id:Identifier,request:Request,limit:int=Query(21,ge=1,le=100),offset:int=Query(0,ge=0,le=10000),principal=Depends(permission('leads.read'))):
    app=service(request);return app.names(app.repository.activities(id,limit,offset))
@router.put('/leads/{id}')
def update(id:Identifier,body:UpdateTracking,request:Request,principal=Depends(permission('leads.write'))):return mutation(id,'tracking',body,request,principal.actor)
@router.post('/leads/{id}/activities')
def activity(id:Identifier,body:Activity,request:Request,principal=Depends(permission('leads.write'))):return mutation(id,'activity',body,request,principal.actor)
@router.post('/leads/{id}/tasks')
def task(id:Identifier,body:CreateTask,request:Request,principal=Depends(permission('leads.write'))):return mutation(id,'task_create',body,request,principal.actor)
@router.post('/leads/{id}/tasks/{task_id}')
def complete(id:Identifier,task_id:Identifier,body:CompleteTask,request:Request,principal=Depends(permission('leads.write'))):return mutation(id,'task_update',body,request,principal.actor,task_id)
@router.get('/analytics')
def analytics(request:Request,period:Literal['7d','30d','month']='7d',principal=Depends(permission('leads.read'))):
    data=service(request).repository.aggregates(period)
    if 'vouchers.read' not in principal.permissions:data.pop('voucher_counts')
    return data
@router.get('/voucher-counts')
def voucher_counts(request:Request,principal=Depends(permission('vouchers.read'))):return service(request).repository.aggregates()['voucher_counts']
@router.post('/leads/export')
def export(body:Search,request:Request,principal=Depends(permission('leads.export'))):
    content=service(request).export(body,principal.actor,request_id.get())
    return Response(content,media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="prospectos.csv"','X-Export-Limit':'1000','Cache-Control':'no-store'})

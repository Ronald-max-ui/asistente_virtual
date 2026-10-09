"""Health transport; probes live in health_service."""
import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from api.dependencies import services
from api.commercial import service
router = APIRouter()

@router.get('/health')
@router.get('/health/live')
async def health_check(): return {'status':'alive','version':'4.0.0'}

@router.get('/health/ready')
async def ready_check(request: Request):
    result = await asyncio.to_thread(services(request).health, service(request).repository, services(request).session.repository)
    prewarm=getattr(request.app.state,'prewarm_status','disabled')
    result['prewarm']={'status':prewarm}
    if prewarm in ('warming','invalid'): result['status']='not_ready'
    if prewarm=='invalid':
        result['checks']['knowledge']=False;result['knowledge']={'status':'invalid'}
    # Failure can be a timeout; validated local knowledge still determines readiness.
    from security.logging import safe_event
    if result.get('knowledge',{}).get('status')=='stale':safe_event('knowledge_stale')
    safe_event('ready' if result['status']=='ready' else 'degraded')
    return JSONResponse(result, status_code=200 if result['status']=='ready' else 503)

"""Authenticated branding/voice tools and allowlisted public assets."""
import asyncio,base64
from typing import Literal
from fastapi import APIRouter,Depends,Request,UploadFile,File,Form,HTTPException
from fastapi.responses import FileResponse
from security.auth import permission
from security.logging import request_id
from api.dependencies import services
from domain.voice import VoiceConfig
from services.voice_service import VoiceService
from services.branding_service import BrandingService
from persistence.branding_repository import BrandingRepository
from api.commercial import service
router=APIRouter()
def branding(request):
    app=services(request)
    return app.branding or BrandingService(BrandingRepository(service(request).repository),service(request).repository.path.parent/'branding')
@router.get('/api/admin/branding-assets')
def assets(request:Request,principal=Depends(permission('settings.read'))):return branding(request).list()
@router.post('/api/admin/branding-assets',status_code=201)
async def upload(request:Request,purpose:Literal['logo','favicon']=Form(),file:UploadFile=File(),principal=Depends(permission('settings.write'))):
    return await branding(request).upload(file,purpose,request.app.state.security_settings,principal.actor,request_id.get())
@router.get('/static/branding/{filename}')
def image(filename:str,request:Request):
    path,record=branding(request).file(filename)
    return FileResponse(path,media_type=record['mime'],headers={'Cache-Control':'public, max-age=31536000, immutable','ETag':'"'+record['sha256']+'"','Content-Security-Policy':"default-src 'none'",'X-Content-Type-Options':'nosniff'})
@router.get('/api/admin/voices')
def voices(request:Request,principal=Depends(permission('settings.read'))):
    voice=VoiceService(service(request).repository)
    return {'voices':voice.catalogue(),'current':voice.public()}
@router.post('/api/admin/voice-preview')
async def preview(body:VoiceConfig,request:Request,principal=Depends(permission('settings.write'))):
    retry=request.app.state.rate_limiter.consume('voice-preview:'+principal.actor,5,60)
    if retry:raise HTTPException(429,headers={'Retry-After':str(retry)})
    if not body.enabled:raise HTTPException(422)
    app=services(request)
    try:
        call=getattr(app.speech,'synthesize_configured',None)
        if call is None:raise RuntimeError('Speech preview unavailable')
        audio=await asyncio.wait_for(call('Hola. Estoy lista para ayudarte.',body.model_dump()),request.app.state.security_settings.tts_timeout)
        return {'audio_b64':base64.b64encode(audio).decode()}
    except asyncio.CancelledError:raise
    except Exception as exc:raise HTTPException(503) from exc

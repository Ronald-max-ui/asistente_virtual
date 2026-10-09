"""Session HTTP boundary; repository policies remain in SessionManager."""
import time
from security.logging import safe_event
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from api.dependencies import services
from security.inputs import ChatInput, SessionInput, CancelInput, validated_key
router = APIRouter()
@router.post('/api/session')
async def create_session(data: SessionInput, request: Request):
    started=time.perf_counter()
    result = await services(request).session.bootstrap(data.session_id, request.headers.get('X-Session-Token'))
    safe_event('session_bootstrap_metrics',session_bootstrap_ms=(time.perf_counter()-started)*1000)
    return JSONResponse(result, headers={'Cache-Control':'no-store'})

@router.post('/api/session/cancel')
async def cancel_session(data: CancelInput, request: Request):
    await services(request).session.authorize(data.session_id, request.headers.get('X-Session-Token'))
    # Validate the same bounded key contract as chat/forms.
    key = validated_key(request.headers.get('Idempotency-Key'))
    return await services(request).session.cancel(data.session_id, data.active_request_id, key=key)

@router.post('/reset-session')
async def reset_session(data: ChatInput, request: Request):
    await services(request).session.authorize(data.session_id, request.headers.get('X-Session-Token'))
    key = data.idempotency_key or validated_key(request.headers.get('Idempotency-Key'))
    return await services(request).session.cancel(data.session_id, reset=True, key=key)

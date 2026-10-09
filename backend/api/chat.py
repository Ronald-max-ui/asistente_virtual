"""JSON and SSE transport adapters for the same conversation service."""
import json
import anyio
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from api.dependencies import services
from security.inputs import ChatInput
from services.llm_protocol import ChatResponse, SSE_SCHEMA

router = APIRouter()

def encode_event(payload):
    payload = SSE_SCHEMA.validate_python(payload).model_dump(mode='json')
    name = 'event: ' + payload['type'] + '\n' if payload['type'] in ('mode_switch','ui_action') else ''
    return name + 'data: ' + json.dumps(payload, ensure_ascii=False) + '\n\n'

@router.post('/chat/stream')
async def responder_streaming(data: ChatInput, request: Request):
    conversation = services(request).conversation
    turn = await conversation.prepare(data, request.headers.get('X-Session-Token'))
    async def transport():
        events = conversation.events(turn, request.app.state.security_settings)
        try:
            async for event in events:
                yield encode_event(event)
        finally:
            with anyio.CancelScope(shield=True):
                await events.aclose()
    return StreamingResponse(transport(), media_type='text/event-stream', headers={
        'Cache-Control':'no-store','X-Accel-Buffering':'no','Connection':'keep-alive','X-Operation-ID':turn.request_id})

@router.post('/chat', response_model=ChatResponse)
async def responder_con_voz(data: ChatInput, request: Request):
    conversation = services(request).conversation
    turn = await conversation.prepare(data, request.headers.get('X-Session-Token'))
    return await conversation.complete(turn, request.app.state.security_settings, request)

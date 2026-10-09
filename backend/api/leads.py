"""Lead request validation and transport; operations own commercial persistence."""
from fastapi import APIRouter, Request, Form
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from fastapi.exceptions import RequestValidationError
from api.dependencies import services
from security.inputs import LeadInput
from security.logging import safe_event
router = APIRouter()

@router.post('/api/leads')
async def registrar_lead(
    request: Request,
    nombre:     str = Form(...),
    whatsapp:   str = Form(...),
    carrera:    str = Form(...),
    notas:      str = Form(""),
    session_id: str = Form(""),
    modalidad: str = Form(""),
    origen: str = Form("web"),
):
    """
    Guarda un prospecto en el repositorio operativo.
    Actualiza la sesión activa marcando lead_submitted = True y funnel_stage = 'lead_captured'.
    """
    try:
        form = LeadInput(nombre=nombre, whatsapp=whatsapp, carrera=carrera, notas=notas, session_id=session_id,
                         modalidad=modalidad, origen=origen, idempotency_key=request.headers.get("Idempotency-Key"))
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    if form.session_id:
        await services(request).session.authorize(form.session_id, request.headers.get('X-Session-Token'))
    result = await services(request).operational.lead(form.session_id or None, form)
    safe_event('lead_created', record_id=result['lead_id'])
    return JSONResponse(result)

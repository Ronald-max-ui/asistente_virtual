"""Voucher multipart transport, without payment business rules."""
from fastapi import APIRouter, Request, Form, File, UploadFile
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from security.inputs import VoucherInput
from api.dependencies import services
router = APIRouter()

@router.post('/api/vouchers')
async def subir_voucher(
    request: Request,
    imagen:   UploadFile = File(...),
    monto:    str        = Form(...),
    carrera:  str        = Form(...),
    whatsapp: str        = Form(""),
    concepto: str        = Form("matricula"),
    modalidad: str       = Form(""),
    turno: str           = Form(""),
    session_id: str = Form(""),
    lead_id: str | None = Form(None),
):
    """Validate form and adapt the application result to HTTP."""
    try:
        form = VoucherInput(monto=monto, carrera=carrera, whatsapp=whatsapp, concepto=concepto, modalidad=modalidad, turno=turno,
                            session_id=session_id, lead_id=lead_id, idempotency_key=request.headers.get("Idempotency-Key"))
    except ValidationError as exc:
        await imagen.close()
        raise RequestValidationError(exc.errors()) from exc
    result = await services(request).vouchers.submit(form, imagen, request.headers.get('X-Session-Token'), request.app.state.security_settings)
    return JSONResponse(result.content, status_code=result.status_code)

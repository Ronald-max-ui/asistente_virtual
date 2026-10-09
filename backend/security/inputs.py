"""Contratos de entrada acotados, independientes del transporte Form/JSON."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictStr, StrictBool, field_validator
from security.config import MAX_MESSAGE, MAX_SESSION_ID, MAX_NAME, MAX_PHONE, MAX_NOTES, MAX_COMMERCIAL

def normalized_phone(value):
    if not value: return value
    digits = ''.join(c for c in value if c in '0123456789')
    if not 7 <= len(digits) <= 15:
        raise ValueError('Teléfono debe contener entre 7 y 15 dígitos')
    return ('+' if value.startswith('+') else '') + digits
class ChatInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mensaje: StrictStr = Field(max_length=MAX_MESSAGE)
    session_id: StrictStr = Field(default='kiosco_principal', min_length=1, max_length=MAX_SESSION_ID,
        pattern=r'^[a-zA-Z0-9_.:/-]+$')
    mode: Literal['web','kiosk'] | None = 'web'
    persona: Literal['info','sales'] | None = None
    replace_active: StrictBool = False
    idempotency_key: StrictStr | None = Field(default=None, min_length=1, max_length=128, pattern=r'^[a-zA-Z0-9_-]+$')

class SessionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: StrictStr | None = Field(default=None, min_length=1, max_length=MAX_SESSION_ID, pattern=r'^[a-zA-Z0-9_.:/-]+$')

class CancelInput(SessionInput):
    session_id: StrictStr = Field(min_length=1, max_length=MAX_SESSION_ID, pattern=r'^[a-zA-Z0-9_.:/-]+$')
    active_request_id: StrictStr | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')

def validated_key(value):
    from pydantic import ValidationError
    from fastapi.exceptions import RequestValidationError
    try:
        return ChatInput(mensaje='', idempotency_key=value).idempotency_key
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc

class LeadInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    nombre: StrictStr = Field(min_length=1, max_length=MAX_NAME, pattern=r'^[^\x00-\x1f\x7f]+$')
    whatsapp: StrictStr = Field(min_length=7, max_length=MAX_PHONE, pattern=r'^\+?[0-9 ()-]{7,24}$')
    carrera: StrictStr = Field(max_length=MAX_COMMERCIAL)
    notas: StrictStr = Field(default='', max_length=MAX_NOTES)
    session_id: StrictStr = Field(default='', max_length=MAX_SESSION_ID, pattern=r'^[a-zA-Z0-9_.:/-]*$')
    modalidad: StrictStr = Field(default='', max_length=64)
    origen: Literal['web','kiosk'] = 'web'
    idempotency_key: StrictStr | None = Field(default=None, min_length=1, max_length=128, pattern=r'^[a-zA-Z0-9_-]+$')
    _phone = field_validator('whatsapp')(normalized_phone)

class VoucherInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    monto: StrictStr = Field(min_length=1, max_length=24, pattern=r'^\d{1,8}(?:\.\d{1,2})?$')
    carrera: StrictStr = Field(min_length=1, max_length=MAX_COMMERCIAL)
    whatsapp: StrictStr = Field(default='', max_length=MAX_PHONE, pattern=r'^(?:\+?[0-9 ()-]{7,24})?$')
    concepto: StrictStr = Field(default='matricula', min_length=1, max_length=64)
    modalidad: StrictStr = Field(default='', max_length=64)
    turno: StrictStr = Field(default='', max_length=64)
    session_id: StrictStr = Field(default='', max_length=MAX_SESSION_ID, pattern=r'^[a-zA-Z0-9_.:/-]*$')
    lead_id: StrictStr | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    idempotency_key: StrictStr | None = Field(default=None, min_length=1, max_length=128, pattern=r'^[a-zA-Z0-9_-]+$')
    _phone = field_validator('whatsapp')(normalized_phone)

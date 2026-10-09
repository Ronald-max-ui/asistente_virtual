"""Voucher orchestration: session association, live tariff and safe upload."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from domain.errors import SessionError
from services.pricing_service import CatalogError, aviso_pago_bloqueado
from services.voucher_service import read_validated_image
from security.logging import safe_event

@dataclass
class VoucherResult:
    content: dict
    status_code: int = 200

class VoucherSubmissionService:
    def __init__(self, sessions, operational, resolve_price, directory):
        self.sessions, self.operational = sessions, operational
        self.resolve_price, self.directory = resolve_price, directory

    async def submit(self, form, imagen, token, config):
        try:
            return await self._submit(form, imagen, token, config)
        finally:
            await imagen.close()

    async def _submit(self, form, imagen, token, config):
        associated_lead = None
        if form.session_id:
            association = await self.sessions.authorize(form.session_id, token)
            associated_lead = association["lead_id"]
            if form.lead_id and form.lead_id != associated_lead:
                raise SessionError("lead_mismatch", 409)
        elif form.lead_id:
            raise SessionError("session_unauthorized", 401)
        monto, carrera = form.monto, form.carrera
        concepto, modalidad, turno = form.concepto, form.modalidad, form.turno
        try:
            tariff = self.resolve_price(carrera, concepto, modalidad or None, turno or None)
        except CatalogError:
            return VoucherResult({"status": "error", "message": "La configuración comercial necesita revisión."}, status_code=409)
        except ValueError:
            return VoucherResult({"status": "error", "message": "Programa, concepto o variante no válido."}, status_code=422)
        pago = {"monto": tariff["amount"], "carrera": tariff["program_label"]}
        notice = aviso_pago_bloqueado(tariff)
        if notice:
            return VoucherResult({"status": "error", **notice}, status_code=409)
        try:
            declarado = Decimal(monto)
            if not declarado.is_finite() or declarado != Decimal(pago["monto"]):
                raise ValueError("Importe distinto del catálogo")
        except (InvalidOperation, ValueError):
            return VoucherResult({"status": "error", "message": "El importe no coincide con la tarifa autorizada."}, status_code=422)

        content, extension = await read_validated_image(imagen, config)
        # Revalidar tras decodificar; una actualización comercial no permite guardar una tarifa antigua.
        current = self.resolve_price(form.carrera, concepto, modalidad or None, turno or None)
        notice = aviso_pago_bloqueado(current)
        if notice or any(current[key] != tariff[key] for key in ('amount','currency','status','campaign','starts_on','ends_on')):
            return VoucherResult({'status':'error','code':'price_changed','message':'La tarifa cambió; consulta el precio vigente.'}, status_code=409)
        result = await self.operational.voucher(form.session_id or None, current, content,
            extension, self.directory, form.idempotency_key, associated_lead)
        safe_event('voucher_created', record_id=result['voucher_id'], bytes=len(content))
        return VoucherResult(result)

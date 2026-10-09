"""Prospectos/comprobantes: asociaciones y reintentos transaccionales."""
import hashlib
import uuid
from pathlib import Path
from domain.idempotency import fingerprint
from domain.errors import CommercialInputError
from security.storage import atomic_private_write
from services.pricing_service import pricing_service


class OperationalService:
    def __init__(self, sessions, pricing=None):
        self.sessions = sessions
        self.pricing = pricing or pricing_service

    async def lead(self, sid, form):
        try:
            program = self.pricing.normalize_program(form.carrera) if form.carrera else None
            if form.modalidad and (not program or form.modalidad not in self.pricing.catalogs()[program].modalities):
                raise ValueError('Invalid modality')
        except ValueError as exc:
            raise CommercialInputError() from exc
        return await self.sessions.call('save_lead', sid, dict(name=form.nombre, whatsapp=form.whatsapp,
            program=program, modality=form.modalidad or None, origin=form.origen, notes=form.notas), form.idempotency_key)

    async def voucher(self, sid, tariff, content, extension, directory, key, expected_lead=None):
        root = Path(directory).resolve()
        if extension not in ('.png', '.jpg', '.webp'):
            raise ValueError('Invalid extension')
        digest = fingerprint({'program':tariff['program'], 'modality':tariff['modality'], 'shift':tariff['shift'],
            'concept':tariff['concept'], 'amount':tariff['amount'], 'currency':tariff['currency'],
            'image_hash':hashlib.sha256(content).hexdigest(), 'expected_lead':expected_lead})
        def write():
            identifier = uuid.uuid4().hex
            reference = identifier + extension
            atomic_private_write(root / reference, content)
            return identifier, reference
        def remove(reference):
            (root / reference).unlink(missing_ok=True)
        return await self.sessions.call('save_voucher', sid, tariff, digest, key, write, remove, expected_lead, bool(sid))

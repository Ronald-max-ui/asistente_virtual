"""Tarifas vigentes desde persistencia; lector JSON sólo para migración/compatibilidad."""
import hashlib
import json
import re
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import RLock
from services.consent_service import normalizar

from domain.pricing import CONCEPTOS, StrictModel, Promotion, PriceEntry, ProgramCatalog

_LABELS = {"inscripcion":"inscripción", "matricula":"matrícula", "mensualidad":"mensualidad", "mensualidad_contado":"mensualidad al contado", "pago_contado":"pago al contado", "ciclo_completo":"ciclo completo", "descuento":"descuento"}
_KNOWLEDGE = Path(__file__).resolve().parents[1] / "knowledge"

class CatalogError(ValueError):
    """Configuración inválida: nunca usar un importe antiguo de respaldo."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Campo JSON duplicado")
        result[key] = value
    return result


def _number(value: Decimal | None):
    return None if value is None else format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else format(value, "f")

class PricingService:
    def __init__(self, knowledge_dir: Path | None = None, today=None, *, repository=None):
        # LEGADO temporal: sólo una ruta explícita habilita el lector de sidecars.
        # La instancia de producción nunca vuelve a JSON si la base está vacía o falla.
        self.root = Path(knowledge_dir).resolve() if knowledge_dir is not None else None
        self.repository = repository
        self.today = today or (lambda: datetime.now(timezone(timedelta(hours=-5), "America/Lima")).date())
        self._cache = {}
        self._lock = RLock()

    def catalogs(self) -> dict[str, ProgramCatalog]:
        if self.root is None:
            return self._database_catalogs(self._database_snapshot())
        """Verifica archivos por contenido. Caché de parseo; recarga sin reinicio."""
        with self._lock:
            result = {}
            aliases = {}
            paths = sorted(self.root.glob("*/*.pricing.json"))
            if not paths:
                raise CatalogError("No hay catálogos comerciales")
            for path in paths:
                # No leer enlaces que escapen del directorio comercial autorizado.
                if not path.resolve().is_relative_to(self.root):
                    raise CatalogError("Ruta comercial no autorizada")
                try:
                    content = path.read_bytes()
                    digest = hashlib.sha256(content).hexdigest()
                    cached = self._cache.get(path)
                    if cached and cached[0] == digest:
                        catalog = cached[1]
                    else:
                        data = json.loads(content.decode("utf-8-sig"), parse_float=Decimal, object_pairs_hook=_unique_object)
                        catalog = ProgramCatalog.model_validate(data)
                        if path.name != catalog.program + ".pricing.json":
                            raise ValueError("ID distinto del archivo")
                        self._cache[path] = (digest, catalog)
                except (OSError, ValueError, InvalidOperation) as exc:
                    self._cache.pop(path, None)
                    raise CatalogError(f"Catálogo inválido: {path.name}") from exc
                if catalog.program in result:
                    raise CatalogError("ID de programa duplicado")
                result[catalog.program] = catalog
                for name in [catalog.program, catalog.program.replace("_", " "), catalog.program_label, *catalog.aliases]:
                    alias = normalizar(name)
                    if not alias or (alias in aliases and aliases[alias] != catalog.program):
                        raise CatalogError("Alias de programa ambiguo")
                    aliases[alias] = catalog.program
            self._cache = {p: item for p, item in self._cache.items() if p in paths}
            return result

    def _database_snapshot(self):
        from commercial_runtime import get_repository
        from services.commercial_service import validate_configuration
        repository = self.repository or get_repository()
        try:
            with repository.transaction() as unit:
                validate_configuration(unit)
                return {resource: unit.list(resource) for resource in ('programs', 'prices', 'campaigns')}
        except ValueError as exc:
            raise CatalogError('La configuración comercial de la base es inválida') from exc

    def _database_catalogs(self, snapshot):
        result = {}
        for program in snapshot['programs']:
            if not program['enabled']:
                continue
            prices = [self._entry(p).model_dump(mode='json') for p in snapshot['prices']
                      if p['program'] == program['id'] and not p['campaign_id']]
            # Catálogo de identificadores para herramientas, nunca una tarifa persistida.
            if not prices:
                prices = [dict(concept='inscripcion', modality=None, shift=None, amount=None,
                               currency='PEN', status='pending', campaign='base', starts_on=None, ends_on=None)]
            catalog = ProgramCatalog.model_validate(dict(schema_version=1, program=program['id'],
                program_label=program['name'], aliases=program['aliases'], modalities=program['modalities'],
                shifts=program['shifts'], prices=prices))
            result[catalog.program] = catalog
        if not result:
            raise CatalogError('No hay programas comerciales activos; ejecutar la migración')
        return result

    @staticmethod
    def _entry(record):
        return PriceEntry.model_validate({key: record[key] for key in PriceEntry.model_fields})

    def _resolve_database(self, program, concept, modality, shift, *, base_only=False):
        snapshot = self._database_snapshot()
        if base_only:
            snapshot['prices'] = [p for p in snapshot['prices'] if not p['campaign_id']]
        catalogs = self._database_catalogs(snapshot)
        name = normalizar(program)
        program = next((c.program for c in catalogs.values() if name in
            [normalizar(n) for n in [c.program, c.program.replace('_', ' '), c.program_label, *c.aliases]]), None)
        if program is None:
            raise ValueError('Programa desconocido o deshabilitado')
        catalog = catalogs[program]
        concept = normalizar(concept).replace(' ', '_')
        modality = normalizar(modality).replace(' ', '_') if modality is not None else None
        shift = normalizar(shift).replace(' ', '_') if shift is not None else None
        if concept not in CONCEPTOS:
            raise ValueError('Concepto desconocido')
        if modality is not None and modality not in catalog.modalities or shift is not None and shift not in catalog.shifts:
            raise ValueError('Variante desconocida')
        base = dict(program=program, program_label=catalog.program_label, concept=concept,
                    concept_label=_LABELS[concept], modality=modality, shift=shift, amount=None, currency=None,
                    status='pending', campaign=None, starts_on=None, ends_on=None, promotions=[],
                    observations='', reason='no_current_price')
        today = self.today().isoformat()
        campaigns = {c['id']: c for c in snapshot['campaigns']}
        current = []
        for price in snapshot['prices']:
            if price['program'] != program or price['concept'] != concept or price['status'] == 'inactive':
                continue
            campaign = campaigns.get(price['campaign_id']) if price['campaign_id'] else None
            if campaign and not campaign['enabled']:
                continue
            start = campaign['starts_on'] if campaign else price['starts_on']
            end = campaign['ends_on'] if campaign else price['ends_on']
            if (start is None or start <= today) and (end is None or today <= end):
                current.append({**price, 'campaign': campaign['name'] if campaign else price['campaign'],
                                'starts_on': start, 'ends_on': end})
        # Una consulta sin variante debe ser inequívoca para todas sus combinaciones.
        selected = {}
        for mode in [modality] if modality else catalog.modalities:
            for turn in [shift] if shift else catalog.shifts or [None]:
                matches = [p for p in current if (p['modality'] is None or p['modality'] == mode)
                           and (p['shift'] is None or p['shift'] == turn)]
                offers = [p for p in matches if p['campaign_id']]
                normals = [p for p in matches if not p['campaign_id']]
                if len(offers) > 1 or len(normals) > 1:
                    raise CatalogError('Conflicto de tarifas: no se selecciona una ganadora')
                choice = (offers or normals or [None])[0]
                selected[choice['id'] if choice else None] = choice
        if set(selected) == {None}:
            return base
        if len(selected) != 1:
            return {**base, 'reason': 'variant_required'}
        price = next(iter(selected.values()))
        entry = self._entry(price)
        return {**base, **entry.model_dump(mode='json'), 'amount': _number(entry.amount),
                'modality': modality or entry.modality, 'shift': shift or entry.shift, 'reason': None,
                'campaign_id': price['campaign_id'], 'price_id': price['id']}

    def resolve_base(self, program, concept, modality=None, shift=None):
        return self._resolve_database(program, concept, modality, shift, base_only=True)

    def normalize_program(self, value: str) -> str:
        name = normalizar(value)
        for catalog in self.catalogs().values():
            if name in [normalizar(n) for n in [catalog.program, catalog.program.replace("_", " "), catalog.program_label, *catalog.aliases]]:
                return catalog.program
        raise ValueError("Programa desconocido")

    def detect_program(self, text: str) -> str | None:
        normalized = normalizar(text)
        found = set()
        for catalog in self.catalogs().values():
            names = [catalog.program, catalog.program.replace("_", " "), catalog.program_label, *catalog.aliases]
            if any(re.search(r"\b" + re.escape(normalizar(n)) + r"\b", normalized) for n in names):
                found.add(catalog.program)
        return next(iter(found)) if len(found) == 1 else None

    def resolve(self, program, concept, modality=None, shift=None) -> dict:
        if self.root is None:
            return self._resolve_database(program, concept, modality, shift)
        program = self.normalize_program(program)
        catalog = self.catalogs()[program]
        concept = normalizar(concept).replace(" ", "_")
        if concept not in CONCEPTOS:
            raise ValueError("Concepto desconocido")
        modality = normalizar(modality).replace(" ", "_") if modality is not None else None
        shift = normalizar(shift).replace(" ", "_") if shift is not None else None
        if modality is not None and modality not in catalog.modalities or shift is not None and shift not in catalog.shifts:
            raise ValueError("Variante desconocida")
        today = self.today()
        candidates = [p for p in catalog.prices if p.concept == concept and p.status != "inactive" and (p.starts_on is None or p.starts_on <= today) and (p.ends_on is None or today <= p.ends_on) and (modality is None or p.modality is None or p.modality == modality) and (shift is None or p.shift is None or p.shift == shift)]
        base = {"program":program, "program_label":catalog.program_label, "concept":concept, "concept_label":_LABELS[concept], "modality":modality, "shift":shift, "amount":None, "currency":None, "status":"pending", "campaign":None, "starts_on":None, "ends_on":None, "promotions":[], "observations":"", "reason":"no_current_price"}
        if not candidates:
            return base
        if len(candidates) != 1:
            return {**base, "reason":"variant_required"}
        entry = candidates[0]
        return {**base, **entry.model_dump(mode="json"), "amount":_number(entry.amount), "modality":modality or entry.modality, "shift":shift or entry.shift, "reason":None}

    def program_from_context(self, question, history):
        program = self.detect_program(question)
        if program:
            return program
        for turn in reversed(history or []):
            program = self.detect_program(turn.get("content", ""))
            if program:
                return program
        return None

    def text_for_price(self, price) -> str:
        label = _LABELS[price["concept"]]
        if price.get("reason") == "variant_required":
            return f"Para confirmar el precio de {label}, indica la modalidad y el turno del programa."
        if price["status"] == "free":
            return f"La {label} es gratuita en la campaña {price['campaign']}."
        if price["status"] != "active":
            return f"El importe de {label} está pendiente de confirmación oficial. No realices un pago hasta confirmarlo."
        currency = "soles" if price["currency"] == "PEN" else price["currency"]
        message = f"La {label} cuesta {price['amount']} {currency}."
        for promotion in price.get("promotions", []):
            message += f" Promoción: {promotion['description']}. Condiciones: {promotion['conditions']}."
        return message

    def authoritative_answer(self, question, history=None) -> str:
        """Consulta directa: no tomar importes, descuentos o gratuidad del RAG/LLM."""
        try:
            program = self.program_from_context(question, history)
            concepts = conceptos_en_texto(question)
            if not concepts:
                concepts = ["inscripcion", "matricula", "mensualidad"]
            if not program:
                # Sin programa sólo informar si TODOS los catálogos concuerdan.
                quotes = [self.resolve(c.program, concepts[0]) for c in self.catalogs().values()] if len(concepts) == 1 else []
                if quotes and len({(q["status"], q["amount"], q["currency"], q["campaign"], q["reason"]) for q in quotes}) == 1:
                    return self.text_for_price(quotes[0])
                return "Indica el programa y la modalidad para consultar su tarifa vigente."
            modality, shift = variantes_en_contexto(self.catalogs()[program], question, history)
            return " ".join(self.text_for_price(self.resolve(program, c, modality, shift)) for c in concepts)
        except CatalogError:
            return "La configuración comercial necesita revisión. No realices un pago hasta confirmar la tarifa oficial."
        except ValueError:
            return "Indica una modalidad y un turno válidos para consultar la tarifa vigente."


pricing_service = PricingService()

def normalizar_programa(value):
    return pricing_service.normalize_program(value)

def programa_canonico(texto):
    return pricing_service.detect_program(texto)

def consultar_tarifa(program, concept, modality=None, shift=None):
    return pricing_service.resolve(program, concept, modality, shift)

def conceptos_en_texto(texto):
    n = normalizar(texto)
    result = []
    if re.search(r"\binscripcion\b", n): result.append("inscripcion")
    if re.search(r"\bmatricula\b", n): result.append("matricula")
    if re.search(r"\b(mensualidad|mensualidades|cuotas?|pensiones|pension)\b", n):
        result.append("mensualidad_contado" if "contado" in n else "mensualidad")
    elif "contado" in n: result.append("pago_contado")
    if re.search(r"ciclo completo|total (?:del )?ciclo|costo total", n): result.append("ciclo_completo")
    if re.search(r"\b(descuento|descuentos|ahorro)\b", n): result.append("descuento")
    return result

def variantes_en_contexto(catalog, question, history=None):
    values = []
    # Sólo retroceder a contexto si el usuario no especificó la variante actual.
    for allowed in (catalog.modalities, catalog.shifts):
        found = [v for v in allowed if re.search(r"\b"+re.escape(v.replace("_", " "))+r"\b", normalizar(question))]
        if not found:
            for turn in reversed(history or []):
                found = [v for v in allowed if re.search(r"\b"+re.escape(v.replace("_", " "))+r"\b", normalizar(turn.get("content", "")))]
                if found: break
        values.append(found[0] if len(found) == 1 else None)
    return tuple(values)

def inferir_solicitud_pago(pregunta, historial=None, params=None, *, service=None):
    service = service or pricing_service
    program = service.program_from_context(pregunta, historial)
    if not program and params:
        try: program = service.normalize_program(params[0])
        except ValueError: pass
    concepts = conceptos_en_texto(pregunta)
    if not concepts:
        previous = next((t.get("content", "") for t in reversed(historial or []) if t.get("role") == "assistant"), "")
        concepts = conceptos_en_texto(previous)
    request = {"program": program, "concept": concepts[0] if len(concepts) == 1 else "matricula"}
    if program:
        request["modality"], request["shift"] = variantes_en_contexto(service.catalogs()[program], pregunta, historial)
    return request

def resolver_pago(pregunta, historial=None, params=None):
    """LEGADO: firma anterior sin ninguna tarifa propia."""
    request = inferir_solicitud_pago(pregunta, historial, params)
    price = consultar_tarifa(request["program"], request["concept"], request.get("modality"), request.get("shift")) if request["program"] else None
    return {"carrera":price["program_label"] if price else "", "programa_id":request["program"], "concepto":request["concept"], "monto":price["amount"] if price else None, "tarifa_confirmada":bool(price and price["status"] in ("active", "free"))}

def instrucciones_tarifas():
    return ("REGLAS COMERCIALES: todos los importes, campañas y gratuidad provienen exclusivamente de PricingService, nunca del contexto vectorial ni del historial. "
            "No declares cifras, gratuidad ni descuentos por tu cuenta: el backend proporciona la respuesta comercial vigente. "
            "Solicita acciones mediante herramientas sin importes. "
            "Gastronomía, Panadería y Bartender pueden tener actividades o clases los sábados. No ofrezcas sábados para otras carreras ni afirmes exclusividad o fechas no confirmadas.")

def sanear_tarifas_texto(texto, pregunta="", historial=None, *, service=None):
    """Reemplaza afirmaciones monetarias del modelo por la consulta actual autorizada."""
    parts = re.split(r"(?<=[!?])\s+|(?<=\.)\s+(?!\d)", texto)
    money = re.compile(r"(?:S/\.?\s*\d+(?:[.,]\d+)*|\$\s*\d+(?:[.,]\d+)*|\b(?:soles|PEN|USD|EUR|euros|gratis|gratuita|gratuito|sin costo|sin pago|por ciento)\b|\d+(?:[.,]\d+)*\s*%)", re.I)
    output = []
    for part in parts:
        n = normalizar(part)
        financial_claim = bool(re.search(r"\b(descuento|descuentos|promocion|promociones|cuesta|cuestan|precio|precios|importe)\b", n)) or (bool(conceptos_en_texto(part)) and bool(re.search(r":\s*\d", part)))
        if money.search(part) or financial_claim:
            # El programa se obtiene del usuario/historial, jamás de una cifra del modelo.
            concepts = conceptos_en_texto(part)
            context = pregunta + " " + " ".join(_LABELS[c] for c in concepts)
            part = (service or pricing_service).authoritative_answer(context, historial)
        output.append(part)
    return " ".join(output)


def respuesta_comercial(pregunta, historial=None, *, service=None):
    """Respuesta vigente obligatoria para preguntas comerciales, aunque el LLM omita precios."""
    n = normalizar(pregunta)
    if re.search(r"\b(precio|precios|costo|costos|cuesta|cuestan|tarifa|tarifas|descuento|descuentos|promocion|promociones|gratis|gratuita|gratuito|pagar)\b", n):
        return (service or pricing_service).authoritative_answer(pregunta, historial)
    return ""


def aviso_pago_bloqueado(price, *, service=None):
    service = service or pricing_service
    """Política comercial compartida por acciones y upload; None autoriza el cobro."""
    if price["status"] == "free":
        return {"code":"price_free", "message":service.text_for_price(price) + " No corresponde enviar un comprobante de pago."}
    if price["status"] != "active":
        return {"code":"tariff_pending", "message":service.text_for_price(price)}
    if price["concept"] == "descuento" or price["currency"] != "PEN":
        return {"code":"payment_unavailable", "message":"Esta tarifa no admite un cobro por Yape en este flujo."}
    return None

class PricingPolicy:
    def __init__(self, service): self.service = service
    def clean(self, text, question='', history=None):
        return sanear_tarifas_texto(text, question, history, service=self.service)
    def answer(self, question, history=None):
        return respuesta_comercial(question, history, service=self.service)

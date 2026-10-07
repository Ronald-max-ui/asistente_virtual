"""Única autorización: esquema, contexto, consentimiento y catálogo."""
from dataclasses import dataclass, field
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictStr, TypeAdapter, ValidationError
from services.consent_service import autorizar_accion, normalizar, accion_disponible
from services.media_registry import obtener_recurso
from services.pricing_service import consultar_tarifa, normalizar_programa, programa_canonico, CONCEPTOS, pricing_service, conceptos_en_texto, variantes_en_contexto, CatalogError, aviso_pago_bloqueado

class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

class ShowPayment(ActionRequest):
    type: Literal["show_payment"]
    program: StrictStr = Field(description="ID de programa del catálogo autorizado")
    concept: StrictStr = Field(description="Concepto del catálogo autorizado; nunca un importe")
    modality: StrictStr | None = None
    shift: StrictStr | None = None

class ShowContact(ActionRequest):
    type: Literal["show_contact"]
    program: StrictStr | None = None

class ShowGallery(ActionRequest):
    type: Literal["show_gallery"]
    resource_id: Literal["gastronomia_uniforme", "gastronomia_talleres", "turismo_salidas", "bartender_barra", "pasteleria_horno", "instituto_fachada"]

REQUEST_SCHEMA = TypeAdapter(Annotated[ShowPayment | ShowContact | ShowGallery, Field(discriminator="type")])
ACTION_REQUEST_MODELS = {"show_payment": ShowPayment, "show_contact": ShowContact, "show_gallery": ShowGallery}
_CONSENT_TYPES = {"show_payment": "SHOW_PAYMENT", "show_contact": "OPEN_LEAD_FORM", "show_gallery": "SHOW_GALLERY"}


class GalleryResource(ActionRequest):
    titulo: StrictStr
    descripcion: StrictStr
    url: StrictStr = Field(pattern=r"^/static/media/[a-zA-Z0-9_-]+\.(?:webp|png|jpe?g)$")


class AuthorizedGallery(ActionRequest):
    type: Literal["show_gallery"]
    resource_id: StrictStr
    resource: GalleryResource


class AuthorizedContact(ActionRequest):
    type: Literal["show_contact"]
    program: StrictStr | None
    program_label: StrictStr


class AuthorizedPayment(ActionRequest):
    """DTO de salida: sus campos sensibles sólo se construyen después de autorizar."""
    type: Literal["show_payment"]
    program: StrictStr
    program_label: StrictStr
    concept: StrictStr
    concept_label: StrictStr
    modality: StrictStr | None
    shift: StrictStr | None
    amount: StrictStr = Field(pattern=r"^(?:[1-9]\d*(?:\.\d{1,2})?|0\.(?:0[1-9]|[1-9]\d?))$")
    currency: Literal["PEN"]
    status: Literal["active"]
    campaign: StrictStr
    starts_on: StrictStr | None
    ends_on: StrictStr | None
    confirmed: Literal[True]
    qr_url: StrictStr = Field(pattern=r"^/static/media/[a-zA-Z0-9_-]+\.(?:webp|png|jpe?g)$")
    payment_number: StrictStr


AuthorizedAction = Annotated[AuthorizedPayment | AuthorizedContact | AuthorizedGallery, Field(discriminator="type")]
AUTHORIZED_ACTION_SCHEMA = TypeAdapter(AuthorizedAction)


class ActionNotice(ActionRequest):
    code: Literal["price_free", "tariff_pending", "payment_unavailable"]
    message: StrictStr

@dataclass
class ActionContext:
    pregunta: str
    historial: list
    mode: str = "web"
    persona: str = "sales"
    lead_submitted: bool = False
    shown_media: list = field(default_factory=list)

@dataclass
class ActionResult:
    actions: list = field(default_factory=list)
    notices: list = field(default_factory=list)

def herramientas_llm(*, mode=None, persona=None, lead_submitted=False) -> list:
    tools = []
    try:
        programs = list(pricing_service.catalogs())
    except CatalogError:
        programs = []
    for model, description in [(ShowPayment, "Solicitar pago; el backend decide la tarifa."), (ShowContact, "Solicitar formulario de contacto."), (ShowGallery, "Solicitar una imagen del catálogo.")]:
        if not programs and model in (ShowPayment, ShowContact):
            continue
        schema = model.model_json_schema()
        name = schema["properties"].pop("type")["const"]
        if mode is not None and not accion_disponible(_CONSENT_TYPES[name], mode=mode, persona=persona, lead_submitted=lead_submitted):
            continue
        schema["required"].remove("type")
        if model is ShowPayment:
            schema["properties"]["program"]["enum"] = programs
            schema["properties"]["concept"]["enum"] = list(CONCEPTOS)
        tools.append({"type": "function", "function": {"name": name, "description": description, "parameters": schema}})
    return tools

def procesar_acciones(requests: list, context: ActionContext) -> ActionResult:
    result = ActionResult()
    seen = set()
    for raw in requests:
        try:
            request = REQUEST_SCHEMA.validate_python(raw)
            if request.type in ("show_contact", "show_payment") and request.program is not None:
                request.program = normalizar_programa(request.program)
            if request.type == "show_payment":
                request.concept = normalizar(request.concept).replace(" ", "_")
                if request.concept not in CONCEPTOS:
                    continue
                explicit_program = programa_canonico(context.pregunta)
                if not explicit_program:
                    previous = next((t.get("content", "") for t in reversed(context.historial) if t.get("role") == "assistant"), "")
                    explicit_program = programa_canonico(previous)
                if explicit_program and explicit_program != request.program:
                    continue
                concepts = conceptos_en_texto(context.pregunta)
                if not concepts:
                    previous = next((t.get("content", "") for t in reversed(context.historial) if t.get("role") == "assistant"), "")
                    concepts = conceptos_en_texto(previous)
                if concepts != [request.concept]:
                    continue
            if not autorizar_accion(_CONSENT_TYPES[request.type], context.pregunta, context.historial, mode=context.mode, persona=context.persona, lead_submitted=context.lead_submitted):
                continue
            if request.type == "show_payment":
                catalog = pricing_service.catalogs()[request.program]
                modality, shift = variantes_en_contexto(catalog, context.pregunta, context.historial)
                if modality and request.modality and normalizar(request.modality).replace(" ", "_") != modality:
                    continue
                if shift and request.shift and normalizar(request.shift).replace(" ", "_") != shift:
                    continue
                tariff = consultar_tarifa(request.program, request.concept, request.modality or modality, request.shift or shift)
                notice = aviso_pago_bloqueado(tariff)
                if notice:
                    if notice not in result.notices:
                        result.notices.append(notice)
                    continue
                qr = obtener_recurso("yape_qr")
                if not qr:
                    continue
                # Proyectar campos explícitos: no propagar metadatos administrativos.
                action = AuthorizedPayment(type=request.type,
                    **{key: tariff[key] for key in ("program", "program_label", "concept", "concept_label",
                        "modality", "shift", "amount", "currency", "status", "campaign", "starts_on", "ends_on")},
                    qr_url=qr["url"], payment_number="994 773 335", confirmed=True).model_dump(mode="json")
            elif request.type == "show_gallery":
                if request.resource_id in context.shown_media and not any(t in normalizar(context.pregunta) for t in ("de nuevo", "otra vez", "volver a ver")):
                    continue
                action = {"type": request.type, "resource_id": request.resource_id, "resource": obtener_recurso(request.resource_id)}
            else:
                label = consultar_tarifa(request.program, "inscripcion")["program_label"] if request.program else ""
                action = {"type": request.type, "program": request.program, "program_label": label}
            action = AUTHORIZED_ACTION_SCHEMA.validate_python(action).model_dump(mode="json")
            key = str(action)
            if key not in seen:
                result.actions.append(action)
                seen.add(key)
        except (ValidationError, ValueError, TypeError):
            continue  # No registrar argumentos crudos del LLM.
    return result

def texto_respaldo(result: ActionResult) -> str:
    if result.notices:
        return result.notices[0]["message"]
    if not result.actions:
        return ""
    action = result.actions[0]
    if action["type"] == "show_payment":
        return pricing_service.text_for_price(action) + " Puedes enviar el comprobante para solicitar su verificación; el envío no confirma una matrícula."
    if action["type"] == "show_contact":
        return "Aquí tienes el formulario para registrar tus datos de contacto."
    return "Aquí tienes la imagen solicitada en tu pantalla."

def validar_accion(tipo: str, params: list, pregunta: str, historial: list, *, mode: str, persona: str, lead_submitted: bool = False):
    """LEGADO: firma de Fase 1 que delega a la única política estructurada."""
    from services.llm_protocol import legacy_request
    request = legacy_request(tipo, params, pregunta, historial)
    result = procesar_acciones([request] if request else [], ActionContext(pregunta, historial, mode, persona, lead_submitted))
    if not result.actions:
        return None
    action = result.actions[0]
    if action["type"] == "show_gallery":
        return [action["resource_id"]]
    if action["type"] == "show_contact":
        return [action["program_label"]]
    return [action["program_label"], action["amount"], action["concept"]]

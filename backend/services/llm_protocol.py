"""Separación de texto/solicitudes y adaptador LEGADO temporal."""
import json
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictStr, StrictBool, TypeAdapter
from services.action_service import ACTION_REQUEST_MODELS, AuthorizedAction, ActionNotice
from services.pricing_service import inferir_solicitud_pago, normalizar_programa

class AssistantReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assistant_text: StrictStr = ""
    structured_actions: list[dict] = Field(default_factory=list)
    native_actions_present: StrictBool = False


def seleccionar_solicitudes(native: list, legacy: list, *, native_present=False) -> list:
    """LEGADO sólo como respaldo. Una solicitud nativa inválida no se reemplaza."""
    return native if native or native_present else legacy


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    texto: StrictStr
    audio_b64: StrictStr
    actions: list[AuthorizedAction]
    notices: list[ActionNotice]


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextEvent(Event):
    type: Literal["text"]
    text: StrictStr


class AudioEvent(Event):
    type: Literal["audio"]
    audio_b64: StrictStr


class UiActionEvent(Event):
    type: Literal["ui_action"]
    action: AuthorizedAction


class DoneEvent(Event):
    type: Literal["done"]
    full_text: StrictStr


class ErrorEvent(Event):
    type: Literal["error"]
    message: StrictStr


class NoticeEvent(Event, ActionNotice):
    type: Literal["notice"]


class ModeSwitchEvent(Event):
    # Evento de sistema; el LLM no dispone de una herramienta para solicitarlo.
    type: Literal["mode_switch"]
    mode: Literal["info", "sales"]


SSE_SCHEMA = TypeAdapter(Annotated[TextEvent | AudioEvent | UiActionEvent | DoneEvent | ErrorEvent | NoticeEvent | ModeSwitchEvent, Field(discriminator="type")])

def legacy_request(tipo, params, pregunta, historial):
    """LEGADO: el importe de cualquier etiqueta se descarta siempre."""
    if tipo == "SHOW_GALLERY" and len(params) == 1:
        return {"type": "show_gallery", "resource_id": params[0]}
    if tipo in ("SHOW_PAYMENT", "OPEN_LEAD_FORM"):
        if params and params[0]:
            try:
                normalizar_programa(params[0])
            except ValueError:
                return None
        pago = inferir_solicitud_pago(pregunta, historial, params[:1])
        if tipo == "OPEN_LEAD_FORM":
            return {"type": "show_contact", "program": pago["program"]}
        if pago["program"]:
            return {"type": "show_payment", "program": pago["program"], "concept": pago["concept"], "modality": pago.get("modality"), "shift": pago.get("shift")}
    return None

class LegacyActionAdapter:
    prefix = "[[ACTION"
    def __init__(self, pregunta, historial):
        self.pregunta, self.historial = pregunta, historial
        self.buffer = ""
        self.structured_actions = []
    def feed(self, text):
        self.buffer += text
        output = ""
        while self.buffer:
            start = self.buffer.upper().find(self.prefix)
            if start >= 0:
                output += self.buffer[:start]
                self.buffer = self.buffer[start:]
                end = self.buffer.find("]]", len(self.prefix))
                if end < 0:
                    return output
                body = self.buffer[len(self.prefix):end]
                fields = body[1:].split(":") if body.startswith(":") else []
                request = legacy_request(fields[0].strip().upper(), [p.strip() for p in fields[1:]], self.pregunta, self.historial) if fields else None
                if request:
                    self.structured_actions.append(request)
                self.buffer = self.buffer[end+2:]
            else:
                hold = next((n for n in range(len(self.prefix)-1, 0, -1) if self.buffer.upper().endswith(self.prefix[:n])), 0)
                output += self.buffer[:-hold] if hold else self.buffer
                self.buffer = self.buffer[-hold:] if hold else ""
                break
        return output
    def finish(self):
        text = "" if self.prefix.startswith(self.buffer.upper()) or self.buffer.upper().startswith(self.prefix) else self.buffer
        self.buffer = ""
        return text

def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Campo duplicado")
        result[key] = value
    return result

class ToolCallCollector:
    """Acumula argumentos por índice. Nunca ejecuta código ni herramientas."""
    def __init__(self):
        self.calls = {}
    def feed(self, calls):
        for call in calls or []:
            index = getattr(call, "index", None)
            if index is None:
                index = len(self.calls)
            item = self.calls.setdefault(index, {"name": "", "arguments": ""})
            function = getattr(call, "function", None)
            if function:
                item["name"] += getattr(function, "name", None) or ""
                item["arguments"] += getattr(function, "arguments", None) or ""
    def finish(self):
        requests = []
        for index in sorted(self.calls):
            call = self.calls[index]
            if call["name"] not in ACTION_REQUEST_MODELS:
                continue
            try:
                args = json.loads(call["arguments"], object_pairs_hook=_unique_object)
                if not isinstance(args, dict) or "type" in args:
                    continue
                requests.append({"type": call["name"], **args})
            except (ValueError, TypeError):
                continue
        return requests

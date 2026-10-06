"""
server.py — Orquestador principal del Asistente Virtual IA (v4.0: Dual-Mode Kiosk/Web).

Endpoints de streaming:
  POST /chat/stream  → SSE streaming: RAG → Groq tokens → TTS por oración → audio base64.
                       El servidor detecta [[ACTION:TIPO:PARAM]] en el texto del LLM,
                       los elimina antes de TTS, y los emite como eventos SSE 'ui_action'.

Endpoints de apoyo (Modo Web):
  GET  /api/media              → Catálogo de recursos multimedia.
  POST /api/leads              → Registro de prospectos (nombre, whatsapp, carrera, notas).
  POST /api/vouchers           → Subida de comprobante de pago (imagen + metadatos).

Endpoints de compatibilidad:
  POST /chat       → Modo estándar (respuesta completa en JSON, sin streaming).
  POST /reset-session, GET /health.
"""
import asyncio
import base64
import json
import os
import re
import time
import unicodedata
import uuid as uuid_lib
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from config import settings
from session_manager import SessionManager
from services.rag_service import buscar_contexto, detectar_entidad
from services.llm_service import (
    generar_respuesta_llm,
    stream_respuesta_llm,
    filtrar_texto,
    construir_prompt_sistema,
)
from services.tts_service import generar_audio_bytes
from services.media_registry import obtener_recurso, listar_recursos
from services.intent_service import (
    PERSONA_INFO,
    PERSONA_SALES,
    detectar_intencion_comercial,
    normalizar_persona,
)


# ── Rutas de almacenamiento ───────────────────────────────────────────────────
_BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
_LEADS_DIR    = os.path.join(_BASE_DIR, "storage", "leads")
_VOUCHERS_DIR = os.path.join(_BASE_DIR, "storage", "vouchers")
os.makedirs(_LEADS_DIR,    exist_ok=True)
os.makedirs(_VOUCHERS_DIR, exist_ok=True)

# ── Gestión de sesiones ───────────────────────────────────────────────────────
session_manager = SessionManager(
    ttl=settings.session_ttl_seconds,
    cleanup_interval=settings.session_cleanup_interval_seconds,
)

# ── Patrón de oración y de acciones inline ───────────────────────────────────
_SENTENCE_BOUNDARY = re.compile(r'(?<=[.!?])\s+')
# Detecta [[ACTION:TIPO:PARAM]] o [[ACTION:TIPO:PARAM1:PARAM2]]
_ACTION_RE = re.compile(r'\[\[ACTION:([A-Z_]+):([^\]]+)\]\]')


# ── Ciclo de vida ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_task = asyncio.create_task(session_manager.iniciar_limpieza_periodica())
    print("[Startup] Asistente Virtual v4.0 iniciado. Dual-Mode (kiosk/web) activo.")
    yield
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    print("[Shutdown] Asistente Virtual detenido limpiamente.")


# ── Aplicación FastAPI ────────────────────────────────────────────────────────
app = FastAPI(
    title="Asistente Virtual IA - Instituto Tuinen Star",
    version="4.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Montar archivos estáticos (fotos de uniformes, QR, etc.)
app.mount("/static", StaticFiles(directory=os.path.join(_BASE_DIR, "static")), name="static")


# ── Modelos de entrada ────────────────────────────────────────────────────────
class ChatInput(BaseModel):
    mensaje: str
    session_id: str = "kiosco_principal"
    mode: Optional[str] = "web"   # "kiosk" | "web"  (default: web)
    persona: Optional[str] = None  # "info" | "sales" (None → default según mode)


# ── Helpers internos ──────────────────────────────────────────────────────────
def _sse_event(payload: dict) -> str:
    """Formatea un dict como evento SSE válido (event: data)."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_action_event(tipo: str, params: list[str]) -> str:
    """Emite un evento SSE de tipo 'ui_action' parseado de [[ACTION:TIPO:PARAMS]]."""
    payload = {"type": "ui_action", "action": tipo}
    # Mapear params según tipo de acción
    if tipo == "SHOW_GALLERY" and params:
        payload["resource_id"] = params[0]
        recurso = obtener_recurso(params[0])
        if recurso:
            payload["resource"] = recurso
    elif tipo == "SHOW_PAYMENT":
        carrera_param = params[0] if len(params) >= 1 and params[0].strip() else "Gastronomia"
        monto_param   = params[1] if len(params) >= 2 and params[1].strip() else "250"
        if carrera_param.lower() in ["general", "carrera"]:
            carrera_param = "Gastronomia"
        payload["carrera"] = carrera_param
        payload["monto"]   = monto_param
        yape_recurso = obtener_recurso("yape_qr")
        if yape_recurso:
            payload["qr_url"] = yape_recurso["url"]
        payload["yape_numero"] = "994 773 335"
    elif tipo == "OPEN_LEAD_FORM" and params:
        payload["carrera"] = params[0]
    return f"event: ui_action\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _extraer_acciones(texto: str) -> tuple[str, list[tuple[str, list[str]]]]:
    """
    Extrae y elimina los tags [[ACTION:TIPO:PARAM]] del texto del LLM.
    Retorna (texto_limpio, [(tipo, [param1, param2, ...]), ...]).
    """
    acciones = []
    def _reemplazar(m: re.Match) -> str:
        tipo   = m.group(1)
        params = [p.strip() for p in m.group(2).split(':')]
        acciones.append((tipo, params))
        return ''
    texto_limpio = _ACTION_RE.sub(_reemplazar, texto).strip()
    return texto_limpio, acciones


def _sse_mode_switch_event(persona: str) -> str:
    """Evento SSE nombrado para que el frontend transmute aura/switch en tiempo real."""
    return f"event: mode_switch\ndata: {json.dumps({'mode': persona})}\n\n"


def _usuario_valido_ver_imagenes(pregunta: str, historial: list) -> bool:
    """
    True si y solo si:
      a) El usuario lo pide explícitamente en su mensaje ("muéstrame", "quiero ver", "enséñame").
      b) El usuario responde afirmativamente ("sí", "claro", "a ver", "por favor", "dale", "bueno")
         a una pregunta previa de Lía donde ella le consultó si deseaba verlos.
    """
    p = unicodedata.normalize('NFD', (pregunta or "").lower())
    p = ''.join(c for c in p if unicodedata.category(c) != 'Mn').strip()

    # a) Orden / petición explícita
    patrones_directos = [
        "quiero ver", "puedo ver", "muestrame", "mostrar", "ensenam", "ver las fotos",
        "ver fotos", "tienes fotos", "tienes foto", "ver imagen", "pon la foto",
        "como es el uniforme", "como son los talleres", "como es la barra"
    ]
    if any(k in p for k in patrones_directos):
        return True

    # b) Respuesta afirmativa a ofrecimiento previo de Lía
    patrones_afirmativos = ["si", "claro", "a ver", "por favor", "dale", "bueno", "por supuesto", "me gustaria", "deseo ver"]
    es_afirmativo = any(p == a or p.startswith(f"{a} ") or p.endswith(f" {a}") or f" {a} " in p for a in patrones_afirmativos)

    if es_afirmativo and historial:
        # Buscar el último mensaje del asistente
        for turno in reversed(historial):
            if turno.get("role") == "assistant":
                content = unicodedata.normalize('NFD', turno.get("content", "").lower())
                content = ''.join(c for c in content if unicodedata.category(c) != 'Mn')
                # ¿Lía ofreció ver imágenes o fotos?
                ofrecio_ver = any(k in content for k in [
                    "quieres ver", "te gustaria ver", "deseas ver", "ver las fotos",
                    "ver los talleres", "ver el uniforme", "te muestro", "te enseno"
                ])
                if ofrecio_ver:
                    return True
                break

    return False


def _pide_ver_de_nuevo(pregunta: str) -> bool:
    """True si el usuario solicita textualmente volver a ver una imagen ('de nuevo', 'otra vez')."""
    p = unicodedata.normalize('NFD', (pregunta or "").lower())
    p = ''.join(c for c in p if unicodedata.category(c) != 'Mn')
    patrones_repeticion = ["de nuevo", "otra vez", "volver a ver", "ponla de nuevo", "muestramela de nuevo"]
    return any(k in p for k in patrones_repeticion)


def _usuario_valido_formulario_lead(pregunta: str, historial: list, texto_llm_actual: str = "") -> bool:
    """
    Guardrail determinista de apertura de formulario de lead (OPEN_LEAD_FORM).
    Se permite si:
      a) Respaldo de coherencia: Si el texto generado por el LLM incluye explícitamente
         frases que anuncian la apertura del formulario ("he abierto el formulario", "aquí tienes el formulario", etc.).
      b) El usuario manifiesta intención explícita directa de contacto/inscripción:
         ["inscribir", "matricular", "postular", "llamen", "llamame", "contacto",
          "formulario", "asesor", "visita guiada", "datos", "dejar mis datos", "quiero que me contacten"].
      c) Confirmación afirmativa breve ("sí", "claro", "por favor", "de acuerdo", "dale", "ok", "a ver", "acepto", "perfecto")
         ante una invitación o cierre del turno previo del asistente (o si hay pacing de conversación).
    """
    # a) Respaldo de coherencia con lo que Lía está diciendo en el turno actual
    if texto_llm_actual:
        txt_norm = unicodedata.normalize('NFD', texto_llm_actual.lower())
        txt_norm = ''.join(c for c in txt_norm if unicodedata.category(c) != 'Mn')
        frases_coherencia = [
            "he abierto el formulario", "abro el formulario", "aqui tienes el formulario",
            "aqui esta el formulario", "te dejo el formulario", "llena el formulario",
            "completa el formulario", "formulario en pantalla", "puedes llenar el formulario",
            "dejar tus datos en el formulario", "te abro el formulario"
        ]
        if any(f in txt_norm for f in frases_coherencia):
            return True

    p = unicodedata.normalize('NFD', (pregunta or "").lower())
    p = ''.join(c for c in p if unicodedata.category(c) != 'Mn').strip()

    # b) Intención explícita directa del usuario (siempre se respeta si el usuario lo pide)
    palabras_intencion_explicita = [
        "inscribir", "inscripcion", "inscribirme", "matricular", "matricula", "matricularme",
        "postular", "postulacion", "llamen", "llamame", "llamad", "contacto", "contactar",
        "contacten", "formulario", "asesor", "asesoria", "visita guiada", "conocer la sede",
        "datos", "dejar mis datos", "quiero registrarme", "registrame", "quiero que me contacten"
    ]
    if any(k in p for k in palabras_intencion_explicita):
        return True

    # c) Confirmación afirmativa (ej. "sí", "de acuerdo", "perfecto", etc.):
    confirmaciones = [
        "si", "claro", "por favor", "de acuerdo", "dale", "ok", "a ver", "por supuesto",
        "bueno", "me gustaria", "acepto", "perfecto", "listo", "genial", "excelente"
    ]
    es_afirmativo = any(p == a or p.startswith(f"{a} ") or p.endswith(f" {a}") or f" {a} " in p for a in confirmaciones)

    if es_afirmativo and historial:
        for turno in reversed(historial):
            if turno.get("role") == "assistant":
                content = unicodedata.normalize('NFD', turno.get("content", "").lower())
                content = ''.join(c for c in content if unicodedata.category(c) != 'Mn')
                # ¿Lía invitó a contacto por WhatsApp, visita guiada, formalizar o dejar datos?
                invito_contacto = any(k in content for k in [
                    "asesor te contacte", "contacte por whatsapp", "visita guiada",
                    "conocer las instalaciones", "agendar una visita", "dejar tus datos",
                    "ayudarte con tu matricula", "te contactemos", "comunicarse contigo",
                    "asesor se comunique", "formulario", "te parece", "te gustaria que",
                    "deseas que", "coordinar", "para orientarte"
                ])
                if invito_contacto:
                    return True
                break

        # Si hay pacing suficiente (al menos 4 mensajes en historial) y responde afirmativamente
        if len(historial) >= 4:
            return True

    return False


def _usuario_valido_pago(user_query: str, session: dict = None, historial: list = None, texto_llm_actual: str = "") -> bool:
    """
    Guardrail determinista para autorizar la acción SHOW_PAYMENT:
      a) El mensaje actual del usuario contiene palabras clave de pago/reserva/QR.
      b) O el turno anterior del asistente ofreció reservar vacante/matrícula/pago por Yape
         y el usuario respondió afirmativamente ("sí", "claro", "por favor", "de acuerdo", etc.).
      c) Regla de coherencia de salida: Si el texto generado por el LLM incluye explícitamente
         frases de entrega del QR o datos de pago ("aquí tienes el qr", "código qr de yape", etc.).
    """
    # c) Coherencia con la respuesta de Lía
    if texto_llm_actual and _texto_contiene_gatillo_pago(texto_llm_actual):
        return True

    # a) Palabras de pago en la consulta del usuario
    palabras_pago = [
        "pagar", "yape", "yapear", "deposito", "depositar", "transferir", "transferencia",
        "matricularme", "inscribirme", "separar mi vacante", "separar vacante", "reservar vacante",
        "comprobante", "qr", "donde pago", "como pago", "hago el pago", "quiero pagar", "pasar el qr"
    ]
    q_norm = unicodedata.normalize('NFD', (user_query or "").lower())
    q_norm = ''.join(c for c in q_norm if unicodedata.category(c) != 'Mn').strip()

    if any(p in q_norm for p in palabras_pago):
        return True

    # b) Respuesta afirmativa ante ofrecimiento previo del asistente de reservar vacante o pago por Yape
    confirmaciones = [
        "si", "claro", "por favor", "de acuerdo", "dale", "ok", "a ver",
        "acepto", "perfecto", "bueno", "por supuesto", "me gustaria", "listo", "genial"
    ]
    es_afirmativo = any(q_norm == a or q_norm.startswith(f"{a} ") or q_norm.endswith(f" {a}") or f" {a} " in q_norm for a in confirmaciones)

    historial_eval = historial
    if not historial_eval and isinstance(session, dict):
        historial_eval = session.get("history", [])

    if es_afirmativo and historial_eval:
        for turno in reversed(historial_eval):
            if turno.get("role") == "assistant":
                content = unicodedata.normalize('NFD', turno.get("content", "").lower())
                content = ''.join(c for c in content if unicodedata.category(c) != 'Mn')
                ofrecio_pago = any(k in content for k in [
                    "yape", "qr", "congelar tu vacante", "asegurar tu vacante", "separar tu vacante",
                    "pagar tu matricula", "pago de matricula", "realizar el pago", "vacantes limitadas",
                    "asegurar tu lugar", "congelar la vacante"
                ])
                if ofrecio_pago:
                    return True
                break

    return False


def _texto_contiene_gatillo_pago(texto: str) -> bool:
    """Detecta si el texto generado por Lía indica explícitamente entrega de QR o datos de pago."""
    if not texto:
        return False
    t_norm = unicodedata.normalize('NFD', texto.lower())
    t_norm = ''.join(c for c in t_norm if unicodedata.category(c) != 'Mn')
    frases_gatillo = [
        "aqui tienes el qr",
        "aqui esta el qr",
        "te muestro el qr",
        "codigo qr de yape",
        "codigo qr oficial",
        "qr de yape",
        "datos de pago para separar tu vacante",
        "datos de pago para tu matricula"
    ]
    return any(f in t_norm for f in frases_gatillo)


def _resolver_carrera_monto_pago(pregunta: str, historial: list = None, params: list = None) -> tuple[str, str]:
    """
    Resuelve la carrera activa y el monto predeterminado de matrícula para SHOW_PAYMENT.
    Prioriza los parámetros existentes si son válidos, o detecta la entidad activa de la sesión.
    """
    carrera = ""
    monto_explicito = ""

    if params and len(params) >= 1 and params[0].strip():
        carrera = params[0].strip()
    if params and len(params) >= 2 and params[1].strip():
        monto_explicito = params[1].strip()

    if not carrera or carrera.lower() in ["general", "carrera"]:
        entidad = detectar_entidad(pregunta or "", historial or [])
        if entidad:
            carrera = entidad.capitalize()
        else:
            carrera = "Gastronomia"

    # Si se proporcionó un monto explícito (distinto de placeholder "100"), respetarlo
    if monto_explicito and monto_explicito != "100":
        monto = monto_explicito
    else:
        # Montos estándar de matrícula según carrera del Instituto
        if carrera.lower() in ["turismo", "administracion", "contabilidad"]:
            monto = "200"
        else:
            monto = "250"

    return carrera, monto


def _deducir_acciones_heuristicas(
    texto: str,
    mode: str = "web",
    persona: str = "sales",
    pregunta: str = "",
    historial: list = None,
) -> list[tuple[str, list[str]]]:
    """
    Fallback heurístico de seguridad empresarial:
    SOLO se dispara si el usuario validó ver imágenes (orden directa o respuesta afirmativa a ofrecimiento)
    o para pagos con intención directa explícita en modo web.
    """
    acciones = []

    # Para imágenes: requiere orden directa o respuesta afirmativa a ofrecimiento previo
    if _usuario_valido_ver_imagenes(pregunta, historial or []):
        p_norm = unicodedata.normalize('NFD', pregunta.lower())
        p_norm = ''.join(c for c in p_norm if unicodedata.category(c) != 'Mn')
        txt_norm = unicodedata.normalize('NFD', texto.lower())
        txt_norm = ''.join(c for c in txt_norm if unicodedata.category(c) != 'Mn')
        # Si el usuario solo dijo "sí", el contexto temático proviene del último turno del asistente
        prev_txt = ""
        if historial:
            for turno in reversed(historial):
                if turno.get("role") == "assistant":
                    prev_txt = turno.get("content", "").lower()
                    break
        combinado = f"{p_norm} {txt_norm} {prev_txt}"

        if any(k in combinado for k in ["taller", "estacion", "cocina"]) and "gastronomia" in combinado:
            acciones.append(("SHOW_GALLERY", ["gastronomia_talleres"]))
        elif any(k in combinado for k in ["uniforme", "filipina", "mandil"]):
            acciones.append(("SHOW_GALLERY", ["gastronomia_uniforme"]))
        elif any(k in combinado for k in ["turismo", "salida", "campo"]):
            acciones.append(("SHOW_GALLERY", ["turismo_salidas"]))
        elif any(k in combinado for k in ["bartender", "barra"]):
            acciones.append(("SHOW_GALLERY", ["bartender_barra"]))
        elif any(k in combinado for k in ["pasteleria", "panaderia", "horno"]):
            acciones.append(("SHOW_GALLERY", ["pasteleria_horno"]))

    # Para pago: solo en web y si el usuario validó el pago o el texto del LLM contiene gatillo explícito de pago
    if mode != "kiosk" and persona != "info":
        if _usuario_valido_pago(pregunta, historial=historial, texto_llm_actual=texto):
            carrera_det, monto_det = _resolver_carrera_monto_pago(pregunta, historial)
            acciones.append(("SHOW_PAYMENT", [carrera_det, monto_det]))

    return acciones


def _generar_frase_respaldo_accion(acciones: list[str]) -> str:
    """
    Salvavidas en backend (Fallback anti-silencio):
    Si se emitió una acción pero el texto quedó vacío o con menos de 10 caracteres,
    genera un diálogo contextual entusiasta con pregunta de avance en el embudo.
    """
    for act in acciones:
        if act.startswith("SHOW_GALLERY:"):
            recurso_id = act.split(":", 1)[1].strip()
            if "taller" in recurso_id:
                return "¡Con gusto! Aquí tienes una vista de nuestras cocinas y talleres equipados. Tenemos turnos de lunes a viernes y fines de semana. ¿Qué horario te acomodaría mejor?"
            elif "uniforme" in recurso_id:
                return "¡Por supuesto! Aquí puedes ver el uniforme oficial completo que viene incluido con tu matrícula. ¿Te gustaría conocer las opciones de turnos disponibles?"
            elif "turismo" in recurso_id:
                return "¡Claro que sí! Aquí tienes una muestra de nuestras salidas de campo y visitas arqueológicas. ¿Prefieres estudiar en turno mañana o turno noche?"
            elif "bartender" in recurso_id:
                return "¡Por supuesto! Aquí tienes nuestra barra profesional de coctelería equipada para tus clases prácticas. ¿Te acomodaría más estudiar entre semana o los sábados?"
            elif "pasteleria" in recurso_id or "horno" in recurso_id:
                return "¡Aquí tienes nuestros talleres de panadería y pastelería con hornos industriales! ¿Te gustaría que revisemos los turnos disponibles para tus clases?"
            elif "fachada" in recurso_id:
                return "¡Aquí puedes ver nuestra sede principal en San Sebastián! Atendemos de lunes a sábado en horario continuo. ¿Te gustaría venir a conocerla en persona?"
            else:
                return "¡Aquí tienes la imagen en tu pantalla! ¿Te gustaría que revisemos juntos los horarios disponibles?"
        elif act.startswith("SHOW_PAYMENT:"):
            return "¡Excelente decisión! Aquí tienes el código QR oficial de Yape y los datos de pago para separar tu vacante. En cuanto hagas el pago, puedes subir tu comprobante aquí mismo para confirmarte."
        elif act.startswith("OPEN_LEAD_FORM:"):
            return "¡Perfecto! Te acabo de abrir el formulario en pantalla para registrar tus datos o agendar tu visita guiada. Por favor, déjanos tu nombre y número de WhatsApp para contactarte."

    return "¡Aquí tienes la información en tu pantalla! ¿Te gustaría que revisemos los turnos y opciones disponibles?"


async def _obtener_rag(historial: list, pregunta: str) -> str:
    """
    Delega la búsqueda RAG a rag_service.buscar_contexto(), que internamente:
      1. Reformula la query si es corta/ambigua y hay historial (via Groq temp=0).
      2. Ejecuta la búsqueda vectorial en ChromaDB en un ThreadPoolExecutor.
      3. Formatea cada chunk con metadatos jerárquicos [Programa | Sección].
    """
    return await buscar_contexto(pregunta, historial)


# ── Endpoint streaming (v4.0) ─────────────────────────────────────────────────
@app.post("/chat/stream")
async def responder_streaming(data: ChatInput):
    """
    Pipeline de streaming SSE con cuatro tipos de eventos:

      { type: "text",  text: "Primera oración." }
      { type: "audio", audio_b64: "..." }
      { type: "done",  full_text: "..." }
      { type: "error", message: "..." }

    Nuevo (v4.0):
      event: ui_action\ndata: { type: "ui_action", action: "SHOW_GALLERY", ... }\n\n
        → Emitido cuando el LLM incluye [[ACTION:SHOW_GALLERY:resource_id]] en su texto,
          o deducido por la regla de seguridad heurística.
        → El tag es eliminado del buffer antes de enviarse a TTS/subtítulos.
    """
    pregunta   = data.mensaje.strip()
    session_id = data.session_id
    mode       = (data.mode or "web").lower()

    # ── Persona: 'info' (Consulta) | 'sales' (Vendedora) ──────────────────────
    # Default: kiosko arranca en Consulta; web/móvil arranca en Vendedora.
    persona = normalizar_persona(
        data.persona,
        default=PERSONA_INFO if mode == "kiosk" else PERSONA_SALES,
    )
    escalo_a_sales = False
    if persona == PERSONA_INFO and detectar_intencion_comercial(pregunta):
        persona = PERSONA_SALES
        escalo_a_sales = True

    SSE_HEADERS = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }

    if not pregunta:
        async def empty_gen():
            yield _sse_event({"type": "done", "full_text": "En que carrera o curso estas interesado?"})
        return StreamingResponse(empty_gen(), media_type="text/event-stream", headers=SSE_HEADERS)

    sesion_obj = await session_manager.obtener_sesion(session_id)
    historial = sesion_obj["history"]
    shown_media = list(sesion_obj.get("shown_media", []))
    funnel_stage = sesion_obj.get("funnel_stage", "discovery")
    lead_submitted = bool(sesion_obj.get("lead_submitted", False))
    pide_revisar = _pide_ver_de_nuevo(pregunta)

    contexto  = await _obtener_rag(historial, pregunta)

    async def event_generator():
        texto_completo = ""
        acumulado      = ""
        inicio         = time.time()
        primer_audio_en = None
        acciones_emitidas = set()

        try:
            # ── Escalación Consulta → Vendedora: avisar al frontend primero ───
            if escalo_a_sales:
                print(f"[PERSONA] Escalacion info -> sales por intencion comercial | Sesion: {session_id}")
                yield _sse_mode_switch_event(PERSONA_SALES)

            stream = await stream_respuesta_llm(
                historial, contexto, pregunta,
                mode=mode, persona=persona, shown_media=shown_media,
                funnel_stage=funnel_stage, lead_submitted=lead_submitted,
            )

            async for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if not delta:
                    continue
                acumulado      += delta
                texto_completo += delta

                # ── Extraer acciones completas directamente del acumulado ─────
                # Si una etiqueta llegó dividida en múltiples micro-tokens,
                # aquí ya se encuentra ensamblada en el buffer acumulado.
                if "[[" in acumulado and "]]" in acumulado:
                    acumulado, acciones_buffer = _extraer_acciones(acumulado)
                    for tipo, params in acciones_buffer:
                        # Bloqueo anti-spam: no repetir galería ya mostrada salvo petición expresa
                        if tipo == "SHOW_GALLERY" and params:
                            recurso_id = params[0]
                            if (recurso_id in shown_media) and not pide_revisar:
                                print(f"[ANTI-SPAM] Bloqueando SHOW_GALLERY repetido: {recurso_id}")
                                continue
                            await session_manager.registrar_medio_mostrado(session_id, recurso_id)
                            shown_media.append(recurso_id)

                        clave = f"{tipo}:{':'.join(params)}"
                        if clave not in acciones_emitidas:
                            acciones_emitidas.add(clave)
                            # Bloquear formulario si es kiosco, si el lead ya fue registrado, o si no cumple el guardrail de doble paso
                            if tipo == "OPEN_LEAD_FORM":
                                if mode == "kiosk" or lead_submitted:
                                    print(f"[STATE-MACHINE] Bloqueando OPEN_LEAD_FORM (lead_submitted={lead_submitted}, mode={mode})")
                                    continue
                                if not _usuario_valido_formulario_lead(pregunta, historial, texto_llm_actual=texto_completo):
                                    print(f"[GUARDRAIL-LEAD] Descartando OPEN_LEAD_FORM no solicitado por el usuario: '{pregunta}'")
                                    continue
                            elif tipo == "SHOW_PAYMENT":
                                if mode == "kiosk" or not _usuario_valido_pago(pregunta, sesion_obj, historial=historial, texto_llm_actual=texto_completo):
                                    print(f"[GUARDRAIL-PAGO] Descartando SHOW_PAYMENT no solicitado por el usuario: '{pregunta}'")
                                    continue
                                c_res, m_res = _resolver_carrera_monto_pago(pregunta, historial, params)
                                params = [c_res, m_res]
                            print(f"[ACTION] Despachando accion explicita: {tipo} {params}")
                            yield _sse_action_event(tipo, params)

                partes = _SENTENCE_BOUNDARY.split(acumulado, maxsplit=1)

                if len(partes) == 2:
                    oracion_raw, acumulado = partes[0].strip(), partes[1]

                    # Por seguridad, asegurar que no queden action tags sueltos en la oración
                    oracion_limpia, acciones_sueltas = _extraer_acciones(oracion_raw)
                    for tipo, params in acciones_sueltas:
                        if tipo == "SHOW_GALLERY" and params:
                            recurso_id = params[0]
                            if (recurso_id in shown_media) and not pide_revisar:
                                print(f"[ANTI-SPAM] Bloqueando SHOW_GALLERY suelto repetido: {recurso_id}")
                                continue
                            await session_manager.registrar_medio_mostrado(session_id, recurso_id)
                            shown_media.append(recurso_id)

                        clave = f"{tipo}:{':'.join(params)}"
                        if clave not in acciones_emitidas:
                            acciones_emitidas.add(clave)
                            if tipo == "OPEN_LEAD_FORM":
                                if mode == "kiosk" or lead_submitted:
                                    print(f"[STATE-MACHINE] Bloqueando OPEN_LEAD_FORM suelto (lead_submitted={lead_submitted}, mode={mode})")
                                    continue
                                if not _usuario_valido_formulario_lead(pregunta, historial, texto_llm_actual=texto_completo):
                                    print(f"[GUARDRAIL-LEAD] Descartando OPEN_LEAD_FORM suelto no solicitado: '{pregunta}'")
                                    continue
                            elif tipo == "SHOW_PAYMENT":
                                if mode == "kiosk" or not _usuario_valido_pago(pregunta, sesion_obj, historial=historial, texto_llm_actual=texto_completo):
                                    print(f"[GUARDRAIL-PAGO] Descartando SHOW_PAYMENT suelto no solicitado: '{pregunta}'")
                                    continue
                                c_res, m_res = _resolver_carrera_monto_pago(pregunta, historial, params)
                                params = [c_res, m_res]
                            print(f"[ACTION] Despachando accion suelta: {tipo} {params}")
                            yield _sse_action_event(tipo, params)

                    oracion = filtrar_texto(oracion_limpia)
                    if not oracion:
                        continue

                    yield _sse_event({"type": "text", "text": oracion})

                    try:
                        audio_bytes = await generar_audio_bytes(oracion)
                        if primer_audio_en is None:
                            primer_audio_en = time.time() - inicio
                        yield _sse_event({
                            "type": "audio",
                            "audio_b64": base64.b64encode(audio_bytes).decode(),
                        })
                    except Exception as tts_err:
                        print(f"[TTS Stream] Oracion fallida: {tts_err}")

            # ── Procesar buffer residual al término del stream ────────────────
            resto = acumulado.strip()
            if resto:
                oracion_limpia, acciones_finales = _extraer_acciones(resto)
                for tipo, params in acciones_finales:
                    if tipo == "SHOW_GALLERY" and params:
                        recurso_id = params[0]
                        if (recurso_id in shown_media) and not pide_revisar:
                            print(f"[ANTI-SPAM] Bloqueando SHOW_GALLERY final repetido: {recurso_id}")
                            continue
                        await session_manager.registrar_medio_mostrado(session_id, recurso_id)
                        shown_media.append(recurso_id)

                    clave = f"{tipo}:{':'.join(params)}"
                    if clave not in acciones_emitidas:
                        acciones_emitidas.add(clave)
                        if tipo == "OPEN_LEAD_FORM":
                            if mode == "kiosk" or lead_submitted:
                                print(f"[STATE-MACHINE] Bloqueando OPEN_LEAD_FORM final (lead_submitted={lead_submitted}, mode={mode})")
                                continue
                            if not _usuario_valido_formulario_lead(pregunta, historial, texto_llm_actual=texto_completo):
                                print(f"[GUARDRAIL-LEAD] Descartando OPEN_LEAD_FORM final no solicitado: '{pregunta}'")
                                continue
                        elif tipo == "SHOW_PAYMENT":
                            if mode == "kiosk" or not _usuario_valido_pago(pregunta, sesion_obj, historial=historial, texto_llm_actual=texto_completo):
                                print(f"[GUARDRAIL-PAGO] Descartando SHOW_PAYMENT final no solicitado: '{pregunta}'")
                                continue
                            c_res, m_res = _resolver_carrera_monto_pago(pregunta, historial, params)
                            params = [c_res, m_res]
                        print(f"[ACTION] Despachando accion final: {tipo} {params}")
                        yield _sse_action_event(tipo, params)

                oracion = filtrar_texto(oracion_limpia)
                if oracion:
                    yield _sse_event({"type": "text", "text": oracion})
                    try:
                        audio_bytes = await generar_audio_bytes(oracion)
                        if primer_audio_en is None:
                            primer_audio_en = time.time() - inicio
                        yield _sse_event({
                            "type": "audio",
                            "audio_b64": base64.b64encode(audio_bytes).decode(),
                        })
                    except Exception as tts_err:
                        print(f"[TTS Stream] Ultima oracion fallida: {tts_err}")

            # ── Fallback Heurístico (SOLO ante validación de usuario) ─────────
            # Si el LLM no emitió ninguna acción pero el usuario lo autorizó:
            if not acciones_emitidas:
                acciones_fallback = _deducir_acciones_heuristicas(
                    texto_completo, mode=mode, persona=persona, pregunta=pregunta, historial=historial,
                )
                for tipo, params in acciones_fallback:
                    if tipo == "SHOW_GALLERY" and params:
                        recurso_id = params[0]
                        if (recurso_id in shown_media) and not pide_revisar:
                            print(f"[ANTI-SPAM] Bloqueando SHOW_GALLERY heuristico repetido: {recurso_id}")
                            continue
                        await session_manager.registrar_medio_mostrado(session_id, recurso_id)
                        shown_media.append(recurso_id)

                    clave = f"{tipo}:{':'.join(params)}"
                    if clave not in acciones_emitidas:
                        acciones_emitidas.add(clave)
                        if tipo == "OPEN_LEAD_FORM":
                            if mode == "kiosk" or lead_submitted:
                                print(f"[STATE-MACHINE] Bloqueando OPEN_LEAD_FORM heuristico (lead_submitted={lead_submitted}, mode={mode})")
                                continue
                            if not _usuario_valido_formulario_lead(pregunta, historial, texto_llm_actual=texto_completo):
                                print(f"[GUARDRAIL-LEAD] Descartando OPEN_LEAD_FORM heuristico no solicitado: '{pregunta}'")
                                continue
                        elif tipo == "SHOW_PAYMENT":
                            if mode == "kiosk" or not _usuario_valido_pago(pregunta, sesion_obj, historial=historial, texto_llm_actual=texto_completo):
                                print(f"[GUARDRAIL-PAGO] Descartando SHOW_PAYMENT heuristico no solicitado: '{pregunta}'")
                                continue
                            c_res, m_res = _resolver_carrera_monto_pago(pregunta, historial, params)
                            params = [c_res, m_res]
                        print(f"[ACTION FALLBACK] Despachando heuristica: {tipo} {params}")
                        yield _sse_action_event(tipo, params)

            # ── Actualizar historial y cerrar stream ──────────────────────────
            texto_final_limpio, _ = _extraer_acciones(texto_completo.strip())
            texto_final = filtrar_texto(texto_final_limpio)

            # ── Salvavidas en backend (Fallback anti-silencio) ────────────────
            # Si se emitió una acción pero el texto quedó vacío o < 10 caracteres,
            # inyectar frase de respaldo hablada para que Edge-TTS nunca quede en silencio.
            if acciones_emitidas and len(texto_final.strip()) < 10:
                print(f"[ANTI-SILENCIO] Texto LLM insuficiente ({len(texto_final.strip())} chars) tras acción. Inyectando respaldo.")
                frase_respaldo = _generar_frase_respaldo_accion(list(acciones_emitidas))
                texto_final = frase_respaldo
                yield _sse_event({"type": "text", "text": frase_respaldo})
                try:
                    audio_bytes = await generar_audio_bytes(frase_respaldo)
                    if primer_audio_en is None:
                        primer_audio_en = time.time() - inicio
                    yield _sse_event({
                        "type": "audio",
                        "audio_b64": base64.b64encode(audio_bytes).decode(),
                    })
                except Exception as tts_err:
                    print(f"[TTS Stream] Respaldo fallido: {tts_err}")

            historial.append({"role": "user",      "content": pregunta})
            historial.append({"role": "assistant", "content": texto_final})

            tiempo_total = time.time() - inicio
            lat_str = f"{primer_audio_en:.2f}s" if primer_audio_en else "N/A"
            print(
                f"[STREAM] Total: {tiempo_total:.2f}s | "
                f"1er audio: {lat_str} | "
                f"Mode: {mode} | Sesion: {session_id} | Acciones: {len(acciones_emitidas)} | "
                f"Etapa: {funnel_stage} | Lead: {lead_submitted} | Shown: {shown_media}"
            )

            yield _sse_event({"type": "done", "full_text": texto_final})

        except Exception as e:
            print(f"[Stream Error] {e}")
            yield _sse_event({"type": "error", "message": "Error procesando la consulta."})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# ── Endpoint estándar (compatibilidad) ────────────────────────────────────────
@app.post("/chat")
async def responder_con_voz(data: ChatInput):
    inicio_total = time.time()
    pregunta   = data.mensaje.strip()
    session_id = data.session_id
    mode       = (data.mode or "web").lower()

    if not pregunta:
        return {"texto": "En que carrera o curso estas interesado?", "audio_b64": ""}

    sesion_obj = await session_manager.obtener_sesion(session_id)
    historial = sesion_obj["history"]
    shown_media = list(sesion_obj.get("shown_media", []))
    funnel_stage = sesion_obj.get("funnel_stage", "discovery")
    lead_submitted = bool(sesion_obj.get("lead_submitted", False))
    contexto  = await _obtener_rag(historial, pregunta)
    texto_respuesta = await generar_respuesta_llm(
        historial, contexto, pregunta,
        mode=mode, shown_media=shown_media,
        funnel_stage=funnel_stage, lead_submitted=lead_submitted,
    )

    texto_limpio, acciones_raw = _extraer_acciones(texto_respuesta)
    texto_final = filtrar_texto(texto_limpio)

    # Filtrar acciones que no cumplan los guardrails
    acciones_validas = []
    for t, p in acciones_raw:
        if t == "OPEN_LEAD_FORM":
            if mode == "kiosk" or lead_submitted or not _usuario_valido_formulario_lead(pregunta, historial, texto_llm_actual=texto_respuesta):
                continue
        elif t == "SHOW_PAYMENT":
            if mode == "kiosk" or not _usuario_valido_pago(pregunta, sesion_obj, historial=historial, texto_llm_actual=texto_respuesta):
                continue
            c_res, m_res = _resolver_carrera_monto_pago(pregunta, historial, p)
            p = [c_res, m_res]
        acciones_validas.append(f"{t}:{':'.join(p)}")

    if acciones_validas and len(texto_final.strip()) < 10:
        texto_final = _generar_frase_respaldo_accion(acciones_validas)

    historial.append({"role": "user",      "content": pregunta})
    historial.append({"role": "assistant", "content": texto_final})

    try:
        audio_bytes = await generar_audio_bytes(texto_final)
        audio_b64   = base64.b64encode(audio_bytes).decode("utf-8")
    except RuntimeError as e:
        print(f"[TTS ERROR] {e}")
        audio_b64 = ""

    tiempo_total = time.time() - inicio_total
    print(f"[CHAT] Total: {tiempo_total:.2f}s | Mode: {mode} | Sesion: {session_id}")
    return {"texto": texto_final, "audio_b64": audio_b64}


# ── Endpoints de apoyo: Multimedia ────────────────────────────────────────────
@app.get("/api/media")
async def listar_medios():
    """Retorna el catálogo completo de recursos multimedia disponibles."""
    return {"recursos": listar_recursos()}


# ── Endpoints de apoyo: Leads ─────────────────────────────────────────────────
@app.post("/api/leads")
async def registrar_lead(
    nombre:     str = Form(...),
    whatsapp:   str = Form(...),
    carrera:    str = Form(...),
    notas:      str = Form(""),
    session_id: str = Form(""),
):
    """
    Guarda los datos de un prospecto (lead) en JSON.
    Cada lead se guarda en un archivo individual con timestamp + UUID.
    Actualiza la sesión activa marcando lead_submitted = True y funnel_stage = 'closing'.
    """
    lead_id  = str(uuid_lib.uuid4())[:8]
    ts       = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{ts}_{lead_id}.json"
    filepath = os.path.join(_LEADS_DIR, filename)

    lead_data = {
        "id":         lead_id,
        "timestamp":  ts,
        "nombre":     nombre.strip(),
        "whatsapp":   whatsapp.strip(),
        "carrera":    carrera.strip(),
        "notas":      notas.strip(),
        "session_id": session_id.strip(),
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(lead_data, f, ensure_ascii=False, indent=2)

    # ── Transición de estado en SessionManager ───────────────────────────────
    sid = session_id.strip() or "kiosco_principal"
    await session_manager.registrar_lead_completado(sid)
    print(f"[Lead] Registrado: {nombre} | {carrera} | WA: {whatsapp} | Sesión '{sid}' -> closing")

    return JSONResponse({
        "status":  "ok",
        "lead_id": lead_id,
        "message": f"Datos de {nombre} registrados correctamente.",
    })


# ── Endpoints de apoyo: Vouchers ──────────────────────────────────────────────
@app.post("/api/vouchers")
async def subir_voucher(
    imagen:   UploadFile = File(...),
    monto:    str        = Form(...),
    carrera:  str        = Form(...),
    whatsapp: str        = Form(""),
):
    """
    Recibe y guarda el comprobante de pago (imagen) junto con sus metadatos.
    Admite JPG, PNG y WebP.
    """
    ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
    if imagen.content_type not in ALLOWED_MIME:
        return JSONResponse(
            {"status": "error", "message": "Solo se aceptan imagenes JPG, PNG o WebP."},
            status_code=400,
        )

    ext        = imagen.filename.rsplit(".", 1)[-1].lower() if "." in imagen.filename else "jpg"
    voucher_id = str(uuid_lib.uuid4())[:8]
    ts         = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    img_name   = f"{ts}_{voucher_id}.{ext}"
    meta_name  = f"{ts}_{voucher_id}.json"

    img_path  = os.path.join(_VOUCHERS_DIR, img_name)
    meta_path = os.path.join(_VOUCHERS_DIR, meta_name)

    content = await imagen.read()
    with open(img_path, "wb") as f:
        f.write(content)

    meta = {
        "voucher_id": voucher_id,
        "timestamp":  ts,
        "carrera":    carrera.strip(),
        "monto":      monto.strip(),
        "whatsapp":   whatsapp.strip(),
        "imagen":     img_name,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"[Voucher] Guardado: {img_name} | {carrera} | {monto} soles")
    return JSONResponse({
        "status":     "ok",
        "voucher_id": voucher_id,
        "message":    "Comprobante recibido. Verificaremos tu pago en breve.",
    })


# ── Gestión de sesión ─────────────────────────────────────────────────────────
@app.post("/reset-session")
async def reset_session(data: ChatInput):
    await session_manager.resetear(data.session_id)
    return {"status": "ok", "message": f"Sesion '{data.session_id}' reiniciada."}


@app.get("/health")
async def health_check():
    return {
        "status":           "ok",
        "version":          "4.0.0",
        "sesiones_activas": await session_manager.contar_sesiones(),
    }


# ── Punto de entrada ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )
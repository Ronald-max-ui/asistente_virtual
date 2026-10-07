"""
server.py — Orquestador principal del Asistente Virtual IA (v4.0: Dual-Mode Kiosk/Web).

Endpoints de streaming:
  POST /chat/stream  → SSE streaming: RAG → Groq tokens → TTS por oración → audio base64.
                       El servidor autoriza solicitudes tipadas separadas del texto y emite
                       acciones JSON; el adaptador legado nunca expone etiquetas.

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
import uuid as uuid_lib
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from config import settings
from api.commercial import admin_router, public_router
from services.pricing_service import consultar_tarifa, sanear_tarifas_texto, respuesta_comercial, CatalogError, aviso_pago_bloqueado
from services.action_service import ActionContext, procesar_acciones, texto_respaldo
from services.llm_protocol import AssistantReply, LegacyActionAdapter, ToolCallCollector, seleccionar_solicitudes, ChatResponse, SSE_SCHEMA
from session_manager import SessionManager
from services.rag_service import buscar_contexto
from services.llm_service import (
    generar_respuesta_llm,
    stream_respuesta_llm,
)
from services.tts_service import generar_audio_bytes
from services.media_registry import listar_recursos
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

# ── Separación de oraciones para TTS ─────────────────────────────────────────
_SENTENCE_BOUNDARY = re.compile(r'(?<=[.!?])\s+')


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
app.include_router(public_router)
app.include_router(admin_router)


# ── Modelos de entrada ────────────────────────────────────────────────────────
class ChatInput(BaseModel):
    mensaje: str
    session_id: str = "kiosco_principal"
    mode: Optional[str] = "web"   # "kiosk" | "web"  (default: web)
    persona: Optional[str] = None  # "info" | "sales" (None → default según mode)


# ── Helpers internos ──────────────────────────────────────────────────────────
def _sse_event(payload: dict) -> str:
    """Formatea un dict como evento SSE válido (event: data)."""
    payload = SSE_SCHEMA.validate_python(payload).model_dump(mode="json")
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_mode_switch_event(persona: str) -> str:
    return "event: mode_switch\n" + _sse_event({"type": "mode_switch", "mode": persona})


async def _registrar_acciones(session_id: str, actions: list):
    for action in actions:
        if action["type"] == "show_gallery":
            await session_manager.registrar_medio_mostrado(session_id, action["resource_id"])


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
    pregunta = data.mensaje.strip()
    mode = (data.mode or "web").lower()
    persona = normalizar_persona(data.persona, default=PERSONA_INFO if mode == "kiosk" else PERSONA_SALES)
    escalated = persona == PERSONA_INFO and detectar_intencion_comercial(pregunta)
    if escalated:
        persona = PERSONA_SALES
    session = await session_manager.obtener_sesion(data.session_id)
    history = session["history"]
    shown = list(session.get("shown_media", []))
    context = ActionContext(pregunta, history, mode, persona, bool(session.get("lead_submitted", False)), shown)
    rag = await _obtener_rag(history, pregunta) if pregunta else ""

    async def generator():
        adapter = LegacyActionAdapter(pregunta, history)
        collector = ToolCallCollector()
        buffer = ""
        spoken = []
        async def sentence_events(sentence, *, trusted=False):
            sentence = sentence.strip() if trusted else sanear_tarifas_texto(sentence.strip(), pregunta, history)
            if not sentence:
                return
            spoken.append(sentence)
            yield _sse_event({"type": "text", "text": sentence})
            try:
                audio = await generar_audio_bytes(sentence)
                yield _sse_event({"type": "audio", "audio_b64": base64.b64encode(audio).decode()})
            except Exception:
                print("[TTS Stream] No se pudo generar audio para una oración.")
        try:
            if escalated:
                yield _sse_mode_switch_event(persona)
            if not pregunta:
                yield _sse_event({"type": "done", "full_text": "En que carrera o curso estas interesado?"})
                return
            stream = await stream_respuesta_llm(history, rag, pregunta, mode=mode, persona=persona,
                shown_media=shown, funnel_stage=session.get("funnel_stage", "discovery"), lead_submitted=context.lead_submitted)
            truncated = False
            async for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                truncated = truncated or getattr(choice, "finish_reason", None) == "length"
                collector.feed(getattr(choice.delta, "tool_calls", None))
                buffer += adapter.feed(getattr(choice.delta, "content", None) or "")
                parts = _SENTENCE_BOUNDARY.split(buffer)
                buffer = parts.pop()
                for sentence in parts:
                    async for event in sentence_events(sentence):
                        yield event
            buffer += adapter.finish()
            async for event in sentence_events(buffer):
                yield event
            requests = [] if truncated else seleccionar_solicitudes(collector.finish(), adapter.structured_actions, native_present=bool(collector.calls))
            commercial = respuesta_comercial(pregunta, history)
            if commercial and commercial not in " ".join(spoken):
                async for event in sentence_events(commercial, trusted=True):
                    yield event
            result = procesar_acciones(requests, context)
            fallback = texto_respaldo(result)
            if fallback and (result.notices or len(" ".join(spoken)) < 10):
                async for event in sentence_events(fallback, trusted=True):
                    yield event
            await _registrar_acciones(data.session_id, result.actions)
            for action in result.actions:
                yield "event: ui_action\n" + _sse_event({"type": "ui_action", "action": action})
            for notice in result.notices:
                yield _sse_event({"type": "notice", **notice})
            assistant_text = " ".join(spoken)
            history.extend([{"role": "user", "content": pregunta}, {"role": "assistant", "content": assistant_text}])
            yield _sse_event({"type": "done", "full_text": assistant_text})
        except Exception:
            print("[Stream Error] No se pudo procesar la consulta.")
            yield _sse_event({"type": "error", "message": "Error procesando la consulta."})
    return StreamingResponse(generator(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


@app.post("/chat", response_model=ChatResponse)
async def responder_con_voz(data: ChatInput):
    pregunta = data.mensaje.strip()
    mode = (data.mode or "web").lower()
    persona = normalizar_persona(data.persona, default=PERSONA_INFO if mode == "kiosk" else PERSONA_SALES)
    if persona == PERSONA_INFO and detectar_intencion_comercial(pregunta):
        persona = PERSONA_SALES
    if not pregunta:
        return {"texto": "En que carrera o curso estas interesado?", "audio_b64": "", "actions": [], "notices": []}
    session = await session_manager.obtener_sesion(data.session_id)
    history = session["history"]
    shown = list(session.get("shown_media", []))
    context = ActionContext(pregunta, history, mode, persona, bool(session.get("lead_submitted", False)), shown)
    rag = await _obtener_rag(history, pregunta)
    reply = await generar_respuesta_llm(history, rag, pregunta, mode=mode, persona=persona,
        shown_media=shown, funnel_stage=session.get("funnel_stage", "discovery"), lead_submitted=context.lead_submitted)
    # Compatibilidad temporal con proveedores/rutas que aún retornan texto legado.
    reply = AssistantReply(assistant_text=reply) if isinstance(reply, str) else reply
    adapter = LegacyActionAdapter(pregunta, history)
    assistant_text = sanear_tarifas_texto((adapter.feed(reply.assistant_text) + adapter.finish()).strip(), pregunta, history)
    commercial = respuesta_comercial(pregunta, history)
    if commercial and commercial not in assistant_text:
        assistant_text = (assistant_text + " " + commercial).strip()
    result = procesar_acciones(seleccionar_solicitudes(reply.structured_actions, adapter.structured_actions, native_present=reply.native_actions_present), context)
    fallback = texto_respaldo(result)
    if fallback and (result.notices or len(assistant_text) < 10):
        assistant_text = (assistant_text + " " + fallback).strip()
    await _registrar_acciones(data.session_id, result.actions)
    history.extend([{"role": "user", "content": pregunta}, {"role": "assistant", "content": assistant_text}])
    try:
        audio_b64 = base64.b64encode(await generar_audio_bytes(assistant_text)).decode()
    except Exception:
        audio_b64 = ""
    return {"texto": assistant_text, "audio_b64": audio_b64, "actions": result.actions, "notices": result.notices}


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
    concepto: str        = Form("matricula"),
    modalidad: str       = Form(""),
    turno: str           = Form(""),
):
    """
    Recibe y guarda el comprobante de pago (imagen) junto con sus metadatos.
    Admite JPG, PNG y WebP.
    """
    try:
        tariff = consultar_tarifa(carrera, concepto, modalidad or None, turno or None)
    except CatalogError:
        return JSONResponse({"status": "error", "message": "La configuración comercial necesita revisión."}, status_code=409)
    except ValueError:
        return JSONResponse({"status": "error", "message": "Programa, concepto o variante no válido."}, status_code=422)
    pago = {"monto": tariff["amount"], "carrera": tariff["program_label"]}
    notice = aviso_pago_bloqueado(tariff)
    if notice:
        return JSONResponse({"status": "error", **notice}, status_code=409)
    try:
        declarado = Decimal(monto)
        if not declarado.is_finite() or declarado != Decimal(pago["monto"]):
            raise ValueError("Importe distinto del catálogo")
    except (InvalidOperation, ValueError):
        return JSONResponse({"status": "error", "message": "El importe no coincide con la tarifa autorizada."}, status_code=422)
    monto = pago["monto"]
    carrera = pago["carrera"]

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
        "concepto":   concepto.strip(),
        "modalidad":  tariff["modality"],
        "turno":      tariff["shift"],
        "campana":    tariff["campaign"],
        "moneda":     tariff["currency"],
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

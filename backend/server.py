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
from services.rag_service import buscar_contexto
from services.llm_service import (
    generar_respuesta_llm,
    stream_respuesta_llm,
    filtrar_texto,
    construir_prompt_sistema,
)
from services.tts_service import generar_audio_bytes
from services.media_registry import obtener_recurso, listar_recursos


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
    elif tipo == "SHOW_PAYMENT" and len(params) >= 2:
        payload["carrera"] = params[0]
        payload["monto"]   = params[1]
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


def _deducir_acciones_heuristicas(texto: str, mode: str = "web") -> list[tuple[str, list[str]]]:
    """
    Fallback heurístico de seguridad empresarial:
    Si el LLM redactó que muestra una foto, taller, uniforme o QR de pago pero no escribió
    la etiqueta [[ACTION:...]], deducimos la acción adecuada para que la UI se despliegue.
    """
    acciones = []
    # Normalizar texto quitando acentos para matching robusto
    txt = unicodedata.normalize('NFD', texto.lower())
    txt = ''.join(c for c in txt if unicodedata.category(c) != 'Mn')

    # 1. Talleres de gastronomía / cocina
    if any(k in txt for k in ["imagen", "foto", "taller", "estacion", "estaciones"]) and any(g in txt for g in ["gastronomia", "cocina", "culinari"]):
        acciones.append(("SHOW_GALLERY", ["gastronomia_talleres"]))
    # 2. Uniforme de gastronomía
    elif any(u in txt for u in ["uniforme", "filipina", "mandil", "gorro"]) and any(g in txt for g in ["gastronomia", "cocina"]):
        acciones.append(("SHOW_GALLERY", ["gastronomia_uniforme"]))
    # 3. Salidas de campo de turismo
    elif any(k in txt for k in ["salida", "campo", "foto", "imagen"]) and any(t in txt for t in ["turismo", "viaje", "arqueolog"]):
        acciones.append(("SHOW_GALLERY", ["turismo_salidas"]))
    # 4. Barra de bartender
    elif any(k in txt for k in ["barra", "taller", "foto", "imagen"]) and "bartender" in txt:
        acciones.append(("SHOW_GALLERY", ["bartender_barra"]))
    # 5. Pago por Yape / QR (solo web)
    if any(p in txt for p in ["yape", "pagar", "pago", "qr", "transfer"]) and mode != "kiosk":
        carrera_det = "Gastronomia" if "gastronomia" in txt else "General"
        monto_det = "250" if "gastronomia" in txt else "100"
        acciones.append(("SHOW_PAYMENT", [carrera_det, monto_det]))

    return acciones


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

    SSE_HEADERS = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }

    if not pregunta:
        async def empty_gen():
            yield _sse_event({"type": "done", "full_text": "En que carrera o curso estas interesado?"})
        return StreamingResponse(empty_gen(), media_type="text/event-stream", headers=SSE_HEADERS)

    historial = await session_manager.obtener_o_crear(session_id)
    contexto  = await _obtener_rag(historial, pregunta)

    async def event_generator():
        texto_completo = ""
        acumulado      = ""
        inicio         = time.time()
        primer_audio_en = None
        acciones_emitidas = set()

        try:
            stream = await stream_respuesta_llm(historial, contexto, pregunta, mode=mode)

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
                        clave = f"{tipo}:{':'.join(params)}"
                        if clave not in acciones_emitidas:
                            acciones_emitidas.add(clave)
                            if tipo == "OPEN_LEAD_FORM" and mode == "kiosk":
                                continue
                            print(f"[ACTION] Despachando accion explicita: {tipo} {params}")
                            yield _sse_action_event(tipo, params)

                partes = _SENTENCE_BOUNDARY.split(acumulado, maxsplit=1)

                if len(partes) == 2:
                    oracion_raw, acumulado = partes[0].strip(), partes[1]

                    # Por seguridad, asegurar que no queden action tags sueltos en la oración
                    oracion_limpia, acciones_sueltas = _extraer_acciones(oracion_raw)
                    for tipo, params in acciones_sueltas:
                        clave = f"{tipo}:{':'.join(params)}"
                        if clave not in acciones_emitidas:
                            acciones_emitidas.add(clave)
                            if tipo == "OPEN_LEAD_FORM" and mode == "kiosk":
                                continue
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
                    clave = f"{tipo}:{':'.join(params)}"
                    if clave not in acciones_emitidas:
                        acciones_emitidas.add(clave)
                        if tipo == "OPEN_LEAD_FORM" and mode == "kiosk":
                            continue
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

            # ── Fallback Heurístico (Regla de Seguridad Empresarial) ───────────
            # Si el LLM no emitió ninguna acción pero el texto prometió imágenes/talleres/pago:
            if not acciones_emitidas:
                acciones_fallback = _deducir_acciones_heuristicas(texto_completo, mode=mode)
                for tipo, params in acciones_fallback:
                    clave = f"{tipo}:{':'.join(params)}"
                    if clave not in acciones_emitidas:
                        acciones_emitidas.add(clave)
                        if tipo == "OPEN_LEAD_FORM" and mode == "kiosk":
                            continue
                        print(f"[ACTION FALLBACK] Despachando heuristica: {tipo} {params}")
                        yield _sse_action_event(tipo, params)

            # ── Actualizar historial y cerrar stream ──────────────────────────
            texto_final_limpio, _ = _extraer_acciones(texto_completo.strip())
            texto_final = filtrar_texto(texto_final_limpio)
            historial.append({"role": "user",      "content": pregunta})
            historial.append({"role": "assistant", "content": texto_final})

            tiempo_total = time.time() - inicio
            lat_str = f"{primer_audio_en:.2f}s" if primer_audio_en else "N/A"
            print(
                f"[STREAM] Total: {tiempo_total:.2f}s | "
                f"1er audio: {lat_str} | "
                f"Mode: {mode} | Sesion: {session_id} | Acciones: {len(acciones_emitidas)}"
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

    historial = await session_manager.obtener_o_crear(session_id)
    contexto  = await _obtener_rag(historial, pregunta)
    texto_respuesta = await generar_respuesta_llm(historial, contexto, pregunta, mode=mode)

    historial.append({"role": "user",      "content": pregunta})
    historial.append({"role": "assistant", "content": texto_respuesta})

    try:
        audio_bytes = await generar_audio_bytes(texto_respuesta)
        audio_b64   = base64.b64encode(audio_bytes).decode("utf-8")
    except RuntimeError as e:
        print(f"[TTS ERROR] {e}")
        audio_b64 = ""

    tiempo_total = time.time() - inicio_total
    print(f"[CHAT] Total: {tiempo_total:.2f}s | Mode: {mode} | Sesion: {session_id}")
    return {"texto": texto_respuesta, "audio_b64": audio_b64}


# ── Endpoints de apoyo: Multimedia ────────────────────────────────────────────
@app.get("/api/media")
async def listar_medios():
    """Retorna el catálogo completo de recursos multimedia disponibles."""
    return {"recursos": listar_recursos()}


# ── Endpoints de apoyo: Leads ─────────────────────────────────────────────────
@app.post("/api/leads")
async def registrar_lead(
    nombre:   str = Form(...),
    whatsapp: str = Form(...),
    carrera:  str = Form(...),
    notas:    str = Form(""),
):
    """
    Guarda los datos de un prospecto (lead) en JSON.
    Cada lead se guarda en un archivo individual con timestamp + UUID.
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
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(lead_data, f, ensure_ascii=False, indent=2)

    print(f"[Lead] Registrado: {nombre} | {carrera} | WA: {whatsapp}")
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
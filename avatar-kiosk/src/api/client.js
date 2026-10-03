/**
 * api/client.js — Cliente SSE streaming con subtítulos sincronizados con audio.
 *
 * v4.0 (Dual-Mode):
 *   - Lee el modo de la URL (?mode=kiosk → kiosk, default → web).
 *   - Incluye `mode` en el body de /chat/stream.
 *   - Escucha eventos SSE de tipo 'ui_action' y los despacha a overlays.js.
 *   - Los tags [[ACTION:...]] nunca llegan al TTS ni a los subtítulos
 *     (el backend los extrae antes de generar el audio).
 *
 * Protocolo SSE completo (v4.0):
 *   data: { type: "text",  text: "..." }
 *   data: { type: "audio", audio_b64: "..." }
 *   event: ui_action\ndata: { type: "ui_action", action: "SHOW_GALLERY", ... }
 *   data: { type: "done",  full_text: "..." }
 *   data: { type: "error", message: "..." }
 */

import { enqueueAudio, clearAudioQueue } from '../audio/player.js';
import { setIsProcessingResponse, registrarActividad } from '../avatar/animator.js';
import { openGallery, openLeadForm, openPayment } from '../ui/overlays.js';

// ── Configuración ─────────────────────────────────────────────────────────────
const BACKEND_URL        = 'http://127.0.0.1:8000';
const CONNECT_TIMEOUT_MS = 20000;
const MAX_REINTENTOS     = 2;

// ── Modo de operación (leído de la URL, inmutable) ────────────────────────────
export const APP_MODE = (() => {
  const params = new URLSearchParams(window.location.search);
  const m = (params.get('mode') || 'web').toLowerCase();
  const mode = m === 'kiosk' ? 'kiosk' : 'web';
  console.log(`[api/client] Modo: ${mode}`);
  return mode;
})();

// ── Sesión UUID única por pestaña ─────────────────────────────────────────────
const SESSION_ID = (() => {
  const KEY = 'av_kiosk_session_id';
  let id = sessionStorage.getItem(KEY);
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem(KEY, id);
  }
  console.log(`[api/client] Session ID: ${id}`);
  return id;
})();

// ── Referencias DOM ───────────────────────────────────────────────────────────
const getStatusBadge = () => document.getElementById('status-badge');
const getSubtitles   = () => document.getElementById('subtitles');

/**
 * Convierte una cadena base64 en una Blob URL de audio MP3.
 */
function b64ToBlobUrl(b64) {
  const binaryStr = atob(b64);
  const bytes = new Uint8Array(binaryStr.length);
  for (let i = 0; i < binaryStr.length; i++) bytes[i] = binaryStr.charCodeAt(i);
  return URL.createObjectURL(new Blob([bytes], { type: 'audio/mpeg' }));
}

/**
 * Parser de SSE v4.0: soporta eventos con nombre (event: ui_action) además
 * de los eventos `data:` estándar sin nombre.
 *
 * El formato SSE completo para eventos con nombre es:
 *   event: ui_action\n
 *   data: {...}\n
 *   \n
 *
 * El formato para eventos sin nombre (estándar) es:
 *   data: {...}\n
 *   \n
 */
async function _parseSseStream(body, onEvent) {
  const reader  = body.getReader();
  const decoder = new TextDecoder();
  let buffer    = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split('\n\n');
      buffer = blocks.pop() ?? '';

      for (const block of blocks) {
        if (!block.trim()) continue;

        // Parsear líneas del bloque SSE
        let eventName = 'message';
        let dataStr   = '';

        for (const line of block.split('\n')) {
          if (line.startsWith('event: '))      eventName = line.slice(7).trim();
          else if (line.startsWith('data: '))  dataStr   = line.slice(6).trim();
        }

        if (!dataStr) continue;

        try {
          const parsed = JSON.parse(dataStr);
          // Normalizar: si el evento tiene nombre propio, lo ponemos en parsed.type
          if (eventName !== 'message' && !parsed.type) {
            parsed.type = eventName;
          }
          onEvent(parsed);
        } catch (parseErr) {
          console.warn('[api/client] SSE parse error:', parseErr, '|', dataStr.slice(0, 80));
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Despacha un evento ui_action al overlay correspondiente.
 * @param {object} event - Payload del SSE ui_action
 */
function _despacharUiAction(event) {
  console.log("[UI_ACTION] Recibido evento:", event.action, event);
  switch (event.action) {
    case 'SHOW_GALLERY':
      openGallery(event);
      break;
    case 'OPEN_LEAD_FORM':
      openLeadForm(event);
      break;
    case 'SHOW_PAYMENT':
      openPayment(event);
      break;
    default:
      console.warn('[api/client] Acción UI desconocida:', event.action);
  }
}

/**
 * Envía la pregunta del usuario al endpoint /chat/stream y procesa
 * la respuesta SSE en tiempo real, sincronizando subtítulos con audio.
 *
 * @param {string} pregunta  - Texto de la pregunta del usuario.
 * @param {number} [intentos=0] - Contador interno de reintentos.
 */
export async function consultarAsistente(pregunta, intentos = 0) {
  if (intentos === 0) clearAudioQueue();
  setIsProcessingResponse(true);
  registrarActividad();

  const controller = new AbortController();
  const timeoutId  = setTimeout(() => controller.abort(), CONNECT_TIMEOUT_MS);

  try {
    const res = await fetch(`${BACKEND_URL}/chat/stream`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        mensaje:    pregunta,
        session_id: SESSION_ID,
        mode:       APP_MODE,         // ← Nuevo: enviamos el modo al backend
      }),
      signal:  controller.signal,
    });
    clearTimeout(timeoutId);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    // Texto pendiente: llega del SSE antes del audio, se muestra al iniciar el audio
    let pendingText  = '';
    let subtitleText = '';

    await _parseSseStream(res.body, (event) => {
      switch (event.type) {

        case 'text':
          // ── Guardar el texto pero NO mostrarlo todavía ─────────────────────
          pendingText = event.text;
          break;

        case 'audio': {
          const textoDeEsteChunk = pendingText;
          pendingText = '';

          if (!event.audio_b64) break;

          enqueueAudio(
            b64ToBlobUrl(event.audio_b64),
            null,
            () => {
              if (textoDeEsteChunk) {
                subtitleText += (subtitleText ? ' ' : '') + textoDeEsteChunk;
                getSubtitles().textContent = subtitleText;
                getStatusBadge().textContent = 'Hablando...';
                getStatusBadge().className   = '';
              }
            },
          );
          break;
        }

        case 'ui_action':
          // ── Despachar acción UI (galería, formulario, pago) ────────────────
          // No afecta audio ni subtítulos — se gestiona en overlays.js
          _despacharUiAction(event);
          break;

        case 'done':
          if (pendingText) {
            subtitleText += (subtitleText ? ' ' : '') + pendingText;
            getSubtitles().textContent = subtitleText;
            pendingText = '';
          }
          setIsProcessingResponse(false);
          registrarActividad();
          console.log('[api/client] Stream completo.');
          break;

        case 'error':
          setIsProcessingResponse(false);
          registrarActividad();
          getSubtitles().textContent   = 'Ocurrió un error. Por favor, intenta de nuevo.';
          getStatusBadge().textContent = 'Toca el micrófono para hablar';
          getStatusBadge().className   = '';
          console.error('[api/client] Error del servidor:', event.message);
          break;

        default:
          console.warn('[api/client] Evento SSE desconocido:', event.type);
      }
    });

  } catch (err) {
    clearTimeout(timeoutId);

    if (intentos < MAX_REINTENTOS) {
      getStatusBadge().textContent = `Reintentando... (${intentos + 1}/${MAX_REINTENTOS})`;
      await new Promise(r => setTimeout(r, 1500));
      return consultarAsistente(pregunta, intentos + 1);
    }

    setIsProcessingResponse(false);
    registrarActividad();
    getSubtitles().textContent   = 'No pude conectarme. Por favor, intenta de nuevo.';
    getStatusBadge().textContent = 'Toca el micrófono para hablar';
    getStatusBadge().className   = '';
    console.error('[api/client] Error tras reintentos:', err);
  }
}

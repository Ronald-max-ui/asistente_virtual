import { setAssistantState } from '../ui/state.js';
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
 *   event: ui_action\ndata: { type: "ui_action", action: { type: "show_gallery", resource_id: "...", resource: {} } }
 *   data: { type: "done",  full_text: "..." }
 *   data: { type: "error", message: "..." }
 */

import { enqueueBase64Audio, waitForAudioCapacity, clearAudioQueue, beginAudioStream, endAudioStream, onAudioQueueFinished } from '../audio/player.js';
import { setIsProcessingResponse, registrarActividad } from '../avatar/animator.js';
import { crearHandlerAccion } from './actions.js';
import { getPersona, setPersona } from '../ui/persona.js';
import { detenerReconocimiento } from '../ui/controls.js';

// ── Configuración ─────────────────────────────────────────────────────────────
import { apiUrl } from './config.js';
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

import { SESSION_ID, sessionHeaders, invalidateSession } from './session.js';
export { SESSION_ID } from './session.js';
let requestGeneration = 0;
let activeController = null;
let activeOperationId = null;
let replacementNeeded=false;
// Numeric transport diagnostics, bounded and correlated only by backend operation.
function transportMetrics() {
  const now = () => globalThis.performance?.now?.() ?? Date.now();
  const started = now(), values = {};
  return {
    first(name) { if (!(name in values)) values[name] = Math.round((now() - started) * 1000) / 1000; },
    report(id) {
      if (!/^[a-f0-9-]{32,36}$/.test(id || '')) return;
      console.debug?.('[performance]', { request_id:id, ...values });
    },
  };
}

export async function cancelarInteraccion() {
  setAssistantState('cancelling');
  const cancelGeneration=++requestGeneration;
  const rid = activeOperationId;
  const hadActiveRequest=!!activeController || !!rid;
  if(hadActiveRequest) replacementNeeded=true;
  activeController?.abort();
  activeController = null;
  activeOperationId = null;
  clearAudioQueue();
  setIsProcessingResponse(false);
  if (hadActiveRequest) {
    try {
      await fetch(apiUrl('/api/session/cancel'), {
        method: 'POST', headers: { 'Content-Type':'application/json', ...await sessionHeaders(crypto.randomUUID()) },
        body: JSON.stringify({ session_id:SESSION_ID, active_request_id:rid }), signal:AbortSignal.timeout(5000),
      });
    } catch { console.warn('[api/client] Cancelación remota no confirmada.'); }
  }
  if(cancelGeneration===requestGeneration) setAssistantState('ready');
}

export async function resetConversation() {
  await cancelarInteraccion();
  const res = await fetch(apiUrl('/reset-session'), {
    method:'POST', headers:{ 'Content-Type':'application/json', ...await sessionHeaders(crypto.randomUUID()) },
    body:JSON.stringify({ mensaje:'', session_id:SESSION_ID }), signal:AbortSignal.timeout(20000),
  });
  if (!res.ok) throw new Error('No se pudo reiniciar la conversación');
  getSubtitles().textContent = '';
  setAssistantState('ready');
}

// ── Referencias DOM ───────────────────────────────────────────────────────────
const getSubtitles   = () => document.getElementById('subtitles');

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
async function waitForRetry() {
  const controller = new AbortController();
  activeController = controller;
  await new Promise((resolve) => {
    let timer;
    const finish = () => {
      clearTimeout(timer);
      controller.signal.removeEventListener('abort', finish);
      resolve();
    };
    timer = setTimeout(finish, 1500);
    controller.signal.addEventListener('abort', finish, { once: true });
  });
}

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
          await onEvent(parsed);
        } catch (parseErr) {
          console.warn('[api/client] Evento SSE inválido; descartado.');
        }
      }
    }
  } finally {
    try { await reader.cancel(); } catch (_) {}
    reader.releaseLock();
  }
}

/**
 * Ejecuta físicamente la acción visual en los overlays.
 * @param {object} event - Payload del SSE ui_action
 */
function _despacharUiAction(event, isCurrent) {
  const handler = crearHandlerAccion(event?.action, isCurrent);
  if (!handler) return;
  // Se conserva el hold hasta done y la finalización real de todo el audio.
  onAudioQueueFinished(() => { if (isCurrent()) handler(); });
}

/**
 * Envía la pregunta del usuario al endpoint /chat/stream y procesa
 * la respuesta SSE en tiempo real, sincronizando subtítulos con audio.
 *
 * @param {string} pregunta  - Texto de la pregunta del usuario.
 * @param {number} [intentos=0] - Contador interno de reintentos.
 */
export async function consultarAsistente(pregunta, intentos = 0, operation = null) {
  if (!operation) {
    const replace = !!activeController || replacementNeeded;
    activeController?.abort();
    operation = { requestGeneration:++requestGeneration, key:crypto.randomUUID(), replace, metrics:transportMetrics() };
    activeOperationId = null;
  }
  const isCurrent = () => requestGeneration === operation.requestGeneration;
  if (!isCurrent()) return;
  clearAudioQueue();
  beginAudioStream();
  let responseDone = false;
  setIsProcessingResponse(true);
  setAssistantState('processing');
  registrarActividad();

  const controller = new AbortController();
  activeController = controller;
  const timeoutId  = setTimeout(() => controller.abort(), CONNECT_TIMEOUT_MS);

  try {
    const headers = await sessionHeaders(operation.key);
    if (!isCurrent()) return;
    const res = await fetch(apiUrl('/chat/stream'), {
      method:  'POST',
      headers: { 'Content-Type': 'application/json', ...headers },
      body:    JSON.stringify({
        mensaje:    pregunta,
        replace_active: operation.replace,
        idempotency_key: operation.key,
        session_id: SESSION_ID,
        mode:       APP_MODE,         // kiosk | web (capacidades del dispositivo)
        persona:    getPersona(),     // info | sales (modo manual o escalado)
      }),
      signal:  controller.signal,
    });
    clearTimeout(timeoutId);
    if (!res.ok) {
      if ([401, 410].includes(res.status)) invalidateSession();
      const error = new Error(`HTTP ${res.status}`);
      error.noRetry = [401, 403, 409, 410, 422, 429].includes(res.status);
      throw error;
    }

    replacementNeeded=false;
    activeOperationId = res.headers?.get('X-Operation-ID') || activeOperationId;
    // Texto pendiente: llega del SSE antes del audio, se muestra al iniciar el audio
    let pendingText  = '';
    let subtitleText = '';
    const sentences=[];let visibleIndex=-1;let audioChunks=0;
    const showThrough=(index)=>{visibleIndex=Math.max(visibleIndex,index);subtitleText=sentences.slice(0,visibleIndex+1).join(' ');getSubtitles().textContent=subtitleText;};
    let micDetenido  = false;

    await _parseSseStream(res.body, async (event) => {
      if (!isCurrent()) return;
      operation.received=true;
      if (event.request_id) {
        if (!activeOperationId) activeOperationId = event.request_id;
        if (activeOperationId !== event.request_id) return;
      }
      if (responseDone) {
        console.warn('[api/client] Evento posterior al cierre; ignorado.');
        return;
      }
      // Liberar el micrófono de inmediato en el primer token/evento para que iOS WebKit habilite los altavoces
      if (!micDetenido) {
        detenerReconocimiento();
        micDetenido = true;
      }

      switch (event.type) {

        case 'text':
          operation.metrics?.first('first_text_sse_ms');
          // ── Guardar el texto pero NO mostrarlo todavía ─────────────────────
          if(pendingText) showThrough(sentences.length-1);
          pendingText = event.text;sentences.push(event.text);
          setAssistantState('responding');
          break;

        case 'audio': {
          const textoDeEsteChunk = pendingText;
          const sentenceIndex=sentences.length-1;
          pendingText = '';

          if (!event.audio_b64) {showThrough(sentenceIndex);break;}
          audioChunks++;

          await waitForAudioCapacity();
          if (!isCurrent()) break;
          enqueueBase64Audio(
            event.audio_b64,
            null,
            () => {
              if (isCurrent()) operation.metrics?.first('first_audio_play_ms');
              if (isCurrent() && textoDeEsteChunk) {
                operation.metrics?.first('first_visible_response_ms');
                showThrough(sentenceIndex);
                setAssistantState('speaking');
              }
            },
          );
          break;
        }

        case 'mode_switch':
          if (!['info', 'sales'].includes(event.mode)) {
            console.warn('[api/client] Persona desconocida; ignorada.');
            break;
          }
          // ── Escalación automática Consulta → Vendedora (intención de compra) ─
          console.log('[api/client] mode_switch recibido:', event.mode);
          setPersona(event.mode, 'auto');
          break;

        case 'ui_action':
          // ── Despachar acción UI (galería, formulario, pago) ────────────────
          // No afecta audio ni subtítulos — se gestiona en overlays.js
          _despacharUiAction(event, () => isCurrent() && responseDone);
          break;

        case 'notice':
          // El aviso hablado ya llegó como texto/audio. No abre ningún modal.
          console.warn('[api/client] Aviso comercial:', event.code);
          break;

        case 'done':
          responseDone = true;
          if(!audioChunks) {const notice=document.getElementById('capability-notice');if(notice) notice.textContent='Respuesta disponible por escrito. Puedes continuar.';}
          operation.metrics?.first('transport_done_ms');
          setIsProcessingResponse(false);
          registrarActividad();
          onAudioQueueFinished(() => {
            if (!isCurrent()) return;
            operation.metrics?.first('first_visible_response_ms');
            operation.metrics?.first('playback_done_ms');
            operation.metrics?.report(activeOperationId);
            getSubtitles().textContent = event.full_text || subtitleText || pendingText;
            setAssistantState('ready');
          });
          endAudioStream();
          break;

        case 'error':
          responseDone = true;
          clearAudioQueue();
          setIsProcessingResponse(false);
          registrarActividad();
          getSubtitles().textContent   = 'Ocurrió un error. Por favor, intenta de nuevo.';
          setAssistantState('error');
          console.error('[api/client] Proveedor no disponible.');
          break;

        default:
          console.warn('[api/client] Evento SSE desconocido:', event.type);
      }
    });
    if (!responseDone) throw new Error('Stream incompleto');

  } catch (err) {
    clearTimeout(timeoutId);
    if (!isCurrent()) return;
    clearAudioQueue();

    if (!operation.received && !err.noRetry && intentos < MAX_REINTENTOS) {
      setAssistantState('processing');
      await waitForRetry();
      return consultarAsistente(pregunta, intentos + 1, operation);
    }

    setIsProcessingResponse(false);
    registrarActividad();
    getSubtitles().textContent = 'No pude completar la respuesta. Por favor, intenta de nuevo.';
    setAssistantState('error');
    console.error('[api/client] Consulta no completada.');
  } finally {
    clearTimeout(timeoutId);
    if (isCurrent() && activeController === controller) activeController = null;
  }
}

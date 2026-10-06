/**
 * audio/player.js — Reproductor de Audio nativo Web Audio API (AudioContext)
 * con decodificación de PCM / MP3 in-memory y cola encadenada de AudioBufferSourceNode.
 *
 * Máxima compatibilidad con iOS Safari / WebKit:
 *  - Sin instanciar elementos HTML5 <audio> ni blobs asíncronos que Safari bloquea.
 *  - Decodificación directa mediante audioContext.decodeAudioData().
 *  - Lipsync garantizado conectando cada AudioBufferSourceNode a analyser -> destination.
 *  - Desbloqueo garantizado en el gesto táctil inicial del usuario.
 */

let audioContext = null;
let analyser     = null;
let dataArray    = null;
let _isSpeaking  = false;

// ── Cola de reproducción de buffers ───────────────────────────────────────────
// Cada ítem: { buffer: AudioBuffer, onEndCallback: Function|null, onPlayCallback: Function|null }
let bufferQueue        = [];
let isPlayingQueue     = false;
let currentSourceNode  = null;
let _onQueueEmptyCallback = null;

// Helper: Convierte string base64 a ArrayBuffer estándar
export function base64ToArrayBuffer(base64) {
  const binaryString = window.atob(base64);
  const len = binaryString.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes.buffer;
}

/**
 * Inicializa el AudioContext global y el nodo Analyser para lipsync.
 */
function _initAudioContext() {
  if (!audioContext) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    audioContext = new AudioContextClass();
    window.audioCtx = audioContext; // Exponer para depuración e interoperabilidad

    analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    dataArray = new Uint8Array(analyser.frequencyBinCount);
    analyser.connect(audioContext.destination);
  }
  return audioContext;
}

/**
 * Desbloquea el AudioContext dentro del evento táctil / click del usuario.
 */
export function unlockAudio() {
  try {
    const ctx = _initAudioContext();
    if (ctx.state === 'suspended') {
      ctx.resume().catch((err) => console.warn('[audio/player] Error resumiendo AudioContext:', err));
    }

    // Inyectar un micro-buffer de silencio (1 muestra a 22050Hz) para autorizar el contexto en iOS
    if (ctx.createBuffer) {
      const buffer = ctx.createBuffer(1, 1, 22050);
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);
      source.start(0);
    }
    console.log('[audio/player] AudioContext desbloqueado exitosamente para iOS/Safari');
  } catch (err) {
    console.warn('[audio/player] Error en unlockAudio:', err);
  }
}

/**
 * Procesa secuencialmente los buffers encolados usando AudioBufferSourceNode.
 */
function _processBufferQueue() {
  if (isPlayingQueue) return;

  if (bufferQueue.length === 0) {
    isPlayingQueue = false;
    _isSpeaking = false;
    if (_onQueueEmptyCallback) {
      const cb = _onQueueEmptyCallback;
      _onQueueEmptyCallback = null;
      cb();
    }
    return;
  }

  isPlayingQueue = true;
  _isSpeaking = true;
  const item = bufferQueue.shift();

  try {
    const ctx = _initAudioContext();
    if (ctx.state === 'suspended') {
      ctx.resume().catch(() => {});
    }

    const source = ctx.createBufferSource();
    source.buffer = item.buffer;
    currentSourceNode = source;

    // Conectar a analyser (para lipsync de Lía) y de ahí a destination (parlantes)
    source.connect(analyser);

    // Disparar sincronización de subtítulos al comenzar la reproducción
    if (item.onPlayCallback) {
      item.onPlayCallback();
    }

    source.onended = () => {
      currentSourceNode = null;
      if (item.onEndCallback) {
        item.onEndCallback();
      }
      isPlayingQueue = false;
      _processBufferQueue(); // Encadenar el siguiente fragmento
    };

    source.start(0);
  } catch (err) {
    console.error('[audio/player] Error reproduciendo buffer en AudioBufferSourceNode:', err);
    if (item.onPlayCallback) item.onPlayCallback();
    if (item.onEndCallback) item.onEndCallback();
    isPlayingQueue = false;
    _processBufferQueue();
  }
}

/**
 * Encola un fragmento de audio en Base64 recibido por SSE.
 * Decodifica asíncronamente con decodeAudioData y lo encadena a la cola de reproducción.
 *
 * @param {string} b64Data - String en formato base64 con audio MP3 o WAV
 * @param {Function|null} onEndCallback - Callback al finalizar este chunk
 * @param {Function|null} onPlayCallback - Callback al iniciar este chunk (para subtítulos sincronizados)
 */
export async function enqueueBase64Audio(b64Data, onEndCallback = null, onPlayCallback = null) {
  if (!b64Data) return;
  try {
    const ctx = _initAudioContext();
    if (ctx.state === 'suspended') {
      await ctx.resume().catch(() => {});
    }

    const arrayBuffer = base64ToArrayBuffer(b64Data);

    // decodeAudioData con soporte dual para callbacks de Safari legado y Promesas
    ctx.decodeAudioData(
      arrayBuffer,
      (audioBuffer) => {
        bufferQueue.push({
          buffer: audioBuffer,
          onEndCallback,
          onPlayCallback,
        });
        _processBufferQueue();
      },
      (decodeErr) => {
        console.warn('[audio/player] Error decodificando audio chunk:', decodeErr);
        if (onPlayCallback) onPlayCallback();
        if (onEndCallback) onEndCallback();
      }
    );
  } catch (err) {
    console.error('[audio/player] Error procesando base64 audio:', err);
    if (onPlayCallback) onPlayCallback();
    if (onEndCallback) onEndCallback();
  }
}

/**
 * Compatibilidad con la firma anterior enqueueAudio(url, ...).
 * Si la url es data: o blob: o base64, la delega a decodificación.
 */
export async function enqueueAudio(urlOrB64, onEndCallback = null, onPlayCallback = null) {
  if (!urlOrB64) return;
  if (urlOrB64.startsWith('data:audio/')) {
    const b64 = urlOrB64.split(',')[1];
    return enqueueBase64Audio(b64, onEndCallback, onPlayCallback);
  }
  try {
    // Si es una URL o Blob URL, descargamos el ArrayBuffer para decodificarlo nativamente con Web Audio
    const res = await fetch(urlOrB64);
    const arrayBuffer = await res.arrayBuffer();
    const ctx = _initAudioContext();
    ctx.decodeAudioData(
      arrayBuffer,
      (audioBuffer) => {
        bufferQueue.push({
          buffer: audioBuffer,
          onEndCallback,
          onPlayCallback,
        });
        _processBufferQueue();
      },
      (err) => {
        console.warn('[audio/player] Error decodificando URL audio:', err);
        if (onPlayCallback) onPlayCallback();
        if (onEndCallback) onEndCallback();
      }
    );
  } catch (e) {
    console.warn('[audio/player] Fallo al cargar audio desde URL:', e);
    if (onPlayCallback) onPlayCallback();
    if (onEndCallback) onEndCallback();
  }
}

/**
 * Reproduce un audio inmediatamente desde URL (ej. atracciones), cancelando colas previas.
 */
export async function playAudio(url, onEndCallback = null) {
  clearAudioQueue();
  stopCurrentAudio();
  enqueueAudio(url, onEndCallback, null);
}

/**
 * Devuelve true si hay audio reproduciéndose activamente.
 */
export function isCurrentlySpeaking() {
  return _isSpeaking;
}

/**
 * Devuelve true si hay audio reproduciéndose o elementos encolados pendientes.
 */
export function isAudioBusy() {
  return _isSpeaking || isPlayingQueue || bufferQueue.length > 0;
}

/**
 * Registra un callback para cuando la cola actual termine completamente.
 */
export function onAudioQueueFinished(callback) {
  if (!isAudioBusy()) {
    callback();
    return;
  }
  _onQueueEmptyCallback = callback;
}

/**
 * Devuelve el analyser y dataArray para el lipsync de Lía en animator.js.
 */
export function getAnalyser() {
  _initAudioContext();
  return { analyser, dataArray };
}

/**
 * Vacía la cola de reproducción.
 */
export function clearAudioQueue() {
  bufferQueue = [];
}

/**
 * Detiene inmediatamente la reproducción actual y vacía la cola.
 */
export function stopCurrentAudio() {
  bufferQueue = [];
  isPlayingQueue = false;
  _isSpeaking = false;
  if (currentSourceNode) {
    try {
      currentSourceNode.stop();
      currentSourceNode.disconnect();
    } catch (_) {}
    currentSourceNode = null;
  }
}


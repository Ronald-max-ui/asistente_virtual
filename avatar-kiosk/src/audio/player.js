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
let queueCallbacks = new Set();
let generation = 0;
let streamHolds = 0;
const MAX_PENDING_AUDIO = 8;
const capacityWaiters = new Set();
function releaseCapacity() {
  if (bufferQueue.length >= MAX_PENDING_AUDIO) return;
  for (const resolve of capacityWaiters) resolve();
  capacityWaiters.clear();
}
export function waitForAudioCapacity() {
  if (bufferQueue.length < MAX_PENDING_AUDIO) return Promise.resolve();
  return new Promise((resolve) => capacityWaiters.add(resolve));
}

function invoke(callback) {
  try { callback?.(); } catch (err) { console.error('[audio/player] Callback fallido.'); }
}

function notifyFinished() {
  if (isAudioBusy()) return;
  const callbacks = [...queueCallbacks];
  queueCallbacks.clear();
  callbacks.forEach(invoke);
}

export function beginAudioStream() { streamHolds++; }
export function endAudioStream() {
  streamHolds = Math.max(0, streamHolds - 1);
  notifyFinished();
}

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
      ctx.resume().catch((err) => console.warn('[audio/player] Error resumiendo AudioContext.'));
    }

    // Inyectar un micro-buffer de silencio (1 muestra a 22050Hz) para autorizar el contexto en iOS
    if (ctx.createBuffer) {
      const buffer = ctx.createBuffer(1, 1, 22050);
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);
      source.onended = () => { source.disconnect(); source.buffer = null; source.onended = null; };
      source.start(0);
    }
    console.log('[audio/player] AudioContext desbloqueado exitosamente para iOS/Safari');
  } catch (err) {
    console.warn('[audio/player] Error en unlockAudio.');
  }
}

/**
 * Procesa secuencialmente los buffers encolados usando AudioBufferSourceNode.
 */
function _processBufferQueue() {
  if (isPlayingQueue) return;
  if (!bufferQueue.length) {
    _isSpeaking = false;
    notifyFinished();
    return;
  }
  // Se reservan posiciones antes de descargar/decodificar para conservar el orden.
  const item = bufferQueue[0];
  if (!item.ready) return;
  bufferQueue.shift();
  releaseCapacity();
  if (!item.buffer) {
    invoke(item.onPlayCallback); // Subtítulos siguen disponibles aunque falle el audio.
    invoke(item.onEndCallback);
    _processBufferQueue();
    return;
  }
  try {
    const ctx = _initAudioContext();
    if (ctx.state === 'suspended') ctx.resume().catch(() => {});
    const source = ctx.createBufferSource();
    source.buffer = item.buffer;
    source.connect(analyser);
    currentSourceNode = source;
    isPlayingQueue = true;
    _isSpeaking = true;
    source.onended = () => {
      source.disconnect();
      source.onended = null;
      source.buffer = null;
      item.buffer = null;
      // Una cancelación no puede finalizar una nueva fuente ni disparar callbacks viejos.
      if (item.generation !== generation || currentSourceNode !== source) return;
      currentSourceNode = null;
      isPlayingQueue = false;
      _isSpeaking = false;
      invoke(item.onEndCallback);
      _processBufferQueue();
    };
    source.start(0);
    invoke(item.onPlayCallback);
  } catch (err) {
    console.error('[audio/player] Reproducción fallida.');
    currentSourceNode?.disconnect();
    currentSourceNode = null;
    isPlayingQueue = false;
    _isSpeaking = false;
    invoke(item.onPlayCallback);
    invoke(item.onEndCallback);
    _processBufferQueue();
  }
}

function reserveAudio(onEndCallback, onPlayCallback) {
  const item = { generation, ready: false, buffer: null, onEndCallback, onPlayCallback };
  bufferQueue.push(item);
  return item;
}

async function decodeItem(item, load) {
  try {
    const arrayBuffer = await load();
    if (item.generation !== generation) return;
    const ctx = _initAudioContext();
    // Adaptador callbacks/Promesa para Safari y navegadores modernos.
    item.buffer = await new Promise((resolve, reject) => {
      const promise = ctx.decodeAudioData(arrayBuffer, resolve, reject);
      promise?.then(resolve, reject);
    });
  } catch (err) {
    console.warn('[audio/player] Audio no disponible.');
  } finally {
    if (item.generation === generation) {
      item.ready = true;
      _processBufferQueue();
    }
  }
}

export function enqueueBase64Audio(b64Data, onEndCallback = null, onPlayCallback = null) {
  if (!b64Data) return Promise.resolve();
  const item = reserveAudio(onEndCallback, onPlayCallback);
  return decodeItem(item, () => base64ToArrayBuffer(b64Data));
}

export function enqueueAudio(urlOrB64, onEndCallback = null, onPlayCallback = null) {
  if (!urlOrB64) return Promise.resolve();
  if (urlOrB64.startsWith('data:audio/')) {
    return enqueueBase64Audio(urlOrB64.split(',')[1], onEndCallback, onPlayCallback);
  }
  const item = reserveAudio(onEndCallback, onPlayCallback);
  return decodeItem(item, async () => {
    const res = await fetch(urlOrB64);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.arrayBuffer();
  });
}

export function playAudio(url, onEndCallback = null) {
  stopCurrentAudio();
  return enqueueAudio(url, onEndCallback);
}

export function isCurrentlySpeaking() { return _isSpeaking; }

export function isAudioBusy() {
  return _isSpeaking || isPlayingQueue || bufferQueue.length > 0 || streamHolds > 0;
}

export function onAudioQueueFinished(callback) {
  if (!isAudioBusy()) { invoke(callback); return () => {}; }
  queueCallbacks.add(callback);
  return () => queueCallbacks.delete(callback);
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
  // Cancelar también cargas/decodificaciones antiguas; no reaparecen en la nueva cola.
  stopCurrentAudio();
}

export function stopCurrentAudio() {
  generation++;
  for (const item of bufferQueue) item.buffer = null;
  bufferQueue = [];
  releaseCapacity();
  queueCallbacks.clear();
  streamHolds = 0;
  isPlayingQueue = false;
  _isSpeaking = false;
  const source = currentSourceNode;
  currentSourceNode = null;
  if (source) {
    source.onended = null;
    try { source.stop(); source.disconnect(); source.buffer = null; } catch (_) {}
  }
}

export async function disposeAudio() {
  stopCurrentAudio();
  analyser?.disconnect();
  if (audioContext?.close) await audioContext.close();
  audioContext = null; analyser = null; dataArray = null;
  window.audioCtx = null;
}

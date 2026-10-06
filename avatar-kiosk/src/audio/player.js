/**
 * audio/player.js — Singleton de AudioContext con cola de reproducción sincronizada con subtítulos.
 *
 * MEJORA (fix desincronización de subtítulos):
 *   enqueueAudio() ahora acepta un `onPlayCallback` que se dispara en el momento
 *   exacto en que AudioContext llama a source.start() / audio.onplay. El cliente
 *   (api/client.js) pasa el texto como closure del onPlayCallback, de modo que el
 *   subtítulo solo se muestra cuando el audio físicamente empieza a sonar.
 *
 * API pública:
 *   playAudio(url, onEnd)           → Reproduce inmediatamente (prioridad atracción).
 *   enqueueAudio(url, onEnd, onPlay)→ Añade a la cola. onPlay se llama al iniciar reproducción.
 *   clearAudioQueue()               → Vacía la cola (al inicio de nueva pregunta).
 *   isCurrentlySpeaking()           → true si hay audio reproduciéndose.
 *   getAnalyser()                   → { analyser, dataArray } para lipsync.
 */

let audioContext        = null;
let analyser            = null;
let dataArray           = null;
let _isSpeaking         = false;
let currentAudioSource  = null;
let currentAudioElement = null;

// ── Cola de reproducción ──────────────────────────────────────────────────────
// Cada ítem: { url: string, onEndCallback: Function|null, onPlayCallback: Function|null }
let audioQueue     = [];
let isPlayingQueue = false;
let _onQueueEmptyCallback = null;

function _initAudioContext() {
  if (audioContext) return;
  audioContext = new (window.AudioContext || window.webkitAudioContext)();
  analyser = audioContext.createAnalyser();
  analyser.fftSize = 256;
  dataArray = new Uint8Array(analyser.frequencyBinCount);
  analyser.connect(audioContext.destination);
}

/**
 * Núcleo interno: reproduce un audio inmediatamente.
 *
 * @param {string}        url            - Blob URL o ruta estática del audio.
 * @param {Function|null} onEndCallback  - Se llama cuando el audio termina.
 * @param {Function|null} onPlayCallback - Se llama en el momento exacto en que el audio EMPIEZA.
 *                                         Usar para sincronizar subtítulos con el audio.
 */
function _playImmediate(url, onEndCallback = null, onPlayCallback = null) {
  _initAudioContext();
  if (audioContext.state === 'suspended') audioContext.resume();

  // Limpiar audio anterior: anular callbacks primero para evitar efectos secundarios
  if (currentAudioElement) {
    currentAudioElement.onplay  = null;
    currentAudioElement.onended = null;
    currentAudioElement.pause();
    currentAudioElement.src = '';
  }
  if (currentAudioSource) {
    try { currentAudioSource.disconnect(); } catch (_) {}
    currentAudioSource = null;
  }

  const audio = new Audio(url);
  audio.crossOrigin = 'anonymous';

  currentAudioSource = audioContext.createMediaElementSource(audio);
  currentAudioSource.connect(analyser);
  currentAudioElement = audio;

  audio.onplay = () => {
    _isSpeaking = true;
    // ── Punto de sincronización: el subtítulo se muestra AQUÍ, no antes ──────
    // onPlayCallback se llama en el momento exacto en que el navegador empieza
    // a reproducir el audio. Cualquier texto asociado a este chunk debe mostrarse
    // dentro de este callback, no cuando el evento SSE llegó al cliente.
    if (onPlayCallback) onPlayCallback();
  };

  audio.onended = () => {
    _isSpeaking = false;
    try { currentAudioSource.disconnect(); } catch (_) {}
    currentAudioSource = null;
    currentAudioElement = null;
    if (url.startsWith('blob:')) URL.revokeObjectURL(url);
    if (onEndCallback) onEndCallback();
  };

  audio.play().catch(e => console.error('[audio/player] Error al reproducir:', e));
}

/** Procesa el siguiente elemento de la cola si hay uno pendiente y no estamos reproduciendo. */
function _processQueue() {
  if (isPlayingQueue) return;
  if (audioQueue.length === 0) {
    if (!_isSpeaking && _onQueueEmptyCallback) {
      const cb = _onQueueEmptyCallback;
      _onQueueEmptyCallback = null;
      cb();
    }
    return;
  }
  isPlayingQueue = true;
  const item = audioQueue.shift();
  _playImmediate(
    item.url,
    () => {
      isPlayingQueue = false;
      if (item.onEndCallback) item.onEndCallback();
      if (audioQueue.length === 0 && _onQueueEmptyCallback) {
        const cb = _onQueueEmptyCallback;
        _onQueueEmptyCallback = null;
        cb();
      } else {
        _processQueue(); // Encadenar el siguiente chunk
      }
    },
    item.onPlayCallback, // Propaga el callback de inicio al núcleo
  );
}

// ── API pública ───────────────────────────────────────────────────────────────

/** Devuelve true si hay audio reproduciéndose actualmente. */
export function isCurrentlySpeaking() {
  return _isSpeaking;
}

/** Devuelve true si hay audio reproduciéndose o elementos esperando en la cola. */
export function isAudioBusy() {
  return _isSpeaking || isPlayingQueue || audioQueue.length > 0;
}

/**
 * Registra un callback que se llamará cuando la cola actual de audio termine
 * completamente de sonar y no queden chunks pendientes.
 * Si ya no hay audio ocupado, ejecuta el callback inmediatamente.
 */
export function onAudioQueueFinished(callback) {
  if (!isAudioBusy()) {
    callback();
    return;
  }
  _onQueueEmptyCallback = callback;
}

/** Devuelve el analyser y dataArray para el lipsync del animator. */
export function getAnalyser() {
  return { analyser, dataArray };
}

/**
 * Reproduce un audio inmediatamente, cancelando cualquier cola activa.
 * Usar para: audios de atracción (/atraccion_1.mp3, etc.).
 *
 * @param {string}        url            - URL del audio.
 * @param {Function|null} onEndCallback  - Callback al terminar.
 */
export function playAudio(url, onEndCallback = null) {
  audioQueue     = [];
  isPlayingQueue = false;
  _playImmediate(url, onEndCallback, null);
}

/**
 * Añade un audio a la cola y la procesa si no hay nada reproduciéndose.
 * Usar para: chunks del pipeline streaming /chat/stream.
 *
 * La sincronización de subtítulos funciona así:
 *   1. El texto llega del SSE → NO se muestra aún.
 *   2. Se llama enqueueAudio(url, null, () => mostrar_texto_en_pantalla).
 *   3. Cuando el AudioContext dispara onplay, se llama onPlayCallback().
 *   4. El subtítulo aparece en pantalla sincronizado con el audio.
 *
 * @param {string}        url             - URL del audio (blob: generada desde base64).
 * @param {Function|null} onEndCallback   - Callback al terminar este chunk.
 * @param {Function|null} onPlayCallback  - Callback al INICIAR este chunk (para subtítulos).
 */
export function enqueueAudio(url, onEndCallback = null, onPlayCallback = null) {
  audioQueue.push({ url, onEndCallback, onPlayCallback });
  _processQueue();
}

/**
 * Vacía la cola de reproducción sin detener el audio actual.
 * Llamar al inicio de cada nueva consulta.
 */
export function clearAudioQueue() {
  audioQueue = [];
}

/**
 * Detiene inmediatamente cualquier audio en reproducción y vacía la cola.
 * Útil para cancelar audios de atracción o respuestas en curso ante interacción del usuario.
 */
export function stopCurrentAudio() {
  audioQueue = [];
  isPlayingQueue = false;
  if (currentAudioElement) {
    currentAudioElement.onplay = null;
    currentAudioElement.onended = null;
    currentAudioElement.pause();
    currentAudioElement.src = '';
    currentAudioElement = null;
  }
  if (currentAudioSource) {
    try { currentAudioSource.disconnect(); } catch (_) {}
    currentAudioSource = null;
  }
  _isSpeaking = false;
}


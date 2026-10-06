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

let globalAudioPlayer = null;

function _getOrCreateGlobalAudioPlayer() {
  if (globalAudioPlayer && document.body.contains(globalAudioPlayer)) {
    return globalAudioPlayer;
  }
  let existing = document.getElementById('lia-audio-player');
  if (!existing) {
    existing = new Audio();
    existing.id = 'lia-audio-player';
    existing.crossOrigin = 'anonymous';
    existing.playsInline = true;
    existing.setAttribute('playsinline', 'true');
    existing.setAttribute('webkit-playsinline', 'true');
    existing.style.display = 'none';
    document.body.appendChild(existing);
  }
  globalAudioPlayer = existing;
  return globalAudioPlayer;
}

function _initAudioContext() {
  if (!audioContext) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    dataArray = new Uint8Array(analyser.frequencyBinCount);
    analyser.connect(audioContext.destination);
  }

  const player = _getOrCreateGlobalAudioPlayer();
  if (!currentAudioSource && audioContext && player) {
    try {
      currentAudioSource = audioContext.createMediaElementSource(player);
      currentAudioSource.connect(analyser);
    } catch (e) {
      console.warn('[audio/player] MediaElementSource ya conectado o error:', e);
    }
  }
}

/**
 * Desbloquea silenciosamente la Web Audio API y el elemento HTML5 Audio único
 * dentro del gesto táctil inicial del usuario (click / touchstart).
 * Crucial para iOS Safari y Chrome en iOS que imponen políticas estrictas de Autoplay.
 */
export function unlockAudio() {
  try {
    _initAudioContext();
    if (audioContext && audioContext.state === 'suspended') {
      audioContext.resume().catch(() => {});
    }

    // "Prime" con 1 milisegundo de buffer de silencio en AudioContext
    if (audioContext && audioContext.createBuffer) {
      const buffer = audioContext.createBuffer(1, 1, 22050);
      const source = audioContext.createBufferSource();
      source.buffer = buffer;
      source.connect(audioContext.destination);
      source.start(0);
    }

    // "Prime" del singleton HTML5 Audio reutilizable en el DOM
    const player = _getOrCreateGlobalAudioPlayer();
    player.src = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA";
    const p = player.play();
    if (p !== undefined) {
      p.then(() => {
        // Pausar y dejar preparado para chunks posteriores
        player.pause();
      }).catch((e) => {
        console.warn('[audio/player] Aviso al desbloquear singleton en gesto:', e);
      });
    }
    console.log('[audio/player] Audio singleton desbloqueado exitosamente para iOS/Safari');
  } catch (err) {
    console.warn('[audio/player] Error intentando desbloquear audio en móvil:', err);
  }
}

/**
 * Núcleo interno: reproduce un audio secuencialmente reutilizando el MISMO elemento singleton.
 *
 * @param {string}        url            - Blob URL, Data URL o ruta estática del audio.
 * @param {Function|null} onEndCallback  - Se llama cuando el audio termina.
 * @param {Function|null} onPlayCallback - Se llama en el momento exacto en que el audio EMPIEZA.
 */
function _playImmediate(url, onEndCallback = null, onPlayCallback = null) {
  _initAudioContext();
  if (audioContext && audioContext.state === 'suspended') {
    audioContext.resume().catch(() => {});
  }

  const audio = _getOrCreateGlobalAudioPlayer();

  // Limpiar listeners y estado anterior del reproductor singleton
  audio.onplay  = null;
  audio.onended = null;
  audio.onerror = null;

  let cleanedUp = false;
  const cleanupAudio = () => {
    if (cleanedUp) return;
    cleanedUp = true;
    _isSpeaking = false;
    audio.onplay  = null;
    audio.onended = null;
    audio.onerror = null;
    if (url.startsWith('blob:')) URL.revokeObjectURL(url);
  };

  audio.onplay = () => {
    _isSpeaking = true;
    if (onPlayCallback) onPlayCallback();
  };

  audio.onended = () => {
    cleanupAudio();
    if (onEndCallback) onEndCallback();
  };

  audio.onerror = (e) => {
    console.warn('[audio/player] Error en elemento de audio singleton:', e);
    if (onPlayCallback) onPlayCallback();
    cleanupAudio();
    if (onEndCallback) onEndCallback();
  };

  // Reutilizar la MISMA instancia asignando el nuevo source
  audio.src = url;
  audio.currentTime = 0;

  const playPromise = audio.play();
  if (playPromise !== undefined) {
    playPromise.catch((err) => {
      console.warn('[audio/player] Play rechazado en móvil (iOS Safari):', err);
      if (onPlayCallback) onPlayCallback();
      cleanupAudio();
      if (onEndCallback) onEndCallback();
    });
  }
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
  if (globalAudioPlayer) {
    globalAudioPlayer.onplay = null;
    globalAudioPlayer.onended = null;
    globalAudioPlayer.onerror = null;
    globalAudioPlayer.pause();
    globalAudioPlayer.currentTime = 0;
  }
  _isSpeaking = false;
}


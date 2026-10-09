import { setAssistantState, assistantState, setConnected, setVoiceAvailable, canSend } from './state.js';
/**
 * ui/controls.js — Interfaz de usuario: micrófono, badges y SpeechRecognition.
 *
 * Responsabilidades:
 *  - Inicializar los event listeners del botón de micrófono.
 *  - Gestionar el ciclo de vida de SpeechRecognition.
 *  - Notificar al animator el estado de escucha (setIsListening).
 *  - Registrar actividad del usuario para el temporizador de inactividad.
 *  - Delegar la petición al backend a api/client.js.
 */

import { consultarAsistente, cancelarInteraccion } from '../api/client.js';
import { dispararSaludo, setIsListening, registrarActividad } from '../avatar/animator.js';
import { isCurrentlySpeaking, unlockAudio } from '../audio/player.js';

/**
 * Inicializa todos los controles de UI.
 * Debe llamarse desde main.js después de que el DOM esté listo.
 */
export function initControls(mode = 'web') {
  disposeControls();
  const micBtn = document.getElementById('mic-btn');
  const subtitles = document.getElementById('subtitles');

  const form=document.getElementById('text-form');
  const input=document.getElementById('text-message');
  const stop=document.getElementById('stop-btn');
  const notice=document.getElementById('capability-notice');
  const textEnabled=mode==='web' || window.__liaPublicConfig?.visual?.kiosk_text_enabled===true;
  if(form) form.hidden=!textEnabled;
  const send=(event)=>{event.preventDefault();if(!canSend() || !input?.value.trim()) return;unlockAudio();
    const text=input.value.trim();input.value='';detenerReconocimiento();void consultarAsistente(text);};
  const cancel=()=>{detenerReconocimiento();void cancelarInteraccion();};
  const offline=()=>{detenerReconocimiento();void cancelarInteraccion();setConnected(false);};
  const online=()=>setConnected(true);
  form?.addEventListener('submit',send);stop?.addEventListener('click',cancel);
  window.addEventListener('offline',offline);window.addEventListener('online',online);
  _removeAlternativeListeners=()=>{form?.removeEventListener('submit',send);stop?.removeEventListener('click',cancel);
    window.removeEventListener('offline',offline);window.removeEventListener('online',online);};
  setConnected(window.navigator?.onLine!==false);
  const voiceUnavailable=(message)=>{setVoiceAvailable(false);if(form) form.hidden=false;if(notice) notice.textContent=message;};
  // Registrar actividad con cualquier interacción táctil o de teclado
  window.addEventListener('pointerdown', registrarActividad);
  window.addEventListener('keydown', registrarActividad);

  // ── SpeechRecognition ──────────────────────────────────────────────────────
  const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!SpeechRecognitionAPI) {
    console.warn('[ui/controls] SpeechRecognition no disponible en este navegador.');
    voiceUnavailable('La voz no está disponible en este navegador. Puedes escribir tu pregunta.');
    return;
  }

  const recognition = new SpeechRecognitionAPI();
  recognition.lang = 'es-PE';
  recognition.continuous = false;
  recognition.interimResults = false;

  let isListening = false;

  const saludoRegex = /\b(hola|buenos d[ií]as|buenas tardes|buenas noches|hey|saludos)\b/i;

  recognition.onstart = () => {
    registrarActividad();
    isListening = true;
    setIsListening(true);
    micBtn.classList.add('active');
    setAssistantState('listening');
  };

  recognition.onspeechstart = () => {
    // Se dispara apenas el navegador detecta que el usuario empezó a emitir voz
    registrarActividad();
    setIsListening(true);
  };

  recognition.onspeechend = () => {
    registrarActividad();
  };

  recognition.onresult = (event) => {
    if(!['ready','listening','error'].includes(assistantState())) return;
    registrarActividad();
    const textoDetectado = event.results[0][0].transcript;
    subtitles.textContent = `"${textoDetectado}"`;
    setAssistantState('processing');

    // Disparar animación de saludo si el usuario saluda
    if (saludoRegex.test(textoDetectado)) {
      dispararSaludo();
    }

    consultarAsistente(textoDetectado);
  };

  recognition.onerror = (event) => {
    isListening = false;
    setIsListening(false);
    micBtn.classList.remove('active');
    if(['not-allowed','service-not-allowed','audio-capture'].includes(event?.error)) {
      voiceUnavailable('El micrófono no está disponible. Puedes escribir sin volver a conceder permiso.');
      try {recognition.abort();} catch (_) {}
    }
    if(assistantState()==='listening') setAssistantState('ready');
  };

  recognition.onend = () => {
    isListening = false;
    setIsListening(false);
    micBtn.classList.remove('active');
    if(assistantState()==='listening') setAssistantState('ready');
  };

  // ── Botón de micrófono: Desbloqueo de audio y soporte táctil para iOS ─────
  const manejarInteraccionMic = (e) => {
    // Si fue touchstart, prevenimos el click fantasma posterior de 300ms
    if (e.type === 'touchstart') {
      e.preventDefault();
    }

    // 1. Desbloqueo silencioso inmediato del motor de audio (Web Audio API)
    unlockAudio();

    // 2. Control de estado del avatar y SpeechRecognition
    if (isCurrentlySpeaking() || (!isListening && !canSend())) return;

    if (!isListening) {
      dispararSaludo(); // Saludo de bienvenida al tocar el micrófono
      try {
        recognition.start();
      } catch (recErr) {
        console.warn('[ui/controls] No se pudo iniciar la voz.');
        voiceUnavailable('No se pudo iniciar la voz. Puedes escribir tu pregunta.');
      }
    } else {
      recognition.stop();
    }
  };

  // Escuchar tanto touchstart como click
  micBtn.addEventListener('touchstart', manejarInteraccionMic, { passive: false });
  micBtn.addEventListener('click', manejarInteraccionMic);

  _recognitionInstance = recognition;
  _removeMicListeners = () => {
    micBtn.removeEventListener('touchstart', manejarInteraccionMic);
    micBtn.removeEventListener('click', manejarInteraccionMic);
  };
}

let _recognitionInstance = null;

/**
 * Detiene inmediatamente la sesión de SpeechRecognition.
 * Crucial para iOS Safari: liberar el micrófono permite al SO conmutar el canal de audio a los altavoces.
 */
export function detenerReconocimiento() {
  if (_recognitionInstance) {
    try {
      _recognitionInstance.stop();
      console.log('[ui/controls] Micrófono / SpeechRecognition liberado para reproducción de audio.');
    } catch (_) {}
  }
}

/**
 * Reactiva SpeechRecognition si es requerido tras finalizar la locución del avatar.
 */
export function reactivarReconocimiento() {
  // En modo quiosco o si se desea reactivar, se puede invocar de forma controlada
}

let _removeMicListeners = null;
let _removeAlternativeListeners = null;
export function disposeControls() {
  _removeAlternativeListeners?.();_removeAlternativeListeners=null;
  window.removeEventListener('pointerdown', registrarActividad);
  window.removeEventListener('keydown', registrarActividad);
  _removeMicListeners?.(); _removeMicListeners = null;
  if (_recognitionInstance) {
    _recognitionInstance.onstart = _recognitionInstance.onresult = null;
    _recognitionInstance.onspeechstart = _recognitionInstance.onspeechend = null;
    _recognitionInstance.onerror = _recognitionInstance.onend = null;
    try { _recognitionInstance.abort(); } catch (_) {}
    _recognitionInstance = null;
  }
}

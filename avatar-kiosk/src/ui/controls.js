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

import { consultarAsistente } from '../api/client.js';
import { dispararSaludo, setIsListening, registrarActividad } from '../avatar/animator.js';
import { isCurrentlySpeaking, unlockAudio } from '../audio/player.js';

/**
 * Inicializa todos los controles de UI.
 * Debe llamarse desde main.js después de que el DOM esté listo.
 */
export function initControls(mode = 'web') {
  const statusBadge = document.getElementById('status-badge');
  const micBtn = document.getElementById('mic-btn');
  const subtitles = document.getElementById('subtitles');

  // Registrar actividad con cualquier interacción táctil o de teclado
  window.addEventListener('pointerdown', registrarActividad);
  window.addEventListener('keydown', registrarActividad);

  // ── SpeechRecognition ──────────────────────────────────────────────────────
  const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!SpeechRecognitionAPI) {
    console.warn('[ui/controls] SpeechRecognition no disponible en este navegador.');
    statusBadge.textContent = 'Navegador no compatible con voz';
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
    statusBadge.textContent = 'Escuchando...';
    statusBadge.className = 'listening';
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
    registrarActividad();
    const textoDetectado = event.results[0][0].transcript;
    subtitles.textContent = `"${textoDetectado}"`;
    statusBadge.textContent = 'Consultando...';
    statusBadge.className = 'thinking';

    // Disparar animación de saludo si el usuario saluda
    if (saludoRegex.test(textoDetectado)) {
      dispararSaludo();
    }

    consultarAsistente(textoDetectado);
  };

  recognition.onerror = () => {
    isListening = false;
    setIsListening(false);
    micBtn.classList.remove('active');
    statusBadge.textContent = 'Toca el micrófono para hablar';
    statusBadge.className = '';
  };

  recognition.onend = () => {
    isListening = false;
    setIsListening(false);
    micBtn.classList.remove('active');
    // Solo resetear el badge si no estamos esperando respuesta del backend
    if (statusBadge.className !== 'thinking') {
      statusBadge.textContent = 'Toca el micrófono para hablar';
      statusBadge.className = '';
    }
  };

  // ── Botón de micrófono: Desbloqueo de audio y soporte táctil para iOS ─────
  const manejarInteraccionMic = (e) => {
    // Si fue touchstart, prevenimos el click fantasma posterior de 300ms
    if (e.type === 'touchstart') {
      e.preventDefault();
    }

    // 1. Desbloqueo silencioso inmediato del motor de audio (Web Audio API + HTML5 Audio)
    unlockAudio();

    // 2. Control de estado del avatar y SpeechRecognition
    if (isCurrentlySpeaking()) return;

    if (!isListening) {
      dispararSaludo(); // Saludo de bienvenida al tocar el micrófono
      try {
        recognition.start();
      } catch (recErr) {
        console.warn('[ui/controls] Error al iniciar recognition:', recErr);
      }
    } else {
      recognition.stop();
    }
  };

  // Escuchar tanto touchstart como click
  micBtn.addEventListener('touchstart', manejarInteraccionMic, { passive: false });
  micBtn.addEventListener('click', manejarInteraccionMic);
}

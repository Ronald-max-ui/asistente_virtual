/**
 * main.js — Orquestador principal del Asistente Virtual (v4.0 Dual-Mode).
 *
 * Este archivo es intencionalmente delgado: solo configura la escena Three.js,
 * instancia los módulos y los conecta. Toda la lógica específica vive en:
 *
 *   avatar/loader.js   → Carga del modelo VRM
 *   avatar/animator.js → Bucle de animación, huesos, expresiones, lipsync
 *   audio/player.js    → AudioContext singleton, reproducción y cleanup
 *   ui/controls.js     → Micrófono, SpeechRecognition, badges de estado
 *   ui/overlays.js     → Modales web: galería, lead form, pago con QR
 *   api/client.js      → Peticiones al backend con UUID de sesión, modo y retry
 *
 * Modos de operación:
 *   ?mode=kiosk → Kiosk Mode: sin formularios de lead, sin pago inline.
 *                 Modo atracción activo, SpeechRecognition habilitado.
 *   (default)   → Web Mode:  galería, lead form y pago con voucher activos.
 *                 Modo atracción deshabilitado (política de audio en móvil).
 */

import { apiUrl } from './api/config.js';
import { ensureSession } from './api/session.js';
import { applyBranding } from './ui/branding.js';
import { fetchPublicConfig } from './api/publicConfig.js';
import { setInitialized, setAssistantState } from './ui/state.js';
import * as THREE from 'three';
import { loadAvatar, disposeAvatar } from './avatar/loader.js';
import { startAnimation, disposeAnimation } from './avatar/animator.js';
import { initControls, disposeControls } from './ui/controls.js';
import { initOverlays } from './ui/lazyOverlays.js';
import { initPersona } from './ui/persona.js';
import { disposeAudio } from './audio/player.js';
import { cancelarInteraccion, APP_MODE } from './api/client.js';

// ── 1. Escena ─────────────────────────────────────────────────────────────────
const scene = new THREE.Scene();
scene.background = null;  // transparente: deja ver el aura (#lia-aura) detrás del canvas

// ── 2. Cámara ─────────────────────────────────────────────────────────────────
const camera = new THREE.PerspectiveCamera(
  30,
  window.innerWidth / window.innerHeight,
  0.1,
  20.0
);
camera.position.set(0.0, 1.30, 0.95);

// ── 3. Renderer ───────────────────────────────────────────────────────────────
let renderer=null;
try { renderer=new THREE.WebGLRenderer({antialias:true,alpha:true}); } catch (_) { console.warn('[main] Render no disponible.'); }
if(renderer) {
renderer.setClearColor(0x000000, 0);   // fondo transparente → se ve #lia-aura detrás
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.domElement.id = 'canvas3d';
document.body.appendChild(renderer.domElement);
}

// ── 4. Iluminación ────────────────────────────────────────────────────────────
const directionalLight = new THREE.DirectionalLight(0xffffff, 1.4);
directionalLight.position.set(1.0, 2.0, 1.0).normalize();
scene.add(directionalLight);
scene.add(new THREE.AmbientLight(0xffffff, 0.7));

// ── 5. Módulos ────────────────────────────────────────────────────────────────
console.log(`[main] Iniciando en modo: ${APP_MODE}`);

initPersona(APP_MODE);           // Aura lumínica + switch Consulta/Vendedora
initOverlays(APP_MODE);          // Prepara el modo; los modales se cargan cuando se solicitan
async function initializeConversation() {
  setInitialized(false);
  const retry=document.getElementById('retry-start');retry.hidden=true;
  try {
    const [config]=await Promise.all([fetchPublicConfig(),ensureSession()]);
    applyBranding(config);
    initControls(APP_MODE);setInitialized(true);
  } catch (_) {
    console.warn('[main] Arranque de conversación no completado.');
    setAssistantState('error');retry.hidden=false;
  }
}
document.getElementById('retry-start').addEventListener('click',()=>void initializeConversation());
initControls(APP_MODE); // Offline and unsupported-voice feedback works even during bootstrap.
void initializeConversation();
if(renderer) {
  void loadAvatar(scene).then(ok=>{if(!ok) document.getElementById('capability-notice').textContent='El avatar no está disponible. Puedes continuar conversando.';});
  startAnimation(renderer,scene,camera,APP_MODE);
} else document.getElementById('capability-notice').textContent='El avatar no está disponible. Puedes continuar conversando.';

// Captions stay above controls as text/error/stop controls change height.
const controlsBox=document.getElementById('ui-container');
function positionCaptions() {
  const subtitles=document.getElementById('subtitles');
  subtitles.style.bottom=Math.max(105,window.innerHeight-controlsBox.getBoundingClientRect().top+16)+'px';
}
const controlsObserver=typeof ResizeObserver==='function'?new ResizeObserver(positionCaptions):null;
controlsObserver?.observe(controlsBox);positionCaptions();

// ── 6. Responsive ─────────────────────────────────────────────────────────────
function resizeScene() {
  positionCaptions();
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer?.setSize(window.innerWidth, window.innerHeight);
}
window.addEventListener('resize', resizeScene);
window.addEventListener('pagehide', (event) => {
  void cancelarInteraccion(); // Navigation invalidates the turn, including BFCache.
  if (event.persisted) return; // Preserve the scene, not a pending conversation.
  controlsObserver?.disconnect();
  disposeControls(); disposeAnimation();
  disposeAvatar(); void disposeAudio(); renderer?.dispose();
  window.removeEventListener('resize', resizeScene);
});
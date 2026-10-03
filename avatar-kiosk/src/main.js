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

import * as THREE from 'three';
import { loadAvatar } from './avatar/loader.js';
import { startAnimation } from './avatar/animator.js';
import { initControls } from './ui/controls.js';
import { initOverlays } from './ui/overlays.js';
import { APP_MODE } from './api/client.js';

// ── 1. Escena ─────────────────────────────────────────────────────────────────
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x000000);

// ── 2. Cámara ─────────────────────────────────────────────────────────────────
const camera = new THREE.PerspectiveCamera(
  30,
  window.innerWidth / window.innerHeight,
  0.1,
  20.0
);
camera.position.set(0.0, 1.30, 0.95);

// ── 3. Renderer ───────────────────────────────────────────────────────────────
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
document.body.appendChild(renderer.domElement);

// ── 4. Iluminación ────────────────────────────────────────────────────────────
const directionalLight = new THREE.DirectionalLight(0xffffff, 1.4);
directionalLight.position.set(1.0, 2.0, 1.0).normalize();
scene.add(directionalLight);
scene.add(new THREE.AmbientLight(0xffffff, 0.7));

// ── 5. Módulos ────────────────────────────────────────────────────────────────
console.log(`[main] Iniciando en modo: ${APP_MODE}`);

initOverlays(APP_MODE);          // Monta overlays (no-op en modo kiosk)
loadAvatar(scene);               // Carga el VRM de forma asíncrona
initControls(APP_MODE);          // Inicializa micrófono y UI (pasa el modo)
startAnimation(renderer, scene, camera, APP_MODE); // Arranca bucle de render

// ── 6. Responsive ─────────────────────────────────────────────────────────────
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});
/**
 * avatar/animator.js — Sistema de animación orgánica v2 para kiosco comercial.
 *
 * MEJORAS respecto al prototipo:
 *  1. PARPADEO ASIMÉTRICO  — cierre rápido (50ms) + apertura lenta (150ms)
 *                            + doble parpadeo (15% probabilidad).
 *  2. RESPIRACIÓN DUAL-SINE — superposición de dos frecuencias para romper
 *                            la perfección robótica. Involucra spine, chest
 *                            y brazo izquierdo.
 *  3. SACADAS OCULARES     — micro-movimientos aleatorios de cuello/cabeza
 *                            cada 2-4s. Se desactivan al hablar/escuchar.
 *  4. MODO ATRACCIÓN v2    — nueva máquina CURIOUS → ATTRACT_FORWARD sin
 *                            salir de pantalla. Transiciones con damp().
 *  5. MICRO-EXPRESIÓN IDLE — sonrisa sutil baseline (happy = 0.12) siempre
 *                            visible en reposo para que el avatar nunca luzca
 *                            inexpresivo.
 *
 * API pública SIN CAMBIOS: dispararSaludo(), setIsListening(),
 *                          registrarActividad(), startAnimation().
 */

import * as THREE from 'three';
import { createRenderLoop } from './renderLoop.js';
import { getCurrentVrm } from './loader.js';
import { isCurrentlySpeaking, getAnalyser, playAudio, stopCurrentAudio } from '../audio/player.js';

// ═══════════════════════════════════════════════════════════════════════════════
// CONSTANTES DE CONFIGURACIÓN
// ═══════════════════════════════════════════════════════════════════════════════

/** Tiempo de inactividad (ms) antes de activar el modo atracción (25 segundos). */
const INACTIVITY_TIMEOUT_MS  = 25000;

/** Duración del cierre de párpado — rápido como un parpadeo humano real. */
const BLINK_CLOSE_TIME       = 0.05;   // 50ms
/** Duración de la apertura de párpado — lenta y suave. */
const BLINK_OPEN_TIME        = 0.15;   // 150ms
/** Probabilidad de un segundo parpadeo inmediato tras el primero. */
const BLINK_DOUBLE_CHANCE    = 0.15;   // 15%
/** Retardo entre el primer y segundo parpadeo en un doble parpadeo. */
const BLINK_DOUBLE_DELAY     = 0.22;   // 220ms

/** Rango mínimo/máximo de intervalos entre sacadas oculares (segundos). */
const SACCADE_MIN_INTERVAL   = 2.0;
const SACCADE_MAX_INTERVAL   = 4.0;
/** Rango de desplazamiento aleatorio para sacadas (radianes). */
const SACCADE_NECK_RANGE     = 0.08;   // ≈ ±4.6°
const SACCADE_HEAD_RANGE     = 0.04;   // ±2.3°

const AUDIOS_FIJOS = ['/atraccion_1.mp3', '/atraccion_2.mp3', '/atraccion_3.mp3'];

// ═══════════════════════════════════════════════════════════════════════════════
// ESTADO GLOBAL DEL MÓDULO
// ═══════════════════════════════════════════════════════════════════════════════

// ── Saludo ─────────────────────────────────────────────────────────────────────
let isWaving  = false;
let waveTimer = 0;

// ── Escucha activa y procesamiento de respuesta ────────────────────────────────
let isListening = false;
let isProcessingResponse = false;
let attractionAudioEnabled = false;

// ── Máquina de estados de atracción ───────────────────────────────────────────
// Estados: 'NORMAL' | 'CURIOUS' | 'ATTRACT_FORWARD' | 'SPEAKING_ATTRACT' | 'RETURNING'
let animState           = 'NORMAL';
let stateTimer          = 0;
let lastInteractionTime = Date.now();

// ── Targets de posición/rotación global del avatar ────────────────────────────
const targetPos = new THREE.Vector3(0, 0, 0);

// ── Targets unificados de gaze (cuello + cabeza) ──────────────────────────────
let targetNeckY = 0;   // Rotación Y del cuello   — mirada lateral
let targetHeadX = 0;   // Rotación X de la cabeza — arriba/abajo
let targetHeadZ = 0;   // Rotación Z de la cabeza — tilt lateral

// ── Lipsync ────────────────────────────────────────────────────────────────────
let targetMouthOpen  = 0;
let currentMouthOpen = 0;

// ── Sistema de parpadeo asimétrico ────────────────────────────────────────────
let blinkPhase         = 'NONE';  // 'NONE' | 'CLOSING' | 'OPENING'
let blinkPhaseTimer    = 0;
let blinkIntervalTimer = 0;
let blinkInterval      = 2.5 + Math.random() * 3.0;  // Intervalo hasta el primer parpadeo
let pendingDoubleBlink = false;

// ── Sistema de sacadas oculares ────────────────────────────────────────────────
let saccadeOffsetY  = 0;
let saccadeOffsetX  = 0;
let saccadeTimer    = 0;
let nextSaccadeTime = SACCADE_MIN_INTERVAL + Math.random() * (SACCADE_MAX_INTERVAL - SACCADE_MIN_INTERVAL);

// ═══════════════════════════════════════════════════════════════════════════════
// API PÚBLICA — Idéntica al prototipo
// ═══════════════════════════════════════════════════════════════════════════════

/** Activa la animación de saludo con la mano (2.8 segundos). */
export function dispararSaludo() {
  isWaving  = true;
  waveTimer = 0;
}

/** Informa al animator si el micrófono está escuchando activamente. */
export function setIsListening(val) {
  isListening = val;
  if (val) {
    registrarActividad();
  }
}

/** Informa al animator si el sistema está procesando una consulta. */
export function setIsProcessingResponse(val) {
  isProcessingResponse = val;
  if (val) {
    registrarActividad();
  }
}

/**
 * Registra actividad del usuario: resetea el temporizador de inactividad,
 * detiene audios de atracción si estaban sonando y vuelve suavemente
 * al estado NORMAL si el avatar estaba en atracción.
 */
export function registrarActividad() {
  lastInteractionTime = Date.now();
  if (animState !== 'NORMAL') {
    if (animState === 'SPEAKING_ATTRACT') {
      stopCurrentAudio();
    }
    animState  = 'NORMAL';
    stateTimer = 0;
    targetPos.set(0, 0, 0);
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SISTEMAS PRIVADOS DE ANIMACIÓN
// Cada sistema es una función pura que recibe los parámetros necesarios.
// Sin closures que acumulen estado implícito; todo el estado está arriba.
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * SISTEMA 1 — Parpadeo asimétrico humano.
 *
 * Fase CLOSING (50ms):  párpado sube de 0→1 rápidamente.
 * Fase OPENING (150ms): párpado baja de 1→0 lentamente (más natural).
 * 15% de probabilidad de doble parpadeo programado 220ms después.
 */
function _updateBlink(delta, expressionManager) {
  if (!expressionManager) return;

  blinkIntervalTimer += delta;

  // Disparar nuevo parpadeo al cumplirse el intervalo
  if (blinkPhase === 'NONE' && blinkIntervalTimer >= blinkInterval) {
    blinkIntervalTimer = 0;
    blinkInterval      = 2.5 + Math.random() * 3.0;  // Nuevo intervalo: 2.5–5.5s
    blinkPhase         = 'CLOSING';
    blinkPhaseTimer    = 0;

    // Programar doble parpadeo (15% de probabilidad)
    if (!pendingDoubleBlink && Math.random() < BLINK_DOUBLE_CHANCE) {
      pendingDoubleBlink = true;
    }
  }

  // ── Fase de cierre rápido ──────────────────────────────────────────────────
  if (blinkPhase === 'CLOSING') {
    blinkPhaseTimer += delta;
    const t = Math.min(blinkPhaseTimer / BLINK_CLOSE_TIME, 1.0);
    expressionManager.setValue('blink', t);
    if (t >= 1.0) {
      blinkPhase      = 'OPENING';
      blinkPhaseTimer = 0;
    }

  // ── Fase de apertura lenta ─────────────────────────────────────────────────
  } else if (blinkPhase === 'OPENING') {
    blinkPhaseTimer += delta;
    const t = Math.min(blinkPhaseTimer / BLINK_OPEN_TIME, 1.0);
    expressionManager.setValue('blink', 1.0 - t);
    if (t >= 1.0) {
      expressionManager.setValue('blink', 0.0);
      blinkPhase      = 'NONE';
      blinkPhaseTimer = 0;

      // Si había un doble parpadeo pendiente, programar el segundo en 220ms
      if (pendingDoubleBlink) {
        pendingDoubleBlink = false;
        blinkInterval      = BLINK_DOUBLE_DELAY;
        blinkIntervalTimer = 0;
      }
    }
  }
}

/**
 * SISTEMA 2 — Respiración procedural asimétrica (dual-sine).
 *
 * Superpone dos frecuencias para evitar la perfecta regularidad mecánica:
 *   breath1 = sin(t × 1.65) × 0.020  →  ciclo principal ≈3.8s
 *   breath2 = sin(t × 0.86) × 0.008  →  variación lenta ≈7.3s
 *
 * Afecta: spine (inclinación principal), chest (elevación de pecho),
 *         leftUpperArm (movimiento de hombro izquierdo sincronizado).
 */
function _updateBreathing(elapsedTime, humanoid) {
  if (!humanoid) return;

  const breath1     = Math.sin(elapsedTime * 1.65) * 0.020;
  const breath2     = Math.sin(elapsedTime * 0.86) * 0.008;
  const breathTotal = breath1 + breath2;

  // Columna vertebral: inclinación frontal + leve roll asimétrico
  const spine = humanoid.getNormalizedBoneNode('spine');
  if (spine) {
    spine.rotation.x = breathTotal;
    spine.rotation.z = Math.sin(elapsedTime * 1.65 + 0.5) * 0.004;  // Roll sutil
  }

  // Pecho: elevación con leve retardo de fase respecto a spine
  const chest = humanoid.getNormalizedBoneNode('chest');
  if (chest) {
    chest.rotation.x = breath1 * 0.6;  // Retardo de fase implícito por amplitud menor
  }

  // Hombro izquierdo: sube y baja sincronizado con la respiración
  const leftUpperArm = humanoid.getNormalizedBoneNode('leftUpperArm');
  if (leftUpperArm) {
    // Postura base (-1.25 rad = brazo al costado) + oscilación de respiración
    leftUpperArm.rotation.z = -1.25 + breath1 * 0.85;
  }
}

/**
 * SISTEMA 3 — Sacadas oculares (Eye Saccades).
 *
 * Genera nuevos targets aleatorios de mirada cada 2-4 segundos.
 * Solo actualiza los offsets cuando el avatar no está hablando, escuchando,
 * o en modo atracción. La aplicación suave ocurre en _updateGaze() via damp().
 */
function _updateSaccades(delta, isSpeaking) {
  if (isSpeaking || isListening || animState !== 'NORMAL') return;

  saccadeTimer += delta;
  if (saccadeTimer >= nextSaccadeTime) {
    saccadeTimer    = 0;
    nextSaccadeTime = SACCADE_MIN_INTERVAL + Math.random() * (SACCADE_MAX_INTERVAL - SACCADE_MIN_INTERVAL);
    // Nueva posición de mirada: desplazamiento aleatorio centrado
    saccadeOffsetY  = (Math.random() - 0.5) * SACCADE_NECK_RANGE;
    saccadeOffsetX  = (Math.random() - 0.5) * SACCADE_HEAD_RANGE;
  }
}

/**
 * SISTEMA 4 — Gaze unificado (cuello + cabeza).
 *
 * Calcula los targets de rotación según el estado activo y los aplica
 * SIEMPRE con damp() para garantizar transiciones suaves entre estados.
 *
 * En NORMAL: base senoidal lenta + offsets de sacada aleatoria.
 * En otros:  targets fijos determinados por el estado de atracción.
 */
function _updateGaze(delta, elapsedTime, humanoid) {
  if (!humanoid) return;

  const neck = humanoid.getNormalizedBoneNode('neck');
  const head = humanoid.getNormalizedBoneNode('head');
  if (!neck || !head) return;

  // ── Calcular targets según estado ─────────────────────────────────────────
  switch (animState) {

    case 'NORMAL':
      // Movimiento idle: ondas senoidales de baja frecuencia + sacadas aleatorias
      targetNeckY = Math.sin(elapsedTime * 0.70) * 0.030 + saccadeOffsetY;
      targetHeadX = Math.cos(elapsedTime * 0.50) * 0.015 + saccadeOffsetX;
      targetHeadZ = 0.0;
      break;

    case 'CURIOUS':
      // Mira curiosamente hacia la derecha, cabeza inclinada
      targetNeckY =  0.18;   //  ≈10° a la derecha
      targetHeadX =  0.04;   //  Ligero tilt hacia arriba
      targetHeadZ = -0.20;   // -11° de inclinación lateral
      break;

    case 'ATTRACT_FORWARD':
      // Mira directamente a la cámara / espectador con cabeza inclinada amistosamente
      targetNeckY =  0.0;
      targetHeadX = -0.04;   // Ligero lean hacia adelante/cámara
      targetHeadZ = -0.25;   // -14° tilt — gesto de invitación
      break;

    case 'SPEAKING_ATTRACT':
      // Mantiene orientación hacia la cámara mientras habla
      targetNeckY =  0.0;
      targetHeadX =  0.0;
      targetHeadZ = -0.18;
      break;

    default:
      // RETURNING y cualquier otro: volver suavemente al neutro
      targetNeckY = 0.0;
      targetHeadX = 0.0;
      targetHeadZ = 0.0;
      break;
  }

  // ── Aplicar con damp — factor más alto en NORMAL para sacadas ágiles ───────
  const dampSpeed = animState === 'NORMAL' ? 6.0 : 3.5;
  neck.rotation.y = THREE.MathUtils.damp(neck.rotation.y, targetNeckY, dampSpeed, delta);
  head.rotation.x = THREE.MathUtils.damp(head.rotation.x, targetHeadX, dampSpeed, delta);
  head.rotation.z = THREE.MathUtils.damp(head.rotation.z, targetHeadZ, dampSpeed, delta);
}

/**
 * SISTEMA 5 — Micro-expresiones (expresión 'happy').
 *
 * Baseline de 0.12 en reposo: el avatar nunca tiene cara completamente neutra.
 * Sube gradualmente según el nivel de actividad/atracción del estado actual.
 * No interfiere con el lipsync (blendshape 'aa' es independiente).
 */
function _updateExpressions(delta, vrm, isSpeaking) {
  if (!vrm.expressionManager) return;

  let happyTarget;
  if      (isSpeaking || isWaving)              happyTarget = 0.40;  // Habla / saluda
  else if (animState === 'ATTRACT_FORWARD')      happyTarget = 0.50;  // Invitando abiertamente
  else if (animState === 'SPEAKING_ATTRACT')     happyTarget = 0.45;  // Hablando en modo atracción
  else if (animState === 'CURIOUS')              happyTarget = 0.25;  // Curiosa, sonrisa leve
  else                                           happyTarget = 0.12;  // IDLE baseline sutil

  const currentHappy = vrm.expressionManager.getValue('happy') ?? 0;
  vrm.expressionManager.setValue(
    'happy',
    THREE.MathUtils.damp(currentHappy, happyTarget, 4.0, delta)
  );
}

/**
 * SISTEMA 6 — Animación de saludo (brazo derecho).
 *
 * Sin cambios de lógica respecto al prototipo.
 * Separado en función propia para legibilidad del loop principal.
 */
function _updateWave(delta, humanoid) {
  if (!humanoid) return;

  const rightUpperArm = humanoid.getNormalizedBoneNode('rightUpperArm');
  const rightLowerArm = humanoid.getNormalizedBoneNode('rightLowerArm');
  const rightHand     = humanoid.getNormalizedBoneNode('rightHand');

  if (isWaving) {
    waveTimer += delta;

    // Brazo superior: codo cerca del cuerpo, orientado al frente
    if (rightUpperArm) {
      rightUpperArm.rotation.x = THREE.MathUtils.damp(rightUpperArm.rotation.x, -0.65, 6.0, delta);
      rightUpperArm.rotation.y = THREE.MathUtils.damp(rightUpperArm.rotation.y,  0.35, 6.0, delta);
      rightUpperArm.rotation.z = THREE.MathUtils.damp(rightUpperArm.rotation.z,  0.85, 6.0, delta);
    }
    // Antebrazo: codo doblado hacia arriba
    if (rightLowerArm) {
      rightLowerArm.rotation.x = THREE.MathUtils.damp(rightLowerArm.rotation.x, -0.20, 6.0, delta);
      rightLowerArm.rotation.y = THREE.MathUtils.damp(rightLowerArm.rotation.y,  1.35, 6.0, delta);
      rightLowerArm.rotation.z = THREE.MathUtils.damp(rightLowerArm.rotation.z, -0.25, 6.0, delta);
    }
    // Mano: agita de lado a lado con ritmo cadencioso
    if (rightHand) {
      rightHand.rotation.x = 0.1;
      rightHand.rotation.z = Math.sin(waveTimer * 8.0) * 0.28;
    }

    if (waveTimer > 2.8) isWaving = false;

  } else {
    // Regreso suave a postura de reposo (brazo al costado)
    if (rightUpperArm) {
      rightUpperArm.rotation.x = THREE.MathUtils.damp(rightUpperArm.rotation.x, 0.0,  4.0, delta);
      rightUpperArm.rotation.y = THREE.MathUtils.damp(rightUpperArm.rotation.y, 0.0,  4.0, delta);
      rightUpperArm.rotation.z = THREE.MathUtils.damp(rightUpperArm.rotation.z, 1.25, 4.0, delta);
    }
    if (rightLowerArm) {
      rightLowerArm.rotation.x = THREE.MathUtils.damp(rightLowerArm.rotation.x, 0.0, 4.0, delta);
      rightLowerArm.rotation.y = THREE.MathUtils.damp(rightLowerArm.rotation.y, 0.0, 4.0, delta);
      rightLowerArm.rotation.z = THREE.MathUtils.damp(rightLowerArm.rotation.z, 0.0, 4.0, delta);
    }
    if (rightHand) {
      rightHand.rotation.z = THREE.MathUtils.damp(rightHand.rotation.z, 0.0, 4.0, delta);
      rightHand.rotation.x = THREE.MathUtils.damp(rightHand.rotation.x, 0.0, 4.0, delta);
    }
  }
}

/**
 * SISTEMA 7 — Lipsync (sin cambios respecto al prototipo).
 *
 * Lee frecuencias del analyser del AudioContext para mover la boca ('aa').
 * Se ejecuta siempre; cuando no hay audio, targetMouthOpen = 0 y la boca
 * cierra suavemente via damp().
 */
function _updateLipsync(delta, elapsedTime, vrm, isSpeaking) {
  if (!vrm.expressionManager) return;

  const { analyser, dataArray } = getAnalyser();
  if (isSpeaking && analyser && dataArray) {
    analyser.getByteFrequencyData(dataArray);
    let sum = 0;
    for (let i = 2; i < 20; i++) sum += dataArray[i];
    const volume = sum / 18 / 255;

    if (volume > 0.08) {
      const ritmoSilabas = (Math.sin(elapsedTime * 22) + 1.2) * 0.5;
      targetMouthOpen = Math.min(1.0, volume * ritmoSilabas * 2.8);
    } else {
      targetMouthOpen = 0.0;
    }
  } else {
    targetMouthOpen = 0.0;
  }

  currentMouthOpen = THREE.MathUtils.damp(currentMouthOpen, targetMouthOpen, 18.0, delta);
  vrm.expressionManager.setValue('aa', currentMouthOpen);
}

/**
 * MÁQUINA DE ESTADOS DE ATRACCIÓN v2.
 *
 * NORMAL ──(20s inactividad)──► CURIOUS ──(3s)──► ATTRACT_FORWARD
 *   ▲                                                     │(2.5s)
 *   │                                                     ▼
 *   └──────(2.2s)── RETURNING ◄──(fin audio)── SPEAKING_ATTRACT
 *
 * Cancelación: registrarActividad() desde cualquier estado → NORMAL instantáneo.
 *
 * FIX vs. prototipo: el callback del audio verifica que aún estamos en
 * SPEAKING_ATTRACT antes de hacer la transición, para manejar correctamente
 * el caso en que el usuario interactúe durante la reproducción del audio.
 */
function _updateAttractionStateMachine(delta, isSpeaking) {

  // Si hay alguna actividad en curso (audio reproduciéndose, usuario hablando o backend procesando),
  // mantener fresco el temporizador de inactividad para que el contador de 25s empiece
  // exactamente cuando reine el silencio absoluto.
  if (isSpeaking || isListening || isProcessingResponse) {
    lastInteractionTime = Date.now();
    return;
  }

  // Trigger: solo desde NORMAL y cuando no hay actividad alguna
  if (animState === 'NORMAL') {
    if (Date.now() - lastInteractionTime > INACTIVITY_TIMEOUT_MS) {
      animState  = 'CURIOUS';
      stateTimer = 0;
    }
    return;  // En NORMAL sin trigger, nada más que hacer
  }

  if (animState === 'NORMAL') return;

  stateTimer += delta;

  switch (animState) {

    case 'CURIOUS':
      // Mira con curiosidad durante 3s, luego avanza hacia la cámara
      if (stateTimer > 3.0) {
        animState  = 'ATTRACT_FORWARD';
        stateTimer = 0;
        targetPos.set(0, 0, 0.06);  // Avance sutil de 6cm hacia la cámara
      }
      break;

    case 'ATTRACT_FORWARD':
      // Inclinada hacia cámara durante 2.5s, luego saludo + audio (solo en kiosk)
      if (stateTimer > 2.5) {
        animState  = 'SPEAKING_ATTRACT';
        stateTimer = 0;
        dispararSaludo();

        if (attractionAudioEnabled) {
          const audioElegido = AUDIOS_FIJOS[Math.floor(Math.random() * AUDIOS_FIJOS.length)];
          playAudio(audioElegido, () => {
            // FIX: verificar estado antes de transicionar; el usuario pudo
            // haber interactuado durante la reproducción del audio.
            if (animState === 'SPEAKING_ATTRACT') {
              animState  = 'RETURNING';
              stateTimer = 0;
              targetPos.set(0, 0, 0);  // Volver al centro
            }
          });
        } else {
          // Modo web: sin audio, transición directa tras la animación de saludo
          attractionTimer = setTimeout(() => {
            attractionTimer = null;
            if (animState === 'SPEAKING_ATTRACT') {
              animState  = 'RETURNING';
              stateTimer = 0;
              targetPos.set(0, 0, 0);
            }
          }, 2500);
        }
      }
      break;


    case 'SPEAKING_ATTRACT':
      // La transición la gestiona el callback del audio; aquí solo se espera.
      break;

    case 'RETURNING':
      // Esperar 2.2s para que los dampers alcancen la posición neutral
      if (stateTimer > 2.2) {
        animState           = 'NORMAL';
        stateTimer          = 0;
        lastInteractionTime = Date.now();  // Evitar re-trigger inmediato
      }
      break;
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// BUCLE PRINCIPAL
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Inicia el bucle de animación. Llamar UNA SOLA VEZ desde main.js.
 *
 * El orden de llamada a los sistemas importa:
 *   1. Estado → define los targets que usan los sistemas siguientes.
 *   2. Sacadas → actualiza offsets que usa el Gaze.
 *   3. Posición global → desplazamiento del avatar completo.
 *   4. Respiración → movimiento de torso y brazo izquierdo.
 *   5. Gaze → cuello y cabeza (usa targets del estado + offsets de sacadas).
 *   6. Saludo → brazo derecho.
 *   7. Expresiones → 'happy' blendshape.
 *   8. Parpadeo → 'blink' blendshape.
 *   9. Lipsync → 'aa' blendshape (canal de audio, NO interferir).
 *  10. vrm.update() → física de pelo y ropa.
 *
 * @param {THREE.WebGLRenderer} renderer
 * @param {THREE.Scene}         scene
 * @param {THREE.Camera}        camera
 */
export function startAnimation(renderer, scene, camera, mode = 'web') {
  // En modo web no reproducimos audios de atracción (política autoplay móvil)
  attractionAudioEnabled = (mode === 'kiosk');
  stopAnimation?.();
  function animate(delta, elapsedTime) {
    const isSpeaking  = isCurrentlySpeaking();

    // 1. Máquina de estados (define animState y targets de posición)
    _updateAttractionStateMachine(delta, isSpeaking);

    // 2. Sacadas (actualiza saccadeOffsetY/X para el Gaze)
    _updateSaccades(delta, isSpeaking);

    const vrm = getCurrentVrm();
    if (!vrm) {
      renderer.render(scene, camera);
      return;
    }

    // 3. Posición global del avatar (damp suave hacia target)
    vrm.scene.position.x = THREE.MathUtils.damp(vrm.scene.position.x, targetPos.x, 3.5, delta);
    vrm.scene.position.y = THREE.MathUtils.damp(vrm.scene.position.y, targetPos.y, 3.5, delta);
    vrm.scene.position.z = THREE.MathUtils.damp(vrm.scene.position.z, targetPos.z, 3.5, delta);
    vrm.scene.rotation.y = THREE.MathUtils.damp(vrm.scene.rotation.y, 0.0, 4.0, delta);

    // 4. Respiración procedural (spine, chest, leftUpperArm)
    _updateBreathing(elapsedTime, vrm.humanoid);

    // 5. Gaze unificado (neck.y, head.x, head.z — con sacadas en NORMAL)
    _updateGaze(delta, elapsedTime, vrm.humanoid);

    // 6. Saludo — brazo derecho
    _updateWave(delta, vrm.humanoid);

    // 7. Micro-expresiones (happy: baseline 0.12 → máx 0.50 según estado)
    _updateExpressions(delta, vrm, isSpeaking);

    // 8. Parpadeo asimétrico (cierre 50ms / apertura 150ms)
    _updateBlink(delta, vrm.expressionManager);

    // 9. Lipsync — canal de audio independiente (NO modificar)
    _updateLipsync(delta, elapsedTime, vrm, isSpeaking);

    // 10. Actualización VRM (activa física de pelo y ropa)
    vrm.update(delta);

    renderer.render(scene, camera);
  }

  stopAnimation = createRenderLoop(animate);
  return stopAnimation;
}
let stopAnimation = null;
let attractionTimer = null;
export function disposeAnimation() {
  stopAnimation?.(); stopAnimation = null;
  if (attractionTimer !== null) clearTimeout(attractionTimer);
  attractionTimer = null;
}

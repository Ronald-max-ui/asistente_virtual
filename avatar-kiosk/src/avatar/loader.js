/**
 * avatar/loader.js — Carga del modelo VRM y postura inicial.
 *
 * Responsabilidades:
 *  - Registrar el plugin VRM en GLTFLoader.
 *  - Consultar el avatar seleccionado en backend y añadirlo a la escena.
 *  - Aplicar la postura inicial (brazos descansando).
 *  - Exponer getCurrentVrm() para que otros módulos accedan al modelo.
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import { fetchAvatarUrl } from '../api/publicConfig.js';

let currentVrm = null;
let loadGeneration = 0;

/** Devuelve la instancia VRM activa, o null si aún no cargó. */
export function getCurrentVrm() {
  return currentVrm;
}

/**
 * Inicia la carga del modelo VRM y lo añade a la escena.
 * La carga es asíncrona; getCurrentVrm() devuelve null hasta que finalice.
 *
 * @param {THREE.Scene} scene - La escena Three.js donde añadir el avatar.
 */
export async function loadAvatar(scene) {
  const generation = ++loadGeneration;
  const perf = globalThis.performance;
  for (const name of ['lia-avatar-start','lia-avatar-load-start','lia-avatar-parsed','lia-avatar-ready','lia-avatar-config','lia-avatar-download-parse','lia-avatar-scene-setup']) {
    perf?.clearMarks?.(name); perf?.clearMeasures?.(name);
  }
  perf?.mark?.('lia-avatar-start');
  let candidate=null;
  try {
    const url = await fetchAvatarUrl();
    if (generation !== loadGeneration) return;
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));

    perf?.mark?.('lia-avatar-load-start');
    perf?.measure?.('lia-avatar-config', 'lia-avatar-start', 'lia-avatar-load-start');
    const gltf = await loader.loadAsync(url);
    candidate=gltf.scene;
    if (generation !== loadGeneration) { VRMUtils.deepDispose(gltf.scene); return; }
    perf?.mark?.('lia-avatar-parsed');
    perf?.measure?.('lia-avatar-download-parse', 'lia-avatar-load-start', 'lia-avatar-parsed');
    const vrm = gltf.userData.vrm;
    if (!vrm) throw new Error('El archivo seleccionado no contiene un avatar VRM.');

    // Optimizaciones de geometría recomendadas por three-vrm
    VRMUtils.removeUnnecessaryVertices(gltf.scene);
    VRMUtils.removeUnnecessaryJoints(gltf.scene);

    if (currentVrm) disposeCurrentAvatar();
    scene.add(vrm.scene);
    currentVrm = vrm;

    // Postura inicial natural: brazos descansando a los costados
    const humanoid = vrm.humanoid;
    if (humanoid) {
      const leftArm = humanoid.getNormalizedBoneNode('leftUpperArm');
      const rightArm = humanoid.getNormalizedBoneNode('rightUpperArm');
      if (leftArm) leftArm.rotation.z = -1.25;
      if (rightArm) rightArm.rotation.z = 1.25;
    }

    perf?.mark?.('lia-avatar-ready');
    perf?.measure?.('lia-avatar-scene-setup', 'lia-avatar-parsed', 'lia-avatar-ready');
    candidate=null;
    console.log('[avatar/loader] Modelo VRM cargado correctamente.');
    return true;
  } catch (error) {
    if(candidate) {if(currentVrm?.scene===candidate) disposeCurrentAvatar();else VRMUtils.deepDispose(candidate);}
    console.warn('[avatar/loader] Avatar no disponible; la conversación continúa.');
    return false;
  }
}

export function disposeAvatar() { loadGeneration++; disposeCurrentAvatar(); }
function disposeCurrentAvatar() {
  if (!currentVrm) return;
  currentVrm.scene.parent?.remove(currentVrm.scene);
  VRMUtils.deepDispose(currentVrm.scene);
  currentVrm = null;
}

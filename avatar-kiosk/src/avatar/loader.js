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
  try {
    const url = await fetchAvatarUrl();
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));

    const gltf = await loader.loadAsync(url);
    const vrm = gltf.userData.vrm;
    if (!vrm) throw new Error('El archivo seleccionado no contiene un avatar VRM.');

    // Optimizaciones de geometría recomendadas por three-vrm
    VRMUtils.removeUnnecessaryVertices(gltf.scene);
    VRMUtils.removeUnnecessaryJoints(gltf.scene);

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

    console.log('[avatar/loader] Modelo VRM cargado correctamente.');
  } catch (error) {
    console.warn('[avatar/loader] No se pudo cargar el avatar configurado:', error);
    const badge = document.getElementById('status-badge');
    if (badge) badge.textContent = 'Avatar no disponible';
  }
}

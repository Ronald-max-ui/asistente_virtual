/**
 * avatar/loader.js — Carga del modelo VRM y postura inicial.
 *
 * Responsabilidades:
 *  - Registrar el plugin VRM en GLTFLoader.
 *  - Cargar el modelo /avatar.vrm y añadirlo a la escena.
 *  - Aplicar la postura inicial (brazos descansando).
 *  - Exponer getCurrentVrm() para que otros módulos accedan al modelo.
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

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
export function loadAvatar(scene) {
  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));

  loader.load('/avatar.vrm', (gltf) => {
    const vrm = gltf.userData.vrm;

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
  });
}

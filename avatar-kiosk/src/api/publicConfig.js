import { apiUrl } from './config.js';

/** Sólo assets locales autorizados. El servidor selecciona el avatar vigente. */
export function selectedAvatarUrl(config, resolve = apiUrl) {
  const avatar = config?.avatar;
  if (!avatar || typeof avatar.id !== 'string' || typeof avatar.name !== 'string' ||
      typeof avatar.url !== 'string' || !/^\/static\/avatars\/[a-zA-Z0-9_-]+\.vrm$/.test(avatar.url)) {
    throw new Error('No hay un avatar válido seleccionado en la configuración pública.');
  }
  return resolve(avatar.url);
}

export async function fetchAvatarUrl(fetcher = fetch, resolve = apiUrl) {
  const response = await fetcher(resolve('/api/config'), { cache: 'no-cache' });
  if (!response.ok) throw new Error('No se pudo obtener la configuración del avatar.');
  const url = selectedAvatarUrl(await response.json(), resolve);
  const revision = response.headers?.get('ETag')?.replaceAll('"', '');
  return /^[a-f0-9]{64}$/.test(revision || '') ? `${url}?v=${revision}` : url;
}

let configurationPromise=null;
export function fetchPublicConfig() {
  if(!configurationPromise) configurationPromise=fetch(apiUrl('/api/config'),{cache:'no-cache',signal:AbortSignal.timeout(20000)})
    .then(async response=>{if(!response.ok) throw new Error('Configuración no disponible');
      const config=await response.json();window.__liaPublicConfig=config;return config;})
    .catch(error=>{configurationPromise=null;throw error;});
  return configurationPromise;
}

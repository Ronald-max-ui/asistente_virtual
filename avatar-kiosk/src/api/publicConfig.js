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
  const response = await fetcher(resolve('/api/config'), { cache: 'no-store' });
  if (!response.ok) throw new Error('No se pudo obtener la configuración del avatar.');
  return selectedAvatarUrl(await response.json(), resolve);
}

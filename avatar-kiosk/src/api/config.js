/** Una base para chat, formularios y medios. Producción usa el mismo origen por defecto. */
export function createApiConfig(configured = '', location = window.location) {
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
  const fallback = local ? `${new URL(location.origin).protocol}//${location.hostname}:8000` : location.origin;
  const base = new URL(configured || fallback, location.origin);
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.search || base.hash) {
    throw new Error('VITE_API_URL debe ser una URL HTTP(S) sin credenciales, query ni fragmento.');
  }
  if (location.origin.startsWith('https:') && base.protocol !== 'https:') {
    throw new Error('VITE_API_URL debe usar HTTPS cuando el frontend usa HTTPS.');
  }
  const backendUrl = base.href.replace(/\/$/, '');
  const apiUrl = (path) => `${backendUrl}/${String(path).replace(/^\/+/, '')}`;
  const mediaUrl = (value) => {
    if (typeof value !== 'string' || !value || /[\\\s]/.test(value)) return '';
    try {
      const url = new URL(value, `${backendUrl}/`);
      // Recursos locales del catálogo; nunca scripts, data URLs, rutas externas o traversal.
      const mediaPrefix = `${base.pathname.replace(/\/$/, '')}/static/media/`;
      if (value.startsWith('/static/media/')) {
        if (!/^\/static\/media\/[a-zA-Z0-9_-]+\.(webp|png|jpe?g)$/.test(value)) return '';
        return apiUrl(value);
      }
      if (url.origin !== base.origin || url.username || url.password || url.search || url.hash) return '';
      if (!url.pathname.startsWith(mediaPrefix)) return '';
      const name = url.pathname.slice(mediaPrefix.length);
      return /^[a-zA-Z0-9_-]+\.(webp|png|jpe?g)$/.test(name) ? url.href : '';
    } catch { return ''; }
  };
  return { backendUrl, apiUrl, mediaUrl };
}

const config = createApiConfig(import.meta.env?.VITE_API_URL || '');
export const BACKEND_URL = config.backendUrl;
export const apiUrl = config.apiUrl;
export const resolverMediaUrl = config.mediaUrl;

/** Session credentials stay in this tab. IDs alone never authorize access. */
import { apiUrl } from './config.js';

export let SESSION_ID = sessionStorage.getItem('av_kiosk_session_id') || crypto.randomUUID();
sessionStorage.setItem('av_kiosk_session_id', SESSION_ID);
let sessionToken = sessionStorage.getItem('av_kiosk_session_token');
let bootstrapPromise = null;
let established = false;
const operationKeys = new WeakMap();

export function invalidateSession() {
  established = false;
  sessionToken = null;
  SESSION_ID = crypto.randomUUID();
  sessionStorage.setItem('av_kiosk_session_id', SESSION_ID);
  sessionStorage.setItem('av_kiosk_session_token', '');
}

export async function ensureSession() {
  if (established) return;
  if (bootstrapPromise) return bootstrapPromise;
  bootstrapPromise = (async () => {
    let res = await fetch(apiUrl('/api/session'), {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...(sessionToken ? { 'X-Session-Token': sessionToken } : {}) },
      body: JSON.stringify({ session_id: SESSION_ID }), signal: AbortSignal.timeout(20000),
    });
    if ([401, 409, 410].includes(res.status)) {
      // Expired IDs are never recycled with their old commercial association.
      sessionToken = null;
      SESSION_ID = crypto.randomUUID();
      res = await fetch(apiUrl('/api/session'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: SESSION_ID }), signal: AbortSignal.timeout(20000),
      });
    }
    if (!res.ok) throw new Error('No se pudo iniciar la sesión');
    const data = await res.json();
    if (typeof data.session_token !== 'string' || typeof data.session_id !== 'string') throw new Error('Sesión inválida');
    SESSION_ID = data.session_id;
    sessionToken = data.session_token;
    sessionStorage.setItem('av_kiosk_session_id', SESSION_ID);
    sessionStorage.setItem('av_kiosk_session_token', sessionToken);
    established = true;
  })();
  try { await bootstrapPromise; } finally { bootstrapPromise = null; }
}

export async function sessionHeaders(key) {
  await ensureSession();
  return { 'X-Session-Token': sessionToken, ...(key ? { 'Idempotency-Key': key } : {}) };
}

/** Keep the retry key until fields change or the form is replaced. */
export function formOperationKey(form, data) {
  const signature = JSON.stringify([...data.entries()].map(([key, value]) => [key,
    typeof value === 'string' ? value : [value.name, value.size, value.lastModified]]));
  const previous = operationKeys.get(form);
  if (previous?.signature === signature) return previous.key;
  const key = crypto.randomUUID();
  operationKeys.set(form, { signature, key });
  return key;
}

// Session credential stays in an HttpOnly cookie. CSRF and revisions live only in memory.
export function createAdminClient(fetcher = fetch) {
    let csrf = null;
    const versions = new Map();
    async function request(path, method = 'GET', body, expected, idempotency) {
        const multipart = typeof FormData !== 'undefined' && body instanceof FormData;
        const headers = multipart ? {} : { 'Content-Type': 'application/json' };
        if (method !== 'GET' && path !== '/auth/login') {
            if (!csrf) csrf = (await request('/auth/csrf')).csrf_token;
            headers['X-CSRF-Token'] = csrf;
        }
        if (expected) headers['If-Match'] = expected;
        if(idempotency)headers['Idempotency-Key']=idempotency;
        let response;
        try { response = await fetcher('/api/admin' + path, { method, headers, credentials: 'same-origin', cache: 'no-store', body: body === undefined ? undefined : multipart ? body : JSON.stringify(body) }); }
        catch { throw new Error('No hay conexión. Tus cambios no se han enviado.'); }
        if (!response.ok) {
            if (response.status === 401) csrf = null;
            let payload = {}; try { payload = await response.json(); } catch { /* safe generic fallback */ }
            const messages = {401:'Credenciales incorrectas o sesión vencida.',403:'No tienes permiso para esta operación.',409:'Conflicto de configuración. Revisa los datos.',422:'Revisa los campos del formulario.',429:'Demasiados intentos. Intenta más tarde.'};
            let message = messages[response.status] || 'No se pudo completar la operación.';
            if(payload.code==='lead_changed')message='Este prospecto fue actualizado por otra persona. Recarga antes de guardar.';
            if(payload.code==='lead_transition')message='La transición comercial no está permitida.';
            if(payload.code==='assignee_invalid')message='El responsable no está habilitado para gestionar prospectos.';
            if (payload.code === 'admin_record_changed') message = 'Este registro fue modificado por otro usuario. Recarga antes de guardar.';
            if (typeof payload.message === 'string' && payload.message.startsWith('Tarifas/campañas superpuestas:')) message = 'Ya existe una tarifa o campaña para esta combinación y periodo.';
            if (payload.code === 'weak_password') message = 'La contraseña no cumple la política de seguridad: usa al menos 12 caracteres variados.';
            const error = new Error(message); error.status = response.status; error.code = payload.code; throw error;
        }
        const etag = response.headers?.get('ETag'); if (etag) versions.set(path, etag);
        return response.status === 204 ? null : response.headers?.get('Content-Type')?.startsWith('text/csv') ? response.text() : response.json();
    }
    return { request, revision: path => versions.get(path),
        me: () => request('/auth/me'),
        login: async (username, password) => { csrf = null; versions.clear(); await request('/auth/login', 'POST', { username, password }); return request('/auth/me'); },
        logout: async () => { try { await request('/auth/logout', 'POST'); } finally { csrf = null; versions.clear(); } }
    };
}

/**
 * ui/overlays.js — Componentes de UI overlay para el Modo Web.
 *
 * Gestiona tres modales superpuestos sobre el canvas del avatar:
 *
 *   1. Gallery Modal   → Muestra una foto grande con título y descripción.
 *                        Disparado por evento SSE `ui_action` SHOW_GALLERY.
 *
 *   2. Lead Form Modal → Formulario de contacto (Nombre, WhatsApp, Carrera).
 *                        Disparado por OPEN_LEAD_FORM. Solo en modo web.
 *
 *   3. Payment Modal   → QR Yape + número + monto + subida de voucher.
 *                        Disparado por SHOW_PAYMENT. Solo en modo web.
 *
 * En modo kiosk, este módulo no monta nada y las funciones de apertura
 * son no-ops para que client.js pueda llamarlas sin condicionales.
 */

// URL base del backend
export const BACKEND_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://127.0.0.1:8000'
  : `${window.location.protocol}//${window.location.hostname}:8000`;

/**
 * Resuelve una URL relativa (/static/...) contra la URL base del backend.
 */
export function resolverMediaUrl(urlRelativa) {
  if (!urlRelativa) return '';
  if (urlRelativa.startsWith('http://') || urlRelativa.startsWith('https://')) {
    return urlRelativa;
  }
  const cleanPath = urlRelativa.startsWith('/') ? urlRelativa : `/${urlRelativa}`;
  return `${BACKEND_URL}${cleanPath}`;
}

// ── Estado del modo ────────────────────────────────────────────────────────────
let _mode = 'web';  // Inicializado desde initOverlays()

// ── Contenedor principal ───────────────────────────────────────────────────────
let _container = null;

/**
 * Crea el contenedor de overlays y los inserta en el DOM.
 * Debe llamarse una vez desde main.js después de que el DOM esté listo.
 *
 * @param {string} mode - 'kiosk' | 'web'
 */
export function initOverlays(mode = 'web') {
  _mode = mode;

  // En modo kiosk no montamos overlays pesados
  if (_mode === 'kiosk') return;

  // Evitar duplicar contenedor si ya existía
  let existingContainer = document.getElementById('overlay-container');
  if (existingContainer) {
    _container = existingContainer;
  } else {
    _container = document.createElement('div');
    _container.id = 'overlay-container';
    document.body.appendChild(_container);
  }

  // Inyectar estilos globales de overlays si no están ya presentes
  if (!document.getElementById('overlay-styles')) {
    const style = document.createElement('style');
    style.id = 'overlay-styles';
    style.textContent = _CSS;
    document.head.appendChild(style);
  }
}

// ── API pública ────────────────────────────────────────────────────────────────

/**
 * Abre el modal de galería mostrando una imagen del recurso dado.
 * @param {object} actionPayload - Payload del SSE ui_action (contiene resource)
 */
export function openGallery(actionPayload) {
  if (_mode === 'kiosk') {
    return;
  }
  const resource = actionPayload.resource || {};
  const rawUrl   = resource.url || actionPayload.url || '';
  const imgUrl   = resolverMediaUrl(rawUrl);
  const fallbackUrl = resolverMediaUrl('/static/media/instituto_fachada.webp');
  const titulo   = resource.titulo   || 'Instituto Tuinen Star';
  const desc     = resource.descripcion || '';

  console.warn('[UI_ACTION] Disparando modal de galeria:', { imgUrl, titulo, actionPayload });

  _renderModal('gallery-modal', `
    <div class="ov-modal-inner ov-gallery">
      <button class="ov-close" onclick="window.__ovClose('gallery-modal')">✕</button>
      <img src="${imgUrl}" alt="${titulo}" class="ov-gallery-img"
           onerror="this.onerror=null; this.src='${fallbackUrl}'">
      <div class="ov-gallery-info">
        <h2>${titulo}</h2>
        <p>${desc}</p>
      </div>
    </div>
  `);
}

/**
 * Abre el formulario de captura de lead.
 * @param {object} actionPayload - { carrera: string }
 */
export function openLeadForm(actionPayload) {
  if (_mode === 'kiosk') return;
  const carrera = actionPayload.carrera || '';

  console.log('[OVERLAYS] Abriendo formulario de contacto para:', carrera);

  _renderModal('lead-modal', `
    <div class="ov-modal-inner ov-lead">
      <button class="ov-close" onclick="window.__ovClose('lead-modal')">✕</button>
      <div class="ov-lead-header">
        <span class="ov-lead-icon">🎓</span>
        <h2>¡Reserva tu lugar!</h2>
        <p>Déjanos tus datos y un asesor te contactará por WhatsApp.</p>
      </div>
      <form id="lead-form" onsubmit="window.__submitLead(event)">
        <input type="hidden" name="carrera" value="${carrera}">
        <div class="ov-field">
          <label>Nombre completo *</label>
          <input type="text" name="nombre" required placeholder="Tu nombre" autocomplete="name">
        </div>
        <div class="ov-field">
          <label>WhatsApp *</label>
          <input type="tel" name="whatsapp" required placeholder="9XX XXX XXX" autocomplete="tel">
        </div>
        <div class="ov-field">
          <label>Carrera / Curso de interés</label>
          <input type="text" name="carrera_display" value="${carrera}" placeholder="Ej: Gastronomía">
        </div>
        <div class="ov-field">
          <label>Notas adicionales</label>
          <textarea name="notas" rows="2" placeholder="Horario preferido, consultas..."></textarea>
        </div>
        <button type="submit" class="ov-btn-primary" id="lead-submit-btn">
          Enviar mis datos →
        </button>
        <p id="lead-msg" class="ov-msg"></p>
      </form>
    </div>
  `);
}

/**
 * Abre el modal de pago con QR Yape y subida de voucher.
 * @param {object} actionPayload - { carrera, monto, qr_url, yape_numero }
 */
export function openPayment(actionPayload) {
  if (_mode === 'kiosk') return;
  const carrera     = actionPayload.carrera    || '';
  const monto       = actionPayload.monto      || '';
  const rawQrUrl    = actionPayload.qr_url     || '/static/media/yape_qr.webp';
  const qrUrl       = resolverMediaUrl(rawQrUrl);
  const yapeNumero  = actionPayload.yape_numero || '994 773 335';

  console.log('[OVERLAYS] Abriendo modal de pago con QR:', qrUrl, { carrera, monto });

  _renderModal('payment-modal', `
    <div class="ov-modal-inner ov-payment">
      <button class="ov-close" onclick="window.__ovClose('payment-modal')">✕</button>
      <h2>Paga tu matrícula con Yape</h2>
      <p class="ov-payment-sub">Carrera: <strong>${carrera}</strong> — Monto: <strong>${monto} soles</strong></p>
      <img src="${qrUrl}" alt="QR Yape" class="ov-qr-img"
           onerror="this.style.display='none'">
      <p class="ov-yape-num">📱 Yape al <strong>${yapeNumero}</strong></p>
      <hr class="ov-divider">
      <p class="ov-upload-label">Sube tu voucher aquí para confirmar tu pago:</p>
      <form id="voucher-form" onsubmit="window.__submitVoucher(event, '${carrera}', '${monto}')">
        <input type="file" name="imagen" accept="image/*" required class="ov-file-input" id="voucher-file">
        <button type="submit" class="ov-btn-primary" id="voucher-submit-btn">
          Enviar comprobante ✓
        </button>
        <p id="voucher-msg" class="ov-msg"></p>
      </form>
    </div>
  `);
}

// ── Helpers internos ───────────────────────────────────────────────────────────

function _renderModal(id, html) {
  if (!_container || !document.body.contains(_container)) {
    initOverlays(_mode);
  }
  if (!_container) return;

  // Garantizar que esté en el body
  if (!document.body.contains(_container)) {
    document.body.appendChild(_container);
  }

  // Cerrar cualquier modal previo del mismo id si existe
  const prev = document.getElementById(id);
  if (prev) prev.remove();

  const backdrop = document.createElement('div');
  backdrop.id = id;
  backdrop.className = 'ov-backdrop';
  backdrop.innerHTML = html;

  // Cerrar al hacer click en el backdrop (fuera del inner)
  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) _closeModal(id);
  });

  _container.appendChild(backdrop);

  // Forzar reflow y animar entrada
  void backdrop.offsetWidth;
  backdrop.classList.add('ov-visible');
}

function _closeModal(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('ov-visible');
  el.addEventListener('transitionend', () => el.remove(), { once: true });
  // Fallback si transitionend no se dispara
  setTimeout(() => { if (el.parentElement) el.remove(); }, 300);
}

// ── Callbacks globales (llamados desde HTML inline) ───────────────────────────
window.__ovClose = _closeModal;

window.__submitLead = async function (e) {
  e.preventDefault();
  const form   = e.target;
  const btn    = document.getElementById('lead-submit-btn');
  const msg    = document.getElementById('lead-msg');
  const data   = new FormData(form);

  const carreraDisplay = data.get('carrera_display');
  if (carreraDisplay) data.set('carrera', carreraDisplay);
  data.delete('carrera_display');

  btn.disabled = true;
  btn.textContent = 'Enviando...';

  try {
    const res = await fetch(`${BACKEND_URL}/api/leads`, { method: 'POST', body: data });
    const json = await res.json();
    if (res.ok) {
      msg.textContent = '¡Listo! Te contactaremos pronto por WhatsApp.';
      msg.className = 'ov-msg ov-msg-ok';
      btn.textContent = '¡Enviado! ✓';
      setTimeout(() => _closeModal('lead-modal'), 3000);
    } else {
      throw new Error(json.message || 'Error al enviar');
    }
  } catch (err) {
    msg.textContent = 'Hubo un error. Por favor intenta de nuevo.';
    msg.className = 'ov-msg ov-msg-error';
    btn.disabled = false;
    btn.textContent = 'Reintentar';
  }
};

window.__submitVoucher = async function (e, carrera, monto) {
  e.preventDefault();
  const form = e.target;
  const btn  = document.getElementById('voucher-submit-btn');
  const msg  = document.getElementById('voucher-msg');
  const data = new FormData(form);
  data.append('carrera', carrera);
  data.append('monto',   monto);

  btn.disabled = true;
  btn.textContent = 'Subiendo...';

  try {
    const res  = await fetch(`${BACKEND_URL}/api/vouchers`, { method: 'POST', body: data });
    const json = await res.json();
    if (res.ok) {
      msg.textContent = '¡Comprobante recibido! Verificaremos tu pago pronto.';
      msg.className = 'ov-msg ov-msg-ok';
      btn.textContent = '¡Enviado! ✓';
      setTimeout(() => _closeModal('payment-modal'), 4000);
    } else {
      throw new Error(json.message || 'Error al subir');
    }
  } catch (err) {
    msg.textContent = 'Hubo un error al subir el comprobante. Intenta de nuevo.';
    msg.className = 'ov-msg ov-msg-error';
    btn.disabled = false;
    btn.textContent = 'Reintentar';
  }
};

// ── Estilos CSS ────────────────────────────────────────────────────────────────
const _CSS = `
/* ── Contenedor overlay global ── */
#overlay-container {
  position: fixed;
  inset: 0;
  z-index: 10000;
  pointer-events: none;
  font-family: 'Segoe UI', system-ui, sans-serif;
}

/* ── Backdrop del modal ── */
.ov-backdrop {
  position: fixed;
  inset: 0;
  z-index: 10000;
  background: rgba(0, 0, 0, 0.78);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: auto;
  opacity: 0;
  visibility: hidden;
  transition: opacity 0.25s ease, visibility 0.25s ease;
  padding: 16px;
  box-sizing: border-box;
}

.ov-backdrop.ov-visible {
  opacity: 1;
  visibility: visible;
}

/* ── Tarjeta modal interior ── */
.ov-modal-inner {
  background: #1a1a2e;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 20px;
  padding: 28px 24px 24px;
  max-width: 480px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  position: relative;
  color: #f0f0f0;
  box-shadow: 0 25px 60px rgba(0, 0, 0, 0.7), 0 0 30px rgba(124, 108, 240, 0.2);
  transform: translateY(16px) scale(0.98);
  transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  pointer-events: auto;
}

.ov-backdrop.ov-visible .ov-modal-inner {
  transform: translateY(0) scale(1);
}

/* ── Botón de cierre ── */
.ov-close {
  position: absolute;
  top: 14px;
  right: 16px;
  background: rgba(255, 255, 255, 0.12);
  border: none;
  color: #fff;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  cursor: pointer;
  font-size: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, transform 0.15s;
}

.ov-close:hover {
  background: rgba(255, 255, 255, 0.25);
  transform: scale(1.08);
}

/* ── Galería ── */
.ov-gallery-img {
  width: 100%;
  max-height: 320px;
  object-fit: cover;
  border-radius: 14px;
  margin-bottom: 14px;
  display: block;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}

.ov-gallery-info h2 {
  font-size: 1.15rem;
  margin: 0 0 6px;
  color: #ffffff;
}

.ov-gallery-info p {
  font-size: 0.9rem;
  color: #cbd5e1;
  margin: 0;
  line-height: 1.45;
}

/* ── Formulario de Leads ── */
.ov-lead-header {
  text-align: center;
  margin-bottom: 20px;
}

.ov-lead-icon {
  font-size: 2.2rem;
  display: block;
  margin-bottom: 6px;
}

.ov-lead-header h2 {
  font-size: 1.3rem;
  margin: 0 0 6px;
}

.ov-lead-header p {
  font-size: 0.86rem;
  color: #bbb;
  margin: 0;
}

.ov-field {
  margin-bottom: 14px;
}

.ov-field label {
  display: block;
  font-size: 0.82rem;
  color: #aaa;
  margin-bottom: 5px;
  font-weight: 500;
}

.ov-field input, .ov-field textarea {
  width: 100%;
  box-sizing: border-box;
  background: rgba(255, 255, 255, 0.07);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 10px;
  color: #fff;
  padding: 10px 14px;
  font-size: 0.95rem;
  outline: none;
  transition: border 0.15s;
  font-family: inherit;
}

.ov-field input:focus, .ov-field textarea:focus {
  border-color: #7c6cf0;
}

.ov-field textarea {
  resize: vertical;
  min-height: 58px;
}

/* ── Pago con QR ── */
.ov-payment {
  text-align: center;
}

.ov-payment h2 {
  font-size: 1.25rem;
  margin: 0 0 6px;
}

.ov-payment-sub {
  font-size: 0.88rem;
  color: #ccc;
  margin: 0 0 16px;
}

.ov-qr-img {
  width: 190px;
  height: 190px;
  object-fit: contain;
  margin: 0 auto 12px;
  display: block;
  border-radius: 12px;
  background: #ffffff;
  padding: 8px;
}

.ov-yape-num {
  font-size: 1rem;
  margin: 0 0 16px;
}

.ov-divider {
  border: none;
  border-top: 1px solid rgba(255, 255, 255, 0.12);
  margin: 16px 0;
}

.ov-upload-label {
  font-size: 0.88rem;
  color: #bbb;
  margin: 0 0 12px;
}

.ov-file-input {
  display: block;
  margin: 0 auto 14px;
  color: #ccc;
  font-size: 0.88rem;
}

/* ── Botones ── */
.ov-btn-primary {
  width: 100%;
  padding: 13px;
  background: linear-gradient(135deg, #7c6cf0 0%, #5b4de8 100%);
  border: none;
  border-radius: 12px;
  color: #fff;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s, transform 0.1s;
  margin-top: 4px;
}

.ov-btn-primary:hover:not(:disabled) {
  opacity: 0.88;
  transform: translateY(-1px);
}

.ov-btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ── Mensajes ── */
.ov-msg {
  font-size: 0.85rem;
  margin-top: 10px;
  text-align: center;
}

.ov-msg-ok {
  color: #6ee7b7;
}

.ov-msg-error {
  color: #f87171;
}
`;

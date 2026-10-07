/**
 * ui/overlays.js — Componentes de UI overlay para el Modo Web.
 *
 * Gestiona tres modales superpuestos sobre el canvas del avatar:
 *
 *   1. Gallery Modal   → Muestra una foto grande con título y descripción.
 *                        Disparado por evento SSE `ui_action` show_gallery.
 *
 *   2. Lead Form Modal → Formulario de contacto (Nombre, WhatsApp, Carrera).
 *                        Disparado por show_contact. Solo en modo web.
 *
 *   3. Payment Modal   → QR Yape + número + monto + subida de voucher.
 *                        Disparado por show_payment. Solo en modo web.
 *
 * En modo kiosk, las galerías están disponibles; contacto y pago permanecen
 * deshabilitados. Conserva los mismos estilos en ambos dispositivos.
 */

import { SESSION_ID } from '../api/client.js';

import { apiUrl, resolverMediaUrl } from '../api/config.js';
export { BACKEND_URL, resolverMediaUrl } from '../api/config.js';

/** Escape para nodos de texto y atributos entre comillas; sin ejecución inline. */
export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]);
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

  // La galería también está disponible en kiosco; contacto/pago siguen siendo web.

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
  const resource = actionPayload.resource || {};
  const rawUrl   = resource.url || actionPayload.url || '';
  const imgUrl   = resolverMediaUrl(rawUrl);

  const titulo   = resource.titulo   || actionPayload.title || 'Instituto Tuinen Star';
  const desc     = resource.descripcion || actionPayload.description || '';

  console.warn('[UI_ACTION] Disparando modal de galeria:', { imgUrl, titulo, actionPayload });

  const modal = _renderModal('gallery-modal', `
    <div class="ov-modal-inner ov-gallery ov-modal-content">
      <button class="ov-close ov-close-btn">&times;</button>
      <div class="ov-img-container">
        <img src="${escapeHtml(imgUrl)}" alt="${escapeHtml(titulo)}" class="ov-gallery-img ov-modal-img" />
      </div>
      <div class="ov-gallery-info ov-text-container">
        <h3>${escapeHtml(titulo)}</h3>
        <p>${escapeHtml(desc)}</p>
      </div>
    </div>
  `);

  modal?.querySelector('img')?.addEventListener('error', (e) => {
    e.target.hidden = true;
    modal.querySelector('p').textContent = 'Imagen no disponible por el momento.';
  }, { once: true });
  _armGalleryAutoClose();
}

/**
 * Abre el formulario de captura de lead.
 * @param {object} actionPayload - { program_label: string }
 */
export function openLeadForm(actionPayload) {
  if (_mode === 'kiosk') return;
  const carrera = actionPayload.program_label || '';

  console.log('[OVERLAYS] Abriendo formulario de contacto para:', carrera);

  const modal = _renderModal('lead-modal', `
    <div class="ov-modal-inner ov-lead ov-lead-modal-card">
      <button class="ov-close">✕</button>
      <div class="ov-lead-header">
        <span class="ov-lead-icon">🎓</span>
        <h2>¡Reserva tu lugar!</h2>
        <p>Déjanos tus datos y un asesor te contactará por WhatsApp.</p>
      </div>
      <form id="lead-form">
        <input type="hidden" name="carrera" value="${escapeHtml(carrera)}">
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
          <input type="text" name="carrera_display" value="${escapeHtml(carrera)}" placeholder="Ej: Gastronomía">
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
  `, 'ov-backdrop-lead');
  modal?.querySelector('form')?.addEventListener('submit', submitLead);
}

/**
 * Abre el modal de pago con QR Yape y subida de voucher.
 * @param {object} actionPayload - { program_label, amount, concept, confirmed, qr_url, payment_number }
 */
export function openPayment(actionPayload) {
  if (_mode === 'kiosk') return;
  const carrera = String(actionPayload.program_label || 'Programa por confirmar');
  const monto = actionPayload.amount;
  const concepto = String(actionPayload.concept_label || actionPayload.concept || '').replaceAll('_', ' ');
  const confirmed = actionPayload.confirmed === true && /^\d+(\.\d{1,2})?$/.test(String(monto)) && Number(monto) > 0;
  const qrUrl = confirmed ? resolverMediaUrl(actionPayload.qr_url || '') : '';
  const yapeNumero = actionPayload.payment_number || '';
  const paymentContent = confirmed ? `
      <p class="ov-payment-sub">Carrera: <strong>${escapeHtml(carrera)}</strong> — Monto: <strong>${escapeHtml(monto)} soles</strong></p>
      <img src="${escapeHtml(qrUrl)}" alt="QR Yape" class="ov-qr-img">
      <p class="ov-yape-num">📱 Yape al <strong>${escapeHtml(yapeNumero)}</strong></p>
      <hr class="ov-divider">
      <p class="ov-upload-label">Sube tu voucher aquí para solicitar la verificación de tu pago:</p>
      <form id="voucher-form">
        <input type="file" name="imagen" accept="image/jpeg,image/png,image/webp" required class="ov-file-input" id="voucher-file">
        <button type="submit" class="ov-btn-primary" id="voucher-submit-btn">Enviar comprobante ✓</button>
        <p id="voucher-msg" class="ov-msg"></p>
      </form>` : `
      <p class="ov-payment-sub">Carrera: <strong>${escapeHtml(carrera)}</strong></p>
      <p class="ov-msg">Importe pendiente de confirmación oficial. No realices un pago hasta confirmarlo.</p>`;
  const modal = _renderModal('payment-modal', `
    <div class="ov-modal-inner ov-payment">
      <button class="ov-close">✕</button>
      <h2>${confirmed ? `Paga tu ${escapeHtml(concepto)} con Yape` : `Consulta de ${escapeHtml(concepto)}`}</h2>
      ${paymentContent}
    </div>
  `, 'ov-backdrop-payment');
  modal?.querySelector('img')?.addEventListener('error', (e) => { e.target.hidden = true; }, { once: true });
  modal?.querySelector('form')?.addEventListener('submit', (e) => submitVoucher(e, actionPayload));
}

// ── Helpers internos ───────────────────────────────────────────────────────────

function _renderModal(id, html, extraBackdropClass = '') {
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
  backdrop.className = `ov-backdrop ${extraBackdropClass}`.trim();
  backdrop.innerHTML = html;

  // Cerrar al hacer click en el backdrop (fuera del inner)
  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) _closeModal(id);
  });

  _container.appendChild(backdrop);

  // Forzar reflow y animar entrada
  void backdrop.offsetWidth;
  backdrop.classList.add('ov-visible');
  backdrop.querySelector('.ov-close')?.addEventListener('click', () => _closeModal(id));
  return backdrop;
}

function _closeModal(id) {
  if (id === 'gallery-modal') _cancelGalleryAutoClose();
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('ov-visible');
  el.addEventListener('transitionend', () => el.remove(), { once: true });
  // Fallback si transitionend no se dispara (mayor que el fade lento de 0.7s)
  setTimeout(() => { if (el.parentElement) el.remove(); }, 900);
}

// ── Auto-cierre temporizado de la galería ─────────────────────────────────────
const GALLERY_AUTOCLOSE_MS = 9000;
let _galleryTimer = null;

function _cancelGalleryAutoClose() {
  if (_galleryTimer) {
    clearTimeout(_galleryTimer);
    _galleryTimer = null;
  }
}

/** Arma el timer de 9s; el hover/touch sobre la tarjeta lo cancela. */
function _armGalleryAutoClose() {
  _cancelGalleryAutoClose();
  const backdrop = document.getElementById('gallery-modal');
  if (!backdrop) return;

  _galleryTimer = setTimeout(() => {
    _galleryTimer = null;
    const el = document.getElementById('gallery-modal');
    if (el) el.classList.add('ov-fading');   // fade-out suave
    _closeModal('gallery-modal');
  }, GALLERY_AUTOCLOSE_MS);

  const card = backdrop.querySelector('.ov-modal-inner') || backdrop;
  card.addEventListener('mouseenter', _cancelGalleryAutoClose, { once: true });
  card.addEventListener('touchstart', _cancelGalleryAutoClose, { once: true, passive: true });
}

// ── Formularios: listeners locales, sin JavaScript inline ─────────────────────
async function submitLead(e) {
  e.preventDefault();
  const form   = e.target;
  const btn    = document.getElementById('lead-submit-btn');
  const msg    = document.getElementById('lead-msg');
  const data   = new FormData(form);
  if (SESSION_ID) {
    data.append('session_id', SESSION_ID);
  }

  const carreraDisplay = data.get('carrera_display');
  if (carreraDisplay) data.set('carrera', carreraDisplay);
  data.delete('carrera_display');

  btn.disabled = true;
  btn.textContent = 'Enviando...';

  try {
    const res = await fetch(apiUrl('/api/leads'), { method: 'POST', body: data });
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

async function submitVoucher(e, action) {
  e.preventDefault();
  const form = e.target;
  const btn  = document.getElementById('voucher-submit-btn');
  const msg  = document.getElementById('voucher-msg');
  const data = new FormData(form);
  data.append('carrera', action.program);
  data.append('monto', String(action.amount));
  data.append('concepto', action.concept);
  if (action.modality) data.append('modalidad', action.modality);
  if (action.shift) data.append('turno', action.shift);

  btn.disabled = true;
  btn.textContent = 'Subiendo...';

  try {
    const res  = await fetch(apiUrl('/api/vouchers'), { method: 'POST', body: data });
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
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: auto;
  opacity: 0;
  visibility: hidden;
  transition: opacity 0.3s cubic-bezier(0.16, 1, 0.3, 1), visibility 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  padding: 16px;
  box-sizing: border-box;
}

/* El backdrop del lead modal y payment modal es ultra-ligero para no oscurecer al avatar ni los subtítulos */
.ov-backdrop-lead,
.ov-backdrop-payment {
  background: rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
  justify-content: flex-end;
  align-items: flex-end;
  padding: 24px;
}

.ov-backdrop.ov-visible {
  opacity: 1;
  visibility: visible;
}

/* ── Tarjeta modal interior (estándar: centro) ── */
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
  transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.35s ease;
  pointer-events: auto;
}

.ov-backdrop.ov-visible .ov-modal-inner {
  transform: translateY(0) scale(1);
}

/* ── Tarjetas no invasivas (Slide-in lateral derecho elegante y translúcido) ── */
.ov-lead-modal-card,
.ov-payment {
  max-width: 420px;
  background: rgba(18, 18, 32, 0.85);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border: 1px solid rgba(124, 108, 240, 0.35);
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6), 0 0 30px rgba(124, 108, 240, 0.25);
  transform: translateX(40px) scale(0.96);
  transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.35s ease;
  margin-bottom: 75px; /* Deja espacio inferior para que los subtítulos y el botón del micro se vean intactos */
}

.ov-backdrop.ov-visible .ov-lead-modal-card,
.ov-backdrop.ov-visible .ov-payment {
  transform: translateX(0) scale(1);
}

@media (max-width: 640px) {
  .ov-backdrop-lead,
  .ov-backdrop-payment {
    justify-content: center;
    align-items: flex-end;
    padding: 12px;
  }
  .ov-lead-modal-card,
  .ov-payment {
    max-width: 100%;
    transform: translateY(40px) scale(0.96);
    margin-bottom: 85px;
  }
  .ov-backdrop.ov-visible .ov-lead-modal-card,
  .ov-backdrop.ov-visible .ov-payment {
    transform: translateY(0) scale(1);
  }
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
.ov-img-container {
  width: 100%;
  min-height: 180px;
  max-height: 45vh;
  display: flex;
  justify-content: center;
  align-items: center;
  overflow: hidden;
  border-radius: 14px;
  margin-bottom: 14px;
  background: rgba(0, 0, 0, 0.2);
}

.ov-modal-img,
.ov-gallery-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.ov-modal img {
  width: 100%;
  max-height: 52vh;
  object-fit: contain;
  object-position: top center;
  border-radius: 14px;
  margin-bottom: 14px;
  display: block;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}

/* El QR de Yape mantiene su tamaño propio (más específico que .ov-modal img) */
.ov-modal-inner .ov-qr-img {
  width: 190px;
  max-height: none;
}

/* Fade-out lento para el auto-cierre de la galería */
.ov-backdrop.ov-fading {
  transition-duration: 0.7s;
}

.ov-gallery-info h2,
.ov-text-container h3 {
  font-size: 1.15rem;
  margin: 0 0 6px;
  color: #ffffff;
}

.ov-gallery-info p,
.ov-text-container p {
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

/**
 * ui/persona.js — Estado de persona de Lía (Consulta 💡 / Vendedora 🎯).
 *
 *   'info'  → aura azul cian, tono técnico/conciso.
 *   'sales' → aura dorada ámbar, tono persuasivo/comercial.
 *
 * Fuente única de verdad en el frontend: client.js lee getPersona() para
 * enviarlo al backend, y escucha `mode_switch` (escalación automática) para
 * llamar a setPersona(). No importa otros módulos → sin dependencias circulares.
 */

export const isMobile = (() => {
  const ua = navigator.userAgent || '';
  return /Android|iPhone|iPad|iPod|Mobi/i.test(ua)
    || (navigator.maxTouchPoints > 1 && window.innerWidth < 900);
})();

let _persona = 'sales';

/** Persona inicial: ?mode=kiosk → info; móvil o URL sin parámetros → sales. */
function _personaInicial(appMode) {
  return appMode === 'kiosk' ? 'info' : 'sales';
}

/** Persona actual ('info' | 'sales'). */
export function getPersona() {
  return _persona;
}

/** Aplica la persona al DOM (aura, switch, atributo en <body>). */
function _render() {
  const aura = document.getElementById('lia-aura');
  if (aura) {
    aura.classList.toggle('aura-info',  _persona === 'info');
    aura.classList.toggle('aura-sales', _persona === 'sales');
  }

  const sw = document.getElementById('mode-switch');
  if (sw) {
    sw.classList.toggle('persona-info',  _persona === 'info');
    sw.classList.toggle('persona-sales', _persona === 'sales');
    sw.querySelectorAll('.ms-opt').forEach((btn) => {
      btn.setAttribute('aria-pressed', String(btn.dataset.persona === _persona));
    });
  }

  document.body.dataset.persona = _persona;
}

/**
 * Cambia la persona y actualiza aura + switch.
 * @param {'info'|'sales'} persona
 * @param {string} [origen] 'manual' | 'auto' | 'init' (solo para logs)
 */
export function setPersona(persona, origen = 'manual') {
  const p = persona === 'info' ? 'info' : 'sales';
  if (p === _persona && origen !== 'init') return;
  _persona = p;
  _render();
  console.log(`[persona] -> ${_persona} (${origen})`);
}

/**
 * Inicializa persona, aura y switch manual. Llamar una vez desde main.js.
 * @param {'kiosk'|'web'} appMode
 */
export function initPersona(appMode = 'web') {
  const sw = document.getElementById('mode-switch');
  if (sw) {
    sw.addEventListener('click', (e) => {
      const btn = e.target.closest('.ms-opt');
      if (btn) setPersona(btn.dataset.persona, 'manual');
    });
  }
  setPersona(_personaInicial(appMode), 'init');
  console.log(`[persona] inicial=${_persona} appMode=${appMode} isMobile=${isMobile}`);
}

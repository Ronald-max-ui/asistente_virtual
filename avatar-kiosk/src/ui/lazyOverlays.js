/** Secondary UI code is requested only by an already-authorized callback. */
export function createLazyOverlays(loader = () => import('./overlays.js')) {
  let mode = 'web';
  let pending = null;
  const load = () => {
    if (!pending) pending = loader().then((module) => { module.initOverlays(mode); return module; })
      .catch((error) => { pending = null; throw error; });
    return pending;
  };
  return {
    initOverlays(value = 'web') { mode = value; },
    openGallery: (payload, isCurrent = () => true) => load().then((module) => { if (isCurrent()) module.openGallery(payload); })
      .catch(() => console.warn('[ui] No se pudo cargar el módulo solicitado.')),
    openLeadForm: (payload, isCurrent = () => true) => load().then((module) => { if (isCurrent()) module.openLeadForm(payload); })
      .catch(() => console.warn('[ui] No se pudo cargar el módulo solicitado.')),
    openPayment: (payload, isCurrent = () => true) => load().then((module) => { if (isCurrent()) module.openPayment(payload); })
      .catch(() => console.warn('[ui] No se pudo cargar el módulo solicitado.')),
  };
}
const overlays = createLazyOverlays();
export const initOverlays = overlays.initOverlays;
export const openGallery = overlays.openGallery;
export const openLeadForm = overlays.openLeadForm;
export const openPayment = overlays.openPayment;

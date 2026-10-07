/** Contrato de transporte: handlers locales conocidos, sin políticas comerciales. */
import { openGallery, openLeadForm, openPayment } from '../ui/overlays.js';

const record = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const string = (value) => typeof value === 'string';
const nullableString = (value) => value === null || string(value);
const mediaPath = (value) => string(value) && /^\/static\/media\/[a-zA-Z0-9_-]+\.(webp|png|jpe?g)$/.test(value);
const shape = (value, fields) => record(value)
  && Object.keys(value).every((key) => Object.hasOwn(fields, key))
  && Object.entries(fields).every(([key, validate]) => Object.hasOwn(value, key) && validate(value[key]));

const handlers = new Map([
  ['show_gallery', {
    run: openGallery,
    fields: { type: (v) => v === 'show_gallery', resource_id: string,
      resource: (v) => shape(v, { titulo: string, descripcion: string, url: mediaPath }) },
  }],
  ['show_contact', {
    run: openLeadForm,
    fields: { type: (v) => v === 'show_contact', program: nullableString, program_label: string },
  }],
  ['show_payment', {
    run: openPayment,
    fields: { type: (v) => v === 'show_payment', program: string, program_label: string,
      concept: string, concept_label: string, modality: nullableString, shift: nullableString,
      amount: (v) => string(v) && /^(?:[1-9]\d*(?:\.\d{1,2})?|0\.(?:0[1-9]|[1-9]\d?))$/.test(v),
      currency: (v) => v === 'PEN', status: (v) => v === 'active', campaign: string,
      starts_on: nullableString, ends_on: nullableString, confirmed: (v) => v === true,
      qr_url: mediaPath, payment_number: string },
  }],
]);

export function crearHandlerAccion(action) {
  const entry = record(action) && handlers.get(action.type);
  if (!entry || !shape(action, entry.fields)) {
    console.warn('[api/actions] Acción desconocida o inválida; ignorada.');
    return null;
  }
  // Capturar datos validados para el callback que ejecuta tras finalizar audio.
  const payload = Object.freeze({ ...action,
    ...(action.resource ? { resource: Object.freeze({ ...action.resource }) } : {}) });
  return () => entry.run(payload);
}

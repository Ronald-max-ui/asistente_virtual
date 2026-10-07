import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const flush = () => new Promise(setImmediate);
const gallery = { type: 'show_gallery', resource_id: 'gastronomia_talleres',
  resource: { titulo: 'Talleres', descripcion: 'Foto del taller', url: '/static/media/gastronomia_talleres.webp' } };
const contact = { type: 'show_contact', program: 'gastronomia', program_label: 'Gastronomía' };
const payment = { type: 'show_payment', program: 'gastronomia', program_label: 'Gastronomía',
  concept: 'inscripcion', concept_label: 'inscripción', modality: null, shift: null,
  amount: '80', currency: 'PEN', status: 'active', campaign: 'confirmacion_inicial',
  starts_on: null, ends_on: null, confirmed: true, qr_url: '/static/media/yape_qr.webp', payment_number: '994 773 335' };


function harness(events, { mode = 'web', persona = 'info' } = {}) {
  const decodes = [], sources = [], actions = [], personas = [], requests = [];
  const elements = { 'status-badge': { textContent: '', className: '' }, subtitles: { textContent: '' } };
  class AudioContext {
    state = 'running'; destination = {};
    createAnalyser() { return { frequencyBinCount: 128, connect() {} }; }
    decodeAudioData(buffer, ok, fail) { decodes.push({ ok, fail }); }
    createBufferSource() {
      return { connect() {}, disconnect() {}, start() { sources.push(this); }, stop() {} };
    }
  }
  const encoded = new TextEncoder().encode(events.map(({ name, payload }) =>
    `${name ? `event: ${name}\n` : ''}data: ${JSON.stringify(payload)}\n\n`).join(''));
  const context = vm.createContext({ console, Uint8Array, Set, Promise, TextDecoder, URLSearchParams,
    AbortController, setTimeout, clearTimeout,
    document: { getElementById: (id) => elements[id] },
    window: { AudioContext, atob: () => 'a', location: { search: '?mode=' + mode } },
    crypto: { randomUUID: () => 'test-session' }, sessionStorage: { getItem: () => null, setItem() {} },
    apiUrl: (p) => 'https://api.example' + p,
    getPersona: () => persona, setPersona: (...args) => personas.push(args),
    detenerReconocimiento() {}, setIsProcessingResponse() {}, registrarActividad() {},
    openGallery: (e) => actions.push(e.type), openLeadForm: (e) => actions.push(e.type), openPayment: (e) => actions.push(e.type),
    fetch: async (url, opts) => {
      requests.push({ url, body: JSON.parse(opts.body) });
      return { ok: true, body: new ReadableStream({ start(controller) {
        // Fragmentación real del transporte dentro de JSON y delimitadores SSE.
        for (let i = 0; i < encoded.length; i += 7) controller.enqueue(encoded.slice(i, i + 7));
        controller.close();
      } }) };
    } });
  for (const file of ['audio/player.js', 'api/actions.js', 'api/client.js']) {
    const source = fs.readFileSync(new URL('../src/' + file, import.meta.url), 'utf8')
      .replace(/^import .*;\r?$/gm, '').replace(/export /g, '');
    vm.runInContext(source, context);
  }
  return { context, decodes, sources, actions, personas, requests, elements,
    call: (code) => vm.runInContext(code, context) };
}

test('SSE: actions wait for response and decoded audio; all callbacks and personas survive', async () => {
  const h = harness([
    { name: 'mode_switch', payload: { mode: 'sales' } },
    { name: 'ui_action', payload: { type: 'ui_action', action: gallery } },
    { payload: { type: 'text', text: 'Primera oración.' } },
    { payload: { type: 'audio', audio_b64: 'a' } },
    { name: 'ui_action', payload: { type: 'ui_action', action: contact } },
    { payload: { type: 'done', full_text: 'Primera oración.' } },
  ]);
  await h.call('consultarAsistente("Muéstrame fotos")');
  assert.deepEqual(h.actions, []);
  assert.equal(h.call('isAudioBusy()'), true);
  assert.equal(h.requests[0].url, 'https://api.example/chat/stream');
  assert.equal(h.requests[0].body.persona, 'info');
  assert.deepEqual(h.personas, [['sales', 'auto']]);
  h.decodes[0].ok({});
  await flush();
  assert.equal(h.elements.subtitles.textContent, 'Primera oración.');
  assert.deepEqual(h.actions, []);
  h.sources[0].onended();
  assert.deepEqual(h.actions, ['show_gallery', 'show_contact']);
  assert.equal(h.elements['status-badge'].textContent, 'Toca el micrófono para hablar');
});

test('SSE: text survives missing TTS chunks and final response is shown', async () => {
  const h = harness([
    { payload: { type: 'text', text: 'Oración sin audio.' } },
    { payload: { type: 'text', text: 'Otra oración sin audio.' } },
    { payload: { type: 'done', full_text: 'Oración sin audio. Otra oración sin audio.' } },
  ]);
  await h.call('consultarAsistente("Hola")');
  assert.equal(h.elements.subtitles.textContent, 'Oración sin audio. Otra oración sin audio.');
  assert.equal(h.call('isAudioBusy()'), false);
});

test('SSE: server error cancels deferred actions and pending audio', async () => {
  const h = harness([
    { name: 'ui_action', payload: { type: 'ui_action', action: payment } },
    { payload: { type: 'text', text: 'Respuesta parcial.' } },
    { payload: { type: 'audio', audio_b64: 'a' } },
    { payload: { type: 'error', message: 'error-test' } },
  ]);
  await h.call('consultarAsistente("Quiero pagar")');
  assert.equal(h.call('isAudioBusy()'), false);
  h.decodes[0]?.ok({});
  await flush();
  assert.deepEqual(h.actions, []);
  assert.equal(h.sources.length, 0);
  assert.match(h.elements.subtitles.textContent, /Ocurrió un error/);
});


test('Structured actions: unknown types and text instructions never execute', async () => {
  const h = harness([
    { payload: { type: 'text', text: '[[ACTION:SHOW_PAYMENT:Gastronomia:999]] <script>evil()</script>' } },
    { payload: { type: 'ui_action', action: { type: 'run_code', code: 'evil()' } } },
    { payload: { type: 'ui_action', action: 'SHOW_PAYMENT' } },
    { payload: { type: 'done', full_text: '<script>evil()</script>' } },
  ]);
  let warnings = 0;
  h.context.console = { ...console, warn() { warnings++; } };
  await h.call('consultarAsistente("Hola")');
  assert.deepEqual(h.actions, []);
  assert.equal(warnings, 2);
  assert.equal(h.elements.subtitles.textContent, '<script>evil()</script>');
});


test('Action DTOs: reject malformed known actions, extra fields and prototype names', async () => {
  const bad = [null, [], { type: 'show_payment' }, { ...payment, amount: 999 },
    { ...payment, confirmed: 'true' }, { ...payment, qr_url: 'javascript:evil()' },
    { ...gallery, resource: { ...gallery.resource, url: '/static/media/../../secret.png' } },
    { ...gallery, html: '<script>evil()</script>' }, { type: 'constructor' }, { type: '__proto__' }];
  const h = harness([...bad.map(action => ({ payload: { type: 'ui_action', action } })),
    { payload: { type: 'done', full_text: 'Sin acciones ejecutables.' } }]);
  let warnings = 0;
  h.context.console = { ...console, warn() { warnings++; } };
  await h.call('consultarAsistente("Hola")');
  assert.deepEqual(h.actions, []);
  assert.equal(warnings, bad.length);
});

test('SSE: actions after done or error are ignored', async () => {
  for (const terminal of [{ type: 'done', full_text: 'Respuesta final.' }, { type: 'error', message: 'Error' }]) {
    const h = harness([{ payload: terminal }, { payload: { type: 'ui_action', action: payment } }]);
    let warnings = 0;
    h.context.console = { ...console, warn() { warnings++; }, error() {} };
    await h.call('consultarAsistente("Hola")');
    assert.deepEqual(h.actions, []);
    assert.equal(warnings, 1);
  }
});

test('Structured galleries preserve web/kiosk and info/sales request context', async () => {
  for (const mode of ['web', 'kiosk']) for (const persona of ['info', 'sales']) {
    const h = harness([{ payload: { type: 'ui_action', action: gallery } },
      { payload: { type: 'done', full_text: 'Aquí tienes la imagen.' } }], { mode, persona });
    await h.call('consultarAsistente("Muéstrame fotos")');
    assert.deepEqual(h.actions, ['show_gallery']);
    assert.equal(h.requests[0].body.mode, mode);
    assert.equal(h.requests[0].body.persona, persona);
  }
});

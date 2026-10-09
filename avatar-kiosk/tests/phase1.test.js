import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const flush = () => new Promise(setImmediate);

function audioHarness() {
  const decodes = [], sources = [];
  class AudioContext {
    state = 'running';
    destination = {};
    createAnalyser() { return { frequencyBinCount: 128, connect() {} }; }
    decodeAudioData(data, ok, fail) { decodes.push({ ok, fail }); }
    createBufferSource() {
      const source = { connect() {}, disconnect() {}, start() { sources.push(this); }, stop() {} };
      return source;
    }
  }
  const context = vm.createContext({ console, Uint8Array, Set, Promise,
    fetch: async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(1) }),
    window: { AudioContext, atob: () => 'a' } });
  const source = fs.readFileSync(new URL('../src/audio/player.js', import.meta.url), 'utf8');
  vm.runInContext(source.replace(/export /g, ''), context);
  const call = (code) => vm.runInContext(code, context);
  return { call, context, decodes, sources };
}

test('audio: pending decodes count as busy, preserve arrival order and notify all callbacks', async () => {
  const h = audioHarness();
  h.call("enqueueBase64Audio('a')");
  h.call("enqueueBase64Audio('b')");
  await flush();
  assert.equal(h.call('isAudioBusy()'), true);
  h.call('globalThis.results=[]; onAudioQueueFinished(()=>results.push(1)); onAudioQueueFinished(()=>results.push(2));');
  h.decodes[1].ok({ id: 2 });
  await flush();
  assert.equal(h.sources.length, 0);
  h.decodes[0].ok({ id: 1 });
  await flush();
  assert.equal(h.sources[0].buffer.id, 1);
  h.sources[0].onended();
  assert.equal(h.sources[1].buffer.id, 2);
  h.sources[1].onended();
  assert.deepEqual(Array.from(h.context.results), [1, 2]);
  assert.equal(h.call('isAudioBusy()'), false);
});

test('audio: cancellation rejects late decode and stale end events', async () => {
  const h = audioHarness();
  h.call("enqueueBase64Audio('old')");
  await flush();
  h.call('stopCurrentAudio()');
  h.decodes[0].ok({ id: 'old' });
  await flush();
  assert.equal(h.sources.length, 0);
  h.call("enqueueBase64Audio('playing')");
  await flush();
  h.decodes[1].ok({ id: 'playing' });
  await flush();
  const oldEnd = h.sources[0].onended;
  h.call('stopCurrentAudio()');
  h.call("enqueueBase64Audio('new')");
  await flush();
  h.decodes[2].ok({ id: 'new' });
  await flush();
  oldEnd();
  assert.equal(h.call('isCurrentlySpeaking()'), true);
});

test('audio: stream holds final callbacks across silent gaps and handles decode failure', async () => {
  const h = audioHarness();
  h.call('beginAudioStream(); globalThis.finished=0; onAudioQueueFinished(()=>finished++);');
  h.call("enqueueBase64Audio('a')");
  await flush();
  h.decodes[0].fail(new Error('invalid audio'));
  await flush();
  assert.equal(h.context.finished, 0);
  h.call('endAudioStream()');
  assert.equal(h.context.finished, 1);
});

test('attraction: kiosk and web reach attraction without an undefined variable', () => {
  for (const enabled of [false, true]) {
    const played = [];
    const context = vm.createContext({ console, Date: { now: () => 40000 },
      setTimeout() {}, requestAnimationFrame() {}, createRenderLoop: () => () => {},
      isCurrentlySpeaking: () => false, getCurrentVrm: () => null,
      THREE: { Vector3: class { set() {} }, Clock: class { getDelta() { return 0; } getElapsedTime() { return 0; } } },
      playAudio: (url) => played.push(url) });
    const source = fs.readFileSync(new URL('../src/avatar/animator.js', import.meta.url), 'utf8')
      .replace(/^import .*;\r?$/gm, '').replace(/export /g, '');
    vm.runInContext(source, context);
    context.renderer = { render() {} };
    vm.runInContext(`startAnimation(renderer, {}, {}, '${enabled ? 'kiosk' : 'web'}'); lastInteractionTime=0;
      _updateAttractionStateMachine(1,false); _updateAttractionStateMachine(4,false);
      _updateAttractionStateMachine(3,false);`, context);
    assert.equal(played.length, enabled ? 1 : 0);
  }
});

test('URLs: local, production, configured path and unsafe media', async () => {
  globalThis.window = { location: { origin: 'https://lia.example', hostname: 'lia.example' } };
  const { createApiConfig } = await import('../src/api/config.js');
  const local = createApiConfig('', { origin: 'http://localhost:5173', hostname: 'localhost' });
  assert.equal(local.apiUrl('/chat/stream'), 'http://localhost:8000/chat/stream');
  const prod = createApiConfig('', window.location);
  assert.equal(prod.apiUrl('/api/leads'), 'https://lia.example/api/leads');
  const configured = createApiConfig('https://api.example/lia/', window.location);
  assert.equal(configured.apiUrl('/api/vouchers'), 'https://api.example/lia/api/vouchers');
  assert.equal(configured.mediaUrl('/static/media/yape_qr.webp'), 'https://api.example/lia/static/media/yape_qr.webp');
  for (const unsafe of ['javascript:alert(1)', '//evil.example/a', 'https://evil.example/static/media/a.webp', '/static/media/../../evil']) {
    assert.equal(configured.mediaUrl(unsafe), '', unsafe);
  }
});

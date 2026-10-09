import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

globalThis.window = { location: { hostname: 'localhost', origin: 'http://localhost:5173' } };
const { selectedAvatarUrl, fetchAvatarUrl } = await import('../src/api/publicConfig.js');
const resolve = (path) => 'https://example.com/lia' + path;

test('avatar seleccionado por backend respeta la base configurada y puede cambiar sin build', async () => {
  const calls = [];
  let avatar = 'first';
  const fetcher = async (url, options) => {
    calls.push({ url, options });
    return { ok: true, json: async () => ({ avatar: { id: avatar, name: avatar, url: `/static/avatars/${avatar}.vrm` } }) };
  };
  assert.equal(await fetchAvatarUrl(fetcher, resolve), 'https://example.com/lia/static/avatars/first.vrm');
  avatar = 'second';
  assert.equal(await fetchAvatarUrl(fetcher, resolve), 'https://example.com/lia/static/avatars/second.vrm');
  assert.equal(calls[0].url, 'https://example.com/lia/api/config');
  assert.equal(calls[0].options.cache, 'no-cache');
});

test('configuración inválida y rutas peligrosas no llegan al cargador VRM', () => {
  for (const url of ['javascript:alert(1)', 'https://evil.example/x.vrm', '/static/avatars/../x.vrm',
                     '/static/avatars/a.vrm?token=x', '/avatar.vrm', '/static/media/test.png']) {
    assert.throws(() => selectedAvatarUrl({ avatar: { id: 'x', name: 'x', url } }, resolve));
  }
  assert.throws(() => selectedAvatarUrl({ avatar: null }, resolve));
});

test('errores HTTP de configuración son explícitos', async () => {
  await assert.rejects(fetchAvatarUrl(async () => ({ ok: false }), resolve), /configuración/);
});

test('cargador utiliza el avatar configurado y conserva la postura de Lía', async () => {
  const calls = [], added = [];
  const bones = { leftUpperArm: { rotation: {} }, rightUpperArm: { rotation: {} } };
  const vrm = { scene: {}, humanoid: { getNormalizedBoneNode: (name) => bones[name] } };
  class GLTFLoader {
    register() {}
    async loadAsync(url) { calls.push(url); return { scene: {}, userData: { vrm } }; }
  }
  const context = vm.createContext({ console, GLTFLoader, VRMLoaderPlugin: class {},
    VRMUtils: { removeUnnecessaryVertices() {}, removeUnnecessaryJoints() {} },
    fetchAvatarUrl: async () => 'https://api.example/static/avatars/second.vrm' });
  const source = fs.readFileSync(new URL('../src/avatar/loader.js', import.meta.url), 'utf8')
    .replace(/^import .*;\r?\n/gm, '').replace(/export /g, '');
  vm.runInContext(source, context);
  await context.loadAvatar({ add: (scene) => added.push(scene) });
  assert.deepEqual(calls, ['https://api.example/static/avatars/second.vrm']);
  assert.equal(context.getCurrentVrm(), vrm);
  assert.equal(added[0], vrm.scene);
  assert.equal(bones.leftUpperArm.rotation.z, -1.25);
  assert.equal(bones.rightUpperArm.rotation.z, 1.25);
});

test('cargador controla el fallo de configuración sin bloquear la aplicación', async () => {
  const badge = { textContent: '' };
  const context = vm.createContext({ console: { warn() {} },
    fetchAvatarUrl: async () => { throw new Error('No disponible'); },
    document: { getElementById: () => badge } });
  const source = fs.readFileSync(new URL('../src/avatar/loader.js', import.meta.url), 'utf8')
    .replace(/^import .*;\r?\n/gm, '').replace(/export /g, '');
  vm.runInContext(source, context);
  assert.equal(await context.loadAvatar({ add: () => assert.fail('No debe añadir un avatar inválido') }),false);
  assert.equal(context.getCurrentVrm(), null);
  assert.equal(badge.textContent, ''); // Optional avatar must not overwrite conversation state.
});

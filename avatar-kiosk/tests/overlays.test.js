import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function harness() {
  const nodes = new Map();
  class Element {
    children = []; events = {}; elements = new Map(); parentElement = null;
    classList = { add() {}, remove() {} };
    appendChild(node) { this.children.push(node); node.parentElement = this; nodes.set(node.id, node); }
    contains(node) { return this.children.includes(node); }
    addEventListener(event, handler) { this.events[event] = handler; }
    remove() { nodes.delete(this.id); }
    querySelector(selector) {
      if (selector === 'form' && !this.innerHTML?.includes('<form ')) return null;
      if (selector === 'img' && !this.innerHTML?.includes('<img ')) return null;
      if (!this.elements.has(selector)) this.elements.set(selector, new Element());
      return this.elements.get(selector);
    }
  }
  const document = { body: new Element(), head: new Element(),
    createElement: () => new Element(), getElementById: (id) => nodes.get(id) };
  const context = vm.createContext({bindDialog:()=>()=>{},sessionStorage:{getItem:()=>null,setItem(){}}, console, document, setTimeout: () => 1, clearTimeout() {},
    SESSION_ID: 'test-session', apiUrl: (p) => 'https://api.example' + p,
    resolverMediaUrl: (p) => p?.startsWith('/static/media/') ? 'https://api.example' + p : '',
    window: {} });
  const source = fs.readFileSync(new URL('../src/ui/overlays.js', import.meta.url), 'utf8')
    .replace(/^import .*;\r?$/gm, '').replace(/^export \{.*;\r?$/gm, '').replace(/export /g, '');
  vm.runInContext(source, context);
  return { context, nodes, call: (code) => vm.runInContext(code, context) };
}

test('modals: adversarial data stays escaped and handlers are listeners', () => {
  const h = harness();
  h.context.attack = `"><img src=x onerror="alert(1)"><script>alert('x')</script>`;
  h.call('initOverlays("web"); openGallery({resource:{url:"javascript:alert(1)",titulo:attack,descripcion:attack}});');
  h.call('openLeadForm({program_label:attack});');
  h.call('openPayment({program_label:attack,amount:"80",concept:"inscripcion",confirmed:true,payment_number:attack});');
  for (const id of ['gallery-modal', 'lead-modal', 'payment-modal']) {
    const modal = h.nodes.get(id);
    assert.ok(modal.innerHTML.includes('&lt;script&gt;'));
    assert.equal(modal.innerHTML.includes(h.context.attack), false);
    assert.equal(/\s(?:onclick|onsubmit|onerror)\s*=/.test(modal.innerHTML.replace(/&quot;[^<]*/g, '')), false);
    assert.equal(typeof modal.querySelector('.ov-close').events.click, 'function');
  }
  assert.equal(typeof h.nodes.get('lead-modal').querySelector('form').events.submit, 'function');
  assert.equal(typeof h.nodes.get('payment-modal').querySelector('form').events.submit, 'function');
  assert.equal(h.nodes.get('gallery-modal').innerHTML.includes('src="javascript:'), false);
});

test('payment: pending tariffs expose no QR, upload form or inferred number', () => {
  const h = harness();
  h.call('initOverlays("web"); openPayment({program_label:"Turismo",amount:null,confirmed:false});');
  const html = h.nodes.get('payment-modal').innerHTML;
  assert.match(html, /pendiente de confirmación oficial/);
  assert.doesNotMatch(html, /<img |<form |200 soles|250 soles/);
});

test('kiosk: gallery works, lead and payment remain disabled', () => {
  const h = harness();
  h.call('initOverlays("kiosk"); openGallery({resource:{url:"/static/media/gastronomia_talleres.webp"}});');
  assert.ok(h.nodes.has('gallery-modal'));
  h.call('openLeadForm({program_label:"Gastronomía"}); openPayment({amount:"80",confirmed:true});');
  assert.equal(h.nodes.has('lead-modal'), false);
  assert.equal(h.nodes.has('payment-modal'), false);
});

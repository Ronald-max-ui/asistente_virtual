import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
globalThis.window={location:{origin:'https://example.test',hostname:'example.test'}};
const {approvedImage,contrastText,applyBranding}=await import('../src/ui/branding.js');
const source=fs.readFileSync(new URL('../../backend/static/admin/appearanceScreen.js',import.meta.url),'utf8');
test('branding URLs reject external, traversal, scripts and SVG; accept deterministic versions',()=>{
  for(const url of ['javascript:alert(1)','https://x/logo.png','/static/branding/../logo.png','/static/branding/x.svg','/static/branding/x.png?v=random'])assert.equal(approvedImage(url),null);
  assert.equal(approvedImage('/static/branding/a.png?v='+'a'.repeat(64)),'/static/branding/a.png?v='+'a'.repeat(64));
});
test('contrast chooses maximum readable black or white without replacing primary color',()=>{
  assert.equal(contrastText('#ffffff'),'#000000');assert.equal(contrastText('#000000'),'#ffffff');assert.equal(contrastText('red'),null);
});
test('public reload applies name, color, logo, initial text and favicon safely',()=>{
  const nodes={};for(const key of ['assistant-name','mode-switch','text-message','assistant-logo','app-favicon','subtitles'])nodes[key]={textContent:'',setAttribute(k,v){this[k]=v;}};
  const colors={};const doc={getElementById:id=>nodes[id],documentElement:{style:{setProperty(k,v){colors[k]=v;}},dataset:{}}};
  applyBranding({assistant:{name:'Instituto',primary_color:'#135790',logo_url:'/static/branding/logo.png',favicon_url:'/static/branding/icon.png?v='+'a'.repeat(64),initial_message:'<script>plain text</script>'}},doc,x=>x);
  assert.equal(doc.title,'Instituto');assert.equal(nodes['assistant-name'].textContent,'Instituto');assert.equal(nodes.subtitles.textContent,'<script>plain text</script>');assert.equal(colors['--assistant-primary'],'#135790');assert.equal(nodes['app-favicon'].type,'image/png');nodes['assistant-logo'].onerror();assert.equal(nodes['assistant-logo'].hidden,true);
});
test('appearance uses CSRF multipart client, optimistic save, fixed voice preview and cleanup',()=>{
  assert.match(source,/voice-preview/);assert.match(source,/URL.revokeObjectURL/);assert.match(source,/ctx.trackForm\(form/);assert.match(source,/\/settings','PUT',body,expected/);assert.match(source,/Guardar cambios/);
  const client=fs.readFileSync(new URL('../../backend/static/admin/adminClient.js',import.meta.url),'utf8');assert.match(client,/body instanceof FormData/);assert.match(client,/X-CSRF-Token/);
  for(const text of [source,client]){assert.doesNotMatch(text,/localStorage|sessionStorage|innerHTML|eval\(/);}
});

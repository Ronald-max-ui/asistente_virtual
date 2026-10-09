import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRenderLoop } from '../src/avatar/renderLoop.js';
import { createLazyOverlays } from '../src/ui/lazyOverlays.js';
const flush = () => new Promise(setImmediate);

test('secondary overlays load once, on demand, and recheck cancellation after import', async () => {
  let resolve, calls=0, opened=0, current=true;
  const module={initOverlays() {},openGallery() { opened++; }};
  const ui=createLazyOverlays(() => { calls++; return new Promise(r => { resolve=r; }); });
  ui.initOverlays('kiosk'); assert.equal(calls,0);
  const opening=ui.openGallery({},()=>current);
  const cancelled=ui.openGallery({},()=>current);
  current=false;resolve(module);await Promise.all([opening,cancelled]);
  assert.equal(calls,1);assert.equal(opened,0);
  current=true;await ui.openGallery({},()=>current);assert.equal(opened,1);
});

test('hidden rendering pauses, resumes without huge delta and never accumulates listeners', () => {
  const listeners=new Set(),frames=new Map();let id=0,rendered=0,lastDelta;
  const doc={hidden:false,addEventListener(_,fn) { listeners.add(fn); },removeEventListener(_,fn) { listeners.delete(fn); }};
  const options={document:doc,requestFrame:fn=>{frames.set(++id,fn);return id;},cancelFrame:i=>frames.delete(i)};
  const tick=t=>{const [i,fn]=frames.entries().next().value;frames.delete(i);fn(t);};
  for(let i=0;i<100;i++) {
    const stop=createRenderLoop(delta=>{rendered++;lastDelta=delta;},options);
    assert.equal(listeners.size,1);tick(0);tick(16);assert.equal(lastDelta,.016);
    doc.hidden=true;listeners.forEach(fn=>fn());assert.equal(frames.size,0);
    doc.hidden=false;listeners.forEach(fn=>fn());tick(100000);assert.equal(lastDelta,0);
    stop();assert.equal(listeners.size,0);assert.equal(frames.size,0);
  }
  assert.equal(rendered,300);
});

test('audio backpressure, cancellation and 100 kiosk rounds release buffers and callbacks', async () => {
  const sources=[];let closed=0,disconnected=0;
  class AudioContext {
    state='running';destination={};
    createAnalyser() { return {frequencyBinCount:128,connect() {},disconnect() { disconnected++; }}; }
    decodeAudioData(_,ok) { ok({duration:.1}); }
    createBufferSource() { return {connect() {},disconnect() {},start() {sources.push(this);},stop() {}}; }
    async close() { closed++; }
  }
  const context=vm.createContext({console,Uint8Array,Promise,Set,window:{AudioContext,atob:()=> 'a'}});
  vm.runInContext(fs.readFileSync(new URL('../src/audio/player.js',import.meta.url),'utf8').replace(/export /g,''),context);
  const run=code=>vm.runInContext(code,context);
  run("for(let i=0;i<9;i++) enqueueBase64Audio('a');globalThis.capacity=false;waitForAudioCapacity().then(()=>capacity=true)");
  await flush();assert.equal(context.capacity,false);assert.equal(run('bufferQueue.length'),8);
  sources[0].onended();await flush();assert.equal(context.capacity,true);
  run('stopCurrentAudio()');assert.equal(run('bufferQueue.length'),0);
  run('globalThis.finished=0');
  for(let i=0;i<100;i++) {
    run("beginAudioStream();enqueueBase64Audio('a');onAudioQueueFinished(()=>finished++);endAudioStream()");
    await flush();const source=sources.at(-1);source.onended();
    assert.equal(source.buffer,null);assert.equal(run('queueCallbacks.size'),0);
  }
  assert.equal(context.finished,100);assert.equal(run('isAudioBusy()'),false);
  await run('disposeAudio()');assert.equal(closed,1);assert.equal(disconnected,1);
  assert.equal(context.window.audioCtx,null);
});

test('versioned avatar URL is derived only from a validated public path and safe ETag', async () => {
  globalThis.window={location:{origin:'http://localhost:5173',hostname:'localhost'}};
  const {fetchAvatarUrl}=await import('../src/api/publicConfig.js');
  const revision='a'.repeat(64);
  const fetcher=async()=>({ok:true,headers:{get:()=>`"${revision}"`},json:async()=>({avatar:{id:'lia',name:'Lía',url:'/static/avatars/lia.vrm'}})});
  assert.equal(await fetchAvatarUrl(fetcher,x=>x),`/static/avatars/lia.vrm?v=${revision}`);
});

test('avatar disposed during loading cannot attach a late model and frees its scene', async () => {
  let resolve,disposed=0,added=0;
  class GLTFLoader { register() {} loadAsync() { return new Promise(r=>resolve=r); } }
  const context=vm.createContext({console,GLTFLoader,VRMLoaderPlugin:class {},
    fetchAvatarUrl:async()=>'/static/avatars/lia.vrm',VRMUtils:{deepDispose() { disposed++; }}});
  const source=fs.readFileSync(new URL('../src/avatar/loader.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/export /g,'');
  vm.runInContext(source,context);
  const loading=context.loadAvatar({add() {added++;}});await flush();
  context.disposeAvatar();resolve({scene:{},userData:{vrm:{scene:{}}}});await loading;
  assert.equal(added,0);assert.equal(disposed,1);assert.equal(context.getCurrentVrm(),null);
});

test('repeated controls setup/disposal removes window and microphone listeners', () => {
  const listeners=new Map(),micListeners=new Map(),recognizers=[];
  const attach=(map,name,fn)=>{const set=map.get(name)||new Set();set.add(fn);map.set(name,set);};
  const remove=(map,name,fn)=>map.get(name)?.delete(fn);
  const mic={addEventListener:(name,fn)=>attach(micListeners,name,fn),removeEventListener:(name,fn)=>remove(micListeners,name,fn)};
  class Recognition { constructor() { recognizers.push(this); } abort() {} }
  const context=vm.createContext({console,registrarActividad() {},
    document:{getElementById:name=>name==='mic-btn'?mic:null},
    setConnected() {},setVoiceAvailable() {},setAssistantState() {},canSend:()=>true,assistantState:()=> 'ready',
    window:{SpeechRecognition:Recognition,addEventListener:(name,fn)=>attach(listeners,name,fn),removeEventListener:(name,fn)=>remove(listeners,name,fn)}});
  const source=fs.readFileSync(new URL('../src/ui/controls.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/export /g,'');
  vm.runInContext(source,context);
  for(let i=0;i<100;i++) {
    context.initControls();context.initControls();
    assert.equal([...listeners.values()].reduce((n,set)=>n+set.size,0),4);
    assert.equal([...micListeners.values()].reduce((n,set)=>n+set.size,0),2);
    context.disposeControls();
    assert.equal([...listeners.values()].reduce((n,set)=>n+set.size,0),0);
    assert.equal([...micListeners.values()].reduce((n,set)=>n+set.size,0),0);
    assert.equal(recognizers.at(-1).onresult,null);assert.equal(recognizers.at(-1).onspeechstart,null);
  }
});

test('invalid VRM releases parsed resources without disabling conversation',async()=>{
  let freed=0;
  class GLTFLoader {register(){}async loadAsync(){return {scene:{},userData:{}};}}
  const context=vm.createContext({console:{warn(){}},GLTFLoader,VRMLoaderPlugin:class{},fetchAvatarUrl:async()=>'/static/avatars/broken.vrm',VRMUtils:{deepDispose(){freed++;}}});
  const source=fs.readFileSync(new URL('../src/avatar/loader.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/export /g,'');
  vm.runInContext(source,context);assert.equal(await context.loadAvatar({add(){assert.fail('Invalid model');}}),false);
  assert.equal(freed,1);assert.equal(context.getCurrentVrm(),null);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {setInitialized,setAssistantState,setConnected,canSend,assistantState,setVoiceAvailable} from '../src/ui/state.js';
import {bindDialog} from '../src/ui/modalAccessibility.js';

test('one state gates startup, processing, cancellation and offline recovery',()=>{
  setInitialized(false);assert.equal(canSend(),false);
  setInitialized(true);assert.equal(canSend(),true);
  setAssistantState('processing');assert.equal(canSend(),false);
  setAssistantState('speaking');assert.equal(assistantState(),'speaking');
  setAssistantState('cancelling');assert.equal(canSend(),false);
  setAssistantState('ready');setConnected(false);assert.equal(assistantState(),'offline');
  setConnected(true);assert.equal(canSend(),true);
  setVoiceAvailable(false);assert.equal(canSend(),true);
  setAssistantState('error');assert.equal(canSend(),true);
  setAssistantState('arbitrary');assert.equal(assistantState(),'error');
});
function controls({supported=false,mode='web',kioskText=false}={}) {
  const nodes={},requests=[],recognizers=[];let state='ready',voice=true;
  for(const id of ['text-form','text-message','stop-btn','capability-notice','mic-btn','subtitles','status-badge'])
    nodes[id]={events:{},hidden:true,value:'',classList:{add(){},remove(){}},addEventListener(name,fn){this.events[name]=fn;},removeEventListener(name){delete this.events[name];}};
  class Recognition {constructor(){recognizers.push(this);} abort(){this.aborts=(this.aborts||0)+1;} start(){this.starts=(this.starts||0)+1;} stop(){} }
  const context=vm.createContext({console,document:{getElementById:id=>nodes[id]},
    window:{navigator:{onLine:true},__liaPublicConfig:{visual:{kiosk_text_enabled:kioskText}},SpeechRecognition:supported?Recognition:null,addEventListener(){},removeEventListener(){}},
    setAssistantState:s=>state=s,assistantState:()=>state,setConnected(){},setVoiceAvailable:v=>voice=v,canSend:()=>state==='ready',
    registrarActividad(){},dispararSaludo(){},setIsListening(){},isCurrentlySpeaking:()=>false,unlockAudio(){},
    consultarAsistente:text=>requests.push(text),cancelarInteraccion(){}});
  const source=fs.readFileSync(new URL('../src/ui/controls.js',import.meta.url),'utf8').replace(/^import .*;\r?$/gm,'').replace(/export /g,'');
  vm.runInContext(source,context);context.initControls(mode);
  return {context,nodes,requests,recognizers,getVoice:()=>voice,getState:()=>state};
}
test('unsupported voice exposes text even kiosk disabled, using same conversation call',()=>{
  const h=controls({mode:'kiosk'});assert.equal(h.nodes['text-form'].hidden,false);assert.equal(h.getVoice(),false);
  h.nodes['text-message'].value=' Turismo ';h.nodes['text-form'].events.submit({preventDefault(){}});
  assert.deepEqual(h.requests,['Turismo']);assert.equal(h.nodes['text-message'].value,'');
});
test('microphone denial becomes text fallback without another permission request',()=>{
  const h=controls({supported:true,mode:'kiosk'});assert.equal(h.nodes['text-form'].hidden,true);
  h.recognizers[0].onerror({error:'not-allowed'});
  assert.equal(h.getVoice(),false);assert.equal(h.nodes['text-form'].hidden,false);
  assert.equal(h.recognizers[0].starts,undefined);assert.equal(h.recognizers[0].aborts,1);
});
test('kiosk text configuration and listening end cannot overwrite processing',()=>{
  const h=controls({supported:true,mode:'kiosk',kioskText:true});assert.equal(h.nodes['text-form'].hidden,false);
  h.recognizers[0].onresult({results:[[{transcript:'Turismo'}]]});h.recognizers[0].onend();
  assert.equal(h.getState(),'processing');assert.deepEqual(h.requests,['Turismo']);
});
test('dialog traps keyboard focus, Escape closes, removes listeners and restores focus',()=>{
  const listeners={},attributes={},doc={activeElement:null,addEventListener:(n,f)=>listeners[n]=f,removeEventListener:n=>delete listeners[n],querySelectorAll:()=>[root]};
  const previous={isConnected:true,focus(){doc.activeElement=this;}};doc.activeElement=previous;
  const first={disabled:false,hidden:false,getClientRects:()=>[{}],focus(){doc.activeElement=this;}},last={...first,focus(){doc.activeElement=this;}};
  const card={setAttribute:(k,v)=>attributes[k]=v,querySelector:()=>null,querySelectorAll:selector=>selector.startsWith('button,input')?[first,last]:[],contains:el=>[first,last].includes(el),focus(){doc.activeElement=this;}};
  const root={id:'dialog',querySelector:()=>card};let closed=0;
  const cleanup=bindDialog(root,()=>closed++,doc);
  assert.equal(attributes.role,'dialog');assert.equal(attributes['aria-modal'],'true');assert.equal(doc.activeElement,first);
  doc.activeElement=last;let prevented=0;listeners.keydown({key:'Tab',shiftKey:false,preventDefault(){prevented++;}});
  assert.equal(doc.activeElement,first);assert.equal(prevented,1);
  listeners.keydown({key:'Escape',preventDefault(){}});assert.equal(closed,1);
  cleanup();assert.equal(doc.activeElement,previous);assert.deepEqual(listeners,{});
});

test('online event cannot release controls while remote cancellation is pending',()=>{
  setInitialized(true);setAssistantState('cancelling');setConnected(false);setConnected(true);
  assert.equal(assistantState(),'cancelling');assert.equal(canSend(),false);
  setAssistantState('ready');assert.equal(canSend(),true);
  setAssistantState('processing');setConnected(true);assert.equal(assistantState(),'processing');
});

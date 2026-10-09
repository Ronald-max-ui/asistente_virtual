/** One visible state; transports and controls publish transitions, never badges. */
const labels = { initializing:'Iniciando…', ready:'Toca el micrófono para hablar', listening:'Escuchando…',
  processing:'Consultando…', responding:'Respondiendo…', speaking:'Hablando…', cancelling:'Deteniendo…',
  offline:'Sin conexión. Vuelve a intentarlo al conectarte.', error:'No se pudo completar. Puedes intentarlo de nuevo.' };
let current='initializing', online=true, initialized=false, voice=true;
const subscribers=new Set();
export function assistantState() { return online ? current : 'offline'; }
export function setAssistantState(value) {
  if (!Object.hasOwn(labels,value)) return;
  current=value; renderState();
}
export function setInitialized(value) { initialized=value; setAssistantState(value?'ready':'initializing'); }
export function setVoiceAvailable(value) { voice=value; renderState(); }
export function setConnected(value) { const changed=online!==value;online=value;
  if(value && changed && current!=='cancelling') current=initialized?'ready':'initializing';renderState(); }
export function canSend() { return initialized && online && ['ready','error'].includes(current); }
export function observeState(fn) { subscribers.add(fn); fn(assistantState()); return ()=>subscribers.delete(fn); }
function renderState() {
  const state=assistantState(), busy=['processing','responding','speaking','cancelling'].includes(state);
  const badge=globalThis.document?.getElementById('status-badge');
  if(badge) { badge.textContent=labels[state]; badge.className=state==='processing'?'thinking':state==='listening'?'listening':''; }
  for(const id of ['text-message','text-send']) { const el=globalThis.document?.getElementById(id); if(el) el.disabled=!canSend(); }
  const mic=globalThis.document?.getElementById('mic-btn'); if(mic) mic.disabled=!voice || !online || !initialized || busy;
  const stop=globalThis.document?.getElementById('stop-btn'); if(stop) {stop.hidden=!busy;stop.disabled=state==='cancelling';}
  for(const fn of subscribers) fn(state);
}

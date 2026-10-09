/** Keyboard/focus lifecycle for an already safely constructed dialog. */
export function bindDialog(root,close,doc=document) {
  const card=root.querySelector('.ov-modal-inner') || root;
  card.setAttribute('role','dialog');card.setAttribute('aria-modal','true');card.tabIndex=-1;
  const title=card.querySelector('h2,h3');
  if(title) { title.id=root.id+'-title';card.setAttribute('aria-labelledby',title.id); }
  else card.setAttribute('aria-label','Información de '+(globalThis.window?.__liaPublicConfig?.assistant?.name||'Lía'));
  const previous=doc.activeElement;
  const elements=()=>[...card.querySelectorAll('button,input:not([type="hidden"]),textarea,select,a[href],[tabindex="0"]')]
    .filter(el=>!el.disabled && !el.hidden && el.getClientRects().length);
  for(const el of card.querySelectorAll('input:not([type="hidden"]),textarea')) {
    if(!el.id) el.id=root.id+'-'+el.name;
    const label=el.closest('.ov-field')?.querySelector('label');if(label) label.htmlFor=el.id;
  }
  for(const button of card.querySelectorAll('.ov-close')) button.setAttribute('aria-label','Cerrar diálogo');
  for(const msg of card.querySelectorAll('.ov-msg')) {msg.setAttribute('role','status');msg.setAttribute('aria-live','polite');}
  const isTop=()=>[...doc.querySelectorAll('.ov-visible')].at(-1)===root;
  const key=(event)=>{
    if(!isTop()) return;
    if(event.key==='Escape') {event.preventDefault();close();}
    if(event.key==='Tab') {
      const list=elements(),first=list[0]||card,last=list.at(-1)||card;
      if(!list.length || (event.shiftKey && (doc.activeElement===first || !card.contains(doc.activeElement)))) {event.preventDefault();last.focus();}
      else if(!event.shiftKey && (doc.activeElement===last || !card.contains(doc.activeElement))) {event.preventDefault();first.focus();}
    }
  };
  const focus=(event)=>{if(isTop() && !card.contains(event.target)) (elements()[0]||card).focus();};
  doc.addEventListener('keydown',key);doc.addEventListener('focusin',focus);
  const initial=()=>{if(isTop()) (card.querySelector('input:not([type="hidden"]),textarea')||elements()[0]||card).focus();};
  initial();
  // CSS visibility transitions can reject focus during the opening frame.
  const focusTimer=setTimeout(initial,350);
  return ()=>{clearTimeout(focusTimer);doc.removeEventListener('keydown',key);doc.removeEventListener('focusin',focus);
    if(previous?.isConnected) previous.focus();};
}

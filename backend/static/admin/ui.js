export function el(tag, attributes = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key,value] of Object.entries(attributes)) {
        if (key === 'class') node.className = value;
        else if (key === 'on') { for (const [event,handler] of Object.entries(value)) node.addEventListener(event,handler); }
        else if (key in node && !key.startsWith('aria')) node[key] = value;
        else node.setAttribute(key, value);
    }
    for (const child of children.flat()) if (child !== null && child !== undefined) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    return node;
}
export const button = (text,handler,kind='secondary small') => el('button',{type:'button',class:kind,on:{click:handler}},text);
export const statusNames={active:'Activo',free:'Gratis',pending:'Pendiente',inactive:'Inactivo',pending_review:'Pendiente de revisión',approved:'Aprobado',rejected:'Rechazado',current:'Activa',installed:'Instalado',upcoming:'Próxima',ended:'Finalizada',disabled:'Deshabilitada'};
export const badge = state => el('span',{class:'badge '+state},statusNames[state] || state);
export function money(amount,currency='PEN',status) {
    if (status==='pending' || amount===null || amount===undefined || amount==='') return 'Pendiente';
    const value=String(amount); if (!/^\d+(?:\.\d{1,2})?$/.test(value)) return 'Importe no disponible';
    const [whole,fraction='']=value.split('.'); return (currency==='PEN'?'S/ ':currency+' ')+whole+'.'+fraction.padEnd(2,'0');
}
export const dateText = value => value ? new Intl.DateTimeFormat('es-PE',{dateStyle:'short',timeStyle:'short',timeZone:'America/Lima'}).format(new Date(typeof value==='number'?value*1000:value)) : '—';
export function table(headers,rows) {
    const body=el('tbody',{},...rows.map(row=>el('tr',{},...row.map(cell=>el('td',{},cell)))));
    return rows.length ? el('div',{class:'table-scroll'},el('table',{},el('thead',{},el('tr',{},...headers.map(h=>el('th',{scope:'col'},h)))),body)) : el('div',{class:'empty'},'No hay registros para mostrar.');
}
export function heading(title,subtitle,action) {return el('div',{class:'heading'},el('div',{},el('h1',{},title),el('p',{class:'muted'},subtitle)),action);}
const toastTimers=new Map();
export function notify(text) {
    const region=document.querySelector('#notifications');
    while(region.children.length>=2){const old=region.firstElementChild;clearTimeout(toastTimers.get(old));toastTimers.delete(old);old.remove();}
    const node=el('div',{class:'toast'},text);region.append(node);toastTimers.set(node,setTimeout(()=>{node.remove();toastTimers.delete(node);},6500));
}
export function dialog(title,content,{submit,onSubmit,onClose}={}) {
    const previous=document.activeElement;
    const node=el('dialog',{role:'dialog','aria-modal':'true','aria-labelledby':'dialog-title-'+crypto.randomUUID()});
    const name=el('h2',{id:node.getAttribute('aria-labelledby')},title);
    const form=el('form',{},name,content);const message=el('p',{class:'error-box',role:'alert',hidden:true});form.append(message);
    let busy=false;
    const close=()=>{if(busy)return;node.close();node.remove();onClose?.();(previous?.isConnected?previous:document.querySelector('#content'))?.focus({preventScroll:true});};
    const cancel=button('Cerrar',close,'secondary');
    const save=submit?el('button',{type:'submit'},submit):null;
    form.append(el('div',{class:'dialog-actions'},cancel,save));node.append(form);document.body.append(node);node.showModal();
    node.addEventListener('cancel',event=>{event.preventDefault();close();});
    node.addEventListener('keydown',event=>{
        if(event.key!=='Tab')return;
        const focusable=[...node.querySelectorAll('button,input,select,textarea,a[href],[tabindex]')].filter(control=>!control.disabled && control.tabIndex>=0 && control.getClientRects().length);
        const first=focusable[0],last=focusable.at(-1);
        if(!first){event.preventDefault();node.focus();return;}
        if(event.shiftKey && document.activeElement===first){event.preventDefault();last.focus();}
        else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first.focus();}
    });
    form.addEventListener('submit',async event=>{event.preventDefault();if(busy)return;busy=true;cancel.disabled=true;if(save)save.disabled=true;message.hidden=true;
        try {await onSubmit?.(new FormData(form),form);busy=false;close();}
        catch(error){message.textContent=error.message;message.hidden=false;busy=false;cancel.disabled=false;if(save)save.disabled=false;}
    });
    return {node,form,close,forceClose:()=>{busy=false;close();}};
}
export function confirmChange(title,description) {return new Promise(resolve=>{let confirmed=false;dialog(title,description,{submit:'Confirmar cambio',onSubmit:async()=>{confirmed=true;},onClose:()=>resolve(confirmed)});});}
export function field(name,label,{value='',type='text',options,required=false,max=120,help,wide=false,disabled=false}={}) {
    const id='field-'+name+'-'+crypto.randomUUID();const input=options?el('select',{id,name,required,disabled},...options.map(([v,text])=>el('option',{value:v},text))):type==='textarea'?el('textarea',{id,name,maxLength:max,required,disabled}):el('input',{id,name,type,required,disabled,maxLength:max});
    if(type==='checkbox')input.checked=!!value;else input.value=options && !options.some(([key])=>key===(value??'')) ? options[0]?.[0]??'' : value??'';
    const wrapper=el('div',{class:wide?'wide':''},el('label',{htmlFor:id},label+(required?' *':'')),input);
    if(help){const hint=el('p',{id:id+'-help',class:'help'},help);input.setAttribute('aria-describedby',hint.id);wrapper.append(hint);}
    input.addEventListener('invalid',()=>{let error=wrapper.querySelector('.field-error');if(!error){error=el('p',{class:'field-error'});wrapper.append(error);}error.textContent='Completa este campo con un valor válido.';input.setAttribute('aria-invalid','true');});
    input.addEventListener('input',()=>{wrapper.querySelector('.field-error')?.remove();input.removeAttribute('aria-invalid');});return wrapper;
}
export const clean = record => Object.fromEntries(Object.entries(record).filter(([key])=>!['created_at','updated_at','created_by','updated_by','phase'].includes(key)));
export const listValue = value => value.split(',').map(v=>v.trim()).filter(Boolean);
export function pager(root,offset,next,change){root.append(el('div',{class:'toolbar'},el('span',{class:'muted'},'Página '+(offset/20+1)),el('div',{class:'actions'},el('button',{type:'button',class:'secondary',disabled:offset===0,on:{click:()=>change(offset-20)}},'Anterior'),el('button',{type:'button',class:'secondary',disabled:!next,on:{click:()=>change(offset+20)}},'Siguiente'))));}

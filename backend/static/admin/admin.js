import {commercialDashboard} from './leadScreens.js';
import {createAdminClient} from './adminClient.js';
import {el,button,heading,notify,dialog,confirmChange} from './ui.js';
import {allowedModules} from './navigation.js';
import {commercialScreen} from './commercialScreens.js';
import {operationalScreen} from './operationalScreens.js';
import {userScreen} from './userScreens.js';
const api=createAdminClient();
const login=document.querySelector('#login'),session=document.querySelector('#session'),access=document.querySelector('#access'),root=document.querySelector('#content'),status=document.querySelector('#status'),logout=document.querySelector('#logout'),navigation=document.querySelector('#navigation');
const state={user:null,module:'dashboard',offset:0,filter:{},busy:false,editor:null,draft:null,tracked:null,generation:0,data:{}};
function setStatus(value){status.textContent=value;}
function show(user){state.user=user;access.hidden=!!user;session.hidden=!user;login.hidden=!!user;document.querySelector('#identity').textContent=user?.display_name||'';document.querySelector('#password').value='';}
function expire(){
    if(state.editor){const editor=state.editor;for(const input of editor.content.querySelectorAll('input[type=password]'))input.value='';state.draft={...editor,userId:state.user?.id,module:state.module};editor.dialog.forceClose();}
    else if(state.tracked?.dirty){state.draft={...state.tracked,userId:state.user?.id,module:state.module,appearance:true};}
    state.tracked?.cleanup?.();show(null);setStatus(state.draft?'Tu sesión venció. El borrador se conserva en esta pestaña; inicia sesión con la misma identidad.':'Tu sesión venció. Inicia sesión nuevamente.');document.querySelector('#username').focus();
}
async function run(work,form){
    if(state.busy)return;state.busy=true;setStatus('Procesando…');const buttons=[...document.querySelectorAll('#login button,#logout'),...(form?[...form.querySelectorAll('button')]:[])];for(const b of buttons)b.disabled=true;
    try {await work();setStatus(state.user?'Listo.':'Inicia sesión.');}
    catch(error){if(error.status===401)expire();else{setStatus(error.message);notify(error.message);}}
    finally{state.busy=false;for(const b of buttons)b.disabled=false;}
}
function trackForm(form,restore,cleanup){
    const entry={content:form,restore,cleanup,dirty:false};state.tracked=entry;form.addEventListener('input',()=>entry.dirty=true);form.addEventListener('change',()=>entry.dirty=true);
}
function editor(title,content,onSubmit,restore,submit='Guardar'){
    const entry={title,content,onSubmit,restore,submit};state.editor=entry;
    entry.dialog=dialog(title,content,{submit,onSubmit:async data=>{try {await onSubmit(data);notify('Cambios guardados.');}catch(error){if(error.status===401)expire();throw error;}},onClose:()=>{if(state.editor===entry)state.editor=null;}});
}
function context(container){return {root:container,data:state.data,api,can:permission=>state.user?.permissions.includes(permission),run,editor,trackForm,refresh:async()=>{await navigate(state.module,state.offset,state.filter,true);},navigate};}
async function dashboard(ctx){
    const data=await api.request('/panel/dashboard');ctx.root.append(heading('Dashboard','Resumen de la institución. Sólo se muestran datos autorizados.'));
    const cards=el('div',{class:'cards'});for(const [key,label] of [['active_programs','Programas activos'],['current_campaigns','Campañas vigentes'],['recent_leads','Prospectos en los últimos 7 días'],['pending_vouchers','Comprobantes pendientes'],['avatar','Avatar activo']])if(key in data)cards.append(el('article',{class:'card'},el('h2',{},label),el('p',{class:'metric'},data[key]??'Sin configurar')));
    cards.append(el('article',{class:'card'},el('h2',{},'Estado de Lía'),el('p',{},data.operational?'Lía operativa':'Requiere atención'),el('p',{class:'help'},data.knowledge==='ready'?'Conocimiento listo':data.knowledge==='stale'?'Conocimiento disponible; actualización pendiente':'Conocimiento no disponible')));ctx.root.append(cards);
    if(ctx.can('leads.read'))await commercialDashboard(ctx);
}
async function navigate(module,offset=0,filter={},force=false){
    if(!state.user || !allowedModules(state.user.permissions).some(([key])=>key===module))return;
    if(state.tracked?.dirty&&!force){if(!await confirmChange('Cambios sin guardar',el('p',{},'¿Descartar el formulario abierto y cambiar de pantalla?')))return;}
    state.tracked?.cleanup?.();state.tracked=null;state.module=module;state.offset=offset;state.filter=filter;const generation=++state.generation;
    const container=el('div',{'aria-busy':'true'});root.replaceChildren(container);container.append(el('p',{role:'status'},'Cargando…'));navigation.classList.remove('open');document.querySelector('#menu-toggle').setAttribute('aria-expanded','false');
    for(const item of navigation.querySelectorAll('button')){if(item.dataset.module===module)item.setAttribute('aria-current','page');else item.removeAttribute('aria-current');}
    try {
        state.data=await api.request('/panel/context');if(generation!==state.generation)return;container.replaceChildren();const ctx=context(container);
        if(module==='dashboard')await dashboard(ctx);else if(['leads','vouchers','audit'].includes(module))await operationalScreen(ctx,module,offset,filter);else if(module==='users')await userScreen(ctx,offset);else await commercialScreen(ctx,module);
        container.setAttribute('aria-busy','false');
        if(generation===state.generation){root.focus({preventScroll:true});window.scrollTo(0,0);setStatus('Listo.');}
    }catch(error){container.setAttribute('aria-busy','false');if(generation!==state.generation)return;if(error.status===401)expire();else{container.replaceChildren(el('p',{class:'error-box',role:'alert'},error.message),button('Reintentar',()=>navigate(module,offset,filter,true)));setStatus(error.message);}}
}
async function enter(user){
    const draft=state.draft;show(user);navigation.replaceChildren(...allowedModules(user.permissions).map(([key,label])=>{const node=button(label,()=>navigate(key),'');node.dataset.module=key;return node;}));
    await navigate(draft?.userId===user.id?draft.module:'dashboard',0,{},true);
    if(draft && draft.userId===user.id){
        state.draft=null;
        const permission=draft.module==='appearance'?'settings.write':draft.module==='vouchers'?'vouchers.review':draft.module==='users'?'users.write':draft.module+'.write';
        if(user.permissions.includes(permission)){
            if(await confirmChange('Recuperar borrador',el('p',{},'Tu sesión anterior venció. Puedes recuperar el formulario; el backend comprobará si el registro cambió.'))){
                if(draft.appearance){const current=root.querySelector('form');if(current){current.replaceWith(draft.content);state.tracked=draft;state.tracked.dirty=true;}}
                else editor(draft.title,draft.content,draft.onSubmit,draft.restore,draft.submit);
            }
        }else{state.draft=draft;notify('Tus permisos cambiaron. El borrador sigue en memoria, pero no puedes modificar este módulo.');}
    }else if(draft){state.draft=null;notify('El borrador de otra identidad se descartó por privacidad.');}
}
login.addEventListener('submit',event=>{event.preventDefault();run(async()=>{const password=document.querySelector('#password').value;document.querySelector('#password').value='';const user=await api.login(document.querySelector('#username').value,password);await enter(user);},login);});
logout.addEventListener('click',()=>run(async()=>{if(state.tracked?.dirty || state.editor){if(!await confirmChange('Cerrar sesión',el('p',{},'Los cambios sin guardar se descartarán.')))return;}await api.logout();state.editor?.dialog.forceClose();state.draft=null;state.tracked?.cleanup?.();state.tracked=null;state.data={};root.replaceChildren();show(null);setStatus('Inicia sesión.');document.querySelector('#username').focus();}));
document.querySelector('#menu-toggle').addEventListener('click',()=>{const open=navigation.classList.toggle('open');document.querySelector('#menu-toggle').setAttribute('aria-expanded',String(open));});
window.addEventListener('offline',()=>setStatus('Sin conexión. Los formularios permanecen en esta pestaña.'));
window.addEventListener('online',()=>{setStatus('Conexión recuperada. Puedes reintentar la operación.');notify('Conexión recuperada. No se reenviaron operaciones automáticamente.');});
window.addEventListener('beforeunload',event=>{if(state.editor||state.tracked?.dirty){event.preventDefault();event.returnValue='';}});
run(async()=>{try{await enter(await api.me());}catch(error){if(error.status!==401)throw error;show(null);setStatus('Inicia sesión.');}});

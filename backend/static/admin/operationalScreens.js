import {leadScreen} from './leadScreens.js';
import {el,button,badge,money,dateText,table,heading,field,dialog,pager,notify} from './ui.js';
import {conceptName} from './commercialScreens.js';
const name=(ctx,program)=>ctx.data.programs?.find(p=>p.id===program)?.name || program || '—';
export async function operationalScreen(ctx,module,offset=0,filter={}){
    const root=ctx.root;
    if(module==='leads'){
        await leadScreen(ctx,offset,filter);
    }else if(module==='vouchers'){
        const query=new URLSearchParams({limit:21,offset});if(filter.status)query.set('status',filter.status);
        const rows=await ctx.api.request('/vouchers?'+query);
        const counts=await ctx.api.request('/operations/voucher-counts');
        root.append(heading('Comprobantes','La revisión administrativa no representa conciliación bancaria automática.'));
        root.append(el('p',{class:'help'},'Pendientes: '+(counts.pending_review||0)+' · Aprobados: '+(counts.approved||0)+' · Rechazados: '+(counts.rejected||0)));
        const filters=el('div',{class:'filters'},field('status','Estado',{value:filter.status||'',options:[['','Todos'],['pending_review','Pendiente de revisión'],['approved','Aprobado'],['rejected','Rechazado']]}));root.append(filters);
        filters.addEventListener('change',()=>ctx.navigate(module,0,{status:filters.querySelector('select').value}));
        root.append(table(['Fecha','Prospecto','Programa','Concepto','Importe','Estado','Acciones'],rows.slice(0,20).map(r=>[dateText(r.created_at),r.lead_name||'Sin prospecto asociado',name(ctx,r.program),conceptName(r.concept),money(r.amount,r.currency),badge(r.status),button('Ver comprobante',()=>ctx.run(()=>reviewVoucher(ctx,r)))])));
        pager(root,offset,rows.length>20,page=>ctx.navigate(module,page,filter));
    }else if(module==='audit'){
        const query=new URLSearchParams({limit:21,offset});for(const [key,value] of Object.entries(filter))if(value)query.set(key,value);
        const rows=await ctx.api.request('/audit?'+query);
        root.append(heading('Auditoría','Registro inmutable de operaciones administrativas. Zona horaria: America/Lima.'));
        let users=[];if(ctx.can('users.read'))users=await ctx.api.request('/users?limit=100');
        const controls=el('form',{class:'filters'},field('actor_user_id','Persona',{value:filter.actor_user_id||'',options:[['','Todas'],...users.map(u=>[u.id,u.display_name])],help:users.length===100?'Mostrando los primeros 100 usuarios.':undefined}),field('resource_type','Recurso',{value:filter.resource_type||'',options:[['','Todos'],...['programs','prices','campaigns','avatars','settings','users','vouchers','sessions','leads','lead_tasks'].map(r=>[r,r])]}),field('action','Acción',{value:filter.action||'',max:64,help:'Por ejemplo: prices.save'}),field('since','Desde',{value:filter.since||'',type:'date'}),field('until','Hasta',{value:filter.until||'',type:'date'}),el('button',{type:'submit'},'Filtrar'));
        controls.addEventListener('submit',event=>{event.preventDefault();ctx.navigate(module,0,Object.fromEntries(new FormData(controls)));});root.append(controls);
        root.append(table(['Fecha','Persona','Acción','Recurso','Resultado','Detalles'],rows.slice(0,20).map(r=>[dateText(r.timestamp),r.actor_name||'Operación administrativa',auditTitle(ctx,r),r.resource_type,r.result,button('Ver detalle',()=>auditDetail(ctx,r))])));
        pager(root,offset,rows.length>20,page=>ctx.navigate(module,page,filter));
    }
}
async function reviewVoucher(ctx,record){
    const image=el('img',{class:'voucher-image',src:'/api/admin/panel/vouchers/'+encodeURIComponent(record.voucher_id)+'/file',alt:'Imagen del comprobante seleccionado'});
    const content=el('div',{},el('p',{},(record.lead_name||'Sin prospecto asociado')+' · '+name(ctx,record.program)),el('p',{},conceptName(record.concept)+' · Importe validado al recibir: '+money(record.amount,record.currency)+' · '+dateText(record.created_at)),badge(record.status),image);
    image.addEventListener('error',()=>{image.hidden=true;content.append(el('p',{role:'alert',class:'error-box'},'No se pudo abrir la imagen. Verifica tu sesión y vuelve a intentarlo.'));});
    if(record.status==='pending_review' && ctx.can('vouchers.review')){
        content.append(field('status','Decisión',{options:[['approved','Aprobar'],['rejected','Rechazar']]}),field('review_note','Nota del revisor',{type:'textarea',max:1000,help:'Texto plano. La decisión queda registrada y no puede revertirse silenciosamente.'}));
        ctx.editor('Revisar comprobante',content,async data=>{await ctx.api.request('/vouchers/'+record.voucher_id+'/review','POST',{status:data.get('status'),review_note:data.get('review_note')});await ctx.refresh();notify('Revisión registrada.');},()=>reviewVoucher(ctx,record),'Guardar revisión');
    }else{content.append(el('p',{class:'help'},record.review_note||'Sin nota de revisión.'),el('p',{class:'help'},record.reviewed_at?'Revisado: '+dateText(record.reviewed_at):'Comprobante recibido y pendiente de revisión.'));dialog('Comprobante',content);}
}
const labels={programs:'programa',prices:'tarifa',campaigns:'campaña',avatars:'avatar',settings:'configuración',users:'usuario',vouchers:'comprobante',sessions:'sesión'};
export function auditTitle(ctx,record){
    const operation={'leads.tracking':'Seguimiento administrativo actualizado','leads.note':'Nota agregada','leads.call':'Llamada registrada','leads.whatsapp_manual':'WhatsApp manual registrado','leads.task_created':'Seguimiento programado','leads.task_completed':'Seguimiento completado','leads.task_cancelled':'Seguimiento cancelado','leads.export':'Prospectos exportados'}[record.action];
    if(operation)return record.action==='leads.tracking'&&record.after?.status==='converted'&&record.before?.status!=='converted'?'Conversión comercial registrada':operation;
    if(record.resource_type==='prices'){const price=record.after||record.before;return 'Cambio de '+conceptName(price?.concept)+' · '+name(ctx,price?.program)+' · '+money(record.before?.amount,record.before?.currency,record.before?.status)+' → '+money(record.after?.amount,record.after?.currency,record.after?.status);}
    return (record.action==='avatars.activate'?'Selección de avatar':'Cambio de '+(labels[record.resource_type]||'registro'))+(record.after?.name?' · '+record.after.name:'');
}
function snapshotView(record){const details=el('dl');if(!record)return el('p',{class:'muted'},'Sin registro anterior.');for(const [key,value] of Object.entries(record)){details.append(el('dt',{},key.replaceAll('_',' ')),el('dd',{},value===null?'Pendiente / sin especificar':Array.isArray(value)?value.map(v=>typeof v==='object'?'Promoción registrada':v).join(', '):typeof value==='boolean'?(value?'Sí':'No'):String(value)));}return details;}
function auditDetail(ctx,record){dialog('Detalle de auditoría',el('div',{},el('p',{},auditTitle(ctx,record)),el('p',{class:'muted'},dateText(record.timestamp)+' · '+(record.actor_name||'Operación administrativa')),el('div',{class:'audit-detail'},el('section',{},el('h3',{},'Antes'),snapshotView(record.before)),el('section',{},el('h3',{},'Después'),snapshotView(record.after)))));}

import {el,button,badge,dateText,table,heading,field,pager,notify,confirmChange} from './ui.js';
export const roles=[['superadmin','Superadministrador'],['administrador','Administrador'],['admisiones','Admisiones'],['revisor_pagos','Revisor de pagos'],['solo_lectura','Sólo lectura']];
export async function userScreen(ctx,offset=0){
    const rows=await ctx.api.request('/users?limit=21&offset='+offset);
    ctx.root.append(heading('Usuarios','Identidades individuales. Los cambios de rol se aplican a las siguientes operaciones.',ctx.can('users.write')?button('Nuevo usuario',()=>ctx.run(()=>editUser(ctx)), ''):null));
    ctx.root.append(table(['Nombre','Usuario','Rol','Estado','Último acceso','Acciones'],rows.slice(0,20).map(user=>{const actions=el('div',{class:'actions'});if(ctx.can('users.write'))actions.append(button('Editar',()=>ctx.run(()=>editUser(ctx,user))),button('Restablecer contraseña',()=>ctx.run(()=>resetPassword(ctx,user))));if(ctx.can('sessions.revoke'))actions.append(button('Revocar sesiones',()=>ctx.run(async()=>{if(await confirmChange('Revocar sesiones',el('p',{},'Todas las sesiones de '+user.display_name+' perderán acceso.'))) {await ctx.api.request('/users/'+user.id+'/sessions/revoke-all','POST');notify('Sesiones revocadas.');}})));return [user.display_name,user.username,roles.find(([id])=>id===user.role_id)?.[1]||user.role_id,badge(user.enabled?'active':'inactive'),dateText(user.last_login_at),actions];})));
    pager(ctx.root,offset,rows.length>20,page=>ctx.navigate('users',page));
}
async function editUser(ctx,user){
    const original=user?await ctx.api.request('/users/'+user.id):null;
    const expected=ctx.api.revision('/users/'+original?.id);
    const form=el('div',{class:'form-grid'},field('display_name','Nombre visible',{value:original?.display_name||'',required:true,wide:true}),field('role','Rol',{value:original?.role_id||'solo_lectura',options:roles}),field('enabled','Habilitado',{value:original?.enabled??true,type:'checkbox'}));
    if(!original){form.prepend(field('username','Usuario / email',{required:true,wide:true}));form.append(field('password','Contraseña inicial',{type:'password',required:true,max:256,wide:true,help:'Mínimo 12 caracteres variados. No se conserva en borradores.'}));}
    ctx.editor(original?'Editar usuario':'Crear usuario',form,async data=>{let body={display_name:data.get('display_name'),role:data.get('role'),enabled:data.has('enabled')};if(!original){delete body.enabled;body.username=data.get('username');body.password=data.get('password');}await ctx.api.request('/users'+(original?'/'+original.id:''),original?'PUT':'POST',body,expected);await ctx.refresh();},()=>editUser(ctx,user));
}
async function resetPassword(ctx,user){
    const content=el('div',{},el('p',{},user.display_name),field('password','Nueva contraseña',{type:'password',required:true,max:256,help:'Mínimo 12 caracteres variados. Revoca todas las sesiones existentes.'}));
    ctx.editor('Restablecer contraseña',content,async data=>{await ctx.api.request('/users/'+user.id+'/password','PUT',{password:data.get('password')});content.querySelector('input').value='';notify('Contraseña cambiada; sesiones revocadas.');},null,'Cambiar contraseña');
}

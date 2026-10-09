import {el,button,heading,field,notify} from './ui.js';
export function readableText(color){
    if(!/^#[a-fA-F0-9]{6}$/.test(color||''))return '#ffffff';
    const c=[1,3,5].map(i=>parseInt(color.slice(i,i+2),16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
    const l=c[0]*.2126+c[1]*.7152+c[2]*.0722;return (l+.05)/.05>=1.05/(l+.05)?'#000000':'#ffffff';
}
export function imageUrl(value){return typeof value==='string'&&/^\/static\/(?:media|branding)\/[a-zA-Z0-9_-]+\.(?:png|webp|jpe?g)(?:\?v=[a-f0-9]{64})?$/.test(value)?value:null;}
export async function appearanceScreen(ctx){
    const original=await ctx.api.request('/settings'),expected=ctx.api.revision('/settings');
    const [voices,assets]=await Promise.all([ctx.api.request('/voices'),ctx.api.request('/branding-assets')]);
    const editable=ctx.can('settings.write'),avatars=ctx.data.avatars||[];
    ctx.root.append(heading('Apariencia','Identidad y voz de esta instalación. Los cambios se aplican en la siguiente carga o conversación.'));
    const form=el('form',{class:'personalization'});ctx.root.append(form);
    const section=(name,...children)=>{const node=el('section',{class:'card'},el('h2',{},name),el('div',{class:'form-grid'},...children));form.append(node);return node;};
    const assetFields=purpose=>{
        const name=purpose+'_url',current=original[name]||'';
        const items=[['','Sin configurar'],...assets.filter(a=>a.purpose===purpose).map(a=>[a.url,'Imagen '+a.id.slice(0,8)+' · '+a.width+'×'+a.height])];
        if(current&&!items.some(([url])=>url===current))items.push([current,'Recurso instalado actual']);
        const selection=field(name,purpose==='logo'?'Logo institucional':'Favicon',{value:current,options:items,wide:true});
        if(editable){const file=field(purpose+'_file','Cargar '+purpose,{type:'file',wide:true,help:purpose==='favicon'?'PNG, JPEG o WebP cuadrado, hasta 512 px. Máximo 2 MiB.':'PNG, JPEG o WebP. Máximo 2 MiB y 2048 px. SVG no admitido.'});file.querySelector('input').accept='image/png,image/jpeg,image/webp';
            selection.append(file,button('Subir '+purpose,()=>ctx.run(async()=>{
                const input=file.querySelector('input'),selected=input.files[0];if(!selected)throw new Error('Selecciona una imagen.');
                const data=new FormData();data.append('purpose',purpose);data.append('file',selected);
                const asset=await ctx.api.request('/branding-assets','POST',data);const select=selection.querySelector('select');select.append(el('option',{value:asset.url},'Imagen recién cargada'));select.value=asset.url;input.value='';select.dispatchEvent(new Event('change',{bubbles:true}));notify('Imagen validada. Guarda los cambios para utilizarla.');
            },form)));}
        return selection;
    };
    section('Identidad',field('assistant_name','Nombre del asistente',{value:original.assistant_name,required:true}),field('primary_color','Color principal',{value:original.primary_color||'',help:'#RRGGBB. El texto del botón será claro u oscuro según contraste.'}),assetFields('logo'),assetFields('favicon'));
    const currentVoice=original.voice||{},voice=voices.current||{};
    const options=voices.voices.map(v=>[v.id,v.name+' · '+v.language+' · '+v.id]);
    if(!options.some(([id])=>id===currentVoice.voice_id)&&currentVoice.voice_id)options.unshift(['','Voz anterior no válida: selecciona una voz']);
    const avatarOptions=[['','Sin avatar'],...avatars.filter(a=>a.enabled).map(a=>[a.id,a.name])];
    if(original.active_avatar_id&&!avatarOptions.some(([id])=>id===original.active_avatar_id))avatarOptions.push([original.active_avatar_id,'Avatar configurado no disponible']);
    const assistant=section('Asistente',field('active_avatar_id','Avatar instalado',{value:original.active_avatar_id||'',options:avatarOptions,disabled:!ctx.can('avatars.write'),help:'Sólo avatares instalados por un operador. No se cargan archivos VRM.'}),field('voice_id','Voz',{value:currentVoice.voice_id||voice.voice_id||'',options,required:true,wide:true}),field('voice_enabled','Respuesta hablada',{type:'checkbox',value:currentVoice.enabled??true}),field('voice_rate','Velocidad',{value:currentVoice.rate||'+10%',help:'De -50% a +50%; incluye signo.'}),field('voice_pitch','Tono',{value:currentVoice.pitch||'+0Hz',help:'De -100Hz a +100Hz; incluye signo.'}),field('voice_volume','Volumen',{value:currentVoice.volume||'+0%',help:'De -50% a +50%; incluye signo.'}),field('initial_message','Mensaje inicial',{value:original.initial_message||'',type:'textarea',max:500,wide:true,help:'Texto visible. No es un prompt ni acepta HTML.'}));
    if(voice.status==='degraded')assistant.append(el('p',{class:'error-box',role:'status'},'La voz configurada no es válida. La conversación seguirá disponible por texto.'));
    section('Kiosk',field('kiosk_text_enabled','Permitir entrada escrita en kiosk',{type:'checkbox',value:original.kiosk_text_enabled}));
    const preview=el('div',{class:'brand-preview'}),audio=el('audio',{controls:true,hidden:true});section('Vista previa',preview,audio);
    const get=name=>form.querySelector('[name='+name+']'),voiceBody=()=>({provider:'edge',voice_id:get('voice_id').value,rate:get('voice_rate').value,pitch:get('voice_pitch').value,volume:get('voice_volume').value,enabled:get('voice_enabled').checked});
    let audioUrl=null,previewEpoch=0;const cleanup=()=>{previewEpoch++;audio.pause();audio.removeAttribute('src');if(audioUrl)URL.revokeObjectURL(audioUrl);audioUrl=null;};audio.addEventListener('ended',cleanup);
    if(editable)assistant.append(button('Probar voz',()=>ctx.run(async()=>{
        cleanup();const epoch=previewEpoch;const result=await ctx.api.request('/voice-preview','POST',voiceBody());if(!form.isConnected||epoch!==previewEpoch)return;
        const raw=atob(result.audio_b64),bytes=Uint8Array.from(raw,c=>c.charCodeAt(0));audioUrl=URL.createObjectURL(new Blob([bytes],{type:'audio/mpeg'}));audio.src=audioUrl;audio.hidden=false;try{await audio.play();}catch{notify('Usa el control de audio para escuchar la prueba.');}
    },form)));
    const render=()=>{const color=get('primary_color').value;preview.style.background=/^#[a-fA-F0-9]{6}$/.test(color)?color:'#243149';preview.style.color=readableText(color);preview.replaceChildren(el('h3',{},get('assistant_name').value),el('p',{},get('initial_message').value));const logo=imageUrl(get('logo_url').value);if(logo){const img=el('img',{src:logo,alt:'Logo en vista previa'});img.addEventListener('error',()=>img.remove(),{once:true});preview.prepend(img);}const avatar=avatars.find(a=>a.id===get('active_avatar_id').value);if(avatar){const thumbnail=imageUrl(avatar.thumbnail_url);if(thumbnail)preview.append(el('img',{src:thumbnail,alt:'Miniatura de '+avatar.name}));preview.append(el('p',{},'Avatar: '+avatar.name));}};
    form.addEventListener('input',render);form.addEventListener('change',render);render();
    for(const input of form.querySelectorAll('input,select,textarea'))if(!editable)input.disabled=true;
    if(editable){form.append(el('button',{type:'submit'},'Guardar cambios'));form.addEventListener('submit',event=>{event.preventDefault();ctx.run(async()=>{
        const body={...original,assistant_name:get('assistant_name').value,primary_color:get('primary_color').value||null,logo_url:get('logo_url').value||null,favicon_url:get('favicon_url').value||null,active_avatar_id:ctx.can('avatars.write')?get('active_avatar_id').value||null:original.active_avatar_id,initial_message:get('initial_message').value,kiosk_text_enabled:get('kiosk_text_enabled').checked,voice:voiceBody()};
        await ctx.api.request('/settings','PUT',body,expected);await ctx.refresh();notify('Personalización guardada.');
    },form);});}
    ctx.trackForm(form,()=>appearanceScreen(ctx),cleanup);
}

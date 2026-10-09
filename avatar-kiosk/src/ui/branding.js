import {apiUrl} from '../api/config.js';
export function approvedImage(value) {
  return typeof value==='string' && /^\/static\/(?:media|branding)\/[a-zA-Z0-9_-]+\.(?:png|webp|jpe?g)(?:\?v=[a-f0-9]{64})?$/.test(value) ? value : null;
}
export function contrastText(color) {
  if(!/^#[a-fA-F0-9]{6}$/.test(color||''))return null;
  const rgb=[1,3,5].map(i=>parseInt(color.slice(i,i+2),16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
  const luminance=.2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2];
  return (luminance+.05)/.05 >= 1.05/(luminance+.05)?'#000000':'#ffffff';
}
export function applyBranding(config,doc=document,resolve=apiUrl) {
  const a=config.assistant||{},visual=config.visual||{};
  const name=typeof a.name==='string'?a.name.slice(0,120):'Lía';doc.title=name;
  const label=doc.getElementById('assistant-name');if(label)label.textContent=name;
  doc.getElementById('mode-switch')?.setAttribute('aria-label','Modo de '+name);
  doc.getElementById('text-message')?.setAttribute('aria-label','Escribe una pregunta a '+name);
  const color=a.primary_color??visual.primary_color,text=contrastText(color);
  if(text){doc.documentElement.style.setProperty('--assistant-primary',color);doc.documentElement.style.setProperty('--assistant-on-primary',text);doc.documentElement.dataset.branding='configured';}
  const logo=doc.getElementById('assistant-logo'),url=approvedImage(a.logo_url??visual.logo_url);
  if(logo){logo.hidden=!url;logo.alt='Logo institucional';if(url){logo.onerror=()=>{logo.hidden=true;};logo.src=resolve(url);}}
  const favicon=approvedImage(a.favicon_url??visual.favicon_url),icon=doc.getElementById('app-favicon');
  if(icon&&favicon){icon.href=resolve(favicon);icon.type=/\.webp/.test(favicon)?'image/webp':/\.jpe?g/.test(favicon)?'image/jpeg':'image/png';}
  const message=a.initial_message??visual.initial_message;
  const subtitles=doc.getElementById('subtitles');if(subtitles&&!subtitles.textContent&&typeof message==='string')subtitles.textContent=message.slice(0,500);
}

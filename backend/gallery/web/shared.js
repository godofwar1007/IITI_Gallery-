export const $ = (selector, root=document) => root.querySelector(selector);
export const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];
export function el(tag, cls='', text='') { const node=document.createElement(tag); node.className=cls; if(text) node.textContent=text; return node; }
const paths={search:'<circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 4.5 4.5"/>',
 arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',close:'<path d="m6 6 12 12M18 6 6 18"/>',
 grid:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
 image:'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-6 5 7"/>',
 upload:'<path d="M12 16V3m-5 5 5-5 5 5M4 16v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4"/>',
 live:'<circle cx="12" cy="12" r="3"/><path d="M7 5a9 9 0 0 0 0 14M17 5a9 9 0 0 1 0 14"/>',
 map:'<circle cx="6" cy="7" r="2"/><circle cx="17" cy="5" r="2"/><circle cx="14" cy="16" r="2"/><circle cx="4" cy="20" r="1"/><path d="m8 7 7-2m-7 4 5 5"/>',
 qr:'<path d="M3 3h6v6H3zM15 3h6v6h-6zM3 15h6v6H3zM14 14h3v3h-3zM20 14v3m-3 4h4v-4m-8 4v-3"/>',
 check:'<path d="m5 12 4 4L19 6"/>',refresh:'<path d="M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 14 6M4 12a8 8 0 0 0 14 6"/>',
 camera:'<path d="m8 4-2 3H3v13h18V7h-3l-2-3z"/><circle cx="12" cy="13" r="4"/>',
 settings:'<path d="M4 7h16M4 17h16M8 4v6m8 4v6"/>',chevron:'<path d="m9 5 7 7-7 7"/>',download:'<path d="M12 3v13m-5-5 5 5 5-5M4 18v3h16v-3"/>'};
export function icon(name){ const box=el('span','icon'); box.innerHTML=`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]||paths.image}</svg>`;return box;}
export function button(text, cls='button', name){ const b=el('button',cls);b.type='button';if(name)b.append(icon(name));b.append(document.createTextNode(text));return b; }
export async function api(path,options={}){
 if(window.FIELDNOTES_PREVIEW)return window.FIELDNOTES_PREVIEW.api(path,options);
 const config={credentials:'same-origin',...options};
 if(config.body && typeof config.body==='object' && !(config.body instanceof Blob)){config.headers={'Content-Type':'application/json',...config.headers};config.body=JSON.stringify(config.body);}
 const response=await fetch(path,config);let data;try{data=await response.json();}catch{data={message:'The server returned an unexpected response.'};}
 if(!response.ok){const error=new Error(data.message||data.detail?.[0]?.msg||'This request could not be completed.');error.status=response.status;error.code=data.error;throw error;}
 return data;
}
export function toast(message){let region=$('#toast');if(!region){region=el('div','toast');region.id='toast';region.setAttribute('role','status');document.body.append(region);}region.textContent=message;region.classList.add('visible');clearTimeout(region.timer);region.timer=setTimeout(()=>region.classList.remove('visible'),5500);}
export function title(name){return name.replace(/\.[^.]+$/,'').replace(/^personal_\d+_/,'').replace(/_\d{8,}$/,'').replaceAll('_',' ').replace(/^./,s=>s.toUpperCase());}
export function age(timestamp){const seconds=Math.max(0,Date.now()/1000-timestamp);return seconds<60?'Just now':seconds<3600?`${Math.floor(seconds/60)} min ago`:`${Math.floor(seconds/3600)} hr ago`;}
export async function organizer(start){
 try{await start();}catch(error){if(error.status!==401){toast(error.message);return;}const dialog=$('#login');dialog.showModal();$('#login-password').focus();$('#login-form').onsubmit=async event=>{event.preventDefault();const submit=$('button[type=submit]',dialog);submit.disabled=true;$('#login-error').textContent='';try{await api('/api/v1/auth/login',{method:'POST',body:{password:$('#login-password').value}});$('#login-password').value='';dialog.close();await start();}catch(e){$('#login-error').textContent=e.message;}finally{submit.disabled=false;}};}
}

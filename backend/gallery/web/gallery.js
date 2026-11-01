import {$,$$,el,icon,button,api,toast,title,age,organizer} from './shared.js';
let state={collection:'all',query:'',items:[],total:0,offset:0,search:false,view:'photos',generation:0,status:null,selected:null,busy:false};
$('#search-icon').append(icon('search'));$('#image-icon').append(icon('image'));$('#view-photos').prepend(icon('grid'));$('#view-map').prepend(icon('map'));$('#open-qr').prepend(icon('qr'));$('#side-map').prepend(icon('map'));$('#open-settings').prepend(icon('settings'));
const labels={all:'All photographs',user_photos:'Campus & personal',coco_starter:'The starter collection',live:'From the room',campus:'Campus photographs'};
function card(item){const b=button('','photo-card');b.setAttribute('aria-label',`Open ${title(item.caption)}`);const frame=el('div','photo-frame');const image=el('img');image.src=item.thumb;image.loading='lazy';image.alt=title(item.caption);frame.append(image);if(item.collection==='live')frame.append(el('span','live-badge','Live upload'));if($('#scores').checked && item.cosine!==undefined)frame.append(el('span','score-badge',item.cosine.toFixed(3)));b.append(frame);const label=el('div','photo-label');label.append(el('span','',title(item.caption)),el('span','',item.collection==='live'?age(item.created):'↗'));b.append(label);b.onclick=()=>openPhoto(item);return b;}
function render(){const grid=$('#photos');grid.replaceChildren(...state.items.map(card));grid.hidden=state.view!=='photos';$('#map-section').hidden=state.view!=='map';$('#empty').hidden=state.items.length!==0||state.view!=='photos';$('#more').hidden=state.search||state.items.length>=state.total||state.view!=='photos';$('#result-count').textContent=`${state.total} ${state.search?'matches':'photographs'}`;$('#clear-search').hidden=!state.search;$('#page-subtitle').textContent=state.search?`Results for “${state.query}”`:`${state.total} photographs${state.collection==='live'?' from the room.':' in the collection.'}`;}
async function browse(append=false){state.busy=true;try{const data=await api(`/api/v1/gallery?collection=${state.collection}&offset=${append?state.items.length:0}&limit=60`);state.items=append?[...state.items,...data.items]:data.items;state.total=data.total;state.search=false;state.generation=data.generation;$('#new-notice').hidden=true;render();}finally{state.busy=false;}}
async function search(){const query=$('#query').value.trim();if(!query){state.query='';await browse();return;}state.busy=true;$('#search-form').classList.add('loading');try{const data=await api('/api/v1/search/text',{method:'POST',body:{query,k:24,collection:state.collection,alpha:Number($('#alpha').value),beta:Number($('#beta').value)}});state.query=query;state.items=data.items;state.total=data.items.length;state.search=true;state.generation=data.generation;$('#new-notice').hidden=true;state.view='photos';setViewButtons();render();if(data.matched_places?.length)$('#page-subtitle').textContent+=` · Reference blend: ${data.matched_places.join(', ')}`;}catch(error){toast(error.message);}finally{state.busy=false;$('#search-form').classList.remove('loading');}}
async function refreshStatus(initial=false){
 const status=await api('/api/v1/admin/status');
 if(initial || (state.status && status.generation!==state.status.generation)){
   const visible=await api('/api/v1/gallery/visibility');
   const ids=new Set(visible.ids);
   if(!initial && state.visibleIds && visible.ids.some(id=>!state.visibleIds.has(id))) $('#new-notice').hidden=false;
   const retained=state.items.filter(item=>ids.has(item.id));
   if(retained.length!==state.items.length){state.total=Math.max(0,state.total-(state.items.length-retained.length));state.items=retained;render();}
   if(state.selected && !ids.has(state.selected.id)){$('#lightbox').close();$('#photo-full').removeAttribute('src');state.selected=null;}
   state.visibleIds=ids;
 }
 state.status=status;
 const canManage=status.organizer!==false;
 ['open-settings','open-qr','add-laptop','add-camera','tags-toggle','hide-photo','reload-places','logout'].forEach(id=>{const node=document.getElementById(id);if(node)node.hidden=!canManage;});
 document.querySelectorAll('a[href="/moderator"]').forEach(node=>node.hidden=!canManage);

 $('#campus-tuned').checked=status.text_profile==='campus-run2';
 $('#campus-tuned-label').textContent=status.text_profile==='campus-run2'?'on':'off';
 $('#campus-tuned').disabled=status.warming;

 $('#count-all').textContent=status.total;
 $('#count-live').textContent=status.live;
 $('#count-personal').textContent=status.collections?.user_photos??0;
 $('#count-starter').textContent=status.collections?.coco_starter??0;
 $('#count-campus').textContent=status.collections?.campus??0;
 catalogueStatus(status.catalogue);
 $('#pending-header').textContent=status.pending?`(${status.pending})`:'';
 $('#model-status').textContent=status.warming?'GPU model warming up':status.mode==='live'?'Live model ready':'Prepared query preview';
 $('#model-dot').classList.toggle('amber',status.mode!=='live');
 $('#mode-notice').hidden=status.mode==='live';
 $('#mode-notice').textContent=status.warming?'The GPU model is warming up. Browse the photos or try a saved search now; arbitrary searches will be available when the model is ready.':status.error||'Prepared preview · Choose a saved search below. New photos and arbitrary queries need the live model.';
 $('#student-link').textContent=status.public_url;
 $('#qr-note').textContent=status.public_url.includes('127.0.0.1')||status.public_url.includes('localhost')?'Local preview address. A public HTTPS host is needed before students can scan from their phones.':'Use campus Wi-Fi or mobile data. Photos appear after organizer review.';
 $('#settings-info').textContent=`${status.total} visible photos · ${status.queued} queued · ${status.free_gib} GiB free · ${status.mode} mode`;
 $('#toggle-live').textContent=status.settings.hide_live==='1'?'Show approved live photos':'Hide all live photos';
 if(initial){
   const hints=$('#hints');
   const preferred=['lhc at night','abhinandan bhawan','lecture hall complex','badminton court','a dog','mess food','main gate','sunset on campus'];
   const choices=preferred.filter(q=>status.prepared_queries.includes(q));
   (choices.length?choices:status.prepared_queries.slice(0,9)).forEach((query,i)=>{const b=button(query,'hint');b.title=query;b.onclick=()=>{$('#query').value=query;search();};hints.append(b);});
 }
}
function connectionLost(){
 $('#model-status').textContent='Connection interrupted';$('#model-dot').classList.add('amber');
 $('#mode-notice').hidden=false;$('#mode-notice').textContent='Connection interrupted. Reconnect for live searches, or switch to your local prepared viewer.';
}
async function start(){await refreshStatus(true);await browse();setInterval(()=>refreshStatus().catch(connectionLost),2500);}
organizer(start);
function catalogueStatus(catalogue){
 $('#places-status').textContent=catalogue?.error?'Catalogue error: '+catalogue.error:`${catalogue?.places?.length||0} places · ${catalogue?.reference_count||0} reference photos`;
 $('#beta').disabled=!catalogue?.places?.length;
 if(!catalogue?.places?.length){$('#beta').value='0';$('#beta-label').textContent='0 · pure model';}
 const names=(catalogue?.places||[]).slice(0,6).map(place=>place.name);
 if(JSON.stringify(names)!==state.placeNames){
  state.placeNames=JSON.stringify(names);$$('.place-hint').forEach(node=>node.remove());
  for(const name of names){const hint=button(name,'hint place-hint');hint.onclick=()=>{$('#query').value=name;search();};$('#hints').append(hint);}
 }
}
$('#beta').oninput=()=>$('#beta-label').textContent=Number($('#beta').value)===0?'0 · pure model':`β ${Number($('#beta').value).toFixed(1)}`;
$('#beta').onchange=()=>{if(state.search)search();};
$('#reload-places').onclick=async()=>{try{const result=await api('/api/v1/demo/places/reload',{method:'POST'});catalogueStatus(result);toast(result.error||'Place catalogue reloaded.');}catch(error){toast(error.message);}};
$('#scores').checked=true;
$('#add-laptop').onclick=()=>$('#laptop-files').click();$('#add-camera').onclick=()=>$('#laptop-camera').click();
async function addPhotos(input){
 const files=Array.isArray(input)?input:[...input.files];if(!Array.isArray(input))input.value='';if(!files.length)return;
 $('#add-laptop').disabled=true;$('#add-camera').disabled=true;
 let complete=0;
 try{for(const file of files){$('#laptop-progress').textContent=`Adding ${complete+1}/${files.length}…`;await api('/api/v1/demo/photos',{method:'POST',body:file,headers:{'Content-Type':file.type||'application/octet-stream','X-Photo-Name':encodeURIComponent(file.name)}});complete++;}toast(`${complete} photo${complete===1?'':'s'} added.`);}catch(error){toast(error.message);}finally{$('#laptop-progress').textContent=complete?`${complete} added`:'';$('#add-laptop').disabled=false;$('#add-camera').disabled=false;await refreshStatus();await browse();}
}
$('#laptop-files').onchange=()=>addPhotos($('#laptop-files')).catch(error=>toast(error.message));$('#laptop-camera').onchange=()=>addPhotos($('#laptop-camera')).catch(error=>toast(error.message));
let cameraStream=null;
function stopCamera(){cameraStream?.getTracks().forEach(track=>track.stop());cameraStream=null;$('#camera-video').srcObject=null;}
$('#camera-dialog').addEventListener('close',stopCamera);
$('#add-camera').onclick=async()=>{
 if(!navigator.mediaDevices?.getUserMedia){$('#laptop-camera').click();return;}
 try{cameraStream=await navigator.mediaDevices.getUserMedia({video:true,audio:false});$('#camera-video').srcObject=cameraStream;$('#camera-dialog').showModal();await $('#camera-video').play();}
 catch(error){stopCamera();if($('#camera-dialog').open)$('#camera-dialog').close();toast('Camera unavailable or permission denied. You can still add a photo file.');}
};
$('#capture-photo').onclick=async()=>{
 const video=$('#camera-video');if(!video.videoWidth){toast('Wait for the camera preview.');return;}
 const canvas=document.createElement('canvas');const ratio=Math.min(1,1024/Math.max(video.videoWidth,video.videoHeight));canvas.width=Math.round(video.videoWidth*ratio);canvas.height=Math.round(video.videoHeight*ratio);canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);
 const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',.9));if(!blob){toast('The camera image could not be captured. Try again.');return;}
 $('#camera-dialog').close();await addPhotos([new File([blob],`webcam-${Date.now()}.jpg`,{type:'image/jpeg'})]).catch(error=>toast(error.message));
};
$('#search-form').onsubmit=event=>{event.preventDefault();search();};$('#more').onclick=()=>browse(true).catch(e=>toast(e.message));$('#clear-search').onclick=()=>{$('#query').value='';state.query='';browse().catch(e=>toast(e.message));};$('#refresh-new').onclick=()=>{if(state.search)search();else browse().catch(e=>toast(e.message));refreshStatus().catch(()=>{});};$('#scores').onchange=render;
$$('[data-collection]').forEach(b=>b.onclick=async()=>{$$('[data-collection]').forEach(x=>x.classList.remove('active'));b.classList.add('active');state.collection=b.dataset.collection;$('#page-title').textContent=labels[state.collection];state.view='photos';setViewButtons();try{if(state.search)await search();else await browse();}catch(e){toast(e.message);}});
$('#hybrid-toggle').onclick=()=>{$('#hybrid').hidden=!$('#hybrid').hidden;};$('#alpha').oninput=()=>$('#alpha-label').textContent=`${Math.round(Number($('#alpha').value)*100)}%`;$('#alpha').onchange=()=>{if(state.search)search();};
function setViewButtons(){$('#view-photos').classList.toggle('active',state.view==='photos');$('#view-map').classList.toggle('active',state.view==='map');}
async function showMap(){state.view='map';setViewButtons();render();try{const data=await api('/api/v1/gallery/map');const svg=$('#map');svg.replaceChildren();if(!data.points.length)return;const xs=data.points.map(p=>p.x),ys=data.points.map(p=>p.y);const minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys);data.points.forEach(p=>{const c=document.createElementNS('http://www.w3.org/2000/svg','circle');c.setAttribute('cx',35+(p.x-minX)/(maxX-minX||1)*830);c.setAttribute('cy',35+(p.y-minY)/(maxY-minY||1)*500);c.setAttribute('r','4.5');c.setAttribute('class','map-point'+(p.live?' live':''));c.setAttribute('tabindex','0');c.setAttribute('aria-label','Open photograph on embedding map');const open=async()=>{let item=state.items.find(i=>i.id===p.id);if(!item){try{item=await api('/api/v1/gallery/assets/'+p.id);}catch(error){toast(error.message);return;}}if(item)openPhoto(item);};c.onclick=open;c.onkeydown=e=>{if(e.key==='Enter')open();};svg.append(c);});}catch(e){toast(e.message);}}
$('#view-map').onclick=showMap;$('#side-map').onclick=showMap;$('#view-photos').onclick=()=>{state.view='photos';setViewButtons();render();};
function openPhoto(item){state.selected=item;$('#photo-full').src=item.image;$('#photo-full').alt=title(item.caption);$('#photo-title').textContent=title(item.caption);$('#photo-meta').textContent=item.collection==='live'?`Live upload · ${age(item.created)}`:(item.collection==='campus'?'IIT Indore · Campus collection':'Seed collection · '+(item.collection==='user_photos'?'Campus & personal':'Starter collection'));$('#maths').hidden=true;$('#tags').hidden=true;$('#tag-text').value=item.tags||'';$('#lightbox').showModal();}
$('#close-photo').onclick=()=>$('#lightbox').close();$('#lightbox').addEventListener('click',event=>{if(event.target===$('#lightbox'))$('#lightbox').close();});
async function similar(minus='',plus=''){if(!state.selected)return;try{const data=await api('/api/v1/search/image',{method:'POST',body:{asset_id:state.selected.id,minus,plus,k:24}});$('#lightbox').close();state.items=data.items;state.total=data.items.length;state.search=true;state.query=minus||plus?`Photo − ${minus||'nothing'} + ${plus||'nothing'}`:'Photographs like this';state.view='photos';setViewButtons();render();}catch(e){toast(e.message);}}
$('#similar').onclick=()=>similar();$('#maths-toggle').onclick=()=>{$('#maths').hidden=!$('#maths').hidden;$('#minus').focus();};$('#maths').onsubmit=e=>{e.preventDefault();similar($('#minus').value,$('#plus').value);};$('#tags-toggle').onclick=()=>{$('#tags').hidden=!$('#tags').hidden;$('#tag-text').focus();};$('#tags').onsubmit=async e=>{e.preventDefault();try{await api(`/api/v1/admin/assets/${state.selected.id}/tags`,{method:'PUT',body:{tags:$('#tag-text').value}});state.selected.tags=$('#tag-text').value;toast('Tags saved.');}catch(e){toast(e.message);}};
$('#hide-photo').onclick=async()=>{if(!confirm('Hide this photo from every presenter view?'))return;try{await api(`/api/v1/admin/assets/${state.selected.id}/hide`,{method:'POST'});$('#lightbox').close();await browse();await refreshStatus();toast('Photo hidden from the collection.');}catch(e){toast(e.message);}};
$('#search-image').onclick=()=>$('#query-file').click();$('#query-file').onchange=async()=>{const file=$('#query-file').files[0];if(!file)return;$('#search-form').classList.add('loading');try{const data=await api('/api/v1/search/image-file',{method:'POST',body:file,headers:{'Content-Type':file.type||'application/octet-stream'}});state.items=data.items;state.total=data.items.length;state.search=true;state.query='Your photo';render();}catch(e){toast(e.message);}finally{$('#query-file').value='';$('#search-form').classList.remove('loading');}};
$('#open-qr').onclick=()=>{$('#qr-image').src='/api/v1/admin/qr.svg';$('#qr-dialog').showModal();};$('#copy-link').onclick=async()=>{try{await navigator.clipboard.writeText($('#student-link').textContent);toast('Upload link copied.');}catch{toast('Select and copy the link shown above.');}};$('#print-qr').onclick=()=>window.print();$$('[data-close]').forEach(b=>b.onclick=()=>$('#'+b.dataset.close).close());$('#open-settings').onclick=()=>$('#settings-dialog').showModal();$('#toggle-live').onclick=async()=>{try{await api('/api/v1/admin/event',{method:'POST',body:{hide_live:state.status.settings.hide_live==='1'?'0':'1'}});await refreshStatus();await browse();toast('Live photo visibility updated.');}catch(e){toast(e.message);}};$('#finish').onclick=async()=>{const confirmText=prompt('This deletes student photos and closes uploads. Type DELETE STUDENT PHOTOS to continue.');if(confirmText!=='DELETE STUDENT PHOTOS')return;try{await api('/api/v1/admin/finish',{method:'POST',body:{confirm:confirmText}});$('#settings-dialog').close();await browse();await refreshStatus();toast('Workshop closed. Student cleanup requested.');}catch(e){toast(e.message);}};$('#logout').onclick=async()=>{await api('/api/v1/auth/logout',{method:'POST'});location.reload();};document.addEventListener('keydown',event=>{if(event.key==='/'&&!['INPUT','TEXTAREA'].includes(document.activeElement.tagName)){event.preventDefault();$('#query').focus();}});

$('#campus-tuned').onchange=async()=>{
 const control=$('#campus-tuned');control.disabled=true;
 try{await api('/api/v1/admin/text-profile',{method:'POST',body:{text_profile:control.checked?'campus-run2':'base'}});await refreshStatus();if(state.search)await search();toast(control.checked?'Campus-tuned search on.':'Base model search on.');}
 catch(error){toast(error.message);await refreshStatus().catch(()=>{});}
 finally{control.disabled=Boolean(state.status?.warming);}
};

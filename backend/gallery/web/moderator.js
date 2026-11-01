import {$,$$,el,button,api,toast,age,organizer} from './shared.js';
let filter='pending',items=[],selected=new Set(),refreshing=false;
async function load(force=false){
 if(refreshing)return;
 refreshing=true;
 try{
  const [status,data]=await Promise.all([api('/api/v1/admin/status'),api('/api/v1/admin/review?filter='+filter)]);
  if(force||items.length===0)items=data.items;
  else{
   // Update progress in place; never move another photo under a reviewer's pointer.
   const incoming=new Map(data.items.map(item=>[item.id,item]));
   items=items.map(item=>incoming.get(item.id)||item);
  }
  $('#pending').textContent=status.pending;$('#queued').textContent=status.queued;
  $('#live').textContent=status.live;$('#failed').textContent=status.failed;
  $('#intake').value=status.mode==='live'?status.settings.intake:'paused';
  $('#intake').disabled=status.mode!=='live';$('#allowance').value=status.settings.allowance;
  $('#mode-notice').hidden=status.mode==='live';
  $('#mode-notice').textContent='Prepared preview. Approvals queue safely, but new image embeddings need live model inference.';
  render();
 }finally{refreshing=false;}
}
function render(){const root=$('#review-grid');root.replaceChildren();$('#empty').hidden=items.length>0;selected=new Set([...selected].filter(id=>items.some(i=>i.id===id&&i.state==='validated'&&i.review==='pending')));for(const item of items){const card=el('article','review-card'+(selected.has(item.id)?' selected':''));if(item.thumb){const image=el('img','review-image');image.src=item.thumb;image.alt='Private photo awaiting review';image.loading='lazy';card.append(image);}else{card.append(el('div','review-placeholder',item.error||'Preparing photo…'));}const bottom=el('div','review-card-bottom');bottom.append(el('h3','',item.review==='pending'?'From the room':item.review[0].toUpperCase()+item.review.slice(1)),el('p','upload-status',age(item.created)));if(item.error)bottom.append(el('p','upload-status failed',item.error));if(item.state==='validated'&&item.asset_id){const actions=el('div','review-actions');if(item.review!=='approved'){const approve=button('Approve','button primary small');approve.onclick=()=>act(item,'approve');actions.append(approve);}if(item.review==='pending'){const reject=button('Reject','button small');reject.onclick=()=>act(item,'reject');actions.append(reject);const check=el('input','review-select');check.type='checkbox';check.checked=selected.has(item.id);check.setAttribute('aria-label','Select submission for approval');check.onchange=()=>{if(check.checked)selected.add(item.id);else selected.delete(item.id);card.classList.toggle('selected',check.checked);bulk();};card.append(check);}else if(item.review==='approved'){const hide=button('Hide','button small');hide.onclick=()=>act(item,'hide');actions.append(hide);}if(item.job_state==='failed'){const retry=button('Retry processing','button soft small');retry.disabled=item.attempts>=3;retry.onclick=async()=>{try{await api('/api/v1/admin/jobs/'+item.asset_id+'/retry',{method:'POST'});await load(true);}catch(error){toast(error.message);}};actions.append(retry);bottom.append(el('p','upload-status failed','Processing failed. '+(item.job_error||'')));}bottom.append(actions);}card.append(bottom);root.append(card);}bulk();}
function bulk(){$('#approve-selected').hidden=!selected.size;$('#approve-selected').textContent=`Approve ${selected.size} reviewed photo${selected.size===1?'':'s'}`;}
async function act(item,action,refresh=true){try{await api(`/api/v1/admin/submissions/${item.id}/review`,{method:'POST',body:{action,revision:item.revision}});selected.delete(item.id);if(refresh)await load(true);return true;}catch(e){toast(e.message);if(refresh)await load(true);return false;}}
$('#approve-selected').onclick=async()=>{const chosen=items.filter(i=>selected.has(i.id));let approved=0;for(const item of chosen)if(await act(item,'approve',false))approved++;await load(true);toast(`${approved} reviewed photo${approved===1?'':'s'} approved.`);};$('#refresh').onclick=()=>load(true).catch(e=>toast(e.message));$$('[data-filter]').forEach(b=>b.onclick=()=>{filter=b.dataset.filter;selected.clear();$$('[data-filter]').forEach(x=>x.classList.toggle('active',x===b));load(true).catch(e=>toast(e.message));});for(const key of ['intake','allowance'])$('#'+key).onchange=async()=>{try{await api('/api/v1/admin/event',{method:'POST',body:{[key]:$('#'+key).value}});await load(true);}catch(e){toast(e.message);await load(true);}};
organizer(async()=>{await load(true);setInterval(()=>load().catch(()=>{}),2500);});

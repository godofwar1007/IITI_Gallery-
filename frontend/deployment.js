// A frontend-only deployment is an explicit setup state, never a fake live gallery.
if (!window.FIELDNOTES_DEPLOYMENT.backendConfigured) {
  document.addEventListener('DOMContentLoaded',()=>{
    const set=(id,text)=>{const node=document.getElementById(id);if(node)node.textContent=text;};
    set('model-status','Backend not connected');
    document.getElementById('model-dot')?.classList.add('amber');
    set('page-subtitle','Frontend ready. Connect the backend to load photographs and enable search.');
    const notice=document.getElementById('mode-notice');
    if(notice){notice.hidden=false;notice.textContent='This is the frontend deployment. Search, photos and uploads become available once the backend is connected.';}
    const empty=document.getElementById('empty');
    if(empty){empty.hidden=false;empty.querySelector('h2').textContent='Your gallery will appear here.';set('empty-message','The frontend is ready; the photo and search backend is the next deployment step.');}
    for(const form of document.querySelectorAll('form')) for(const input of form.elements) input.disabled=true;
    for(const id of ['add-laptop','add-camera','campus-tuned','search-image','open-qr','finish','reload-places']) {
      const node=document.getElementById(id);if(node)node.disabled=true;
    }
  });
}

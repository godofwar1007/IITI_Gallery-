/* Standalone adapter over real exported vectors; no network or GPU calls. */
(function () {
 const data=JSON.parse(document.getElementById('preview-data').textContent);
 function floats(encoded){const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));return new Float32Array(bytes.buffer);}
 let profile=data.queryProfiles?.includes('campus-run2')?'campus-run2':'base';
 const vectors=floats(data.vectors),queries=floats(data.queryVectors),dim=1536;
 const photos=data.photos.map(photo=>({...photo,image:photo.thumb})),byId=new Map(photos.map((photo,i)=>[photo.id,{...photo,index:i}]));
 function error(message){throw Object.assign(new Error(message),{status:503});}
 function record(photo,cosine){return {...photo,...(cosine===undefined?{}:{cosine,score:(cosine+1)/2,keyword:0})};}
 function dense(vector,collection='all',k=24,exclude=null){
  return photos.filter(p=>p.id!==exclude&&(collection==='all'||collection==='seed'||p.collection===collection)).map(p=>{
   const index=byId.get(p.id).index;let score=0;
   for(let j=0;j<dim;j++)score+=vector[j]*vectors[index*dim+j];
   return record(p,score);
  }).sort((a,b)=>b.cosine-a.cosine||a.id.localeCompare(b.id)).slice(0,k);
 }
 function textVector(query){const row=data.queryTexts.findIndex((q,i)=>q===query.toLowerCase().trim()&&(data.queryProfiles?.[i]||'base')===profile);if(row<0)error('This file preview supports the saved searches below. Double-click Open_Gallery.cmd for arbitrary live searches.');return queries.slice(row*dim,(row+1)*dim);}
 window.FIELDNOTES_PREVIEW={api:async function(path,options={}){
  const url=new URL(path,'http://preview.invalid'),body=options.body||{};
  if(path==='/api/v1/admin/status')return {total:photos.length,live:0,pending:0,queued:0,failed:0,free_gib:'—',mode:'prepared',generation:1,local_demo:true,settings:{hide_live:'0'},catalogue:{places:[],reference_count:0},text_profile:profile,collections:Object.fromEntries([...new Set(photos.map(p=>p.collection))].map(c=>[c,photos.filter(p=>p.collection===c).length])),prepared_queries:data.queryTexts.filter((q,i)=>(data.queryProfiles?.[i]||'base')===profile),public_url:'http://127.0.0.1:7860/e/workshop'};
  if(path==='/api/v1/admin/text-profile'){if(!['base','campus-run2'].includes(body.text_profile))error('Unknown text profile');if(!data.queryProfiles?.includes(body.text_profile)&&body.text_profile!=='base')error('Rebuild prepared queries first');profile=body.text_profile;return {text_profile:profile};}
  if(path==='/api/v1/gallery/visibility')return {ids:photos.map(p=>p.id),generation:1};
  if(url.pathname==='/api/v1/gallery'){
   const collection=url.searchParams.get('collection')||'all',offset=Number(url.searchParams.get('offset')||0),limit=Number(url.searchParams.get('limit')||60);
   const items=photos.filter(p=>collection==='all'||collection==='seed'||p.collection===collection);
   return {items:items.slice(offset,offset+limit).map(p=>record(p)),total:items.length,generation:1};
  }
  if(path.startsWith('/api/v1/gallery/assets/')){const photo=byId.get(path.split('/').pop());if(!photo)error('Photo not found');return record(photo);}
  if(path==='/api/v1/search/text')return {items:dense(textVector(body.query),body.collection,body.k),generation:1,matched_places:[]};
  if(path==='/api/v1/search/image'){
   const photo=byId.get(body.asset_id);if(!photo)error('Photo not found');
   const vector=vectors.slice(photo.index*dim,(photo.index+1)*dim);
   if(body.minus?.trim()){const minus=textVector(body.minus);for(let i=0;i<dim;i++)vector[i]-=minus[i];}
   if(body.plus?.trim()){const plus=textVector(body.plus);for(let i=0;i<dim;i++)vector[i]+=plus[i];}
   const norm=Math.sqrt(vector.reduce((sum,value)=>sum+value*value,0));for(let i=0;i<dim;i++)vector[i]/=norm;
   return {items:dense(vector,'all',body.k,body.minus||body.plus?null:photo.id),generation:1};
  }
  if(path==='/api/v1/gallery/map')return {points:data.points};
  error('This is the standalone browsing preview. Double-click Open_Gallery.cmd for uploads, camera and live search.');
 }};
})();

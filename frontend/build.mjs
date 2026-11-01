import {mkdir, readFile, writeFile, readdir, copyFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

export function backendOrigin(value='') {
  if (!value.trim()) return null;
  const url=new URL(value.trim());
  if(url.protocol!=='https:'||url.username||url.password||url.search||url.hash||url.pathname!=='/') {
    throw new Error('GALLERY_BACKEND_URL must be an HTTPS origin without a path, credentials, query or fragment.');
  }
  return url.origin;
}

export function routing(origin) {
  const routes=[{src:'/assets/(.*)',headers:{'Cache-Control':'public, max-age=0, must-revalidate'},continue:true}];
  // Same-origin proxy keeps cookies and media URLs on the frontend domain.
  // The future backend gateway must route organizer AND student APIs securely.
  if(origin) routes.push({src:'/api/(.*)',dest:`${origin}/api/$1`},{src:'/health/(.*)',dest:`${origin}/health/$1`});
  else routes.push({src:'/api/.*',dest:'/backend-unavailable.json',status:503});
  routes.push({handle:'filesystem'},
    {src:'/(?:presenter)?/?',dest:'/index.html'},
    {src:'/moderator/?',dest:'/moderator.html'},
    {src:'/e/workshop/?',dest:'/upload.html'},
    {src:'/.*',dest:'/404.html',status:404});
  return {version:3,routes};
}

export async function build(root=path.resolve(fileURLToPath(new URL('..',import.meta.url))), value=process.env.GALLERY_BACKEND_URL) {
  if(value===undefined) {
    try { value=JSON.parse(await readFile(path.join(root,'frontend/backend.json'),'utf8')).url; }
    catch(error) { if(error.code!=='ENOENT') throw error; value=''; }
  }
  const origin=backendOrigin(value);
  const output=path.join(root,'.vercel/output');
  const dest=path.join(output,'static');
  await mkdir(path.join(dest,'assets'),{recursive:true});
  const source=path.join(root,'backend/gallery/web');
  // Explicit file allowlist: no dataset, model, local DB or preview is published.
  const assets=['style.css','gallery.js','shared.js','upload.js','moderator.js','file-entry.js'];
  for(const name of assets) await copyFile(path.join(source,name),path.join(dest,'assets',name));
  await copyFile(path.join(source,'file-entry.js'),path.join(dest,'file-entry.js'));
  for(const [sourceName,targetName] of [['gallery.html','index.html'],['moderator.html','moderator.html'],['upload.html','upload.html']]) {
    const html=(await readFile(path.join(source,sourceName),'utf8')).replace('</head>','<script src="/assets/deployment.js" defer></script></head>');
    await writeFile(path.join(dest,targetName),html);
  }
  const script=await readFile(path.join(root,'frontend/deployment.js'),'utf8');
  await writeFile(path.join(dest,'assets/deployment.js'),`window.FIELDNOTES_DEPLOYMENT={backendConfigured:${Boolean(origin)}};\n${script}`);
  await writeFile(path.join(dest,'backend-unavailable.json'),JSON.stringify({error:'backend_not_connected',message:'The frontend is deployed. The gallery backend has not been connected yet.'}));
  await writeFile(path.join(dest,'404.html'),'<!doctype html><html lang="en"><meta charset="utf-8"><title>Not found</title><h1>Page not found</h1><a href="/">Open Fieldnotes</a></html>');
  await writeFile(path.join(output,'config.json'),JSON.stringify(routing(origin),null,2)+'\n');
  console.log(`Frontend built. Backend ${origin?'proxy configured':'not connected (setup state)'}.`);
  return {output,dest,origin};
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) await build();

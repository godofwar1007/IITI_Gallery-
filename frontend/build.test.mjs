import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile, readdir} from 'node:fs/promises';
import {backendOrigin,routing,build} from './build.mjs';

test('backend origin is explicit and cannot inject credentials, paths or non-HTTPS routes',()=>{
  assert.equal(backendOrigin(''),null);
  assert.equal(backendOrigin('https://example.modal.run/'),'https://example.modal.run');
  for(const value of ['http://example.org','https://u:p@example.org','https://example.org/path','https://example.org/?key=secret','https://example.org/#fragment']) assert.throws(()=>backendOrigin(value));
});
test('same-origin routing preserves API paths; missing backend returns explicit 503',()=>{
  assert.deepEqual(routing('https://backend.example').routes.find(r=>r.src==='/api/(.*)'),{src:'/api/(.*)',dest:'https://backend.example/api/$1'});
  assert.equal(routing(null).routes.find(r=>r.src==='/api/.*').status,503);
  assert(routing(null).routes.some(r=>r.src==='/moderator/?'));
  assert(routing(null).routes.some(r=>r.src==='/e/workshop/?'));
});
test('build publishes only static UI files and an honest disconnected state',async()=>{
  const {dest}=await build(undefined,'');
  const files=await readdir(dest);
  assert.deepEqual(files.sort(),['404.html','assets','backend-unavailable.json','file-entry.js','index.html','moderator.html','upload.html'].sort());
  const script=await readFile(dest+'/assets/deployment.js','utf8');
  assert(script.includes('backendConfigured:false'));
  assert((await readFile(dest+'/index.html','utf8')).includes('/assets/deployment.js'));
  const css=await readFile(dest+'/assets/style.css','utf8');
  assert(css.includes('.gallery-grid{display:grid;'));
});
test('connected build emits the real HTTPS backend proxy',async()=>{
  const {output,dest}=await build(undefined,'https://ppp3work--iiti-fieldnotes.us-east.modal.run');
  const config=JSON.parse(await readFile(output+'/config.json','utf8'));
  assert.equal(config.routes.find(r=>r.src==='/api/(.*)').dest,'https://ppp3work--iiti-fieldnotes.us-east.modal.run/api/$1');
  assert((await readFile(dest+'/assets/deployment.js','utf8')).includes('backendConfigured:true'));
});

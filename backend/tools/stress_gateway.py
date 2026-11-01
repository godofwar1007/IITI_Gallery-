"""Real HTTP/QR/upload/review/index stress exercise against a disposable event.

Requires an empty live-photo queue. Uses generated test photos only and withdraws
its own submissions afterwards. Does not claim to test a venue or TLS proxy.
"""
import argparse
import asyncio
from collections import Counter
import io
import json
import os
from pathlib import Path
import statistics
import time
import uuid

import httpx
import numpy as np
from PIL import Image
import zxingcpp


def percentile(values,p):
    return round(float(np.percentile(values,p))*1000,2) if values else None


async def exercise(args):
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    limits=httpx.Limits(max_connections=550,max_keepalive_connections=100)
    metrics={'entry':[],'join':[],'qr':[],'upload':[],'search':[],'status':[]}
    counters=Counter(); ids=[]; errors=[]; byte_sizes=[]
    started=time.perf_counter()
    async with httpx.AsyncClient(base_url=args.admin,limits=limits,timeout=60) as admin, \
               httpx.AsyncClient(base_url=args.public,limits=limits,timeout=60) as network:
        for attempt in range(180):
            try:
                healthy=await network.get('/health/ready')
                if healthy.status_code==200:break
            except httpx.ConnectError:
                pass
            await asyncio.sleep(1)
        else:raise RuntimeError('Live inference server did not become ready within three minutes')
        login=await admin.post('/api/v1/auth/login',json={'password':os.environ['GALLERY_ADMIN_PASSWORD']})
        login.raise_for_status()
        baseline=(await admin.get('/api/v1/admin/status')).json()
        if any(baseline[k] for k in ['live','pending','queued','received']):
            raise RuntimeError('Refusing to load test an event with existing student photos/jobs')
        await admin.post('/api/v1/admin/event',json={'allowance':'3','intake':'open'})
        async def timed(bucket,method,url,**kwargs):
            begin=time.perf_counter();response=await network.request(method,url,**kwargs);metrics[bucket].append(time.perf_counter()-begin);return response
        async def participant(index):
            page=await timed('entry','GET','/e/workshop?code=INDORE26')
            assert page.status_code==200
            result=await timed('join','POST','/api/v1/join',json={'code':args.code,'consent':True})
            assert result.status_code==200,result.text
            return {'Cookie':'fn_student='+result.cookies['fn_student']}
        # Explicit cookies per request prevent a shared cookie jar merging identities.
        participants=await asyncio.gather(*(participant(i) for i in range(args.clients)))
        print('Joined',len(participants),'clients',flush=True)
        qr=(await admin.get('/api/v1/admin/qr.png')).content
        decoded=zxingcpp.read_barcode(Image.open(io.BytesIO(qr)))
        assert decoded and decoded.text==baseline['public_url']
        async def qr_hit():
            begin=time.perf_counter();r=await admin.get('/api/v1/admin/qr.svg');metrics['qr'].append(time.perf_counter()-begin);assert r.status_code==200
        await asyncio.gather(*(qr_hit() for _ in range(args.clients)))
        print('QR decoded correctly; QR endpoint burst complete',flush=True)
        alive=True
        async def polls():
            while alive:
                async def poll(headers):
                    for attempt in range(3):
                        try:
                            r=await timed('status','GET','/api/v1/me/submissions',headers=headers)
                            if r.status_code!=200:errors.append('poll:'+str(r.status_code))
                            return
                        except httpx.HTTPError as error:
                            counters['poll_transport_retries']+=1
                            if attempt==2:errors.append('poll_transport:'+type(error).__name__)
                            await asyncio.sleep(.25)
                await asyncio.gather(*(poll(h) for h in participants))
                counters['completed_status_cycles']+=1
                await asyncio.sleep(5)
        async def searches():
            i=0
            while alive:
                begin=time.perf_counter()
                r=await admin.post('/api/v1/search/text',json={'query':f'a blue bottle beside a window in a classroom, view {i}','k':12})
                metrics['search'].append(time.perf_counter()-begin)
                if r.status_code!=200:errors.append('search:'+str(r.status_code))
                i+=1;await asyncio.sleep(2)
        async def moderation():
            while alive:
                result=await admin.get('/api/v1/admin/review?filter=pending&limit=120')
                async def approve(item):
                    if item['state']!='validated':return
                    r=await admin.post(f"/api/v1/admin/submissions/{item['id']}/review",json={'action':'approve','revision':item['revision']})
                    if r.status_code==200:counters['approved']+=1
                    elif r.status_code!=409:errors.append('approve:'+str(r.status_code))
                await asyncio.gather(*(approve(i) for i in result.json()['items']))
                await asyncio.sleep(.3)
        async def monitor(function):
            try:
                await function()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                errors.append('background_'+function.__name__+':'+type(error).__name__)
        background=[asyncio.create_task(monitor(f)) for f in [polls,searches,moderation]]
        semaphore=asyncio.Semaphore(args.concurrency)
        async def send(index):
            async with semaphore:
                rng=np.random.default_rng(index+1000)
                array=rng.integers(0,256,size=(768,1024,3),dtype=np.uint8)
                buffer=io.BytesIO();Image.fromarray(array).save(buffer,format='JPEG',quality=45)
                data=buffer.getvalue();byte_sizes.append(len(data))
                owner=participants[index%args.clients]
                key='load_'+uuid.uuid4().hex
                begin=time.perf_counter()
                response=await network.post('/api/v1/upload-intents',headers=owner,json={'client_item_id':key,'size':len(data),'mime':'image/jpeg'})
                if response.status_code!=200:
                    errors.append('intent:'+str(response.status_code));return
                upload_id=response.json()['id'];ids.append((upload_id,owner))
                for attempt in range(50):
                    response=await network.put(f'/api/v1/uploads/{upload_id}/content',headers={**owner,'Content-Type':'image/jpeg'},content=data)
                    if response.status_code in {200,202}:
                        counters['accepted']+=1;metrics['upload'].append(time.perf_counter()-begin);break
                    if response.status_code in {429,503,409}:
                        counters['backpressure']+=1;await asyncio.sleep(.15+attempt*.02);continue
                    errors.append('upload:'+str(response.status_code));break
                else:errors.append('retry_exhausted')
                if counters['accepted']%100==0:print('Accepted',counters['accepted'],'photos',flush=True)
        try:
            await asyncio.gather(*(send(i) for i in range(args.photos)))
            deadline=time.monotonic()+args.drain_timeout
            final=None
            while time.monotonic()<deadline:
                final=(await admin.get('/api/v1/admin/status')).json()
                if final['live']==counters['accepted']:break
                if final['failed']:errors.append('embedding_failed');break
                print('Drain:',{k:final[k] for k in ['live','pending','received','queued','failed']},flush=True)
                await asyncio.sleep(10)
            if final['live']!=counters['accepted']:errors.append('not_all_indexed_before_deadline')
            if counters['completed_status_cycles']<3:errors.append('insufficient_continuous_status_polling')
        finally:
            alive=False
            for task in background:task.cancel()
            await asyncio.gather(*background,return_exceptions=True)
            # Only generated fixtures owned by this run are withdrawn.
            async def withdraw(pair):
                uid,headers=pair
                async with semaphore:
                    r=await network.delete(f'/api/v1/me/submissions/{uid}',headers=headers)
                    if r.status_code!=200:errors.append('cleanup:'+str(r.status_code))
            await asyncio.gather(*(withdraw(pair) for pair in ids))
            await admin.post('/api/v1/admin/event',json={k:baseline['settings'][k] for k in ['allowance','intake','hide_live']})
        report={'status':'passed' if not errors and counters['accepted']==args.photos else 'failed',
            'scope':'Real HTTP loopback test; real configured runtime model. Does not qualify public TLS/proxy/venue Wi-Fi or an L4 host.',
            'runtime_mode':baseline['mode'],'clients':args.clients,'photos_requested':args.photos,
            'counts':dict(counters),'errors':errors,'qr_decode_matches_url':bool(decoded),
            'payload_mib':round(sum(byte_sizes)/2**20,2),'elapsed_seconds':round(time.perf_counter()-started,2),
            'latency_ms':{key:{'samples':len(values),'p50':percentile(values,50),'p95':percentile(values,95),'p99':percentile(values,99),'max':round(max(values)*1000,2) if values else None} for key,values in metrics.items()}}
        (output/'gateway_stress.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2),flush=True)
        if report['status']!='passed':raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--public',default='http://127.0.0.1:7860')
    parser.add_argument('--admin',default='http://127.0.0.1:7861')
    parser.add_argument('--code',default='INDORE26')
    parser.add_argument('--clients',type=int,default=500)
    parser.add_argument('--photos',type=int,default=900)
    parser.add_argument('--concurrency',type=int,default=16)
    parser.add_argument('--drain-timeout',type=int,default=1200)
    parser.add_argument('--output',default='test-results')
    asyncio.run(exercise(parser.parse_args()))

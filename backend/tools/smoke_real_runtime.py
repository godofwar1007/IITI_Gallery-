"""Check fresh real-model queries and the independent seed-only viewer."""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import time

import httpx


def run():
    password=os.environ['GALLERY_ADMIN_PASSWORD']
    results=[]
    with httpx.Client(base_url='http://127.0.0.1:7861',timeout=60) as client:
        client.post('/api/v1/auth/login',json={'password':password}).raise_for_status()
        baseline=client.get('/api/v1/admin/status').json()
        assert baseline['total']==120 and baseline['live']==0
        queries=[
            ('a brightly glowing decorative lamp against a cloudy evening sky','personal_01'),
            ('a monkey climbing metal bars in dense green foliage','personal_10'),
            ('a vivid facade of colored glass at night','personal_16'),
        ]
        for query,expected in queries:
            start=time.perf_counter()
            response=client.post('/api/v1/search/text',json={'query':query,'k':12});response.raise_for_status()
            hits=response.json()['items']
            rank=next((i+1 for i,item in enumerate(hits) if item['caption'].startswith(expected)),None)
            results.append({'query':query,'expected_rank':rank,'top_1':hits[0]['caption'],
                            'seconds':round(time.perf_counter()-start,3)})
            assert rank is not None,results[-1]
        all_photos=client.get('/api/v1/gallery?limit=120').json()['items']
        photo=next(x for x in all_photos if x['caption'].startswith('personal_06'))
        content=client.get(photo['image']).content
        response=client.post('/api/v1/search/image-file',content=content,headers={'Content-Type':'image/jpeg'})
        response.raise_for_status()
        assert response.json()['items'][0]['id']==photo['id']
        image_agreement=response.json()['items'][0]['cosine']
        assert image_agreement>.99
        response=client.post('/api/v1/search/image',json={'asset_id':photo['id'],'minus':'day','plus':'night','k':8})
        response.raise_for_status();assert len(response.json()['items'])==8
        assert client.get('/api/v1/admin/status').json()['total']==120
    with httpx.Client(base_url='http://127.0.0.1:7862',timeout=20) as offline:
        offline.post('/api/v1/auth/login',json={'password':password}).raise_for_status()
        status=offline.get('/api/v1/admin/status').json()
        assert status['mode']=='prepared' and status['total']==120 and status['live']==0
        q=status['prepared_queries'][0]
        response=offline.post('/api/v1/search/text',json={'query':q});response.raise_for_status()
        assert response.json()['items']
        assert offline.post('/api/v1/search/text',json={'query':'not a saved query '+str(time.time())}).status_code==503
    report={'status':'passed','live_runtime':baseline['mode'],'seed_count':baseline['total'],
            'fresh_text_queries':results,'fresh_query_image_top_1_matches_source':True,
            'fresh_query_image_cosine':image_agreement,'photo_maths_returns_valid_results':True,
            'transient_query_upload_does_not_add_gallery_photo':True,
            'independent_seed_only_viewer_works_without_model':True,
            'offline_arbitrary_text_is_explicitly_refused':True,
            'host_gpu':subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total','--format=csv,noheader'],text=True).strip(),
            'limits':'HTTP/model checks only. No visual browser QA, physical phone camera scan, venue network or cloud VM deployment verified.'}
    target=Path('test-results/real_model_smoke.json')
    target.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':run()

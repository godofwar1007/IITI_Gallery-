"""Small real-model/local HTTP smoke. No stress test or student traffic."""
import asyncio
import io
import json
from pathlib import Path
import time

import httpx
from PIL import Image


async def main():
    checks=[('a brightly glowing decorative lamp against a cloudy evening sky','personal_01_ornate_lamp_at_dusk.jpg'),
            ('a monkey climbing metal bars in dense green foliage','personal_10_monkeys_on_railing.jpg'),
            ('a vivid facade of colored glass at night','personal_16_colorful_glass_building_night.jpg')]
    report={'scope':'Local presenter HTTP, real cached pretrained model. No visual/browser/webcam claim.','queries':[]}
    async with httpx.AsyncClient(base_url='http://127.0.0.1:7861',timeout=60) as client:
        status=(await client.get('/api/v1/admin/status')).json()
        assert status['mode']=='live' and status['local_demo']
        report['seed_visible_before']=status['total']
        for query,expected in checks:
            started=time.perf_counter()
            response=await client.post('/api/v1/search/text',json={'query':query,'beta':0})
            assert response.status_code==200,response.text
            top=response.json()['items'][0]['caption']
            assert top==expected,(top,expected)
            report['queries'].append({'query':query,'top_1':top,'seconds':round(time.perf_counter()-started,3)})
        content=io.BytesIO();Image.new('RGB',(77,91),(63,117,199)).save(content,format='JPEG')
        response=await client.post('/api/v1/demo/photos',content=content.getvalue(),headers={'X-Photo-Name':'generated-demo-smoke.jpg'})
        assert response.status_code==200,response.text
        asset=response.json()['asset_id']
        try:
            assert (await client.get('/api/v1/media/'+asset+'/full')).status_code==200
            assert (await client.get('/api/v1/gallery?collection=campus')).json()['total']>=1
            report['presenter_add_real_decode_and_embedding']='passed'
        finally:
            response=await client.post('/api/v1/admin/assets/'+asset+'/hide')
            assert response.status_code==200
        assert (await client.get('/api/v1/media/'+asset+'/full')).status_code==404
        report['generated_fixture_hidden']=True
        report['visible_after']=(await client.get('/api/v1/admin/status')).json()['total']
    report['status']='passed'
    destination=Path(__file__).resolve().parents[1]/'test-results/local_demo_smoke.json'
    destination.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':asyncio.run(main())

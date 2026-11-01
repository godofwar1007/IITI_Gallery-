"""Exercise the real HTTPS gateway without logging passwords or session cookies."""
import argparse
import io
import json
from pathlib import Path
import time
import uuid
import httpx
from PIL import Image


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--url',required=True)
    p.add_argument('--organizer-file',type=Path,required=True)
    p.add_argument('--output',type=Path,default=Path('integration-checks/modal-verification.json'))
    args=p.parse_args()
    credentials=json.loads(args.organizer_file.read_text(encoding='utf-8'))
    started=time.time()
    report={'url':args.url,'checks':{}}
    options={'base_url':args.url,'timeout':180,'follow_redirects':True,'max_redirects':2}
    with httpx.Client(**options) as admin, httpx.Client(**options) as student:
        ready=admin.get('/health/ready');ready.raise_for_status()
        assert ready.json()['ready'] and ready.json()['inference']=='live'
        report['checks']['readiness']=True
        assert admin.get('/api/v1/gallery').status_code==401
        assert admin.post('/api/v1/admin/text-profile',json={'text_profile':'base'}).status_code==401
        assert admin.post('/api/v1/auth/login',json={'password':'incorrect-test-password'}).status_code==401
        denied=admin.post('/api/v1/auth/login',json={'password':'unused'},headers={'Origin':'https://untrusted.example'})
        assert denied.status_code==403
        login=admin.post('/api/v1/auth/login',json={'password':credentials['GALLERY_ADMIN_PASSWORD']},headers={'Origin':args.url})
        login.raise_for_status();assert 'Secure' in login.headers['set-cookie']
        report['checks']['authentication_and_origin']=True
        status=admin.get('/api/v1/admin/status').json()
        assert status['total']==252 and status['collections']['campus']==132
        assert status['text_profile']=='campus-run2' and status['inference_device']=='cuda'
        report['gpu_name']=status['gpu_name'];report['collections']=status['collections']
        report['initial_instance_id']=status['instance_id']
        for name in ['/presenter','/moderator','/e/workshop','/assets/style.css','/assets/gallery.js']:
            assert admin.get(name).status_code==200
        report['checks']['frontend_assets']=True
        results={}
        for profile in ['base','campus-run2']:
            switched=admin.post('/api/v1/admin/text-profile',json={'text_profile':profile})
            switched.raise_for_status();assert switched.json()['query_cache_size']==0
            results[profile]={}
            for query in ['lhc','a dog','a quiet courtyard with curved balconies beneath evening clouds']:
                response=admin.post('/api/v1/search/text',json={'query':query,'k':5})
                response.raise_for_status();items=response.json()['items'];assert len(items)==5
                results[profile][query]=[{'id':r['id'],'caption':r['caption'],'cosine':r['cosine']} for r in items]
                assert admin.get(items[0]['thumb']).status_code==200
                assert student.get(items[0]['thumb']).status_code==401
        assert results['base']['lhc'][0]['id']!=results['campus-run2']['lhc'][0]['id']
        assert [r['id'] for r in results['base']['a dog']]==[r['id'] for r in results['campus-run2']['a dog']]
        report['search_results']=results
        report['checks']['real_gpu_search_and_toggle']=True
        # A synthetic image exercises decoding/indexing. It is withdrawn afterwards.
        image=io.BytesIO();Image.new('RGB',(96,80),(15,130,75)).save(image,format='JPEG');content=image.getvalue()
        join=student.post('/api/v1/join',json={'code':credentials['GALLERY_EVENT_CODE'],'consent':True});join.raise_for_status()
        intent=student.post('/api/v1/upload-intents',json={'client_item_id':uuid.uuid4().hex,'size':len(content),'mime':'image/jpeg'})
        intent.raise_for_status();uid=intent.json()['id']
        try:
            upload=student.put('/api/v1/uploads/'+uid+'/content',content=content,headers={'Content-Type':'image/jpeg'})
            assert upload.status_code in {200,202},upload.text
            deadline=time.monotonic()+50
            row=None
            while time.monotonic()<deadline:
                rows=admin.get('/api/v1/admin/review?filter=all').json()['items']
                row=next((r for r in rows if r['id']==uid and r['state']=='validated'),None)
                if row:break
                time.sleep(.5)
            assert row,'Photo did not validate'
            review=admin.post('/api/v1/admin/submissions/'+uid+'/review',json={'action':'approve','revision':row['revision']})
            review.raise_for_status()
            while time.monotonic()<deadline:
                own=student.get('/api/v1/me/submissions').json()['items']
                if next(r for r in own if r['id']==uid)['state']=='searchable':break
                time.sleep(.5)
            else:raise AssertionError('Approved photo was not embedded')
            report['checks']['student_upload_decode_approve_embed']=True
        finally:
            response=student.delete('/api/v1/me/submissions/'+uid);response.raise_for_status()
        assert admin.get('/api/v1/admin/status').json()['total']==252
        report['checks']['withdrawal_cleanup']=True
        report['final_status']=admin.get('/api/v1/admin/status').json()
    report['elapsed_seconds']=round(time.time()-started,2)
    report['passed']=True
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'passed':True,'gpu_name':report['gpu_name'],'checks':report['checks'],
                      'elapsed_seconds':report['elapsed_seconds'],'report':str(args.output)},indent=2))


if __name__=='__main__':main()

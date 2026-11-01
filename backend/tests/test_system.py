import asyncio
import hashlib
import io
import json
import time
import uuid
import zipfile

import httpx
import numpy as np
import pytest

from gallery.service import tokens
from gallery.importer import import_seed
from .conftest import join,upload,photo,wait_for


async def review_record(admin,upload_id):
    async def get():return (await admin.get('/api/v1/admin/review?filter=all')).json()['items']
    rows=await wait_for(get,lambda rows:any(r['id']==upload_id and r['state']=='validated' for r in rows))
    return next(r for r in rows if r['id']==upload_id)


async def approve(admin,upload_id):
    record=await review_record(admin,upload_id)
    response=await admin.post(f'/api/v1/admin/submissions/{upload_id}/review',json={'action':'approve','revision':record['revision']})
    assert response.status_code==200,response.text
    return record


async def test_seed_and_prepared_queries_are_real(bundle):
    service,student,admin,_,_=bundle
    gallery=(await admin.get('/api/v1/gallery?limit=120')).json()
    assert gallery['total']==120 and len(gallery['items'])==120
    response=await admin.post('/api/v1/search/text',json={'query':'a construction crane above an unfinished building under an orange sky'})
    assert response.status_code==200
    assert 'construction' in response.json()['items'][0]['caption']
    image=await admin.get(response.json()['items'][0]['image'])
    assert image.status_code==200 and image.headers['content-type']=='image/jpeg'
    assert image.headers['cache-control']=='no-store'


async def test_student_cannot_access_organizer_or_media(bundle):
    _,student,admin,_,admin_app=bundle
    for route in ['/presenter','/moderator','/api/v1/admin/status','/api/v1/gallery','/api/v1/admin/qr.svg','/docs']:
        assert (await student.get(route)).status_code==404
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=admin_app),base_url='http://testserver') as anonymous:
        for route in ['/api/v1/admin/status','/api/v1/gallery','/api/v1/admin/qr.svg']:
            assert (await anonymous.get(route)).status_code==401


async def test_join_consent_and_origin_protection(bundle):
    _,student,admin,_,_=bundle
    assert (await student.post('/api/v1/join',json={'code':'INDORE26','consent':False})).status_code==403
    assert (await student.post('/api/v1/join',json={'code':'wrong','consent':True})).status_code==403
    response=await student.post('/api/v1/join',json={'code':'INDORE26','consent':True},headers={'Origin':'https://evil.example'})
    assert response.status_code==403
    assert (await student.get('/',headers={'Host':'evil.example'})).status_code==400
    assert (await admin.post('/api/v1/admin/event',json={'intake':'open'},headers={'Origin':'https://evil.example'})).status_code==403


async def test_photo_requires_review_then_becomes_searchable(bundle):
    service,student,admin,_,_=bundle
    await join(student)
    upload_id,_=await upload(student)
    record=await review_record(admin,upload_id)
    asset=record['asset_id']
    assert (await admin.get(f'/api/v1/media/{asset}/thumb')).status_code==404
    assert (await admin.get('/api/v1/gallery?collection=live')).json()['total']==0
    await approve(admin,upload_id)
    async def mine():return (await student.get('/api/v1/me/submissions')).json()['items']
    await wait_for(mine,lambda values:values[0]['state']=='searchable')
    assert (await admin.get('/api/v1/gallery?collection=live')).json()['total']==1
    assert (await admin.get(f'/api/v1/media/{asset}/thumb')).status_code==200


async def test_quota_and_idempotent_retry(bundle):
    _,student,admin,_,_=bundle
    await join(student)
    data=photo();key=uuid.uuid4().hex
    first,_=await upload(student,data,key)
    repeat=await student.post('/api/v1/upload-intents',json={'client_item_id':key,'size':len(data),'mime':'image/jpeg'})
    assert repeat.json()['id']==first and repeat.json()['reused']
    assert (await student.put(f'/api/v1/uploads/{first}/content',content=data)).status_code==200
    conflict=await student.post('/api/v1/upload-intents',json={'client_item_id':key,'size':len(data)+1,'mime':'image/jpeg'})
    assert conflict.status_code==409
    quota=await student.post('/api/v1/upload-intents',json={'client_item_id':uuid.uuid4().hex,'size':len(data),'mime':'image/jpeg'})
    assert quota.status_code==429


async def test_interrupted_bytes_retry_without_losing_slot(bundle):
    _,student,_,_,_=bundle
    await join(student);data=photo()
    intent=(await student.post('/api/v1/upload-intents',json={'client_item_id':uuid.uuid4().hex,'size':len(data),'mime':'image/jpeg'})).json()
    response=await student.put(f"/api/v1/uploads/{intent['id']}/content",content=data[:20])
    assert response.status_code==422
    response=await student.put(f"/api/v1/uploads/{intent['id']}/content",content=data)
    assert response.status_code==202


async def test_oversized_and_untrusted_file_bytes(bundle):
    _,student,_,_,_=bundle
    await join(student)
    response=await student.post('/api/v1/upload-intents',json={'client_item_id':uuid.uuid4().hex,'size':3*1024*1024,'mime':'image/jpeg'})
    assert response.status_code==413
    upload_id,_=await upload(student,b'not an image')
    async def mine():return (await student.get('/api/v1/me/submissions')).json()['items']
    values=await wait_for(mine,lambda values:values[0]['state']=='invalid')
    assert values[0]['error']


async def test_parallel_review_has_optimistic_conflict(bundle):
    _,student,admin,_,_=bundle
    await join(student);upload_id,_=await upload(student)
    record=await review_record(admin,upload_id)
    route=f'/api/v1/admin/submissions/{upload_id}/review'
    results=await asyncio.gather(admin.post(route,json={'action':'approve','revision':record['revision']}),
                                 admin.post(route,json={'action':'hide','revision':record['revision']}))
    assert sorted(r.status_code for r in results)==[200,409]


async def test_withdraw_during_embedding_cannot_revive_photo(bundle):
    service,student,admin,_,_=bundle
    await join(student);upload_id,_=await upload(student)
    original=service.encoder.images
    def slow(paths):time.sleep(.3);return original(paths)
    service.encoder.images=slow
    record=await approve(admin,upload_id)
    await asyncio.sleep(.1)
    assert (await student.delete(f'/api/v1/me/submissions/{upload_id}')).status_code==200
    await asyncio.sleep(.5)
    assert (await admin.get('/api/v1/gallery?collection=live')).json()['total']==0
    assert (await admin.get(f"/api/v1/media/{record['asset_id']}/full")).status_code==404
    assert (await student.get('/api/v1/me/submissions')).json()['items'][0]['state']=='withdrawn'


async def test_duplicate_content_keeps_independent_consent(bundle):
    service,student,admin,public,_=bundle
    await join(student);first,_=await upload(student,photo('blue'))
    await approve(admin,first)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=public),base_url='http://testserver') as other:
        await join(other);second,_=await upload(other,photo('blue'))
        await approve(admin,second)
        await wait_for(lambda:service.gallery('live'),lambda result:result['total']==1)
        assert (await student.delete(f'/api/v1/me/submissions/{second}')).status_code==404
        await student.delete(f'/api/v1/me/submissions/{first}')
        assert (await admin.get('/api/v1/gallery?collection=live')).json()['total']==1
        await other.delete(f'/api/v1/me/submissions/{second}')
        assert (await admin.get('/api/v1/gallery?collection=live')).json()['total']==0


async def test_hidden_photo_removed_from_search_map_and_media(bundle):
    service,_,admin,_,_=bundle
    item=(await admin.get('/api/v1/gallery')).json()['items'][0]
    assert (await admin.post(f"/api/v1/admin/assets/{item['id']}/hide")).status_code==200
    assert (await admin.get(item['image'])).status_code==404
    assert item['id'] not in [p['id'] for p in (await admin.get('/api/v1/gallery/map')).json()['points']]
    assert (await admin.get('/api/v1/gallery')).json()['total']==119


async def test_intake_pause_does_not_drop_received_photos(bundle):
    _,student,admin,_,_=bundle
    await join(student);upload_id,_=await upload(student)
    await admin.post('/api/v1/admin/event',json={'intake':'paused'})
    assert (await student.get('/api/v1/me/submissions')).json()['items'][0]['id']==upload_id
    assert (await student.post('/api/v1/upload-intents',json={'client_item_id':uuid.uuid4().hex,'size':10,'mime':'image/jpeg'})).status_code==409


async def test_finish_keeps_seed_removes_attendee_access(bundle):
    service,student,admin,_,_=bundle
    await join(student);upload_id,_=await upload(student)
    await approve(admin,upload_id)
    assert (await admin.post('/api/v1/admin/finish',json={'confirm':'wrong'})).status_code==422
    assert (await admin.post('/api/v1/admin/finish',json={'confirm':'DELETE STUDENT PHOTOS'})).status_code==200
    assert (await student.get('/api/v1/me/submissions')).status_code==401
    assert (await admin.get('/api/v1/gallery')).json()['total']==120


async def test_qr_encodes_actual_student_entry_and_cookie_auth(bundle):
    _,student,admin,_,_=bundle
    qr=await admin.get('/api/v1/admin/qr.svg')
    assert qr.status_code==200 and '<svg' in qr.text
    assert (await student.get('/e/workshop?code=INDORE26')).status_code==200
    assert (await student.get('/assets/upload.js')).status_code==200
    assert 'httponly' in (await student.post('/api/v1/join',json={'code':'INDORE26','consent':True})).headers['set-cookie'].lower()


async def test_json_body_is_bounded_and_malicious_tags_are_data(bundle):
    _,_,admin,_,_=bundle
    assert (await admin.post('/api/v1/search/text',content=b'{"query":"'+b'x'*70000+b'"}',headers={'Content-Type':'application/json'})).status_code==413
    item=(await admin.get('/api/v1/gallery')).json()['items'][0]
    payload='<script>alert(1)</script> खाना'
    assert (await admin.put(f"/api/v1/admin/assets/{item['id']}/tags",json={'tags':payload})).status_code==200
    assert 'खाना' in tokens(payload)


async def test_seed_zip_traversal_rejected(tmp_path):
    path=tmp_path/'bad.zip'
    with zipfile.ZipFile(path,'w') as z:z.writestr('../escape','oops')
    with pytest.raises(ValueError,match='Unsafe'):
        import_seed(path,tmp_path/'data')
    assert not (tmp_path/'escape').exists()
